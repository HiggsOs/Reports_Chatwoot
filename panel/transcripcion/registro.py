"""Registro de estrategias de transcripción por nombre.

Agregar un proveedor es escribir su clase en `estrategias/` y decorarla con
`@registrar`; ni el servicio ni la base cambian.
"""

from collections.abc import Mapping
from decimal import Decimal

from panel.transcripcion.base import (
    Capacidades,
    EstrategiaTranscripcion,
    FabricaEstrategia,
    TranscripcionNoDisponible,
)

_FABRICAS: dict[str, FabricaEstrategia] = {}


def registrar(clase):
    if clase.nombre in _FABRICAS:
        raise ValueError(f"Ya hay una estrategia de transcripción llamada {clase.nombre!r}.")
    _FABRICAS[clase.nombre] = clase
    return clase


def nombres() -> list[str]:
    return list(_FABRICAS)


def titulo(nombre: str) -> str:
    """«openai» → «OpenAI»; «openai:whisper-1» → «OpenAI · whisper-1»."""
    proveedor, _, modelo = nombre.partition(":")
    fabrica = _FABRICAS.get(proveedor)
    base = fabrica.titulo if fabrica else proveedor
    return f"{base} · {modelo}" if modelo else base


def proveedor_de(nombre: str) -> str:
    return nombre.partition(":")[0]


def variable_clave(nombre: str) -> str | None:
    """La variable (y el ajuste del panel) con la clave de API del proveedor."""
    return getattr(_FABRICAS.get(nombre), "variable_clave", None)


def modelos_conocidos(nombre: str) -> dict[str, Capacidades]:
    """Los modelos que el proveedor sabe usar y qué devuelve cada uno."""
    return dict(getattr(_FABRICAS.get(nombre), "modelos_conocidos", {}) or {})


def crear_modelo(
    nombre: str,
    valores: Mapping[str, str],
    modelo: str,
    precio_minuto: Decimal | None,
    redondeo: str = "segundo",
) -> EstrategiaTranscripcion:
    """Arma la estrategia para un modelo y un precio elegidos en el panel.

    La estrategia declara en `variables_modelo` qué variables leen el modelo,
    el precio y el redondeo; aquí solo se pisan esas, y el resto (la clave, la
    URL) sale de la configuración como siempre.
    """
    fabrica = _FABRICAS.get(nombre)
    if fabrica is None:
        raise TranscripcionNoDisponible(
            f"No hay una estrategia de transcripción llamada {nombre!r}."
        )
    variables = getattr(fabrica, "variables_modelo", None)
    if variables is None:
        raise TranscripcionNoDisponible(f"{fabrica.titulo} no permite elegir el modelo.")
    variable_modelo, variable_precio, variable_redondeo = variables
    return fabrica.desde_config(
        {
            **valores,
            variable_modelo: modelo,
            variable_precio: "" if precio_minuto is None else str(precio_minuto),
            variable_redondeo: redondeo,
        }
    )


def resolver(nombre: str | None, disponibles: Mapping[str, object]) -> str | None:
    """El nombre con que está armada la estrategia pedida.

    Un pedido viejo dice solo «openai»; si las estrategias están armadas por
    modelo («openai:whisper-1»), vale la primera de ese proveedor.
    """
    if not nombre:
        return None
    if nombre in disponibles:
        return nombre
    return next((clave for clave in disponibles if proveedor_de(clave) == nombre), None)


def crear(nombre: str, valores: Mapping[str, str]) -> EstrategiaTranscripcion:
    """Arma la estrategia con la configuración (las variables de entorno)."""
    fabrica = _FABRICAS.get(nombre)
    if fabrica is None:
        raise TranscripcionNoDisponible(
            f"No hay una estrategia de transcripción llamada {nombre!r}."
        )
    return fabrica.desde_config(valores)


def disponibles(valores: Mapping[str, str]) -> dict[str, EstrategiaTranscripcion]:
    """Las estrategias que se pueden usar con esta configuración."""
    armadas = {}
    for nombre in _FABRICAS:
        try:
            armadas[nombre] = crear(nombre, valores)
        except TranscripcionNoDisponible:
            continue
    return armadas


def probar_clave(nombre: str, valores: Mapping[str, str]) -> str:
    """Comprueba la clave sin transcribir. Lanza TranscripcionError si falla."""
    fabrica = _FABRICAS.get(nombre)
    probar = getattr(fabrica, "probar_clave", None)
    if probar is None:
        raise TranscripcionNoDisponible("Este proveedor no tiene una prueba de conexión.")
    return probar(valores)
