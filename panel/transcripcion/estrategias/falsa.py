"""Estrategia falsa: un texto fijo, sin red ni costo.

Para desarrollo y pruebas (TRANSCRIPCION_PROVEEDOR=falsa). Se puede configurar
para que falle o para que no tenga ciertas capacidades.
"""

from collections.abc import Mapping
from decimal import Decimal

from panel.transcripcion.base import (
    AudioPreparado,
    Capacidades,
    OpcionesTranscripcion,
    Segmento,
    Transcripcion,
    TranscripcionError,
    TranscripcionNoDisponible,
)
from panel.transcripcion.registro import registrar

PRECIO_POR_MINUTO = Decimal("0")


@registrar
class EstrategiaFalsa:
    nombre = "falsa"
    titulo = "Falsa (para pruebas)"

    def __init__(
        self,
        diarizacion: bool = True,
        marcas_de_tiempo: bool = True,
        tamano_max_bytes: int | None = None,
        error: str | None = None,
        modelo: str = "texto-fijo",
        otros_modelos: tuple[str, ...] = (),
    ) -> None:
        self._capacidades = Capacidades(
            diarizacion=diarizacion,
            marcas_de_tiempo=marcas_de_tiempo,
            tamano_max_bytes=tamano_max_bytes,
        )
        self._error = error
        self._modelo = modelo
        self._otros = tuple(m for m in otros_modelos if m != modelo)
        self.recibidos: list[AudioPreparado] = []

    @classmethod
    def desde_config(cls, valores: Mapping[str, str]) -> "EstrategiaFalsa":
        return cls()

    @property
    def modelo(self) -> str:
        return self._modelo

    @property
    def modelos(self) -> tuple[str, ...]:
        return (self._modelo, *self._otros)

    def con_modelo(self, modelo: str) -> "EstrategiaFalsa":
        if modelo == self._modelo:
            return self
        if modelo not in self._otros:
            raise TranscripcionNoDisponible(f"La estrategia falsa no tiene el modelo {modelo!r}.")
        otra = EstrategiaFalsa(
            self._capacidades.diarizacion,
            self._capacidades.marcas_de_tiempo,
            self._capacidades.tamano_max_bytes,
            self._error,
            modelo,
            self.modelos,
        )
        otra.recibidos = self.recibidos  # para ver en las pruebas qué se pidió
        return otra

    @property
    def capacidades(self) -> Capacidades:
        return self._capacidades

    def transcribir(self, audio: AudioPreparado, opciones: OpcionesTranscripcion) -> Transcripcion:
        self.recibidos.append(audio)
        if self._error:
            raise TranscripcionError(self._error)
        duracion = audio.duracion_s or 4.0
        mitad = duracion / 2
        marcas = self._capacidades.marcas_de_tiempo
        if audio.hablante is not None:
            segmentos = [
                Segmento(
                    hablante=audio.hablante,
                    inicio=0.0 if marcas else None,
                    fin=mitad if marcas else None,
                    texto=f"Texto del {audio.hablante}.",
                )
            ]
        else:
            diariza = self._capacidades.diarizacion
            segmentos = [
                Segmento(
                    hablante="desconocido",
                    etiqueta="A" if diariza else None,
                    inicio=0.0 if marcas else None,
                    fin=mitad if marcas else None,
                    texto="Buenos días, servicio de grúas.",
                ),
                Segmento(
                    hablante="desconocido",
                    etiqueta="B" if diariza else None,
                    inicio=mitad if marcas else None,
                    fin=duracion if marcas else None,
                    texto="Necesito una grúa.",
                ),
            ]
        return Transcripcion(
            proveedor=self.nombre,
            modelo=self.modelo,
            idioma=opciones.idioma,
            segmentos=segmentos,
            duracion_audio=audio.duracion_s,
            costo_estimado=self.costo_estimado(audio.duracion_s),
        )

    def costo_estimado(self, duracion_s: float | None) -> Decimal | None:
        return PRECIO_POR_MINUTO
