import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError

from panel.db.base import (
    comprobar_conexion,
    crear_fabrica_sesiones,
    crear_motor,
    unidad_de_trabajo,
)
from panel.db.modelos import Persona
from panel.db.repositorios.personas import RepositorioPersonas
from panel.esquemas.personas import AsesorArea


def asesor(correo, area="Comercial"):
    return AsesorArea(correo=correo, area=area)


def guardar(fabrica, *asesores):
    with unidad_de_trabajo(fabrica) as sesion:
        return RepositorioPersonas(sesion).sincronizar_areas(list(asesores))


def mapa(fabrica):
    with unidad_de_trabajo(fabrica) as sesion:
        return RepositorioPersonas(sesion).mapa_areas()


def test_asesor_normaliza_el_correo():
    assert asesor("  Ana@Empresa.COM ").correo == "ana@empresa.com"


def test_asesor_rechaza_correo_vacio_y_area_invalida():
    with pytest.raises(ValidationError):
        asesor("   ")
    with pytest.raises(ValidationError):
        asesor("ana@empresa.com", "Ventas")


def test_base_vacia(fabrica):
    with unidad_de_trabajo(fabrica) as sesion:
        assert not RepositorioPersonas(sesion).hay_personas()
    assert mapa(fabrica) == {}


def test_crea_asesores(fabrica):
    resumen = guardar(fabrica, asesor("luis@e.com", "RDC"), asesor("ana@e.com"))
    assert resumen.creadas == 2
    assert list(mapa(fabrica).items()) == [("ana@e.com", "Comercial"), ("luis@e.com", "RDC")]


def test_cambia_el_area(fabrica):
    guardar(fabrica, asesor("ana@e.com"))
    resumen = guardar(fabrica, asesor("ana@e.com", "RDC"))
    assert resumen.actualizadas == 1
    assert mapa(fabrica) == {"ana@e.com": "RDC"}


def test_quitar_un_asesor_lo_desactiva_sin_borrarlo(fabrica):
    guardar(fabrica, asesor("ana@e.com"), asesor("luis@e.com"))
    resumen = guardar(fabrica, asesor("ana@e.com"))

    assert resumen.desactivadas == 1
    assert mapa(fabrica) == {"ana@e.com": "Comercial"}
    with unidad_de_trabajo(fabrica) as sesion:
        luis = sesion.scalar(select(Persona).where(Persona.correo == "luis@e.com"))
        assert luis is not None and not luis.activa


def test_volver_a_agregarlo_lo_reactiva_con_su_area_nueva(fabrica):
    guardar(fabrica, asesor("ana@e.com"))
    guardar(fabrica)
    resumen = guardar(fabrica, asesor("ana@e.com", "RDC"))

    assert (resumen.reactivadas, resumen.actualizadas, resumen.creadas) == (1, 1, 0)
    assert mapa(fabrica) == {"ana@e.com": "RDC"}


def test_guardar_lo_mismo_no_cambia_nada(fabrica):
    guardar(fabrica, asesor("ana@e.com"))
    assert not guardar(fabrica, asesor("ana@e.com")).hubo_cambios


def test_correos_repetidos_no_se_guardan(fabrica):
    with pytest.raises(ValueError):
        guardar(fabrica, asesor("ana@e.com"), asesor("ANA@e.com", "RDC"))
    assert mapa(fabrica) == {}


def test_la_base_rechaza_un_area_invalida(fabrica):
    with pytest.raises(IntegrityError):
        with unidad_de_trabajo(fabrica) as sesion:
            sesion.add(Persona(correo="ana@e.com", area="Ventas"))


def test_la_base_rechaza_un_correo_sin_normalizar(fabrica):
    with pytest.raises(IntegrityError):
        with unidad_de_trabajo(fabrica) as sesion:
            sesion.add(Persona(correo="Ana@e.com", area="RDC"))


def test_comprobar_conexion_con_la_base_en_marcha(fabrica):
    comprobar_conexion(fabrica)


def test_comprobar_conexion_falla_si_la_base_no_responde():
    motor = crear_motor("postgresql+psycopg://nadie@127.0.0.1:1/panel_test?connect_timeout=2")
    with pytest.raises(OperationalError):
        comprobar_conexion(crear_fabrica_sesiones(motor))
