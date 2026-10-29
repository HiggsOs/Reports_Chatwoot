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


def test_sync_rechaza_una_fecha_invalida():
    with pytest.raises(SystemExit) as salida:
        main(["--desde", "2026-13-01"])
    assert salida.value.code == 2


def test_sync_sin_configuracion_termina_con_error(monkeypatch):
    monkeypatch.setattr("os.environ", {})
    assert main(["--una-vez"]) == 2
