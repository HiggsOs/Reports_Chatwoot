"""Lo que se configura desde la pantalla Transcripción: modelos con precio,
tope de gasto, encolado automático y precio real cobrado."""

import json
from datetime import date, timedelta
from decimal import Decimal

import pytest

from config import cargar_config
from panel.composicion import cadena_transcripcion, estrategias_transcripcion
from panel.db.base import unidad_de_trabajo
from panel.db.modelos import (
    TRABAJO_ERROR,
    Llamada,
    TrabajoTranscripcion,
    TranscripcionGuardada,
)
from panel.sync.tareas import EncolarLlamadasNuevas, ProcesarTranscripciones
from panel.transcripcion import consultas, registro
from panel.transcripcion.estrategias.openai import EstrategiaOpenAI
from tests.test_audio_servicio import AHORA, guardar_llamada
from tests.test_config import ENTORNO_VALIDO

MODELOS = [
    {"proveedor": "openai", "modelo": "gpt-4o-transcribe-diarize", "precio_minuto": "0.006"},
    {"proveedor": "openai", "modelo": "whisper-1", "precio_minuto": "0.006", "redondeo": "minuto"},
    {"proveedor": "openai", "modelo": "gpt-4o-mini-transcribe", "activo": False},
]


def configuracion(**extra):
    return cargar_config(
        {
            **ENTORNO_VALIDO,
            "OPENAI_API_KEY": "sk-prueba",
            "TRANSCRIPCION_MODELOS": json.dumps(MODELOS),
            **extra,
        }
    )


def test_una_estrategia_por_modelo_activo_con_su_precio():
    estrategias = estrategias_transcripcion(configuracion())

    assert list(estrategias) == ["openai:gpt-4o-transcribe-diarize", "openai:whisper-1"]
    whisper = estrategias["openai:whisper-1"]
    assert whisper.modelo == "whisper-1"
    assert whisper.capacidades.marcas_de_tiempo and not whisper.capacidades.diarizacion
    # 61 segundos redondeados a 2 minutos.
    assert whisper.costo_estimado(61) == Decimal("0.0120")
    assert estrategias["openai:gpt-4o-transcribe-diarize"].costo_estimado(60) == Decimal("0.0060")


def test_sin_clave_no_hay_estrategias():
    cfg = cargar_config({**ENTORNO_VALIDO, "TRANSCRIPCION_MODELOS": json.dumps(MODELOS)})
    assert estrategias_transcripcion(cfg) == {}


def test_la_cadena_acepta_el_proveedor_a_secas_o_el_modelo():
    cfg = configuracion(
        TRANSCRIPCION_PROVEEDOR="openai:whisper-1", TRANSCRIPCION_RESPALDO="openai"
    )
    assert cadena_transcripcion(cfg, estrategias_transcripcion(cfg)) == [
        "openai:whisper-1",
        "openai:gpt-4o-transcribe-diarize",
    ]
    # Un modelo apagado no entra en la cadena.
    cfg = configuracion(TRANSCRIPCION_PROVEEDOR="openai:gpt-4o-mini-transcribe")
    assert cadena_transcripcion(cfg, estrategias_transcripcion(cfg)) == []


def test_sin_modelos_cargados_se_usa_el_entorno_como_antes():
    cfg = cargar_config({**ENTORNO_VALIDO, "OPENAI_API_KEY": "sk-prueba"})
    estrategias = estrategias_transcripcion(cfg)
    assert "openai" in estrategias
    assert cadena_transcripcion(cfg, estrategias) == ["openai"]


def test_registro_titulos_y_modelos():
    assert registro.titulo("openai:whisper-1") == "OpenAI · whisper-1"
    assert registro.titulo("openai") == "OpenAI"
    assert registro.variable_clave("openai") == "OPENAI_API_KEY"
    assert "whisper-1" in registro.modelos_conocidos("openai")
    assert registro.resolver("openai", {"openai:a": 1, "openai:b": 2}) == "openai:a"
    assert registro.resolver("otro", {"openai:a": 1}) is None


def test_openai_por_segundo_no_redondea():
    estrategia = EstrategiaOpenAI(clave="x", precio_minuto=Decimal("0.006"))
    assert estrategia.costo_estimado(30) == Decimal("0.0030")


def _guardar_transcripcion(fabrica, llamada_id, costo, creada, modelo="whisper-1", segundos=60.0):
    with unidad_de_trabajo(fabrica) as sesion:
        sesion.add(
            TranscripcionGuardada(
                llamada_id=llamada_id,
                proveedor="openai",
                modelo=modelo,
                idioma="es",
                canales_audio="mono",
                segmentos=[],
                texto="",
                duracion_audio=segundos,
                costo_estimado=costo,
                creado_en=creada,
            )
        )


def test_gasto_del_mes_en_hora_de_espana(fabrica):
    llamada_id = guardar_llamada(fabrica)
    _guardar_transcripcion(fabrica, llamada_id, Decimal("1.5"), AHORA)
    _guardar_transcripcion(fabrica, llamada_id, Decimal("2"), AHORA - timedelta(days=40))
    _guardar_transcripcion(fabrica, llamada_id, None, AHORA)
    with unidad_de_trabajo(fabrica) as sesion:
        assert consultas.gasto_del_mes(sesion, AHORA) == Decimal("1.5")


class ColaFalsa:
    def __init__(self):
        self.procesadas = 0
        self.encoladas: list[int] = []

    def procesar_cola(self, limite):
        self.procesadas += 1
        return consultas_resumen()

    def encolar(self, ids):
        self.encoladas += ids
        return len(ids)


def consultas_resumen():
    from panel.transcripcion.servicio import ResumenCola

    return ResumenCola(hechos=1)


def test_el_tope_mensual_pausa_la_cola(fabrica):
    llamada_id = guardar_llamada(fabrica)
    _guardar_transcripcion(fabrica, llamada_id, Decimal("10"), AHORA)
    cola = ColaFalsa()

    pausada = ProcesarTranscripciones(fabrica, cola, 5, Decimal("10"), ahora=lambda: AHORA).ejecutar()
    assert pausada.resumen["pausada_por_tope"] is True
    assert cola.procesadas == 0

    sigue = ProcesarTranscripciones(fabrica, cola, 5, Decimal("20"), ahora=lambda: AHORA).ejecutar()
    assert sigue.resumen["hechos"] == 1 and cola.procesadas == 1


def test_encola_solo_las_llamadas_nuevas_y_largas(fabrica):
    nueva = guardar_llamada(fabrica, "nueva", dias_atras=1)
    vieja = guardar_llamada(fabrica, "vieja", dias_atras=5)
    sin_grabar = guardar_llamada(fabrica, "sin-grabar", dias_atras=1, grabada=False)
    fallida = guardar_llamada(fabrica, "fallida", dias_atras=1)
    corta = guardar_llamada(fabrica, "corta", dias_atras=1)
    with unidad_de_trabajo(fabrica) as sesion:
        sesion.get(Llamada, corta).duracion_s = 10
        sesion.add(TrabajoTranscripcion(llamada_id=fallida, estado=TRABAJO_ERROR, error="x"))
    cola = ColaFalsa()

    resultado = EncolarLlamadasNuevas(fabrica, cola, 30, ahora=lambda: AHORA).ejecutar()

    assert cola.encoladas == [nueva]
    assert resultado.resumen == {"encoladas": 1}
    assert vieja not in cola.encoladas and sin_grabar not in cola.encoladas


def test_precio_real_compara_lo_cobrado_con_lo_configurado(fabrica):
    llamada_id = guardar_llamada(fabrica)
    _guardar_transcripcion(fabrica, llamada_id, Decimal("0.6"), AHORA, segundos=6000)
    mes = date(2026, 11, 1)
    with unidad_de_trabajo(fabrica) as sesion:
        consultas.guardar_cobro(sesion, mes, "openai", "whisper-1", Decimal("110"), Decimal("0.726"))
        consultas.guardar_cobro(sesion, date(2026, 11, 15), "openai", "nova", Decimal("10"), Decimal("1"))
        # Corregir un cobro lo reemplaza.
        consultas.guardar_cobro(sesion, mes, "openai", "nova", Decimal("10"), Decimal("0.05"))
    with unidad_de_trabajo(fabrica) as sesion:
        filas = consultas.precio_real(
            sesion, mes, {("openai", "whisper-1"): Decimal("0.006"), ("openai", "nova"): Decimal("0.005")}
        )

    por_modelo = {f.modelo: f for f in filas}
    whisper = por_modelo["whisper-1"]
    assert whisper.minutos_panel == 100.0 and whisper.usd_estimado == Decimal("0.6")
    assert whisper.precio_real == Decimal("0.0066")
    assert whisper.diferencia == pytest.approx(Decimal("0.1"))
    assert whisper.desviado
    nova = por_modelo["nova"]
    assert nova.minutos_panel == 0 and nova.usd_cobrados == Decimal("0.05")
    assert not nova.desviado
