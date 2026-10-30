"""Página General: las conexiones con CloudTalk, Chatwoot y el servidor SFTP.

Lo que se guarda aquí pisa a la variable de entorno del mismo nombre (ver
`panel/ajustes.py`). Las claves se guardan cifradas y nunca se muestran
completas: un campo de clave vacío deja la que ya está.
"""

from collections.abc import Callable, Mapping

import streamlit as st
from sqlalchemy.orm import Session, sessionmaker

from chatwoot import ChatwootError, ClienteChatwoot
from cloudtalk import ClienteCloudTalk, CloudTalkError
from config import Config, ruta_audios_locales
from panel.ajustes import LecturaAjustes
from panel.asignacion.servicio import ZONA_OPERACION_POR_DEFECTO
from panel.audio.almacen import AlmacenError, AlmacenLocal, AlmacenSFTP, obtener_huella
from panel.db.base import unidad_de_trabajo
from panel.servicios import consultas
from ui.componentes import avisos
from ui.componentes.ajustes import FormularioAjustes
from ui.componentes.estilo import ICONOS, insignia

ARCHIVO_DE_PRUEBA = "prueba-del-panel/conexion.txt"
ALMACENES = {
    "": "No guardar los audios",
    "sftp": "SFTP del hosting",
    "local": "Carpeta local (solo desarrollo)",
}


def _momento(momento) -> str:
    if momento is None:
        return "nunca"
    return momento.astimezone(ZONA_OPERACION_POR_DEFECTO).strftime("%d/%m/%Y %H:%M")


def mostrar(
    fabrica: sessionmaker[Session],
    cfg: Config,
    entorno: Mapping[str, str],
    lectura: LecturaAjustes,
    recargar: Callable[[], None],
) -> None:
    st.title("Configuración general")
    st.caption(
        "Conexiones con CloudTalk, Chatwoot y el servidor donde se guardan los audios. "
        "Lo que se guarda aquí reemplaza a las variables de entorno del servidor; la "
        "sincronización lo toma en su próximo ciclo. Las claves se guardan cifradas."
    )
    avisos.mostrar()

    formulario = FormularioAjustes(fabrica, entorno, lectura, recargar)
    with unidad_de_trabajo(fabrica) as sesion:
        puntos = {p.fuente: p for p in consultas.estado_sincronizacion(sesion)}
    _estado(cfg, puntos)
    _cloudtalk(formulario, cfg, puntos.get("cloudtalk"))
    _chatwoot(formulario, cfg, puntos.get("chatwoot"))
    _almacen(formulario, cfg)
    _sincronizacion(formulario)
    st.caption(
        "El usuario y la contraseña del panel, DATABASE_URL y la llave de cifrado "
        "(PANEL_CLAVE_CIFRADO o APP_COOKIE_KEY) solo se cambian en el servidor."
    )


def _estado(cfg: Config, puntos) -> None:
    def tarjeta(columna, icono, nombre, configurado, punto):
        with columna.container(border=True):
            if not configurado:
                estado = insignia("Sin configurar", "sin")
            elif punto is not None and punto.ultimo_error:
                estado = insignia("Error en la última corrida", "error")
            elif punto is not None and punto.ultimo_exito:
                estado = insignia(f"Correcta · {_momento(punto.ultimo_exito)}", "ok")
            else:
                estado = insignia("Sin sincronizar todavía", "neutro")
            st.markdown(f"**{nombre}** &nbsp; {estado}", unsafe_allow_html=True)

    columnas = st.columns(3)
    tarjeta(columnas[0], ":material/call:", "CloudTalk", cfg.cloudtalk_configurado, puntos.get("cloudtalk"))
    tarjeta(columnas[1], ":material/chat:", "Chatwoot", cfg.chatwoot_configurado, puntos.get("chatwoot"))
    with columnas[2].container(border=True):
        tipo = cfg.almacen_tipo
        estado = insignia("Sin almacén: los audios no se guardan", "sin") if not tipo else insignia(
            ALMACENES[tipo], "ok"
        )
        st.markdown(f"**Audios** &nbsp; {estado}", unsafe_allow_html=True)


def _pie(punto) -> None:
    if punto is None:
        st.caption("Todavía no se sincronizó.")
        return
    st.caption(f"Última sincronización correcta: {_momento(punto.ultimo_exito)}.")
    if punto.ultimo_error:
        st.error(f"Última corrida ({_momento(punto.ultimo_intento)}): {punto.ultimo_error}")


def _cloudtalk(formulario: FormularioAjustes, cfg: Config, punto) -> None:
    with st.container(border=True):
        izquierda, derecha = st.columns([1, 2], gap="large")
        with izquierda:
            st.subheader(":material/call: CloudTalk")
            st.caption(
                "Trae las llamadas, sus grabaciones y las cuentas de los agentes. La "
                "clave se crea en CloudTalk: Cuenta › Configuración › API."
            )
            _pie(punto)
        with derecha, st.form("general-cloudtalk", border=False):
            uno, dos = st.columns(2)
            with uno:
                id_clave = formulario.texto("ID de la clave de API", "CLOUDTALK_API_KEY_ID")
            with dos:
                secreto = formulario.secreto("Clave secreta", "CLOUDTALK_API_KEY_SECRET", "gen-ct-secreto")
            guardar, probar = _botones()
        secreto = secreto or formulario.valor("CLOUDTALK_API_KEY_SECRET")
        if probar:
            if not (id_clave and secreto):
                st.warning("Complete el ID y la clave secreta para probar.")
            else:
                with st.spinner("Probando la conexión con CloudTalk…"):
                    try:
                        agentes = ClienteCloudTalk(
                            id_clave, secreto, cfg.cloudtalk_base_url, intentos_limite=1
                        ).listar_agentes()
                    except CloudTalkError as error:
                        st.error(f"CloudTalk rechazó la conexión: {error}")
                    else:
                        st.success(f"Conexión correcta: CloudTalk tiene {len(agentes)} agentes.")
        if guardar:
            cambios = {"CLOUDTALK_API_KEY_ID": id_clave}
            if formulario_secreto := st.session_state.get("gen-ct-secreto"):
                cambios["CLOUDTALK_API_KEY_SECRET"] = formulario_secreto
            formulario.guardar(cambios, "Conexión con CloudTalk guardada.")


def _chatwoot(formulario: FormularioAjustes, cfg: Config, punto) -> None:
    with st.container(border=True):
        izquierda, derecha = st.columns([1, 2], gap="large")
        with izquierda:
            st.subheader(":material/chat: Chatwoot")
            st.caption(
                "Trae las conversaciones, sus mensajes y notas internas. El token sale de "
                "Chatwoot: Perfil › Ajustes del perfil › Token de acceso. Use el de un "
                "administrador: con el de un agente solo se ven sus bandejas."
            )
            _pie(punto)
        with derecha, st.form("general-chatwoot", border=False):
            uno, dos = st.columns([2, 1])
            with uno:
                url = formulario.texto(
                    "URL de la instancia", "CHATWOOT_BASE_URL", placeholder="https://chat.miempresa.com"
                )
            with dos:
                cuenta = formulario.texto(
                    "ID de la cuenta", "CHATWOOT_ACCOUNT_ID",
                    placeholder="1",
                )
            token = formulario.secreto("Token de acceso", "CHATWOOT_API_TOKEN", "gen-cw-token")
            relectura = formulario.texto(
                "Releer las conversaciones de los últimos (días)", "CHATWOOT_DIAS_RELECTURA", "14",
            )
            st.caption("El ID de la cuenta es el número de la URL: /app/accounts/**1**/…")
            guardar, probar = _botones()
        token = token or formulario.valor("CHATWOOT_API_TOKEN")
        if probar:
            if not (url and cuenta.isdigit() and token):
                st.warning("Complete la URL, el ID de la cuenta (un número) y el token para probar.")
            else:
                with st.spinner("Probando la conexión con Chatwoot…"):
                    try:
                        bandejas = ClienteChatwoot(url.rstrip("/"), int(cuenta), token).listar_inboxes()
                    except ChatwootError as error:
                        st.error(f"Chatwoot rechazó la conexión: {error}")
                    else:
                        nombres = ", ".join(bandejas.values()) or "ninguna"
                        st.success(f"Conexión correcta. Bandejas visibles: {nombres}.")
        if guardar:
            cambios = {
                "CHATWOOT_BASE_URL": url,
                "CHATWOOT_ACCOUNT_ID": cuenta,
                "CHATWOOT_DIAS_RELECTURA": relectura,
            }
            if nuevo := st.session_state.get("gen-cw-token"):
                cambios["CHATWOOT_API_TOKEN"] = nuevo
            formulario.guardar(cambios, "Conexión con Chatwoot guardada.")


def _traer_huella() -> None:
    """Callback: corre antes de dibujar, así puede escribir en el campo."""
    host = (st.session_state.get("gen-ftp-host") or "").strip()
    puerto = (st.session_state.get("gen-ftp-puerto") or "").strip()
    if not host or not puerto.isdigit():
        st.session_state["gen-ftp-huella-error"] = "Complete el servidor y el puerto primero."
        return
    try:
        st.session_state["gen-ftp-huella"] = obtener_huella(host, int(puerto))
        st.session_state["gen-ftp-huella-nueva"] = True
    except Exception as error:  # noqa: BLE001 — cualquier fallo de red se muestra igual
        st.session_state["gen-ftp-huella-error"] = f"No se pudo leer la huella: {error}"


def _almacen(formulario: FormularioAjustes, cfg: Config) -> None:
    with st.container(border=True):
        izquierda, derecha = st.columns([1, 2], gap="large")
        with izquierda:
            st.subheader(":material/dns: Audios (SFTP)")
            st.caption(
                "Dónde se guarda la copia de cada audio escuchado. El panel lo borra al "
                "cumplir el plazo, salvo que haya un borrador de auditoría."
            )
            st.caption(
                "Se verifica la huella del servidor en cada conexión: sin eso, otro "
                "servidor podría hacerse pasar por el suyo y recibir las grabaciones."
            )
        for clave, ajuste, defecto in (
            ("gen-ftp-host", "FTP_HOST", ""),
            ("gen-ftp-puerto", "FTP_PORT", "22"),
            ("gen-ftp-huella", "SFTP_HUELLA_HOST", ""),
        ):
            st.session_state.setdefault(clave, formulario.valor(ajuste, defecto))
        with derecha, st.form("general-almacen", border=False):
            tipos = list(ALMACENES)
            tipo = st.radio(
                "Guardar los audios en",
                tipos,
                index=tipos.index(formulario.valor("ALMACEN_TIPO")) if formulario.valor("ALMACEN_TIPO") in tipos else 0,
                format_func=ALMACENES.get,
                horizontal=True,
                help=formulario.ayuda("ALMACEN_TIPO"),
            )
            uno, dos = st.columns([3, 1])
            with uno:
                st.text_input("Servidor", key="gen-ftp-host", help=formulario.ayuda("FTP_HOST"))
            with dos:
                st.text_input("Puerto", key="gen-ftp-puerto", help=formulario.ayuda("FTP_PORT"))
            uno, dos = st.columns(2)
            with uno:
                usuario = formulario.texto("Usuario", "FTP_USER", autocomplete="off")
            with dos:
                clave = formulario.secreto("Contraseña", "FTP_PASSWORD", "gen-ftp-clave")
            uno, dos = st.columns(2)
            with uno:
                directorio = formulario.texto("Carpeta remota", "FTP_DIR", "/")
            with dos:
                retencion = formulario.texto(
                    "Conservar los audios (días)", "AUDIO_RETENCION_DIAS", "90"
                )
            st.text_input(
                "Huella del servidor (SHA256)", key="gen-ftp-huella",
                help="La que presenta el servidor SFTP. Compárela con la que muestre su hosting.",
            )
            guardar, probar = _botones()
            st.form_submit_button(
                "Traer la huella del servidor", icon=":material/fingerprint:", on_click=_traer_huella
            )
        if error := st.session_state.pop("gen-ftp-huella-error", None):
            st.error(error)
        if st.session_state.pop("gen-ftp-huella-nueva", False):
            st.warning(
                f"Huella leída: {st.session_state['gen-ftp-huella']}. Compruebe que coincide "
                "con la de su hosting antes de guardar."
            )

        host = st.session_state["gen-ftp-host"].strip()
        puerto = st.session_state["gen-ftp-puerto"].strip()
        huella = st.session_state["gen-ftp-huella"].strip()
        clave = clave or formulario.valor("FTP_PASSWORD")
        if probar:
            _probar_almacen(cfg, tipo, host, puerto, usuario, clave, directorio, huella)
        if guardar:
            cambios = {
                "ALMACEN_TIPO": tipo,
                "FTP_HOST": host,
                "FTP_PORT": puerto,
                "FTP_USER": usuario,
                "FTP_DIR": directorio,
                "SFTP_HUELLA_HOST": huella,
                "AUDIO_RETENCION_DIAS": retencion,
            }
            if nueva := st.session_state.get("gen-ftp-clave"):
                cambios["FTP_PASSWORD"] = nueva
            formulario.guardar(cambios, "Almacén de audios guardado.")


def _probar_almacen(cfg, tipo, host, puerto, usuario, clave, directorio, huella) -> None:
    if tipo == "":
        st.info("Sin almacén no hay nada que probar: los audios se escuchan sin guardarse.")
        return
    if tipo == "sftp":
        faltan = [n for n, v in (("servidor", host), ("usuario", usuario), ("contraseña", clave),
                                 ("huella", huella)) if not v]
        if faltan or not puerto.isdigit():
            st.warning("Para probar faltan: " + ", ".join(faltan or ["un puerto numérico"]) + ".")
            return
        almacen = AlmacenSFTP(host, int(puerto), usuario, clave, directorio or "/", huella)
    else:
        almacen = AlmacenLocal(ruta_audios_locales(cfg))
    with st.spinner("Subiendo, leyendo y borrando un archivo de prueba…"):
        try:
            almacen.subir(ARCHIVO_DE_PRUEBA, b"prueba del panel")
            leido = almacen.bajar(ARCHIVO_DE_PRUEBA)
            almacen.borrar(ARCHIVO_DE_PRUEBA)
        except AlmacenError as error:
            st.error(str(error))
            return
    if leido == b"prueba del panel":
        st.success("Conexión correcta: se pudo escribir, leer y borrar un archivo de prueba.")
    else:
        st.error("Se escribió el archivo de prueba pero al leerlo volvió distinto.")


def _sincronizacion(formulario: FormularioAjustes) -> None:
    with st.container(border=True):
        izquierda, derecha = st.columns([1, 2], gap="large")
        with izquierda:
            st.subheader(":material/sync: Sincronización")
            st.caption(
                "Cada cuánto se traen las llamadas y conversaciones nuevas, y cuánto "
                "historial trae la primera vez."
            )
        with derecha, st.form("general-sync", border=False):
            uno, dos = st.columns(2)
            with uno:
                intervalo = formulario.texto(
                    "Sincronizar cada (minutos)", "SYNC_INTERVALO_MINUTOS", "15"
                )
            with dos:
                dias = formulario.texto(
                    "La primera vez, traer los últimos (días)", "SYNC_DIAS_INICIALES", "30"
                )
            guardar = st.form_submit_button("Guardar", type="primary", icon=ICONOS["guardar"])
        if guardar:
            formulario.guardar(
                {"SYNC_INTERVALO_MINUTOS": intervalo, "SYNC_DIAS_INICIALES": dias},
                "Sincronización guardada. Vale desde el próximo ciclo.",
            )


def _botones() -> tuple[bool, bool]:
    uno, dos = st.columns([1, 2.2])
    with uno:
        guardar = st.form_submit_button("Guardar", type="primary", icon=ICONOS["guardar"])
    with dos:
        probar = st.form_submit_button("Probar con estos datos", icon=ICONOS["probar"])
    return guardar, probar
