"""Contrato común de las estrategias de transcripción (patrón Strategy).

Cada proveedor (OpenAI hoy; Alibaba u otros después) es una estrategia que
recibe un audio preparado y devuelve una `Transcripcion` con la forma común.
El resto del sistema nunca ve el formato de un proveedor.
"""

from collections.abc import Mapping
from decimal import Decimal
from typing import ClassVar, Literal, Protocol

from pydantic import BaseModel, ConfigDict

Hablante = Literal["agente", "cliente", "desconocido"]


class TranscripcionError(Exception):
    """El proveedor no pudo transcribir el audio."""


class TranscripcionNoDisponible(TranscripcionError):
    """La estrategia no está configurada (por ejemplo, falta su clave)."""


class Capacidades(BaseModel):
    model_config = ConfigDict(frozen=True)

    diarizacion: bool  # separa a los hablantes por sí misma
    marcas_de_tiempo: bool  # da inicio y fin de cada segmento
    tamano_max_bytes: int | None  # límite del archivo que acepta


class AudioPreparado(BaseModel):
    model_config = ConfigDict(frozen=True)

    contenido: bytes
    nombre_archivo: str  # la extensión le dice al proveedor el formato
    tipo_mime: str
    duracion_s: float | None
    # Si el audio es de una sola persona (un canal de un estéreo), quién es.
    hablante: Hablante | None = None


class OpcionesTranscripcion(BaseModel):
    model_config = ConfigDict(frozen=True)

    idioma: str = "es"
    vocabulario: tuple[str, ...] = ()  # nombres propios, marcas, productos


class Segmento(BaseModel):
    model_config = ConfigDict(frozen=True)

    hablante: Hablante
    # La etiqueta del proveedor («A», «B»…) cuando separó hablantes sin saber
    # quién es quién; sirve para que el auditor diga cuál es el agente.
    etiqueta: str | None = None
    inicio: float | None  # segundos desde el comienzo de la llamada
    fin: float | None
    texto: str


class Transcripcion(BaseModel):
    proveedor: str
    modelo: str
    idioma: str
    segmentos: list[Segmento]
    duracion_audio: float | None
    costo_estimado: Decimal | None

    @property
    def texto(self) -> str:
        return "\n".join(segmento.texto for segmento in self.segmentos)


class EstrategiaTranscripcion(Protocol):
    nombre: ClassVar[str]  # el que se guarda en la base; no cambia nunca
    titulo: ClassVar[str]

    @property
    def modelo(self) -> str: ...

    @property
    def capacidades(self) -> Capacidades: ...

    def transcribir(
        self, audio: AudioPreparado, opciones: OpcionesTranscripcion
    ) -> Transcripcion: ...

    def costo_estimado(self, duracion_s: float | None) -> Decimal | None:
        """None si no se conoce el precio: el panel no inventa costos."""
        ...


class FabricaEstrategia(Protocol):
    """Lo que se registra: arma la estrategia con la configuración.

    `desde_config` lanza TranscripcionNoDisponible si falta configuración.
    """

    nombre: ClassVar[str]
    titulo: ClassVar[str]

    @classmethod
    def desde_config(cls, valores: Mapping[str, str]) -> EstrategiaTranscripcion: ...
