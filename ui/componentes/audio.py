"""Reproductor de llamadas, para el detalle en Llamadas y en Historial del cliente."""

import streamlit as st

from panel.audio.servicio import ResultadoAudio, ServicioAudio

# Lo ya escuchado en esta sesión, para adelantar o volver sin pedirlo de nuevo.
CLAVE_ESCUCHADOS = "audios_escuchados"
MAXIMO_EN_SESION = 5

ESTADOS = {
    "guardado": "guardado",
    "pendiente": "guardándose",
    "sin_grabacion": "sin grabación",
    "vencido": "CloudTalk lo borró",
    "eliminado": "borrado por plazo",
}


def etiqueta_estado(estado: str | None) -> str:
    return ESTADOS.get(estado or "", "")


def reproductor(audio: ServicioAudio | None, llamada_id: int, retencion_dias: int) -> None:
    if audio is None:
        st.caption("Para escuchar las llamadas hay que configurar CloudTalk.")
        return

    escuchados: dict[int, ResultadoAudio] = st.session_state.setdefault(CLAVE_ESCUCHADOS, {})
    if llamada_id not in escuchados:
        lugar = st.empty()
        with lugar.container():
            if audio.guarda_audios:
                st.caption(
                    f"Al escucharla, el audio queda guardado {retencion_dias} días desde "
                    "la fecha de la llamada."
                )
            if not st.button(
                "Escuchar la llamada", key=f"escuchar-{llamada_id}", type="primary",
                icon=":material/play_arrow:",
            ):
                return
        lugar.empty()
        with st.spinner("Trayendo el audio de CloudTalk…"):
            escuchados[llamada_id] = audio.escuchar(llamada_id)
        while len(escuchados) > MAXIMO_EN_SESION:
            escuchados.pop(next(iter(escuchados)))

    resultado = escuchados[llamada_id]
    if resultado.mp3:
        st.audio(resultado.mp3, format="audio/mpeg")
    if resultado.mensaje:
        (st.info if resultado.mp3 else st.warning)(resultado.mensaje)

    if resultado.pendiente_de_subir:
        # Después de mostrar el reproductor: la subida no demora la escucha.
        with st.spinner("Guardando el audio en el servidor…"):
            subido = audio.subir_pendiente(llamada_id)
        escuchados[llamada_id] = resultado.model_copy(update={"pendiente_de_subir": False})
        if subido:
            st.caption("Audio guardado en el servidor.")
        else:
            st.caption(
                "No se pudo guardar en el servidor ahora; la sincronización lo reintenta "
                "en su próximo ciclo. Mientras tanto se escucha igual."
            )
