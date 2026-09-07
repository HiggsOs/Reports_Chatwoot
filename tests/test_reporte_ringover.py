from datetime import date

from reporte_ringover import (
    AVISO_SIN_DIRECCIONES,
    CANAL_QUIEN_EMITE,
    CANAL_QUIEN_RECIBE,
    COLUMNAS,
    SIN_TEXTO,
    a_fecha_local,
    canal_del_agente,
    construir_fila,
    escribir_csv,
    formatear_duracion,
    generar_filas,
    nombre_agente,
    nombre_archivo,
    texto_transcripcion,
)
from ringover import RingoverAuthError

TRANSCRIPCION = {
    "call_id": "11801011684818386499",
    "user": {"user_id": 24412200, "concat_name": "tatiana velandia"},
    "transcription_status": "DONE",
    "creation_date": "2026-09-01T08:28:01Z",
    "transcription_data": {
        "duration": 308.16,
        "speeches": [
            {"channelId": 0, "text": "Buen día, servicio de grúa."},
            {"channelId": 1, "text": "Hola, buen día."},
        ],
    },
}


def test_toma_el_nombre_concatenado_del_usuario():
    assert nombre_agente(TRANSCRIPCION) == "tatiana velandia"


def test_arma_el_nombre_con_las_partes_sueltas():
    transcripcion = {"user": {"firstname": "Ana", "lastname": "Gil"}}
    assert nombre_agente(transcripcion) == "Ana Gil"


def test_usuario_sin_nombre_queda_identificado_por_id():
    assert nombre_agente({"user": {"user_id": 42}}) == "Usuario 42"


def test_la_fecha_utc_pasa_a_hora_local():
    momento = a_fecha_local("2026-09-01T08:28:01Z")
    assert momento.strftime("%Y-%m-%d %H:%M") == "2026-09-01 03:28"


def test_fecha_invalida_no_rompe():
    assert a_fecha_local("no es una fecha") is None
    assert a_fecha_local(None) is None


def test_duracion_en_segundos_con_dos_decimales():
    assert formatear_duracion(308.156) == "308.16s"
    assert formatear_duracion("18.4") == "18.40s"
    assert formatear_duracion(None) == ""


def test_en_una_entrante_el_agente_es_quien_recibe():
    assert canal_del_agente("in") == CANAL_QUIEN_RECIBE


def test_en_una_saliente_el_agente_es_quien_emite():
    assert canal_del_agente("OUT") == CANAL_QUIEN_EMITE


def test_sin_direccion_conocida_se_supone_entrante():
    assert canal_del_agente(None) == CANAL_QUIEN_RECIBE


INTERVENCIONES = [
    {"channelId": 0, "text": "Servicio de grúa."},
    {"channelId": 1, "text": "Buenos días."},
]


def test_el_dialogo_de_una_entrante():
    dialogo = texto_transcripcion(INTERVENCIONES, "ANA GIL", CANAL_QUIEN_RECIBE)
    assert dialogo == "[ANA GIL]: Servicio de grúa.\n[Cliente]: Buenos días."


def test_el_dialogo_de_una_saliente_invierte_los_papeles():
    dialogo = texto_transcripcion(INTERVENCIONES, "ANA GIL", CANAL_QUIEN_EMITE)
    assert dialogo == "[Cliente]: Servicio de grúa.\n[ANA GIL]: Buenos días."


def test_se_ignoran_las_intervenciones_vacias():
    assert texto_transcripcion([{"channelId": 0, "text": "   "}], "ANA") == ""


def test_la_fila_usa_la_direccion_de_la_llamada():
    fila = construir_fila(TRANSCRIPCION, {TRANSCRIPCION["call_id"]: "out"})
    assert fila["transcripcion_completa"].startswith("[Cliente]: Buen día")


def test_la_fila_tiene_las_columnas_del_reporte():
    fila = construir_fila(TRANSCRIPCION)

    assert set(fila) == set(COLUMNAS)
    assert fila["call_id"] == "11801011684818386499"
    assert fila["agente"] == "tatiana velandia"
    assert fila["fecha"] == "2026-09-01 03:28"
    assert fila["duracion_total"] == "308.16s"
    assert fila["estado"] == "DONE"
    assert fila["transcripcion_completa"].startswith("[tatiana velandia]: Buen día")


def test_llamada_sin_texto_queda_marcada():
    fila = construir_fila({"call_id": "1", "transcription_data": {"speeches": []}})
    assert fila["transcripcion_completa"] == SIN_TEXTO


class ClienteFalso:
    def __init__(self, transcripciones, direcciones=None, error=None):
        self._transcripciones = transcripciones
        self._direcciones = direcciones or {}
        self._error = error

    def listar_transcripciones(self, desde, hasta, al_avanzar=None):
        return self._transcripciones

    def listar_direcciones(self, desde, hasta):
        if self._error:
            raise self._error
        return self._direcciones


def test_las_filas_quedan_ordenadas_por_fecha():
    tarde = dict(TRANSCRIPCION, call_id="2", creation_date="2026-09-02T08:00:00Z")
    filas = generar_filas(ClienteFalso([tarde, TRANSCRIPCION]), None, None)

    assert [fila["call_id"] for fila in filas] == ["11801011684818386499", "2"]


def test_las_direcciones_llegan_hasta_las_filas():
    cliente = ClienteFalso([TRANSCRIPCION], {TRANSCRIPCION["call_id"]: "out"})
    filas = generar_filas(cliente, None, None)

    assert filas[0]["transcripcion_completa"].startswith("[Cliente]: ")


def test_sin_permiso_de_llamadas_avisa_y_sigue():
    cliente = ClienteFalso([TRANSCRIPCION], error=RingoverAuthError("sin permiso"))
    avisos = []

    filas = generar_filas(cliente, None, None, al_advertir=avisos.append)

    assert avisos == [AVISO_SIN_DIRECCIONES]
    assert filas[0]["transcripcion_completa"].startswith("[tatiana velandia]: ")


def test_sin_permiso_de_llamadas_y_sin_quien_escuche_el_aviso():
    cliente = ClienteFalso([TRANSCRIPCION], error=RingoverAuthError("sin permiso"))
    assert len(generar_filas(cliente, None, None)) == 1


def test_el_csv_lleva_bom_y_encabezados():
    csv = escribir_csv([construir_fila(TRANSCRIPCION)])

    assert csv.startswith("﻿".encode("utf-8"))
    texto = csv.decode("utf-8-sig")
    assert texto.splitlines()[0] == ",".join(COLUMNAS)
    assert "tatiana velandia" in texto


def test_nombre_del_archivo():
    assert (
        nombre_archivo(date(2026, 9, 1), date(2026, 9, 30))
        == "reporte-transcripciones-2026-09-01-a-2026-09-30.csv"
    )
