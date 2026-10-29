"""Lecturas para la página Transcripción: la cola, el gasto y las llamadas
con más de una transcripción."""

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from panel.asignacion.servicio import ZONA_OPERACION_POR_DEFECTO
from panel.db.modelos import (
    TRABAJO_ERROR,
    Llamada,
    TrabajoTranscripcion,
    TranscripcionGuardada,
)


class TrabajoConError(BaseModel):
    id: int
    llamada_id: int
    llamada: str  # id de CloudTalk
    inicio: datetime
    intentos: int
    error: str


class GastoProveedor(BaseModel):
    proveedor: str
    modelo: str
    transcripciones: int
    minutos: float
    costo: Decimal | None  # None si alguna no tiene precio


class LlamadaComparable(BaseModel):
    llamada_id: int
    llamada: str
    inicio: datetime
    transcripciones: int


def estado_cola(sesion: Session) -> dict[str, int]:
    return dict(
        sesion.execute(
            select(TrabajoTranscripcion.estado, func.count()).group_by(TrabajoTranscripcion.estado)
        ).all()
    )


def trabajos_con_error(
    sesion: Session, zona: ZoneInfo = ZONA_OPERACION_POR_DEFECTO, limite: int = 100
) -> list[TrabajoConError]:
    filas = sesion.execute(
        select(TrabajoTranscripcion, Llamada)
        .join(Llamada, TrabajoTranscripcion.llamada_id == Llamada.id)
        .where(TrabajoTranscripcion.estado == TRABAJO_ERROR)
        .order_by(TrabajoTranscripcion.actualizado_en.desc())
        .limit(limite)
    )
    return [
        TrabajoConError(
            id=trabajo.id,
            llamada_id=llamada.id,
            llamada=llamada.id_externo,
            inicio=llamada.inicio.astimezone(zona),
            intentos=trabajo.intentos,
            error=trabajo.error or "",
        )
        for trabajo, llamada in filas
    ]


def gasto(sesion: Session, desde: datetime, hasta: datetime) -> list[GastoProveedor]:
    """Lo transcrito en el período, por proveedor y modelo."""
    filas = sesion.execute(
        select(
            TranscripcionGuardada.proveedor,
            TranscripcionGuardada.modelo,
            func.count(),
            func.coalesce(func.sum(TranscripcionGuardada.duracion_audio), 0),
            func.sum(TranscripcionGuardada.costo_estimado),
            func.count(TranscripcionGuardada.costo_estimado),
        )
        .where(TranscripcionGuardada.creado_en >= desde, TranscripcionGuardada.creado_en < hasta)
        .group_by(TranscripcionGuardada.proveedor, TranscripcionGuardada.modelo)
        .order_by(TranscripcionGuardada.proveedor)
    )
    return [
        GastoProveedor(
            proveedor=proveedor,
            modelo=modelo,
            transcripciones=cantidad,
            minutos=round(float(segundos) / 60, 1),
            costo=costo if con_precio == cantidad else None,
        )
        for proveedor, modelo, cantidad, segundos, costo, con_precio in filas
    ]


def llamadas_comparables(
    sesion: Session, zona: ZoneInfo = ZONA_OPERACION_POR_DEFECTO, limite: int = 50
) -> list[LlamadaComparable]:
    """Las llamadas con dos o más transcripciones, para compararlas."""
    cantidad = func.count(TranscripcionGuardada.id)
    filas = sesion.execute(
        select(Llamada.id, Llamada.id_externo, Llamada.inicio, cantidad)
        .join(TranscripcionGuardada, TranscripcionGuardada.llamada_id == Llamada.id)
        .group_by(Llamada.id)
        .having(cantidad >= 2)
        .order_by(Llamada.inicio.desc())
        .limit(limite)
    )
    return [
        LlamadaComparable(
            llamada_id=lid, llamada=externo, inicio=inicio.astimezone(zona), transcripciones=n
        )
        for lid, externo, inicio, n in filas
    ]
