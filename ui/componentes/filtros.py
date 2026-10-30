"""Filtros comunes: rango de fechas en hora de España."""

from datetime import date, datetime, time, timedelta

import streamlit as st

from panel.asignacion.servicio import ZONA_OPERACION_POR_DEFECTO


def inicio_del_dia(dia: date) -> datetime:
    return datetime.combine(dia, time.min, tzinfo=ZONA_OPERACION_POR_DEFECTO)


def rango_fechas(prefijo: str, dias: int, columnas=None) -> tuple[datetime, datetime, date, date] | None:
    """Desde y Hasta (incluido). Devuelve los límites para consultar (el
    segundo excluido) y los días elegidos, o None si el rango está al revés.

    `columnas`: dos columnas donde dibujarlos; si no, se crean.
    """
    hoy = date.today()
    izquierda, derecha = columnas or st.columns(2)
    desde = izquierda.date_input(
        "Desde", value=hoy - timedelta(days=dias), format="DD/MM/YYYY", key=f"{prefijo}-desde"
    )
    hasta = derecha.date_input("Hasta", value=hoy, format="DD/MM/YYYY", key=f"{prefijo}-hasta")
    if desde > hasta:
        st.warning("La fecha inicial no puede ser posterior a la final.")
        return None
    return inicio_del_dia(desde), inicio_del_dia(hasta + timedelta(days=1)), desde, hasta
