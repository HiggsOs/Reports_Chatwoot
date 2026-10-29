from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest
from pydantic import BaseModel, ValidationError

from panel.asignacion import registro
from panel.asignacion.base import Franja, ResultadoAsignacion, describir_dias

MADRID = ZoneInfo("Europe/Madrid")
JUAN, ANA, LUIS = 1, 2, 3
LUN_VIE = (0, 1, 2, 3, 4)

# 2026-11-03 es martes y 2026-11-07, sábado.
MARTES = datetime(2026, 11, 3, tzinfo=MADRID)
SABADO = datetime(2026, 11, 7, tzinfo=MADRID)


def a_las(dia: datetime, hora: int, minuto: int = 0) -> datetime:
    return dia.replace(hour=hora, minute=minuto)


def franja(dias, inicio, fin) -> dict:
    return {"dias": list(dias), "inicio": inicio, "fin": fin}


# Un juego de parámetros válidos por estrategia. Una estrategia nueva tiene que
# sumar el suyo: test_toda_estrategia_tiene_un_ejemplo lo exige.
EJEMPLOS = {
    "dueno_unico": {"persona_id": JUAN},
    "fijo_y_resto": {
        "persona_fija_id": JUAN,
        "franjas_fijas": [
            franja(LUN_VIE, "08:00", "14:00"),
            franja(LUN_VIE, "16:00", "19:00"),
        ],
        "persona_resto_id": ANA,
    },
    "franjas_completas": {
        "franjas": [
            {**franja(LUN_VIE, "08:00", "14:00"), "persona_id": JUAN},
            {**franja(LUN_VIE, "14:00", "20:00"), "persona_id": ANA},
        ]
    },
}

TODAS = registro.disponibles(incluir_retiradas=True)


def parametros(nombre: str, datos: dict | None = None):
    estrategia = registro.obtener(nombre)
    return estrategia.Parametros.model_validate(datos or EJEMPLOS[nombre])


def asignar(nombre: str, momento: datetime, datos: dict | None = None):
    return registro.obtener(nombre).asignar(momento, parametros(nombre, datos))


# --- Contrato: corre contra todas las estrategias registradas ---------------


def test_toda_estrategia_tiene_un_ejemplo():
    assert {e.nombre for e in TODAS} <= set(EJEMPLOS)


@pytest.mark.parametrize("estrategia", TODAS, ids=lambda e: e.nombre)
def test_contrato_de_la_estrategia(estrategia):
    assert estrategia.titulo and estrategia.descripcion
    assert issubclass(estrategia.Parametros, BaseModel)

    datos = estrategia.Parametros.model_validate(EJEMPLOS[estrategia.nombre])
    # Los parámetros se guardan como JSON en la base y tienen que volver iguales.
    assert estrategia.Parametros.model_validate(datos.model_dump(mode="json")) == datos

    personas = estrategia.personas(datos)
    assert personas
    for dia in (MARTES, SABADO):
        for hora in range(24):
            resultado = estrategia.asignar(a_las(dia, hora), datos)
            assert isinstance(resultado, ResultadoAsignacion)
            assert resultado.motivo
            assert resultado.persona_id is None or resultado.persona_id in personas

    lineas = estrategia.describir(datos, {JUAN: "Juan", ANA: "Ana"})
    assert lineas and all(isinstance(linea, str) and linea for linea in lineas)


def test_obtener_una_estrategia_desconocida():
    with pytest.raises(registro.EstrategiaDesconocida):
        registro.obtener("no_existe")


def test_no_se_registra_dos_veces_el_mismo_nombre():
    class Repetida:
        nombre = "dueno_unico"

    with pytest.raises(ValueError):
        registro.registrar(Repetida)


# --- Franja -----------------------------------------------------------------


def test_franja_incluye_el_inicio_y_excluye_el_fin():
    f = Franja.model_validate(franja(LUN_VIE, "08:00", "14:00"))
    assert f.contiene(a_las(MARTES, 8))
    assert f.contiene(a_las(MARTES, 13, 59))
    assert not f.contiene(a_las(MARTES, 14))
    assert not f.contiene(a_las(MARTES, 7, 59))
    assert not f.contiene(a_las(SABADO, 10))


def test_franja_ordena_y_deduplica_los_dias():
    assert Franja.model_validate(franja([4, 0, 0], "08:00", "09:00")).dias == (0, 4)


@pytest.mark.parametrize(
    "datos",
    [
        franja([], "08:00", "09:00"),
        franja([7], "08:00", "09:00"),
        franja([0], "14:00", "08:00"),
        franja([0], "08:00", "08:00"),
    ],
)
def test_franja_invalida(datos):
    with pytest.raises(ValidationError):
        Franja.model_validate(datos)


def test_describir_dias():
    assert describir_dias((0, 1, 2, 3, 4)) == "lun–vie"
    assert describir_dias((0, 1, 2, 3, 4, 6)) == "lun–vie, dom"
    assert describir_dias((5, 6)) == "sáb, dom"


# --- dueno_unico ------------------------------------------------------------


def test_dueno_unico_asigna_todo_a_su_persona():
    assert asignar("dueno_unico", a_las(SABADO, 3)).persona_id == JUAN


# --- fijo_y_resto -----------------------------------------------------------


@pytest.mark.parametrize(
    ("momento", "esperada"),
    [
        (a_las(MARTES, 10, 30), JUAN),
        (a_las(MARTES, 8), JUAN),  # inicio incluido
        (a_las(MARTES, 14), ANA),  # fin excluido
        (a_las(MARTES, 15), ANA),  # corte del mediodía
        (a_las(MARTES, 16), JUAN),  # segunda franja
        (a_las(MARTES, 19), ANA),
        (a_las(MARTES, 7, 59), ANA),
        (a_las(SABADO, 10), ANA),  # fin de semana
    ],
)
def test_fijo_y_resto(momento, esperada):
    assert asignar("fijo_y_resto", momento).persona_id == esperada


def test_fijo_y_resto_explica_el_motivo():
    assert asignar("fijo_y_resto", a_las(MARTES, 10)).motivo == (
        "Dentro del horario fijo (lun–vie 08:00–14:00)"
    )
    assert asignar("fijo_y_resto", a_las(SABADO, 10)).motivo == "Fuera del horario fijo"


def test_fijo_y_resto_necesita_dos_personas_distintas():
    with pytest.raises(ValidationError):
        parametros("fijo_y_resto", {**EJEMPLOS["fijo_y_resto"], "persona_resto_id": JUAN})


def test_fijo_y_resto_necesita_al_menos_una_franja():
    with pytest.raises(ValidationError):
        parametros("fijo_y_resto", {**EJEMPLOS["fijo_y_resto"], "franjas_fijas": []})


def test_fijo_y_resto_rechaza_franjas_superpuestas():
    datos = {
        **EJEMPLOS["fijo_y_resto"],
        "franjas_fijas": [franja(LUN_VIE, "08:00", "14:00"), franja([2], "13:00", "15:00")],
    }
    with pytest.raises(ValidationError, match="se superponen"):
        parametros("fijo_y_resto", datos)


def test_fijo_y_resto_acepta_franjas_contiguas():
    datos = {
        **EJEMPLOS["fijo_y_resto"],
        "franjas_fijas": [franja(LUN_VIE, "08:00", "14:00"), franja(LUN_VIE, "14:00", "15:00")],
    }
    assert asignar("fijo_y_resto", a_las(MARTES, 14, 30), datos).persona_id == JUAN


# --- franjas_completas ------------------------------------------------------


@pytest.mark.parametrize(
    ("momento", "esperada"),
    [
        (a_las(MARTES, 9), JUAN),
        (a_las(MARTES, 14), ANA),
        (a_las(MARTES, 20), None),
        (a_las(SABADO, 10), None),
    ],
)
def test_franjas_completas(momento, esperada):
    assert asignar("franjas_completas", momento).persona_id == esperada


def test_franjas_completas_rechaza_dos_dueños_a_la_misma_hora():
    datos = {
        "franjas": [
            {**franja(LUN_VIE, "08:00", "14:00"), "persona_id": JUAN},
            {**franja([0], "13:00", "15:00"), "persona_id": LUIS},
        ]
    }
    with pytest.raises(ValidationError, match="se superponen"):
        parametros("franjas_completas", datos)
