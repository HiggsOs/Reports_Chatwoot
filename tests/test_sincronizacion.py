from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from panel.db.base import unidad_de_trabajo
from panel.db.modelos import Conversacion, Llamada, PuntoSincronizacion
from panel.fuentes.cuentas import CuentaExterna
from panel.fuentes.interacciones import ConversacionExterna, LlamadaExterna
from panel.servicios.interacciones import ServicioInteracciones
from panel.sync.sincronizadores import (
    CLAVE_BLOQUEO_SINCRONIZACION,
    SincronizadorConversaciones,
    SincronizadorLlamadas,
    ejecutar_ciclo,
)

UTC = timezone.utc
AHORA = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
INICIAL = AHORA - timedelta(days=30)


def llamada(id_externo, inicio):
    return LlamadaExterna(
        id_externo=id_externo,
        agente=CuentaExterna(id_externo="100", nombre="Asesor"),
        inicio=inicio,
        duracion_s=30,
        direccion="entrante",
        grabada=False,
        enlace_plataforma=None,
        telefono_cliente=None,
        nombre_cliente=None,
        datos_origen={},
    )


def conversacion(id_externo, ultima):
    return ConversacionExterna(
        id_externo=id_externo,
        usuario=None,
        inicio=AHORA - timedelta(days=1),
        ultima_actividad=ultima,
        canal="WhatsApp",
        estado="open",
        etiquetas=[],
        telefono_cliente=None,
        nombre_cliente=None,
        datos_origen={"id": int(id_externo), "status": "open"},
    )


class FuenteLlamadasFalsa:
    plataforma = "cloudtalk"

    def __init__(self, llamadas=(), error=None):
        self.llamadas_disponibles = list(llamadas)
        self.error = error
        self.pedidos = []

    def llamadas(self, desde, hasta):
        self.pedidos.append((desde, hasta))
        if self.error:
            raise self.error
        return self.llamadas_disponibles


class FuenteConversacionesFalsa:
    plataforma = "chatwoot"

    def __init__(self, conversaciones):
        self.disponibles = conversaciones
        self.pedidos = []
        self.mensajes_pedidos = []

    def conversaciones(self, desde, hasta):
        self.pedidos.append((desde, hasta))
        return self.disponibles

    def mensajes(self, id_externo):
        self.mensajes_pedidos.append(id_externo)
        return []


def punto(fabrica, fuente):
    with unidad_de_trabajo(fabrica) as sesion:
        p = sesion.get(PuntoSincronizacion, fuente)
        return p.hasta, p.ultimo_exito, p.ultimo_error, p.resumen


def contar(fabrica, modelo):
    with unidad_de_trabajo(fabrica) as sesion:
        return sesion.scalar(select(func.count()).select_from(modelo))


def sincronizador_llamadas(fabrica, fuente, ahora=AHORA):
    return SincronizadorLlamadas(fabrica, fuente, INICIAL, ahora=lambda: ahora)


def test_la_primera_vez_trae_desde_el_inicio_configurado(fabrica):
    fuente = FuenteLlamadasFalsa([llamada("1", AHORA - timedelta(hours=1))])
    resultado = sincronizador_llamadas(fabrica, fuente).ejecutar()

    assert fuente.pedidos == [(INICIAL, AHORA)]
    assert resultado.error is None
    assert resultado.resumen["nuevas"] == 1
    hasta, exito, error, resumen = punto(fabrica, "cloudtalk")
    assert (hasta, exito, error) == (AHORA, AHORA, None)
    assert resumen["nuevas"] == 1


def test_despues_sigue_desde_el_punto_con_margen(fabrica):
    fuente = FuenteLlamadasFalsa()
    sincronizador_llamadas(fabrica, fuente).ejecutar()
    despues = AHORA + timedelta(minutes=15)
    sincronizador_llamadas(fabrica, fuente, despues).ejecutar()
    assert fuente.pedidos[1] == (AHORA - timedelta(hours=2), despues)


def test_un_error_queda_anotado_y_no_avanza_el_punto(fabrica):
    sincronizador_llamadas(fabrica, FuenteLlamadasFalsa()).ejecutar()
    falla = FuenteLlamadasFalsa(error=RuntimeError("CloudTalk no responde"))
    resultado = sincronizador_llamadas(fabrica, falla, AHORA + timedelta(hours=1)).ejecutar()

    assert resultado.error == "RuntimeError: CloudTalk no responde"
    hasta, _, error, _ = punto(fabrica, "cloudtalk")
    assert hasta == AHORA
    assert error == "RuntimeError: CloudTalk no responde"


def test_una_carga_de_historial_no_hace_retroceder_el_punto(fabrica):
    fuente = FuenteLlamadasFalsa([llamada("viejo", datetime(2026, 1, 10, tzinfo=UTC))])
    sincronizador_llamadas(fabrica, fuente).ejecutar()
    sincronizador_llamadas(fabrica, fuente).ejecutar(
        desde=datetime(2026, 1, 1, tzinfo=UTC), hasta=datetime(2026, 2, 1, tzinfo=UTC)
    )
    assert fuente.pedidos[1] == (datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 2, 1, tzinfo=UTC))
    assert punto(fabrica, "cloudtalk")[0] == AHORA
    assert contar(fabrica, Llamada) == 1


def test_conversaciones_relee_los_ultimos_dias_y_pide_mensajes_solo_si_cambio(fabrica):
    ultima = AHORA - timedelta(hours=3)
    fuente = FuenteConversacionesFalsa([conversacion("1", ultima), conversacion("2", ultima)])
    sincronizador = SincronizadorConversaciones(fabrica, fuente, INICIAL, 14, ahora=lambda: AHORA)
    sincronizador.ejecutar()
    assert fuente.mensajes_pedidos == ["1", "2"]

    fuente.disponibles = [conversacion("1", ultima), conversacion("2", AHORA)]
    despues = AHORA + timedelta(minutes=15)
    SincronizadorConversaciones(fabrica, fuente, INICIAL, 14, ahora=lambda: despues).ejecutar()
    assert fuente.mensajes_pedidos == ["1", "2", "2"]
    assert fuente.pedidos[1] == (despues - timedelta(days=14), despues)
    assert contar(fabrica, Conversacion) == 2


def test_el_ciclo_sigue_aunque_una_fuente_falle(fabrica):
    falla = sincronizador_llamadas(fabrica, FuenteLlamadasFalsa(error=RuntimeError("x")))
    bien = SincronizadorConversaciones(
        fabrica, FuenteConversacionesFalsa([conversacion("1", AHORA)]), INICIAL, 14, ahora=lambda: AHORA
    )
    resultados = ejecutar_ciclo(fabrica, [falla, bien])
    assert [r.error is not None for r in resultados] == [True, False]
    assert contar(fabrica, Conversacion) == 1


def test_no_corren_dos_ciclos_a_la_vez(fabrica, motor):
    with motor.connect() as otra:
        otra.execute(select(func.pg_advisory_lock(CLAVE_BLOQUEO_SINCRONIZACION)))
        try:
            fuente = FuenteLlamadasFalsa()
            assert ejecutar_ciclo(fabrica, [sincronizador_llamadas(fabrica, fuente)]) is None
            assert fuente.pedidos == []
        finally:
            otra.execute(select(func.pg_advisory_unlock(CLAVE_BLOQUEO_SINCRONIZACION)))


@pytest.mark.parametrize("veces", [2])
def test_el_bloqueo_se_libera_al_terminar(fabrica, veces):
    fuente = FuenteLlamadasFalsa()
    for _ in range(veces):
        assert ejecutar_ciclo(fabrica, [sincronizador_llamadas(fabrica, fuente)]) is not None


def test_pide_los_mensajes_que_faltan_aunque_la_conversacion_no_cambie(fabrica):
    ultima = AHORA - timedelta(hours=3)
    with unidad_de_trabajo(fabrica) as sesion:
        # Guardada por una versión anterior, sin mensajes.
        ServicioInteracciones(sesion).guardar_conversaciones([(conversacion("1", ultima), None)])
    fuente = FuenteConversacionesFalsa([conversacion("1", ultima)])
    SincronizadorConversaciones(fabrica, fuente, INICIAL, 14, ahora=lambda: AHORA).ejecutar()
    assert fuente.mensajes_pedidos == ["1"]


def test_cada_ciclo_lee_los_ajustes_del_panel(fabrica):
    from config import cargar_config
    from panel.ajustes import Cifrador, RepositorioAjustes
    from panel.sync.__main__ import config_del_ciclo
    from tests.test_config import ENTORNO_VALIDO

    base = cargar_config(ENTORNO_VALIDO)
    with fabrica() as sesion:
        RepositorioAjustes(sesion, Cifrador.desde_entorno(ENTORNO_VALIDO)).guardar(
            {"SYNC_INTERVALO_MINUTOS": "5", "CHATWOOT_API_TOKEN": "del-panel"}
        )
        sesion.commit()

    cfg = config_del_ciclo(base, fabrica, ENTORNO_VALIDO)
    assert cfg.sync_intervalo_minutos == 5
    assert cfg.api_token == "del-panel"

    with fabrica() as sesion:
        RepositorioAjustes(sesion, Cifrador.desde_entorno(ENTORNO_VALIDO)).guardar(
            {"SYNC_INTERVALO_MINUTOS": "cero"}
        )
        sesion.commit()
    # Un ajuste inválido no frena la sincronización: sigue con el entorno.
    assert config_del_ciclo(base, fabrica, ENTORNO_VALIDO) is base
