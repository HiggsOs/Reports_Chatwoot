"""Lo que cobró de verdad cada proveedor, para comprobar los precios configurados.

Ningún proveedor publica sus precios por API: el panel los lee de la
configuración. Lo que sí se puede leer, con una clave de administrador, es lo
cobrado y los minutos transcritos por modelo. De ahí sale el precio por minuto
real, que se compara con el configurado.

Cada proveedor con API de facturación tiene su fuente (patrón Adapter), que se
registra igual que las estrategias.
"""

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import ClassVar, Protocol

from pydantic import BaseModel, ConfigDict

from panel.transcripcion.base import EstrategiaTranscripcion, TranscripcionError

# Una diferencia mayor que esta entre el precio real y el configurado se avisa.
TOLERANCIA = Decimal("0.05")


class FacturacionError(TranscripcionError):
    """El proveedor no devolvió lo cobrado."""


class FacturacionNoDisponible(FacturacionError):
    """Falta la configuración (por ejemplo, la clave de administrador)."""


class CobroModelo(BaseModel):
    model_config = ConfigDict(frozen=True)

    modelo: str
    segundos: float  # de audio, según el proveedor
    costo: Decimal | None  # None si el proveedor no informó cobro para el modelo


class FuenteFacturacion(Protocol):
    proveedor: ClassVar[str]  # el `nombre` de la estrategia a la que corresponde

    def cobrado(self, desde: datetime, hasta: datetime) -> list[CobroModelo]:
        """Lo cobrado en [desde, hasta), por modelo de transcripción."""
        ...


class FabricaFacturacion(Protocol):
    proveedor: ClassVar[str]

    @classmethod
    def desde_config(cls, valores: Mapping[str, str]) -> FuenteFacturacion: ...


class PrecioReal(BaseModel):
    modelo: str
    minutos: float
    cobrado: Decimal | None
    precio_real: Decimal | None  # USD por minuto
    precio_configurado: Decimal | None
    diferencia: Decimal | None  # (real - configurado) / configurado

    @property
    def desviado(self) -> bool:
        return self.diferencia is not None and abs(self.diferencia) > TOLERANCIA


_FABRICAS: dict[str, FabricaFacturacion] = {}


def registrar(clase):
    if clase.proveedor in _FABRICAS:
        raise ValueError(f"Ya hay una fuente de facturación para {clase.proveedor!r}.")
    _FABRICAS[clase.proveedor] = clase
    return clase


def disponibles(valores: Mapping[str, str]) -> dict[str, FuenteFacturacion]:
    """Las fuentes que se pueden usar con esta configuración, por proveedor."""
    armadas = {}
    for proveedor, fabrica in _FABRICAS.items():
        try:
            armadas[proveedor] = fabrica.desde_config(valores)
        except FacturacionNoDisponible:
            continue
    return armadas


def _precio_configurado(estrategia: EstrategiaTranscripcion | None, modelo: str) -> Decimal | None:
    if estrategia is None or modelo not in estrategia.modelos:
        return None
    return estrategia.con_modelo(modelo).costo_estimado(60)


def comparar(
    cobros: list[CobroModelo], estrategia: EstrategiaTranscripcion | None
) -> list[PrecioReal]:
    """El precio por minuto que se cobró de verdad, al lado del configurado."""
    filas = []
    for cobro in sorted(cobros, key=lambda c: c.modelo):
        minutos = Decimal(str(cobro.segundos)) / 60
        real = None
        if cobro.costo is not None and minutos > 0:
            real = (cobro.costo / minutos).quantize(Decimal("0.0001"))
        configurado = _precio_configurado(estrategia, cobro.modelo)
        diferencia = None
        if real is not None and configurado:
            diferencia = ((real - configurado) / configurado).quantize(Decimal("0.001"))
        filas.append(
            PrecioReal(
                modelo=cobro.modelo,
                minutos=round(float(minutos), 1),
                cobrado=cobro.costo,
                precio_real=real,
                precio_configurado=configurado,
                diferencia=diferencia,
            )
        )
    return filas
