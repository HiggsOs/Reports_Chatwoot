from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from panel.asignacion.servicio import DESDE_SIEMPRE
from panel.db.base import unidad_de_trabajo
from panel.db.modelos import Cliente, Conversacion
from panel.db.repositorios.cuentas import RepositorioCuentas
from panel.db.repositorios.personas import RepositorioPersonas
from panel.esquemas.personas import AsesorArea
from panel.fuentes.cuentas import CuentaExterna
from panel.fuentes.interacciones import ConversacionExterna, LlamadaExterna
from panel.servicios import clientes
from panel.servicios.interacciones import ServicioInteracciones

UTC = timezone.utc
MADRID = ZoneInfo("Europe/Madrid")
INICIO = datetime(2026, 11, 3, 9, 0, tzinfo=UTC)

MENSAJES = [
    {"id": 3, "message_type": 1, "content": "Le enviamos la grúa.", "created_at": 1793710800,
     "sender": {"name": "Ana"}},
    {"id": 1, "message_type": 0, "content": "Necesito una grúa", "created_at": 1793707200,
     "sender": {"name": "Pedro"}},
    {"id": 2, "message_type": 2, "content": "Conversación asignada a Ana", "created_at": 1793707300},
    {"id": 4, "message_type": 1, "content": "Cliente VIP", "private": True, "created_at": 1793710900,
     "sender": {"name": "Luis"}},
    {"id": 5, "message_type": 0, "content": None, "attachments": [{"file_type": "image"}],
     "created_at": 1793711000},
    {"id": 6, "message_type": 0, "content": "   ", "created_at": 1793711100},
]


def llamada(id_externo, horas, telefono, duracion=95):
    return LlamadaExterna(
        id_externo=id_externo,
        agente=CuentaExterna(id_externo="100", nombre="Asesor 3"),
        inicio=INICIO + timedelta(hours=horas),
        duracion_s=duracion,
        direccion="entrante",
        grabada=True,
        enlace_plataforma=None,
        telefono_cliente=telefono,
        nombre_cliente="Pedro Grúas",
        datos_origen={},
    )


def conversacion(id_externo, horas, telefono):
    return ConversacionExterna(
        id_externo=id_externo,
        usuario=CuentaExterna(id_externo="9", nombre="Ana", correo="ana@e.com"),
        inicio=INICIO + timedelta(hours=horas),
        ultima_actividad=INICIO + timedelta(hours=horas),
        canal="WhatsApp Ventas",
        estado="resolved",
        etiquetas=["grua"],
        telefono_cliente=telefono,
        nombre_cliente=None,
        datos_origen={"id": int(id_externo), "status": "resolved"},
    )


@pytest.fixture
def datos(fabrica):
    with unidad_de_trabajo(fabrica) as sesion:
        RepositorioPersonas(sesion).sincronizar_areas(
            [
                AsesorArea(correo="ana@e.com", area="RDC", nombre="Ana"),
                AsesorArea(correo="juan@e.com", area="Comercial", nombre="Juan"),
            ]
        )
        servicio = ServicioInteracciones(sesion)
        servicio.guardar_llamadas(
            [
                llamada("1", 0, "612 345 678"),
                llamada("2", 5, "+34612345678", duracion=40),
                llamada("3", 1, "699000111"),
            ]
        )
        juan = RepositorioPersonas(sesion).activa_por_correo("juan@e.com").id
        cuenta = RepositorioCuentas(sesion).de_plataforma("cloudtalk")["100"].id
        servicio.asignacion.crear_regla(cuenta, "dueno_unico", {"persona_id": juan}, DESDE_SIEMPRE)
        servicio.reasignar_cuenta(cuenta, DESDE_SIEMPRE)
        servicio.guardar_conversaciones([(conversacion("50", 2, "0034612345678"), MENSAJES)])
        cliente = sesion.scalar(select(Cliente).where(Cliente.telefono == "+34612345678")).id
    return {"cliente": cliente}


def buscar(fabrica, texto="", solo_revisar=False):
    with unidad_de_trabajo(fabrica) as sesion:
        return clientes.buscar(sesion, texto, solo_revisar)


@pytest.mark.parametrize("texto", ["612 345 678", "+34612345678", "0034 612345678", "345678", "pedro"])
def test_busca_por_telefono_en_cualquier_formato_o_por_nombre(fabrica, datos, texto):
    assert datos["cliente"] in [c.id for c in buscar(fabrica, texto)]


def test_resumen_del_cliente(fabrica, datos):
    encontrado = [c for c in buscar(fabrica, "612345678") if c.id == datos["cliente"]][0]
    assert (encontrado.llamadas, encontrado.conversaciones) == (2, 1)
    assert encontrado.ultima == (INICIO + timedelta(hours=5)).astimezone(MADRID)
    assert encontrado.etiqueta == "Pedro Grúas · +34612345678"


def test_sin_texto_muestra_los_mas_recientes_primero(fabrica, datos):
    assert [c.telefono for c in buscar(fabrica)] == ["+34612345678", "+34699000111"]


def test_solo_los_telefonos_por_revisar(fabrica, datos):
    with unidad_de_trabajo(fabrica) as sesion:
        ServicioInteracciones(sesion).guardar_llamadas([llamada("9", 3, "123")])
    assert [c.telefono for c in buscar(fabrica, solo_revisar=True)] == ["123"]


def test_historial_mezcla_llamadas_y_chats_del_mas_reciente_al_mas_viejo(fabrica, datos):
    with unidad_de_trabajo(fabrica) as sesion:
        resultado = clientes.historial(sesion, datos["cliente"])
    assert [(e.tipo, e.id_externo) for e in resultado.elementos] == [
        ("llamada", "2"),
        ("conversacion", "50"),
        ("llamada", "1"),
    ]
    assert resultado.elementos[0].resumen == "Llamada entrante · 40 s"
    assert resultado.elementos[2].resumen == "Llamada entrante · 1 min 35 s"
    assert resultado.elementos[1].resumen == "Chat por WhatsApp Ventas · resuelta · grua"
    assert resultado.elementos[1].asesor == "Ana"
    assert resultado.por_asesor == {"Juan": 2, "Ana": 1}


def test_historial_de_un_cliente_que_no_existe(fabrica, datos):
    with unidad_de_trabajo(fabrica) as sesion:
        assert clientes.historial(sesion, 999999) is None


def test_mensajes_legibles_en_orden_y_con_su_autor(fabrica, datos):
    with unidad_de_trabajo(fabrica) as sesion:
        conversacion_id = sesion.scalar(select(Conversacion.id))
        mensajes = clientes.mensajes_de_conversacion(sesion, conversacion_id)
    assert [(m.rol, m.autor, m.texto) for m in mensajes] == [
        ("cliente", "Pedro", "Necesito una grúa"),
        ("actividad", "", "Conversación asignada a Ana"),
        ("asesor", "Ana", "Le enviamos la grúa."),
        ("nota", "Luis", "Cliente VIP"),
        ("cliente", "Cliente", "[adjunto: image]"),
    ]
    assert mensajes[0].fecha == datetime.fromtimestamp(1793707200, MADRID)


def test_una_conversacion_sin_mensajes_guardados(fabrica, datos):
    with unidad_de_trabajo(fabrica) as sesion:
        ServicioInteracciones(sesion).guardar_conversaciones([(conversacion("51", 1, None), None)])
        conversacion_id = sesion.scalar(select(Conversacion.id).where(Conversacion.id_externo == "51"))
        assert clientes.mensajes_de_conversacion(sesion, conversacion_id) is None


def test_formatear_duracion():
    assert clientes.formatear_duracion(None) == "duración desconocida"
    assert clientes.formatear_duracion(5) == "5 s"
    assert clientes.formatear_duracion(125) == "2 min 05 s"
