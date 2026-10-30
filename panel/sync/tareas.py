"""Tareas de mantenimiento que corren en cada ciclo de sincronización.

Como los sincronizadores, anotan su resultado en `puntos_sincronizacion`
(con su nombre como fuente), así se ven en Inicio.
"""

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import datetime, timedelta
from decimal import Decimal
from typing import ClassVar

from pydantic import BaseModel
from sqlalchemy.orm import Session, sessionmaker

from panel.asignacion.servicio import ZONA_OPERACION_POR_DEFECTO
from panel.audio.servicio import ServicioAudio
from panel.db.base import unidad_de_trabajo
from panel.db.modelos import PuntoSincronizacion
from panel.sync.sincronizadores import ResultadoSincronizacion, ahora_utc
from panel.transcripcion import consultas as consultas_transcripcion
from panel.transcripcion.servicio import (
    ResumenCola,
    ServicioTranscripcion,
    borrar_transcripciones_vencidas,
)

registro = logging.getLogger(__name__)


class Tarea(ABC):
    nombre: ClassVar[str]

    def __init__(self, fabrica: sessionmaker[Session], ahora: Callable[[], datetime] = ahora_utc):
        self._fabrica = fabrica
        self._ahora = ahora

    def ejecutar(self, desde=None, hasta=None) -> ResultadoSincronizacion:
        """El rango se ignora: se recibe para correr junto a los sincronizadores."""
        momento = self._ahora()
        with unidad_de_trabajo(self._fabrica) as sesion:
            punto = sesion.get(PuntoSincronizacion, self.nombre)
            if punto is None:
                punto = PuntoSincronizacion(fuente=self.nombre)
                sesion.add(punto)
            if not self.toca_correr(punto.ultimo_exito, momento):
                return ResultadoSincronizacion(fuente=self.nombre, resumen={"omitida": True})
            punto.ultimo_intento = momento

        try:
            resumen = self.correr().model_dump()
        except Exception as error:
            registro.exception("Falló la tarea %s", self.nombre)
            mensaje = f"{type(error).__name__}: {error}"[:2000]
            with unidad_de_trabajo(self._fabrica) as sesion:
                sesion.get(PuntoSincronizacion, self.nombre).ultimo_error = mensaje
            return ResultadoSincronizacion(fuente=self.nombre, error=mensaje)

        with unidad_de_trabajo(self._fabrica) as sesion:
            punto = sesion.get(PuntoSincronizacion, self.nombre)
            punto.ultimo_exito = self._ahora()
            punto.ultimo_error = None
            punto.resumen = resumen
        return ResultadoSincronizacion(fuente=self.nombre, resumen=resumen)

    def toca_correr(self, ultimo_exito: datetime | None, ahora: datetime) -> bool:
        return True

    @abstractmethod
    def correr(self) -> BaseModel: ...


class SubirAudiosPendientes(Tarea):
    """Reintenta subir al almacén los audios escuchados que quedaron pendientes."""

    nombre = "audios_pendientes"

    def __init__(self, fabrica, audio: ServicioAudio, ahora=ahora_utc) -> None:
        super().__init__(fabrica, ahora)
        self._audio = audio

    def correr(self):
        return self._audio.subir_pendientes()


class UnaVezPorDia(Tarea):
    """Corre como mucho una vez por día, en hora de España."""

    def toca_correr(self, ultimo_exito, ahora):
        if ultimo_exito is None:
            return True
        zona = ZONA_OPERACION_POR_DEFECTO
        return ultimo_exito.astimezone(zona).date() < ahora.astimezone(zona).date()


class RetencionDeAudios(UnaVezPorDia):
    """Borra los audios de llamadas más viejas que el plazo."""

    nombre = "retencion_audios"

    def __init__(self, fabrica, audio: ServicioAudio, ahora=ahora_utc) -> None:
        super().__init__(fabrica, ahora)
        self._audio = audio

    def correr(self):
        return self._audio.aplicar_retencion()


class ProcesarTranscripciones(Tarea):
    """Transcribe hasta TRANSCRIPCION_POR_CICLO pedidos de la cola.

    Con un tope mensual, no toma pedidos cuando lo estimado en el mes ya lo
    alcanzó: la cola queda en pausa hasta el mes siguiente o hasta subir el tope.
    """

    nombre = "transcripciones"

    def __init__(
        self,
        fabrica,
        transcripcion: ServicioTranscripcion,
        limite: int,
        tope_mensual: Decimal | None = None,
        ahora=ahora_utc,
    ):
        super().__init__(fabrica, ahora)
        self._transcripcion = transcripcion
        self._limite = limite
        self._tope = tope_mensual

    def correr(self):
        if self._tope is not None:
            with unidad_de_trabajo(self._fabrica) as sesion:
                gastado = consultas_transcripcion.gasto_del_mes(sesion, self._ahora())
            if gastado >= self._tope:
                registro.info("Cola de transcripción en pausa: %s de %s USD.", gastado, self._tope)
                return ResumenCola(pausada_por_tope=True)
        return self._transcripcion.procesar_cola(self._limite)


class ResumenEncolado(BaseModel):
    encoladas: int = 0


class EncolarLlamadasNuevas(Tarea):
    """Pide transcribir las llamadas grabadas de los últimos días que duran al
    menos TRANSCRIPCION_AUTO_MIN_SEGUNDOS. Nunca vuelve a pedir una que falló."""

    nombre = "transcripcion_automatica"
    VENTANA = timedelta(days=2)

    def __init__(self, fabrica, transcripcion: ServicioTranscripcion, min_segundos: int, ahora=ahora_utc):
        super().__init__(fabrica, ahora)
        self._transcripcion = transcripcion
        self._min_segundos = min_segundos

    def correr(self):
        with unidad_de_trabajo(self._fabrica) as sesion:
            ids = consultas_transcripcion.llamadas_para_encolar(
                sesion, self._ahora() - self.VENTANA, self._min_segundos
            )
        return ResumenEncolado(encoladas=self._transcripcion.encolar(ids) if ids else 0)


class RetencionDeTranscripciones(UnaVezPorDia):
    """Borra las transcripciones de llamadas más viejas que el plazo."""

    nombre = "retencion_transcripciones"

    def __init__(self, fabrica, dias: int, ahora=ahora_utc) -> None:
        super().__init__(fabrica, ahora)
        self._dias = dias

    def correr(self):
        return borrar_transcripciones_vencidas(self._fabrica, self._dias, self._ahora())
