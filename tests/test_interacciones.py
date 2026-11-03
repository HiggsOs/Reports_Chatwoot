from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from panel.asignacion.servicio import DESDE_SIEMPRE, ReglaInvalida, ServicioAsignacion
from panel.db.base import unidad_de_trabajo
from panel.db.modelos import ASIGNACION_MANUAL, Cliente, Conversacion, Llamada
from panel.db.repositorios.cuentas import RepositorioCuentas
from panel.db.repositorios.personas import RepositorioPersonas
from panel.esquemas.personas import AsesorArea
from panel.fuentes.cuentas import CuentaExterna
from panel.fuentes.interacciones import ConversacionExterna, LlamadaExterna
from panel.servicios import clientes, consultas
from panel.servicios.interacciones import (
    MOTIVO_FINALIZACION,
    MOTIVO_MANUAL,
    MOTIVO_POR_MENSAJES,
    MOTIVO_SIN_USUARIO,
    MOTIVO_SIN_USUARIO_NI_MENSAJES,
    ServicioInteracciones,
)

UTC = timezone.utc
MADRID = ZoneInfo("Europe/Madrid")
AGENTE = CuentaExterna(id_externo="100", nombre="Asesor 3", correo="juan@e.com")
# Martes 3 de noviembre de 2026: 09:00 y 15:00 en Madrid.
MAÑANA = datetime(2026, 11, 3, 8, 0, tzinfo=UTC)
TARDE = datetime(2026, 11, 3, 14, 0, tzinfo=UTC)


def llamada(id_externo, inicio, telefono="612345678", agente=AGENTE):
    return LlamadaExterna(
        id_externo=id_externo,
        agente=agente,
        inicio=inicio,
        duracion_s=60,
        direccion="entrante",
        grabada=True,
        enlace_plataforma=None,
        telefono_cliente=telefono,
        nombre_cliente="Cliente",
        datos_origen={"Cdr": {"id": id_externo}},
    )


def conversacion(
    id_externo, usuario, ultima=None, estado="open", telefono="+34612345678", inicio=MAÑANA
):
    return ConversacionExterna(
        id_externo=id_externo,
        usuario=usuario,
        inicio=inicio,
        ultima_actividad=ultima or inicio,
        canal="WhatsApp",
        estado=estado,
        etiquetas=["venta"],
        telefono_cliente=telefono,
        nombre_cliente="Cliente",
        datos_origen={"id": int(id_externo), "status": estado},
    )


@pytest.fixture
def personas(fabrica):
    with unidad_de_trabajo(fabrica) as sesion:
        repositorio = RepositorioPersonas(sesion)
        repositorio.sincronizar_areas(
            [
                AsesorArea(correo="juan@e.com", area="Comercial", nombre="Juan"),
                AsesorArea(correo="ana@e.com", area="RDC", nombre="Ana"),
            ]
        )
        return {p.nombre.lower(): p.id for p in repositorio.listar()}


def guardar_llamadas(fabrica, *llamadas):
    with unidad_de_trabajo(fabrica) as sesion:
        return ServicioInteracciones(sesion).guardar_llamadas(list(llamadas))


def persona_de(fabrica, modelo, id_externo):
    with unidad_de_trabajo(fabrica) as sesion:
        fila = sesion.scalar(select(modelo).where(modelo.id_externo == id_externo))
        return fila.persona_id, fila.asignacion, fila.motivo_asignacion


def cuenta_id(fabrica, plataforma="cloudtalk", id_externo="100"):
    with unidad_de_trabajo(fabrica) as sesion:
        return RepositorioCuentas(sesion).de_plataforma(plataforma)[id_externo].id


def crear_regla(fabrica, estrategia, parametros, desde=DESDE_SIEMPRE, cuenta=None):
    with unidad_de_trabajo(fabrica) as sesion:
        servicio = ServicioInteracciones(sesion)
        cid = cuenta or cuenta_id(fabrica)
        servicio.asignacion.crear_regla(cid, estrategia, parametros, desde)
        return servicio.reasignar_cuenta(cid, desde)


def fijo_y_resto(personas):
    return {
        "persona_fija_id": personas["juan"],
        "franjas_fijas": [{"dias": [0, 1, 2, 3, 4], "inicio": "08:00", "fin": "14:00"}],
        "persona_resto_id": personas["ana"],
    }


# --- Llamadas ---------------------------------------------------------------


def test_una_llamada_nueva_crea_su_cuenta_y_queda_sin_asignar_sin_regla(fabrica, personas):
    resumen = guardar_llamadas(fabrica, llamada("1", MAÑANA))
    assert (resumen.nuevas, resumen.sin_asignar) == (1, 1)
    persona, origen, motivo = persona_de(fabrica, Llamada, "1")
    assert persona is None and origen == "automatica"
    assert motivo == "La cuenta no tiene regla de asignación"


def test_las_llamadas_se_asignan_con_la_regla_de_la_cuenta(fabrica, personas):
    guardar_llamadas(fabrica, llamada("1", MAÑANA))
    crear_regla(fabrica, "fijo_y_resto", fijo_y_resto(personas))
    guardar_llamadas(fabrica, llamada("1", MAÑANA), llamada("2", TARDE))

    assert persona_de(fabrica, Llamada, "1")[0] == personas["juan"]
    assert persona_de(fabrica, Llamada, "2")[0] == personas["ana"]
    assert persona_de(fabrica, Llamada, "2")[2] == "Fuera del horario fijo"


def test_guardar_dos_veces_no_duplica(fabrica, personas):
    guardar_llamadas(fabrica, llamada("1", MAÑANA))
    resumen = guardar_llamadas(fabrica, llamada("1", MAÑANA))
    assert (resumen.nuevas, resumen.actualizadas) == (0, 1)
    with unidad_de_trabajo(fabrica) as sesion:
        assert len(sesion.scalars(select(Llamada)).all()) == 1


def test_el_mismo_telefono_en_distintos_formatos_es_un_solo_cliente(fabrica, personas):
    guardar_llamadas(
        fabrica, llamada("1", MAÑANA, "612 345 678"), llamada("2", TARDE, "0034612345678")
    )
    with unidad_de_trabajo(fabrica) as sesion:
        clientes = sesion.scalars(select(Cliente)).all()
        assert [c.telefono for c in clientes] == ["+34612345678"]
        assert {ll.cliente_id for ll in sesion.scalars(select(Llamada))} == {clientes[0].id}


def test_un_telefono_raro_queda_marcado_para_revisar(fabrica, personas):
    guardar_llamadas(fabrica, llamada("1", MAÑANA, "123"))
    with unidad_de_trabajo(fabrica) as sesion:
        cliente = sesion.scalar(select(Cliente))
        assert (cliente.telefono, cliente.revisar) == ("123", True)


def test_sin_telefono_no_hay_cliente(fabrica, personas):
    guardar_llamadas(fabrica, llamada("1", MAÑANA, None))
    with unidad_de_trabajo(fabrica) as sesion:
        assert sesion.scalar(select(Llamada)).cliente_id is None


# --- Asignación manual y reasignación ---------------------------------------


def test_la_asignacion_manual_no_se_pisa(fabrica, personas):
    guardar_llamadas(fabrica, llamada("1", MAÑANA))
    crear_regla(fabrica, "dueno_unico", {"persona_id": personas["juan"]})
    with unidad_de_trabajo(fabrica) as sesion:
        llamada_id = sesion.scalar(select(Llamada.id))
        ServicioInteracciones(sesion).asignar_manual("llamada", llamada_id, personas["ana"])

    guardar_llamadas(fabrica, llamada("1", MAÑANA))
    crear_regla(
        fabrica, "dueno_unico", {"persona_id": personas["juan"]}, datetime(2026, 1, 1, tzinfo=UTC)
    )
    assert persona_de(fabrica, Llamada, "1") == (personas["ana"], ASIGNACION_MANUAL, MOTIVO_MANUAL)

    with unidad_de_trabajo(fabrica) as sesion:
        ServicioInteracciones(sesion).volver_a_automatica("llamada", llamada_id)
    assert persona_de(fabrica, Llamada, "1")[:2] == (personas["juan"], "automatica")


def test_asignar_a_mano_exige_un_asesor_activo(fabrica, personas):
    guardar_llamadas(fabrica, llamada("1", MAÑANA))
    with unidad_de_trabajo(fabrica) as sesion:
        llamada_id = sesion.scalar(select(Llamada.id))
        with pytest.raises(ValueError):
            ServicioInteracciones(sesion).asignar_manual("llamada", llamada_id, 999999)
        # Dejarla sin asignar a mano sí se puede.
        ServicioInteracciones(sesion).asignar_manual("llamada", llamada_id, None)
    assert persona_de(fabrica, Llamada, "1")[:2] == (None, ASIGNACION_MANUAL)


def test_una_regla_nueva_reasigna_solo_desde_su_fecha(fabrica, personas):
    antes = datetime(2026, 10, 1, 9, tzinfo=UTC)
    guardar_llamadas(fabrica, llamada("viejo", antes), llamada("nuevo", MAÑANA))
    crear_regla(fabrica, "dueno_unico", {"persona_id": personas["juan"]})

    resumen = crear_regla(
        fabrica, "dueno_unico", {"persona_id": personas["ana"]}, datetime(2026, 11, 1, tzinfo=MADRID)
    )
    assert (resumen.revisadas, resumen.cambiaron) == (1, 1)
    assert resumen.por_persona == {"Ana": 1}
    assert persona_de(fabrica, Llamada, "viejo")[0] == personas["juan"]
    assert persona_de(fabrica, Llamada, "nuevo")[0] == personas["ana"]


def test_la_vista_previa_no_guarda_nada(fabrica, personas):
    guardar_llamadas(fabrica, llamada("1", MAÑANA), llamada("2", TARDE))
    crear_regla(fabrica, "dueno_unico", {"persona_id": personas["juan"]})
    cid = cuenta_id(fabrica)

    with unidad_de_trabajo(fabrica) as sesion:
        servicio = ServicioInteracciones(sesion)
        previa = servicio.simular_regla(cid, "fijo_y_resto", fijo_y_resto(personas), DESDE_SIEMPRE)
        assert previa.cambiaron == 1
        assert previa.por_persona == {"Juan": 1, "Ana": 1}
        # Después de simular, todo sigue como estaba, incluso en esta sesión.
        assert servicio.asignacion.resolver(cid, TARDE).persona_id == personas["juan"]

    assert persona_de(fabrica, Llamada, "2")[0] == personas["juan"]
    with unidad_de_trabajo(fabrica) as sesion:
        assert len(ServicioAsignacion(sesion)._reglas.historial(cid)) == 1


def test_la_vista_previa_valida_igual_que_guardar(fabrica, personas):
    guardar_llamadas(fabrica, llamada("1", MAÑANA))
    with unidad_de_trabajo(fabrica) as sesion:
        with pytest.raises(ReglaInvalida):
            ServicioInteracciones(sesion).simular_regla(
                cuenta_id(fabrica), "dueno_unico", {"persona_id": 999999}, DESDE_SIEMPRE
            )


# --- Conversaciones ---------------------------------------------------------


USUARIO_ANA = CuentaExterna(id_externo="9", nombre="Ana", correo="ana@e.com")


def guardar_conversaciones(fabrica, *datos):
    with unidad_de_trabajo(fabrica) as sesion:
        return ServicioInteracciones(sesion).guardar_conversaciones(list(datos))


MENSAJES = [
    {"id": 1, "message_type": 0, "content": "Hola", "created_at": 1},
    {"id": 2, "message_type": 2, "content": "Conversation was marked resolved", "created_at": 1793700000},
]


def test_la_conversacion_se_asigna_al_usuario_por_su_correo(fabrica, personas):
    guardar_conversaciones(fabrica, (conversacion("5", USUARIO_ANA), MENSAJES))
    persona, origen, motivo = persona_de(fabrica, Conversacion, "5")
    assert (persona, origen, motivo) == (personas["ana"], "automatica", "Cuenta de una sola persona")
    with unidad_de_trabajo(fabrica) as sesion:
        guardada = sesion.scalar(select(Conversacion))
        assert guardada.direccion == "Entrante"
        assert guardada.etiquetas == ["venta"]


def test_conversacion_sin_usuario_ni_mensajes_de_asesores_queda_sin_asignar(fabrica, personas):
    guardar_conversaciones(fabrica, (conversacion("5", None), MENSAJES))
    assert persona_de(fabrica, Conversacion, "5") == (
        None,
        "automatica",
        MOTIVO_SIN_USUARIO_NI_MENSAJES,
    )


def test_conversacion_sin_usuario_ni_mensajes_guardados_queda_sin_asignar(fabrica, personas):
    guardar_conversaciones(fabrica, (conversacion("5", None), None))
    assert persona_de(fabrica, Conversacion, "5") == (None, "automatica", MOTIVO_SIN_USUARIO)


USUARIO_JUAN = CuentaExterna(id_externo="8", nombre="Juan", correo="juan@e.com")


def saliente(id_mensaje, usuario_id, **extra):
    return {
        "id": id_mensaje,
        "message_type": 1,
        "content": "Respuesta",
        "created_at": 1793700000 + id_mensaje,
        "sender_type": "User",
        "sender_id": usuario_id,
        "sender": {"id": usuario_id, "name": f"Usuario {usuario_id}", "type": "user"},
        **extra,
    }


def chat_de_ana_y_juan():
    """Ana envía dos mensajes y Juan uno; una nota privada de Juan no cuenta."""
    return [
        {"id": 1, "message_type": 0, "content": "Hola", "created_at": 1793700000},
        saliente(2, 8),
        saliente(3, 9),
        saliente(4, 9),
        saliente(5, 8, private=True),
        saliente(6, 8, private=True),
    ]


def con_cuentas_de_chatwoot(fabrica):
    """Las cuentas de Ana y Juan, con su regla por correo, como las deja
    «Actualizar cuentas»."""
    guardar_conversaciones(
        fabrica, (conversacion("1", USUARIO_ANA), []), (conversacion("2", USUARIO_JUAN), [])
    )


def test_sin_usuario_se_asigna_al_asesor_que_mas_mensajes_envio(fabrica, personas):
    con_cuentas_de_chatwoot(fabrica)
    resumen = guardar_conversaciones(fabrica, (conversacion("5", None), chat_de_ana_y_juan()))
    persona, origen, motivo = persona_de(fabrica, Conversacion, "5")
    assert (persona, origen) == (personas["ana"], "automatica")
    assert motivo == f"{MOTIVO_POR_MENSAJES} · Cuenta de una sola persona"
    assert resumen.sin_asignar == 0
    with unidad_de_trabajo(fabrica) as sesion:
        guardada = sesion.scalar(select(Conversacion).where(Conversacion.id_externo == "5"))
        assert guardada.cuenta.id_externo == "9"
        assert guardada.cuenta_por_mensajes


def test_sin_usuario_usa_los_mensajes_ya_guardados(fabrica, personas):
    con_cuentas_de_chatwoot(fabrica)
    guardar_conversaciones(fabrica, (conversacion("5", None), chat_de_ana_y_juan()))
    guardar_conversaciones(fabrica, (conversacion("5", None), None))
    assert persona_de(fabrica, Conversacion, "5")[0] == personas["ana"]


def test_cuando_chatwoot_asigna_usuario_manda_el_usuario(fabrica, personas):
    con_cuentas_de_chatwoot(fabrica)
    guardar_conversaciones(fabrica, (conversacion("5", None), chat_de_ana_y_juan()))
    guardar_conversaciones(fabrica, (conversacion("5", USUARIO_JUAN), None))
    persona, _, motivo = persona_de(fabrica, Conversacion, "5")
    assert (persona, motivo) == (personas["juan"], "Cuenta de una sola persona")
    with unidad_de_trabajo(fabrica) as sesion:
        assert not sesion.scalar(
            select(Conversacion.cuenta_por_mensajes).where(Conversacion.id_externo == "5")
        )


def test_la_asignacion_por_mensajes_no_pisa_la_manual(fabrica, personas):
    con_cuentas_de_chatwoot(fabrica)
    guardar_conversaciones(fabrica, (conversacion("5", None), MENSAJES))
    with unidad_de_trabajo(fabrica) as sesion:
        conversacion_id = sesion.scalar(
            select(Conversacion.id).where(Conversacion.id_externo == "5")
        )
        ServicioInteracciones(sesion).asignar_manual(
            "conversacion", conversacion_id, personas["juan"]
        )
    guardar_conversaciones(fabrica, (conversacion("5", None), chat_de_ana_y_juan()))
    assert persona_de(fabrica, Conversacion, "5")[:2] == (personas["juan"], ASIGNACION_MANUAL)


def test_sin_mensajes_conserva_direccion_y_cierre(fabrica, personas):
    guardar_conversaciones(fabrica, (conversacion("5", USUARIO_ANA, estado="resolved"), MENSAJES))
    guardar_conversaciones(fabrica, (conversacion("5", USUARIO_ANA, estado="resolved"), None))
    with unidad_de_trabajo(fabrica) as sesion:
        guardada = sesion.scalar(select(Conversacion))
        assert guardada.direccion == "Entrante"
        assert guardada.cierre is not None


def test_chat_y_llamada_del_mismo_telefono_comparten_cliente(fabrica, personas):
    guardar_llamadas(fabrica, llamada("1", MAÑANA, "612 34 56 78"))
    guardar_conversaciones(fabrica, (conversacion("5", USUARIO_ANA), []))
    with unidad_de_trabajo(fabrica) as sesion:
        assert sesion.scalar(select(Llamada.cliente_id)) == sesion.scalar(
            select(Conversacion.cliente_id)
        )


def test_ultima_actividad_guardada(fabrica, personas):
    ultima = MAÑANA + timedelta(hours=1)
    guardar_conversaciones(
        fabrica, (conversacion("5", None, ultima=ultima), []), (conversacion("7", None), None)
    )
    with unidad_de_trabajo(fabrica) as sesion:
        assert ServicioInteracciones(sesion).ultima_actividad_guardada(["5", "6", "7"]) == {
            "5": (ultima, True),
            "7": (MAÑANA, False),
        }


# --- Finalización de una conversación abandonada -----------------------------


UN_MENSAJE = [{"id": 1, "message_type": 0, "content": "Gracias", "created_at": 1793800000}]
DIA_SIGUIENTE = MAÑANA + timedelta(days=1)


def conversacion_de(fabrica, id_externo):
    with unidad_de_trabajo(fabrica) as sesion:
        return sesion.scalar(select(Conversacion).where(Conversacion.id_externo == id_externo))


def test_la_abandonada_finaliza_la_anterior_y_toma_su_asesor(fabrica, personas):
    guardar_conversaciones(fabrica, (conversacion("5", USUARIO_ANA), MENSAJES))
    guardar_conversaciones(
        fabrica, (conversacion("6", None, inicio=DIA_SIGUIENTE), UN_MENSAJE)
    )
    anterior, abandonada = conversacion_de(fabrica, "5"), conversacion_de(fabrica, "6")
    assert abandonada.continua_de_id == anterior.id
    assert abandonada.persona_id == personas["ana"]
    assert abandonada.cuenta_id == anterior.cuenta_id
    assert abandonada.motivo_asignacion == MOTIVO_FINALIZACION.format(anterior="5")


def test_la_abandonada_no_cuenta_como_conversacion_nueva(fabrica, personas):
    guardar_conversaciones(fabrica, (conversacion("5", USUARIO_ANA), MENSAJES))
    guardar_conversaciones(
        fabrica, (conversacion("6", None, inicio=DIA_SIGUIENTE), UN_MENSAJE)
    )
    with unidad_de_trabajo(fabrica) as sesion:
        filtros = consultas.Filtros(desde=MAÑANA - timedelta(days=1), hasta=MAÑANA + timedelta(days=3))
        assert [f.id_externo for f in consultas.listar_conversaciones(sesion, filtros)] == ["5"]
        conteo = consultas.resumen(sesion, filtros.desde, filtros.hasta)
        assert (conteo.conversaciones, conteo.conversaciones_sin_asignar) == (1, 0)

        cliente_id = conversacion_de(fabrica, "5").cliente_id
        historial = clientes.historial(sesion, cliente_id)
        assert historial.cliente.conversaciones == 1
        assert [e.finalizacion for e in historial.elementos] == [True, False]
        assert sum(historial.por_asesor.values()) == 1


def test_en_el_mismo_lote_tambien_encuentra_la_anterior(fabrica, personas):
    guardar_conversaciones(
        fabrica,
        (conversacion("6", None, inicio=DIA_SIGUIENTE), UN_MENSAJE),
        (conversacion("5", USUARIO_ANA), MENSAJES),
    )
    assert conversacion_de(fabrica, "6").persona_id == personas["ana"]


def test_pasado_el_plazo_queda_como_conversacion_propia(fabrica, personas):
    guardar_conversaciones(fabrica, (conversacion("5", USUARIO_ANA), MENSAJES))
    guardar_conversaciones(
        fabrica, (conversacion("6", None, inicio=MAÑANA + timedelta(days=8)), UN_MENSAJE)
    )
    abandonada = conversacion_de(fabrica, "6")
    assert (abandonada.continua_de_id, abandonada.persona_id) == (None, None)


def test_el_plazo_se_puede_cambiar(fabrica, personas):
    guardar_conversaciones(fabrica, (conversacion("5", USUARIO_ANA), MENSAJES))
    with unidad_de_trabajo(fabrica) as sesion:
        ServicioInteracciones(sesion, plazo_finalizacion=timedelta(hours=12)).guardar_conversaciones(
            [(conversacion("6", None, inicio=DIA_SIGUIENTE), UN_MENSAJE)]
        )
    assert conversacion_de(fabrica, "6").continua_de_id is None


def test_dos_mensajes_del_cliente_no_es_abandonada(fabrica, personas):
    guardar_conversaciones(fabrica, (conversacion("5", USUARIO_ANA), MENSAJES))
    dos = UN_MENSAJE + [{"id": 2, "message_type": 0, "content": "¿Hola?", "created_at": 1793800100}]
    guardar_conversaciones(fabrica, (conversacion("6", None, inicio=DIA_SIGUIENTE), dos))
    assert conversacion_de(fabrica, "6").continua_de_id is None


def test_otro_cliente_no_se_une(fabrica, personas):
    guardar_conversaciones(fabrica, (conversacion("5", USUARIO_ANA), MENSAJES))
    guardar_conversaciones(
        fabrica,
        (conversacion("6", None, inicio=DIA_SIGUIENTE, telefono="+34699999999"), UN_MENSAJE),
    )
    assert conversacion_de(fabrica, "6").continua_de_id is None


def test_si_la_anterior_cambia_de_asesor_la_finalizacion_la_sigue(fabrica, personas):
    guardar_conversaciones(fabrica, (conversacion("5", USUARIO_ANA), MENSAJES))
    guardar_conversaciones(
        fabrica, (conversacion("6", None, inicio=DIA_SIGUIENTE), UN_MENSAJE)
    )
    with unidad_de_trabajo(fabrica) as sesion:
        ServicioInteracciones(sesion).asignar_manual(
            "conversacion", conversacion_de(fabrica, "5").id, personas["juan"]
        )
    assert conversacion_de(fabrica, "6").persona_id == personas["juan"]


def test_si_un_asesor_responde_deja_de_ser_finalizacion(fabrica, personas):
    con_cuentas_de_chatwoot(fabrica)
    guardar_conversaciones(fabrica, (conversacion("5", USUARIO_ANA), MENSAJES))
    guardar_conversaciones(
        fabrica, (conversacion("6", None, inicio=DIA_SIGUIENTE), UN_MENSAJE)
    )
    respondida = UN_MENSAJE + [saliente(2, 8)]
    guardar_conversaciones(fabrica, (conversacion("6", None, inicio=DIA_SIGUIENTE), respondida))
    abandonada = conversacion_de(fabrica, "6")
    assert (abandonada.continua_de_id, abandonada.persona_id) == (None, personas["juan"])
