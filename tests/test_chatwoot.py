from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
import responses

from chatwoot import ChatwootAuthError, ChatwootError, ClienteChatwoot

BOGOTA = ZoneInfo("America/Bogota")
DESDE = datetime(2026, 9, 1, 0, 0, tzinfo=BOGOTA)
HASTA = datetime(2026, 9, 30, 23, 59, tzinfo=BOGOTA)

URL_FILTRO = "https://chat.ejemplo.com/api/v1/accounts/7/conversations/filter"


def cliente():
    return ClienteChatwoot("https://chat.ejemplo.com", 7, "token-secreto")


def pagina(ids):
    return {"payload": [{"id": i} for i in ids]}


@responses.activate
def test_recorre_todas_las_paginas():
    responses.post(URL_FILTRO, json=pagina([1, 2]))
    responses.post(URL_FILTRO, json=pagina([3]))
    responses.post(URL_FILTRO, json=pagina([]))

    conversaciones = cliente().listar_conversaciones(DESDE, HASTA)

    assert [c["id"] for c in conversaciones] == [1, 2, 3]
    assert len(responses.calls) == 3


@responses.activate
def test_envia_el_token_y_el_rango_de_fechas():
    responses.post(URL_FILTRO, json=pagina([]))

    cliente().listar_conversaciones(DESDE, HASTA)

    peticion = responses.calls[0].request
    assert peticion.headers["api_access_token"] == "token-secreto"
    cuerpo = peticion.body.decode() if isinstance(peticion.body, bytes) else peticion.body
    assert str(int(DESDE.timestamp())) in cuerpo
    assert str(int(HASTA.timestamp())) in cuerpo


@responses.activate
def test_pide_paginas_consecutivas():
    responses.post(URL_FILTRO, json=pagina([1]))
    responses.post(URL_FILTRO, json=pagina([]))

    cliente().listar_conversaciones(DESDE, HASTA)

    assert "page=1" in responses.calls[0].request.url
    assert "page=2" in responses.calls[1].request.url


@responses.activate
def test_token_invalido_da_error_claro():
    responses.post(URL_FILTRO, status=401, json={"error": "no autorizado"})

    with pytest.raises(ChatwootAuthError) as error:
        cliente().listar_conversaciones(DESDE, HASTA)
    assert "token" in str(error.value).lower()


@responses.activate
def test_error_del_servidor_persistente():
    # Retry-After en 0 para que el test no espere los reintentos reales.
    for _ in range(6):
        responses.post(URL_FILTRO, status=500, headers={"Retry-After": "0"}, json={})

    with pytest.raises(ChatwootError) as error:
        cliente().listar_conversaciones(DESDE, HASTA)
    assert "5 intentos" in str(error.value)
