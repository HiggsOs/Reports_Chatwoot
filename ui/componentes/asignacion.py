"""Elegir una fila para ver su detalle y cambiar a mano quién la atendió."""

import streamlit as st

from panel.db.base import unidad_de_trabajo
from panel.servicios.interacciones import SIN_ASIGNAR, ServicioInteracciones


def fila_elegida(clave: str, evento, filas, identificar):
    """La fila que se está viendo en detalle.

    Streamlit olvida la fila elegida cuando cambian los datos de la tabla (por
    ejemplo, al transcribir o asignar), así que se recuerda por su id hasta que
    se elija otra o se cierre el detalle.
    """
    seleccion = evento.selection.rows if evento else []
    if seleccion and seleccion[0] < len(filas):
        st.session_state[clave] = identificar(filas[seleccion[0]])
    elegida = st.session_state.get(clave)
    return next((f for f in filas if identificar(f) == elegida), None)


def cerrar_detalle(clave: str) -> None:
    if st.button("Cerrar el detalle", key=f"{clave}-cerrar"):
        st.session_state.pop(clave, None)
        st.rerun()


def editor_asignacion(
    fabrica, tipo: str, interaccion_id: int, persona_id: int | None, asignacion: str, personas
) -> None:
    """Cambiar el asesor a mano, o volver a la asignación automática."""
    ids = [None] + [p.id for p in personas]
    nombres = {p.id: p.etiqueta for p in personas}
    elegida = st.selectbox(
        "Asignar a mano",
        ids,
        index=ids.index(persona_id) if persona_id in ids else 0,
        format_func=lambda pid: SIN_ASIGNAR if pid is None else nombres[pid],
        key=f"{tipo}-{interaccion_id}-persona",
        help="Una asignación hecha a mano no la cambian ni la sincronización ni las reglas.",
    )
    izquierda, derecha = st.columns(2)
    if izquierda.button("Guardar asignación", key=f"{tipo}-{interaccion_id}-guardar"):
        with unidad_de_trabajo(fabrica) as sesion:
            ServicioInteracciones(sesion).asignar_manual(tipo, interaccion_id, elegida)
        st.rerun()
    if asignacion == "manual" and derecha.button(
        "Volver a la asignación automática", key=f"{tipo}-{interaccion_id}-automatica"
    ):
        with unidad_de_trabajo(fabrica) as sesion:
            ServicioInteracciones(sesion).volver_a_automatica(tipo, interaccion_id)
        st.rerun()
