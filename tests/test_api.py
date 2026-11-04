"""La API del frontend de React, contra una base real."""

import json
from datetime import date, datetime, timedelta, timezone

import bcrypt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from api.contenedor import Contenedor
from api.main import crear_app
from panel.db.base import unidad_de_trabajo
from panel.db.repositorios.personas import RepositorioPersonas
from panel.esquemas.personas import AsesorArea
from panel.fuentes.interacciones import ConversacionExterna, CuentaExterna, LlamadaExterna
from panel.servicios.interacciones import ServicioInteracciones

CLAVE = "clave-del-panel"
CABECERA = {"X-Panel": "1"}


@pytest.fixture
def entorno(motor):
    return {
        "APP_USERNAME": "auditor",
        "APP_PASSWORD_HASH": bcrypt.hashpw(CLAVE.encode(), bcrypt.gensalt(4)).decode(),
        "APP_COOKIE_KEY": "cookie-de-prueba",
        "DATABASE_URL": motor.url.render_as_string(hide_password=False),
        "PANEL_COOKIE_SEGURA": "0",
        "DATA_DIR": "/tmp",
    }


@pytest.fixture
def datos(motor):
    fabrica = sessionmaker(motor, expire_on_commit=False)
    ahora = datetime.now(timezone.utc) - timedelta(hours=1)
    with unidad_de_trabajo(fabrica) as s:
        RepositorioPersonas(s).sincronizar_areas([AsesorArea(correo="ana@x.es", area="Comercial", nombre="Ana")])
        servicio = ServicioInteracciones(s)
        servicio.guardar_llamadas([LlamadaExterna(
            id_externo="900", agente=CuentaExterna(id_externo="1", nombre="Compartida"), inicio=ahora,
            duracion_s=272, direccion="entrante", grabada=True, enlace_plataforma=None,
            telefono_cliente="612345678", nombre_cliente="Taller", datos_origen={},
        )])
        servicio.guardar_conversaciones([(ConversacionExterna(
            id_externo="77", usuario=None, inicio=ahora, ultima_actividad=ahora, canal="WhatsApp",
            estado="open", etiquetas=[], telefono_cliente="+34 612 345 678", nombre_cliente="Taller",
            datos_origen={},
        ), [{"id": 1, "message_type": 0, "content": "Hola", "created_at": int(ahora.timestamp()),
             "sender": {"name": "Rosa"}}])])
    yield fabrica
    with motor.begin() as conexion:
        conexion.execute(text(
            "TRUNCATE ajustes, cobros_transcripcion, llamadas, conversaciones, clientes, cuentas, "
            "reglas_asignacion, personas RESTART IDENTITY CASCADE"
        ))


@pytest.fixture
def cliente(entorno, datos, tmp_path):
    web = tmp_path / "web"
    (web / "assets").mkdir(parents=True)
    (web / "index.html").write_text("<html>panel</html>")
    with TestClient(crear_app(Contenedor(entorno), web)) as cliente:
        yield cliente


@pytest.fixture
def con_sesion(cliente):
    respuesta = cliente.post("/api/sesion", json={"usuario": "auditor", "contrasena": CLAVE}, headers=CABECERA)
    assert respuesta.status_code == 200
    return cliente


def test_sin_sesion_no_se_puede_usar(cliente):
    assert cliente.get("/api/inicio").status_code == 401
    assert cliente.get("/api/sesion").status_code == 401


def test_login_incorrecto_y_bloqueo(cliente):
    for _ in range(4):
        r = cliente.post("/api/sesion", json={"usuario": "auditor", "contrasena": "mal"}, headers=CABECERA)
        assert r.status_code == 401
    assert "Le queda" in r.json()["detail"]
    cliente.post("/api/sesion", json={"usuario": "auditor", "contrasena": "mal"}, headers=CABECERA)
    r = cliente.post("/api/sesion", json={"usuario": "auditor", "contrasena": CLAVE}, headers=CABECERA)
    assert r.status_code == 429


def test_cambiar_algo_exige_la_cabecera(con_sesion):
    r = con_sesion.put("/api/interacciones/llamada/1/asignacion", json={"persona_id": None})
    assert r.status_code == 403


def test_cerrar_sesion(con_sesion):
    assert con_sesion.get("/api/sesion").json() == {"usuario": "auditor"}
    con_sesion.delete("/api/sesion", headers=CABECERA)
    assert con_sesion.get("/api/sesion").status_code == 401


def test_inicio(con_sesion):
    datos = con_sesion.get("/api/inicio").json()
    assert datos["semana"]["llamadas"] == 1
    assert datos["semana"]["conversaciones_sin_asignar"] == 1
    assert datos["config"]["cloudtalk"] is False


def _rango():
    hoy = date.today()
    return {"desde": (hoy - timedelta(days=7)).isoformat(), "hasta": hoy.isoformat()}


def test_listar_asignar_y_volver(con_sesion):
    llamadas = con_sesion.get("/api/interacciones/llamada", params=_rango()).json()
    assert llamadas["recortado"] is False
    fila = llamadas["filas"][0]
    assert fila["asesor"] == "" and fila["duracion_s"] == 272

    persona = con_sesion.get("/api/catalogos").json()["personas"][0]["id"]
    url = f"/api/interacciones/llamada/{fila['id']}/asignacion"
    assert con_sesion.put(url, json={"persona_id": persona}, headers=CABECERA).status_code == 204
    fila = con_sesion.get("/api/interacciones/llamada", params=_rango()).json()["filas"][0]
    assert (fila["asesor"], fila["asignacion"]) == ("Ana", "manual")
    assert con_sesion.delete(url, headers=CABECERA).status_code == 204
    assert con_sesion.get("/api/interacciones/llamada", params=_rango()).json()["filas"][0]["asesor"] == ""

    assert con_sesion.put("/api/interacciones/llamada/9999/asignacion", json={"persona_id": None},
                          headers=CABECERA).status_code == 404


def test_rango_invertido(con_sesion):
    r = con_sesion.get("/api/interacciones/llamada", params={"desde": "2026-10-10", "hasta": "2026-10-01"})
    assert r.status_code == 422


def test_csv(con_sesion):
    r = con_sesion.get("/api/interacciones/conversacion/csv", params=_rango())
    assert r.status_code == 200 and "Id Chatwoot" in r.text


def test_asignar_en_bloque(con_sesion):
    conversacion = con_sesion.get("/api/interacciones/conversacion", params=_rango()).json()["filas"][0]
    persona = con_sesion.get("/api/catalogos").json()["personas"][0]["id"]
    r = con_sesion.post("/api/sin-asignar/asignar", json={"tipo": "conversacion", "ids": [conversacion["id"]],
                                                          "persona_id": persona}, headers=CABECERA)
    assert r.json() == {"asignadas": 1}


def test_mensajes_y_historial(con_sesion):
    conversacion = con_sesion.get("/api/interacciones/conversacion", params=_rango()).json()["filas"][0]
    mensajes = con_sesion.get(f"/api/conversaciones/{conversacion['id']}/mensajes").json()
    assert mensajes[0]["texto"] == "Hola"
    encontrados = con_sesion.get("/api/clientes", params={"q": "612 345 678"}).json()
    assert len(encontrados) == 1
    historial = con_sesion.get(f"/api/clientes/{encontrados[0]['id']}").json()
    assert {e["tipo"] for e in historial["elementos"]} == {"llamada", "conversacion"}


def test_audio_sin_cloudtalk(con_sesion):
    llamada = con_sesion.get("/api/interacciones/llamada", params=_rango()).json()["filas"][0]
    r = con_sesion.get(f"/api/llamadas/{llamada['id']}/audio")
    assert r.status_code == 409 and "CloudTalk" in r.json()["detail"]


def test_ajustes_generales(con_sesion):
    r = con_sesion.put("/api/ajustes/general", json={"valores": {
        "CHATWOOT_BASE_URL": "https://chat.x.es", "CHATWOOT_ACCOUNT_ID": "2", "CHATWOOT_API_TOKEN": "tok-123456789",
    }}, headers=CABECERA)
    assert r.status_code == 204
    valores = con_sesion.get("/api/ajustes/general").json()
    assert valores["CHATWOOT_BASE_URL"] == {"valor": "https://chat.x.es", "secreto": False, "origen": "panel"}
    assert valores["CHATWOOT_API_TOKEN"]["valor"].endswith("6789")
    assert "tok-" not in valores["CHATWOOT_API_TOKEN"]["valor"]
    assert con_sesion.get("/api/estado").json()["chatwoot"] is True

    # Un secreto vacío no borra el guardado.
    con_sesion.put("/api/ajustes/general", json={"valores": {"CHATWOOT_API_TOKEN": ""}}, headers=CABECERA)
    assert con_sesion.get("/api/estado").json()["chatwoot"] is True

    r = con_sesion.put("/api/ajustes/general", json={"valores": {"SYNC_INTERVALO_MINUTOS": "cero"}}, headers=CABECERA)
    assert r.status_code == 422 and "SYNC_INTERVALO_MINUTOS" in r.json()["detail"]
    r = con_sesion.put("/api/ajustes/general", json={"valores": {"DATABASE_URL": "x"}}, headers=CABECERA)
    assert r.status_code == 422


def test_probar_conexiones_incompletas(con_sesion):
    r = con_sesion.post("/api/ajustes/probar/cloudtalk", json={"valores": {}}, headers=CABECERA).json()
    assert r["ok"] is False
    r = con_sesion.post("/api/ajustes/probar/almacen", json={"valores": {"ALMACEN_TIPO": "sftp"}},
                        headers=CABECERA).json()
    assert r["ok"] is False and "servidor" in r["mensaje"]


def test_configuracion_de_transcripcion(con_sesion):
    inicial = con_sesion.get("/api/transcripcion/configuracion").json()
    assert inicial["proveedores"][0]["nombre"] == "openai"
    assert inicial["proveedores"][0]["clave_mascara"] == ""

    # Sin CloudTalk no hay audio que transcribir.
    con_sesion.put("/api/ajustes/general", json={"valores": {
        "CLOUDTALK_API_KEY_ID": "id", "CLOUDTALK_API_KEY_SECRET": "secreto"}}, headers=CABECERA)
    assert con_sesion.put("/api/transcripcion/claves/openai", json={"clave": "sk-abcdefgh1234"},
                          headers=CABECERA).status_code == 204
    cambios = {
        "modelos": [{"proveedor": "openai", "modelo": "whisper-1", "precio_minuto": "0.006", "activo": True}],
        "principal": "openai:whisper-1",
        "tope_mensual_usd": 40,
    }
    assert con_sesion.put("/api/transcripcion/configuracion", json=cambios, headers=CABECERA).status_code == 204
    guardada = con_sesion.get("/api/transcripcion/configuracion").json()
    assert guardada["principal"] == "openai:whisper-1"
    assert guardada["tope_mensual_usd"] == 40
    assert guardada["proveedores"][0]["clave_mascara"].endswith("1234")

    resumen = con_sesion.get("/api/transcripcion/resumen").json()
    assert resumen["configurada"] is True and resumen["tope_mensual_usd"] == 40

    llamada = con_sesion.get("/api/interacciones/llamada", params=_rango()).json()["filas"][0]
    costo = con_sesion.post("/api/transcripcion/lote/costo", json={"ids": [llamada["id"]]}, headers=CABECERA).json()
    assert costo["llamadas"] == 1 and costo["costo_usd"] == pytest.approx(0.0272)
    opciones = con_sesion.get(f"/api/llamadas/{llamada['id']}/transcripciones").json()
    assert opciones["opciones"][0]["clave"] == "openai:whisper-1"

    malo = {**cambios, "principal": "openai:otro"}
    assert con_sesion.put("/api/transcripcion/configuracion", json=malo, headers=CABECERA).status_code == 422


def test_gasto_y_cobros(con_sesion):
    mes = date.today().replace(day=1).isoformat()
    r = con_sesion.put("/api/transcripcion/cobros", json={"mes": mes, "proveedor": "openai", "modelo": "whisper-1",
                                                          "minutos": "10", "usd": "0.066"}, headers=CABECERA)
    assert r.status_code == 204
    fila = con_sesion.get("/api/transcripcion/gasto", params={"mes": mes}).json()[0]
    assert fila["precio_real"] == pytest.approx(0.0066) and fila["titulo"] == "OpenAI · whisper-1"


def test_cuentas_y_reglas(con_sesion):
    cuentas = con_sesion.get("/api/cuentas").json()
    compartida = next(c for c in cuentas if c["nombre"] == "Compartida")
    assert compartida["estrategia"] is None
    persona = con_sesion.get("/api/catalogos").json()["personas"][0]["id"]
    regla = {"estrategia": "dueno_unico", "parametros": {"persona_id": persona}, "desde_siempre": True}
    previa = con_sesion.post(f"/api/cuentas/{compartida['id']}/reglas", json=regla, headers=CABECERA).json()
    assert previa["cambiaron"] == 1
    assert con_sesion.get("/api/cuentas").json()[0]["estrategia"] is None  # la previa no guarda
    con_sesion.post(f"/api/cuentas/{compartida['id']}/reglas", json={**regla, "previa": False}, headers=CABECERA)
    detalle = con_sesion.get(f"/api/cuentas/{compartida['id']}").json()
    assert detalle["estrategia"] == "dueno_unico" and detalle["horario"][0][10] == "Ana"
    malo = {"estrategia": "dueno_unico", "parametros": {}, "desde_siempre": True}
    assert con_sesion.post(f"/api/cuentas/{compartida['id']}/reglas", json=malo, headers=CABECERA).status_code == 422
    estrategias = con_sesion.get("/api/estrategias").json()
    assert {e["nombre"] for e in estrategias} >= {"dueno_unico", "fijo_y_resto", "franjas_completas"}


def test_asesores(con_sesion):
    r = con_sesion.put("/api/asesores", json={"asesores": [
        {"correo": "ana@x.es", "area": "Comercial", "nombre": "Ana"},
        {"correo": "luis@x.es", "area": "RDC", "nombre": "Luis"},
    ]}, headers=CABECERA)
    assert r.json()["creadas"] == 1
    assert len(con_sesion.get("/api/asesores").json()) == 2
    r = con_sesion.put("/api/asesores", json={"asesores": [{"correo": "a@x.es", "area": "Otra"}]}, headers=CABECERA)
    assert r.status_code == 422


def test_el_frontend_responde_cualquier_ruta(cliente):
    assert cliente.get("/llamadas").text == "<html>panel</html>"
    assert cliente.get("/api/no-existe").status_code == 404
    assert cliente.get("/api/salud").json() == {"ok": True}


class ChatwootFalso:
    """Lo mínimo que usa `reporte.generar_filas`."""

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def listar_conversaciones(self, _desde, _hasta):
        ahora = int(datetime.now(timezone.utc).timestamp())
        return [
            {"id": 1, "status": "open", "created_at": ahora, "inbox_id": 3, "labels": ["grua"],
             "meta": {"assignee": {"name": "Ana", "email": "ana@x.es"}}},
            {"id": 2, "status": "open", "created_at": ahora, "inbox_id": 3, "labels": [],
             "meta": {"assignee": {"name": "Luis", "email": "luis@x.es"}}},
        ]

    def listar_inboxes(self):
        return {3: "WhatsApp"}

    def listar_mensajes(self, _conversacion_id):
        return [{"message_type": 0, "content": "Hola"}]


def _esperar_reporte(cliente, trabajo_id):
    import time

    for _ in range(100):
        estado = cliente.get(f"/api/reportes/chatwoot/{trabajo_id}").json()
        if estado["estado"] != "en_curso":
            return estado
        time.sleep(0.05)
    raise AssertionError("El reporte no terminó.")


def test_reporte_chatwoot_sin_conectar(con_sesion):
    rango = {"desde": "2026-11-01", "hasta": "2026-11-04"}
    assert con_sesion.post("/api/reportes/chatwoot", json=rango, headers=CABECERA).status_code == 409


def test_reporte_chatwoot(entorno, datos, tmp_path, monkeypatch):
    from api.rutas import reportes

    monkeypatch.setattr(reportes, "ClienteChatwoot", ChatwootFalso)
    entorno = {**entorno, "CHATWOOT_BASE_URL": "https://chat.x.es", "CHATWOOT_ACCOUNT_ID": "1",
               "CHATWOOT_API_TOKEN": "t", "DATA_DIR": str(tmp_path)}
    with TestClient(crear_app(Contenedor(entorno), tmp_path / "sin-web")) as cliente:
        cliente.post("/api/sesion", json={"usuario": "auditor", "contrasena": CLAVE}, headers=CABECERA)
        invertido = cliente.post("/api/reportes/chatwoot", json={"desde": "2026-11-04", "hasta": "2026-11-01"},
                                 headers=CABECERA)
        assert invertido.status_code == 422
        hoy = date.today().isoformat()
        respuesta = cliente.post("/api/reportes/chatwoot", json={"desde": hoy, "hasta": hoy}, headers=CABECERA)
        assert respuesta.status_code == 200
        trabajo_id = respuesta.json()["id"]

        estado = _esperar_reporte(cliente, trabajo_id)
        assert estado["estado"] == "listo"
        assert [f["area"] for f in estado["filas"]] == ["Comercial", "SIN_MAPEAR"]
        assert estado["sin_mapear"] == ["luis@x.es"]

        csv = cliente.get(f"/api/reportes/chatwoot/{trabajo_id}/csv")
        assert csv.status_code == 200
        assert f"reporte-chatwoot-{hoy}-a-{hoy}.csv" in csv.headers["content-disposition"]
        assert csv.content.decode("utf-8-sig").splitlines()[0].startswith("conversacion_id,asesor")
        assert cliente.get("/api/reportes/chatwoot/no-existe").status_code == 404



def test_un_error_inesperado_llega_con_su_motivo(entorno, datos, tmp_path, monkeypatch):
    from api.rutas import inicio

    def explota(*_args, **_kwargs):
        raise ValueError("dato raro")

    monkeypatch.setattr(inicio.consultas, "resumen", explota)
    with TestClient(crear_app(Contenedor(entorno), tmp_path / "sin-web"), raise_server_exceptions=False) as cliente:
        cliente.post("/api/sesion", json={"usuario": "auditor", "contrasena": CLAVE}, headers=CABECERA)
        respuesta = cliente.get("/api/inicio")
    assert respuesta.status_code == 500
    assert respuesta.json()["detail"] == "Error inesperado: ValueError: dato raro"


def test_transcribir_pasa_por_la_cola_y_dice_por_que_fallo(entorno, datos, tmp_path, monkeypatch):
    from api.contenedor import Contenedor as ClaseContenedor
    from panel.transcripcion.base import OpcionesTranscripcion
    from panel.transcripcion.estrategias.falsa import EstrategiaFalsa
    from panel.transcripcion.servicio import ResultadoTranscripcion, ServicioTranscripcion

    servicio = ServicioTranscripcion(datos, None, {"falsa": EstrategiaFalsa()}, ["falsa"],
                                     OpcionesTranscripcion(idioma="es"))
    pedidos = []

    def transcribir(llamada_id, proveedor=None):
        pedidos.append((llamada_id, proveedor))
        return ResultadoTranscripcion(error="sin saldo")

    monkeypatch.setattr(servicio, "transcribir", transcribir)
    monkeypatch.setattr(ClaseContenedor, "transcripcion", property(lambda _self: servicio))
    with TestClient(crear_app(Contenedor(entorno), tmp_path / "sin-web")) as cliente:
        cliente.post("/api/sesion", json={"usuario": "auditor", "contrasena": CLAVE}, headers=CABECERA)
        llamada = cliente.get("/api/interacciones/llamada", params=_rango()).json()["filas"][0]

        respuesta = cliente.post(f"/api/llamadas/{llamada['id']}/transcripciones", json={"proveedor": "falsa"},
                                 headers=CABECERA)
        assert respuesta.status_code == 202
        # La cola lo procesó enseguida, en segundo plano.
        assert pedidos == [(llamada["id"], "falsa")]

        pedido = cliente.get(f"/api/llamadas/{llamada['id']}/transcripciones").json()["pedido"]
        assert (pedido["estado"], pedido["intentos"], pedido["error"]) == ("pendiente", 1, "sin saldo")
        abiertos = cliente.get("/api/transcripcion/resumen").json()["abiertos"]
        assert [(a["llamada"], a["estado"], a["error"]) for a in abiertos] == [("900", "pendiente", "sin saldo")]

        # Pedirla otra vez no duplica el pedido.
        cliente.post(f"/api/llamadas/{llamada['id']}/transcripciones", json={}, headers=CABECERA)
        assert len(cliente.get("/api/transcripcion/resumen").json()["abiertos"]) == 1
