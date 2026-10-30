"""Panel de auditorías: punto de entrada de Streamlit.

Aquí solo se carga la configuración, se comprueba la base, se pide el login y
se arma la navegación. Cada página vive en `ui/`.

La configuración es el entorno con los ajustes guardados desde el panel
(pantallas General y Transcripción) encima. Al guardar un ajuste se vacían las
cachés que dependen de ella (`recargar`).
"""

import logging
import os
from pathlib import Path

import streamlit as st
import streamlit_authenticator as stauth
from sqlalchemy.exc import SQLAlchemyError

from config import ConfigError, cargar_config, ruta_asesores
from panel.ajustes import entorno_efectivo
from panel.composicion import servicio_audio, servicio_transcripcion
from panel.db.base import (
    comprobar_conexion,
    crear_fabrica_sesiones,
    crear_motor,
    unidad_de_trabajo,
)
from panel.db.repositorios.personas import RepositorioPersonas
from panel.importar_asesores import importar_asesores_csv
from ui import navegacion as navegacion_ui
from ui.componentes import estilo

registro = logging.getLogger(__name__)

st.set_page_config(
    page_title="Calidad · Grúas",
    page_icon=":material/fact_check:",
    layout="wide",
    initial_sidebar_state="expanded",
)
estilo.aplicar()


@st.cache_resource
def obtener_config_entorno():
    """Solo el entorno: alcanza para conectarse a la base y pedir el login."""
    return cargar_config(os.environ)


@st.cache_resource
def obtener_config(database_url: str):
    """El entorno con los ajustes del panel encima, y un error si los ajustes
    no son válidos (entonces se sigue con el entorno, para poder corregirlos)."""
    base = obtener_config_entorno()
    efectivo, lectura = entorno_efectivo(os.environ, obtener_fabrica(database_url))
    try:
        return cargar_config(efectivo), lectura, None
    except ConfigError as error:
        return base, lectura, str(error)


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
    return servicio_audio(obtener_fabrica(database_url), obtener_config(database_url)[0])


@st.cache_resource
def obtener_transcripcion(database_url: str):
    return servicio_transcripcion(
        obtener_fabrica(database_url),
        obtener_config(database_url)[0],
        obtener_audio(database_url),
    )


def recargar() -> None:
    """Después de guardar un ajuste: lo que depende de la configuración se arma
    de nuevo en la próxima carga."""
    obtener_config.clear()
    obtener_audio.clear()
    obtener_transcripcion.clear()


def leer_areas() -> dict[str, str]:
    with unidad_de_trabajo(obtener_fabrica(CFG.database_url)) as sesion:
        return RepositorioPersonas(sesion).mapa_areas()


try:
    CFG = obtener_config_entorno()
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
    CFG, LECTURA_AJUSTES, ERROR_AJUSTES = obtener_config(CFG.database_url)
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

if st.session_state.get("authentication_status") is not True:
    _, centro, _ = st.columns([1, 1.2, 1])
    with centro:
        st.markdown("### Calidad · Grúas")
        st.caption("Auditoría de llamadas y chats")
        autenticador.login(
            location="main",
            fields={
                "Form name": "Iniciar sesión",
                "Username": "Usuario",
                "Password": "Contraseña",
                "Login": "Entrar",
            },
        )
        if st.session_state.get("authentication_status") is False:
            st.error("El usuario o la contraseña no son correctos.")
        elif st.session_state.get("authentication_status") is None:
            st.caption("La contraseña se cambia en el servidor (APP_PASSWORD_HASH).")
    if st.session_state.get("authentication_status") is not True:
        st.stop()

autenticador.logout("Cerrar sesión", "sidebar")
st.sidebar.caption("Horas en hora de España (Europe/Madrid).")

if ERROR_AJUSTES:
    st.error(
        "Los ajustes guardados en el panel no son válidos y se está usando solo el "
        f"entorno. Corríjalos en General o en Transcripción.\n\n{ERROR_AJUSTES}"
    )
if LECTURA_AJUSTES.ilegibles:
    st.warning(
        "Estas claves se guardaron con otra llave de cifrado y no se pueden leer; "
        "cárguelas de nuevo en General o en Transcripción: "
        + ", ".join(LECTURA_AJUSTES.ilegibles)
    )

FABRICA = obtener_fabrica(CFG.database_url)
AUDIO = obtener_audio(CFG.database_url)
TRANSCRIPCION = obtener_transcripcion(CFG.database_url)


navegacion = st.navigation(
    navegacion_ui.armar(
        {
            "fabrica": FABRICA,
            "cfg": CFG,
            "audio": AUDIO,
            "transcripcion": TRANSCRIPCION,
            "importacion": IMPORTACION,
            "entorno": dict(os.environ),
            "lectura": LECTURA_AJUSTES,
            "recargar": recargar,
            "leer_areas": leer_areas,
        }
    )
)
navegacion.run()
