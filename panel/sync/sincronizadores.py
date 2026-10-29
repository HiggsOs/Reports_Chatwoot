"""Sincronización de cada fuente hacia la base (patrón Template Method).

`Sincronizador.ejecutar` es el ciclo común: leer hasta dónde se llegó, traer
lo nuevo con un margen hacia atrás, guardarlo (con *upsert*, así repetir no
duplica nada), avanzar el punto y anotar el error si lo hubo. Cada fuente
solo define cómo trae y cómo guarda.
"""

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any, ClassVar

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from panel.db.base import unidad_de_trabajo
from panel.db.modelos import PuntoSincronizacion
from panel.fuentes.interacciones import FuenteConversaciones, FuenteLlamadas
from panel.servicios.interacciones import ServicioInteracciones

registro = logging.getLogger(__name__)

# Bloqueo de Postgres que impide que dos ciclos corran a la vez (el proceso
# `sync` y el botón «Sincronizar ahora» del panel).
CLAVE_BLOQUEO_SINCRONIZACION = 7_420_002


class ResultadoSincronizacion(BaseModel):
    fuente: str
    desde: datetime
    hasta: datetime
    resumen: dict[str, Any] = {}
    error: str | None = None


def ahora_utc() -> datetime:
    return datetime.now(timezone.utc)


class Sincronizador(ABC):
    fuente: ClassVar[str]

    def __init__(
        self,
        fabrica: sessionmaker[Session],
        desde_inicial: datetime,
        ahora: Callable[[], datetime] = ahora_utc,
    ) -> None:
        self._fabrica = fabrica
        self._desde_inicial = desde_inicial
        self._ahora = ahora

    def ejecutar(
        self, desde: datetime | None = None, hasta: datetime | None = None
    ) -> ResultadoSincronizacion:
        """Con `desde`, carga ese rango aunque ya esté sincronizado (historial)."""
        momento = self._ahora()
        hasta = hasta or momento
        with unidad_de_trabajo(self._fabrica) as sesion:
            punto = sesion.get(PuntoSincronizacion, self.fuente)
            if punto is None:
                punto = PuntoSincronizacion(fuente=self.fuente)
                sesion.add(punto)
            punto.ultimo_intento = momento
            anterior = punto.hasta
        if desde is None:
            desde = self.calcular_desde(anterior, hasta)

        try:
            datos = self.traer(desde, hasta)
            with unidad_de_trabajo(self._fabrica) as sesion:
                resumen = self.guardar(sesion, datos).model_dump()
        except Exception as error:
            registro.exception("Falló la sincronización de %s", self.fuente)
            mensaje = f"{type(error).__name__}: {error}"[:2000]
            with unidad_de_trabajo(self._fabrica) as sesion:
                sesion.get(PuntoSincronizacion, self.fuente).ultimo_error = mensaje
            return ResultadoSincronizacion(
                fuente=self.fuente, desde=desde, hasta=hasta, error=mensaje
            )

        with unidad_de_trabajo(self._fabrica) as sesion:
            punto = sesion.get(PuntoSincronizacion, self.fuente)
            # Una carga de historial no hace retroceder el punto.
            punto.hasta = max(anterior, hasta) if anterior else hasta
            punto.ultimo_exito = self._ahora()
            punto.ultimo_error = None
            punto.resumen = resumen
        registro.info("Sincronización de %s: %s", self.fuente, resumen)
        return ResultadoSincronizacion(
            fuente=self.fuente, desde=desde, hasta=hasta, resumen=resumen
        )

    def calcular_desde(self, anterior: datetime | None, hasta: datetime) -> datetime:
        return anterior if anterior is not None else self._desde_inicial

    @abstractmethod
    def traer(self, desde: datetime, hasta: datetime) -> Any: ...

    @abstractmethod
    def guardar(self, sesion: Session, datos: Any) -> BaseModel: ...


class SincronizadorLlamadas(Sincronizador):
    fuente = "cloudtalk"
    # Una llamada aparece en el historial al terminar: se relee un margen por
    # las que estaban en curso en el ciclo anterior.
    margen = timedelta(hours=2)

    def __init__(self, fabrica, fuente: FuenteLlamadas, desde_inicial, ahora=ahora_utc) -> None:
        super().__init__(fabrica, desde_inicial, ahora)
        self._fuente = fuente

    def calcular_desde(self, anterior, hasta):
        return anterior - self.margen if anterior is not None else self._desde_inicial

    def traer(self, desde, hasta):
        return self._fuente.llamadas(desde, hasta)

    def guardar(self, sesion, datos):
        return ServicioInteracciones(sesion).guardar_llamadas(datos)


class SincronizadorConversaciones(Sincronizador):
    fuente = "chatwoot"

    def __init__(
        self,
        fabrica,
        fuente: FuenteConversaciones,
        desde_inicial,
        dias_relectura: int,
        ahora=ahora_utc,
    ) -> None:
        super().__init__(fabrica, desde_inicial, ahora)
        self._fuente = fuente
        self._relectura = timedelta(days=dias_relectura)

    def calcular_desde(self, anterior, hasta):
        if anterior is None:
            return self._desde_inicial
        return min(anterior, hasta - self._relectura)

    def traer(self, desde, hasta):
        """Las conversaciones del rango y, de las nuevas o cambiadas, sus
        mensajes (para la dirección y el cierre). Los mensajes se piden fuera
        de la transacción de guardado, que así dura poco."""
        conversaciones = self._fuente.conversaciones(desde, hasta)
        with unidad_de_trabajo(self._fabrica) as sesion:
            guardadas = ServicioInteracciones(sesion).ultima_actividad_guardada(
                [c.id_externo for c in conversaciones]
            )
        datos = []
        for conversacion in conversaciones:
            cambio = (
                conversacion.id_externo not in guardadas
                or guardadas[conversacion.id_externo] != conversacion.ultima_actividad
            )
            mensajes = self._fuente.mensajes(conversacion.id_externo) if cambio else None
            datos.append((conversacion, mensajes))
        return datos

    def guardar(self, sesion, datos):
        return ServicioInteracciones(sesion).guardar_conversaciones(datos)


def ejecutar_ciclo(
    fabrica: sessionmaker[Session],
    sincronizadores: list[Sincronizador],
    desde: datetime | None = None,
    hasta: datetime | None = None,
) -> list[ResultadoSincronizacion] | None:
    """Corre cada sincronizador. Devuelve None si ya hay otro ciclo en curso."""
    with fabrica() as sesion:
        tomado = sesion.scalar(select(func.pg_try_advisory_lock(CLAVE_BLOQUEO_SINCRONIZACION)))
        if not tomado:
            registro.info("Ya hay una sincronización en curso; se salta este ciclo.")
            return None
        try:
            # Una fuente que falla no frena a las demás: su error queda anotado
            # en su punto de sincronización.
            return [s.ejecutar(desde, hasta) for s in sincronizadores]
        finally:
            sesion.scalar(select(func.pg_advisory_unlock(CLAVE_BLOQUEO_SINCRONIZACION)))
            sesion.commit()
