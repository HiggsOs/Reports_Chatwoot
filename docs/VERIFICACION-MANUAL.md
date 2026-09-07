# Verificación manual — lo que falta comprobar

Todo lo que sigue necesita algo que el entorno de desarrollo no tenía:
credenciales reales de Chatwoot, o un navegador capaz de renderizar la tabla
editable de Streamlit. Son los últimos pasos antes de dar el reporte por bueno.

Recórrelos en orden. Si algo no coincide, la sección final dice dónde mirar.

---

## Parte A — La tabla de asesores

Esta parte no necesita credenciales de Chatwoot: puedes levantar el contenedor
con un token ficticio. El login y la pestaña Asesores no llaman a la API.

Este flujo es el que más importa probar. Necesitó tres correcciones durante el
desarrollo y nunca pudo ejecutarse: la tabla editable de Streamlit se dibuja
sobre un `<canvas>` que no monta en el navegador del entorno de pruebas, así
que no se pudieron manipular sus celdas.

- [ ] **A1. Edición normal.** Agrega dos asesores con su área, guarda, recarga
      la página. Deben seguir ahí.
- [ ] **A2. Correos repetidos.** Agrega el mismo correo dos veces y guarda.
      Debe rechazarlo con un mensaje claro, sin guardar nada.
- [ ] **A3. Borrado total.** Con asesores ya guardados, borra todas las filas.
      Debe aparecer una advertencia diciendo cuántos asesores se perderían, y
      una casilla de confirmación. El botón *Guardar cambios* debe quedar
      **deshabilitado** hasta marcarla.
- [ ] **A4. Borrado confirmado.** Marca la casilla y guarda. Debe verse el
      mensaje de éxito **sin ningún error rojo ni traceback en pantalla**.
      Este es el punto exacto donde una corrección anterior rompía la app.
- [ ] **A5. Secuencia de rearme.** Vacía la tabla, marca la casilla, y en vez
      de guardar vuelve a agregar una fila. Después vacía la tabla otra vez.
      La casilla debe reaparecer **desmarcada**, exigiendo confirmar de nuevo.
- [ ] **A6. Mapeo ya vacío.** Con la tabla vacía y sin asesores guardados,
      guarda. No debe pedir ninguna confirmación: no hay nada que perder.

## Parte B — El reporte contra la instancia real

Esta parte necesita las credenciales reales de Chatwoot. Es la Tarea 9 del plan.

- [ ] **B1. Un día conocido.** Elige un día con pocas conversaciones y genera
      el reporte.
- [ ] **B2. El conteo cuadra.** Filtra ese mismo día en la interfaz de Chatwoot
      y cuenta. Debe coincidir con la cantidad de filas del CSV.
- [ ] **B3. Tres conversaciones a mano.** Toma del CSV una entrante, una
      saliente y una resuelta. Ábrelas en Chatwoot y confirma que el asesor,
      las etiquetas, la dirección y la fecha de cierre coinciden.
- [ ] **B4. Cuántos cierres son aproximados.** Cuenta las filas con
      `cierre_aproximado = Sí`. Si son muchas, ver más abajo.
- [ ] **B5. El CSV en Excel.** Ábrelo en Excel en Windows. Los acentos deben
      verse bien y las columnas deben quedar separadas.
- [ ] **B6. Rendimiento y caché.** Genera un mes completo y mide cuánto tarda.
      Repite la misma consulta: la segunda vez debe ser mucho más rápida.
      Si no lo es, la caché no está funcionando.

---

## Si algo no coincide

**El conteo de B2 no cuadra** — El sospechoso es el filtro de fechas. Chatwoot
ha cambiado entre versiones si espera el `created_at` como epoch o como texto.
Está en `listar_conversaciones`, en `chatwoot.py`. El plan (Tarea 9, Paso 2)
explica qué probar.

**Muchas filas con `cierre_aproximado = Sí` en B4** — Significa que el idioma de
los mensajes de actividad de tu Chatwoot no está cubierto. Copia el texto
literal de una actividad de resolución y amplía `_PATRON_RESOLUCION` en
`reporte.py`. La sección 5.3 del diseño explica por qué existe esta cascada:
la API no expone una fecha de cierre, así que se deduce del hilo de mensajes.

**La app muestra un error rojo en A4** — Es la regresión que ya se corrigió una
vez. Revisa que no haya ninguna escritura a `st.session_state` después de que
la casilla se haya instanciado en la misma corrida del script.

**El login no acepta la contraseña** — Verifica que `APP_PASSWORD_HASH` sea el
hash generado con `python generar_hash.py`, y no la contraseña en texto plano.

**Tras un redespliegue se perdieron los asesores** — El volumen no está montado
en `/data`. Sin él, EasyPanel recrea el contenedor vacío en cada despliegue.
