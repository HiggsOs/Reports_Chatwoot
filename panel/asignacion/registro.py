"""Registro de estrategias de asignación por nombre.

Agregar una estrategia es escribir su clase en `estrategias/` y decorarla con
`@registrar`; ni el servicio ni la base cambian.
"""

from panel.asignacion.base import EstrategiaAsignacion

_ESTRATEGIAS: dict[str, EstrategiaAsignacion] = {}


class EstrategiaDesconocida(LookupError):
    """La regla nombra una estrategia que no está registrada."""


def registrar(clase):
    if clase.nombre in _ESTRATEGIAS:
        raise ValueError(f"Ya hay una estrategia registrada como {clase.nombre!r}.")
    _ESTRATEGIAS[clase.nombre] = clase()
    return clase


def obtener(nombre: str) -> EstrategiaAsignacion:
    try:
        return _ESTRATEGIAS[nombre]
    except KeyError:
        raise EstrategiaDesconocida(
            f"No hay una estrategia de asignación llamada {nombre!r}."
        ) from None


def disponibles(incluir_retiradas: bool = False) -> list[EstrategiaAsignacion]:
    return [
        estrategia
        for estrategia in _ESTRATEGIAS.values()
        if incluir_retiradas or not estrategia.retirada
    ]
