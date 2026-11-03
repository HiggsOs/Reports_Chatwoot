"""Página Historial del cliente: llamadas y chats de un número, en orden."""

import pandas as pd
import streamlit as st
from sqlalchemy.orm import Session, sessionmaker

from config import Config
from panel.db.base import unidad_de_trabajo
from panel.db.repositorios.personas import RepositorioPersonas
from panel.servicios import clientes
from panel.servicios.clientes import SIN_ASIGNAR
from ui import estado
from ui.componentes import chat
from ui.componentes import transcripcion as ui_transcripcion
from ui.componentes.asignacion import cerrar_detalle, editor_asignacion, fila_elegida
from ui.componentes.audio import reproductor
from ui.componentes.estilo import ICONOS, franja_asesor

TIPOS = {"llamada": "Llamada", "conversacion": "Chat"}


def _cantidad(numero: int, singular: str, plural: str) -> str:
    return f"{numero} {singular if numero == 1 else plural}"


def _descripcion(resumen: clientes.ResumenCliente) -> str:
    partes = [
        resumen.etiqueta,
        _cantidad(resumen.llamadas, "llamada", "llamadas"),
        _cantidad(resumen.conversaciones, "chat", "chats"),
    ]
    if resumen.ultima:
        partes.append(f"última {resumen.ultima:%d/%m/%Y}")
    return " — ".join(partes)


def mostrar(fabrica: sessionmaker[Session], cfg: Config, audio=None, transcripcion=None) -> None:
    """`audio` y `transcripcion`: los servicios, para escuchar y transcribir."""
    st.title("Historial del cliente")
    st.caption(
        "Busque un número en cualquier formato (612 345 678, +34 612…, 0034…) o un "
        "nombre. Se ven todas sus llamadas y chats, con el asesor que atendió cada uno."
    )

    elegido_antes = st.session_state.pop(estado.CLIENTE_ELEGIDO, None)
    izquierda, derecha = st.columns([3, 1])
    texto = izquierda.text_input(
        "Buscar", placeholder="Teléfono o nombre", key="historial-busqueda"
    )
    derecha.write("")
    solo_revisar = derecha.checkbox(
        "Teléfonos por revisar",
        key="historial-revisar",
        help="Números que no se pudieron interpretar: se guardaron solo sus dígitos.",
    )

    with unidad_de_trabajo(fabrica) as sesion:
        encontrados = clientes.buscar(sesion, texto, solo_revisar)
        if elegido_antes is not None and elegido_antes not in [c.id for c in encontrados]:
            if (previo := clientes.obtener(sesion, elegido_antes)) is not None:
                encontrados.insert(0, previo)

    if not encontrados:
        st.info("No hay clientes que coincidan con la búsqueda.")
        return
    if not texto and not solo_revisar and elegido_antes is None:
        st.caption(f"Los {len(encontrados)} clientes con actividad más reciente.")

    ids = [c.id for c in encontrados]
    descripciones = {c.id: _descripcion(c) for c in encontrados}
    if elegido_antes in ids:
        st.session_state["historial-cliente"] = elegido_antes
    cliente_id = st.selectbox(
        "Cliente", ids, format_func=descripciones.get, key="historial-cliente"
    )

    with unidad_de_trabajo(fabrica) as sesion:
        resultado = clientes.historial(sesion, cliente_id)
        personas = RepositorioPersonas(sesion).listar()
    if resultado is None:
        st.warning("El cliente ya no existe.")
        return

    _encabezado(resultado)
    _linea_de_tiempo(fabrica, cfg, resultado, personas, audio, transcripcion)


def _encabezado(resultado: clientes.Historial) -> None:
    cliente = resultado.cliente
    if cliente.revisar:
        st.warning(
            f"El teléfono «{cliente.telefono}» no se pudo interpretar como un número "
            "válido. Puede que otras interacciones del mismo cliente estén con otro formato."
        )
    columnas = st.columns(3)
    columnas[0].metric("Llamadas", cliente.llamadas)
    columnas[1].metric("Chats", cliente.conversaciones)
    columnas[2].metric("Última", f"{cliente.ultima:%d/%m/%Y}" if cliente.ultima else "—")
    st.markdown(
        "**Atendido por:** "
        + ", ".join(f"{asesor} ({cantidad})" for asesor, cantidad in resultado.por_asesor.items())
    )


def _linea_de_tiempo(
    fabrica, cfg: Config, resultado: clientes.Historial, personas, audio, transcripcion
) -> None:
    st.subheader("Línea de tiempo")
    tabla = pd.DataFrame(
        [
            {
                "Fecha": f"{e.inicio:%d/%m/%Y %H:%M}",
                "Tipo": TIPOS[e.tipo],
                "Detalle": e.resumen,
                "Asesor": e.asesor or SIN_ASIGNAR,
                "Cuenta": e.cuenta,
                "Asignación": e.asignacion,
            }
            for e in resultado.elementos
        ]
    )
    evento = st.dataframe(
        tabla,
        hide_index=True,
        use_container_width=True,
        on_select="rerun",
        selection_mode="single-row",
        key=f"historial-{resultado.cliente.id}",
    )
    clave = f"historial-{resultado.cliente.id}-elegido"
    elemento = fila_elegida(clave, evento, resultado.elementos, lambda e: (e.tipo, e.id))
    if elemento is None:
        st.caption("Elija una fila para ver la llamada o leer el chat.")
        return

    icono = ICONOS[elemento.tipo]
    st.subheader(f"{icono} {TIPOS[elemento.tipo]} del {elemento.inicio:%d/%m/%Y %H:%M}")
    franja_asesor(elemento.asesor, elemento.asignacion, elemento.motivo)
    if elemento.tipo == "llamada":
        if elemento.enlace_plataforma:
            st.link_button("Abrir en CloudTalk", elemento.enlace_plataforma, icon=ICONOS["abrir"])
        reproductor(audio, elemento.id, cfg.audio_retencion_dias)
        ui_transcripcion.panel(transcripcion, elemento.id)
    else:
        if cfg.chatwoot_configurado:
            st.link_button(
                "Abrir en Chatwoot",
                f"{cfg.base_url}/app/accounts/{cfg.account_id}/conversations/{elemento.id_externo}",
                icon=ICONOS["abrir"],
            )
        chat.mostrar(fabrica, elemento.id)

    editor_asignacion(
        fabrica, elemento.tipo, elemento.id, elemento.persona_id, elemento.asignacion, personas
    )
    cerrar_detalle(clave)
