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
    TranscripcionGuardada,
)
from panel.servicios.clientes import mensajes_legibles
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


class FilaLlamadaCsv(FilaLlamada):
    transcripcion_texto: str = ""


class FilaConversacion(FilaInteraccion):
    canal: str
    estado: str
    etiquetas: str
    direccion: str
    cierre: datetime | None
    cierre_aproximado: bool
    horas_resolucion: float | None


class FilaConversacionCsv(FilaConversacion):
    chat_texto: str = ""


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
        # Una finalización es parte de la conversación anterior, no una nueva.
        .where(Conversacion.continua_de_id.is_(None))
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


# Excel no muestra más de 32 767 caracteres en una celda.
MAXIMO_TEXTO_CELDA = 32_000
QUIEN = {"agente": "Agente", "cliente": "Cliente"}


def _linea(segmento: dict) -> str:
    texto = (segmento.get("texto") or "").strip()
    if not texto:
        return ""
    quien = QUIEN.get(segmento.get("hablante"))
    if quien is None and segmento.get("etiqueta"):
        quien = f"Hablante {segmento['etiqueta']}"
    return f"{quien}: {texto}" if quien else texto


def textos_de_transcripcion(sesion: Session, llamada_ids: list[int]) -> dict[int, str]:
    """El texto de la transcripción principal de cada llamada, una línea por
    frase y con quién habla («Agente: …»)."""
    if not llamada_ids:
        return {}
    filas = sesion.execute(
        select(TranscripcionGuardada.llamada_id, TranscripcionGuardada.segmentos).where(
            TranscripcionGuardada.llamada_id.in_(llamada_ids), TranscripcionGuardada.principal
        )
    )
    textos = {}
    for llamada_id, segmentos in filas:
        textos[llamada_id] = _recortar("\n".join(linea for linea in map(_linea, segmentos or []) if linea))
    return textos


def con_transcripciones(sesion: Session, filas: list[FilaLlamada]) -> list[FilaLlamadaCsv]:
    textos = textos_de_transcripcion(sesion, [f.id for f in filas])
    return [FilaLlamadaCsv(**f.model_dump(), transcripcion_texto=textos.get(f.id, "")) for f in filas]


SIN_MENSAJES = "(los mensajes todavía no están guardados)"
ROL_CHAT = {"cliente": "Cliente", "asesor": "Asesor", "nota": "Nota interna"}


def _recortar(texto: str) -> str:
    if len(texto) > MAXIMO_TEXTO_CELDA:
        return texto[:MAXIMO_TEXTO_CELDA] + " … (recortado: véalo completo en el panel)"
    return texto


def _lineas_de_chat(crudos: list[dict], zona: ZoneInfo) -> list[str]:
    lineas = []
    for mensaje in mensajes_legibles(crudos, zona):
        if mensaje.rol == "actividad":
            continue
        rol = ROL_CHAT[mensaje.rol]
        quien = f"{rol} ({mensaje.autor})" if mensaje.autor and mensaje.autor != rol else rol
        hora = f"[{mensaje.fecha:%d/%m %H:%M}] " if mensaje.fecha else ""
        lineas.append(f"{hora}{quien}: {' '.join(mensaje.texto.split())}")
    return lineas


def textos_de_chat(
    sesion: Session, conversacion_ids: list[int], zona: ZoneInfo = ZONA_OPERACION_POR_DEFECTO
) -> dict[int, str]:
    """El chat de cada conversación, un mensaje por línea con la hora y quién
    escribió. Incluye las notas internas y los mensajes de sus finalizaciones
    (la conversación abandonada que la continúa); deja fuera las actividades
    del sistema."""
    if not conversacion_ids:
        return {}
    filas = sesion.execute(
        select(Conversacion.id, Conversacion.continua_de_id, Conversacion.mensajes)
        .where(
            or_(Conversacion.id.in_(conversacion_ids), Conversacion.continua_de_id.in_(conversacion_ids))
        )
        .order_by(Conversacion.inicio)
    )
    lineas: dict[int, list[str]] = {}
    sin_guardar = set()
    for conversacion_id, continua_de_id, crudos in filas:
        propia = continua_de_id is None or conversacion_id in conversacion_ids
        destino = conversacion_id if propia else continua_de_id
        if crudos is None:
            if propia:
                sin_guardar.add(destino)
            continue
        lineas.setdefault(destino, []).extend(_lineas_de_chat(crudos, zona))
    return {
        i: SIN_MENSAJES if i in sin_guardar and not lineas.get(i) else _recortar("\n".join(lineas.get(i, [])))
        for i in conversacion_ids
    }


def con_textos_de_chat(sesion: Session, filas: list[FilaConversacion]) -> list[FilaConversacionCsv]:
    textos = textos_de_chat(sesion, [f.id for f in filas])
    return [FilaConversacionCsv(**f.model_dump(), chat_texto=textos.get(f.id, "")) for f in filas]


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
        conversaciones=contar(Conversacion, Conversacion.continua_de_id.is_(None)),
        llamadas_sin_asignar=contar(Llamada, Llamada.persona_id.is_(None)),
        conversaciones_sin_asignar=contar(
            Conversacion,
            Conversacion.persona_id.is_(None),
            Conversacion.continua_de_id.is_(None),
        ),
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
