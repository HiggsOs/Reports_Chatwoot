from datetime import datetime, timezone
from decimal import Decimal

import pytest
import responses
from responses import matchers

from config import cargar_config
from panel.composicion import fuentes_facturacion
from panel.transcripcion import facturacion
from panel.transcripcion.estrategias.openai import EstrategiaOpenAI
from panel.transcripcion.estrategias.openai_facturacion import FacturacionOpenAI
from panel.transcripcion.facturacion import CobroModelo, FacturacionError
from tests.test_config import ENTORNO_VALIDO

USO = "https://api.openai.com/v1/organization/usage/audio_transcriptions"
COSTOS = "https://api.openai.com/v1/organization/costs"
DESDE = datetime(2026, 10, 1, tzinfo=timezone.utc)
HASTA = datetime(2026, 10, 31, tzinfo=timezone.utc)


def balde(*resultados):
    return {"object": "bucket", "start_time": 0, "end_time": 86400, "results": list(resultados)}


def pagina(*baldes, siguiente=None):
    return {"object": "page", "data": list(baldes), "has_more": siguiente is not None,
            "next_page": siguiente}


def uso(modelo, segundos):
    return {"object": "organization.usage.audio_transcriptions.result", "model": modelo,
            "seconds": segundos, "num_model_requests": 1}


def costo(concepto, valor, moneda="usd"):
    return {"object": "organization.costs.result", "line_item": concepto,
            "amount": {"value": valor, "currency": moneda}}


@responses.activate
def test_suma_por_modelo_siguiendo_las_paginas():
    responses.get(
        USO,
        match=[matchers.query_param_matcher(
            {"start_time": str(int(DESDE.timestamp())), "end_time": str(int(HASTA.timestamp())),
             "bucket_width": "1d", "group_by": "model", "limit": "31"}
        )],
        json=pagina(balde(uso("gpt-4o-transcribe-diarize", 600), uso("whisper-1", 60)), siguiente="p2"),
    )
    responses.get(
        USO,
        match=[matchers.query_param_matcher({"page": "p2"}, strict_match=False)],
        json=pagina(balde(uso("gpt-4o-transcribe-diarize", 600), uso(None, 5))),
    )
    responses.get(
        COSTOS,
        json=pagina(
            balde(
                costo("gpt-4o-transcribe-diarize, input", 0.05),
                costo("gpt-4o-transcribe-diarize, output", "0.02"),
                costo("whisper-1", 0.006),
                costo("gpt-4o, input", 3.5),  # chat: no es transcripción
                costo(None, 1.0),
            ),
            balde(costo("gpt-4o-transcribe-diarize, input", 0.05)),
        ),
    )

    cobros = FacturacionOpenAI("sk-admin").cobrado(DESDE, HASTA)

    assert cobros == [
        CobroModelo(modelo="gpt-4o-transcribe-diarize", segundos=1200.0, costo=Decimal("0.12")),
        CobroModelo(modelo="whisper-1", segundos=60.0, costo=Decimal("0.006")),
    ]
    assert responses.calls[0].request.headers["Authorization"] == "Bearer sk-admin"


@responses.activate
def test_un_concepto_se_asigna_al_modelo_mas_largo_que_lo_nombra():
    responses.get(USO, json=pagina(balde(uso("gpt-4o-mini-transcribe-2025-12-15", 120))))
    responses.get(
        COSTOS,
        json=pagina(balde(
            costo("gpt-4o-mini-transcribe-2025-12-15", 0.006),
            costo("GPT-4o-transcribe", 0.01),
        )),
    )

    cobros = {c.modelo: c for c in FacturacionOpenAI("sk-admin").cobrado(DESDE, HASTA)}

    assert cobros["gpt-4o-mini-transcribe-2025-12-15"].costo == Decimal("0.006")
    # Cobrado sin uso informado todavía (las APIs no van a la par).
    assert cobros["gpt-4o-transcribe"].segundos == 0.0
    assert "gpt-4o-mini-transcribe" not in cobros


@responses.activate
def test_el_proyecto_filtra_las_dos_consultas():
    filtro = [matchers.query_param_matcher({"project_ids": "proj_1"}, strict_match=False)]
    responses.get(USO, match=filtro, json=pagina())
    responses.get(COSTOS, match=filtro, json=pagina())
    assert FacturacionOpenAI("sk-admin", proyecto="proj_1").cobrado(DESDE, HASTA) == []


@responses.activate
@pytest.mark.parametrize(
    ("estado", "texto"), [(401, "Admin key"), (403, "Admin key"), (500, "500")]
)
def test_errores_de_la_api(estado, texto):
    responses.get(USO, status=estado, body="no")
    with pytest.raises(FacturacionError, match=texto):
        FacturacionOpenAI("sk-normal").cobrado(DESDE, HASTA)


@responses.activate
def test_otra_moneda_no_se_mezcla_con_usd():
    responses.get(USO, json=pagina())
    responses.get(COSTOS, json=pagina(balde(costo("whisper-1", 1, "eur"))))
    with pytest.raises(FacturacionError, match="eur"):
        FacturacionOpenAI("sk-admin").cobrado(DESDE, HASTA)


def test_comparar_con_los_precios_configurados():
    estrategia = EstrategiaOpenAI(
        clave="sk", precio_minuto=Decimal("0.006"), precios={"whisper-1": Decimal("0.006")}
    )
    filas = facturacion.comparar(
        [
            CobroModelo(modelo="whisper-1", segundos=600, costo=Decimal("0.066")),
            CobroModelo(modelo="gpt-4o-transcribe-diarize", segundos=1200, costo=Decimal("0.12")),
            CobroModelo(modelo="gpt-transcribe", segundos=60, costo=Decimal("0.004")),
            CobroModelo(modelo="gpt-4o-transcribe", segundos=0, costo=Decimal("0.01")),
            CobroModelo(modelo="otro-modelo", segundos=60, costo=None),
        ],
        estrategia,
    )
    por_modelo = {f.modelo: f for f in filas}

    whisper = por_modelo["whisper-1"]
    assert (whisper.minutos, whisper.precio_real, whisper.diferencia) == (10.0, Decimal("0.0066"), Decimal("0.100"))
    assert whisper.desviado
    diarizado = por_modelo["gpt-4o-transcribe-diarize"]
    assert (diarizado.precio_real, diarizado.diferencia, diarizado.desviado) == (Decimal("0.0060"), Decimal("0.000"), False)
    sin_precio = por_modelo["gpt-transcribe"]
    assert (sin_precio.precio_real, sin_precio.precio_configurado, sin_precio.desviado) == (Decimal("0.0040"), None, False)
    assert por_modelo["gpt-4o-transcribe"].precio_real is None  # sin minutos no hay precio
    assert por_modelo["otro-modelo"].precio_configurado is None
    assert [f.modelo for f in filas] == sorted(por_modelo)


def test_configuracion():
    assert fuentes_facturacion(cargar_config(ENTORNO_VALIDO)) == {}
    fuentes = fuentes_facturacion(cargar_config({**ENTORNO_VALIDO, "OPENAI_ADMIN_KEY": "sk-admin"}))
    assert set(fuentes) == {"openai"}
    with pytest.raises(ValueError):
        facturacion.registrar(FacturacionOpenAI)
