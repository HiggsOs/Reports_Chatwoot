from decimal import Decimal

import pytest
import responses
from responses import matchers

import panel.transcripcion.estrategias.openai as modulo_openai
from panel.transcripcion import registro
from panel.transcripcion.base import (
    AudioPreparado,
    OpcionesTranscripcion,
    Transcripcion,
    TranscripcionError,
    TranscripcionNoDisponible,
)
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


@pytest.fixture(autouse=True)
def sin_esperas(monkeypatch):
    esperas = []
    monkeypatch.setattr(modulo_openai.time, "sleep", esperas.append)
    return esperas


def openai(**extra):
    return EstrategiaOpenAI(clave="sk-prueba", **extra)


# --- Contrato: corre contra cada estrategia ---------------------------------


@pytest.fixture(params=["falsa", "openai"])
def estrategia(request):
    if request.param == "falsa":
        yield EstrategiaFalsa()
        return
    with responses.RequestsMock() as simulado:
        simulado.post(URL, json=DIARIZADA)
        yield openai()


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
