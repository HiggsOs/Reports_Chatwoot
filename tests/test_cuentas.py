from datetime import datetime, timezone

import responses

from chatwoot import ClienteChatwoot
from panel.asignacion.servicio import ServicioAsignacion
from panel.db.base import unidad_de_trabajo
from panel.db.repositorios.cuentas import RepositorioCuentas, RepositorioReglas
from panel.db.repositorios.personas import RepositorioPersonas
from panel.esquemas.personas import AsesorArea
from panel.fuentes.cuentas import CuentaExterna, cuentas_de_chatwoot, cuentas_de_cloudtalk
from panel.servicios.cuentas import ServicioCuentas


def externa(id_externo, nombre="Agente", correo=None):
    return CuentaExterna(id_externo=id_externo, nombre=nombre, correo=correo)


def actualizar(fabrica, plataforma, *externas):
    with unidad_de_trabajo(fabrica) as sesion:
        return ServicioCuentas(sesion).actualizar(plataforma, list(externas))


def cuentas(fabrica, plataforma):
    with unidad_de_trabajo(fabrica) as sesion:
        return {
            id_externo: (c.nombre, c.correo, c.activa)
            for id_externo, c in RepositorioCuentas(sesion).de_plataforma(plataforma).items()
        }


# --- Adaptadores ------------------------------------------------------------


def test_cuentas_de_cloudtalk():
    agentes = [
        {"id": "7", "firstname": "Ana", "lastname": "Gil", "email": " Ana@E.com ", "extension": "1002"},
        {"id": "8", "email": "x@e.com"},
        {"firstname": "Sin id"},
    ]
    assert cuentas_de_cloudtalk(agentes) == [
        externa("7", "Ana Gil (ext. 1002)", "ana@e.com"),
        externa("8", "x@e.com", "x@e.com"),
    ]


def test_cuentas_de_chatwoot():
    agentes = [
        {"id": 3, "name": "Ana Gil", "available_name": "Ana", "email": "ana@e.com"},
        {"id": 4, "name": "", "email": "luis@e.com"},
        {"id": 5},
    ]
    assert cuentas_de_chatwoot(agentes) == [
        externa("3", "Ana", "ana@e.com"),
        externa("4", "luis@e.com", "luis@e.com"),
        externa("5", "Usuario 5", None),
    ]


@responses.activate
def test_chatwoot_lista_los_agentes():
    responses.get(
        "https://chat.e.com/api/v1/accounts/1/agents",
        json=[{"id": 3, "name": "Ana", "email": "ana@e.com"}],
    )
    assert ClienteChatwoot("https://chat.e.com", 1, "t").listar_agentes() == [
        {"id": 3, "name": "Ana", "email": "ana@e.com"}
    ]


# --- Servicio ---------------------------------------------------------------


def test_crea_y_actualiza_cuentas(fabrica):
    resumen = actualizar(fabrica, "cloudtalk", externa("1", "Ana"), externa("2", "Luis"))
    assert resumen.nuevas == 2

    resumen = actualizar(fabrica, "cloudtalk", externa("1", "Ana Gil"), externa("2", "Luis"))
    assert (resumen.nuevas, resumen.actualizadas) == (0, 1)
    assert cuentas(fabrica, "cloudtalk")["1"] == ("Ana Gil", None, True)


def test_la_cuenta_que_desaparece_se_desactiva_y_puede_volver(fabrica):
    actualizar(fabrica, "cloudtalk", externa("1"), externa("2"))
    assert actualizar(fabrica, "cloudtalk", externa("1")).desactivadas == 1
    assert cuentas(fabrica, "cloudtalk")["2"][2] is False

    assert actualizar(fabrica, "cloudtalk", externa("1"), externa("2")).reactivadas == 1
    assert cuentas(fabrica, "cloudtalk")["2"][2] is True


def test_una_respuesta_vacia_no_desactiva_nada(fabrica):
    actualizar(fabrica, "cloudtalk", externa("1"))
    assert actualizar(fabrica, "cloudtalk").desactivadas == 0
    assert cuentas(fabrica, "cloudtalk")["1"][2] is True


def test_las_plataformas_no_se_mezclan(fabrica):
    actualizar(fabrica, "cloudtalk", externa("1", "Agente CT"))
    actualizar(fabrica, "chatwoot", externa("1", "Usuario CW"))
    assert cuentas(fabrica, "cloudtalk")["1"][0] == "Agente CT"
    assert cuentas(fabrica, "chatwoot")["1"][0] == "Usuario CW"


def test_chatwoot_crea_la_regla_por_correo(fabrica):
    with unidad_de_trabajo(fabrica) as sesion:
        RepositorioPersonas(sesion).sincronizar_areas(
            [AsesorArea(correo="ana@e.com", area="RDC", nombre="Ana")]
        )

    resumen = actualizar(
        fabrica, "chatwoot", externa("3", "Ana", "ana@e.com"), externa("4", "Otro", "otro@e.com")
    )
    assert resumen.reglas_automaticas == 1

    with unidad_de_trabajo(fabrica) as sesion:
        cuenta_ana = RepositorioCuentas(sesion).de_plataforma("chatwoot")["3"]
        cuenta_otro = RepositorioCuentas(sesion).de_plataforma("chatwoot")["4"]
        assert len(RepositorioReglas(sesion).historial(cuenta_otro.id)) == 0
        servicio = ServicioAsignacion(sesion)
        resultado = servicio.asignar(cuenta_ana.id, datetime(2026, 11, 3, tzinfo=timezone.utc))
        assert resultado.persona_id is not None
        assert servicio.describir(RepositorioReglas(sesion).ultima(cuenta_ana.id)) == [
            "Todo para Ana"
        ]

    # Una segunda actualización no duplica la regla.
    assert actualizar(fabrica, "chatwoot", externa("3", "Ana", "ana@e.com")).reglas_automaticas == 0


def test_cloudtalk_no_crea_reglas_por_correo(fabrica):
    with unidad_de_trabajo(fabrica) as sesion:
        RepositorioPersonas(sesion).sincronizar_areas(
            [AsesorArea(correo="ana@e.com", area="RDC")]
        )
    assert actualizar(fabrica, "cloudtalk", externa("7", "Ana", "ana@e.com")).reglas_automaticas == 0
