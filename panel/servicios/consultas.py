"""Lecturas para las pantallas: listados filtrados, conteos y exportación."""

import io
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, aliased

from panel.asignacion.servicio import ZONA_OPERACION_POR_DEFECTO
from panel.db.modelos import (
    ASIGNACION_MANUAL,
    AUDIO_GUARDADO,
    Cliente,
    Conversacion,
    Cuenta,
    Llamada,
    Persona,
    PuntoSincronizacion,
    ReglaAsignacion,
)
from reporte import traducir_estado

LIMITE_FILAS = 5000


class Filtros(BaseModel):
    desde: datetime
    hasta: datetime  # excluido
    persona_ids: list[int] = []
    cuenta_ids: list[int] = []
    solo_sin_asignar: bool = False
    # Dígitos del teléfono o parte del nombre del cliente.
    cliente: str = ""


class FilaInteraccion(BaseModel):
    id: int
    id_externo: str
    inicio: datetime  # en hora de la zona de operación
    cuenta: str
    persona_id: int | None
    asesor: str
    area: str
    asignacion: str  # «automática» o «manual»
    motivo: str
    telefono: str
    cliente: str
    cliente_id: int | None


class FilaLlamada(FilaInteraccion):
    direccion: str
    duracion_s: int | None
    grabada: bool
    enlace_plataforma: str | None
    audio_estado: str | None
    transcripcion_estado: str | None


class FilaConversacion(FilaInteraccion):
    canal: str
    estado: str
    etiquetas: str
    direccion: str
    cierre: datetime | None
    cierre_aproximado: bool
    horas_resolucion: float | None


def _filtrar(consulta, modelo, filtros: Filtros, cliente):
    consulta = consulta.where(modelo.inicio >= filtros.desde, modelo.inicio < filtros.hasta)
    if filtros.persona_ids:
        consulta = consulta.where(modelo.persona_id.in_(filtros.persona_ids))
    if filtros.cuenta_ids:
        consulta = consulta.where(modelo.cuenta_id.in_(filtros.cuenta_ids))
    if filtros.solo_sin_asignar:
        consulta = consulta.where(modelo.persona_id.is_(None))
    texto = filtros.cliente.strip()
    if texto:
        digitos = "".join(c for c in texto if c.isdigit())
        condiciones = [cliente.nombre.ilike(f"%{texto}%")]
        if len(digitos) >= 4:
            condiciones.append(cliente.telefono.contains(digitos))
        consulta = consulta.where(or_(*condiciones))
    return consulta.order_by(modelo.inicio.desc()).limit(LIMITE_FILAS)


def _comunes(fila, cuenta, persona, cliente, zona) -> dict:
    return {
        "id": fila.id,
        "id_externo": fila.id_externo,
        "inicio": fila.inicio.astimezone(zona),
        "cuenta": cuenta.nombre if cuenta else "—",
        "persona_id": fila.persona_id,
        "asesor": (persona.nombre or persona.correo) if persona else "",
        "area": persona.area if persona else "",
        "asignacion": "manual" if fila.asignacion == ASIGNACION_MANUAL else "automática",
        "motivo": fila.motivo_asignacion,
        "telefono": cliente.telefono if cliente else "",
        "cliente": (cliente.nombre or "") if cliente else "",
        "cliente_id": fila.cliente_id,
    }


def listar_llamadas(
    sesion: Session, filtros: Filtros, zona: ZoneInfo = ZONA_OPERACION_POR_DEFECTO
) -> list[FilaLlamada]:
    cliente = aliased(Cliente)
    consulta = (
        select(Llamada, Cuenta, Persona, cliente)
        .join(Cuenta, Llamada.cuenta_id == Cuenta.id)
        .outerjoin(Persona, Llamada.persona_id == Persona.id)
        .outerjoin(cliente, Llamada.cliente_id == cliente.id)
    )
    filas = []
    for llamada, cuenta, persona, cli in sesion.execute(_filtrar(consulta, Llamada, filtros, cliente)):
        filas.append(
            FilaLlamada(
                **_comunes(llamada, cuenta, persona, cli, zona),
                direccion=llamada.direccion,
                duracion_s=llamada.duracion_s,
                grabada=llamada.grabada,
                enlace_plataforma=llamada.enlace_plataforma,
                audio_estado=llamada.audio_estado,
                transcripcion_estado=llamada.transcripcion_estado,
            )
        )
    return filas


def listar_conversaciones(
    sesion: Session, filtros: Filtros, zona: ZoneInfo = ZONA_OPERACION_POR_DEFECTO
) -> list[FilaConversacion]:
    cliente = aliased(Cliente)
    consulta = (
        select(Conversacion, Cuenta, Persona, cliente)
        .outerjoin(Cuenta, Conversacion.cuenta_id == Cuenta.id)
        .outerjoin(Persona, Conversacion.persona_id == Persona.id)
        .outerjoin(cliente, Conversacion.cliente_id == cliente.id)
    )
    filas = []
    for conv, cuenta, persona, cli in sesion.execute(
        _filtrar(consulta, Conversacion, filtros, cliente)
    ):
        horas = None
        if conv.cierre is not None:
            horas = round((conv.cierre - conv.inicio).total_seconds() / 3600, 1)
        filas.append(
            FilaConversacion(
                **_comunes(conv, cuenta, persona, cli, zona),
                canal=conv.canal,
                estado=traducir_estado(conv.estado),
                etiquetas=";".join(conv.etiquetas or []),
                direccion=conv.direccion,
                cierre=conv.cierre.astimezone(zona) if conv.cierre else None,
                cierre_aproximado=conv.cierre_aproximado,
                horas_resolucion=horas,
            )
        )
    return filas


class Resumen(BaseModel):
    llamadas: int
    conversaciones: int
    llamadas_sin_asignar: int
    conversaciones_sin_asignar: int
    cuentas_sin_regla: int


def resumen(sesion: Session, desde: datetime, hasta: datetime) -> Resumen:
    def contar(modelo, *condiciones) -> int:
        return sesion.scalar(
            select(func.count())
            .select_from(modelo)
            .where(modelo.inicio >= desde, modelo.inicio < hasta, *condiciones)
        )

    con_reglas = select(ReglaAsignacion.cuenta_id)
    return Resumen(
        llamadas=contar(Llamada),
        conversaciones=contar(Conversacion),
        llamadas_sin_asignar=contar(Llamada, Llamada.persona_id.is_(None)),
        conversaciones_sin_asignar=contar(Conversacion, Conversacion.persona_id.is_(None)),
        cuentas_sin_regla=sesion.scalar(
            select(func.count())
            .select_from(Cuenta)
            .where(Cuenta.activa, Cuenta.id.not_in(con_reglas))
        ),
    )


def estado_sincronizacion(sesion: Session) -> list[PuntoSincronizacion]:
    return list(sesion.scalars(select(PuntoSincronizacion).order_by(PuntoSincronizacion.fuente)))


def a_csv(filas: list[BaseModel], columnas: dict[str, str]) -> bytes:
    """CSV con BOM para que Excel en Windows respete los acentos.

    `columnas`: atributo → encabezado, en el orden de salida.
    """
    datos = pd.DataFrame(
        [{titulo: getattr(fila, atributo) for atributo, titulo in columnas.items()} for fila in filas],
        columns=list(columnas.values()),
    )
    for columna in datos.columns:
        if pd.api.types.is_datetime64_any_dtype(datos[columna]):
            datos[columna] = datos[columna].dt.strftime("%Y-%m-%d %H:%M")
    memoria = io.StringIO()
    datos.to_csv(memoria, index=False, lineterminator="\r\n")
    return ("﻿" + memoria.getvalue()).encode("utf-8")


def audios_por_vencer(sesion: Session, ahora: datetime, retencion_dias: int, aviso_dias: int = 7) -> int:
    """Audios guardados que se borran en los próximos `aviso_dias` días."""
    desde = ahora - timedelta(days=retencion_dias)
    hasta = desde + timedelta(days=aviso_dias)
    return sesion.scalar(
        select(func.count())
        .select_from(Llamada)
        .where(Llamada.audio_estado == AUDIO_GUARDADO, Llamada.inicio >= desde, Llamada.inicio < hasta)
    )
