"""Formularios de los parámetros de cada estrategia de asignación.

Cada estrategia registra aquí el suyo con el mismo nombre que en
`panel.asignacion.registro`. La pantalla de cuentas no sabe qué pide cada una:
llama al formulario y recibe los parámetros en crudo, que el servicio valida.
"""

from collections.abc import Callable
from datetime import time

import pandas as pd
import streamlit as st

from panel.asignacion.base import DIAS_SEMANA
from panel.esquemas.personas import PersonaResumida

# (personas activas, parámetros de la regla vigente si es de la misma
# estrategia, prefijo de las claves de los widgets) → parámetros, o una lista
# de errores si el formulario está incompleto.
Formulario = Callable[[list[PersonaResumida], dict | None, str], dict | list[str]]

_FORMULARIOS: dict[str, Formulario] = {}

FRANJA_POR_DEFECTO = {"dias": [0, 1, 2, 3, 4], "inicio": "08:00:00", "fin": "14:00:00"}
DIAS_TITULO = [dia.capitalize() for dia in DIAS_SEMANA]


def registrar(nombre: str):
    def decorar(funcion: Formulario) -> Formulario:
        _FORMULARIOS[nombre] = funcion
        return funcion

    return decorar


def obtener(nombre: str) -> Formulario | None:
    return _FORMULARIOS.get(nombre)


def _elegir_persona(
    etiqueta: str, personas: list[PersonaResumida], actual: int | None, clave: str
) -> int | None:
    ids = [p.id for p in personas]
    nombres = {p.id: p.etiqueta for p in personas}
    return st.selectbox(
        etiqueta,
        ids,
        index=ids.index(actual) if actual in ids else None,
        format_func=lambda pid: nombres[pid],
        placeholder="Elija un asesor",
        key=clave,
    )


def _a_hora(texto: str) -> time:
    return time.fromisoformat(texto)


def _editor_franjas(
    franjas: list[dict], clave: str, personas: list[PersonaResumida] | None = None
) -> list[dict] | list[str]:
    """Tabla editable de franjas: una fila por franja, un tilde por día.

    Con `personas`, agrega una columna para elegir de quién es cada franja.
    """
    nombres = {p.etiqueta: p.id for p in personas or []}
    por_id = {pid: nombre for nombre, pid in nombres.items()}
    filas = []
    for franja in franjas:
        fila = {}
        if personas is not None:
            fila["Asesor"] = por_id.get(franja.get("persona_id"))
        fila.update({dia: i in franja["dias"] for i, dia in enumerate(DIAS_TITULO)})
        fila["Inicio"] = _a_hora(franja["inicio"])
        fila["Fin"] = _a_hora(franja["fin"])
        filas.append(fila)

    columnas = {dia: st.column_config.CheckboxColumn(dia, default=False) for dia in DIAS_TITULO}
    columnas["Inicio"] = st.column_config.TimeColumn("Inicio", format="HH:mm", step=300)
    columnas["Fin"] = st.column_config.TimeColumn("Fin", format="HH:mm", step=300)
    if personas is not None:
        columnas["Asesor"] = st.column_config.SelectboxColumn(
            "Asesor", options=list(nombres), required=True
        )

    orden = (["Asesor"] if personas is not None else []) + [*DIAS_TITULO, "Inicio", "Fin"]
    editada = st.data_editor(
        pd.DataFrame(filas, columns=orden),
        column_config=columnas,
        num_rows="dynamic",
        hide_index=True,
        use_container_width=True,
        key=clave,
    )

    resultado: list[dict] = []
    errores: list[str] = []
    for numero, fila in enumerate(editada.to_dict("records"), start=1):
        dias = [i for i, dia in enumerate(DIAS_TITULO) if bool(fila.get(dia))]
        inicio, fin = fila.get("Inicio"), fila.get("Fin")
        vacia = not dias and pd.isna(inicio) and pd.isna(fin)
        if vacia:
            continue
        if pd.isna(inicio) or pd.isna(fin):
            errores.append(f"Complete la hora de inicio y de fin de la franja {numero}.")
            continue
        franja = {"dias": dias, "inicio": inicio.isoformat(), "fin": fin.isoformat()}
        if personas is not None:
            asesor = fila.get("Asesor")
            if not asesor or pd.isna(asesor):
                errores.append(f"Elija el asesor de la franja {numero}.")
                continue
            franja["persona_id"] = nombres[asesor]
        resultado.append(franja)
    if not resultado and not errores:
        errores.append("Cargue al menos una franja.")
    return errores or resultado


@registrar("dueno_unico")
def formulario_dueno_unico(personas, actuales, clave):
    persona = _elegir_persona(
        "Asesor", personas, (actuales or {}).get("persona_id"), f"{clave}-persona"
    )
    if persona is None:
        return ["Elija el asesor."]
    return {"persona_id": persona}


@registrar("fijo_y_resto")
def formulario_fijo_y_resto(personas, actuales, clave):
    actuales = actuales or {}
    izquierda, derecha = st.columns(2)
    with izquierda:
        fija = _elegir_persona(
            "Asesor con horario fijo", personas, actuales.get("persona_fija_id"), f"{clave}-fija"
        )
    with derecha:
        resto = _elegir_persona(
            "Asesor del resto del tiempo",
            personas,
            actuales.get("persona_resto_id"),
            f"{clave}-resto",
        )
    st.caption(
        "Horario fijo, en hora de España. Una fila por franja; si el asesor "
        "atiende en dos franjas, cargue dos filas. Todo lo que quede fuera es del "
        "asesor del resto del tiempo."
    )
    franjas = _editor_franjas(
        actuales.get("franjas_fijas") or [FRANJA_POR_DEFECTO], f"{clave}-franjas"
    )

    errores = [] if fija else ["Elija el asesor con horario fijo."]
    errores += [] if resto else ["Elija el asesor del resto del tiempo."]
    if franjas and isinstance(franjas[0], str):
        errores += franjas
    if errores:
        return errores
    return {"persona_fija_id": fija, "franjas_fijas": franjas, "persona_resto_id": resto}


@registrar("franjas_completas")
def formulario_franjas_completas(personas, actuales, clave):
    st.caption(
        "Una fila por franja, en hora de España. Lo que no caiga en ninguna franja "
        "queda sin asignar."
    )
    franjas = _editor_franjas(
        (actuales or {}).get("franjas") or [FRANJA_POR_DEFECTO], f"{clave}-franjas", personas
    )
    if franjas and isinstance(franjas[0], str):
        return franjas
    return {"franjas": franjas}
