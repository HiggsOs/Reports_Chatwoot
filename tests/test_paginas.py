"""Prueba de humo de la interfaz: cada página registrada se dibuja sin errores
contra una base real (vacía) con Streamlit AppTest."""

import os

import pytest
from streamlit.testing.v1 import AppTest

from ui.navegacion import PAGINAS

GUION = """
import os
from dataclasses import replace
import streamlit as st
from config import cargar_config
from panel.ajustes import entorno_efectivo
from panel.composicion import servicio_audio, servicio_transcripcion
from panel.db.base import crear_fabrica_sesiones, crear_motor
from panel.importar_asesores import ResultadoImportacion
from ui import navegacion
from ui.componentes import estilo

estilo.aplicar()
fabrica = crear_fabrica_sesiones(crear_motor(cargar_config(os.environ).database_url))
efectivo, lectura = entorno_efectivo(os.environ, fabrica)
cfg = cargar_config(efectivo)
audio = servicio_audio(fabrica, cfg)
dependencias = {
    "fabrica": fabrica, "cfg": cfg, "audio": audio,
    "transcripcion": servicio_transcripcion(fabrica, cfg, audio),
    "importacion": None, "entorno": dict(os.environ), "lectura": lectura,
    "recargar": lambda: None, "leer_areas": lambda: {},
}
# La misma navegación que app.py, con la página a probar como inicial.
entradas = [replace(e, inicial=e.ruta == st.session_state["ruta"]) for e in navegacion.PAGINAS]
st.navigation(navegacion.armar(dependencias, entradas)).run()
"""


@pytest.fixture
def entorno(motor, monkeypatch):
    from tests.test_config import ENTORNO_VALIDO

    monkeypatch.setitem(os.environ, "DATABASE_URL", str(motor.url.render_as_string(hide_password=False)))
    for clave, valor in ENTORNO_VALIDO.items():
        if clave != "DATABASE_URL":
            monkeypatch.setitem(os.environ, clave, valor)


@pytest.mark.parametrize("ruta", [e.ruta for e in PAGINAS if not e.ruta.startswith("transcripciones-")])
def test_cada_pagina_se_dibuja(entorno, ruta):
    app = AppTest.from_string(GUION, default_timeout=60)
    app.session_state["ruta"] = ruta
    app.run()
    assert not app.exception, [e.message for e in app.exception]


@pytest.fixture
def con_datos(motor, entorno):
    """Una llamada, una conversación y ajustes de transcripción, confirmados
    (la app usa su propia conexión). Se borran al terminar."""
    import json
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import text
    from sqlalchemy.orm import sessionmaker

    from panel.ajustes import Cifrador, RepositorioAjustes
    from panel.db.repositorios.personas import RepositorioPersonas
    from panel.esquemas.personas import AsesorArea
    from panel.db.base import unidad_de_trabajo
    from panel.fuentes.interacciones import ConversacionExterna, CuentaExterna, LlamadaExterna
    from panel.servicios.interacciones import ServicioInteracciones

    fabrica = sessionmaker(motor, expire_on_commit=False)
    ahora = datetime.now(timezone.utc) - timedelta(hours=1)
    with unidad_de_trabajo(fabrica) as sesion:
        RepositorioPersonas(sesion).sincronizar_areas(
            [AsesorArea(correo="ana@ejemplo.es", area="Comercial", nombre="Ana Martín")]
        )
        servicio = ServicioInteracciones(sesion)
        servicio.guardar_llamadas([
            LlamadaExterna(
                id_externo="900", agente=CuentaExterna(id_externo="1", nombre="Compartida"),
                inicio=ahora, duracion_s=272, direccion="entrante", grabada=True,
                enlace_plataforma=None, telefono_cliente="612345678", nombre_cliente="Taller",
                datos_origen={},
            )
        ])
        servicio.guardar_conversaciones([(
            ConversacionExterna(
                id_externo="77", usuario=None, inicio=ahora, ultima_actividad=ahora,
                canal="WhatsApp", estado="open", etiquetas=["asistencia"],
                telefono_cliente="+34 612 345 678", nombre_cliente="Taller", datos_origen={},
            ),
            [],
        )])
        RepositorioAjustes(sesion, Cifrador.desde_entorno(os.environ)).guardar({
            "OPENAI_API_KEY": "sk-prueba",
            "TRANSCRIPCION_PROVEEDOR": "openai:whisper-1",
            "TRANSCRIPCION_MODELOS": json.dumps([
                {"proveedor": "openai", "modelo": "whisper-1", "precio_minuto": "0.006"}
            ]),
            "TRANSCRIPCION_TOPE_MENSUAL_USD": "50",
        })
    yield
    with motor.begin() as conexion:
        conexion.execute(text(
            "TRUNCATE ajustes, llamadas, conversaciones, clientes, cuentas, "
            "reglas_asignacion, personas RESTART IDENTITY CASCADE"
        ))


@pytest.mark.parametrize("ruta", ["inicio", "sin-asignar", "llamadas", "conversaciones",
                                  "historial", "general", "cuentas", "transcripcion"])
def test_cada_pagina_se_dibuja_con_datos(con_datos, ruta):
    app = AppTest.from_string(GUION, default_timeout=60)
    app.session_state["ruta"] = ruta
    app.run()
    assert not app.exception, [e.message for e in app.exception]


@pytest.mark.parametrize("ruta, clave", [("llamadas", "llamada-elegida"),
                                         ("conversaciones", "conversacion-elegida")])
def test_el_detalle_se_dibuja(con_datos, motor, ruta, clave):
    from sqlalchemy import text

    tabla = "llamadas" if ruta == "llamadas" else "conversaciones"
    with motor.connect() as conexion:
        elegida = conexion.execute(text(f"SELECT id FROM {tabla}")).scalar_one()
    app = AppTest.from_string(GUION, default_timeout=60)
    app.session_state["ruta"] = ruta
    app.session_state[clave] = elegida
    app.run()
    assert not app.exception, [e.message for e in app.exception]
    textos = " ".join(m.value for m in app.markdown)
    assert "Sin asignar" in textos  # la franja de quién atendió
