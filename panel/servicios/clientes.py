"""Historial del cliente: todo lo que pasó con un número, en orden."""

from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from panel.asignacion.servicio import ZONA_OPERACION_POR_DEFECTO
from panel.db.modelos import ASIGNACION_MANUAL, Cliente, Conversacion, Cuenta, Llamada, Persona
from panel.telefonos import normalizar
from reporte import TIPO_ACTIVIDAD, TIPO_ENTRANTE, TIPO_SALIENTE, traducir_estado

LIMITE_CLIENTES = 50
TIPO_PLANTILLA = 3
SIN_ASIGNAR = "Sin asignar"


class ResumenCliente(BaseModel):
    id: int
    telefono: str
    nombre: str | None
    revisar: bool
    llamadas: int
    conversaciones: int
    ultima: datetime | None  # en hora de la zona de operación

    @property
    def etiqueta(self) -> str:
        return f"{self.nombre} · {self.telefono}" if self.nombre else self.telefono


class ElementoHistorial(BaseModel):
    tipo: Literal["llamada", "conversacion"]
    id: int
    id_externo: str
    inicio: datetime  # en hora de la zona de operación
    cuenta: str
    persona_id: int | None
    asesor: str
    asignacion: str  # «automática» o «manual»
    motivo: str
    resumen: str
    enlace_plataforma: str | None = None  # la llamada en CloudTalk


class Historial(BaseModel):
    cliente: ResumenCliente
    elementos: list[ElementoHistorial]  # del más reciente al más antiguo
    # Asesor (o «Sin asignar») → cuántas interacciones atendió.
    por_asesor: dict[str, int]


class Mensaje(BaseModel):
    fecha: datetime | None
    rol: Literal["cliente", "asesor", "nota", "actividad"]
    autor: str
    texto: str


def formatear_duracion(segundos: int | None) -> str:
    if segundos is None:
        return "duración desconocida"
    minutos, resto = divmod(int(segundos), 60)
    return f"{minutos} min {resto:02d} s" if minutos else f"{resto} s"


def _contar(modelo):
    return (
        select(func.count())
        .select_from(modelo)
        .where(modelo.cliente_id == Cliente.id)
        .correlate(Cliente)
        .scalar_subquery()
    )


def _ultima(modelo):
    return (
        select(func.max(modelo.inicio))
        .where(modelo.cliente_id == Cliente.id)
        .correlate(Cliente)
        .scalar_subquery()
    )


def _consulta_resumen():
    llamadas, conversaciones = _contar(Llamada), _contar(Conversacion)
    ultima = func.greatest(_ultima(Llamada), _ultima(Conversacion))
    return select(Cliente, llamadas, conversaciones, ultima), ultima


def _resumen(fila, zona: ZoneInfo) -> ResumenCliente:
    cliente, llamadas, conversaciones, ultima = fila
    return ResumenCliente(
        id=cliente.id,
        telefono=cliente.telefono,
        nombre=cliente.nombre,
        revisar=cliente.revisar,
        llamadas=llamadas,
        conversaciones=conversaciones,
        ultima=ultima.astimezone(zona) if ultima else None,
    )


def buscar(
    sesion: Session,
    texto: str = "",
    solo_revisar: bool = False,
    zona: ZoneInfo = ZONA_OPERACION_POR_DEFECTO,
) -> list[ResumenCliente]:
    """Por teléfono (en cualquier formato, o parte de él) o por nombre. Sin
    texto, los clientes con actividad más reciente."""
    consulta, ultima = _consulta_resumen()
    texto = texto.strip()
    if texto:
        condiciones = [Cliente.nombre.ilike(f"%{texto}%")]
        digitos = "".join(c for c in texto if c.isdigit())
        if len(digitos) >= 4:
            condiciones.append(Cliente.telefono.contains(digitos))
            normalizado = normalizar(texto)
            if normalizado is not None:
                condiciones.append(Cliente.telefono == normalizado.valor)
        consulta = consulta.where(or_(*condiciones))
    if solo_revisar:
        consulta = consulta.where(Cliente.revisar)
    consulta = consulta.order_by(ultima.desc().nulls_last()).limit(LIMITE_CLIENTES)
    return [_resumen(fila, zona) for fila in sesion.execute(consulta)]


def obtener(
    sesion: Session, cliente_id: int, zona: ZoneInfo = ZONA_OPERACION_POR_DEFECTO
) -> ResumenCliente | None:
    consulta, _ = _consulta_resumen()
    fila = sesion.execute(consulta.where(Cliente.id == cliente_id)).first()
    return _resumen(fila, zona) if fila else None


def historial(
    sesion: Session, cliente_id: int, zona: ZoneInfo = ZONA_OPERACION_POR_DEFECTO
) -> Historial | None:
    cliente = obtener(sesion, cliente_id, zona)
    if cliente is None:
        return None

    elementos: list[ElementoHistorial] = []
    llamadas = sesion.execute(
        select(Llamada, Cuenta, Persona)
        .join(Cuenta, Llamada.cuenta_id == Cuenta.id)
        .outerjoin(Persona, Llamada.persona_id == Persona.id)
        .where(Llamada.cliente_id == cliente_id)
    )
    for llamada, cuenta, persona in llamadas:
        elementos.append(
            _elemento(
                "llamada",
                llamada,
                cuenta,
                persona,
                zona,
                f"Llamada {llamada.direccion} · {formatear_duracion(llamada.duracion_s)}",
                llamada.enlace_plataforma,
            )
        )
    conversaciones = sesion.execute(
        select(Conversacion, Cuenta, Persona)
        .outerjoin(Cuenta, Conversacion.cuenta_id == Cuenta.id)
        .outerjoin(Persona, Conversacion.persona_id == Persona.id)
        .where(Conversacion.cliente_id == cliente_id)
    )
    for conversacion, cuenta, persona in conversaciones:
        partes = [f"Chat por {conversacion.canal}", traducir_estado(conversacion.estado)]
        if conversacion.etiquetas:
            partes.append(", ".join(conversacion.etiquetas))
        elementos.append(
            _elemento("conversacion", conversacion, cuenta, persona, zona, " · ".join(partes))
        )

    elementos.sort(key=lambda e: e.inicio, reverse=True)
    por_asesor: dict[str, int] = {}
    for elemento in elementos:
        clave = elemento.asesor or SIN_ASIGNAR
        por_asesor[clave] = por_asesor.get(clave, 0) + 1
    return Historial(
        cliente=cliente,
        elementos=elementos,
        por_asesor=dict(sorted(por_asesor.items(), key=lambda par: -par[1])),
    )


def _elemento(tipo, fila, cuenta, persona, zona, resumen, enlace=None) -> ElementoHistorial:
    return ElementoHistorial(
        tipo=tipo,
        id=fila.id,
        id_externo=fila.id_externo,
        inicio=fila.inicio.astimezone(zona),
        cuenta=cuenta.nombre if cuenta else "—",
        persona_id=fila.persona_id,
        asesor=(persona.nombre or persona.correo) if persona else "",
        asignacion="manual" if fila.asignacion == ASIGNACION_MANUAL else "automática",
        motivo=fila.motivo_asignacion,
        resumen=resumen,
        enlace_plataforma=enlace,
    )


def _texto(mensaje: dict) -> str:
    texto = (mensaje.get("content") or "").strip()
    adjuntos = [
        f"[adjunto: {adjunto.get('file_type') or 'archivo'}]"
        for adjunto in mensaje.get("attachments") or []
    ]
    return "\n".join(parte for parte in [texto, " ".join(adjuntos)] if parte)


def mensajes_legibles(
    crudos: list[dict], zona: ZoneInfo = ZONA_OPERACION_POR_DEFECTO
) -> list[Mensaje]:
    """Los mensajes de Chatwoot en orden, con quién escribió cada uno."""
    resultado = []
    for mensaje in sorted(crudos, key=lambda m: m.get("id") or 0):
        tipo = mensaje.get("message_type")
        remitente = (mensaje.get("sender") or {}).get("name") or ""
        if mensaje.get("private"):
            rol, autor = "nota", remitente or "Nota interna"
        elif tipo == TIPO_ENTRANTE:
            rol, autor = "cliente", remitente or "Cliente"
        elif tipo in (TIPO_SALIENTE, TIPO_PLANTILLA):
            rol, autor = "asesor", remitente or "Asesor"
        elif tipo == TIPO_ACTIVIDAD:
            rol, autor = "actividad", ""
        else:
            continue
        texto = _texto(mensaje)
        if not texto:
            continue
        epoch = mensaje.get("created_at")
        resultado.append(
            Mensaje(
                fecha=datetime.fromtimestamp(float(epoch), zona) if epoch else None,
                rol=rol,
                autor=autor,
                texto=texto,
            )
        )
    return resultado


def mensajes_de_conversacion(
    sesion: Session, conversacion_id: int, zona: ZoneInfo = ZONA_OPERACION_POR_DEFECTO
) -> list[Mensaje] | None:
    """None si la conversación todavía no tiene los mensajes guardados."""
    crudos = sesion.scalar(select(Conversacion.mensajes).where(Conversacion.id == conversacion_id))
    if crudos is None:
        return None
    return mensajes_legibles(crudos, zona)
