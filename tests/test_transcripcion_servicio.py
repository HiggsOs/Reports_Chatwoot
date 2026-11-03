import shutil
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from config import ConfigError, cargar_config
from panel.audio.almacen import AlmacenLocal
from panel.audio.servicio import ServicioAudio
from panel.composicion import servicio_audio, servicio_transcripcion
from panel.db.base import unidad_de_trabajo
from panel.db.modelos import Llamada, TrabajoTranscripcion, TranscripcionGuardada
from panel.transcripcion import consultas
from panel.transcripcion.base import OpcionesTranscripcion
from panel.transcripcion.estrategias.falsa import EstrategiaFalsa
from panel.transcripcion.servicio import ServicioTranscripcion, borrar_transcripciones_vencidas
from tests.audio_de_prueba import wav
from tests.test_audio_servicio import AHORA, FuenteFalsa, guardar_llamada
from tests.test_config import ENTORNO_VALIDO

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="Falta ffmpeg.")


@pytest.fixture
def almacen(tmp_path):
    return AlmacenLocal(tmp_path / "audios")


def servicio(fabrica, almacen, audio=None, estrategias=None, cadena=None, ahora=AHORA):
    estrategias = estrategias or {"falsa": EstrategiaFalsa()}
    audio_servicio = ServicioAudio(
        fabrica, FuenteFalsa(audio or wav(segundos=6)), almacen, 90, ahora=lambda: ahora
    )
    return ServicioTranscripcion(
        fabrica,
        audio_servicio,
        estrategias,
        cadena or list(estrategias),
        OpcionesTranscripcion(idioma="es"),
        "izquierdo",
        ahora=lambda: ahora,
    )


def guardadas(fabrica, llamada_id):
    with unidad_de_trabajo(fabrica) as sesion:
        return [
            (t.proveedor, t.canales_audio, t.principal)
            for t in sesion.scalars(
                select(TranscripcionGuardada)
                .where(TranscripcionGuardada.llamada_id == llamada_id)
                .order_by(TranscripcionGuardada.id)
            )
        ]


def test_mono_queda_con_hablantes_por_resolver(fabrica, almacen):
    llamada_id = guardar_llamada(fabrica)
    transcripcion = servicio(fabrica, almacen)

    resultado = transcripcion.transcribir(llamada_id)

    assert resultado.error is None and resultado.proveedor == "falsa"
    vista = transcripcion.de_llamada(llamada_id)[0]
    assert vista.principal and vista.canales_audio == "mono"
    assert [(s.hablante, s.etiqueta) for s in vista.segmentos] == [
        ("desconocido", "A"),
        ("desconocido", "B"),
    ]
    assert vista.etiquetas_sin_resolver == ["A", "B"]
    with unidad_de_trabajo(fabrica) as sesion:
        llamada = sesion.get(Llamada, llamada_id)
        # Transcribir también deja el audio guardado.
        assert (llamada.transcripcion_estado, llamada.audio_estado) == ("transcrita", "guardado")


def test_decir_quien_es_quien(fabrica, almacen):
    llamada_id = guardar_llamada(fabrica)
    transcripcion = servicio(fabrica, almacen)
    resultado = transcripcion.transcribir(llamada_id)

    transcripcion.asignar_hablantes(resultado.transcripcion_id, {"A": "agente", "B": "cliente"})

    vista = transcripcion.de_llamada(llamada_id)[0]
    assert [s.hablante for s in vista.segmentos] == ["agente", "cliente"]
    assert vista.etiquetas_sin_resolver == []
    with pytest.raises(ValueError):
        transcripcion.asignar_hablantes(resultado.transcripcion_id, {"A": "jefe"})


def test_estereo_se_transcribe_por_canal_e_intercalado(fabrica, almacen):
    llamada_id = guardar_llamada(fabrica)
    falsa = EstrategiaFalsa()
    transcripcion = servicio(fabrica, almacen, wav(segundos=6, canales=2), {"falsa": falsa})

    transcripcion.transcribir(llamada_id)

    assert [a.hablante for a in falsa.recibidos] == ["agente", "cliente"]
    vista = transcripcion.de_llamada(llamada_id)[0]
    assert vista.canales_audio == "estereo"
    assert {s.hablante for s in vista.segmentos} == {"agente", "cliente"}
    assert vista.etiquetas_sin_resolver == []


def test_estereo_sin_marcas_de_tiempo_se_transcribe_mezclado(fabrica, almacen):
    llamada_id = guardar_llamada(fabrica)
    sin_marcas = EstrategiaFalsa(marcas_de_tiempo=False)
    transcripcion = servicio(fabrica, almacen, wav(canales=2), {"falsa": sin_marcas})

    transcripcion.transcribir(llamada_id)

    assert len(sin_marcas.recibidos) == 1 and sin_marcas.recibidos[0].hablante is None
    assert transcripcion.de_llamada(llamada_id)[0].canales_audio == "estereo"


def test_estereo_duplicado_se_transcribe_como_mono(fabrica, almacen):
    llamada_id = guardar_llamada(fabrica)
    falsa = EstrategiaFalsa()
    transcripcion = servicio(fabrica, almacen, wav(canales=2, duplicado=True), {"falsa": falsa})
    transcripcion.transcribir(llamada_id)
    assert len(falsa.recibidos) == 1
    assert guardadas(fabrica, llamada_id) == [("falsa", "estereo_duplicado", True)]


def test_si_la_principal_falla_prueba_el_respaldo(fabrica, almacen):
    llamada_id = guardar_llamada(fabrica)
    estrategias = {"rota": EstrategiaFalsa(error="sin saldo"), "buena": EstrategiaFalsa()}
    resultado = servicio(fabrica, almacen, estrategias=estrategias).transcribir(llamada_id)
    assert resultado.proveedor == "buena" and resultado.error is None


def test_si_fallan_todas_dice_por_que(fabrica, almacen):
    llamada_id = guardar_llamada(fabrica)
    estrategias = {"a": EstrategiaFalsa(error="sin saldo"), "b": EstrategiaFalsa(error="caído")}
    resultado = servicio(fabrica, almacen, estrategias=estrategias).transcribir(llamada_id)
    assert resultado.transcripcion_id is None
    assert "sin saldo" in resultado.error and "caído" in resultado.error
    with unidad_de_trabajo(fabrica) as sesion:
        assert sesion.get(Llamada, llamada_id).transcripcion_estado is None


def test_sin_audio_no_se_transcribe(fabrica, almacen):
    llamada_id = guardar_llamada(fabrica, grabada=False)
    resultado = servicio(fabrica, almacen).transcribir(llamada_id)
    assert resultado.error == "La llamada no se grabó."


def test_un_audio_grande_se_parte_y_se_corren_los_tiempos(fabrica, almacen):
    llamada_id = guardar_llamada(fabrica)
    chica = EstrategiaFalsa(tamano_max_bytes=12_000)
    transcripcion = servicio(fabrica, almacen, wav(segundos=12), {"falsa": chica})

    transcripcion.transcribir(llamada_id)

    assert len(chica.recibidos) > 1
    inicios = [s.inicio for s in transcripcion.de_llamada(llamada_id)[0].segmentos]
    assert inicios == sorted(inicios) and inicios[-1] > 6


def test_una_segunda_transcripcion_no_pisa_la_principal(fabrica, almacen):
    llamada_id = guardar_llamada(fabrica)
    transcripcion = servicio(fabrica, almacen)
    primera = transcripcion.transcribir(llamada_id)
    segunda = transcripcion.transcribir(llamada_id)
    assert [t[2] for t in guardadas(fabrica, llamada_id)] == [True, False]

    transcripcion.marcar_principal(segunda.transcripcion_id)
    vistas = transcripcion.de_llamada(llamada_id)
    assert vistas[0].id == segunda.transcripcion_id and vistas[0].principal
    assert [v.principal for v in vistas] == [True, False]
    assert primera.transcripcion_id == vistas[1].id


def test_la_cola_no_repite_pedidos_y_los_procesa(fabrica, almacen):
    una, otra = guardar_llamada(fabrica, "1"), guardar_llamada(fabrica, "2")
    transcripcion = servicio(fabrica, almacen)
    assert transcripcion.encolar([una, otra, una]) == 2
    assert transcripcion.encolar([una]) == 0

    assert transcripcion.procesar_cola(limite=1).hechos == 1
    assert transcripcion.procesar_cola(limite=5).hechos == 1
    assert transcripcion.procesar_cola(limite=5).model_dump() == {
        "hechos": 0, "reintentos": 0, "errores": 0, "pausada_por_tope": False
    }
    # Ya hecho: se puede volver a pedir.
    assert transcripcion.encolar([una]) == 1


def test_la_cola_reintenta_tres_veces_y_despues_queda_en_error(fabrica, almacen):
    llamada_id = guardar_llamada(fabrica)
    transcripcion = servicio(fabrica, almacen, estrategias={"rota": EstrategiaFalsa(error="caído")})
    transcripcion.encolar([llamada_id])

    resumenes = [transcripcion.procesar_cola(5).model_dump() for _ in range(3)]
    assert [r["reintentos"] for r in resumenes] == [1, 1, 0]
    assert resumenes[2]["errores"] == 1
    with unidad_de_trabajo(fabrica) as sesion:
        trabajo = sesion.scalar(select(TrabajoTranscripcion))
        assert (trabajo.estado, trabajo.intentos) == ("error", 3)
        assert "caído" in trabajo.error
        trabajo_id = trabajo.id

    transcripcion.reintentar(trabajo_id)
    with unidad_de_trabajo(fabrica) as sesion:
        assert sesion.get(TrabajoTranscripcion, trabajo_id).estado == "pendiente"


def test_un_pedido_colgado_vuelve_a_la_cola(fabrica, almacen):
    llamada_id = guardar_llamada(fabrica)
    servicio(fabrica, almacen).encolar([llamada_id])
    with unidad_de_trabajo(fabrica) as sesion:
        trabajo = sesion.scalar(select(TrabajoTranscripcion))
        trabajo.estado = "en_proceso"
    # Dos horas después, otro proceso lo retoma.
    despues = servicio(fabrica, almacen, ahora=datetime.now(timezone.utc) + timedelta(hours=2))
    assert despues.procesar_cola(5).hechos == 1


def test_costo_de_un_lote(fabrica, almacen):
    ids = [guardar_llamada(fabrica, str(i)) for i in range(3)]  # 60 s cada una
    transcripcion = servicio(fabrica, almacen)
    minutos, costo = transcripcion.costo_de_lote(ids)
    assert (minutos, costo) == (3.0, Decimal("0"))


def test_las_transcripciones_se_borran_a_los_tres_años(fabrica, almacen):
    reciente = guardar_llamada(fabrica, "1", dias_atras=1094)
    vieja = guardar_llamada(fabrica, "2", dias_atras=1096)
    # Se transcribieron cuando eran nuevas (las fechas del audio no importan aquí).
    for llamada_id in (reciente, vieja):
        servicio(fabrica, almacen, ahora=AHORA - timedelta(days=1100)).transcribir(llamada_id)

    resumen = borrar_transcripciones_vencidas(fabrica, 1095, AHORA)

    assert resumen.borradas == 1
    assert len(guardadas(fabrica, reciente)) == 1 and guardadas(fabrica, vieja) == []
    with unidad_de_trabajo(fabrica) as sesion:
        assert sesion.get(Llamada, vieja).transcripcion_estado == "eliminada"
        assert sesion.get(Llamada, reciente).transcripcion_estado == "transcrita"


def test_configuracion_y_composicion(fabrica):
    con_cloudtalk = {**ENTORNO_VALIDO, "CLOUDTALK_API_KEY_ID": "a", "CLOUDTALK_API_KEY_SECRET": "b"}

    def armar(**extra):
        cfg = cargar_config({**con_cloudtalk, **extra})
        return servicio_transcripcion(fabrica, cfg, servicio_audio(fabrica, cfg))

    assert armar() is None  # sin proveedor
    assert armar(TRANSCRIPCION_PROVEEDOR="openai") is None  # falta la clave
    con_openai = armar(OPENAI_API_KEY="sk", TRANSCRIPCION_RESPALDO="falsa, alibaba")
    assert con_openai.cadena == ["openai", "falsa"]  # alibaba no está registrada
    assert armar(TRANSCRIPCION_PROVEEDOR="falsa").cadena == ["falsa"]
    with pytest.raises(ConfigError, match="CLOUDTALK_CANAL_AGENTE"):
        cargar_config({**con_cloudtalk, "CLOUDTALK_CANAL_AGENTE": "medio"})
    cfg = cargar_config({**con_cloudtalk, "TRANSCRIPCION_VOCABULARIO": "grúa, Mapfre ,"})
    assert cfg.transcripcion_vocabulario == ("grúa", "Mapfre")


def test_consultas_de_la_pagina_transcripcion(fabrica, almacen):
    una, otra = guardar_llamada(fabrica, "1"), guardar_llamada(fabrica, "2")
    transcripcion = servicio(fabrica, almacen)
    transcripcion.transcribir(una)
    transcripcion.transcribir(una)
    rota = servicio(fabrica, almacen, estrategias={"rota": EstrategiaFalsa(error="caído")})
    rota.encolar([otra])
    for _ in range(3):
        rota.procesar_cola(5)

    ahora = datetime.now(timezone.utc)
    with unidad_de_trabajo(fabrica) as sesion:
        assert consultas.estado_cola(sesion) == {"error": 1}
        errores = consultas.trabajos_con_error(sesion)
        gasto = consultas.gasto(sesion, ahora - timedelta(days=1), ahora + timedelta(days=1))
        comparables = consultas.llamadas_comparables(sesion)
    assert [(e.llamada, e.intentos) for e in errores] == [("2", 3)]
    assert [(g.proveedor, g.transcripciones, g.costo) for g in gasto] == [("falsa", 2, Decimal("0"))]
    assert [(c.llamada, c.transcripciones) for c in comparables] == [("1", 2)]
