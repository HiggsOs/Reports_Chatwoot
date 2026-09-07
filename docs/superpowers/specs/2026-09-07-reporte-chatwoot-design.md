# Reporte de conversaciones de Chatwoot — Diseño

Fecha: 2026-09-07
Estado: propuesto

## 1. Problema

No existe una forma de obtener, desde Chatwoot, un reporte de conversaciones que
combine el asesor que atendió, la fecha, las etiquetas, el tiempo de resolución,
si la conversación fue entrante o saliente, la fecha de cierre y el área
(Comercial o RDC). Los reportes nativos de Chatwoot entregan métricas agregadas
por agente, no el detalle conversación por conversación.

El reporte debe poder generarlo una persona sin conocimientos técnicos, para
rangos de fechas arbitrarios, sin pedir ayuda a nadie.

## 2. Alcance

**Incluye:** aplicación web con login, selección de rango de fechas, generación
del reporte en CSV descargable, y mantenimiento del mapeo asesor → área desde la
misma interfaz. Despliegue en VPS con EasyPanel vía Dockerfile.

**No incluye:** generación automática programada, envío por correo, escritura a
Google Sheets, gestión de múltiples usuarios, gráficas o tableros. La
arquitectura no impide agregarlos después.

## 3. Decisiones tomadas

| Decisión | Elección | Motivo |
|---|---|---|
| Origen de datos | API REST de Chatwoot | Portable entre Cloud y self-hosted; no acopla al esquema interno de la base de datos |
| Área Comercial/RDC | Mapeo por email del asesor | Cada asesor pertenece de forma fija a un área |
| Formato de salida | CSV | Suficiente para filtrar y compartir |
| Rango de fechas | Elegido por el usuario en cada consulta | Necesitan períodos a la medida, no solo el mes cerrado |
| Interfaz | Streamlit | Interfaz web con calendarios y descarga, con muy poco código |
| Autenticación | Usuario único compartido | La app queda expuesta a internet detrás del dominio de EasyPanel |
| Despliegue | Dockerfile en EasyPanel | Es el flujo nativo del panel; HTTPS y dominio automáticos |

## 4. Arquitectura

Dos capas, separadas de forma estricta:

```
┌─────────────────────────────────────┐
│ app.py — Streamlit                  │  login, calendarios, tabla,
│                                     │  descarga, edición de asesores
└──────────────┬──────────────────────┘
               │ llama funciones puras
┌──────────────┴──────────────────────┐
│ reporte.py — armado de filas y CSV  │
│ chatwoot.py — cliente de la API     │
└─────────────────────────────────────┘
```

El núcleo (`chatwoot.py`, `reporte.py`) no importa Streamlit ni conoce la
existencia de una interfaz. Recibe fechas y devuelve filas. Esto permite
probarlo de forma aislada y reutilizarlo si más adelante se agrega ejecución
programada o envío automático.

### Estructura de archivos

```
reportes-chatwoot/
├── app.py                 # interfaz Streamlit y login
├── chatwoot.py            # cliente HTTP de la API de Chatwoot
├── reporte.py             # transformación a filas y escritura de CSV
├── config.py              # lectura y validación de variables de entorno
├── Dockerfile
├── requirements.txt
├── .env.example
├── .dockerignore
├── tests/
│   ├── test_reporte.py    # armado de filas con respuestas de API fijas
│   └── test_chatwoot.py   # paginación y reintentos con HTTP simulado
└── /data/                 # volumen persistente (no versionado)
    ├── asesores.csv
    └── cache/
```

## 5. Obtención de datos

### 5.1 Listado de conversaciones

`POST /api/v1/accounts/{account_id}/conversations/filter?page=N`

Encabezado `api_access_token`. Filtro por `created_at` entre las fechas
seleccionadas (convertidas a epoch), con `status: all` para incluir abiertas,
pendientes y resueltas. Se pagina hasta recibir una página vacía.

De cada conversación se toma: `id`, `meta.assignee` (nombre y email),
`created_at`, `labels`, `status`, `inbox_id`.

### 5.2 Dirección y fecha de cierre

`GET /api/v1/accounts/{account_id}/conversations/{id}/messages`

Una llamada por conversación, que resuelve dos columnas a la vez:

- **Dirección**: el mensaje más antiguo cuyo `message_type` sea 0 (incoming) o 1
  (outgoing). Si es 0 → `Entrante`; si es 1 → `Saliente`. Si la conversación no
  tiene ningún mensaje de esos tipos → `Indeterminado`.
- **Fecha de cierre**: el mensaje de actividad (`message_type` 2) más reciente
  que corresponda a una resolución.

Los mensajes se paginan hacia atrás con el parámetro `before`, usando el id del
mensaje más antiguo recibido.

### 5.3 Limitación conocida — fecha de cierre y tiempo de resolución

La API de Chatwoot **no expone** un campo `closed_at` ni un tiempo de resolución
por conversación individual; solo entrega promedios por agente en los endpoints
de reportes. Por lo tanto:

- `fecha_cierre` se deriva del mensaje de actividad de resolución.
- `tiempo_resolucion_horas` se calcula como `fecha_cierre - fecha_creacion`.

El texto del mensaje de actividad depende del idioma configurado en Chatwoot. La
detección usa una expresión regular que cubre español e inglés
(`resolved|resuelta|resuelto`). Se aplica un respaldo en cascada:

1. Si se encuentra el mensaje de actividad de resolución, se usa su fecha.
2. Si no se encuentra pero el estado de la conversación es `resolved`, se usa
   `last_activity_at` y la fila se marca en la columna `cierre_aproximado`.
3. Si la conversación no está resuelta, `fecha_cierre` y
   `tiempo_resolucion_horas` quedan vacíos.

Si una conversación se reabre y se vuelve a resolver, se toma la resolución más
reciente.

### 5.4 Resiliencia y rendimiento

- **Reintentos**: ante HTTP 429 y 5xx, hasta 5 reintentos con espera
  exponencial, respetando el encabezado `Retry-After` cuando venga.
- **Caché**: las respuestas de mensajes de conversaciones ya resueltas se
  guardan en `/data/cache/` indexadas por id de conversación. Las conversaciones
  abiertas nunca se cachean, porque todavía pueden cambiar.
- **Progreso**: la interfaz muestra una barra de progreso durante el paso 5.2,
  que es el más lento (una llamada por conversación).

## 6. Mapeo asesor → área

`/data/asesores.csv` con dos columnas: `email_asesor,area`, donde `area` es
`Comercial` o `RDC`.

- El archivo se edita desde la pestaña *Asesores* de la interfaz, con una tabla
  editable. Al guardar se reescribe el CSV en el volumen.
- Un asesor no presente en el archivo produce `SIN_MAPEAR` en la columna `area`;
  la fila **no** se descarta. La interfaz muestra un aviso listando los correos
  sin mapear al terminar de generar el reporte.
- Una conversación sin asesor asignado produce `asesor` y `email_asesor` vacíos
  y `area` en `SIN_ASIGNAR`.
- La comparación de correos es insensible a mayúsculas y espacios.

## 7. Formato del reporte

CSV codificado en UTF-8 con BOM, para que Excel en Windows lo abra con los
acentos correctos.

| Columna | Descripción |
|---|---|
| `conversacion_id` | Identificador en Chatwoot |
| `asesor` | Nombre del agente asignado |
| `email_asesor` | Correo del agente asignado |
| `area` | `Comercial`, `RDC`, `SIN_MAPEAR` o `SIN_ASIGNAR` |
| `fecha_creacion` | `YYYY-MM-DD HH:MM` |
| `etiquetas` | Etiquetas separadas por `;` |
| `direccion` | `Entrante`, `Saliente` o `Indeterminado` |
| `estado` | `abierta`, `pendiente`, `resuelta`, `pospuesta` |
| `fecha_cierre` | `YYYY-MM-DD HH:MM`, vacío si no está resuelta |
| `tiempo_resolucion_horas` | Decimal con un decimal, vacío si no está resuelta |
| `cierre_aproximado` | `Sí` cuando aplicó el respaldo de la sección 5.3 |

Todas las fechas se convierten de epoch UTC a `America/Bogota` antes de mostrar
o escribir. El rango elegido por el usuario se interpreta también en hora de
Colombia: `--desde` incluye desde las 00:00 de ese día y `--hasta` incluye hasta
las 23:59 del día indicado.

## 8. Interfaz

**Pantalla de login.** Si no hay sesión válida, se muestra únicamente el
formulario y el resto de la aplicación no se ejecuta. Un solo usuario
compartido; contraseña almacenada como hash bcrypt en variable de entorno, nunca
en texto plano ni en el repositorio. Se usa `streamlit-authenticator` por su
cookie firmada, que evita reingresar la contraseña en cada recarga de página.

**Pestaña Reporte.** Dos selectores de fecha (por defecto, el mes en curso),
botón *Generar reporte*, barra de progreso, vista previa de la tabla en pantalla
y botón de descarga del CSV. El nombre del archivo se arma solo:
`reporte-chatwoot-YYYY-MM-DD-a-YYYY-MM-DD.csv`.

**Pestaña Asesores.** Tabla editable del mapeo, con validación de que `area` sea
`Comercial` o `RDC` y de que no haya correos repetidos. Botón de guardar.

Los mensajes de error se muestran en español y en términos entendibles: si el
token es inválido, si Chatwoot no responde, o si el rango de fechas no tiene
conversaciones.

## 9. Despliegue

**Dockerfile** de una sola etapa sobre `python:3.12-slim`: instala
`requirements.txt`, copia el código, expone el puerto `8501` y arranca Streamlit
con `--server.address=0.0.0.0` y `--server.headless=true`.

**Volumen persistente** montado en `/data`. Es obligatorio: EasyPanel recrea el
contenedor en cada despliegue, y sin el volumen se perderían el mapeo de
asesores y la caché en cada actualización. Al arrancar, si `/data/asesores.csv`
no existe, se crea vacío con solo los encabezados.

**Variables de entorno**, configuradas en EasyPanel y nunca dentro de la imagen:

| Variable | Descripción |
|---|---|
| `CHATWOOT_BASE_URL` | Ej. `https://chat.miempresa.com` |
| `CHATWOOT_ACCOUNT_ID` | Id numérico de la cuenta |
| `CHATWOOT_API_TOKEN` | Token de acceso de un usuario administrador |
| `APP_USERNAME` | Usuario del login |
| `APP_PASSWORD_HASH` | Hash bcrypt de la contraseña |
| `APP_COOKIE_KEY` | Cadena aleatoria para firmar la cookie de sesión |
| `TZ` | `America/Bogota` |

Se incluye un pequeño comando auxiliar para generar el hash bcrypt de la
contraseña, de modo que no haya que calcularlo a mano.

Al arrancar, la aplicación valida que todas las variables estén presentes y
falla de inmediato con un mensaje claro si falta alguna, en lugar de fallar más
tarde a mitad de una consulta.

## 10. Pruebas

- `test_reporte.py`: armado de filas a partir de respuestas de API fijas —
  detección de dirección, resolución del área, los tres caminos de la fecha de
  cierre (5.3), conversación sin asesor, asesor sin mapear, conversación
  reabierta y resuelta dos veces, conversación sin mensajes.
- `test_chatwoot.py`: paginación de conversaciones y de mensajes, reintento ante
  429 respetando `Retry-After`, y error claro ante token inválido. Sin llamadas
  reales a la red.
- Verificación manual contra la instancia real de Chatwoot con un rango corto,
  comparando el conteo de conversaciones contra lo que muestra la interfaz de
  Chatwoot.

## 11. Riesgos

| Riesgo | Mitigación |
|---|---|
| Cambio de idioma en Chatwoot rompe la detección de la fecha de cierre | La expresión regular cubre español e inglés; el respaldo con `last_activity_at` evita perder la fila, y `cierre_aproximado` deja visible cuándo ocurrió |
| Rango de fechas muy amplio hace lenta la consulta | Caché en disco, barra de progreso y aviso en pantalla cuando el rango supera 90 días |
| Cambios en la API de Chatwoot entre versiones | El cliente HTTP está aislado en `chatwoot.py`; el resto no se entera |
| Fuga del token si el repositorio se hace público | El token solo vive en variables de entorno de EasyPanel; `.env` está en `.gitignore` y en `.dockerignore` |
