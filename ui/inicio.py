"""Página Inicio: qué hay para revisar y cómo va la sincronización."""

from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st
from sqlalchemy.orm import Session, sessionmaker

from config import Config
from panel.asignacion.servicio import ZONA_OPERACION_POR_DEFECTO
from panel.composicion import sincronizadores
from panel.db.base import unidad_de_trabajo
from panel.servicios import consultas
from panel.sync.sincronizadores import ejecutar_ciclo

NOMBRES_FUENTE = {"cloudtalk": "CloudTalk (llamadas)", "chatwoot": "Chatwoot (conversaciones)"}


def _fecha(momento: datetime | None) -> str:
    if momento is None:
        return "—"
    return momento.astimezone(ZONA_OPERACION_POR_DEFECTO).strftime("%d/%m/%Y %H:%M")


def mostrar(fabrica: sessionmaker[Session], cfg: Config, enlaces: dict) -> None:
    """`enlaces`: las páginas «sin_asignar» y «cuentas», para ir directo."""
    st.title("Inicio")
    hasta = datetime.now(timezone.utc)
    desde = hasta - timedelta(days=7)
    with unidad_de_trabajo(fabrica) as sesion:
        numeros = consultas.resumen(sesion, desde, hasta)
        puntos = consultas.estado_sincronizacion(sesion)
        estado = [
            {
                "Fuente": NOMBRES_FUENTE.get(p.fuente, p.fuente),
                "Sincronizado hasta": _fecha(p.hasta),
                "Último éxito": _fecha(p.ultimo_exito),
                "Último error": p.ultimo_error or "",
                "Último ciclo": ", ".join(f"{k}: {v}" for k, v in (p.resumen or {}).items()),
            }
            for p in puntos
        ]

    st.caption("Últimos 7 días.")
    columnas = st.columns(3)
    columnas[0].metric("Llamadas", numeros.llamadas)
    columnas[1].metric("Conversaciones", numeros.conversaciones)
    columnas[2].metric(
        "Sin asignar", numeros.llamadas_sin_asignar + numeros.conversaciones_sin_asignar
    )
    if numeros.llamadas_sin_asignar or numeros.conversaciones_sin_asignar:
        st.page_link(enlaces["sin_asignar"], label="Revisar la bandeja Sin asignar", icon="📥")
    if numeros.cuentas_sin_regla:
        st.warning(
            f"{numeros.cuentas_sin_regla} cuentas no tienen regla de asignación: sus "
            "interacciones quedan sin asignar."
        )
        st.page_link(enlaces["cuentas"], label="Cargar las reglas en Cuentas", icon="🗂️")

    st.subheader("Sincronización")
    st.caption(
        f"El proceso de sincronización trae lo nuevo cada {cfg.sync_intervalo_minutos} "
        "minutos. Este botón corre un ciclo ahora."
    )
    if estado:
        st.dataframe(pd.DataFrame(estado), hide_index=True, use_container_width=True)
    else:
        st.info("Todavía no se sincronizó nada.")

    if st.button("Sincronizar ahora"):
        with st.spinner("Sincronizando… la primera vez puede tardar varios minutos."):
            resultados = ejecutar_ciclo(fabrica, sincronizadores(fabrica, cfg))
        if resultados is None:
            st.info("Ya hay una sincronización en curso. Vuelva a mirar en unos minutos.")
        else:
            for resultado in resultados:
                nombre = NOMBRES_FUENTE.get(resultado.fuente, resultado.fuente)
                if resultado.error:
                    st.error(f"{nombre}: {resultado.error}")
                else:
                    st.success(
                        f"{nombre}: {resultado.resumen.get('nuevas', 0)} nuevas, "
                        f"{resultado.resumen.get('actualizadas', 0)} actualizadas."
                    )
