"""Registro de estrategias de transcripción por nombre.

Agregar un proveedor es escribir su clase en `estrategias/` y decorarla con
`@registrar`; ni el servicio ni la base cambian.
"""

from collections.abc import Mapping

from panel.transcripcion.base import (
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
    fabrica = _FABRICAS.get(nombre)
    return fabrica.titulo if fabrica else nombre


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
