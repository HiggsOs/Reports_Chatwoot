"""Panel de auditorías: punto de entrada de Streamlit.

Aquí solo se carga la configuración, se comprueba la base, se pide el login y
se arma la navegación. Cada página vive en `ui/`.
"""

import logging
import os
from functools import partial
from pathlib import Path

import streamlit as st
import streamlit_authenticator as stauth
from sqlalchemy.exc import SQLAlchemyError

from config import ConfigError, cargar_config, ruta_asesores
from panel.composicion import servicio_audio
from panel.db.base import (
    comprobar_conexion,
    crear_fabrica_sesiones,
    crear_motor,
    unidad_de_trabajo,
)
from panel.db.repositorios.personas import RepositorioPersonas
from panel.importar_asesores import importar_asesores_csv
from ui import asesores as ui_asesores
from ui import clientes as ui_clientes
from ui import cuentas as ui_cuentas
from ui import en_vivo as ui_en_vivo
from ui import inicio as ui_inicio
from ui import interacciones as ui_interacciones

registro = logging.getLogger(__name__)

st.set_page_config(page_title="Panel de auditorías", page_icon="📊", layout="wide")


@st.cache_resource
def obtener_config():
    return cargar_config(os.environ)


@st.cache_resource
def obtener_fabrica(database_url: str):
    return crear_fabrica_sesiones(crear_motor(database_url))


@st.cache_resource(show_spinner="Importando asesores a la base de datos…")
def importar_asesores_una_vez(database_url: str, ruta: str):
    """Copia `asesores.csv` a la base la primera vez que arranca la app."""
    return importar_asesores_csv(Path(ruta), obtener_fabrica(database_url))


@st.cache_resource
def obtener_audio(database_url: str):
    """Uno para toda la app: comparte el cliente de CloudTalk y su control del
    límite de peticiones."""
    return servicio_audio(obtener_fabrica(database_url), CFG)


def leer_areas() -> dict[str, str]:
    with unidad_de_trabajo(obtener_fabrica(CFG.database_url)) as sesion:
        return RepositorioPersonas(sesion).mapa_areas()


try:
    CFG = obtener_config()
except ConfigError as error:
    st.error(f"La aplicación no está bien configurada.\n\n{error}")
    st.stop()

try:
    # En cada carga: el motor queda en caché, pero la base puede haberse caído
    # después de arrancar.
    comprobar_conexion(obtener_fabrica(CFG.database_url))
    IMPORTACION = importar_asesores_una_vez(
        CFG.database_url, str(ruta_asesores(CFG))
    )
except SQLAlchemyError:
    # Esto se ve antes del login: el detalle (servidor, usuario) va solo al log.
    registro.exception("No se pudo conectar con la base de datos.")
    st.error(
        "No se pudo conectar con la base de datos. Revise DATABASE_URL y que "
        "PostgreSQL esté en marcha; el detalle está en el log del servicio."
    )
    st.stop()

autenticador = stauth.Authenticate(
    {
        "usernames": {
            CFG.usuario: {
                "name": CFG.usuario,
                "password": CFG.password_hash,
                "email": "",
            }
        }
    },
    "reporte_chatwoot",
    CFG.cookie_key,
    cookie_expiry_days=7,
)

autenticador.login(location="main", fields={"Form name": "Ingresar"})

if st.session_state.get("authentication_status") is False:
    st.error("Usuario o contraseña incorrectos.")
    st.stop()
if st.session_state.get("authentication_status") is None:
    st.info("Ingrese sus datos para entrar al panel.")
    st.stop()

autenticador.logout("Cerrar sesión", "sidebar")

FABRICA = obtener_fabrica(CFG.database_url)
AUDIO = obtener_audio(CFG.database_url)


def pagina(funcion, titulo: str, ruta: str, icono: str, **extra) -> st.Page:
    return st.Page(partial(funcion, **extra), title=titulo, url_path=ruta, icon=icono)


historial = pagina(ui_clientes.mostrar, "Historial del cliente", "historial", "🧾",
                   fabrica=FABRICA, cfg=CFG, audio=AUDIO)
sin_asignar = pagina(ui_interacciones.sin_asignar, "Sin asignar", "sin-asignar", "📥",
                     fabrica=FABRICA, cfg=CFG)
cuentas = pagina(ui_cuentas.mostrar, "Cuentas", "cuentas", "🗂️", fabrica=FABRICA, cfg=CFG)
inicio = st.Page(
    partial(ui_inicio.mostrar, FABRICA, CFG, {"sin_asignar": sin_asignar, "cuentas": cuentas}),
    title="Inicio",
    url_path="inicio",
    icon="🏠",
    default=True,
)

navegacion = st.navigation(
    {
        "Auditoría": [
            inicio,
            sin_asignar,
            pagina(ui_interacciones.pagina, "Llamadas", "llamadas", "📞",
                   fabrica=FABRICA, cfg=CFG, tipo="llamada", historial=historial, audio=AUDIO),
            pagina(ui_interacciones.pagina, "Conversaciones", "conversaciones", "💬",
                   fabrica=FABRICA, cfg=CFG, tipo="conversacion", historial=historial),
            historial,
        ],
        "Configuración": [
            pagina(ui_asesores.mostrar, "Asesores", "asesores", "👥",
                   fabrica=FABRICA, importacion=IMPORTACION),
            cuentas,
        ],
        "Reportes en vivo": [
            pagina(ui_en_vivo.reporte_chatwoot, "Reporte de Chatwoot", "reporte-chatwoot", "📊",
                   cfg=CFG, leer_areas=leer_areas),
            pagina(ui_en_vivo.transcripciones_ringover, "Transcripciones de Ringover",
                   "transcripciones-ringover", "🎙️", cfg=CFG),
            pagina(ui_en_vivo.transcripciones_cloudtalk, "Transcripciones de CloudTalk",
                   "transcripciones-cloudtalk", "🎧", cfg=CFG),
        ],
    }
)
navegacion.run()
