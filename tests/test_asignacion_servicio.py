from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.exc import IntegrityError

from panel.asignacion import registro
from panel.asignacion.servicio import (
    DESDE_SIEMPRE,
    SIN_REGLA,
    ReglaInvalida,
    ServicioAsignacion,
    ocupacion_semanal,
)
from panel.db.base import unidad_de_trabajo
from panel.db.modelos import Cuenta, ReglaAsignacion
from panel.db.repositorios.cuentas import RepositorioReglas
from panel.db.repositorios.personas import RepositorioPersonas
from panel.esquemas.personas import AsesorArea

MADRID = ZoneInfo("Europe/Madrid")
UTC = timezone.utc
LUN_VIE = [0, 1, 2, 3, 4]


def utc(*partes) -> datetime:
    return datetime(*partes, tzinfo=UTC)


@pytest.fixture
def datos(fabrica):
    """Una cuenta de CloudTalk y tres asesores: Juan, Ana y Luis (inactivo)."""
    with unidad_de_trabajo(fabrica) as sesion:
        personas = RepositorioPersonas(sesion)
        personas.sincronizar_areas(
            [
                AsesorArea(correo="juan@e.com", area="Comercial", nombre="Juan"),
                AsesorArea(correo="ana@e.com", area="Comercial", nombre="Ana"),
                AsesorArea(correo="luis@e.com", area="RDC", nombre="Luis"),
            ]
        )
        personas.sincronizar_areas(
            [
                AsesorArea(correo="juan@e.com", area="Comercial", nombre="Juan"),
                AsesorArea(correo="ana@e.com", area="Comercial", nombre="Ana"),
            ]
        )
        ids = {p.correo.split("@")[0]: p.id for p in personas.listar(solo_activas=False)}
        cuenta = Cuenta(plataforma="cloudtalk", id_externo="100", nombre="Asesor 3")
        sesion.add(cuenta)
        sesion.flush()
        ids["cuenta"] = cuenta.id
    return ids


def fijo_y_resto(datos, desde="08:00", hasta="14:00") -> dict:
    return {
        "persona_fija_id": datos["juan"],
        "franjas_fijas": [{"dias": LUN_VIE, "inicio": desde, "fin": hasta}],
        "persona_resto_id": datos["ana"],
    }


def crear(fabrica, datos, estrategia, parametros, desde=DESDE_SIEMPRE):
    with unidad_de_trabajo(fabrica) as sesion:
        return ServicioAsignacion(sesion).crear_regla(
            datos["cuenta"], estrategia, parametros, desde
        )


def asignar(fabrica, datos, inicio):
    with unidad_de_trabajo(fabrica) as sesion:
        return ServicioAsignacion(sesion).asignar(datos["cuenta"], inicio)


def test_sin_regla_queda_sin_asignar(fabrica, datos):
    resultado = asignar(fabrica, datos, utc(2026, 11, 3, 10))
    assert resultado.persona_id is None
    assert resultado.motivo == SIN_REGLA


def test_asigna_con_la_hora_de_españa(fabrica, datos):
    crear(fabrica, datos, "fijo_y_resto", fijo_y_resto(datos))
    # Martes 3 de noviembre de 2026, horario de invierno (UTC+1).
    assert asignar(fabrica, datos, utc(2026, 11, 3, 7, 30)).persona_id == datos["juan"]
    assert asignar(fabrica, datos, utc(2026, 11, 3, 6, 59)).persona_id == datos["ana"]
    assert asignar(fabrica, datos, utc(2026, 11, 3, 12, 59)).persona_id == datos["juan"]
    assert asignar(fabrica, datos, utc(2026, 11, 3, 13, 0)).persona_id == datos["ana"]


@pytest.mark.parametrize(
    ("inicio", "esperada"),
    [
        # Viernes 27 de marzo: invierno, 06:30 UTC son 07:30 en Madrid.
        (utc(2026, 3, 27, 6, 30), "ana"),
        # Lunes 30 de marzo: verano (UTC+2), la misma hora UTC ya son 08:30.
        (utc(2026, 3, 30, 6, 30), "juan"),
        # Viernes 23 de octubre: verano, 12:30 UTC son 14:30.
        (utc(2026, 10, 23, 12, 30), "ana"),
        # Lunes 26 de octubre: invierno, 12:30 UTC son 13:30.
        (utc(2026, 10, 26, 12, 30), "juan"),
    ],
)
def test_respeta_los_cambios_de_horario_de_verano(fabrica, datos, inicio, esperada):
    crear(fabrica, datos, "fijo_y_resto", fijo_y_resto(datos))
    assert asignar(fabrica, datos, inicio).persona_id == datos[esperada]


def test_una_regla_nueva_cierra_la_anterior_y_respeta_el_pasado(fabrica, datos):
    crear(fabrica, datos, "dueno_unico", {"persona_id": datos["juan"]})
    cambio = datetime(2026, 11, 1, tzinfo=MADRID)
    crear(fabrica, datos, "dueno_unico", {"persona_id": datos["ana"]}, cambio)

    assert asignar(fabrica, datos, utc(2026, 10, 31, 22, 59)).persona_id == datos["juan"]
    assert asignar(fabrica, datos, utc(2026, 10, 31, 23, 0)).persona_id == datos["ana"]
    with unidad_de_trabajo(fabrica) as sesion:
        historial = RepositorioReglas(sesion).historial(datos["cuenta"])
    assert [r.vigente_hasta for r in historial] == [None, cambio]


def test_corregir_una_regla_el_mismo_dia_la_deja_sin_vigencia(fabrica, datos):
    desde = datetime(2026, 11, 1, tzinfo=MADRID)
    crear(fabrica, datos, "dueno_unico", {"persona_id": datos["juan"]}, desde)
    crear(fabrica, datos, "dueno_unico", {"persona_id": datos["ana"]}, desde)

    assert asignar(fabrica, datos, utc(2026, 11, 5, 10)).persona_id == datos["ana"]
    with unidad_de_trabajo(fabrica) as sesion:
        historial = RepositorioReglas(sesion).historial(datos["cuenta"])
    assert len(historial) == 2
    corregida = [r for r in historial if r.parametros["persona_id"] == datos["juan"]][0]
    assert corregida.vigente_desde == corregida.vigente_hasta == desde


def test_no_se_puede_crear_una_regla_que_empiece_antes_que_la_ultima(fabrica, datos):
    crear(fabrica, datos, "dueno_unico", {"persona_id": datos["juan"]}, utc(2026, 11, 1))
    with pytest.raises(ReglaInvalida, match="no puede empezar antes"):
        crear(fabrica, datos, "dueno_unico", {"persona_id": datos["ana"]}, utc(2026, 10, 1))


def test_rechaza_parametros_invalidos_con_mensajes_legibles(fabrica, datos):
    parametros = {**fijo_y_resto(datos), "persona_resto_id": datos["juan"]}
    with pytest.raises(ReglaInvalida) as error:
        crear(fabrica, datos, "fijo_y_resto", parametros)
    assert error.value.errores == ["la persona fija y la del resto deben ser distintas"]


def test_rechaza_personas_inexistentes_o_inactivas(fabrica, datos):
    with pytest.raises(ReglaInvalida) as error:
        crear(fabrica, datos, "dueno_unico", {"persona_id": datos["luis"]})
    assert error.value.errores == ["Luis no está activa en la lista de asesores."]

    with pytest.raises(ReglaInvalida, match="No existe la persona 999999"):
        crear(fabrica, datos, "dueno_unico", {"persona_id": 999999})


def test_rechaza_una_estrategia_desconocida_o_retirada(fabrica, datos, monkeypatch):
    with pytest.raises(ReglaInvalida, match="no_existe"):
        crear(fabrica, datos, "no_existe", {})

    monkeypatch.setattr(type(registro.obtener("dueno_unico")), "retirada", True)
    with pytest.raises(ReglaInvalida, match="retirada"):
        crear(fabrica, datos, "dueno_unico", {"persona_id": datos["juan"]})


def test_una_estrategia_retirada_sigue_asignando_sus_reglas_viejas(fabrica, datos, monkeypatch):
    crear(fabrica, datos, "dueno_unico", {"persona_id": datos["juan"]})
    monkeypatch.setattr(type(registro.obtener("dueno_unico")), "retirada", True)
    assert asignar(fabrica, datos, utc(2026, 11, 3, 10)).persona_id == datos["juan"]


def test_la_base_impide_dos_reglas_vigentes_a_la_vez(fabrica, datos):
    with pytest.raises(IntegrityError):
        with unidad_de_trabajo(fabrica) as sesion:
            for persona in ("juan", "ana"):
                sesion.add(
                    ReglaAsignacion(
                        cuenta_id=datos["cuenta"],
                        estrategia="dueno_unico",
                        parametros={"persona_id": datos[persona]},
                        vigente_desde=DESDE_SIEMPRE,
                    )
                )


def test_describir_usa_los_nombres(fabrica, datos):
    regla = crear(fabrica, datos, "fijo_y_resto", fijo_y_resto(datos))
    with unidad_de_trabajo(fabrica) as sesion:
        servicio = ServicioAsignacion(sesion)
        assert servicio.describir(regla) == ["Juan: lun–vie 08:00–14:00", "Ana: todo lo demás"]
        assert servicio.personas_inactivas(regla) == []
        assert servicio.formatear_fecha(regla.vigente_desde) == "siempre"
        assert servicio.inicio_del_dia(date(2026, 11, 1)) == datetime(2026, 11, 1, tzinfo=MADRID)


def test_ocupacion_semanal_pregunta_a_la_estrategia_tramo_por_tramo():
    estrategia = registro.obtener("fijo_y_resto")
    parametros = estrategia.Parametros.model_validate(
        {
            "persona_fija_id": 1,
            "franjas_fijas": [{"dias": LUN_VIE, "inicio": "08:00", "fin": "14:00"}],
            "persona_resto_id": 2,
        }
    )
    celdas = ocupacion_semanal(estrategia, parametros, paso_minutos=60)
    assert len(celdas) == 7 * 24
    por_tramo = {(c.dia, c.hora.hour): c.resultado.persona_id for c in celdas}
    assert por_tramo[(0, 8)] == 1
    assert por_tramo[(0, 14)] == 2
    assert por_tramo[(5, 10)] == 2
