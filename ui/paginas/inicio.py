"""Página Inicio: qué hay pendiente, los números de la semana y cómo va la
sincronización."""

from datetime import datetime, timedelta, timezone

import streamlit as st
from sqlalchemy.orm import Session, sessionmaker

from config import Config
from panel.asignacion.servicio import ZONA_OPERACION_POR_DEFECTO
from panel.composicion import sincronizadores
from panel.db.base import unidad_de_trabajo
from panel.servicios import consultas
from panel.sync.sincronizadores import ejecutar_ciclo
from panel.transcripcion import consultas as consultas_transcripcion
from ui.componentes.estilo import ICONOS, insignia, usd

NOMBRES_FUENTE = {
    "cloudtalk": "CloudTalk · llamadas",
    "chatwoot": "Chatwoot · conversaciones",
    "audios_pendientes": "Audios por subir al servidor",
    "retencion_audios": "Borrado de audios vencidos",
    "transcripciones": "Transcripciones en cola",
    "transcripcion_automatica": "Transcripción automática",
    "retencion_transcripciones": "Borrado de transcripciones vencidas",
}
FUENTES_PRINCIPALES = ("cloudtalk", "chatwoot")
DIAS = 7


def _fecha(momento: datetime | None) -> str:
    if momento is None:
        return "—"
    return momento.astimezone(ZONA_OPERACION_POR_DEFECTO).strftime("%d/%m/%Y %H:%M")


def _variacion(actual: int, anterior: int) -> str | None:
    if not anterior:
        return None
    cambio = (actual - anterior) / anterior
    return f"{cambio:+.0%} vs. la semana anterior"


def mostrar(fabrica: sessionmaker[Session], cfg: Config, paginas: dict) -> None:
    """`paginas`: ruta → página, para ir directo a lo pendiente."""
    ahora = datetime.now(timezone.utc)
    desde = ahora - timedelta(days=DIAS)
    st.title("Inicio")
    st.caption(
        f"{ahora.astimezone(ZONA_OPERACION_POR_DEFECTO):%d/%m/%Y %H:%M} (hora de España) · "
        f"números de los últimos {DIAS} días."
    )

    with unidad_de_trabajo(fabrica) as sesion:
        numeros = consultas.resumen(sesion, desde, ahora)
        antes = consultas.resumen(sesion, desde - timedelta(days=DIAS), desde)
        puntos = {p.fuente: p for p in consultas.estado_sincronizacion(sesion)}
        cola = consultas_transcripcion.estado_cola(sesion)
        por_vencer = consultas.audios_por_vencer(sesion, ahora, cfg.audio_retencion_dias)
        gastado = consultas_transcripcion.gasto_del_mes(sesion, ahora)

    _sin_configurar(cfg, paginas)
    _pendiente(cfg, paginas, numeros, cola, por_vencer, gastado)

    st.subheader("La semana")
    columnas = st.columns(5)
    columnas[0].metric("Llamadas", numeros.llamadas, _variacion(numeros.llamadas, antes.llamadas))
    columnas[1].metric(
        "Chats", numeros.conversaciones, _variacion(numeros.conversaciones, antes.conversaciones)
    )
    columnas[2].metric(
        "Llamadas sin asignar", numeros.llamadas_sin_asignar,
        _variacion(numeros.llamadas_sin_asignar, antes.llamadas_sin_asignar), delta_color="inverse",
    )
    columnas[3].metric(
        "Chats sin asignar", numeros.conversaciones_sin_asignar,
        _variacion(numeros.conversaciones_sin_asignar, antes.conversaciones_sin_asignar),
        delta_color="inverse",
    )
    columnas[4].metric("Cuentas sin regla", numeros.cuentas_sin_regla)

    _sincronizacion(fabrica, cfg, puntos)


def _sin_configurar(cfg: Config, paginas: dict) -> None:
    faltan = [nombre for nombre, listo in (("CloudTalk", cfg.cloudtalk_configurado),
                                          ("Chatwoot", cfg.chatwoot_configurado)) if not listo]
    if not faltan:
        return
    st.warning(
        f"Falta conectar {' y '.join(faltan)}: sin eso no llegan "
        + ("llamadas ni chats." if len(faltan) == 2 else
           "llamadas." if faltan == ["CloudTalk"] else "chats.")
    )
    st.page_link(paginas["general"], label="Configurar las conexiones", icon=ICONOS["general"])


def _pendiente(cfg, paginas, numeros, cola, por_vencer, gastado) -> None:
    tareas = []
    if numeros.llamadas_sin_asignar:
        tareas.append((paginas["sin-asignar"], f"{numeros.llamadas_sin_asignar} llamadas sin asignar",
                       ":material/call:"))
    if numeros.conversaciones_sin_asignar:
        tareas.append((paginas["sin-asignar"], f"{numeros.conversaciones_sin_asignar} chats sin asignar",
                       ":material/chat:"))
    if numeros.cuentas_sin_regla:
        tareas.append((paginas["cuentas"], f"{numeros.cuentas_sin_regla} cuentas sin regla",
                       ":material/account_tree:"))
    if cola.get("error"):
        tareas.append((paginas["transcripcion"], f"{cola['error']} transcripciones con error",
                       ":material/error:"))
    if por_vencer:
        tareas.append((paginas["llamadas"], f"{por_vencer} audios se borran esta semana",
                       ":material/timer:"))
    tope = cfg.transcripcion_tope_mensual_usd
    if tope and gastado >= tope * cfg.transcripcion_aviso_porcentaje / 100:
        tareas.append((paginas["transcripcion"], f"Gasto de transcripción: {usd(gastado)} de {usd(tope)}",
                       ":material/payments:"))

    with st.container(border=True):
        st.markdown("**Pendiente**")
        if not tareas:
            st.success("Todo asignado y sin errores.")
            return
        columnas = st.columns(3)
        for i, (pagina, texto, icono) in enumerate(tareas):
            with columnas[i % 3]:
                st.page_link(pagina, label=texto, icon=icono)
        if por_vencer:
            st.caption(
                f"Los audios se conservan {cfg.audio_retencion_dias} días desde la llamada; "
                "las transcripciones, 3 años."
            )


def _tarjeta_fuente(punto, configurado: bool) -> str:
    if not configurado:
        return insignia("Sin configurar", "sin")
    if punto is None:
        return insignia("Sin sincronizar", "neutro")
    if punto.ultimo_error:
        return insignia("Falló", "error")
    return insignia("Correcta", "ok")


def _sincronizacion(fabrica, cfg: Config, puntos) -> None:
    st.subheader("Sincronización")
    configuradas = {"cloudtalk": cfg.cloudtalk_configurado, "chatwoot": cfg.chatwoot_configurado}
    columnas = st.columns(2)
    for columna, fuente in zip(columnas, FUENTES_PRINCIPALES):
        punto = puntos.get(fuente)
        with columna.container(border=True):
            st.markdown(
                f"**{NOMBRES_FUENTE[fuente]}** &nbsp; {_tarjeta_fuente(punto, configuradas[fuente])}",
                unsafe_allow_html=True,
            )
            if punto is None:
                st.caption("Todavía no corrió.")
                continue
            resumen = punto.resumen or {}
            st.caption(
                f"Última corrida correcta {_fecha(punto.ultimo_exito)} · "
                f"{resumen.get('nuevas', 0)} nuevas, {resumen.get('actualizadas', 0)} actualizadas · "
                f"sincronizado hasta {_fecha(punto.hasta)}"
            )
            if punto.ultimo_error:
                st.error(f"{_fecha(punto.ultimo_intento)} · {punto.ultimo_error}")

    otras = [p for f, p in puntos.items() if f not in FUENTES_PRINCIPALES]
    if otras:
        with st.expander("Tareas de mantenimiento", icon=":material/build:"):
            for punto in otras:
                estado = "con error: " + punto.ultimo_error if punto.ultimo_error else "correcta"
                st.caption(
                    f"**{NOMBRES_FUENTE.get(punto.fuente, punto.fuente)}** · última "
                    f"{_fecha(punto.ultimo_exito)} · {estado}"
                )

    st.caption(
        f"La sincronización trae lo nuevo cada {cfg.sync_intervalo_minutos} minutos. "
        "Este botón corre un ciclo ahora."
    )
    if st.button("Sincronizar ahora", icon=ICONOS["sincronizar"]):
        with st.spinner("Sincronizando… la primera vez puede tardar varios minutos."):
            resultados = ejecutar_ciclo(fabrica, sincronizadores(fabrica, cfg))
        if resultados is None:
            st.info("Ya hay una sincronización en curso. Vuelva a mirar en unos minutos.")
            return
        for resultado in resultados:
            nombre = NOMBRES_FUENTE.get(resultado.fuente, resultado.fuente)
            if resultado.error:
                st.error(f"{nombre}: {resultado.error}")
            elif resultado.fuente in FUENTES_PRINCIPALES:
                st.success(
                    f"{nombre}: {resultado.resumen.get('nuevas', 0)} nuevas, "
                    f"{resultado.resumen.get('actualizadas', 0)} actualizadas."
                )
