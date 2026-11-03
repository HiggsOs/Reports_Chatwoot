"""Raíz de composición de la API: arma la configuración y los servicios.

La configuración es el entorno con los ajustes del panel encima (como en la
sincronización). Al guardar un ajuste, `recargar()` descarta lo armado y la
próxima petición lo vuelve a armar con los valores nuevos.
"""

import logging
import os
import threading
from collections.abc import Mapping

from sqlalchemy.orm import Session, sessionmaker

from config import Config, ConfigError, cargar_config
from panel.ajustes import LecturaAjustes, entorno_efectivo
from panel.audio.servicio import ServicioAudio
from panel.composicion import servicio_audio, servicio_transcripcion
from panel.db.base import crear_fabrica_sesiones, crear_motor
from panel.transcripcion.servicio import ServicioTranscripcion

registro = logging.getLogger(__name__)


class Contenedor:
    def __init__(self, entorno: Mapping[str, str] | None = None) -> None:
        self.entorno = dict(os.environ if entorno is None else entorno)
        # Solo el entorno: alcanza para conectarse a la base y validar el login.
        self.base = cargar_config(self.entorno)
        self.fabrica: sessionmaker[Session] = crear_fabrica_sesiones(crear_motor(self.base.database_url))
        self._candado = threading.Lock()
        self._armado: tuple | None = None

    def _armar(self) -> tuple:
        efectivo, lectura = entorno_efectivo(self.entorno, self.fabrica)
        error = None
        try:
            cfg = cargar_config(efectivo)
        except ConfigError as excepcion:
            registro.error("Ajustes del panel inválidos, se usa el entorno: %s", excepcion)
            cfg, error = self.base, str(excepcion)
        audio = servicio_audio(self.fabrica, cfg)
        transcripcion = servicio_transcripcion(self.fabrica, cfg, audio)
        return cfg, lectura, error, audio, transcripcion

    def _obtener(self) -> tuple:
        with self._candado:
            if self._armado is None:
                self._armado = self._armar()
            return self._armado

    @property
    def cfg(self) -> Config:
        return self._obtener()[0]

    @property
    def lectura(self) -> LecturaAjustes:
        return self._obtener()[1]

    @property
    def error_ajustes(self) -> str | None:
        return self._obtener()[2]

    @property
    def audio(self) -> ServicioAudio | None:
        return self._obtener()[3]

    @property
    def transcripcion(self) -> ServicioTranscripcion | None:
        return self._obtener()[4]

    def recargar(self) -> None:
        with self._candado:
            self._armado = None
