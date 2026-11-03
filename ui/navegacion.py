"""Registro de páginas e inyección de dependencias por nombre.

Cada pantalla se declara una vez en `PAGINAS` (sección, título, ruta, icono y
la función que la dibuja). `armar` le pasa a cada función solo lo que pide su
firma, tomado de las dependencias que arma app.py (la fábrica de sesiones, la
configuración, los servicios…). Agregar una pantalla es escribir su módulo en
`ui/paginas/` y sumar una línea aquí; app.py no cambia.

Las páginas que enlazan a otras reciben `paginas`: el diccionario ruta → página,
que se llena antes de navegar.
"""

import inspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from functools import partial

import streamlit as st

from ui.paginas import (
    asesores,
    cuentas,
    en_vivo,
    general,
    historial,
    inicio,
    interacciones,
    transcripcion,
)


@dataclass(frozen=True)
class EntradaPagina:
    seccion: str
    titulo: str
    ruta: str
    icono: str  # nombre de Material Symbols
    funcion: Callable[..., None]
    # Argumentos fijos de esta entrada (por ejemplo, qué Vista muestra).
    fijos: Mapping[str, object] = field(default_factory=dict)
    inicial: bool = False


OPERACION, CONFIGURACION, EN_VIVO = "Operación", "Configuración", "Reportes en vivo"

PAGINAS: tuple[EntradaPagina, ...] = (
    EntradaPagina(OPERACION, "Inicio", "inicio", "home", inicio.mostrar, inicial=True),
    EntradaPagina(OPERACION, "Sin asignar", "sin-asignar", "assignment_late", interacciones.sin_asignar),
    EntradaPagina(OPERACION, "Llamadas", "llamadas", "call", interacciones.pagina, {"tipo": "llamada"}),
    EntradaPagina(OPERACION, "Conversaciones", "conversaciones", "chat", interacciones.pagina,
                  {"tipo": "conversacion"}),
    EntradaPagina(OPERACION, "Historial del cliente", "historial", "history", historial.mostrar),
    EntradaPagina(CONFIGURACION, "General", "general", "settings", general.mostrar),
    EntradaPagina(CONFIGURACION, "Asesores", "asesores", "group", asesores.mostrar),
    EntradaPagina(CONFIGURACION, "Cuentas", "cuentas", "account_tree", cuentas.mostrar),
    EntradaPagina(CONFIGURACION, "Transcripción", "transcripcion", "graphic_eq", transcripcion.pagina),
    EntradaPagina(EN_VIVO, "Reporte de Chatwoot", "reporte-chatwoot", "forum", en_vivo.reporte_chatwoot),
    EntradaPagina(EN_VIVO, "Transcripciones de Ringover", "transcripciones-ringover", "mic",
                  en_vivo.transcripciones_ringover),
    EntradaPagina(EN_VIVO, "Transcripciones de CloudTalk", "transcripciones-cloudtalk",
                  "record_voice_over", en_vivo.transcripciones_cloudtalk),
)


class DependenciaFaltante(TypeError):
    """Una página pide algo que app.py no armó."""


def _argumentos(funcion: Callable, dependencias: Mapping[str, object], fijos: Mapping[str, object]) -> dict:
    argumentos = {}
    for nombre, parametro in inspect.signature(funcion).parameters.items():
        if nombre in fijos:
            argumentos[nombre] = fijos[nombre]
        elif nombre in dependencias:
            argumentos[nombre] = dependencias[nombre]
        elif parametro.default is inspect.Parameter.empty:
            raise DependenciaFaltante(f"{funcion.__module__}.{funcion.__name__} pide «{nombre}».")
    return argumentos


def armar(dependencias: Mapping[str, object], entradas=PAGINAS) -> dict[str, list[st.Page]]:
    """Las secciones de `st.navigation`, con cada página ya armada."""
    paginas: dict[str, st.Page] = {}
    disponibles = {**dependencias, "paginas": paginas}
    secciones: dict[str, list[st.Page]] = {}
    for entrada in entradas:
        funcion = partial(entrada.funcion, **_argumentos(entrada.funcion, disponibles, entrada.fijos))
        pagina = st.Page(
            funcion,
            title=entrada.titulo,
            url_path=entrada.ruta,
            icon=f":material/{entrada.icono}:",
            default=entrada.inicial,
        )
        paginas[entrada.ruta] = pagina
        secciones.setdefault(entrada.seccion, []).append(pagina)
    return secciones
