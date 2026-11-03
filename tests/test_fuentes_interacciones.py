from datetime import datetime, timezone

from panel.fuentes.interacciones import (
    asesor_con_mas_mensajes,
    es_abandonada,
    FuenteChatwoot,
    FuenteCloudTalk,
    conversacion_de_chatwoot,
    llamada_de_cloudtalk,
)

LLAMADA_CT = {
    "Cdr": {
        "id": "27",
        "billsec": "30",
        "talking_time": "21",
        "type": "incoming",
        "recorded": True,
        "started_at": "2026-09-01T08:28:01.000Z",
        "public_external": "612345678",
        "recording_link": "https://analytics.cloudtalk.io/call/27",
        "user_id": "1000",
    },
    "Agent": {"id": "1000", "fullname": "Tatiana Velandia", "email": "Tatiana@E.com"},
    "Contact": {"name": "Grúas Pérez", "contact_numbers": ["+34 699 000 111"]},
}

CONVERSACION_CW = {
    "id": 512,
    "inbox_id": 3,
    "status": "resolved",
    "labels": ["venta", "grua"],
    "created_at": 1788336000,  # 2026-09-02 08:00 UTC
    "last_activity_at": 1788339600,
    "meta": {
        "assignee": {"id": 9, "name": "Ana Gil", "available_name": "Ana", "email": "ana@e.com"},
        "sender": {"name": "Cliente", "phone_number": "+34612345678"},
    },
}


def test_llamada_de_cloudtalk():
    llamada = llamada_de_cloudtalk(LLAMADA_CT)
    assert llamada.id_externo == "27"
    assert llamada.agente.id_externo == "1000"
    assert llamada.agente.nombre == "Tatiana Velandia"
    assert llamada.agente.correo == "tatiana@e.com"
    assert llamada.inicio == datetime(2026, 9, 1, 8, 28, 1, tzinfo=timezone.utc)
    assert llamada.duracion_s == 21
    assert llamada.direccion == "entrante"
    assert llamada.grabada
    assert llamada.enlace_plataforma == "https://analytics.cloudtalk.io/call/27"
    assert llamada.telefono_cliente == "612345678"
    assert llamada.nombre_cliente == "Grúas Pérez"
    assert llamada.datos_origen == LLAMADA_CT


def test_llamada_sin_numero_externo_usa_el_del_contacto_y_billsec():
    cdr = {k: v for k, v in LLAMADA_CT["Cdr"].items() if k not in ("public_external", "talking_time")}
    llamada = llamada_de_cloudtalk({**LLAMADA_CT, "Cdr": cdr})
    assert llamada.telefono_cliente == "+34 699 000 111"
    assert llamada.duracion_s == 30


def test_llamada_sin_agente_o_sin_inicio_se_descarta():
    assert llamada_de_cloudtalk({"Cdr": {"id": "1", "started_at": "2026-09-01T08:00:00Z"}}) is None
    assert llamada_de_cloudtalk({**LLAMADA_CT, "Cdr": {"id": "1", "user_id": "5"}}) is None


def test_llamada_con_tipo_desconocido():
    llamada = llamada_de_cloudtalk({**LLAMADA_CT, "Cdr": {**LLAMADA_CT["Cdr"], "type": "raro"}})
    assert llamada.direccion == "desconocida"


def test_conversacion_de_chatwoot():
    conversacion = conversacion_de_chatwoot(CONVERSACION_CW, {3: "WhatsApp Ventas"})
    assert conversacion.id_externo == "512"
    assert conversacion.usuario.id_externo == "9"
    assert conversacion.usuario.nombre == "Ana"
    assert conversacion.inicio == datetime(2026, 9, 2, 8, 0, tzinfo=timezone.utc)
    assert conversacion.canal == "WhatsApp Ventas"
    assert conversacion.estado == "resolved"
    assert conversacion.etiquetas == ["venta", "grua"]
    assert conversacion.telefono_cliente == "+34612345678"


def test_conversacion_sin_usuario_asignado():
    sin_asignar = {**CONVERSACION_CW, "meta": {"sender": {}}}
    conversacion = conversacion_de_chatwoot(sin_asignar, {})
    assert conversacion.usuario is None
    assert conversacion.telefono_cliente is None
    assert conversacion.canal == "inbox 3"


class ClienteCloudTalkFalso:
    def listar_llamadas(self, desde, hasta):
        return [LLAMADA_CT, {"Cdr": {}}]


class ClienteChatwootFalso:
    def __init__(self):
        self.bandejas_pedidas = 0

    def listar_inboxes(self):
        self.bandejas_pedidas += 1
        return {3: "WhatsApp"}

    def listar_conversaciones(self, desde, hasta):
        return [CONVERSACION_CW]

    def listar_mensajes(self, conversacion_id):
        return [{"id": 1, "conversacion": conversacion_id}]


def test_las_fuentes_descartan_lo_que_no_se_puede_guardar():
    assert [ll.id_externo for ll in FuenteCloudTalk(ClienteCloudTalkFalso()).llamadas(None, None)] == [
        "27"
    ]


def test_la_fuente_de_chatwoot_pide_las_bandejas_una_vez():
    cliente = ClienteChatwootFalso()
    fuente = FuenteChatwoot(cliente)
    fuente.conversaciones(None, None)
    fuente.conversaciones(None, None)
    assert cliente.bandejas_pedidas == 1
    assert fuente.mensajes("512") == [{"id": 1, "conversacion": 512}]


def _saliente(usuario_id, creado, **extra):
    return {
        "message_type": 1,
        "created_at": creado,
        "sender_type": "User",
        "sender_id": usuario_id,
        "sender": {"id": usuario_id, "available_name": f"Asesor {usuario_id}", "type": "user"},
        **extra,
    }


def test_asesor_con_mas_mensajes():
    mensajes = [
        {"message_type": 0, "created_at": 1, "sender_type": "Contact", "sender_id": 50},
        _saliente(7, 2),
        _saliente(8, 3),
        _saliente(8, 4),
        _saliente(7, 5, private=True),  # nota privada
        {"message_type": 1, "created_at": 6, "sender_type": "AgentBot", "sender_id": 1},
        {"message_type": 1, "created_at": 7, "sender": None},  # automatización
        {"message_type": 2, "created_at": 8, "content": "Conversation was marked resolved"},
    ]
    asesor = asesor_con_mas_mensajes(mensajes)
    assert asesor.cuenta.id_externo == "8"
    assert asesor.cuenta.nombre == "Asesor 8"
    assert (asesor.mensajes, asesor.total) == (2, 3)


def test_asesor_con_mas_mensajes_desempata_por_el_ultimo_que_escribio():
    mensajes = [_saliente(7, 1), _saliente(8, 2), _saliente(8, 3), _saliente(7, 4)]
    assert asesor_con_mas_mensajes(mensajes).cuenta.id_externo == "7"


def test_asesor_con_mas_mensajes_sin_asesores():
    assert asesor_con_mas_mensajes([]) is None
    assert asesor_con_mas_mensajes([{"message_type": 0, "sender_type": "Contact"}]) is None


def test_es_abandonada():
    cliente = {"message_type": 0, "created_at": 1}
    assert es_abandonada([cliente])
    assert es_abandonada([cliente, {"message_type": 2, "content": "resolved"}])
    assert es_abandonada([cliente, _saliente(7, 2, private=True)])  # nota interna
    assert not es_abandonada([cliente, cliente])
    assert not es_abandonada([cliente, _saliente(7, 2)])
    assert not es_abandonada([])
