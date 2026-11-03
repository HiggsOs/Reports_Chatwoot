"""Pestaña Configuración de la página Transcripción (ver ui/paginas/transcripcion.py).

Se carga aquí lo que antes iba en variables de entorno: la clave de cada
proveedor, los modelos que se pueden elegir con su precio, el modelo principal
y el de respaldo, y los límites de gasto. Se guarda como ajustes del panel
(ver `panel/ajustes.py`).
"""

import json
from collections.abc import Callable, Mapping
from decimal import Decimal

import pandas as pd
import streamlit as st

from config import Config, ModeloTranscripcion
from panel.ajustes import LecturaAjustes, enmascarar
from panel.transcripcion import registro
from panel.transcripcion.base import TranscripcionError
from panel.transcripcion.estrategias.openai import MODELO_POR_DEFECTO
from ui.componentes.ajustes import ORIGEN, FormularioAjustes
from ui.componentes.estilo import ICONOS, insignia, usd

COBROS = {"segundo": "por segundo", "minuto": "redondea al minuto"}
AUTOMATICA = {0: "No: solo a mano o en lote", 30: "Sí, las de 30 s o más", 60: "Sí, las de 60 s o más", 1: "Sí, todas"}
CANALES = {"izquierdo": "Izquierdo (1)", "derecho": "Derecho (2)"}


def _proveedores() -> list[str]:
    # La estrategia «falsa» es para pruebas: no se ofrece.
    return [n for n in registro.nombres() if n != "falsa"]


def que_devuelve(proveedor: str, modelo: str) -> str:
    capacidades = registro.modelos_conocidos(proveedor).get(modelo)
    if capacidades is None:
        return "desconocido: solo texto"
    if capacidades.diarizacion:
        return "separa hablantes, con tiempos"
    return "con tiempos" if capacidades.marcas_de_tiempo else "solo texto"


def _modelos_iniciales(cfg: Config, efectivo: Mapping[str, str]) -> list[ModeloTranscripcion]:
    if cfg.transcripcion_modelos:
        return list(cfg.transcripcion_modelos)
    # Primera vez: el modelo del entorno con su precio, y los demás conocidos apagados.
    actual = (efectivo.get("OPENAI_MODELO_TRANSCRIPCION") or MODELO_POR_DEFECTO).strip()
    precio = (efectivo.get("OPENAI_PRECIO_MINUTO") or "").strip().replace(",", ".") or None
    modelos = [ModeloTranscripcion(proveedor="openai", modelo=actual, precio_minuto=precio)]
    for nombre in registro.modelos_conocidos("openai"):
        if nombre != actual:
            modelos.append(ModeloTranscripcion(proveedor="openai", modelo=nombre, activo=False))
    return modelos


def mostrar(
    fabrica,
    cfg: Config,
    entorno: Mapping[str, str],
    lectura: LecturaAjustes,
    recargar: Callable[[], None],
) -> None:
    formulario = FormularioAjustes(fabrica, entorno, lectura, recargar)
    efectivo, origen, guardar = formulario.efectivo, formulario.origen, formulario.guardar

    _claves(efectivo, origen, guardar)
    modelos = _tabla_modelos(cfg, efectivo)
    _uso_y_limites(cfg, efectivo, modelos, guardar)


def _claves(efectivo, origen, guardar) -> None:
    st.subheader("Proveedores y claves de API")
    st.caption(
        "Las claves se guardan cifradas y nunca se vuelven a mostrar completas. Si una "
        "clave también está en el entorno del servidor, manda la del panel."
    )
    columnas = st.columns(max(len(_proveedores()), 1))
    for columna, proveedor in zip(columnas, _proveedores()):
        variable = registro.variable_clave(proveedor)
        actual = (efectivo.get(variable) or "").strip() if variable else ""
        with columna.container(border=True):
            estado = insignia("Con clave", "ok") if actual else insignia("Sin clave", "sin")
            st.markdown(f"**{registro.titulo(proveedor)}** &nbsp; {estado}", unsafe_allow_html=True)
            if variable is None:
                st.caption("Este proveedor no usa clave de API.")
                continue
            marcador = (
                f"Guardada ({ORIGEN[origen[variable]]}): {enmascarar(actual)}"
                if actual and variable in origen
                else "Pegue la clave"
            )
            nueva = st.text_input(
                "Clave de API", type="password", placeholder=marcador,
                key=f"clave-{proveedor}", autocomplete="off",
            )
            uno, dos = st.columns(2)
            if uno.button("Guardar", key=f"guardar-clave-{proveedor}", type="primary",
                          icon=ICONOS["guardar"], disabled=not nueva):
                guardar({variable: nueva.strip()}, f"Clave de {registro.titulo(proveedor)} guardada.")
            if dos.button("Probar conexión", key=f"probar-clave-{proveedor}", icon=ICONOS["probar"]):
                valores = {**efectivo, variable: (nueva or actual).strip()}
                with st.spinner("Probando la clave…"):
                    try:
                        st.success(registro.probar_clave(proveedor, valores))
                    except TranscripcionError as error:
                        st.error(str(error))
            if actual and origen.get(variable) == "panel" and st.button(
                "Quitar la clave del panel", key=f"quitar-clave-{proveedor}",
                help="Vuelve a valer la del entorno del servidor, si hay una.",
            ):
                guardar({variable: None}, f"Clave de {registro.titulo(proveedor)} quitada del panel.")


def _tabla_modelos(cfg: Config, efectivo) -> list[ModeloTranscripcion] | None:
    st.subheader("Modelos y precios")
    st.caption(
        "Copie el precio de la tarifa del proveedor (USD por minuto). Con él se calcula "
        "el costo estimado que se muestra antes de transcribir. Un modelo apagado no se "
        "ofrece, pero sus transcripciones viejas se siguen leyendo."
    )
    iniciales = _modelos_iniciales(cfg, efectivo)
    tabla = pd.DataFrame(
        [
            {
                "Activo": m.activo,
                "Proveedor": m.proveedor,
                "Modelo": m.modelo,
                "USD/min": float(m.precio_minuto) if m.precio_minuto is not None else float("nan"),
                "Cobro": COBROS[m.redondeo],
                "Qué devuelve": que_devuelve(m.proveedor, m.modelo),
                "Llamada de 5 min": (
                    usd(m.precio_minuto * 5, 3) if m.precio_minuto is not None else "sin precio"
                ),
            }
            for m in iniciales
        ]
    )
    editada = st.data_editor(
        tabla,
        num_rows="dynamic",
        hide_index=True,
        use_container_width=True,
        key="modelos-transcripcion",
        column_config={
            "Activo": st.column_config.CheckboxColumn("Activo", default=True),
            "Proveedor": st.column_config.SelectboxColumn(
                "Proveedor", options=_proveedores(), required=True, default="openai"
            ),
            "Modelo": st.column_config.TextColumn(
                "Modelo (id exacto)", required=True,
                help="Conocidos: " + ", ".join(registro.modelos_conocidos("openai")),
            ),
            "USD/min": st.column_config.NumberColumn("USD/min", min_value=0.0, step=0.0001, format="%.4f"),
            "Cobro": st.column_config.SelectboxColumn(
                "Mínimo cobrado", options=list(COBROS.values()), default=COBROS["segundo"],
                help="Algunos proveedores cobran cada audio redondeado al minuto siguiente.",
            ),
            "Qué devuelve": st.column_config.TextColumn("Qué devuelve", disabled=True),
            "Llamada de 5 min": st.column_config.TextColumn("Llamada de 5 min", disabled=True),
        },
    )

    modelos, errores = [], []
    cobro = {v: k for k, v in COBROS.items()}
    for numero, fila in enumerate(editada.to_dict("records"), start=1):
        nombre = "" if pd.isna(fila.get("Modelo")) else str(fila["Modelo"]).strip()
        if not nombre:
            continue
        precio = fila.get("USD/min")
        try:
            modelos.append(
                ModeloTranscripcion(
                    proveedor=fila.get("Proveedor") or "openai",
                    modelo=nombre,
                    precio_minuto=None if precio is None or pd.isna(precio) else Decimal(str(precio)),
                    redondeo=cobro.get(fila.get("Cobro"), "segundo"),
                    activo=bool(fila.get("Activo")),
                )
            )
        except ValueError as error:
            errores.append(f"Fila {numero}: {error}")
    claves = [m.clave for m in modelos]
    if len(claves) != len(set(claves)):
        errores.append("Hay un modelo repetido.")
    for error in errores:
        st.error(error)
    return None if errores else modelos


def _uso_y_limites(cfg: Config, efectivo, modelos, guardar) -> None:
    st.subheader("Cómo se transcribe")
    activos = [m.clave for m in modelos or [] if m.activo]
    if not activos:
        st.warning("Active al menos un modelo para poder elegir el principal.")
    actual = registro.resolver(cfg.transcripcion_proveedor, dict.fromkeys(activos))
    respaldo_actual = [
        c for c in (registro.resolver(n, dict.fromkeys(activos)) for n in cfg.transcripcion_respaldo) if c
    ]
    uno, dos = st.columns(2)
    principal = uno.selectbox(
        "Modelo principal", activos, index=activos.index(actual) if actual in activos else 0,
        format_func=registro.titulo, key="tx-principal",
        help="Solo aparecen los modelos activos de la tabla.",
    ) if activos else None
    respaldo = dos.multiselect(
        "Respaldo (si falla el principal)", [c for c in activos if c != principal],
        default=[c for c in respaldo_actual if c != principal], format_func=registro.titulo,
        key="tx-respaldo", placeholder="Ninguno",
    )
    uno, dos, tres = st.columns(3)
    idioma = uno.text_input("Idioma", value=cfg.transcripcion_idioma, key="tx-idioma",
                            help="Código ISO: es, en, pt…")
    canales = list(CANALES)
    canal = dos.radio(
        "Canal del agente en grabaciones estéreo", canales, index=canales.index(cfg.cloudtalk_canal_agente),
        format_func=CANALES.get, horizontal=True, key="tx-canal",
        help="Con estéreo, cada canal es una persona y no hace falta separar hablantes.",
    )
    opciones_auto = list(AUTOMATICA)
    if cfg.transcripcion_auto_min_segundos not in opciones_auto:
        opciones_auto.append(cfg.transcripcion_auto_min_segundos)
    automatica = tres.selectbox(
        "Transcribir llamadas nuevas", opciones_auto,
        index=opciones_auto.index(cfg.transcripcion_auto_min_segundos),
        format_func=lambda s: AUTOMATICA.get(s, f"Sí, las de {s} s o más"), key="tx-auto",
    )
    vocabulario = st.text_input(
        "Vocabulario (separado por comas)", value=", ".join(cfg.transcripcion_vocabulario),
        key="tx-vocabulario", help="Nombres propios, marcas, productos: ayudan a escribirlos bien.",
    )

    st.subheader("Límites de gasto")
    uno, dos, tres = st.columns(3)
    tope = uno.number_input(
        "Tope mensual (USD)", min_value=0.0, step=5.0,
        value=float(cfg.transcripcion_tope_mensual_usd or 0), key="tx-tope",
        help="Al llegar, la cola se pausa hasta el mes siguiente. 0: sin tope.",
    )
    aviso = dos.slider(
        "Avisar al llegar al (% del tope)", min_value=10, max_value=100, step=5,
        value=min(cfg.transcripcion_aviso_porcentaje, 100), key="tx-aviso",
    )
    confirmar = tres.number_input(
        "Pedir confirmación en lotes de más de (USD)", min_value=0.0, step=1.0,
        value=float(cfg.transcripcion_confirmar_lote_usd or 0), key="tx-confirmar",
        help="0: nunca se pide confirmación.",
    )

    if st.button("Guardar la configuración de transcripción", type="primary",
                 icon=ICONOS["guardar"], disabled=modelos is None):
        cambios = {
            "TRANSCRIPCION_MODELOS": json.dumps(
                [m.model_dump(mode="json") for m in modelos], ensure_ascii=False
            ),
            "TRANSCRIPCION_PROVEEDOR": principal or "",
            "TRANSCRIPCION_RESPALDO": ",".join(respaldo),
            "TRANSCRIPCION_IDIOMA": idioma.strip(),
            "TRANSCRIPCION_VOCABULARIO": ",".join(p.strip() for p in vocabulario.split(",") if p.strip()),
            "CLOUDTALK_CANAL_AGENTE": canal,
            "TRANSCRIPCION_AUTO_MIN_SEGUNDOS": str(automatica),
            "TRANSCRIPCION_TOPE_MENSUAL_USD": f"{tope:g}" if tope else "",
            "TRANSCRIPCION_AVISO_PORCENTAJE": str(aviso),
            "TRANSCRIPCION_CONFIRMAR_LOTE_USD": f"{confirmar:g}" if confirmar else "",
        }
        guardar(cambios, "Configuración de transcripción guardada. La cola la usa desde su próximo ciclo.")
