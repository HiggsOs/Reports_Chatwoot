"""Avisos que sobreviven a un `st.rerun()` (patrón flash message).

Una acción guarda el aviso y vuelve a dibujar la página; la página lo muestra
una sola vez arriba de todo. Así todas las confirmaciones se ven igual.
"""

import streamlit as st

_CLAVE = "_avisos_pendientes"


def dejar(texto: str, tipo: str = "exito") -> None:
    st.session_state.setdefault(_CLAVE, []).append((tipo, texto))


def mostrar() -> None:
    for tipo, texto in st.session_state.pop(_CLAVE, []):
        {"exito": st.success, "info": st.info, "aviso": st.warning, "error": st.error}[tipo](texto)
