from decimal import Decimal

import pytest
import responses
from responses import matchers

import panel.transcripcion.estrategias.deepgram as modulo_deepgram
import panel.transcripcion.estrategias.openai as modulo_openai
from panel.transcripcion import registro
from panel.transcripcion.base import (
    AudioPreparado,
    OpcionesTranscripcion,
    Transcripcion,
    TranscripcionError,
    TranscripcionNoDisponible,
)
from panel.transcripcion.estrategias.deepgram import EstrategiaDeepgram
from panel.transcripcion.estrategias.falsa import EstrategiaFalsa
from panel.transcripcion.estrategias.openai import EstrategiaOpenAI

URL = "https://api.openai.com/v1/audio/transcriptions"
AUDIO = AudioPreparado(
    contenido=b"ID3 audio", nombre_archivo="27.mp3", tipo_mime="audio/mpeg", duracion_s=90.0
)
OPCIONES = OpcionesTranscripcion(idioma="es", vocabulario=("grúa", "Mapfre"))

DIARIZADA = {
    "task": "transcribe",
    "duration": 90.0,
    "text": "Buenos días. Necesito una grúa.",
    "segments": [
        {"id": "s1", "type": "transcript.text.segment", "speaker": "A", "start": 0.4,
         "end": 2.1, "text": " Buenos días."},
        {"id": "s2", "type": "transcript.text.segment", "speaker": "B", "start": 2.5,
         "end": 4.0, "text": "Necesito una grúa. "},
        {"id": "s3", "type": "transcript.text.segment", "speaker": "B", "start": 4.0,
         "end": 4.2, "text": "  "},
    ],
}


# Respuesta de Deepgram con `utterances` y `diarize`.
URL_DEEPGRAM = "https://api.deepgram.com/v1/listen"
DEEPGRAM = {
    "metadata": {"request_id": "r1", "duration": 90.0, "channels": 1},
    "results": {
        "channels": [{"alternatives": [{"transcript": "Buenos días. Necesito una grúa."}]}],
        "utterances": [
            {"start": 0.4, "end": 2.1, "channel": 0, "speaker": 0, "transcript": " Buenos días."},
            {"start": 2.5, "end": 4.0, "channel": 0, "speaker": 1, "transcript": "Necesito una grúa. "},
            {"start": 4.0, "end": 4.2, "channel": 0, "speaker": 1, "transcript": "  "},
        ],
    },
}


@pytest.fixture(autouse=True)
def sin_esperas(monkeypatch):
    esperas = []
    monkeypatch.setattr(modulo_openai.time, "sleep", esperas.append)
    monkeypatch.setattr(modulo_deepgram.time, "sleep", esperas.append)
    return esperas


def openai(**extra):
    return EstrategiaOpenAI(clave="sk-prueba", **extra)


# --- Contrato: corre contra cada estrategia ---------------------------------


@pytest.fixture(params=["falsa", "openai", "deepgram"])
def estrategia(request):
    if request.param == "falsa":
        yield EstrategiaFalsa()
        return
    with responses.RequestsMock() as simulado:
        if request.param == "openai":
            simulado.post(URL, json=DIARIZADA)
            yield openai()
        else:
            simulado.post(URL_DEEPGRAM, json=DEEPGRAM)
            yield deepgram()


def test_contrato_de_la_estrategia(estrategia):
    assert estrategia.nombre in registro.nombres()
    assert estrategia.modelo
    resultado = estrategia.transcribir(AUDIO, OPCIONES)
    assert isinstance(resultado, Transcripcion)
    assert resultado.proveedor == estrategia.nombre
    assert resultado.segmentos and all(s.texto.strip() for s in resultado.segmentos)
    if estrategia.capacidades.marcas_de_tiempo:
        assert all(s.inicio is not None for s in resultado.segmentos)
    if estrategia.capacidades.diarizacion:
        assert all(s.etiqueta for s in resultado.segmentos)


def test_contrato_con_un_canal_de_hablante_conocido(estrategia):
    canal = AUDIO.model_copy(update={"hablante": "agente"})
    resultado = estrategia.transcribir(canal, OPCIONES)
    assert {s.hablante for s in resultado.segmentos} == {"agente"}
    assert all(s.etiqueta is None for s in resultado.segmentos)


# --- OpenAI -----------------------------------------------------------------


@responses.activate
def test_openai_diarizado_pide_lo_que_corresponde_y_traduce():
    responses.post(URL, json=DIARIZADA)
    resultado = openai(precio_minuto=Decimal("0.006")).transcribir(AUDIO, OPCIONES)

    pedido = responses.calls[0].request
    assert pedido.headers["Authorization"] == "Bearer sk-prueba"
    cuerpo = pedido.body
    for esperado in (b"gpt-4o-transcribe-diarize", b"diarized_json", b"chunking_strategy", b"27.mp3"):
        assert esperado in cuerpo
    # El modelo diarizado no acepta prompt.
    assert b'name="prompt"' not in cuerpo

    assert [(s.etiqueta, s.inicio, s.texto) for s in resultado.segmentos] == [
        ("A", 0.4, "Buenos días."),
        ("B", 2.5, "Necesito una grúa."),
    ]
    assert resultado.duracion_audio == 90.0
    assert resultado.costo_estimado == Decimal("0.0090")
    assert openai().capacidades.diarizacion


@responses.activate
def test_openai_whisper_da_tiempos_sin_hablantes_y_usa_prompt():
    responses.post(
        URL,
        json={"duration": 5.0, "language": "spanish", "text": "Hola.",
              "segments": [{"start": 0.0, "end": 1.0, "text": "Hola."}]},
    )
    estrategia = openai(modelo="whisper-1")
    resultado = estrategia.transcribir(AUDIO, OPCIONES)
    assert b"verbose_json" in responses.calls[0].request.body
    assert "Vocabulario: grúa, Mapfre".encode() in responses.calls[0].request.body
    assert (resultado.segmentos[0].inicio, resultado.segmentos[0].etiqueta) == (0.0, None)
    assert estrategia.capacidades.marcas_de_tiempo and not estrategia.capacidades.diarizacion


@responses.activate
def test_openai_modelo_desconocido_pide_json_y_da_solo_texto():
    responses.post(
        URL,
        json={"text": " Todo el texto. ", "usage": {"type": "duration", "seconds": 42}},
        match=[matchers.header_matcher({"Authorization": "Bearer sk-prueba"})],
    )
    estrategia = openai(modelo="gpt-transcribe")
    resultado = estrategia.transcribir(AUDIO, OPCIONES)
    cuerpo = responses.calls[0].request.body
    assert b'name="response_format"\r\n\r\njson' in cuerpo
    assert cuerpo.count(b'name="keywords[]"') == 2
    assert [(s.texto, s.inicio) for s in resultado.segmentos] == [("Todo el texto.", None)]
    assert resultado.duracion_audio == 42
    assert not estrategia.capacidades.marcas_de_tiempo


@responses.activate
def test_openai_formato_forzado_para_un_modelo_nuevo():
    responses.post(URL, json=DIARIZADA)
    estrategia = openai(modelo="gpt-transcribe", formato="diarized_json")
    assert estrategia.capacidades.diarizacion
    assert estrategia.transcribir(AUDIO, OPCIONES).segmentos[0].etiqueta == "A"


@responses.activate
def test_openai_reintenta_429_y_5xx(sin_esperas):
    responses.post(URL, status=429, headers={"Retry-After": "7"})
    responses.post(URL, status=503)
    responses.post(URL, json=DIARIZADA)
    assert openai().transcribir(AUDIO, OPCIONES).segmentos
    assert sin_esperas[0] == 7.0 and len(responses.calls) == 3


@responses.activate
def test_openai_se_rinde_tras_tres_intentos():
    for _ in range(3):
        responses.post(URL, status=500, body="caído")
    with pytest.raises(TranscripcionError, match="3 intentos"):
        openai().transcribir(AUDIO, OPCIONES)


@responses.activate
@pytest.mark.parametrize(("estado", "texto"), [(401, "clave"), (400, "400")])
def test_openai_errores_que_no_se_reintentan(estado, texto):
    responses.post(URL, status=estado, body="mal")
    with pytest.raises(TranscripcionError, match=texto):
        openai().transcribir(AUDIO, OPCIONES)
    assert len(responses.calls) == 1


def test_openai_rechaza_un_audio_de_mas_de_25_mb():
    grande = AUDIO.model_copy(update={"contenido": b"x" * (25 * 1024 * 1024 + 1)})
    with pytest.raises(TranscripcionError, match="25 MB"):
        openai().transcribir(grande, OPCIONES)


def test_openai_sin_precio_no_inventa_costo():
    assert openai().costo_estimado(60) is None


def test_openai_desde_la_configuracion():
    with pytest.raises(TranscripcionNoDisponible, match="OPENAI_API_KEY"):
        registro.crear("openai", {})
    estrategia = registro.crear(
        "openai",
        {"OPENAI_API_KEY": "sk", "OPENAI_MODELO_TRANSCRIPCION": "whisper-1",
         "OPENAI_PRECIO_MINUTO": "0,006"},
    )
    assert estrategia.modelo == "whisper-1"
    assert estrategia.costo_estimado(120) == Decimal("0.0120")
    with pytest.raises(TranscripcionNoDisponible):
        registro.crear("openai", {"OPENAI_API_KEY": "sk", "OPENAI_PRECIO_MINUTO": "caro"})
    with pytest.raises(TranscripcionNoDisponible):
        registro.crear("openai", {"OPENAI_API_KEY": "sk", "OPENAI_FORMATO_RESPUESTA": "srt"})


def test_registro():
    assert set(registro.disponibles({})) == {"falsa"}
    assert set(registro.disponibles({"OPENAI_API_KEY": "sk"})) == {"falsa", "openai"}
    assert set(registro.disponibles({"DEEPGRAM_API_KEY": "dg"})) == {"falsa", "deepgram"}
    assert registro.variable_clave("deepgram") == "DEEPGRAM_API_KEY"
    assert registro.titulo("openai") == "OpenAI"
    with pytest.raises(TranscripcionNoDisponible):
        registro.crear("no_existe", {})
    with pytest.raises(ValueError):
        registro.registrar(EstrategiaFalsa)


@responses.activate
def test_openai_probar_la_clave():
    from panel.transcripcion import registro

    responses.get(
        "https://api.openai.com/v1/models",
        json={"data": [{"id": "whisper-1"}, {"id": "gpt-4o"}]},
    )
    mensaje = registro.probar_clave("openai", {"OPENAI_API_KEY": "sk-x"})
    assert "whisper-1" in mensaje and "gpt-4o," not in mensaje

    responses.replace(responses.GET, "https://api.openai.com/v1/models", status=401)
    with pytest.raises(TranscripcionError):
        registro.probar_clave("openai", {"OPENAI_API_KEY": "sk-x"})


# --- Deepgram ---------------------------------------------------------------


def deepgram(**extra):
    return EstrategiaDeepgram(clave="dg-prueba", **extra)


def _parametros(llamada) -> dict[str, list[str]]:
    from urllib.parse import parse_qs, urlparse

    return parse_qs(urlparse(llamada.request.url).query)


@responses.activate
def test_deepgram_pide_lo_que_corresponde_y_traduce():
    responses.post(URL_DEEPGRAM, json=DEEPGRAM)
    resultado = deepgram(precio_minuto=Decimal("0.0043")).transcribir(AUDIO, OPCIONES)

    llamada = responses.calls[0]
    assert llamada.request.headers["Authorization"] == "Token dg-prueba"
    assert llamada.request.headers["Content-Type"] == "audio/mpeg"
    assert llamada.request.body == b"ID3 audio"
    parametros = _parametros(llamada)
    assert parametros["model"] == ["nova-3"] and parametros["language"] == ["es"]
    assert parametros["diarize"] == ["true"] and parametros["utterances"] == ["true"]
    assert parametros["keyterm"] == ["grúa", "Mapfre"] and "keywords" not in parametros

    assert [(s.etiqueta, s.inicio, s.fin, s.texto) for s in resultado.segmentos] == [
        ("A", 0.4, 2.1, "Buenos días."),
        ("B", 2.5, 4.0, "Necesito una grúa."),
    ]
    assert resultado.proveedor == "deepgram" and resultado.modelo == "nova-3"
    assert resultado.duracion_audio == 90.0
    assert resultado.costo_estimado == Decimal("0.0064")  # 1,5 min × 0,0043


@responses.activate
def test_deepgram_un_canal_no_separa_hablantes_y_nova2_usa_keywords():
    responses.post(URL_DEEPGRAM, json=DEEPGRAM)
    canal = AUDIO.model_copy(update={"hablante": "cliente"})
    resultado = deepgram(modelo="nova-2").transcribir(canal, OPCIONES)
    parametros = _parametros(responses.calls[0])
    assert parametros["diarize"] == ["false"]
    assert parametros["keywords"] == ["grúa", "Mapfre"] and "keyterm" not in parametros
    assert {(s.hablante, s.etiqueta) for s in resultado.segmentos} == {("cliente", None)}


@responses.activate
def test_deepgram_sin_frases_usa_el_texto_entero():
    responses.post(URL_DEEPGRAM, json={"metadata": {}, "results": {
        "channels": [{"alternatives": [{"transcript": " Todo junto. "}]}]}})
    resultado = deepgram().transcribir(AUDIO, OPCIONES)
    assert [(s.texto, s.inicio) for s in resultado.segmentos] == [("Todo junto.", None)]
    assert resultado.duracion_audio == 90.0  # la del audio, si Deepgram no la da


@responses.activate
def test_deepgram_si_rechaza_el_vocabulario_repite_sin_el():
    responses.post(URL_DEEPGRAM, status=400, body="keyterm not supported")
    responses.post(URL_DEEPGRAM, json=DEEPGRAM)
    assert deepgram().transcribir(AUDIO, OPCIONES).segmentos
    assert "keyterm" in _parametros(responses.calls[0]) and "keyterm" not in _parametros(responses.calls[1])


@responses.activate
def test_deepgram_reintenta_429_y_5xx(sin_esperas):
    responses.post(URL_DEEPGRAM, status=429, headers={"Retry-After": "5"})
    responses.post(URL_DEEPGRAM, status=502)
    responses.post(URL_DEEPGRAM, json=DEEPGRAM)
    assert deepgram().transcribir(AUDIO, OPCIONES).segmentos
    assert sin_esperas[0] == 5.0 and len(responses.calls) == 3


@responses.activate
@pytest.mark.parametrize(("estado", "texto"), [(401, "clave"), (402, "saldo"), (400, "400")])
def test_deepgram_errores_que_no_se_reintentan(estado, texto):
    responses.post(URL_DEEPGRAM, status=estado, body="mal")
    sin_vocabulario = OpcionesTranscripcion(idioma="es")
    with pytest.raises(TranscripcionError, match=texto):
        deepgram().transcribir(AUDIO, sin_vocabulario)
    assert len(responses.calls) == 1


def test_deepgram_desde_la_configuracion():
    with pytest.raises(TranscripcionNoDisponible, match="DEEPGRAM_API_KEY"):
        registro.crear("deepgram", {})
    estrategia = registro.crear_modelo("deepgram", {"DEEPGRAM_API_KEY": "dg"}, "nova-2", Decimal("0.0043"), "minuto")
    assert estrategia.modelo == "nova-2"
    assert estrategia.costo_estimado(61) == Decimal("0.0086")
    assert registro.crear("deepgram", {"DEEPGRAM_API_KEY": "dg"}).costo_estimado(60) is None
    with pytest.raises(TranscripcionNoDisponible):
        registro.crear("deepgram", {"DEEPGRAM_API_KEY": "dg", "DEEPGRAM_PRECIO_MINUTO": "caro"})


@responses.activate
def test_deepgram_probar_la_clave_muestra_el_saldo():
    responses.get("https://api.deepgram.com/v1/projects", json={"projects": [{"project_id": "p1", "name": "x"}]})
    responses.get("https://api.deepgram.com/v1/projects/p1/balances",
                  json={"balances": [{"balance_id": "b", "amount": 187.5, "units": "usd"}]})
    assert registro.probar_clave("deepgram", {"DEEPGRAM_API_KEY": "dg"}) == "Clave válida. Saldo de la cuenta: 187.50 USD."

    # Una clave sin permiso para ver el saldo sigue siendo válida.
    responses.replace(responses.GET, "https://api.deepgram.com/v1/projects/p1/balances", status=403)
    assert registro.probar_clave("deepgram", {"DEEPGRAM_API_KEY": "dg"}) == "Clave válida."

    responses.replace(responses.GET, "https://api.deepgram.com/v1/projects", status=401)
    with pytest.raises(TranscripcionError, match="rechazó"):
        registro.probar_clave("deepgram", {"DEEPGRAM_API_KEY": "dg"})


@responses.activate
def test_deepgram_lista_los_modelos_del_idioma():
    responses.get("https://api.deepgram.com/v1/models", json={"stt": [
        {"name": "nova-2", "canonical_name": "nova-2-phonecall", "languages": ["en", "en-US"], "batch": True},
        {"name": "nova-2", "canonical_name": "nova-2-general", "languages": ["es", "es-419", "en"], "batch": True},
        {"name": "nova-3", "canonical_name": "nova-3-general", "languages": ["multi", "en"], "batch": True},
        {"name": "nova-3", "canonical_name": "nova-3-general", "languages": ["es"], "batch": True},
        {"name": "flux", "canonical_name": "flux-general-es", "languages": ["es"], "batch": False},
        {"name": "base", "languages": ["es"]},
    ], "tts": [{"name": "aura"}]},
        match=[matchers.header_matcher({"Authorization": "Token dg"})])
    modelos = registro.listar_modelos("deepgram", {"DEEPGRAM_API_KEY": "dg"}, "es")
    # Ni el de solo inglés ni el que no sirve para audios grabados; sin repetidos.
    assert modelos == ["nova-3-general", "nova-2-general", "base"]
    # Cualquier modelo de Deepgram separa hablantes, aunque el panel no lo conozca.
    assert registro.capacidades("deepgram", "nova-2-general").diarizacion

    responses.replace(responses.GET, "https://api.deepgram.com/v1/models", status=401)
    with pytest.raises(TranscripcionError, match="rechazó"):
        registro.listar_modelos("deepgram", {"DEEPGRAM_API_KEY": "dg"}, "es")
    with pytest.raises(TranscripcionNoDisponible):
        registro.listar_modelos("deepgram", {}, "es")


@responses.activate
def test_openai_lista_solo_los_de_transcripcion():
    responses.get("https://api.openai.com/v1/models", json={"data": [
        {"id": "gpt-4o"}, {"id": "whisper-1"}, {"id": "gpt-transcribe"}, {"id": "gpt-4o-transcribe-diarize"},
    ]})
    modelos = registro.listar_modelos("openai", {"OPENAI_API_KEY": "sk"}, "es")
    assert modelos == ["gpt-4o-transcribe-diarize", "whisper-1", "gpt-transcribe"]
    assert registro.capacidades("openai", "gpt-transcribe") is None


@responses.activate
def test_deepgram_suma_lo_cobrado_por_modelo_desde_el_historial():
    from datetime import datetime, timezone

    base = "https://api.deepgram.com/v1"
    responses.get(f"{base}/projects", json={"projects": [{"project_id": "p1"}]})

    def pedido(ruta, usd, duracion):
        return {"request_id": ruta, "path": ruta, "response": {"code": 200, "details": {"usd": usd, "duration": duracion}}}

    pagina = [pedido("/v1/listen?model=nova-3&language=es", 0.0129, 180.0) for _ in range(2)]
    pagina += [pedido("/v1/listen?language=es&model=nova-2", 0.0043, 60.0),
               pedido("/v1/speak?model=aura", 0.03, 0),  # voz, no transcripción: no cuenta
               {"path": "/v1/listen?model=nova-3", "response": {"code": 200}}]  # sin costo: se salta
    responses.get(f"{base}/projects/p1/requests", json={"page": 0, "limit": 1000, "requests": pagina})

    desde = datetime(2026, 10, 31, 23, 0, tzinfo=timezone.utc)
    cobros = registro.cobros("deepgram", {"DEEPGRAM_API_KEY": "dg"}, desde, datetime(2026, 11, 30, 23, 0, tzinfo=timezone.utc))
    assert [(c.modelo, c.minutos, c.usd) for c in cobros] == [
        ("nova-2", Decimal("1.00"), Decimal("0.0043")),
        ("nova-3", Decimal("6.00"), Decimal("0.0258")),
    ]
    consulta = responses.calls[1].request.url
    assert "start=2026-10-31T23%3A00%3A00Z" in consulta and "status=succeeded" in consulta
    assert registro.informa_cobros("deepgram") and not registro.informa_cobros("openai")


@responses.activate
def test_deepgram_cobros_sin_costo_o_sin_permiso_dicen_por_que():
    from datetime import datetime, timezone

    base = "https://api.deepgram.com/v1"
    desde, hasta = datetime(2026, 11, 1, tzinfo=timezone.utc), datetime(2026, 12, 1, tzinfo=timezone.utc)
    responses.get(f"{base}/projects", json={"projects": [{"project_id": "p1"}]})
    responses.get(f"{base}/projects/p1/requests", json={"requests": [{"path": "/v1/listen?model=nova-3", "response": {}}]})
    with pytest.raises(TranscripcionError, match="no informó el costo"):
        registro.cobros("deepgram", {"DEEPGRAM_API_KEY": "dg"}, desde, hasta)

    responses.replace(responses.GET, f"{base}/projects/p1/requests", status=403)
    with pytest.raises(TranscripcionError, match="administrador"):
        registro.cobros("deepgram", {"DEEPGRAM_API_KEY": "dg"}, desde, hasta)
