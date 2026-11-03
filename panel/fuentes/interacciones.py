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
from reporte import TIPO_SALIENTE, a_fecha_local, resolver_canal
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


class AsesorDeMensajes(BaseModel):
    """El asesor que más mensajes envió en una conversación."""

    model_config = ConfigDict(frozen=True)

    cuenta: CuentaExterna
    mensajes: int  # los que envió él
    total: int  # los que enviaron todos los asesores


def asesor_con_mas_mensajes(mensajes: list[dict]) -> AsesorDeMensajes | None:
    """El usuario de Chatwoot que más mensajes envió al cliente.

    Cuentan los mensajes salientes (`message_type` 1) de un usuario: no las
    notas privadas, ni los de bots o automatizaciones, ni las actividades. Si
    dos empatan, gana el que escribió último. None si ningún asesor escribió.
    """
    conteo: dict[str, int] = {}
    ultimo: dict[str, tuple[float, int]] = {}
    remitentes: dict[str, dict] = {}
    for orden, msg in enumerate(mensajes):
        if msg.get("message_type") != TIPO_SALIENTE or msg.get("private"):
            continue
        remitente = msg.get("sender") or {}
        tipo = (msg.get("sender_type") or remitente.get("type") or "").lower()
        id_remitente = msg.get("sender_id") or remitente.get("id")
        if tipo != "user" or id_remitente in (None, ""):
            continue
        clave = str(id_remitente)
        conteo[clave] = conteo.get(clave, 0) + 1
        ultimo[clave] = max(ultimo.get(clave, (0.0, -1)), (_numero(msg.get("created_at")), orden))
        if remitente:
            remitentes[clave] = remitente
    if not conteo:
        return None

    elegido = max(conteo, key=lambda clave: (conteo[clave], ultimo[clave]))
    remitente = remitentes.get(elegido, {})
    correo = (remitente.get("email") or "").strip()
    nombre = (remitente.get("available_name") or remitente.get("name") or "").strip()
    return AsesorDeMensajes(
        cuenta=CuentaExterna(
            id_externo=elegido,
            nombre=nombre or correo or f"Usuario {elegido}",
            correo=correo,
        ),
        mensajes=conteo[elegido],
        total=sum(conteo.values()),
    )


def _numero(valor) -> float:
    try:
        return float(valor)
    except (TypeError, ValueError):
        return 0.0


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

    def grabacion(self, id_externo: str) -> bytes | None:
        return self._cliente.obtener_grabacion(id_externo)


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
