"""La transcripción de una llamada: leerla, decir quién es quién, pedirla y
encolar un lote. Se usa en el detalle de Llamadas y de Historial del cliente."""


import streamlit as st

from config import Config
from panel.asignacion.servicio import ZONA_OPERACION_POR_DEFECTO
from panel.transcripcion.registro import titulo as titulo_proveedor
from panel.transcripcion.servicio import ServicioTranscripcion, VistaTranscripcion
from ui.componentes.estilo import ICONOS, usd

HABLANTES = {"agente": "Agente", "cliente": "Cliente"}
CANALES = {
    "mono": "grabación mono",
    "estereo": "grabación estéreo (un canal por persona)",
    "estereo_duplicado": "grabación estéreo con el mismo audio en los dos canales",
}
NO_CONFIGURADA = (
    "La transcripción no está configurada: falta elegir el modelo principal o la clave "
    "del proveedor. Se configura en la página Transcripción, pestaña Configuración."
)


def _minuto(segundos: float | None) -> str:
    if segundos is None:
        return ""
    minutos, resto = divmod(int(segundos), 60)
    return f"{minutos:02d}:{resto:02d}"


def _quien(segmento) -> str:
    if segmento.hablante in HABLANTES:
        return HABLANTES[segmento.hablante]
    return f"Hablante {segmento.etiqueta}" if segmento.etiqueta else "?"


def costo_texto(costo) -> str:
    return "sin precio configurado" if costo is None else usd(costo, 4)


def dialogo(vista: VistaTranscripcion) -> None:
    lineas = []
    for segmento in vista.segmentos:
        marca = f"`{_minuto(segmento.inicio)}` " if segmento.inicio is not None else ""
        texto = segmento.texto.replace("\n", " ")
        lineas.append(f"{marca}**{_quien(segmento)}:** {texto}")
    with st.container(height=420):
        st.markdown("  \n".join(lineas) if lineas else "_La transcripción no tiene texto._")


def etiqueta_version(vista: VistaTranscripcion) -> str:
    principal = " (principal)" if vista.principal else ""
    return (
        f"{titulo_proveedor(vista.proveedor)} · {vista.modelo} · "
        f"{vista.creado_en.astimezone(ZONA_OPERACION_POR_DEFECTO):%d/%m/%Y %H:%M}{principal}"
    )


def panel(transcripcion: ServicioTranscripcion | None, llamada_id: int) -> None:
    """La transcripción de una llamada: leerla, decir quién es quién y pedirla."""
    st.markdown("**Transcripción**")
    if transcripcion is None:
        st.caption(NO_CONFIGURADA)
        return

    vistas = transcripcion.de_llamada(llamada_id)
    if vistas:
        vista = vistas[0]
        if len(vistas) > 1:
            elegida = st.selectbox(
                "Versión", range(len(vistas)), format_func=lambda i: etiqueta_version(vistas[i]),
                key=f"version-{llamada_id}",
                help="La principal es la que se usa al auditar.",
            )
            vista = vistas[elegida]
        st.caption(
            f"{titulo_proveedor(vista.proveedor)} ({vista.modelo}) · "
            f"{CANALES.get(vista.canales_audio, vista.canales_audio)} · {costo_texto(vista.costo_estimado)}"
        )
        dialogo(vista)
        _quien_es_quien(transcripcion, vista, llamada_id)
        if not vista.principal and st.button(
            "Usar esta como principal", key=f"principal-{vista.id}", icon=":material/star:"
        ):
            transcripcion.marcar_principal(vista.id)
            st.rerun()

    _pedir(transcripcion, llamada_id, ya_hay=bool(vistas))


def _quien_es_quien(transcripcion, vista: VistaTranscripcion, llamada_id: int) -> None:
    etiquetas = vista.etiquetas_sin_resolver
    if not etiquetas:
        return
    st.info(
        "El proveedor separó las voces pero no sabe cuál es el agente. Elija quién es; "
        "el resto queda como cliente."
    )
    izquierda, derecha = st.columns([2, 1])
    agente = izquierda.radio(
        "¿Quién es el agente?",
        etiquetas,
        format_func=lambda e: f"Hablante {e}",
        horizontal=True,
        key=f"agente-{vista.id}",
    )
    derecha.write("")
    if derecha.button("Guardar", key=f"guardar-hablantes-{vista.id}"):
        roles = {e: ("agente" if e == agente else "cliente") for e in etiquetas}
        transcripcion.asignar_hablantes(vista.id, roles)
        st.rerun()


def _pedir(transcripcion: ServicioTranscripcion, llamada_id: int, ya_hay: bool) -> None:
    nombres = list(transcripcion.cadena) + [
        n for n in transcripcion.estrategias if n not in transcripcion.cadena and n != "falsa"
    ]
    if not nombres:
        return
    izquierda, derecha = st.columns([2, 1])
    proveedor = izquierda.selectbox(
        "Proveedor y modelo", nombres, format_func=titulo_proveedor, key=f"proveedor-{llamada_id}",
        help="El primero es el configurado; elegir otro sirve para comparar.",
    )
    _, costo = transcripcion.costo_de_lote([llamada_id], proveedor)
    derecha.write("")
    texto = "Transcribir de nuevo" if ya_hay else "Transcribir"
    if derecha.button(
        f"{texto} · {costo_texto(costo)}" if costo is not None else texto,
        key=f"transcribir-{llamada_id}",
        type="secondary" if ya_hay else "primary",
        icon=ICONOS["transcribir"],
    ):
        with st.spinner("Transcribiendo… puede tardar un minuto."):
            resultado = transcripcion.transcribir(llamada_id, proveedor)
        if resultado.error:
            st.error(resultado.error)
        else:
            st.rerun()
    st.caption(f"Costo estimado: {costo_texto(costo)}. Crea una versión nueva; la principal no cambia.")




def lote(transcripcion: ServicioTranscripcion | None, filas, cfg: Config | None = None) -> None:
    """Pedir la transcripción de las llamadas filtradas que todavía no tienen."""
    if transcripcion is None:
        return
    pendientes = [
        f.id for f in filas
        if f.grabada and not f.transcripcion_estado and f.audio_estado not in ("sin_grabacion", "vencido")
    ]
    with st.expander(
        f"Transcribir en lote · {len(pendientes)} llamadas sin transcripción", icon=ICONOS["transcribir"]
    ):
        if not pendientes:
            st.caption("Todas las llamadas del listado ya están transcritas o no tienen grabación.")
            return
        minutos, costo = transcripcion.costo_de_lote(pendientes)
        st.markdown(
            f"{len(pendientes)} llamadas, unos **{minutos:.0f} minutos** de audio. "
            f"Costo estimado: **{costo_texto(costo)}**."
        )
        st.caption(
            "Se agregan a la cola y las transcribe la sincronización, unas cuantas por "
            "ciclo. El avance se ve en la página Transcripción."
        )
        umbral = cfg.transcripcion_confirmar_lote_usd if cfg else None
        confirmado = True
        if umbral is not None and costo is not None and costo > umbral:
            confirmado = st.checkbox(
                f"Confirmo el gasto de {costo_texto(costo)} (supera el límite de {umbral} USD por lote).",
                key="lote-confirmar",
            )
        if st.button(
            f"Agregar {len(pendientes)} a la cola", type="primary", key="lote-encolar",
            disabled=not confirmado,
        ):
            creados = transcripcion.encolar(pendientes)
            st.success(
                f"Se agregaron {creados} llamadas a la cola. Costo estimado: {costo_texto(costo)}. "
                "Puede seguir trabajando."
            )
