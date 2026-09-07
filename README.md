# Reportes

Aplicación web que genera, para el rango de fechas que se elija, dos CSV:

- **Conversaciones de Chatwoot**: asesor, fecha, canal, etiquetas, tiempo de
  resolución, si fue entrante o saliente, fecha de cierre y área (Comercial o
  RDC).
- **Transcripciones de Ringover**: una fila por llamada con `call_id`, agente,
  fecha, duración, estado de la transcripción y el diálogo completo.

La columna `canal` trae el nombre del inbox por el que entró la conversación
—por ejemplo el número de WhatsApp concreto—, no el tipo de canal, para que se
distingan entre sí varias bandejas del mismo tipo.

## Uso

Se entra con usuario y contraseña. Hay tres pestañas:

- **Reporte**: elegir *Desde* y *Hasta*, presionar *Generar reporte* y descargar
  el CSV.
- **Transcripciones**: mismo flujo, contra la API de Ringover. La pestaña solo
  pide datos si está configurado `RINGOVER_API_TOKEN`.
- **Asesores**: mantener la lista de correo → área. Un asesor que no esté en la
  lista aparece como `SIN_MAPEAR` en el reporte.

## Variables de entorno

| Variable | Descripción |
|---|---|
| `CHATWOOT_BASE_URL` | Ej. `https://chat.miempresa.com` |
| `CHATWOOT_ACCOUNT_ID` | Id numérico de la cuenta |
| `CHATWOOT_API_TOKEN` | Token de acceso de un usuario administrador |
| `APP_USERNAME` | Usuario del login |
| `APP_PASSWORD_HASH` | Hash bcrypt de la contraseña |
| `APP_COOKIE_KEY` | Cadena aleatoria para firmar la cookie de sesión |
| `RINGOVER_API_TOKEN` | Token público de Ringover, con el permiso `Calls Read`. Opcional: sin él, la pestaña de transcripciones queda inactiva |
| `RINGOVER_BASE_URL` | Por defecto `https://public-api.ringover.com/v2`; usar el servidor de EE. UU. si la cuenta está allá |
| `DATA_DIR` | Ruta de los datos persistentes (por defecto `/data`) |
| `TZ` | `America/Bogota` |

Para generar el hash de la contraseña:

```bash
python generar_hash.py 'la-contraseña-elegida'
```

## Despliegue en EasyPanel

1. Crear un servicio de tipo App apuntando a este repositorio (usa el
   `Dockerfile`).
2. **Montar un volumen persistente en `/data`.** Sin esto se pierden el mapeo de
   asesores y la caché en cada despliegue.
3. Cargar las variables de entorno de la tabla anterior.
4. Asignar el dominio. EasyPanel gestiona el HTTPS.

## Desarrollo

```bash
pip install -r requirements.txt
python -m pytest
streamlit run app.py
```

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
