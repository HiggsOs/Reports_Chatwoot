from datetime import date

from chatwoot import CacheMensajes
from reporte_cloudtalk import (
    COLUMNAS,
    SIN_GRABACION,
    SIN_TRANSCRIPCION,
    TRANSCRITA,
    construir_fila,
    escribir_csv,
    generar_filas,
    nombre_agente,
    nombre_archivo,
    texto_transcripcion,
)

LLAMADA = {
    "Cdr": {
        "id": "27",
        "billsec": "30",
        "type": "incoming",
        "recorded": True,
        "talking_time": "21",
        "started_at": "2026-09-01T08:28:01.000Z",
    },
    "Agent": {"id": "1000", "firstname": "Tatiana", "lastname": "Velandia",
              "fullname": "Tatiana Velandia"},
}

TRANSCRIPCION = {
    "callId": 27,
    "segments": [
        {"start": 5.1, "end": 8.5, "caller": "caller1", "text": "Hola, necesito una grúa."},
        {"start": 1.5, "end": 4.5, "caller": "caller2", "text": "Buen día, servicio de grúa."},
        {"start": 9.0, "end": 9.5, "caller": "caller1", "text": "   "},
    ],
    "callers": [
        {"id": 5000, "type": "contact", "localIdentifier": "caller1"},
        {"id": 1000, "type": "agent", "localIdentifier": "caller2"},
    ],
    "language": "es",
}


class ClienteFalso:
    def __init__(self, llamadas, transcripciones):
        self.llamadas = llamadas
        self.transcripciones = transcripciones
        self.pedidas = []

    def listar_llamadas(self, desde, hasta):
        return self.llamadas

    def obtener_transcripcion(self, call_id):
        self.pedidas.append(call_id)
        return self.transcripciones.get(call_id)


def test_nombre_del_agente():
    assert nombre_agente(LLAMADA) == "Tatiana Velandia"
    assert nombre_agente({"Agent": {"firstname": "Ana", "lastname": "Gil"}}) == "Ana Gil"
    assert nombre_agente({"Cdr": {"user_id": "42"}}) == "Agente 42"


def test_dialogo_ordenado_y_con_hablantes():
    assert texto_transcripcion(TRANSCRIPCION, LLAMADA) == (
        "[Tatiana Velandia]: Buen día, servicio de grúa.\n"
        "[Cliente]: Hola, necesito una grúa."
    )


def test_un_segundo_agente_queda_identificado():
    transcripcion = {
        "segments": [{"start": 0, "caller": "caller3", "text": "Le transfiero."}],
        "callers": [{"id": 2000, "type": "agent", "localIdentifier": "caller3"}],
    }
    assert texto_transcripcion(transcripcion, LLAMADA) == "[Agente 2000]: Le transfiero."


def test_fila_completa():
    fila = construir_fila(LLAMADA, TRANSCRIPCION)

    assert tuple(fila) == COLUMNAS
    assert fila["call_id"] == "27"
    assert fila["fecha"].startswith("2026-09-01 03:28")
    assert fila["direccion"] == "entrante"
    assert fila["duracion_total"] == "21.00s"
    assert fila["estado"] == TRANSCRITA


def test_estado_sin_transcripcion_o_sin_grabacion():
    assert construir_fila(LLAMADA, None)["estado"] == SIN_TRANSCRIPCION
    sin_grabar = {**LLAMADA, "Cdr": {**LLAMADA["Cdr"], "recorded": False}}
    assert construir_fila(sin_grabar, None)["estado"] == SIN_GRABACION


def test_no_pide_transcripcion_de_llamadas_sin_grabar():
    sin_grabar = {**LLAMADA, "Cdr": {**LLAMADA["Cdr"], "id": "28", "recorded": False}}
    cliente = ClienteFalso([LLAMADA, sin_grabar], {"27": TRANSCRIPCION})

    filas = generar_filas(cliente, None, None)

    assert cliente.pedidas == ["27"]
    assert len(filas) == 2


def test_usa_la_cache_y_no_guarda_las_faltantes(tmp_path):
    cache = CacheMensajes(tmp_path)
    otra = {**LLAMADA, "Cdr": {**LLAMADA["Cdr"], "id": "28"}}
    cliente = ClienteFalso([LLAMADA, otra], {"27": TRANSCRIPCION})

    generar_filas(cliente, None, None, cache=cache)
    generar_filas(cliente, None, None, cache=cache)

    # La 27 se pidió una sola vez; la 28, sin transcripción, se vuelve a pedir.
    assert cliente.pedidas == ["27", "28", "28"]
    assert cache.leer("28") is None


def test_avisa_el_avance():
    avances = []
    generar_filas(
        ClienteFalso([LLAMADA], {}), None, None,
        al_avanzar=lambda hechas, total: avances.append((hechas, total)),
    )
    assert avances == [(1, 1)]


def test_csv_con_bom_y_nombre_de_archivo():
    contenido = escribir_csv([construir_fila(LLAMADA, TRANSCRIPCION)])
    assert contenido.startswith(b"\xef\xbb\xbf")
    assert "Buen día" in contenido.decode("utf-8-sig")
    assert nombre_archivo(date(2026, 9, 1), date(2026, 9, 30)) == (
        "reporte-cloudtalk-2026-09-01-a-2026-09-30.csv"
    )
