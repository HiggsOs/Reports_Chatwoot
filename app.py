"""Interfaz web de los reportes de Chatwoot y de transcripciones de Ringover y
CloudTalk."""

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
import reporte_cloudtalk
import reporte_ringover
from cloudtalk import ClienteCloudTalk, CloudTalkError
from ringover import ClienteRingover, RingoverError

DIAS_RANGO_AMPLIO = 90

st.set_page_config(page_title="Reportes", page_icon="📊")


@st.cache_resource
def obtener_config():
    return cargar_config(os.environ)


@st.cache_data(ttl=3600, show_spinner="Cargando agentes, grupos y números de CloudTalk…")
def catalogo_cloudtalk(key_id: str, key_secret: str, base_url: str) -> dict:
    """Opciones de los filtros. Cambian poco, así que se guardan una hora; un
    error no se guarda y se reintenta en la próxima carga de la página."""
    # Sin paciencia ante el límite: es mejor mostrar la pestaña sin opciones
    # que dejarla congelada varios minutos.
    cliente = ClienteCloudTalk(key_id, key_secret, base_url, intentos_limite=1)
    return {
        "agentes": reporte_cloudtalk.opciones_agentes(cliente.listar_agentes()),
        "grupos": reporte_cloudtalk.opciones_grupos(cliente.listar_grupos()),
        "numeros": reporte_cloudtalk.opciones_numeros(cliente.listar_numeros()),
    }


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
st.title("Reportes")

(
    pestana_reporte,
    pestana_transcripciones,
    pestana_cloudtalk,
    pestana_asesores,
) = st.tabs(["Reporte", "Transcripciones", "CloudTalk", "Asesores"])

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

with pestana_transcripciones:
    st.caption(
        "Transcripciones de las llamadas de Ringover en el rango elegido, una "
        "fila por llamada."
    )

    if not CFG.ringover_token:
        st.info(
            "Falta configurar la variable de entorno RINGOVER_API_TOKEN para "
            "consultar las transcripciones."
        )
    else:
        hoy_llamadas = date.today()
        columna_desde_ll, columna_hasta_ll = st.columns(2)
        desde_ll = columna_desde_ll.date_input(
            "Desde",
            value=hoy_llamadas.replace(day=1),
            format="YYYY-MM-DD",
            key="desde_transcripciones",
        )
        hasta_ll = columna_hasta_ll.date_input(
            "Hasta",
            value=hoy_llamadas,
            format="YYYY-MM-DD",
            key="hasta_transcripciones",
        )

        if desde_ll > hasta_ll:
            st.warning("La fecha inicial no puede ser posterior a la final.")

        if st.button(
            "Generar reporte de transcripciones",
            type="primary",
            disabled=desde_ll > hasta_ll,
            key="generar_transcripciones",
        ):
            cliente_ringover = ClienteRingover(
                CFG.ringover_token, CFG.ringover_base_url
            )
            aviso = st.empty()
            aviso.info("Consultando transcripciones…")

            def contar(traidas: int) -> None:
                aviso.info(f"{traidas} transcripciones descargadas…")

            advertencias: list[str] = []

            try:
                filas_ll = reporte_ringover.generar_filas(
                    cliente_ringover,
                    datetime.combine(desde_ll, time.min, tzinfo=TZ),
                    datetime.combine(hasta_ll, time.max, tzinfo=TZ),
                    al_avanzar=contar,
                    al_advertir=advertencias.append,
                )
            except RingoverError as error:
                aviso.empty()
                st.error(f"No se pudo consultar Ringover.\n\n{error}")
                st.stop()

            aviso.empty()

            for advertencia in advertencias:
                st.warning(advertencia)

            if not filas_ll:
                st.warning("No hay transcripciones en el rango seleccionado.")
                st.stop()

            st.success(f"{len(filas_ll)} transcripciones encontradas.")
            st.dataframe(pd.DataFrame(filas_ll), use_container_width=True)
            st.download_button(
                "Descargar CSV",
                data=reporte_ringover.escribir_csv(filas_ll),
                file_name=reporte_ringover.nombre_archivo(desde_ll, hasta_ll),
                mime="text/csv",
                key="descargar_transcripciones",
            )

with pestana_cloudtalk:
    st.caption(
        "Transcripciones de las llamadas contestadas de CloudTalk en el rango "
        "elegido, una fila por llamada."
    )

    if not CFG.cloudtalk_configurado:
        st.info(
            "Falta configurar las variables de entorno CLOUDTALK_API_KEY_ID y "
            "CLOUDTALK_API_KEY_SECRET para consultar las transcripciones."
        )
    else:
        hoy_ct = date.today()
        columna_desde_ct, columna_hasta_ct = st.columns(2)
        desde_ct = columna_desde_ct.date_input(
            "Desde",
            value=hoy_ct.replace(day=1),
            format="YYYY-MM-DD",
            key="desde_cloudtalk",
        )
        hasta_ct = columna_hasta_ct.date_input(
            "Hasta",
            value=hoy_ct,
            format="YYYY-MM-DD",
            key="hasta_cloudtalk",
        )

        if desde_ct > hasta_ct:
            st.warning("La fecha inicial no puede ser posterior a la final.")

        try:
            catalogo = catalogo_cloudtalk(
                CFG.cloudtalk_key_id, CFG.cloudtalk_key_secret, CFG.cloudtalk_base_url
            )
        except CloudTalkError as error:
            catalogo = {"agentes": {}, "grupos": [], "numeros": {}}
            st.warning(
                "No se pudieron cargar los agentes, grupos y números para los "
                f"filtros; el reporte funciona igual sin ellos.\n\n{error}"
            )

        with st.expander("Filtros", expanded=False):
            st.caption(
                "Se aplican antes de descargar las transcripciones, así que "
                "también acortan la espera. Un filtro vacío no descarta nada."
            )
            columna_a, columna_b = st.columns(2)
            agentes_ct = columna_a.multiselect(
                "Agentes",
                options=list(catalogo["agentes"]),
                format_func=lambda i: catalogo["agentes"].get(i, i),
                key="agentes_cloudtalk",
            )
            grupos_ct = columna_b.multiselect(
                "Grupos",
                options=catalogo["grupos"],
                key="grupos_cloudtalk",
                help="Llamadas atendidas por agentes de estos grupos.",
            )
            numeros_ct = columna_a.multiselect(
                "Números de la empresa",
                options=list(catalogo["numeros"]),
                format_func=lambda i: catalogo["numeros"].get(i, i),
                key="numeros_cloudtalk",
                help="Línea por la que entró o salió la llamada.",
            )
            direcciones_ct = columna_b.multiselect(
                "Dirección (inbound / outbound)",
                options=list(reporte_cloudtalk.DIRECCIONES),
                format_func=reporte_cloudtalk.ETIQUETAS_DIRECCION.get,
                key="direcciones_cloudtalk",
                help="Entrante: el cliente llamó. Saliente: el agente llamó.",
            )
            duracion_ct = columna_a.number_input(
                "Duración mínima de la conversación (segundos)",
                min_value=0,
                value=0,
                step=10,
                key="duracion_cloudtalk",
                help="Descarta llamadas cortas, como buzones o cuelgues.",
            )
            contacto_ct = columna_b.text_input(
                "Cliente",
                key="contacto_cloudtalk",
                placeholder="Nombre, empresa o teléfono",
            )
            solo_transcritas_ct = st.checkbox(
                "Solo llamadas con transcripción",
                key="solo_transcritas_cloudtalk",
            )

        filtros_ct = reporte_cloudtalk.Filtros(
            agentes=frozenset(agentes_ct),
            grupos=frozenset(grupos_ct),
            numeros=frozenset(numeros_ct),
            direcciones=frozenset(direcciones_ct),
            duracion_minima=int(duracion_ct),
            contacto=contacto_ct,
            solo_con_transcripcion=solo_transcritas_ct,
        )

        if st.button(
            "Generar reporte de CloudTalk",
            type="primary",
            disabled=desde_ct > hasta_ct,
            key="generar_cloudtalk",
        ):
            barra_ct = st.progress(0.0, text="Consultando llamadas…")
            pausa_ct = st.empty()

            def avanzar_ct(hechas: int, total: int, restante: float) -> None:
                pausa_ct.empty()
                texto = f"Transcripción {hechas} de {total}"
                espera = reporte_cloudtalk.formatear_espera(restante)
                if espera:
                    texto += f" · faltan {espera}"
                barra_ct.progress(hechas / total, text=texto + "…")

            def esperar_ct(segundos: float) -> None:
                pausa_ct.info(
                    "CloudTalk pidió bajar el ritmo de consultas. Se reanuda "
                    f"solo en {segundos:.0f} s; lo ya descargado queda guardado."
                )

            cliente_cloudtalk = ClienteCloudTalk(
                CFG.cloudtalk_key_id,
                CFG.cloudtalk_key_secret,
                CFG.cloudtalk_base_url,
                CFG.cloudtalk_ai_base_url,
                al_esperar=esperar_ct,
            )

            try:
                filas_ct = reporte_cloudtalk.generar_filas(
                    cliente_cloudtalk,
                    datetime.combine(desde_ct, time.min, tzinfo=TZ),
                    datetime.combine(hasta_ct, time.max, tzinfo=TZ),
                    cache=CacheMensajes(ruta_cache(CFG) / "cloudtalk"),
                    al_avanzar=avanzar_ct,
                    filtros=filtros_ct,
                )
            except CloudTalkError as error:
                barra_ct.empty()
                pausa_ct.empty()
                st.error(f"No se pudo consultar CloudTalk.\n\n{error}")
                st.stop()

            barra_ct.empty()
            pausa_ct.empty()

            if not filas_ct:
                st.warning(
                    "No hay llamadas contestadas en el rango seleccionado que "
                    "cumplan los filtros."
                )
                st.stop()

            transcritas = sum(
                fila["estado"] == reporte_cloudtalk.TRANSCRITA for fila in filas_ct
            )
            st.success(
                f"{len(filas_ct)} llamadas encontradas, {transcritas} con "
                "transcripción."
            )
            st.dataframe(pd.DataFrame(filas_ct), use_container_width=True)
            st.download_button(
                "Descargar CSV",
                data=reporte_cloudtalk.escribir_csv(filas_ct),
                file_name=reporte_cloudtalk.nombre_archivo(desde_ct, hasta_ct),
                mime="text/csv",
                key="descargar_cloudtalk",
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
            st.success(f"Se guardaron {len(limpias)} asesores.")
