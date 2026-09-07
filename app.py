"""Interfaz web del reporte de conversaciones de Chatwoot."""

import os
from datetime import date, datetime, time, timedelta

import pandas as pd
import streamlit as st
import streamlit_authenticator as stauth

from chatwoot import CacheMensajes, ChatwootError, ClienteChatwoot
from config import ConfigError, cargar_config, ruta_asesores, ruta_cache
from reporte import (
    AREAS_VALIDAS,
    SIN_MAPEAR,
    TZ,
    cargar_asesores,
    escribir_csv,
    generar_filas,
    guardar_asesores,
    nombre_archivo,
)

DIAS_RANGO_AMPLIO = 90

st.set_page_config(page_title="Reporte de Chatwoot", page_icon="📊")


@st.cache_resource
def obtener_config():
    return cargar_config(os.environ)


try:
    CFG = obtener_config()
except ConfigError as error:
    st.error(f"La aplicación no está bien configurada.\n\n{error}")
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
    st.info("Ingrese sus datos para ver el reporte.")
    st.stop()

autenticador.logout("Cerrar sesión", "sidebar")
st.title("Reporte de conversaciones de Chatwoot")

pestana_reporte, pestana_asesores = st.tabs(["Reporte", "Asesores"])

with pestana_reporte:
    hoy = date.today()
    columna_desde, columna_hasta = st.columns(2)
    desde = columna_desde.date_input("Desde", value=hoy.replace(day=1), format="YYYY-MM-DD")
    hasta = columna_hasta.date_input("Hasta", value=hoy, format="YYYY-MM-DD")

    if desde > hasta:
        st.warning("La fecha inicial no puede ser posterior a la final.")
    elif (hasta - desde) > timedelta(days=DIAS_RANGO_AMPLIO):
        st.info(
            f"El rango supera {DIAS_RANGO_AMPLIO} días. La consulta puede tardar "
            "varios minutos la primera vez."
        )

    if st.button("Generar reporte", type="primary", disabled=desde > hasta):
        cliente = ClienteChatwoot(CFG.base_url, CFG.account_id, CFG.api_token)
        mapeo = cargar_asesores(ruta_asesores(CFG))
        barra = st.progress(0.0, text="Consultando conversaciones…")

        def avanzar(hechas: int, total: int) -> None:
            barra.progress(hechas / total, text=f"Procesando {hechas} de {total}…")

        try:
            filas = generar_filas(
                cliente,
                datetime.combine(desde, time.min, tzinfo=TZ),
                datetime.combine(hasta, time.max, tzinfo=TZ),
                mapeo,
                cache=CacheMensajes(ruta_cache(CFG)),
                al_avanzar=avanzar,
            )
        except ChatwootError as error:
            barra.empty()
            st.error(f"No se pudo consultar Chatwoot.\n\n{error}")
            st.stop()

        barra.empty()

        if not filas:
            st.warning("No hay conversaciones en el rango seleccionado.")
            st.stop()

        sin_mapear = sorted(
            {f["email_asesor"] for f in filas if f["area"] == SIN_MAPEAR}
        )
        if sin_mapear:
            st.warning(
                "Estos asesores no tienen área asignada. Agréguelos en la pestaña "
                "Asesores: " + ", ".join(sin_mapear)
            )

        st.success(f"{len(filas)} conversaciones encontradas.")
        st.dataframe(pd.DataFrame(filas), use_container_width=True)
        st.download_button(
            "Descargar CSV",
            data=escribir_csv(filas),
            file_name=nombre_archivo(desde, hasta),
            mime="text/csv",
        )

with pestana_asesores:
    st.caption(
        "Cada asesor pertenece a un área. Los asesores que no estén en esta lista "
        "aparecen como SIN_MAPEAR en el reporte."
    )

    actual = cargar_asesores(ruta_asesores(CFG))
    tabla = pd.DataFrame(
        sorted(actual.items()) or [], columns=["email_asesor", "area"]
    )

    editada = st.data_editor(
        tabla,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "email_asesor": st.column_config.TextColumn("Correo del asesor", required=True),
            "area": st.column_config.SelectboxColumn(
                "Área", options=list(AREAS_VALIDAS), required=True
            ),
        },
        key="editor_asesores",
    )

    limpias = [
        (str(fila.email_asesor).strip().lower(), str(fila.area).strip())
        for fila in editada.itertuples()
        if str(fila.email_asesor).strip()
    ]

    borraria_todo = bool(actual) and not limpias

    if not borraria_todo:
        # Ninguna confirmación vieja debe sobrevivir al episodio de borrado
        # que la motivó: si ya no hay nada que borrar, se apaga.
        st.session_state["confirmar_borrado_asesores"] = False

    confirmado = True
    if borraria_todo:
        st.warning(
            f"La tabla quedó vacía. Si guarda, se borrará el mapeo completo de "
            f"{len(actual)} asesores y todos aparecerán como SIN_MAPEAR en el "
            "próximo reporte."
        )
        confirmado = st.checkbox(
            "Confirmo que quiero borrar todos los asesores.",
            key="confirmar_borrado_asesores",
        )

    if st.button(
        "Guardar cambios", type="primary", disabled=borraria_todo and not confirmado
    ):
        correos = [correo for correo, _ in limpias]
        invalidas = [area for _, area in limpias if area not in AREAS_VALIDAS]

        if len(correos) != len(set(correos)):
            st.error("Hay correos repetidos. Cada asesor debe aparecer una sola vez.")
        elif invalidas:
            st.error(f"El área debe ser {' o '.join(AREAS_VALIDAS)}.")
        else:
            guardar_asesores(ruta_asesores(CFG), dict(limpias))
            st.session_state["confirmar_borrado_asesores"] = False
            st.success(f"Se guardaron {len(limpias)} asesores.")
