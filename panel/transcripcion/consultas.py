"""Lecturas para la página Transcripción: la cola, el gasto y las llamadas
con más de una transcripción."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from pydantic import BaseModel
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from panel.asignacion.servicio import ZONA_OPERACION_POR_DEFECTO
from panel.db.modelos import (
    TRABAJO_EN_PROCESO,
    TRABAJO_ERROR,
    TRABAJO_PENDIENTE,
    CobroTranscripcion,
    Llamada,
    PuntoSincronizacion,
    TrabajoTranscripcion,
    TranscripcionGuardada,
)

# Una diferencia mayor entre lo cobrado y lo configurado se marca como desviada.
DESVIO_MAXIMO = Decimal("0.05")


class TrabajoConError(BaseModel):
    id: int
    llamada_id: int
    llamada: str  # id de CloudTalk
    inicio: datetime
    intentos: int
    error: str
    modelo: str | None = None  # el elegido para el pedido; vacío: el principal y los de respaldo


class TrabajoEnCola(TrabajoConError):
    estado: str


class PedidoLlamada(BaseModel):
    """El último pedido de cola de una llamada, para mostrar su estado."""

    id: int
    estado: str
    intentos: int
    error: str | None


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


# Nombre de la tarea de la sincronización que vacía la cola (ver panel.sync.tareas).
TAREA_COLA = "transcripciones"
# Con menos margen, un ciclo largo (muchas llamadas por transcribir) parecería detenido.
MARGEN_MINIMO = timedelta(hours=1)


class EstadoProcesador(BaseModel):
    """Quién vacía la cola y cuándo lo hizo por última vez.

    La cola la procesa el servicio de sincronización (`python -m panel.sync`),
    no la API: si ese servicio no corre, o corre sin la transcripción armada,
    los pedidos se quedan esperando sin ningún error. `diagnostico` lo explica
    cuando hay pedidos esperando y la cola no avanza."""

    ultima_vuelta: datetime | None  # el último ciclo que tomó pedidos de la cola
    ultimo_exito: datetime | None
    ultimo_error: str | None
    resumen: dict | None
    sincronizacion: datetime | None  # el último ciclo de la sincronización, de cualquier tarea
    diagnostico: str | None = None


def _hora(momento: datetime | None, zona: ZoneInfo) -> str:
    return momento.astimezone(zona).strftime("%d/%m %H:%M") if momento else ""


def estado_procesador(
    sesion: Session, ahora: datetime, intervalo_minutos: int, zona: ZoneInfo = ZONA_OPERACION_POR_DEFECTO
) -> EstadoProcesador:
    puntos = {p.fuente: p for p in sesion.scalars(select(PuntoSincronizacion))}
    cola = puntos.get(TAREA_COLA)
    ultimos = [p.ultimo_intento for p in puntos.values() if p.ultimo_intento]
    estado = EstadoProcesador(
        ultima_vuelta=cola.ultimo_intento if cola else None,
        ultimo_exito=cola.ultimo_exito if cola else None,
        ultimo_error=cola.ultimo_error if cola else None,
        resumen=cola.resumen if cola else None,
        sincronizacion=max(ultimos) if ultimos else None,
    )
    esperando = sesion.scalar(
        select(func.count()).where(TrabajoTranscripcion.estado == TRABAJO_PENDIENTE)
    )
    if not esperando:
        return estado

    limite = ahora - max(timedelta(minutes=3 * intervalo_minutos), MARGEN_MINIMO)
    if estado.sincronizacion is None or estado.sincronizacion < limite:
        desde = f"desde el {_hora(estado.sincronizacion, zona)}" if estado.sincronizacion else "nunca"
        estado.diagnostico = (
            f"La sincronización no corre ({desde}), y es ella la que transcribe la cola: los pedidos "
            "se quedan esperando. Revise en EasyPanel que el servicio de sincronización "
            "(python -m panel.sync) esté encendido y mire su log. Mientras tanto puede "
            "transcribirlos desde aquí con «Transcribir la cola ahora»."
        )
    elif estado.ultima_vuelta is None or estado.ultima_vuelta < limite:
        estado.diagnostico = (
            "La sincronización corre, pero no transcribe: en ese servicio la transcripción no "
            "quedó armada. Lo más común es que no tenga la misma PANEL_CLAVE_CIFRADO (o "
            "APP_COOKIE_KEY) que el panel y no pueda leer la clave del proveedor; su log lo dice "
            "(«Ajustes cifrados con otra llave» o «la transcripción no se pudo armar»). Mientras "
            "tanto puede transcribirlos desde aquí con «Transcribir la cola ahora»."
        )
    elif estado.ultimo_error:
        estado.diagnostico = f"La última vuelta de la cola falló ({_hora(estado.ultima_vuelta, zona)}): {estado.ultimo_error}"
    return estado


def trabajos_abiertos(
    sesion: Session, zona: ZoneInfo = ZONA_OPERACION_POR_DEFECTO, limite: int = 200
) -> list[TrabajoEnCola]:
    """Los pedidos que se están transcribiendo y después los que esperan, en
    el orden en que la cola los va a tomar (el más viejo primero). `error` es
    el del último intento, si falló alguno."""
    filas = sesion.execute(
        select(TrabajoTranscripcion, Llamada)
        .join(Llamada, TrabajoTranscripcion.llamada_id == Llamada.id)
        .where(TrabajoTranscripcion.estado.in_([TRABAJO_EN_PROCESO, TRABAJO_PENDIENTE]))
        .order_by(
            case((TrabajoTranscripcion.estado == TRABAJO_EN_PROCESO, 0), else_=1),
            TrabajoTranscripcion.creado_en,
            TrabajoTranscripcion.id,
        )
        .limit(limite)
    )
    return [
        TrabajoEnCola(
            id=trabajo.id,
            llamada_id=llamada.id,
            llamada=llamada.id_externo,
            inicio=llamada.inicio.astimezone(zona),
            intentos=trabajo.intentos,
            error=trabajo.error or "",
            estado=trabajo.estado,
            modelo=trabajo.proveedor,
        )
        for trabajo, llamada in filas
    ]


def pedido_de_llamada(sesion: Session, llamada_id: int) -> PedidoLlamada | None:
    trabajo = sesion.scalar(
        select(TrabajoTranscripcion)
        .where(TrabajoTranscripcion.llamada_id == llamada_id)
        .order_by(TrabajoTranscripcion.id.desc())
        .limit(1)
    )
    if trabajo is None:
        return None
    return PedidoLlamada(id=trabajo.id, estado=trabajo.estado, intentos=trabajo.intentos, error=trabajo.error)


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
            modelo=trabajo.proveedor,
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


def limites_del_mes(mes: date, zona: ZoneInfo = ZONA_OPERACION_POR_DEFECTO) -> tuple[datetime, datetime]:
    """Desde el día 1 a las 00:00 (hora de España) hasta el día 1 siguiente."""
    inicio = datetime.combine(mes.replace(day=1), time.min, tzinfo=zona)
    siguiente = (inicio + timedelta(days=32)).replace(day=1)
    return inicio, siguiente


def gasto_del_mes(sesion: Session, ahora: datetime, zona: ZoneInfo = ZONA_OPERACION_POR_DEFECTO) -> Decimal:
    """Lo estimado en el mes en curso. Las transcripciones sin precio no suman."""
    desde, hasta = limites_del_mes(ahora.astimezone(zona).date(), zona)
    total = sesion.scalar(
        select(func.coalesce(func.sum(TranscripcionGuardada.costo_estimado), 0)).where(
            TranscripcionGuardada.creado_en >= desde, TranscripcionGuardada.creado_en < hasta
        )
    )
    return Decimal(total)


def llamadas_para_encolar(sesion: Session, desde: datetime, min_segundos: int, limite: int = 200) -> list[int]:
    """Llamadas grabadas recientes, sin transcribir y sin pedido abierto."""
    abiertos = select(TrabajoTranscripcion.llamada_id).where(
        TrabajoTranscripcion.estado.in_([TRABAJO_PENDIENTE, TRABAJO_EN_PROCESO, TRABAJO_ERROR])
    )
    return list(
        sesion.scalars(
            select(Llamada.id)
            .where(
                Llamada.inicio >= desde,
                Llamada.grabada,
                Llamada.transcripcion_estado.is_(None),
                Llamada.duracion_s >= min_segundos,
                Llamada.id.not_in(abiertos),
            )
            .order_by(Llamada.inicio)
            .limit(limite)
        )
    )


class FilaPrecioReal(BaseModel):
    proveedor: str
    modelo: str
    minutos_panel: float
    usd_estimado: Decimal | None
    minutos_cobrados: Decimal | None
    usd_cobrados: Decimal | None
    precio_configurado: Decimal | None

    @property
    def precio_real(self) -> Decimal | None:
        if not self.minutos_cobrados or self.usd_cobrados is None:
            return None
        return (self.usd_cobrados / self.minutos_cobrados).quantize(Decimal("0.00001"))

    @property
    def diferencia(self) -> Decimal | None:
        """(real − configurado) / configurado. None si falta alguno."""
        real = self.precio_real
        if real is None or not self.precio_configurado:
            return None
        return (real - self.precio_configurado) / self.precio_configurado

    @property
    def desviado(self) -> bool:
        return self.diferencia is not None and abs(self.diferencia) > DESVIO_MAXIMO


def precio_real(
    sesion: Session,
    mes: date,
    precios: dict[tuple[str, str], Decimal | None],
    zona: ZoneInfo = ZONA_OPERACION_POR_DEFECTO,
) -> list[FilaPrecioReal]:
    """Lo que estimó el panel y lo que cobró el proveedor, por modelo.

    `precios`: (proveedor, modelo) → USD por minuto configurado.
    """
    desde, hasta = limites_del_mes(mes, zona)
    estimado = {(g.proveedor, g.modelo): g for g in gasto(sesion, desde, hasta)}
    cobros = {
        (c.proveedor, c.modelo): c
        for c in sesion.scalars(select(CobroTranscripcion).where(CobroTranscripcion.mes == mes.replace(day=1)))
    }
    filas = []
    for clave in sorted(set(estimado) | set(cobros)):
        g, c = estimado.get(clave), cobros.get(clave)
        filas.append(
            FilaPrecioReal(
                proveedor=clave[0],
                modelo=clave[1],
                minutos_panel=g.minutos if g else 0.0,
                usd_estimado=g.costo if g else None,
                minutos_cobrados=c.minutos if c else None,
                usd_cobrados=c.usd if c else None,
                precio_configurado=precios.get(clave),
            )
        )
    return filas


def guardar_cobro(
    sesion: Session, mes: date, proveedor: str, modelo: str, minutos: Decimal, usd: Decimal
) -> None:
    """Carga o corrige lo cobrado en un mes por un modelo."""
    mes = mes.replace(day=1)
    fila = sesion.scalar(
        select(CobroTranscripcion).where(
            CobroTranscripcion.mes == mes,
            CobroTranscripcion.proveedor == proveedor,
            CobroTranscripcion.modelo == modelo,
        )
    )
    if fila is None:
        sesion.add(CobroTranscripcion(mes=mes, proveedor=proveedor, modelo=modelo, minutos=minutos, usd=usd))
    else:
        fila.minutos, fila.usd = minutos, usd
