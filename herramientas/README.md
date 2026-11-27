# Herramientas de diagnóstico

Scripts para comprobar cómo se comporta la API de Chatwoot de una instancia
concreta. No forman parte de la aplicación: el `Dockerfile` no los copia a la
imagen. Se ejecutan desde la raíz del proyecto y leen las credenciales del
`.env`. Solo hacen lecturas.

## `diagnostico_filtro.py`

Comprueba que el filtro de fechas devuelve lo que debe: que un solo día trae
conversaciones, y que la suma de días sueltos coincide con el total del rango
que los contiene.

```bash
 .venv/bin/python herramientas/diagnostico_filtro.py
```

Sirvió para descubrir dos defectos que ningún test podía ver, porque dependían
del comportamiento real del servidor: Chatwoot responde 500 si `created_at`
llega como número epoch, y compara esa fecha por día ignorando la hora, con
operadores estrictos — así que pedir un solo día devolvía cero conversaciones
en silencio.

En la versión 4.20.1, Chatwoot ya valida la fecha con `Date.iso8601` y a
responder 422 ("Los valores proporcionados para created_at no son válidos")
si llevaba hora. Desde entonces el filtro manda solo el día, `AAAA-MM-DD`.

Vale la pena volver a correrlo después de actualizar la versión de Chatwoot.

## `diagnostico_canal.py`

Muestra los inboxes de la cuenta y cómo se reparten las conversaciones entre
ellos.

```bash
 .venv/bin/python herramientas/diagnostico_canal.py
```

Sirvió para decidir que la columna `canal` use el nombre del inbox y no el tipo
de canal: la cuenta tiene dos bandejas de WhatsApp, y el tipo habría dicho
"WhatsApp" en ambas sin distinguirlas.

## `diagnostico_deepgram.py`

Muestra cuántas voces separa Deepgram en una grabación concreta: manda el audio
con los mismos parámetros que el panel y cuenta los hablantes por palabra y por
utterance. Si es estéreo, también lo pide canal por canal.

```bash
 .venv/bin/python herramientas/diagnostico_deepgram.py llamada-123.mp3
```

El MP3 se baja desde la llamada en el panel (botón de descarga del reproductor).
Lee `DEEPGRAM_API_KEY` del `.env`. Transcribe de verdad, así que gasta lo mismo
que transcribir la llamada desde el panel.

Sirvió para ver que Deepgram da un hablante por utterance y que una utterance
puede mezclar las dos voces: el panel ahora arma las frases por palabra.
