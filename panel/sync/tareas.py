"""Tareas de mantenimiento que corren en cada ciclo de sincronización.

Como los sincronizadores, anotan su resultado en `puntos_sincronizacion`
(con su nombre como fuente), así se ven en Inicio.
"""

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import datetime
from typing import ClassVar

from pydantic import BaseModel
from sqlalchemy.orm import Session, sessionmaker

from panel.asignacion.servicio import ZONA_OPERACION_POR_DEFECTO
from panel.audio.servicio import ServicioAudio
from panel.db.base import unidad_de_trabajo
from panel.db.modelos import PuntoSincronizacion
from panel.sync.sincronizadores import ResultadoSincronizacion, ahora_utc
from panel.transcripcion.servicio import ServicioTranscripcion, borrar_transcripciones_vencidas

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
    """Transcribe hasta TRANSCRIPCION_POR_CICLO pedidos de la cola."""

    nombre = "transcripciones"

    def __init__(self, fabrica, transcripcion: ServicioTranscripcion, limite: int, ahora=ahora_utc):
        super().__init__(fabrica, ahora)
        self._transcripcion = transcripcion
        self._limite = limite

    def correr(self):
        return self._transcripcion.procesar_cola(self._limite)


class RetencionDeTranscripciones(UnaVezPorDia):
    """Borra las transcripciones de llamadas más viejas que el plazo."""

    nombre = "retencion_transcripciones"

    def __init__(self, fabrica, dias: int, ahora=ahora_utc) -> None:
        super().__init__(fabrica, ahora)
        self._dias = dias

    def correr(self):
        return borrar_transcripciones_vencidas(self._fabrica, self._dias, self._ahora())
