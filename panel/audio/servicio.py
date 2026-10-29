"""Escuchar una llamada, guardar su audio y borrarlo al cumplir el plazo.

Estrategia mixta: el audio se pide a CloudTalk recién cuando alguien escucha
la llamada, y entonces se guarda en MP3 en el almacén por AUDIO_RETENCION_DIAS
(contados desde la fecha de la llamada). Sin almacén configurado, se escucha
igual pero no se guarda nada.

La red (CloudTalk, el almacén, ffmpeg) se usa siempre fuera de una transacción
de la base, para que las transacciones duren poco.
"""

import logging
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Protocol

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from cloudtalk import CloudTalkError, GrabacionVencida
from panel.asignacion.servicio import ZONA_OPERACION_POR_DEFECTO
from panel.audio import conversion
from panel.audio.almacen import AlmacenAudio, AlmacenError
from panel.db.base import unidad_de_trabajo
from panel.db.modelos import (
    AUDIO_ELIMINADO,
    AUDIO_GUARDADO,
    AUDIO_PENDIENTE,
    AUDIO_SIN_GRABACION,
    AUDIO_VENCIDO,
    AudioPendiente,
    Llamada,
)

registro = logging.getLogger(__name__)

RETENCION_DIAS_POR_DEFECTO = 90


class FuenteGrabaciones(Protocol):
    def grabacion(self, id_externo: str) -> bytes | None:
        """El audio original, o None si no hay. Lanza GrabacionVencida si la
        plataforma ya lo borró."""
        ...


class ResultadoAudio(BaseModel):
    mp3: bytes | None = None
    # Mensaje para la persona: por qué no hay audio, o un aviso.
    mensaje: str = ""
    # El MP3 quedó pendiente de subir: quien lo muestra llama después a
    # subir_pendiente(), para que la subida no demore la reproducción.
    pendiente_de_subir: bool = False


class ResumenSubidas(BaseModel):
    subidos: int = 0
    fallidos: int = 0


class ResumenRetencion(BaseModel):
    borrados: int = 0
    fallidos: int = 0


def ruta_de(llamada: Llamada, zona=ZONA_OPERACION_POR_DEFECTO) -> str:
    inicio = llamada.inicio.astimezone(zona)
    return f"cloudtalk/{inicio:%Y}/{inicio:%m}/{llamada.id_externo}.mp3"


class ServicioAudio:
    def __init__(
        self,
        fabrica: sessionmaker[Session],
        fuente: FuenteGrabaciones,
        almacen: AlmacenAudio | None,
        retencion_dias: int = RETENCION_DIAS_POR_DEFECTO,
        ahora: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._fabrica = fabrica
        self._fuente = fuente
        self._almacen = almacen
        self._retencion = timedelta(days=retencion_dias)
        self._ahora = ahora

    @property
    def guarda_audios(self) -> bool:
        return self._almacen is not None

    # --- Escuchar ------------------------------------------------------------

    def escuchar(self, llamada_id: int) -> ResultadoAudio:
        with unidad_de_trabajo(self._fabrica) as sesion:
            llamada = sesion.get(Llamada, llamada_id)
            if llamada is None:
                return ResultadoAudio(mensaje="La llamada no existe.")
            estado, ruta, id_externo = llamada.audio_estado, llamada.audio_ruta, llamada.id_externo
            grabada, inicio = llamada.grabada, llamada.inicio
            pendiente = sesion.get(AudioPendiente, llamada_id)
            contenido_pendiente = pendiente.contenido if pendiente else None

        if estado == AUDIO_PENDIENTE and contenido_pendiente is not None:
            return ResultadoAudio(mp3=contenido_pendiente, pendiente_de_subir=True)
        if estado == AUDIO_GUARDADO and ruta and self._almacen is not None:
            try:
                return ResultadoAudio(mp3=self._almacen.bajar(ruta))
            except AlmacenError as error:
                registro.warning("No se pudo bajar %s del almacén: %s", ruta, error)
                aviso = "No se pudo leer el audio guardado; se trajo de nuevo de CloudTalk."
                return self._traer(llamada_id, id_externo, inicio, guardar=False, aviso=aviso)
        if estado == AUDIO_SIN_GRABACION:
            return ResultadoAudio(mensaje="CloudTalk no tiene grabación de esta llamada.")
        if estado == AUDIO_VENCIDO:
            return ResultadoAudio(mensaje="CloudTalk ya borró la grabación de esta llamada.")
        if not grabada:
            return ResultadoAudio(mensaje="La llamada no se grabó.")

        # Una llamada más vieja que el plazo (o cuyo audio ya se borró al
        # cumplirlo) se escucha si CloudTalk todavía la tiene, pero no se guarda.
        vencida_aqui = estado == AUDIO_ELIMINADO or inicio < self._ahora() - self._retencion
        aviso = ""
        if vencida_aqui:
            aviso = (
                f"El audio guardado se borra a los {self._retencion.days} días; este "
                "se trajo de CloudTalk y no se vuelve a guardar."
            )
        elif self._almacen is None:
            aviso = "No hay almacén de audios configurado: el audio no se guarda."
        return self._traer(
            llamada_id, id_externo, inicio, guardar=not vencida_aqui and self._almacen is not None,
            aviso=aviso,
        )

    def _traer(self, llamada_id, id_externo, inicio, guardar: bool, aviso: str) -> ResultadoAudio:
        try:
            original = self._fuente.grabacion(id_externo)
        except GrabacionVencida:
            self._marcar(llamada_id, AUDIO_VENCIDO)
            return ResultadoAudio(mensaje="CloudTalk ya borró la grabación de esta llamada.")
        except CloudTalkError as error:
            return ResultadoAudio(mensaje=f"No se pudo traer el audio de CloudTalk: {error}")
        if original is None:
            self._marcar(llamada_id, AUDIO_SIN_GRABACION)
            return ResultadoAudio(mensaje="CloudTalk no tiene grabación de esta llamada.")

        try:
            canales = conversion.analizar(original).canales
            mp3 = conversion.a_mp3(original, canales)
        except conversion.AudioInvalido as error:
            return ResultadoAudio(mensaje=f"El audio de CloudTalk no se pudo convertir: {error}")

        if not guardar:
            return ResultadoAudio(mp3=mp3, mensaje=aviso)

        with unidad_de_trabajo(self._fabrica) as sesion:
            llamada = sesion.get(Llamada, llamada_id)
            # Si dos personas abren la misma llamada a la vez, gana la primera.
            sesion.execute(
                insert(AudioPendiente)
                .values(llamada_id=llamada_id, contenido=mp3)
                .on_conflict_do_nothing(index_elements=["llamada_id"])
            )
            llamada.audio_estado = AUDIO_PENDIENTE
            llamada.audio_ruta = ruta_de(llamada)
            llamada.audio_canales = canales
            llamada.audio_bytes = len(mp3)
        return ResultadoAudio(mp3=mp3, mensaje=aviso, pendiente_de_subir=True)

    def _marcar(self, llamada_id: int, estado: str) -> None:
        with unidad_de_trabajo(self._fabrica) as sesion:
            sesion.get(Llamada, llamada_id).audio_estado = estado

    # --- Subir ---------------------------------------------------------------

    def subir_pendiente(self, llamada_id: int) -> bool:
        """Sube un MP3 pendiente. Si falla, queda pendiente para el próximo ciclo."""
        if self._almacen is None:
            return False
        with unidad_de_trabajo(self._fabrica) as sesion:
            pendiente = sesion.get(AudioPendiente, llamada_id)
            llamada = sesion.get(Llamada, llamada_id)
            if pendiente is None or llamada is None or not llamada.audio_ruta:
                return False
            contenido, ruta = pendiente.contenido, llamada.audio_ruta

        try:
            self._almacen.subir(ruta, contenido)
        except AlmacenError as error:
            registro.warning("No se pudo subir %s: %s", ruta, error)
            with unidad_de_trabajo(self._fabrica) as sesion:
                pendiente = sesion.get(AudioPendiente, llamada_id)
                if pendiente is not None:
                    pendiente.intentos += 1
                    pendiente.ultimo_error = str(error)[:2000]
            return False

        with unidad_de_trabajo(self._fabrica) as sesion:
            llamada = sesion.get(Llamada, llamada_id)
            llamada.audio_estado = AUDIO_GUARDADO
            llamada.audio_guardado_en = self._ahora()
            pendiente = sesion.get(AudioPendiente, llamada_id)
            if pendiente is not None:
                sesion.delete(pendiente)
        return True

    def subir_pendientes(self) -> ResumenSubidas:
        with unidad_de_trabajo(self._fabrica) as sesion:
            ids = list(sesion.scalars(select(AudioPendiente.llamada_id).order_by(AudioPendiente.creado_en)))
        resumen = ResumenSubidas()
        for llamada_id in ids:
            if self.subir_pendiente(llamada_id):
                resumen.subidos += 1
            else:
                resumen.fallidos += 1
        return resumen

    # --- Retención -----------------------------------------------------------

    def aplicar_retencion(self) -> ResumenRetencion:
        """Borra del almacén los audios de llamadas más viejas que el plazo.

        La transcripción y las auditorías no se tocan. (Con las auditorías,
        en la etapa 7, se suma la excepción de no borrar el audio de una
        auditoría en borrador.)
        """
        limite = self._ahora() - self._retencion
        with unidad_de_trabajo(self._fabrica) as sesion:
            vencidas = list(
                sesion.execute(
                    select(Llamada.id, Llamada.audio_estado, Llamada.audio_ruta).where(
                        Llamada.audio_estado.in_([AUDIO_GUARDADO, AUDIO_PENDIENTE]),
                        Llamada.inicio < limite,
                    )
                )
            )
        resumen = ResumenRetencion()
        for llamada_id, estado, ruta in vencidas:
            if estado == AUDIO_GUARDADO and ruta and self._almacen is not None:
                try:
                    self._almacen.borrar(ruta)
                except AlmacenError as error:
                    registro.warning("No se pudo borrar %s: %s", ruta, error)
                    resumen.fallidos += 1
                    continue
            with unidad_de_trabajo(self._fabrica) as sesion:
                llamada = sesion.get(Llamada, llamada_id)
                llamada.audio_estado = AUDIO_ELIMINADO
                llamada.audio_ruta = None
                pendiente = sesion.get(AudioPendiente, llamada_id)
                if pendiente is not None:
                    sesion.delete(pendiente)
            resumen.borrados += 1
        if resumen.borrados:
            registro.info("Retención de audios: %s", resumen.model_dump())
        return resumen
