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
