from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
import responses

from ringover import ClienteRingover, RingoverAuthError, RingoverError

BOGOTA = ZoneInfo("America/Bogota")
DESDE = datetime(2026, 9, 1, 0, 0, tzinfo=BOGOTA)
HASTA = datetime(2026, 9, 30, 23, 59, 59, tzinfo=BOGOTA)

URL = "https://public-api.ringover.com/v2/transcriptions"


def cliente():
    return ClienteRingover("token-secreto")


def pagina(cantidad: int, desde: int = 0):
    return [{"call_id": str(desde + i)} for i in range(cantidad)]


@responses.activate
def test_envia_el_token_y_el_rango_en_utc():
    responses.get(URL, json=[])

    cliente().listar_transcripciones(DESDE, HASTA)

    peticion = responses.calls[0].request
    assert peticion.headers["Authorization"] == "token-secreto"
    # Bogotá es UTC-5: el 1 de septiembre a las 00:00 local son las 05:00 UTC.
    assert "created_from=2026-09-01T05%3A00%3A00Z" in peticion.url
    assert "created_to=2026-10-01T04%3A59%3A59Z" in peticion.url
    assert "limit_count=100" in peticion.url


@responses.activate
def test_pagina_hasta_una_pagina_incompleta():
    responses.get(URL, json=pagina(100))
    responses.get(URL, json=pagina(30, desde=100))

    transcripciones = cliente().listar_transcripciones(DESDE, HASTA)

    assert len(transcripciones) == 130
    assert len(responses.calls) == 2
    assert "limit_offset=100" in responses.calls[1].request.url


@responses.activate
def test_se_detiene_con_una_pagina_vacia():
    responses.get(URL, json=pagina(100))
    responses.get(URL, json=[])

    assert len(cliente().listar_transcripciones(DESDE, HASTA)) == 100


@responses.activate
def test_sin_contenido_da_lista_vacia():
    responses.get(URL, status=204)

    assert cliente().listar_transcripciones(DESDE, HASTA) == []


@responses.activate
def test_acepta_la_lista_envuelta_en_un_objeto():
    responses.get(URL, json={"list_count": 2, "list": pagina(2)})

    assert len(cliente().listar_transcripciones(DESDE, HASTA)) == 2


@responses.activate
def test_token_rechazado():
    responses.get(URL, status=401, json={})

    with pytest.raises(RingoverAuthError):
        cliente().listar_transcripciones(DESDE, HASTA)


@responses.activate
def test_error_del_servidor_tras_reintentar(monkeypatch):
    monkeypatch.setattr("ringover.time.sleep", lambda _: None)
    for _ in range(5):
        responses.get(URL, status=500, json={})

    with pytest.raises(RingoverError):
        cliente().listar_transcripciones(DESDE, HASTA)


@responses.activate
def test_avisa_del_avance():
    responses.get(URL, json=pagina(100))
    responses.get(URL, json=pagina(5, desde=100))
    avances = []

    cliente().listar_transcripciones(DESDE, HASTA, al_avanzar=avances.append)

    assert avances == [100, 105]


URL_LLAMADAS = "https://public-api.ringover.com/v2/calls"


def llamadas(cantidad: int, desde_cdr: int = 1000, direccion: str = "in"):
    return {
        "call_list_count": cantidad,
        "call_list": [
            {
                "cdr_id": desde_cdr - i,
                "call_id": str(desde_cdr - i),
                "direction": direccion,
            }
            for i in range(cantidad)
        ],
    }


@responses.activate
def test_las_direcciones_salen_del_registro_de_llamadas():
    responses.get(URL_LLAMADAS, json=llamadas(2, direccion="OUT"))

    assert cliente().listar_direcciones(DESDE, HASTA) == {"1000": "out", "999": "out"}


@responses.activate
def test_el_rango_se_parte_en_ventanas_de_quince_dias():
    responses.get(URL_LLAMADAS, json=llamadas(1))
    responses.get(URL_LLAMADAS, json=llamadas(1, desde_cdr=500))

    cliente().listar_direcciones(DESDE, HASTA)

    assert len(responses.calls) == 2
    primera, segunda = (llamada.request.url for llamada in responses.calls)
    assert "start_date=2026-09-01T05%3A00%3A00Z" in primera
    assert "end_date=2026-09-16T04%3A59%3A59Z" in primera
    assert "start_date=2026-09-16T05%3A00%3A00Z" in segunda
    assert "end_date=2026-10-01T04%3A59%3A59Z" in segunda


@responses.activate
def test_pagina_las_llamadas_con_el_cursor():
    responses.get(URL_LLAMADAS, json=llamadas(1000, desde_cdr=5000))
    responses.get(URL_LLAMADAS, json=llamadas(4, desde_cdr=4000))

    direcciones = cliente().listar_direcciones(DESDE, DESDE)

    assert len(direcciones) == 1004
    # El cursor pide los registros anteriores al menor cdr_id de la página.
    assert "last_id_returned=4001" in responses.calls[1].request.url


@responses.activate
def test_la_primera_pata_de_una_transferencia_manda():
    responses.get(
        URL_LLAMADAS,
        json={
            "call_list": [
                {"cdr_id": 2, "call_id": "77", "direction": "out"},
                {"cdr_id": 1, "call_id": "77", "direction": "in"},
            ]
        },
    )

    assert cliente().listar_direcciones(DESDE, DESDE) == {"77": "out"}


@responses.activate
def test_sin_llamadas_no_hay_direcciones():
    responses.get(URL_LLAMADAS, status=204)

    assert cliente().listar_direcciones(DESDE, DESDE) == {}
