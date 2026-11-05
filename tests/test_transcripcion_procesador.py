"""El diagnóstico de quién vacía la cola de transcripción.

La cola la procesa el servicio de sincronización. Si no corre, o corre sin la
transcripción armada, los pedidos se quedan esperando sin ningún error: el
panel tiene que decirlo.
"""

from datetime import timedelta

from panel.db.base import unidad_de_trabajo
from panel.db.modelos import PuntoSincronizacion, TrabajoTranscripcion
from panel.transcripcion import consultas
from tests.test_audio_servicio import AHORA, guardar_llamada


def _punto(fabrica, fuente, hace, error=None, resumen=None):
    with unidad_de_trabajo(fabrica) as sesion:
        sesion.add(PuntoSincronizacion(
            fuente=fuente, ultimo_intento=AHORA - hace, ultimo_exito=None if error else AHORA - hace,
            ultimo_error=error, resumen=resumen,
        ))


def _pedido(fabrica):
    llamada_id = guardar_llamada(fabrica)
    with unidad_de_trabajo(fabrica) as sesion:
        sesion.add(TrabajoTranscripcion(llamada_id=llamada_id))


def _estado(fabrica):
    with unidad_de_trabajo(fabrica) as sesion:
        return consultas.estado_procesador(sesion, AHORA, intervalo_minutos=15)


def test_sin_pedidos_esperando_no_hay_nada_que_avisar(fabrica):
    estado = _estado(fabrica)
    assert estado.diagnostico is None and estado.ultima_vuelta is None


def test_la_sincronizacion_nunca_corrio(fabrica):
    _pedido(fabrica)
    assert "La sincronización no corre (nunca)" in _estado(fabrica).diagnostico


def test_la_sincronizacion_se_detuvo(fabrica):
    _pedido(fabrica)
    _punto(fabrica, "cloudtalk", timedelta(hours=20))
    _punto(fabrica, consultas.TAREA_COLA, timedelta(hours=20))
    assert "La sincronización no corre (desde el" in _estado(fabrica).diagnostico


def test_la_sincronizacion_corre_pero_sin_transcripcion(fabrica):
    _pedido(fabrica)
    _punto(fabrica, "cloudtalk", timedelta(minutes=5))
    estado = _estado(fabrica)
    assert estado.sincronizacion == AHORA - timedelta(minutes=5)
    assert "corre, pero no transcribe" in estado.diagnostico


def test_la_cola_avanza(fabrica):
    _pedido(fabrica)
    _punto(fabrica, "cloudtalk", timedelta(minutes=50))
    # Un ciclo largo (40 min transcribiendo) no se confunde con uno detenido.
    _punto(fabrica, consultas.TAREA_COLA, timedelta(minutes=40), resumen={"hechos": 20})
    estado = _estado(fabrica)
    assert estado.diagnostico is None and estado.resumen == {"hechos": 20}


def test_la_ultima_vuelta_fallo(fabrica):
    _pedido(fabrica)
    _punto(fabrica, consultas.TAREA_COLA, timedelta(minutes=5), error="OperationalError: sin conexión")
    assert "OperationalError: sin conexión" in _estado(fabrica).diagnostico


def test_la_tabla_muestra_primero_la_que_se_esta_transcribiendo(fabrica):
    ids = [guardar_llamada(fabrica, id_externo=str(n)) for n in (1, 2, 3)]
    with unidad_de_trabajo(fabrica) as sesion:
        sesion.add_all(TrabajoTranscripcion(llamada_id=i) for i in ids)
    with unidad_de_trabajo(fabrica) as sesion:
        trabajo = sesion.query(TrabajoTranscripcion).filter_by(llamada_id=ids[2]).one()
        trabajo.estado = "en_proceso"
    with unidad_de_trabajo(fabrica) as sesion:
        abiertos = consultas.trabajos_abiertos(sesion)
    assert [(a.llamada, a.estado) for a in abiertos] == [("3", "en_proceso"), ("1", "pendiente"), ("2", "pendiente")]
