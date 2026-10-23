from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
import responses

import cloudtalk
from cloudtalk import ClienteCloudTalk, CloudTalkAuthError, CloudTalkError, fue_grabada

BOGOTA = ZoneInfo("America/Bogota")
DESDE = datetime(2026, 9, 1, 0, 0, tzinfo=BOGOTA)
HASTA = datetime(2026, 9, 30, 23, 59, 59, tzinfo=BOGOTA)

URL_LLAMADAS = "https://my.cloudtalk.io/api/calls/index.json"
URL_TRANSCRIPCION = "https://api.cloudtalk.io/v1/ai/calls/27/transcription"


@pytest.fixture(autouse=True)
def esperas(monkeypatch):
    registro = []
    monkeypatch.setattr(cloudtalk.time, "sleep", registro.append)
    return registro


def cliente():
    return ClienteCloudTalk("id-clave", "secreto")


def llamada(identificador, inicio="2026-09-10T15:00:00.000Z"):
    return {"Cdr": {"id": str(identificador), "started_at": inicio}}


def pagina_llamadas(lote, pagina=1, paginas=1):
    return {
        "responseData": {
            "itemsCount": len(lote),
            "pageCount": paginas,
            "pageNumber": pagina,
            "limit": 1000,
            "data": lote,
        }
    }


@responses.activate
def test_envia_basic_auth_y_pide_solo_las_contestadas():
    responses.get(URL_LLAMADAS, json=pagina_llamadas([]))

    cliente().listar_llamadas(DESDE, HASTA)

    peticion = responses.calls[0].request
    assert peticion.headers["Authorization"].startswith("Basic ")
    assert "status=answered" in peticion.url
    assert "limit=1000" in peticion.url
    # Un día de margen por cada lado, en UTC.
    assert "date_from=2026-08-31+05%3A00%3A00" in peticion.url
    assert "date_to=2026-10-02+04%3A59%3A59" in peticion.url


@responses.activate
def test_recorta_al_rango_exacto_con_started_at():
    responses.get(
        URL_LLAMADAS,
        json=pagina_llamadas(
            [
                llamada(1, "2026-09-01T04:59:59.000Z"),  # 31 de agosto en Bogotá
                llamada(2, "2026-09-01T05:00:00.000Z"),
                llamada(3, "2026-10-01T05:00:00.000Z"),  # 1 de octubre en Bogotá
                llamada(4, None),
            ]
        ),
    )

    llamadas = cliente().listar_llamadas(DESDE, HASTA)

    assert [ll["Cdr"]["id"] for ll in llamadas] == ["2"]


@responses.activate
def test_pagina_hasta_page_count():
    responses.get(URL_LLAMADAS, json=pagina_llamadas([llamada(1)], 1, 2))
    responses.get(URL_LLAMADAS, json=pagina_llamadas([llamada(2)], 2, 2))

    assert len(cliente().listar_llamadas(DESDE, HASTA)) == 2
    assert len(responses.calls) == 2
    assert "page=2" in responses.calls[1].request.url


@responses.activate
def test_credenciales_rechazadas():
    responses.get(URL_LLAMADAS, status=401)

    with pytest.raises(CloudTalkAuthError):
        cliente().listar_llamadas(DESDE, HASTA)


@responses.activate
def test_reintenta_ante_limite_de_peticiones():
    responses.get(URL_LLAMADAS, status=429, headers={"Retry-After": "7"})
    responses.get(URL_LLAMADAS, json=pagina_llamadas([llamada(1)]))
    avisos = []

    cliente_ct = ClienteCloudTalk("id", "secreto", al_esperar=avisos.append)

    assert len(cliente_ct.listar_llamadas(DESDE, HASTA)) == 1
    assert avisos == [7.0]


@responses.activate
def test_sin_retry_after_espera_la_ventana_completa(esperas):
    responses.get(URL_TRANSCRIPCION, status=429)
    responses.get(URL_TRANSCRIPCION, status=404)

    assert cliente().obtener_transcripcion("27") is None
    assert 60.0 in esperas


@responses.activate
def test_aguanta_muchos_limites_seguidos_antes_de_rendirse():
    for _ in range(cloudtalk.INTENTOS_MAXIMOS_LIMITE - 1):
        responses.get(URL_TRANSCRIPCION, status=429)
    responses.get(URL_TRANSCRIPCION, status=404)

    assert cliente().obtener_transcripcion("27") is None


@responses.activate
def test_se_rinde_si_el_limite_no_cede():
    responses.get(URL_TRANSCRIPCION, status=429)

    with pytest.raises(CloudTalkError, match="429"):
        cliente().obtener_transcripcion("27")
    assert len(responses.calls) == cloudtalk.INTENTOS_MAXIMOS_LIMITE


@responses.activate
def test_un_429_alarga_el_intervalo_entre_peticiones():
    responses.get(URL_TRANSCRIPCION, status=429, headers={"Retry-After": "0"})
    responses.get(URL_TRANSCRIPCION, status=404)

    cliente_ct = cliente()
    cliente_ct.obtener_transcripcion("27")

    assert cliente_ct._intervalo == pytest.approx(1.5)


@responses.activate
def test_errores_del_servidor_tienen_su_propio_tope():
    responses.get(URL_TRANSCRIPCION, status=503)

    with pytest.raises(CloudTalkError, match="503"):
        cliente().obtener_transcripcion("27")
    assert len(responses.calls) == cloudtalk.INTENTOS_MAXIMOS


@responses.activate
def test_error_del_cliente_no_se_reintenta():
    responses.get(URL_LLAMADAS, status=400, body="mal")

    with pytest.raises(CloudTalkError):
        cliente().listar_llamadas(DESDE, HASTA)
    assert len(responses.calls) == 1


@responses.activate
def test_transcripcion_inexistente_da_none():
    responses.get(URL_TRANSCRIPCION, status=404)

    assert cliente().obtener_transcripcion("27") is None


@responses.activate
def test_junta_todas_las_paginas_de_segmentos():
    callers = [{"id": 1000, "type": "agent", "localIdentifier": "caller2"}]
    responses.get(
        URL_TRANSCRIPCION,
        json={
            "data": {
                "callId": 27,
                "segments": [{"start": 1, "caller": "caller2", "text": "Hola"}],
                "callers": callers,
                "language": "es",
            },
            "pagination": {"limit": 1, "offset": 0, "total": 2},
        },
    )
    responses.get(
        URL_TRANSCRIPCION,
        json={
            "data": {
                "callId": 27,
                "segments": [{"start": 2, "caller": "caller2", "text": "Chao"}],
                "callers": callers,
                "language": "es",
            },
            "pagination": {"limit": 1, "offset": 1, "total": 2},
        },
    )

    transcripcion = cliente().obtener_transcripcion("27")

    assert [s["text"] for s in transcripcion["segments"]] == ["Hola", "Chao"]
    assert transcripcion["callers"] == callers
    assert "offset=1" in responses.calls[1].request.url


def test_grabada_acepta_booleano_y_texto():
    assert fue_grabada({"Cdr": {"recorded": True}})
    assert fue_grabada({"Cdr": {"recorded": "1"}})
    assert not fue_grabada({"Cdr": {"recorded": False}})
    assert not fue_grabada({"Cdr": {"recorded": "0"}})
    assert not fue_grabada({})


@responses.activate
def test_espacia_las_peticiones_para_no_pasar_el_limite(esperas, monkeypatch):
    reloj = iter([100.0, 100.2, 100.2])
    monkeypatch.setattr(cloudtalk.time, "monotonic", lambda: next(reloj))
    responses.get(URL_TRANSCRIPCION, status=404)

    cliente_ct = cliente()
    cliente_ct.obtener_transcripcion("27")
    cliente_ct.obtener_transcripcion("27")

    # La segunda petición sale 0,2 s después de la primera: espera el resto.
    assert esperas == [pytest.approx(0.8)]
