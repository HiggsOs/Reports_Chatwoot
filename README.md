# Panel de auditorías

Aplicación web que guarda en PostgreSQL las llamadas de CloudTalk y las
conversaciones de Chatwoot, las asigna al asesor real (aunque la cuenta sea
compartida) y las prepara para auditar. También genera, contra las APIs y para
el rango de fechas que se elija, tres CSV:

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

Se entra con usuario y contraseña. Las páginas están en el menú lateral, en
tres grupos.

**Auditoría** (lee de la base, que llena la sincronización):

- **Inicio**: llamadas, conversaciones y pendientes de los últimos 7 días,
  cuentas sin regla, estado de la sincronización de cada fuente con su último
  error, y el botón *Sincronizar ahora*.
- **Sin asignar**: la bandeja de llamadas y conversaciones sin asesor. Se
  eligen filas y se asignan a un asesor de una vez.
- **Llamadas** y **Conversaciones**: listado con filtros (fechas, asesor,
  cuenta, cliente por nombre o teléfono, solo sin asignar) y descarga en CSV.
  Al elegir una fila se ve el detalle, el enlace a CloudTalk o a Chatwoot y se
  puede escuchar y transcribir la llamada, cambiar el asesor a mano o ir al
  historial del cliente.
- **Historial del cliente**: se busca un teléfono en cualquier formato
  (`612 345 678`, `+34…`, `0034…`, o una parte) o un nombre, y se ven todas sus
  llamadas y chats en una línea de tiempo, con el asesor que atendió cada uno y
  cuántas veces atendió cada asesor. Al elegir un chat se lee la conversación
  completa (mensajes del cliente, del asesor, notas internas y actividad); al
  elegir una llamada, el reproductor y el enlace a CloudTalk. Desde ahí también se cambia el
  asesor. La casilla *Teléfonos por revisar* muestra los números que no se
  pudieron interpretar.

**Configuración**:

- **Asesores**: la lista de personas reales con su nombre y su área. Quitar un
  asesor no lo borra: lo desactiva, y si se vuelve a agregar se reactiva. Un
  asesor que no esté en la lista aparece como `SIN_MAPEAR` en el reporte de
  Chatwoot en vivo.
- **Cuentas**: las cuentas de CloudTalk (agentes) y de Chatwoot (usuarios), con
  la regla que dice qué asesor atendió cada llamada o conversación. Ver
  *Cuentas y reglas de asignación* más abajo.
- **Transcripción**: el proveedor configurado, la cola de transcripciones, el
  gasto del mes y la comparación de dos versiones de una misma llamada. Ver
  *Transcripción* más abajo.

**Reportes en vivo** (consultan las APIs en el momento, como antes de la base):

- **Reporte de Chatwoot**: elegir *Desde* y *Hasta*, *Generar reporte* y
  descargar el CSV.
- **Transcripciones de Ringover**: mismo flujo. Solo pide datos si está
  configurado `RINGOVER_API_TOKEN`.
- **Transcripciones de CloudTalk**: mismo flujo. Solo pide datos si están
  configurados `CLOUDTALK_API_KEY_ID` y `CLOUDTALK_API_KEY_SECRET`.

Al abrir el panel por una dirección directa (por ejemplo `/llamadas`) se entra
a Inicio: el login corre antes que la navegación. Desde ahí se usa el menú.

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
| `RINGOVER_API_TOKEN` | Token público de Ringover, con el permiso `Calls Read`. Opcional: sin él, la página de transcripciones de Ringover queda inactiva |
| `RINGOVER_BASE_URL` | Por defecto `https://public-api.ringover.com/v2`; usar el servidor de EE. UU. si la cuenta está allá |
| `CLOUDTALK_API_KEY_ID` | Id de la clave de API de CloudTalk (Dashboard → Account → Settings → API Keys). Opcional |
| `CLOUDTALK_API_KEY_SECRET` | Secreto de esa misma clave. Opcional: sin el par, la página de transcripciones de CloudTalk queda inactiva |
| `SYNC_INTERVALO_MINUTOS` | Cada cuánto corre la sincronización. Por defecto `15` |
| `SYNC_DIAS_INICIALES` | Cuántos días hacia atrás trae la primera sincronización de cada fuente. Por defecto `30` |
| `CHATWOOT_DIAS_RELECTURA` | Cuántos días hacia atrás relee Chatwoot en cada ciclo, porque las conversaciones cambian después de creadas. Por defecto `14` |
| `ALMACEN_TIPO` | Dónde se guardan los audios escuchados: `sftp` (el hosting), `local` (una carpeta en `DATA_DIR/audios`, solo para desarrollo) o vacío (se escuchan pero no se guardan) |
| `FTP_HOST`, `FTP_PORT`, `FTP_USER`, `FTP_PASSWORD` | Acceso SFTP a la cuenta FTP de los audios. En el hosting, `FTP_PORT=8023` |
| `FTP_DIR` | Carpeta de los audios dentro de esa cuenta. Por defecto `/` |
| `SFTP_HUELLA_HOST` | Huella del servidor SFTP (`SHA256:…`); ver *Audio de las llamadas* |
| `AUDIO_RETENCION_DIAS` | Días que se guarda un audio, desde la fecha de la llamada. Por defecto `90` |
| `TRANSCRIPCION_PROVEEDOR` | Quién transcribe: `openai` (por defecto si hay `OPENAI_API_KEY`) o `falsa` (texto fijo, para pruebas). Vacío y sin clave: la transcripción está apagada |
| `TRANSCRIPCION_RESPALDO` | Proveedores a probar si falla el principal, separados por coma |
| `TRANSCRIPCION_IDIOMA` | Por defecto `es` |
| `TRANSCRIPCION_VOCABULARIO` | Palabras propias separadas por coma (marcas, productos), para que el modelo las escriba bien |
| `TRANSCRIPCION_POR_CICLO` | Cuántos pedidos de la cola transcribe cada ciclo de la sincronización. Por defecto `20` |
| `TRANSCRIPCION_RETENCION_DIAS` | Días que se guarda una transcripción, desde la fecha de la llamada. Por defecto `1095` (3 años) |
| `CLOUDTALK_CANAL_AGENTE` | En una grabación estéreo, qué canal es el del agente: `izquierdo` (por defecto) o `derecho` |
| `OPENAI_API_KEY` | Clave de la API de OpenAI |
| `OPENAI_MODELO_TRANSCRIPCION` | Por defecto `gpt-4o-transcribe-diarize` |
| `OPENAI_FORMATO_RESPUESTA` | Solo para un modelo que el código no conoce: `diarized_json`, `verbose_json` o `json` |
| `OPENAI_PRECIO_MINUTO` | Precio por minuto de audio en USD, para el costo estimado. Sin valor, el panel no muestra costos |
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
6. Crear un segundo servicio de tipo App, **sincronización**, con el mismo
   repositorio, las mismas variables y este comando de inicio (no necesita
   dominio ni volumen):

   ```bash
   sh -c "alembic upgrade head && python -m panel.sync"
   ```

   Corre un ciclo cada `SYNC_INTERVALO_MINUTOS`. Si los dos servicios arrancan a
   la vez, las migraciones esperan una a la otra.

Al arrancar, el contenedor aplica las migraciones pendientes
(`alembic upgrade head`) antes de levantar la app. Si la base no responde, el
contenedor no arranca.

### Paso de `asesores.csv` a la base de datos

La primera vez que la app arranca con la base vacía, copia
`DATA_DIR/asesores.csv` a la tabla `personas` y renombra el archivo a
`asesores.csv.migrado`, que queda como respaldo y ya no se lee. Las filas con un
área que no sea `Comercial` ni `RDC` no se importan; la página **Asesores**
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

## Cuentas y reglas de asignación

*Actualizar cuentas desde las plataformas* trae los agentes de CloudTalk
(`GET /agents/index.json`, si CloudTalk está configurado) y los usuarios de
Chatwoot (`GET /agents`). Una cuenta que la plataforma deja de devolver se
desactiva, no se borra; si la respuesta llega vacía no se desactiva nada.

Cada cuenta tiene una **regla de asignación**: una estrategia y sus parámetros,
con vigencia. Las horas de las franjas son de España (`Europe/Madrid`), con su
horario de verano; inicio incluido y fin excluido.

| Estrategia | Cómo asigna |
|---|---|
| Una sola persona (`dueno_unico`) | Todo a un asesor |
| Horario fijo y el resto al otro (`fijo_y_resto`) | Lo que cae dentro del horario del asesor fijo es suyo; todo lo demás, del otro. Nunca deja nada sin asignar |
| Franjas para cada persona (`franjas_completas`) | Cada asesor tiene sus franjas; lo que no cae en ninguna queda sin asignar |

- En **Chatwoot** cada usuario es una persona (las bandejas son las
  compartidas). Al actualizar, a cada usuario sin regla cuyo correo coincide
  con el de un asesor activo se le crea una regla *Una sola persona* desde
  siempre. En CloudTalk no se hace, porque una cuenta compartida tiene el
  correo de uno solo de los asesores que la usan.
- Las reglas no se editan ni se borran. Guardar una regla nueva cierra la
  anterior en la fecha elegida (00:00 de España); si es la misma fecha en que
  empezó la anterior, esa queda como «corregida, nunca rigió». La base impide
  que dos reglas de una cuenta estén vigentes a la vez.
- Una regla no se puede guardar si nombra a un asesor inactivo. Si un asesor se
  quita de la lista después, la tabla de cuentas avisa qué reglas lo nombran.
- *Ver vista previa* dice, sin guardar nada, cuántas interacciones del período
  quedarían para cada asesor y cuántas cambiarían. Al guardar, se reasignan las
  interacciones de la cuenta desde la fecha de la regla.
- Una interacción asignada a mano (en *Sin asignar* o en el detalle de
  *Llamadas* y *Conversaciones*) no la cambian ni la sincronización ni las
  reglas nuevas, hasta que se vuelve a la asignación automática.

Para agregar una estrategia nueva: una clase en
`panel/asignacion/estrategias/` registrada con `@registrar`, su formulario en
`ui/formularios_asignacion.py` y su ejemplo en
`tests/test_asignacion_estrategias.py`, donde las pruebas de contrato la
validan junto con las demás.

## Sincronización

`python -m panel.sync` guarda en la base las llamadas contestadas de CloudTalk
(si está configurado) y las conversaciones de Chatwoot, y las asigna con la
regla de su cuenta.

- **Incremental**: cada fuente guarda hasta dónde llegó (se ve en Inicio). Las
  llamadas se releen con dos horas de margen; las conversaciones, los últimos
  `CHATWOOT_DIAS_RELECTURA` días, porque se resuelven o se reasignan después.
  Una conversación que cambia más allá de ese plazo no se actualiza.
- **Sin duplicados**: se guarda por id de la plataforma; repetir un ciclo
  actualiza lo que ya estaba.
- **Mensajes de Chatwoot**: se guardan en la base, para leer el chat en el
  historial del cliente y calcular la dirección y el cierre. Se piden solo de
  las conversaciones nuevas, las que cambiaron o las que todavía no los tienen
  (por ejemplo, las guardadas antes de esta versión: las de los últimos
  `CHATWOOT_DIAS_RELECTURA` días se completan en el próximo ciclo, y las más
  viejas al cargar su rango con `--desde`).
- **Clientes**: el teléfono se normaliza a formato internacional (`+34…` si no
  trae código de país), así una llamada y un chat del mismo número quedan
  ligados al mismo cliente. Los números que no se pueden interpretar se
  guardan con sus dígitos y quedan marcados para revisar.
- **Errores**: si una fuente falla, su error queda anotado y se ve en Inicio;
  la otra fuente sigue. El punto no avanza, así que el próximo ciclo reintenta.
- **Un ciclo a la vez**: el proceso y el botón *Sincronizar ahora* comparten un
  bloqueo de Postgres; si ya hay uno en curso, el otro se salta.

Comandos útiles (con las mismas variables de entorno):

```bash
python -m panel.sync --una-vez
```

```bash
python -m panel.sync --desde 2026-01-01 --hasta 2026-06-30
```

El segundo carga el historial de ese rango, por ejemplo la primera vez, sin
mover el punto de la sincronización normal.

## Audio de las llamadas

En el detalle de una llamada (páginas *Llamadas* e *Historial del cliente*),
*▶ Escuchar la llamada* trae la grabación de CloudTalk
(`GET /calls/recording/{id}.json`), la convierte a MP3 con `ffmpeg` y la
reproduce. Después la guarda en el almacén, así la próxima vez sale de ahí sin
volver a CloudTalk.

- Solo se pide cuando alguien la escucha, no al elegir la fila.
- Una grabación estéreo se guarda en estéreo (64 kbps) para conservar la
  separación de canales; una mono, en mono (32 kbps). Con audio telefónico el
  MP3 ocupa unas cuatro veces menos que el WAV (unos 0,24 MB por minuto en
  mono).
- Si CloudTalk responde que no hay grabación (`404`) o que ya la borró (`410`),
  queda anotado y no se vuelve a pedir.
- Si la subida al almacén falla, el MP3 queda en la base (tabla
  `audios_pendientes`) y se sigue escuchando desde ahí; la sincronización
  reintenta la subida en cada ciclo.
- **Retención**: una vez por día, la sincronización borra del almacén los audios
  de llamadas con más de `AUDIO_RETENCION_DIAS` días (el día 90 se conserva, el
  91 se borra). Una llamada más vieja se puede escuchar si CloudTalk todavía la
  tiene, pero no se vuelve a guardar.
- La columna *Audio* de la página *Llamadas* dice en qué estado está cada una.

### Configurar el SFTP del hosting

1. En Plesk, en *FTP seguro*, activar **Permitir SFTP para cuentas FTP** (puerto
   `8023`) y comprobar que ese puerto esté abierto en el firewall.
2. Crear una **cuenta FTP solo para los audios**, con su directorio **fuera de
   `httpdocs`**: lo que está en `httpdocs` se puede abrir desde internet.
3. Obtener la huella del servidor desde cualquier equipo con el proyecto
   instalado, y cargarla en `SFTP_HUELLA_HOST`:

   ```bash
   python -m panel.audio.huella ftp.midominio.com 8023
   ```

   La app verifica esa huella en cada conexión y no envía nada si no coincide:
   así nadie que se haga pasar por el servidor recibe las grabaciones. Si el
   hosting cambia la clave del servidor, hay que volver a obtenerla.
4. Cargar `ALMACEN_TIPO=sftp` y las variables `FTP_*` en **los dos servicios**
   de EasyPanel (la app y la sincronización).

## Transcripción

En el detalle de una llamada, *Transcribir* la transcribe en el momento y
muestra el diálogo con la hora de cada intervención. En *Llamadas*, *Transcribir
en lote* agrega a la cola las llamadas filtradas que todavía no tienen
transcripción, con el costo estimado antes de confirmar; la sincronización las
transcribe de a `TRANSCRIPCION_POR_CICLO` por ciclo y reintenta tres veces cada
una. La página *Transcripción* muestra la cola, los errores (con un botón para
reintentar), lo gastado en el mes y dos transcripciones de la misma llamada lado
a lado.

**Quién habla.** Antes de transcribir se mira la grabación:

- **Estéreo con una persona por canal**: cada canal se transcribe aparte, así
  que cada frase queda como *Agente* o *Cliente* sin dudas. El canal del agente
  se configura con `CLOUDTALK_CANAL_AGENTE`: conviene escuchar una grabación y
  comprobarlo. Cuesta el doble, porque se transcriben dos audios.
- **Mono, o estéreo con el mismo audio en los dos canales**: el modelo separa
  las voces como *Hablante A* y *Hablante B*. El auditor elige cuál es el agente
  con un clic.

**Proveedores.** Cada proveedor es una estrategia en
`panel/transcripcion/estrategias/` (patrón Strategy). Para OpenAI, el modelo por
defecto es `gpt-4o-transcribe-diarize`, el único que hoy separa hablantes;
OpenAI anunció su apagado para el 26/02/2027, así que antes de esa fecha hay que
cambiar `OPENAI_MODELO_TRANSCRIPCION` (y `OPENAI_FORMATO_RESPUESTA` si el modelo
nuevo no es uno que el código conozca). Para sumar otro proveedor: una clase con
`@registrar`, sus variables de entorno, y su caso en las pruebas de contrato de
`tests/test_transcripcion_estrategias.py`.

**Varias versiones.** *Transcribir de nuevo* (con el mismo u otro proveedor)
guarda otra versión; la primera queda como principal (★) y se puede cambiar.

**Retención.** Una vez por día, la sincronización borra las transcripciones de
llamadas con más de `TRANSCRIPCION_RETENCION_DIAS` días.

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

La página *Transcripciones de CloudTalk* tiene un panel **Filtros** que se aplica antes de descargar las
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

Si los catálogos no se pueden cargar, la página lo avisa y el reporte sigue
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
