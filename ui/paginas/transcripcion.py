"""La transcripción en el detalle de una llamada, y la página Transcripción."""

from datetime import date, datetime, time, timedelta

import pandas as pd
import streamlit as st
from sqlalchemy.orm import Session, sessionmaker

from config import Config
from panel.asignacion.servicio import ZONA_OPERACION_POR_DEFECTO
from panel.db.base import unidad_de_trabajo
from panel.transcripcion import consultas
from panel.transcripcion.registro import titulo as titulo_proveedor
from panel.transcripcion.servicio import ServicioTranscripcion, VistaTranscripcion

HABLANTES = {"agente": "Agente", "cliente": "Cliente"}
CANALES = {
    "mono": "grabación mono",
    "estereo": "grabación estéreo (un canal por persona)",
    "estereo_duplicado": "grabación estéreo con el mismo audio en los dos canales",
}
NO_CONFIGURADA = (
    "La transcripción no está configurada: falta TRANSCRIPCION_PROVEEDOR o la clave "
    "del proveedor (por ejemplo, OPENAI_API_KEY)."
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


def _costo(costo) -> str:
    return "sin precio configurado" if costo is None else f"{costo:.4f} USD"


def dialogo(vista: VistaTranscripcion) -> None:
    lineas = []
    for segmento in vista.segmentos:
        marca = f"`{_minuto(segmento.inicio)}` " if segmento.inicio is not None else ""
        texto = segmento.texto.replace("\n", " ")
        lineas.append(f"{marca}**{_quien(segmento)}:** {texto}")
    with st.container(height=420):
        st.markdown("  \n".join(lineas) if lineas else "_La transcripción no tiene texto._")


def _etiqueta(vista: VistaTranscripcion) -> str:
    estrella = "★ " if vista.principal else ""
    return (
        f"{estrella}{titulo_proveedor(vista.proveedor)} · {vista.modelo} · "
        f"{vista.creado_en.astimezone(ZONA_OPERACION_POR_DEFECTO):%d/%m/%Y %H:%M}"
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
                "Versión", range(len(vistas)), format_func=lambda i: _etiqueta(vistas[i]),
                key=f"version-{llamada_id}",
                help="★ es la principal: la que se usa al auditar.",
            )
            vista = vistas[elegida]
        st.caption(
            f"{titulo_proveedor(vista.proveedor)} ({vista.modelo}) · "
            f"{CANALES.get(vista.canales_audio, vista.canales_audio)} · {_costo(vista.costo_estimado)}"
        )
        dialogo(vista)
        _quien_es_quien(transcripcion, vista, llamada_id)
        if not vista.principal and st.button("Usar esta como principal", key=f"principal-{vista.id}"):
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
        "Proveedor", nombres, format_func=titulo_proveedor, key=f"proveedor-{llamada_id}",
        help="El primero es el configurado; elegir otro sirve para comparar.",
    )
    _, costo = transcripcion.costo_de_lote([llamada_id], proveedor)
    derecha.write("")
    texto = "Transcribir de nuevo" if ya_hay else "Transcribir"
    if derecha.button(texto, key=f"transcribir-{llamada_id}", type="secondary" if ya_hay else "primary"):
        with st.spinner("Transcribiendo… puede tardar un minuto."):
            resultado = transcripcion.transcribir(llamada_id, proveedor)
        if resultado.error:
            st.error(resultado.error)
        else:
            st.rerun()
    st.caption(f"Costo estimado: {_costo(costo)}.")


def lote(transcripcion: ServicioTranscripcion | None, filas) -> None:
    """Pedir la transcripción de las llamadas filtradas que todavía no tienen."""
    if transcripcion is None:
        return
    pendientes = [
        f.id for f in filas
        if f.grabada and not f.transcripcion_estado and f.audio_estado not in ("sin_grabacion", "vencido")
    ]
    with st.expander(f"Transcribir en lote ({len(pendientes)} llamadas sin transcripción)"):
        if not pendientes:
            st.caption("Todas las llamadas del listado ya están transcritas o no tienen grabación.")
            return
        minutos, costo = transcripcion.costo_de_lote(pendientes)
        st.markdown(
            f"{len(pendientes)} llamadas, unos **{minutos:.0f} minutos** de audio. "
            f"Costo estimado: **{_costo(costo)}**."
        )
        st.caption(
            "Se agregan a la cola y las transcribe la sincronización, unas cuantas por "
            "ciclo. El avance se ve en la página Transcripción."
        )
        if st.button(f"Agregar {len(pendientes)} a la cola", type="primary", key="lote-encolar"):
            creados = transcripcion.encolar(pendientes)
            st.success(f"Se agregaron {creados} llamadas a la cola.")


def pagina(fabrica: sessionmaker[Session], cfg: Config, transcripcion: ServicioTranscripcion | None) -> None:
    st.title("Transcripción")
    if transcripcion is None:
        st.warning(NO_CONFIGURADA)
    else:
        principal = transcripcion.estrategias[transcripcion.cadena[0]]
        respaldo = ", ".join(titulo_proveedor(n) for n in transcripcion.cadena[1:]) or "ninguno"
        st.markdown(
            f"**Proveedor:** {titulo_proveedor(principal.nombre)} (`{principal.modelo}`) · "
            f"**Respaldo:** {respaldo} · **Idioma:** {cfg.transcripcion_idioma}"
        )
        capacidades = principal.capacidades
        st.caption(
            ("Separa hablantes" if capacidades.diarizacion else "No separa hablantes")
            + " · "
            + ("da marcas de tiempo" if capacidades.marcas_de_tiempo else "no da marcas de tiempo")
            + f" · en estéreo, el agente es el canal {cfg.cloudtalk_canal_agente}."
        )

    with unidad_de_trabajo(fabrica) as sesion:
        cola = consultas.estado_cola(sesion)
        errores = consultas.trabajos_con_error(sesion)
        inicio_mes = datetime.combine(date.today().replace(day=1), time.min, tzinfo=ZONA_OPERACION_POR_DEFECTO)
        gasto = consultas.gasto(sesion, inicio_mes, inicio_mes + timedelta(days=32))
        comparables = consultas.llamadas_comparables(sesion)

    st.subheader("Cola")
    columnas = st.columns(4)
    for columna, (estado, etiqueta) in zip(
        columnas,
        [("pendiente", "Pendientes"), ("en_proceso", "En proceso"), ("hecho", "Hechas"), ("error", "Con error")],
    ):
        columna.metric(etiqueta, cola.get(estado, 0))
    st.caption(
        f"La sincronización transcribe hasta {cfg.transcripcion_por_ciclo} por ciclo, cada "
        f"{cfg.sync_intervalo_minutos} minutos. Un pedido que falla se reintenta tres veces."
    )
    if errores:
        st.dataframe(
            pd.DataFrame(
                [
                    {"Llamada": e.llamada, "Fecha": f"{e.inicio:%d/%m/%Y %H:%M}",
                     "Intentos": e.intentos, "Error": e.error}
                    for e in errores
                ]
            ),
            hide_index=True,
            use_container_width=True,
        )
        if transcripcion is not None and st.button("Reintentar las que fallaron"):
            for error in errores:
                transcripcion.reintentar(error.id)
            st.rerun()

    st.subheader(f"Gasto de {inicio_mes:%m/%Y}")
    if gasto:
        st.dataframe(
            pd.DataFrame(
                [
                    {"Proveedor": titulo_proveedor(g.proveedor), "Modelo": g.modelo,
                     "Transcripciones": g.transcripciones, "Minutos": g.minutos,
                     "Costo estimado (USD)": "sin precio" if g.costo is None else f"{g.costo:.2f}"}
                    for g in gasto
                ]
            ),
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.caption("Todavía no hay transcripciones este mes.")

    st.subheader("Comparar proveedores")
    if not comparables or transcripcion is None:
        st.caption(
            "Cuando una llamada tenga dos transcripciones (con «Transcribir de nuevo» y otro "
            "proveedor), aquí se ven lado a lado."
        )
        return
    elegida = st.selectbox(
        "Llamada",
        comparables,
        format_func=lambda c: f"{c.llamada} · {c.inicio:%d/%m/%Y %H:%M} · {c.transcripciones} versiones",
    )
    vistas = transcripcion.de_llamada(elegida.llamada_id)
    izquierda, derecha = st.columns(2)
    for columna, vista in zip((izquierda, derecha), vistas[:2]):
        with columna:
            st.caption(_etiqueta(vista) + f" · {_costo(vista.costo_estimado)}")
            dialogo(vista)
