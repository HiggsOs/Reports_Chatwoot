import json
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import responses

from chatwoot import CacheMensajes, ChatwootAuthError, ChatwootError, ClienteChatwoot

BOGOTA = ZoneInfo("America/Bogota")
DESDE = datetime(2026, 9, 1, 0, 0, tzinfo=BOGOTA)
HASTA = datetime(2026, 9, 30, 23, 59, tzinfo=BOGOTA)

URL_FILTRO = "https://chat.ejemplo.com/api/v1/accounts/7/conversations/filter"


def cliente():
    return ClienteChatwoot("https://chat.ejemplo.com", 7, "token-secreto")


EN_RANGO = int(datetime(2026, 9, 15, 12, 0, tzinfo=BOGOTA).timestamp())


def pagina(ids, created_at=EN_RANGO):
    return {"payload": [{"id": i, "created_at": created_at} for i in ids]}


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
    # Se pide un día de margen por lado: DESDE es 2026-09-01 00:00 Bogotá
    # (05:00 UTC), así que la consulta arranca el 2026-08-31 05:00 UTC.
    assert "2026-08-31 05:00:00" in cuerpo
    assert "2026-10-02 04:59:00" in cuerpo


@responses.activate
def test_las_fechas_del_filtro_van_como_texto_y_no_como_epoch():
    """Chatwoot responde 500 si created_at llega como número epoch."""
    responses.post(URL_FILTRO, json=pagina([]))

    cliente().listar_conversaciones(DESDE, HASTA)

    peticion = responses.calls[0].request
    cuerpo = json.loads(
        peticion.body.decode() if isinstance(peticion.body, bytes) else peticion.body
    )
    for clausula in cuerpo["payload"]:
        valor = clausula["values"][0]
        assert isinstance(valor, str), f"{valor!r} debe ser texto, no {type(valor)}"
        assert not valor.isdigit(), f"{valor!r} parece un epoch; Chatwoot lo rechaza"
        datetime.strptime(valor, "%Y-%m-%d %H:%M:%S")


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


URL_MENSAJES = "https://chat.ejemplo.com/api/v1/accounts/7/conversations/42/messages"


@responses.activate
def test_mensajes_en_orden_cronologico():
    responses.get(
        URL_MENSAJES,
        json={"payload": [{"id": 10, "content": "b"}, {"id": 5, "content": "a"}]},
    )
    responses.get(URL_MENSAJES, json={"payload": []})

    mensajes = cliente().listar_mensajes(42)

    assert [m["id"] for m in mensajes] == [5, 10]


@responses.activate
def test_mensajes_paginan_hacia_atras_con_before():
    responses.get(URL_MENSAJES, json={"payload": [{"id": 8}, {"id": 9}]})
    responses.get(URL_MENSAJES, json={"payload": [{"id": 3}]})
    responses.get(URL_MENSAJES, json={"payload": []})

    mensajes = cliente().listar_mensajes(42)

    assert [m["id"] for m in mensajes] == [3, 8, 9]
    assert "before=8" in responses.calls[1].request.url
    assert "before=3" in responses.calls[2].request.url


@responses.activate
def test_reintenta_tras_429_y_luego_tiene_exito():
    responses.get(URL_MENSAJES, status=429, headers={"Retry-After": "0"}, json={})
    responses.get(URL_MENSAJES, json={"payload": [{"id": 1}]})
    responses.get(URL_MENSAJES, json={"payload": []})

    mensajes = cliente().listar_mensajes(42)

    assert [m["id"] for m in mensajes] == [1]
    assert len(responses.calls) == 3


@responses.activate
def test_mensajes_no_se_duplican_si_una_pagina_llega_repetida():
    responses.get(URL_MENSAJES, json={"payload": [{"id": 10}, {"id": 9}, {"id": 8}]})
    responses.get(URL_MENSAJES, json={"payload": [{"id": 10}, {"id": 9}, {"id": 8}]})

    mensajes = cliente().listar_mensajes(42)

    assert [m["id"] for m in mensajes] == [8, 9, 10]


def test_cache_devuelve_none_cuando_no_hay_nada(tmp_path: Path):
    assert CacheMensajes(tmp_path).leer(42) is None


def test_cache_guarda_y_recupera(tmp_path: Path):
    cache = CacheMensajes(tmp_path)
    cache.guardar(42, [{"id": 1, "content": "hola"}])
    assert cache.leer(42) == [{"id": 1, "content": "hola"}]


def test_cache_ignora_un_archivo_corrupto(tmp_path: Path):
    cache = CacheMensajes(tmp_path)
    cache.guardar(42, [{"id": 1}])
    (tmp_path / "42.json").write_text("{roto", encoding="utf-8")
    assert cache.leer(42) is None


def test_cache_crea_el_directorio_si_no_existe(tmp_path: Path):
    destino = tmp_path / "sub" / "cache"
    CacheMensajes(destino).guardar(1, [])
    assert (destino / "1.json").exists()


@responses.activate
def test_descarta_las_conversaciones_fuera_del_rango_exacto():
    """La API acota por día; el recorte fino con la hora se hace aquí."""
    antes_del_rango = int(datetime(2026, 8, 31, 23, 0, tzinfo=BOGOTA).timestamp())
    despues_del_rango = int(datetime(2026, 10, 1, 8, 0, tzinfo=BOGOTA).timestamp())
    responses.post(
        URL_FILTRO,
        json={
            "payload": [
                {"id": 1, "created_at": antes_del_rango},
                {"id": 2, "created_at": EN_RANGO},
                {"id": 3, "created_at": despues_del_rango},
            ]
        },
    )
    responses.post(URL_FILTRO, json=pagina([]))

    conversaciones = cliente().listar_conversaciones(DESDE, HASTA)

    assert [c["id"] for c in conversaciones] == [2]


@responses.activate
def test_conserva_los_bordes_exactos_del_rango():
    responses.post(
        URL_FILTRO,
        json={
            "payload": [
                {"id": 1, "created_at": int(DESDE.timestamp())},
                {"id": 2, "created_at": int(HASTA.timestamp())},
            ]
        },
    )
    responses.post(URL_FILTRO, json=pagina([]))

    conversaciones = cliente().listar_conversaciones(DESDE, HASTA)

    assert [c["id"] for c in conversaciones] == [1, 2]


@responses.activate
def test_descarta_conversaciones_sin_fecha_de_creacion():
    responses.post(URL_FILTRO, json={"payload": [{"id": 1}, {"id": 2, "created_at": EN_RANGO}]})
    responses.post(URL_FILTRO, json=pagina([]))

    conversaciones = cliente().listar_conversaciones(DESDE, HASTA)

    assert [c["id"] for c in conversaciones] == [2]


URL_INBOXES = "https://chat.ejemplo.com/api/v1/accounts/7/inboxes"


@responses.activate
def test_listar_inboxes_devuelve_id_a_nombre():
    responses.get(
        URL_INBOXES,
        json={
            "payload": [
                {"id": 14, "name": "Gruas Asistencia 24", "channel_type": "Channel::Whatsapp"},
                {"id": 15, "name": "Gruas Asistencia", "channel_type": "Channel::Whatsapp"},
            ]
        },
    )

    assert cliente().listar_inboxes() == {14: "Gruas Asistencia 24", 15: "Gruas Asistencia"}


@responses.activate
def test_listar_inboxes_sin_inboxes():
    responses.get(URL_INBOXES, json={"payload": []})
    assert cliente().listar_inboxes() == {}
