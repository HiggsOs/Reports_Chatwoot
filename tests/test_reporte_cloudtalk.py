from datetime import date

import reporte_cloudtalk
from chatwoot import CacheMensajes
from reporte_cloudtalk import (
    COLUMNAS,
    SIN_GRABACION,
    SIN_TRANSCRIPCION,
    TRANSCRITA,
    construir_fila,
    escribir_csv,
    formatear_espera,
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
        al_avanzar=lambda hechas, total, _: avances.append((hechas, total)),
    )
    assert avances == [(0, 1), (1, 1)]


def test_estima_con_el_ritmo_del_cliente_y_luego_con_el_medido(monkeypatch):
    llamadas = [
        {**LLAMADA, "Cdr": {**LLAMADA["Cdr"], "id": str(i)}} for i in range(4)
    ]
    cliente = ClienteFalso(llamadas, {})
    cliente.segundos_por_peticion = 1.0
    # Cada descarga tarda 3 s según el reloj: más lento que el ritmo nominal.
    reloj = iter([0.0, 3.0, 6.0, 9.0, 12.0])
    monkeypatch.setattr(reporte_cloudtalk.time, "monotonic", lambda: next(reloj))
    restantes = []

    generar_filas(cliente, None, None, al_avanzar=lambda h, t, r: restantes.append(r))

    # Antes de empezar: 4 pendientes a 1 s. Después: lo que falta a 3 s cada una.
    assert restantes == [4.0, 9.0, 6.0, 3.0, 0.0]


def test_las_que_estan_en_cache_no_suman_tiempo(tmp_path):
    cache = CacheMensajes(tmp_path)
    cache.guardar("27", TRANSCRIPCION)
    restantes = []

    generar_filas(
        ClienteFalso([LLAMADA], {}), None, None, cache=cache,
        al_avanzar=lambda h, t, r: restantes.append(r),
    )

    assert restantes == [0.0, 0.0]


def test_formatear_espera():
    assert formatear_espera(0) == ""
    assert formatear_espera(45) == "menos de 1 min"
    assert formatear_espera(61) == "unos 2 min"
    assert formatear_espera(3600) == "unas 1 h"
    assert formatear_espera(5000) == "unas 1 h 24 min"


def test_csv_con_bom_y_nombre_de_archivo():
    contenido = escribir_csv([construir_fila(LLAMADA, TRANSCRIPCION)])
    assert contenido.startswith(b"\xef\xbb\xbf")
    assert "Buen día" in contenido.decode("utf-8-sig")
    assert nombre_archivo(date(2026, 9, 1), date(2026, 9, 30)) == (
        "reporte-cloudtalk-2026-09-01-a-2026-09-30.csv"
    )
