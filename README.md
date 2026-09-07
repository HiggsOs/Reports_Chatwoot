# Reporte de conversaciones de Chatwoot

Aplicación web que genera, para el rango de fechas que se elija, un CSV con las
conversaciones de Chatwoot: asesor, fecha, canal, etiquetas, tiempo de
resolución, si fue entrante o saliente, fecha de cierre y área (Comercial o
RDC).

La columna `canal` trae el nombre del inbox por el que entró la conversación
—por ejemplo el número de WhatsApp concreto—, no el tipo de canal, para que se
distingan entre sí varias bandejas del mismo tipo.

## Uso

Se entra con usuario y contraseña. Hay dos pestañas:

- **Reporte**: elegir *Desde* y *Hasta*, presionar *Generar reporte* y descargar
  el CSV.
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
