from datetime import datetime, timedelta, timezone

import pytest

from panel.asignacion.servicio import DESDE_SIEMPRE
from panel.db.base import unidad_de_trabajo
from panel.db.repositorios.cuentas import RepositorioCuentas
from panel.db.repositorios.personas import RepositorioPersonas
from panel.esquemas.personas import AsesorArea
from panel.fuentes.cuentas import CuentaExterna
from panel.fuentes.interacciones import ConversacionExterna, LlamadaExterna
from panel.servicios import consultas
from panel.servicios.interacciones import ServicioInteracciones
from panel.sync.__main__ import main

UTC = timezone.utc
INICIO = datetime(2026, 11, 3, 9, 0, tzinfo=UTC)


def llamada(id_externo, agente, horas, telefono):
    return LlamadaExterna(
        id_externo=id_externo,
        agente=CuentaExterna(id_externo=agente, nombre=f"Agente {agente}"),
        inicio=INICIO + timedelta(hours=horas),
        duracion_s=90,
        direccion="entrante",
        grabada=True,
        enlace_plataforma=None,
        telefono_cliente=telefono,
        nombre_cliente=f"Cliente {id_externo}",
        datos_origen={},
    )


@pytest.fixture
def datos(fabrica):
    with unidad_de_trabajo(fabrica) as sesion:
        RepositorioPersonas(sesion).sincronizar_areas(
            [AsesorArea(correo="ana@e.com", area="RDC", nombre="Ana")]
        )
        ana = RepositorioPersonas(sesion).listar()[0].id
        servicio = ServicioInteracciones(sesion)
        servicio.guardar_llamadas(
            [
                llamada("1", "A", 0, "612345678"),
                llamada("2", "A", 1, "699000111"),
                llamada("3", "B", 2, "612345678"),
            ]
        )
        cuenta_a = RepositorioCuentas(sesion).de_plataforma("cloudtalk")["A"].id
        servicio.asignacion.crear_regla(cuenta_a, "dueno_unico", {"persona_id": ana}, DESDE_SIEMPRE)
        servicio.reasignar_cuenta(cuenta_a, DESDE_SIEMPRE)
        servicio.guardar_conversaciones(
            [
                (
                    ConversacionExterna(
                        id_externo="9",
                        usuario=None,
                        inicio=INICIO,
                        ultima_actividad=INICIO,
                        canal="WhatsApp",
                        estado="resolved",
                        etiquetas=["a", "b"],
                        telefono_cliente="612345678",
                        nombre_cliente=None,
                        datos_origen={"id": 9, "status": "resolved"},
                    ),
                    [],
                )
            ]
        )
    return {"ana": ana, "cuenta_a": cuenta_a}


def filtros(**extra):
    return consultas.Filtros(desde=INICIO - timedelta(days=1), hasta=INICIO + timedelta(days=1), **extra)


def llamadas(fabrica, **extra):
    with unidad_de_trabajo(fabrica) as sesion:
        return consultas.listar_llamadas(sesion, filtros(**extra))


def test_lista_las_llamadas_de_la_mas_reciente_a_la_mas_vieja(fabrica, datos):
    filas = llamadas(fabrica)
    assert [f.id_externo for f in filas] == ["3", "2", "1"]
    assert filas[2].asesor == "Ana" and filas[2].area == "RDC"
    assert filas[2].telefono == "+34612345678"
    assert filas[0].asesor == "" and filas[0].motivo == "La cuenta no tiene regla de asignación"


def test_filtra_por_asesor_cuenta_y_sin_asignar(fabrica, datos):
    assert [f.id_externo for f in llamadas(fabrica, persona_ids=[datos["ana"]])] == ["2", "1"]
    assert [f.id_externo for f in llamadas(fabrica, cuenta_ids=[datos["cuenta_a"]])] == ["2", "1"]
    assert [f.id_externo for f in llamadas(fabrica, solo_sin_asignar=True)] == ["3"]


def test_filtra_por_cliente_con_digitos_o_nombre(fabrica, datos):
    assert [f.id_externo for f in llamadas(fabrica, cliente="612 345")] == ["3", "1"]
    assert [f.id_externo for f in llamadas(fabrica, cliente="cliente 2")] == ["2"]


def test_el_rango_excluye_el_final(fabrica, datos):
    with unidad_de_trabajo(fabrica) as sesion:
        filas = consultas.listar_llamadas(
            sesion, consultas.Filtros(desde=INICIO, hasta=INICIO + timedelta(hours=1))
        )
    assert [f.id_externo for f in filas] == ["1"]


def test_conversaciones_y_resumen(fabrica, datos):
    with unidad_de_trabajo(fabrica) as sesion:
        filas = consultas.listar_conversaciones(sesion, filtros())
        numeros = consultas.resumen(sesion, INICIO - timedelta(days=1), INICIO + timedelta(days=1))
    assert filas[0].estado == "resuelta"
    assert filas[0].etiquetas == "a;b"
    assert filas[0].cuenta == "—"
    assert numeros.model_dump() == {
        "llamadas": 3,
        "conversaciones": 1,
        "llamadas_sin_asignar": 1,
        "conversaciones_sin_asignar": 1,
        "cuentas_sin_regla": 1,
    }


def test_a_csv_tiene_bom_y_fechas_legibles(fabrica, datos):
    contenido = consultas.a_csv(llamadas(fabrica), {"id_externo": "Id", "inicio": "Fecha"})
    assert contenido.startswith("﻿".encode("utf-8"))
    lineas = contenido.decode("utf-8-sig").splitlines()
    assert lineas[0] == "Id,Fecha"
    # 09:00 UTC del 3 de noviembre son las 10:00 en Madrid.
    assert lineas[-1] == "1,2026-11-03 10:00"


def test_el_csv_de_llamadas_trae_el_texto_de_la_transcripcion_principal(fabrica, datos):
    import csv
    import io

    from sqlalchemy import select

    from panel.db.modelos import Llamada, TranscripcionGuardada

    def transcripcion(llamada_id, segmentos, principal):
        return TranscripcionGuardada(
            llamada_id=llamada_id, proveedor="falsa", modelo="m", idioma="es", canales_audio="mono",
            segmentos=segmentos, texto="", principal=principal,
        )

    with unidad_de_trabajo(fabrica) as sesion:
        uno = sesion.scalar(select(Llamada.id).where(Llamada.id_externo == "1"))
        sesion.add_all([
            transcripcion(uno, [
                {"hablante": "agente", "texto": "Buenos días, grúas."},
                {"hablante": "desconocido", "etiqueta": "B", "texto": "Necesito una grúa, \"ya\"."},
                {"hablante": "cliente", "texto": "  "},
            ], principal=True),
            transcripcion(uno, [{"hablante": "agente", "texto": "Versión vieja"}], principal=False),
        ])

    with unidad_de_trabajo(fabrica) as sesion:
        filas = consultas.con_transcripciones(sesion, consultas.listar_llamadas(sesion, filtros()))
    contenido = consultas.a_csv(filas, {"id_externo": "Id", "transcripcion_texto": "Texto"})
    leidas = list(csv.DictReader(io.StringIO(contenido.decode("utf-8-sig"))))
    assert {f["Id"]: f["Texto"] for f in leidas} == {
        "3": "",
        "2": "",
        "1": 'Agente: Buenos días, grúas.\nHablante B: Necesito una grúa, "ya".',
    }


def test_el_csv_de_chats_trae_los_mensajes_con_sus_finalizaciones(fabrica, datos):
    import csv
    import io

    from sqlalchemy import select

    from panel.db.modelos import Conversacion

    epoch = int(INICIO.timestamp())  # 10:00 en Madrid
    with unidad_de_trabajo(fabrica) as sesion:
        chat = sesion.scalar(select(Conversacion).where(Conversacion.id_externo == "9"))
        chat.mensajes = [
            {"id": 2, "message_type": 1, "content": "Buenos días,\nle ayudo.", "created_at": epoch + 60,
             "sender": {"name": "Rosa"}},
            {"id": 1, "message_type": 0, "content": "Necesito una grúa", "created_at": epoch,
             "sender": {"name": "Juan"}},
            {"id": 3, "message_type": 2, "content": "Conversación resuelta", "created_at": epoch + 120},
            {"id": 4, "message_type": 1, "private": True, "content": "Cliente habitual", "created_at": epoch + 180,
             "sender": {"name": "Rosa"}},
            {"id": 5, "message_type": 0, "content": None, "created_at": epoch + 240,
             "attachments": [{"file_type": "image"}]},
        ]
        comunes = {"canal": "WhatsApp", "estado": "resolved", "direccion": "Entrante", "datos_origen": {}}
        sesion.add_all([
            # La finalización: un mensaje del cliente que se suma al chat de arriba.
            Conversacion(id_externo="10", inicio=INICIO + timedelta(hours=2), continua_de_id=chat.id,
                         mensajes=[{"id": 9, "message_type": 0, "content": "Gracias", "created_at": epoch + 7200}],
                         **comunes),
            Conversacion(id_externo="11", inicio=INICIO + timedelta(hours=3), mensajes=None, **comunes),
        ])

    with unidad_de_trabajo(fabrica) as sesion:
        filas = consultas.con_textos_de_chat(sesion, consultas.listar_conversaciones(sesion, filtros()))
    contenido = consultas.a_csv(filas, {"id_externo": "Id", "chat_texto": "Texto"})
    leidas = {f["Id"]: f["Texto"] for f in csv.DictReader(io.StringIO(contenido.decode("utf-8-sig")))}
    assert leidas == {
        "9": "\n".join([
            "[03/11 10:00] Cliente (Juan): Necesito una grúa",
            "[03/11 10:01] Asesor (Rosa): Buenos días, le ayudo.",
            "[03/11 10:03] Nota interna (Rosa): Cliente habitual",
            "[03/11 10:04] Cliente: [adjunto: image]",
            "[03/11 12:00] Cliente: Gracias",
        ]),
        "11": "(los mensajes todavía no están guardados)",
    }


def test_sync_rechaza_una_fecha_invalida():
    with pytest.raises(SystemExit) as salida:
        main(["--desde", "2026-13-01"])
    assert salida.value.code == 2


def test_sync_sin_configuracion_termina_con_error(monkeypatch):
    monkeypatch.setattr("os.environ", {})
    assert main(["--una-vez"]) == 2


def test_audios_por_vencer(fabrica):
    from datetime import datetime, timedelta, timezone

    from panel.db.base import unidad_de_trabajo
    from panel.db.modelos import Llamada
    from panel.servicios.consultas import audios_por_vencer
    from tests.test_audio_servicio import guardar_llamada

    ahora = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
    pronto = guardar_llamada(fabrica, "pronto", dias_atras=1)
    lejos = guardar_llamada(fabrica, "lejos", dias_atras=1)
    with unidad_de_trabajo(fabrica) as sesion:
        for llamada_id, dias in ((pronto, 87), (lejos, 30)):
            fila = sesion.get(Llamada, llamada_id)
            fila.audio_estado, fila.inicio = "guardado", ahora - timedelta(days=dias)
    with unidad_de_trabajo(fabrica) as sesion:
        assert audios_por_vencer(sesion, ahora, 90) == 1
