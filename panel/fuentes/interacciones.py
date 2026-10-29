"""Llamadas y conversaciones de cada plataforma, en una forma común.

La sincronización trabaja con `LlamadaExterna` y `ConversacionExterna` y nunca
ve el JSON de una API. Cada plataforma tiene su adaptador, que cumple la
interfaz `FuenteLlamadas` o `FuenteConversaciones`.
"""

from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from chatwoot import ClienteChatwoot
from cloudtalk import ClienteCloudTalk, a_fecha_utc, fue_grabada
from panel.fuentes.cuentas import CuentaExterna
from reporte import a_fecha_local, resolver_canal
from reporte_cloudtalk import nombre_agente

DIRECCIONES_CLOUDTALK = {"incoming": "entrante", "outgoing": "saliente", "internal": "interna"}
DESCONOCIDA = "desconocida"


class LlamadaExterna(BaseModel):
    model_config = ConfigDict(frozen=True)

    id_externo: str
    agente: CuentaExterna
    inicio: datetime  # con zona horaria
    duracion_s: int | None
    direccion: str
    grabada: bool
    enlace_plataforma: str | None
    telefono_cliente: str | None
    nombre_cliente: str | None
    datos_origen: dict[str, Any]


class ConversacionExterna(BaseModel):
    model_config = ConfigDict(frozen=True)

    id_externo: str
    usuario: CuentaExterna | None  # el usuario asignado en Chatwoot
    inicio: datetime
    ultima_actividad: datetime | None
    canal: str
    estado: str
    etiquetas: list[str]
    telefono_cliente: str | None
    nombre_cliente: str | None
    datos_origen: dict[str, Any]


class FuenteLlamadas(Protocol):
    plataforma: str

    def llamadas(self, desde: datetime, hasta: datetime) -> list[LlamadaExterna]: ...


class FuenteConversaciones(Protocol):
    plataforma: str

    def conversaciones(self, desde: datetime, hasta: datetime) -> list[ConversacionExterna]: ...

    def mensajes(self, id_externo: str) -> list[dict]: ...


def _entero(valor) -> int | None:
    try:
        return int(float(valor))
    except (TypeError, ValueError):
        return None


def llamada_de_cloudtalk(llamada: dict) -> LlamadaExterna | None:
    """None si la llamada no trae id, inicio o agente: sin ellos no se puede
    guardar ni asignar."""
    cdr = llamada.get("Cdr") or {}
    agente = llamada.get("Agent") or {}
    contacto = llamada.get("Contact") or {}
    id_agente = agente.get("id") or cdr.get("user_id")
    inicio = a_fecha_utc(cdr.get("started_at"))
    if not cdr.get("id") or not id_agente or inicio is None:
        return None

    duracion = _entero(cdr.get("talking_time"))
    if duracion is None:
        duracion = _entero(cdr.get("billsec"))
    numeros = contacto.get("contact_numbers") or []
    telefono = cdr.get("public_external") or (numeros[0] if numeros else None)

    return LlamadaExterna(
        id_externo=str(cdr["id"]),
        agente=CuentaExterna(
            id_externo=str(id_agente),
            nombre=nombre_agente(llamada) or f"Agente {id_agente}",
            correo=agente.get("email"),
        ),
        inicio=inicio,
        duracion_s=duracion,
        direccion=DIRECCIONES_CLOUDTALK.get(cdr.get("type") or "", DESCONOCIDA),
        grabada=fue_grabada(llamada),
        enlace_plataforma=cdr.get("recording_link") or None,
        telefono_cliente=str(telefono) if telefono else None,
        nombre_cliente=(contacto.get("name") or "").strip() or None,
        datos_origen=llamada,
    )


def conversacion_de_chatwoot(
    conversacion: dict, bandejas: dict[int, str]
) -> ConversacionExterna | None:
    if conversacion.get("id") is None:
        return None
    inicio = a_fecha_local(conversacion.get("created_at"))
    if inicio is None:
        return None
    meta = conversacion.get("meta") or {}
    asignado = meta.get("assignee") or {}
    remitente = meta.get("sender") or {}

    usuario = None
    if asignado.get("id") is not None:
        correo = (asignado.get("email") or "").strip()
        nombre = (asignado.get("available_name") or asignado.get("name") or "").strip()
        usuario = CuentaExterna(
            id_externo=str(asignado["id"]),
            nombre=nombre or correo or f"Usuario {asignado['id']}",
            correo=correo,
        )

    return ConversacionExterna(
        id_externo=str(conversacion["id"]),
        usuario=usuario,
        inicio=inicio,
        ultima_actividad=a_fecha_local(conversacion.get("last_activity_at")),
        canal=resolver_canal(conversacion, bandejas),
        estado=conversacion.get("status") or "",
        etiquetas=list(conversacion.get("labels") or []),
        telefono_cliente=remitente.get("phone_number") or None,
        nombre_cliente=(remitente.get("name") or "").strip() or None,
        datos_origen=conversacion,
    )


class FuenteCloudTalk:
    plataforma = "cloudtalk"

    def __init__(self, cliente: ClienteCloudTalk) -> None:
        self._cliente = cliente

    def llamadas(self, desde: datetime, hasta: datetime) -> list[LlamadaExterna]:
        convertidas = (llamada_de_cloudtalk(ll) for ll in self._cliente.listar_llamadas(desde, hasta))
        return [ll for ll in convertidas if ll is not None]


class FuenteChatwoot:
    plataforma = "chatwoot"

    def __init__(self, cliente: ClienteChatwoot) -> None:
        self._cliente = cliente
        self._bandejas: dict[int, str] | None = None

    def conversaciones(self, desde: datetime, hasta: datetime) -> list[ConversacionExterna]:
        if self._bandejas is None:
            self._bandejas = self._cliente.listar_inboxes()
        convertidas = (
            conversacion_de_chatwoot(c, self._bandejas)
            for c in self._cliente.listar_conversaciones(desde, hasta)
        )
        return [c for c in convertidas if c is not None]

    def mensajes(self, id_externo: str) -> list[dict]:
        return self._cliente.listar_mensajes(int(id_externo))
