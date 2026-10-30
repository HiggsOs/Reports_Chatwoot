"""El chat de una conversación de Chatwoot en burbujas, para el detalle en
Conversaciones y en Historial del cliente."""

import streamlit as st

from panel.db.base import unidad_de_trabajo
from panel.servicios import clientes

# Lo que escribe el cliente no debe leerse como formato Markdown.
_ESPECIALES_MARKDOWN = set("\\`*_{}[]()#+-.!|>~<$")
# Rol del mensaje → nombre en st.chat_message. Con un nombre propio, Streamlit
# muestra su inicial como avatar (el de «assistant» sería un robot, y es una persona).
ROLES_CHAT = {"cliente": "Cliente", "asesor": "Asesor"}


def _literal(texto: str) -> str:
    return "".join(f"\\{c}" if c in _ESPECIALES_MARKDOWN else c for c in texto)


def mostrar(fabrica, conversacion_id: int, alto: int = 520) -> None:
    with unidad_de_trabajo(fabrica) as sesion:
        mensajes = clientes.mensajes_de_conversacion(sesion, conversacion_id)
    if mensajes is None:
        st.info(
            "Los mensajes de este chat todavía no están guardados. Si es de los "
            "últimos días, llegan en el próximo ciclo de sincronización; si es más "
            "viejo, al cargar ese rango con «python -m panel.sync --desde». Mientras "
            "tanto se puede leer en Chatwoot."
        )
        return
    if not mensajes:
        st.caption("El chat no tiene mensajes con texto.")
        return
    with st.container(height=alto):
        for mensaje in mensajes:
            hora = f"{mensaje.fecha:%d/%m %H:%M}" if mensaje.fecha else ""
            if mensaje.rol == "actividad":
                st.caption(f"{hora} · {mensaje.texto}")
            elif mensaje.rol == "nota":
                st.warning(
                    f"**Nota interna de {_literal(mensaje.autor)}** · {hora} · no la ve el cliente\n\n"
                    + _literal(mensaje.texto),
                    icon=":material/sticky_note_2:",
                )
            else:
                with st.chat_message(ROLES_CHAT[mensaje.rol]):
                    st.markdown(f"**{_literal(mensaje.autor)}** · {hora}")
                    st.markdown(_literal(mensaje.texto).replace("\n", "  \n"))
