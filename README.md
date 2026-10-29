# Reportes

Aplicación web que genera, para el rango de fechas que se elija, tres CSV:

- **Conversaciones de Chatwoot**: asesor, fecha, canal, etiquetas, tiempo de
  resolución, si fue entrante o saliente, fecha de cierre y área (Comercial o
  RDC).
- **Transcripciones de Ringover**: una fila por llamada con `call_id`, agente,
  fecha, duración, estado de la transcripción y el diálogo completo.
- **Transcripciones de CloudTalk**: una fila por llamada contestada con
  `call_id`, agente, fecha, dirección, duración, estado y el diálogo completo.

La columna `canal` trae el nombre del inbox por el que entró la conversación
—por ejemplo el número de WhatsApp concreto—, no el tipo de canal, para que se
distingan entre sí varias bandejas del mismo tipo.

## Uso

Se entra con usuario y contraseña. Hay cuatro pestañas:

- **Reporte**: elegir *Desde* y *Hasta*, presionar *Generar reporte* y descargar
  el CSV.
- **Transcripciones**: mismo flujo, contra la API de Ringover. La pestaña solo
  pide datos si está configurado `RINGOVER_API_TOKEN`.
- **CloudTalk**: mismo flujo, contra la API de CloudTalk. Solo pide datos si
  están configurados `CLOUDTALK_API_KEY_ID` y `CLOUDTALK_API_KEY_SECRET`.
- **Asesores**: mantener la lista de correo → área, guardada en PostgreSQL. Un
  asesor que no esté en la lista aparece como `SIN_MAPEAR` en el reporte.
  Quitar un asesor de la lista no lo borra de la base: lo desactiva, y si se
  vuelve a agregar se reactiva.

## Variables de entorno

| Variable | Descripción |
|---|---|
| `CHATWOOT_BASE_URL` | Ej. `https://chat.miempresa.com` |
| `CHATWOOT_ACCOUNT_ID` | Id numérico de la cuenta |
| `CHATWOOT_API_TOKEN` | Token de acceso de un usuario administrador |
| `APP_USERNAME` | Usuario del login |
| `APP_PASSWORD_HASH` | Hash bcrypt de la contraseña |
| `APP_COOKIE_KEY` | Cadena aleatoria para firmar la cookie de sesión |
| `DATABASE_URL` | Conexión a PostgreSQL, por ejemplo `postgres://usuario:clave@host:5432/base`. Se aceptan `postgres://`, `postgresql://` y `postgresql+psycopg://` |
| `RINGOVER_API_TOKEN` | Token público de Ringover, con el permiso `Calls Read`. Opcional: sin él, la pestaña de transcripciones queda inactiva |
| `RINGOVER_BASE_URL` | Por defecto `https://public-api.ringover.com/v2`; usar el servidor de EE. UU. si la cuenta está allá |
| `CLOUDTALK_API_KEY_ID` | Id de la clave de API de CloudTalk (Dashboard → Account → Settings → API Keys). Opcional |
| `CLOUDTALK_API_KEY_SECRET` | Secreto de esa misma clave. Opcional: sin el par, la pestaña de CloudTalk queda inactiva |
| `DATA_DIR` | Ruta de los datos persistentes (por defecto `/data`) |
| `TZ` | `America/Bogota` |

Para generar el hash de la contraseña:

```bash
python generar_hash.py 'la-contraseña-elegida'
```

## Despliegue en EasyPanel

1. Crear un servicio de tipo **Postgres** en el mismo proyecto y copiar su
   URL de conexión interna.
2. Crear un servicio de tipo App apuntando a este repositorio (usa el
   `Dockerfile`).
3. **Montar un volumen persistente en `/data`.** Sin esto se pierde la caché en
   cada despliegue.
4. Cargar las variables de entorno de la tabla anterior, con `DATABASE_URL`
   apuntando al servicio Postgres.
5. Asignar el dominio. EasyPanel gestiona el HTTPS.

Al arrancar, el contenedor aplica las migraciones pendientes
(`alembic upgrade head`) antes de levantar la app. Si la base no responde, el
contenedor no arranca.

### Paso de `asesores.csv` a la base de datos

La primera vez que la app arranca con la base vacía, copia
`DATA_DIR/asesores.csv` a la tabla `personas` y renombra el archivo a
`asesores.csv.migrado`, que queda como respaldo y ya no se lee. Las filas con un
área que no sea `Comercial` ni `RDC` no se importan; la pestaña **Asesores**
las muestra en un aviso para cargarlas a mano. Si la base ya tenía asesores, el
archivo no se importa (la base manda), pero se renombra igual.

## Desarrollo

```bash
pip install -r requirements.txt
```

```bash
alembic upgrade head
```

```bash
streamlit run app.py
```

`alembic upgrade head` y la app leen `DATABASE_URL`. Las pruebas de base de
datos corren contra un PostgreSQL real indicado en `TEST_DATABASE_URL`, y se
saltan si no está definida. **Esa base se vacía en cada corrida**, así que su
nombre tiene que contener `test`:

```bash
TEST_DATABASE_URL=postgresql://usuario:clave@localhost:5432/panel_test python -m pytest
```

Para cambiar el esquema: editar `panel/db/modelos.py`, generar la migración y
revisarla antes de confirmarla. Una migración ya aplicada no se edita: se
escribe otra.

```bash
alembic revision --autogenerate -m "descripcion del cambio"
```

La prueba `test_los_modelos_coinciden_con_las_migraciones` falla si un modelo
cambió sin su migración.

## Nota sobre la fecha de cierre

La API de Chatwoot no expone un campo de fecha de cierre por conversación. La
fecha se deduce del evento de resolución en el hilo de mensajes. Cuando ese
evento no se puede identificar, se usa la última actividad como aproximación y
la fila queda marcada con `cierre_aproximado = Sí`. El detalle está en la
sección 5.3 de `docs/superpowers/specs/2026-09-07-reporte-chatwoot-design.md`.

## Notas sobre las transcripciones

El equipo debe tener habilitada la función de transcripciones en Ringover: el
endpoint no depende de los permisos del token sino de ese ajuste, y responde
`401` cuando está apagado.

Ringover trae el texto completo de cada llamada en la misma respuesta, así que
la API limita cada página a 100 filas. El cliente pagina con `limit_offset`
hasta agotar el rango; un mes con muchas llamadas tarda varios minutos.

El nombre del agente sale del usuario dueño de la llamada que devuelve la API,
no de una lista fija: si entra un asesor nuevo, aparece solo.

En el diálogo, cada intervención se atribuye por el `channelId`: `0` es quien
recibe la llamada y `1` quien la emite. Cuál de los dos es el agente depende de
si la llamada fue entrante o saliente, y eso la API de transcripciones no lo
dice: se consulta aparte en el registro de llamadas (`GET /calls`), una vez por
reporte. Por eso el token necesita también el permiso **Calls Read**; sin él el
reporte se genera igual, con un aviso, suponiendo que todas las llamadas son
entrantes.

`GET /calls` no acepta rangos de más de 15 días, así que el rango se consulta
por ventanas, y se pagina con el cursor `last_id_returned`, que no tiene el
tope de 9000 filas del desplazamiento.

La columna `fecha` está en hora local (`America/Bogota`), igual que el reporte de
Chatwoot, aunque Ringover la entregue en UTC.

## Notas sobre CloudTalk

Las transcripciones salen de *Conversation Intelligence*, que la cuenta debe
tener contratado. Esa API vive en `api.cloudtalk.io/v1`, aparte del resto
(`my.cloudtalk.io/api`); ambas usan la misma clave con autenticación Basic.

CloudTalk no tiene un listado de transcripciones por fecha. El reporte trae
primero el historial de llamadas contestadas del rango
(`GET /calls/index.json?status=answered`) y después pide la transcripción de
cada llamada grabada (`GET /ai/calls/{id}/transcription`). Como eso es una
petición por llamada y la API admite 60 peticiones por minuto, el cliente
espacia las peticiones a una por segundo y las
transcripciones ya descargadas se guardan en `DATA_DIR/cache/cloudtalk/`: la
primera consulta de un mes tarda alrededor de un minuto por cada 60 llamadas
grabadas; las siguientes son rápidas. La barra de progreso muestra cuánto falta
aproximadamente: arranca con el ritmo de una petición por segundo y se ajusta
con el ritmo real, pausas incluidas; las llamadas que ya están en caché no
suman tiempo. Si aun así CloudTalk responde `429` (por ejemplo, porque otra
integración usa la misma clave), el cliente espera lo que indique
`Retry-After` —o un minuto completo si no lo indica—, alarga el intervalo
entre peticiones hasta 6 s y reintenta durante varios minutos antes de
rendirse. Si un reporte se corta, lo ya descargado queda en caché y el
siguiente intento sigue desde ahí.

### Filtros

La pestaña tiene un panel **Filtros** que se aplica antes de descargar las
transcripciones, así que además de acotar el CSV acorta la espera:

- **Agentes**, **Grupos** y **Números de la empresa**: listas que se llenan con
  `GET /agents`, `/groups` y `/numbers` y se guardan una hora. El grupo se
  compara con los grupos del agente que trae cada llamada en el historial.
- **Dirección**: entrante (inbound), saliente (outbound) o interna.
- **Duración mínima**: descarta cuelgues y buzones.
- **Cliente**: busca en el nombre y la empresa del contacto, o en su teléfono
  comparando solo dígitos (mínimo 4).
- **Solo llamadas con transcripción**: no consulta las llamadas sin grabación y
  quita del CSV las que no tienen texto.

Si los catálogos no se pueden cargar, la pestaña lo avisa y el reporte sigue
funcionando sin esas tres listas.

La columna `estado` dice qué pasó con cada llamada:

- `transcrita`: tiene transcripción.
- `sin transcripción`: se grabó, pero CloudTalk no tiene transcripción (por
  ejemplo, todavía se está procesando o la función no estaba activa). No se
  guarda en caché, así que se vuelve a consultar en el próximo reporte.
- `sin grabación`: no se grabó, así que no puede tener transcripción.

A diferencia de Ringover, CloudTalk indica de cada hablante si es agente o
contacto, de modo que el diálogo no depende de si la llamada fue entrante o
saliente. Si interviene un segundo agente (una transferencia) aparece como
`Agente <id>`.

La documentación no dice en qué zona horaria interpreta `date_from` y
`date_to`, así que se pide un día de más por cada lado y el recorte exacto se
hace con `started_at`, que viene en UTC. La columna `fecha` queda en hora local.
