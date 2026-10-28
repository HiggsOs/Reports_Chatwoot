# Panel de auditorías de calidad — Plan general

Fecha: 2026-10-28
Estado: propuesto

## 1. Problema

Hoy la aplicación genera CSV a pedido contra las APIs de Chatwoot, Ringover y
CloudTalk. No guarda nada salvo `asesores.csv` y una caché de archivos, así que
no permite:

- Escuchar una llamada desde el panel.
- Saber qué persona atendió una llamada cuando la cuenta del asesor es
  compartida: varias personas usan la misma cuenta, cada una en una o dos
  franjas horarias.
- Ver todo lo que pasó con un cliente (chats y llamadas) a partir de su número.
- Calificar la calidad de cada asesor y descargar un reporte de esas
  auditorías.

## 2. Alcance

**Incluye:**

- Base de datos PostgreSQL con personas, cuentas, franjas, clientes, llamadas,
  conversaciones y auditorías.
- Sincronización periódica de CloudTalk, Ringover y Chatwoot hacia la base.
- Asignación de cada llamada y conversación a la persona real según la franja.
- Traza por número de teléfono del cliente.
- Escucha de grabaciones bajo demanda, con guardado en MP3 en el FTP de las
  llamadas escuchadas.
- Fichas de auditoría configurables, pantalla de auditoría y reporte
  descargable.
- Varios usuarios con rol.

**No incluye (por ahora):** transcribir llamadas con un motor propio, puntuar
de forma automática con IA, enviar reportes por correo, ni que los asesores
entren a ver su propia nota. La arquitectura no impide agregarlos después.

## 3. Decisiones tomadas

| Decisión | Elección | Motivo |
|---|---|---|
| Base de datos | PostgreSQL | Varios usuarios escribiendo a la vez; EasyPanel lo levanta como servicio |
| ORM | SQLAlchemy 2.x (estilo tipado `Mapped[...]`) | Estándar en Python; separa el modelo de la consulta |
| Migraciones | Alembic | Acompaña a SQLAlchemy; el esquema evoluciona sin perder datos |
| Validación y tipos | Pydantic v2 | Esquemas de entrada y salida, y configuración por variables de entorno (`pydantic-settings`) |
| Interfaz | Streamlit (se mantiene) | Se reutiliza lo existente; alcanza para un equipo interno |
| CSV | Solo como **descarga**; nada se guarda en CSV | `asesores.csv` se migra a la base una vez y deja de usarse |
| Zona horaria de las franjas | `Europe/Madrid` | Los turnos se definen en hora de España |
| Almacenamiento de fechas | `timestamptz` en UTC | La zona se aplica solo al mostrar o al evaluar franjas |
| País por defecto de los teléfonos | España (`+34`) | La mayoría de las llamadas son en España |
| Normalización de teléfonos | Librería `phonenumbers`, formato E.164 | Evita reglas a mano por país |
| Audio | Mixto: bajo demanda; se guarda en MP3 lo que se escucha | Poco espacio y la evidencia de cada auditoría queda guardada |
| Almacén de audio | FTP del hosting contratado, con FTPS si está disponible | Ya está pago por un año |
| Rutas de audio | Relativas al directorio del FTP | Permite cambiar de servidor sin tocar la base |

## 4. Arquitectura

```
┌──────────────────────── Frontend ─────────────────────────┐
│ Streamlit multipágina (st.navigation)                      │
│ login · asesores · franjas · historial · auditoría · ...   │
└───────────────┬────────────────────────────────────────────┘
                │ solo llama a servicios (nunca SQL directo)
┌───────────────┴──────────────── Backend ──────────────────┐
│ servicios/   lógica de negocio, recibe y devuelve Pydantic │
│ db/          modelos SQLAlchemy, sesión, Alembic           │
│ clientes/    chatwoot.py, ringover.py, cloudtalk.py        │
│ audio/       conversión a MP3 y almacén FTP                │
│ sync/        proceso aparte que llena la base              │
└───────────────┬───────────────────────────┬────────────────┘
                │                           │
         PostgreSQL                    Servidor FTP
```

Se despliegan **tres servicios en EasyPanel** con la misma imagen Docker:

1. `app`: Streamlit (como hoy).
2. `sync`: el mismo código con otro comando (`python -m sync`), que corre la
   sincronización cada cierto tiempo.
3. `postgres`: el servicio de base de datos de EasyPanel.

El núcleo no importa Streamlit, igual que hoy: el frontend se puede cambiar
después (por ejemplo a FastAPI + React) sin reescribir el backend.

## 5. Backend

### 5.1 Estructura de carpetas

```
app/
  config.py            # Settings de pydantic-settings
  db/
    base.py            # engine, SessionLocal, Base
    modelos.py         # tablas SQLAlchemy
    migraciones/       # Alembic
  esquemas/            # modelos Pydantic de entrada/salida
  clientes/            # chatwoot.py, ringover.py, cloudtalk.py (los actuales)
  servicios/
    personas.py        # personas, cuentas, franjas
    asignacion.py      # llamada/conversación → persona
    telefonos.py       # normalización
    clientes.py        # historial por número
    audio.py           # flujo de escucha y guardado
    auditorias.py      # fichas, auditorías, puntajes
    reportes.py        # armado de reportes y exportación
    usuarios.py        # usuarios del panel y roles
  audio/
    conversion.py      # WAV → MP3 con ffmpeg
    almacen_ftp.py     # subir, bajar, existe
  sync/
    __main__.py        # bucle del proceso de sincronización
    cloudtalk.py
    ringover.py
    chatwoot.py
  ui/                  # frontend (sección 6)
tests/
```

Los módulos actuales (`chatwoot.py`, `ringover.py`, `cloudtalk.py` y los
`reporte_*.py`) se mueven a `clientes/` y `servicios/` sin cambiar su lógica.
Sus pruebas se conservan.

### 5.2 Modelo de datos

```
usuarios ─────────────┐
                      │ auditor
personas ──┬── franjas ──┐                 fichas ── criterios
  │        │             │                    │          │
  │     cuentas ─────────┘                    │          │
  │        │                                  │          │
  │        ├── llamadas ──────┬── auditorias ─┘── puntajes
  │        │                  │
  │        └── conversaciones ┘
  │                  │
  └── (persona asignada en llamadas y conversaciones)

clientes ── llamadas / conversaciones (por teléfono)
```

| Tabla | Campos principales | Notas |
|---|---|---|
| `usuarios` | id, usuario, nombre, hash_contraseña, rol, activo | Roles: `admin`, `auditor`, `supervisor` (sección 5.8) |
| `personas` | id, nombre, correo, área (`Comercial`/`RDC`), activa | El asesor real; reemplaza a `asesores.csv` |
| `cuentas` | id, plataforma (`cloudtalk`/`ringover`/`chatwoot`), id_externo, nombre, correo, compartida, persona_id | Si no es compartida, `persona_id` es su único dueño |
| `franjas` | id, cuenta_id, persona_id, día_semana (0–6), hora_inicio, hora_fin, vigente_desde, vigente_hasta | Horas en `Europe/Madrid`. Sin superposición por cuenta (restricción `EXCLUDE` de Postgres) |
| `clientes` | id, teléfono_e164, teléfono_original, nombre, revisar | `revisar` marca números que no se pudieron normalizar |
| `llamadas` | id, plataforma, id_externo, cuenta_id, cliente_id, persona_id, asignación (`franja`/`dueño`/`manual`/`sin_asignar`), inicio, duración, dirección, estado, transcripción (JSONB), enlace_plataforma, audio_estado, audio_ruta | Único por (plataforma, id_externo) |
| `conversaciones` | id, id_externo, inbox, cuenta_id, cliente_id, persona_id, asignación, inicio, cierre, estado, etiquetas, dirección, área | Los mensajes se guardan aparte o en JSONB |
| `fichas` | id, nombre, versión, activa | Las fichas se versionan: una auditoría vieja conserva su ficha |
| `criterios` | id, ficha_id, nombre, descripción, peso, puntaje_máx, crítico | Un criterio crítico en cero anula la nota |
| `auditorias` | id, ficha_id, llamada_id o conversación_id, persona_id, auditor_id, fecha, nota_final, comentario, estado (`borrador`/`cerrada`) | `persona_id` se copia al cerrar: si luego se reasigna la llamada, la auditoría no cambia |
| `puntajes` | auditoría_id, criterio_id, puntaje, comentario | |

Todas las tablas llevan `creado_en` y `actualizado_en`.

### 5.3 Asignación a la persona real

Función pura `asignar(cuenta, inicio_utc, franjas) -> (persona_id, tipo)`:

1. Si la llamada tiene una asignación `manual`, no se toca nunca.
2. Si la cuenta no es compartida, se asigna a su dueño (`dueño`).
3. Si es compartida, `inicio_utc` se convierte a `Europe/Madrid` y se busca la
   franja vigente de esa cuenta que contenga ese día y esa hora (`franja`).
4. Si no hay franja, queda `sin_asignar`.

Cuando se crea o edita una franja, se reasignan las llamadas de esa cuenta en
el período afectado que no sean `manual`. Las pruebas cubren: dentro de cada
franja, el corte entre dos franjas, los bordes exactos (inicio incluido, fin
excluido), el cambio de vigencia y los cambios de horario de verano en España.

### 5.4 Teléfonos

`normalizar(texto) -> (e164 | None, revisar: bool)` con `phonenumbers` y
región `ES` por defecto. Si el número trae código de país, se respeta. Si no
se puede interpretar, se guardan solo los dígitos y se marca `revisar`.

Origen del teléfono del cliente:

- CloudTalk: `Contact.contact_numbers` del historial de llamadas.
- Ringover: número de origen o de destino de `GET /calls`, según la dirección.
- Chatwoot: `meta.sender.phone_number` de la conversación.

### 5.5 Sincronización (`sync`)

Proceso aparte que corre cada N minutos (`SYNC_INTERVALO_MINUTOS`):

- Cada plataforma guarda su último punto sincronizado; cada ciclo trae solo
  lo nuevo, con un margen de solapamiento para no perder registros tardíos.
- Escribe con *upsert* por (plataforma, id_externo): repetir un ciclo no
  duplica nada.
- CloudTalk: historial de llamadas → transcripción de las grabadas. Respeta el
  límite de 60 peticiones por minuto, como hoy.
- Ringover: transcripciones y `GET /calls` (para dirección y número).
- Chatwoot: conversaciones con su asesor, inbox, etiquetas y teléfono.
- Después de guardar, aplica la asignación (5.3) y la traza por teléfono (5.4).
- Un bloqueo en Postgres (`pg_advisory_lock`) impide que corran dos ciclos a
  la vez.
- Hay una tarea aparte para cargar datos históricos de un rango a elección.

La caché de archivos actual (`DATA_DIR/cache`) deja de ser necesaria.

### 5.6 Audio

Flujo `obtener_audio(llamada) -> bytes`:

1. Si `audio_ruta` existe, se baja el MP3 del FTP.
2. Si no, se pide el WAV a la plataforma
   (CloudTalk: `GET /calls/recording/{id}.json`). `404` → `sin_grabación`;
   `410` → `vencida`. En ninguno de los dos casos se reintenta.
3. Se convierte a MP3 mono (aprox. 32 kbps) con `ffmpeg` y se devuelve para
   reproducirlo.
4. La subida al FTP corre después, en segundo plano. Si falla, el MP3 queda en
   `DATA_DIR/audio_pendiente/` y `sync` reintenta la subida.

Ruta en el FTP: `{plataforma}/{año}/{mes}/{id_externo}.mp3`, guardada en la
base relativa a `FTP_DIR`.

`enlace_plataforma` (`Cdr.recording_link` en CloudTalk) se guarda para el
botón «Abrir en CloudTalk». Solo se pide audio a CloudTalk cuando ese enlace
existe, para no gastar peticiones en llamadas sin grabación.

El endpoint de grabaciones de Ringover está pendiente de confirmar.

### 5.7 Auditorías y reportes

- Nota final = suma de (puntaje / máximo × peso) / suma de pesos × 100, salvo
  que un criterio crítico esté en cero, en cuyo caso la nota es 0.
- Una auditoría `cerrada` no se edita; solo un `admin` puede reabrirla.
- Reportes (todos con filtros de período, área y persona):
  - Detalle: una fila por auditoría con sus puntajes por criterio.
  - Resumen por persona: cantidad de auditorías, nota promedio, promedio por
    criterio y evolución mensual.
  - Exportación en Excel (`openpyxl`, una hoja por reporte) y CSV. El PDF
    queda como opcional.

### 5.8 Usuarios y roles

| Rol | Puede |
|---|---|
| `admin` | Todo: usuarios, personas, cuentas, franjas, fichas, reabrir auditorías |
| `auditor` | Escuchar llamadas, corregir asignaciones, crear y cerrar auditorías, descargar reportes |
| `supervisor` | Ver historial, auditorías y reportes; no edita |

El login sigue con `streamlit-authenticator`, pero los usuarios salen de la
tabla `usuarios`. El usuario actual de las variables de entorno se crea como
`admin` en el primer arranque.

### 5.9 Configuración nueva

| Variable | Descripción |
|---|---|
| `DATABASE_URL` | `postgresql+psycopg://usuario:clave@host:5432/base` |
| `TZ_OPERACION` | `Europe/Madrid` |
| `TELEFONO_REGION` | `ES` |
| `FTP_HOST`, `FTP_PORT`, `FTP_USER`, `FTP_PASSWORD`, `FTP_DIR` | Acceso al FTP |
| `FTP_TLS` | `true` para FTPS |
| `SYNC_INTERVALO_MINUTOS` | Frecuencia de la sincronización |

Las variables actuales se mantienen.

### 5.10 Dependencias nuevas

`sqlalchemy`, `alembic`, `psycopg[binary]`, `pydantic`, `pydantic-settings`,
`phonenumbers`, `openpyxl`. En el `Dockerfile`: el paquete del sistema
`ffmpeg`. Para las pruebas de base de datos: `testcontainers[postgres]` o un
Postgres de servicio en CI.

## 6. Frontend (Streamlit)

Aplicación multipágina con `st.navigation`; cada página se muestra según el
rol del usuario.

| Página | Rol | Contenido |
|---|---|---|
| **Inicio** | todos | Llamadas sin asignar, auditorías en borrador y última sincronización |
| **Personas** | admin | Alta, baja y edición de asesores con su área (reemplaza la pestaña Asesores) |
| **Cuentas** | admin | Cuentas de cada plataforma (se cargan solas desde `sync`); marcar compartida o elegir dueño |
| **Franjas** | admin | Por cuenta compartida: tabla editable de persona, día, inicio, fin y vigencia. Vista semanal del horario. Avisa superposiciones y muestra cuántas llamadas se reasignarían antes de guardar |
| **Sin asignar** | auditor | Bandeja de llamadas y chats sin persona, con asignación individual o en lote |
| **Llamadas** | auditor, supervisor | Lista filtrable (fecha, persona, cuenta, dirección, duración, con transcripción, auditada o no). Al abrir una llamada: reproductor, transcripción, persona asignada (editable) y botón «Auditar» |
| **Historial del cliente** | auditor, supervisor | Buscar por número. Línea de tiempo con chats y llamadas por fecha, con quién atendió cada uno. Se abre cada elemento y se audita desde ahí |
| **Auditar** | auditor | Audio y transcripción (o mensajes del chat) a la izquierda; ficha con los criterios, puntajes y comentarios a la derecha. Guardar borrador o cerrar. Muestra la nota en vivo |
| **Auditorías** | auditor, supervisor | Lista de auditorías con filtros; abrir una muestra el detalle y el audio guardado |
| **Reportes** | auditor, supervisor | Elegir período, área y persona; ver la tabla y un gráfico de evolución; descargar Excel o CSV |
| **Fichas** | admin | Crear y editar fichas y criterios (nombre, peso, puntaje máximo, crítico). Editar una ficha en uso crea una versión nueva |
| **Usuarios** | admin | Alta de usuarios del panel, rol y contraseña |
| **Exportar datos** | auditor, supervisor | Los tres CSV de hoy (Chatwoot, Ringover y CloudTalk), ahora leídos de la base |

Criterios comunes a todas las páginas:

- Las fechas y horas se muestran en `Europe/Madrid`.
- Las páginas leen de la base, nunca de las APIs, así que cargan rápido. La
  única excepción es la primera escucha de una grabación.
- El audio se cachea por sesión (`st.cache_data`) para adelantar y retroceder
  sin volver a pedirlo.

## 7. Etapas

| # | Etapa | Backend | Frontend | Resultado visible |
|---|---|---|---|---|
| 1 | Base de datos | Configuración Pydantic, SQLAlchemy, Alembic, modelos, servicio Postgres, migración de `asesores.csv` | Pestaña Asesores leyendo de la base | La app funciona igual, pero con Postgres |
| 2 | Asesores y franjas | Servicios de personas, cuentas y franjas; asignación con sus pruebas | Páginas Personas, Cuentas y Franjas | Se cargan los turnos |
| 3 | Sincronización | Proceso `sync` para las tres plataformas, teléfonos, asignación automática | Inicio, Sin asignar, Llamadas (sin audio), Exportar datos | Las llamadas y chats aparecen solos y asignados |
| 4 | Historial del cliente | Consulta por teléfono | Página Historial del cliente | Traza completa por número |
| 5 | Audio | Grabación de CloudTalk (y de Ringover), MP3, FTP, reintentos | Reproductor en Llamadas e Historial | Se escuchan las llamadas |
| 6 | Auditorías | Fichas, auditorías y cálculo de nota | Fichas, Auditar y Auditorías | Se audita |
| 7 | Reportes y usuarios | Reportes, Excel, usuarios y roles | Reportes y Usuarios | Se descarga el reporte; cada auditor tiene su usuario |

Cada etapa se entrega con pruebas y se puede desplegar por separado.

## 8. Pruebas

- Funciones puras (asignación, teléfonos, nota, armado de reportes): pruebas
  unitarias con `pytest`, como hoy.
- Servicios con base de datos: contra un Postgres real de prueba, no SQLite,
  porque se usan `EXCLUDE`, `JSONB` y `timestamptz`.
- Clientes de API y FTP: simulados (`responses` y un FTP falso).
- Migraciones: una prueba que aplica todas desde cero.

## 9. Pendientes

1. La ficha de calidad: ¿ya existe con sus criterios y pesos, o se arma?
2. ¿Hay llamadas sin transcripción que tengamos que transcribir nosotros?
3. ¿Cuánto tiempo hay que conservar los audios en el FTP?
4. ¿El FTP del hosting acepta FTPS? ¿Cuánto espacio tiene el plan?
5. ¿Cuál es el endpoint de grabaciones de Ringover?
6. ¿Alguna bandeja de Chatwoot también es compartida, y necesita franjas?
7. ¿Los roles propuestos (admin, auditor, supervisor) se ajustan al equipo?
8. ¿Cuánto tiempo guarda CloudTalk las grabaciones en el plan contratado?
