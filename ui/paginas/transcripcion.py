"""Página Transcripción: configuración, cola, gasto y comparación de versiones."""

from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta
from decimal import Decimal

import pandas as pd
import streamlit as st
from sqlalchemy.orm import Session, sessionmaker

from config import Config
from panel.ajustes import LecturaAjustes
from panel.asignacion.servicio import ZONA_OPERACION_POR_DEFECTO
from panel.db.base import unidad_de_trabajo
from panel.transcripcion import consultas
from panel.transcripcion.registro import titulo as titulo_proveedor
from panel.transcripcion.servicio import ServicioTranscripcion
from ui.componentes import avisos
from ui.componentes.estilo import ICONOS, numero, usd
from ui.componentes.transcripcion import NO_CONFIGURADA, costo_texto, etiqueta_version, dialogo
from ui.paginas import transcripcion_configuracion

def pagina(
    fabrica: sessionmaker[Session],
    cfg: Config,
    transcripcion: ServicioTranscripcion | None,
    entorno: Mapping[str, str],
    lectura: LecturaAjustes,
    recargar: Callable[[], None],
) -> None:
    st.title("Transcripción")
    avisos.mostrar()
    with unidad_de_trabajo(fabrica) as sesion:
        cola = consultas.estado_cola(sesion)
        gastado = consultas.gasto_del_mes(sesion, datetime.now(ZONA_OPERACION_POR_DEFECTO))
    _resumen(cfg, transcripcion, cola, gastado)

    errores = cola.get("error", 0)
    pestanas = st.tabs(
        [
            ":material/tune: Configuración",
            f":material/queue: Cola{f' · {errores} con error' if errores else ''}",
            ":material/payments: Gasto y precio real",
            ":material/compare_arrows: Comparar versiones",
        ]
    )
    with pestanas[0]:
        transcripcion_configuracion.mostrar(fabrica, cfg, entorno, lectura, recargar)
    with pestanas[1]:
        _cola(fabrica, cfg, transcripcion, cola, gastado)
    with pestanas[2]:
        _gasto(fabrica, cfg)
    with pestanas[3]:
        _comparar(fabrica, transcripcion)


def _resumen(cfg, transcripcion, cola, gastado) -> None:
    columnas = st.columns(4)
    columnas[0].metric("En cola", cola.get("pendiente", 0))
    columnas[1].metric("En proceso", cola.get("en_proceso", 0))
    columnas[2].metric("Con error", cola.get("error", 0))
    tope = cfg.transcripcion_tope_mensual_usd
    columnas[3].metric(
        "Gasto del mes",
        usd(gastado),
        help="Lo que estimó el panel en el mes en curso (hora de España).",
        delta=f"{numero(gastado / tope * 100, 0)} % del tope de {usd(tope)}" if tope else None,
        delta_color="off",
    )
    if transcripcion is None:
        st.warning(NO_CONFIGURADA)
    elif tope and gastado >= tope:
        st.error(
            f"Se alcanzó el tope mensual de {tope} USD: la cola está en pausa hasta el mes "
            "que viene o hasta subir el tope en Configuración."
        )
    elif tope and gastado >= tope * cfg.transcripcion_aviso_porcentaje / 100:
        st.warning(f"El gasto del mes ya pasó el {cfg.transcripcion_aviso_porcentaje} % del tope.")


def _cola(fabrica, cfg: Config, transcripcion, cola, gastado) -> None:
    with unidad_de_trabajo(fabrica) as sesion:
        errores = consultas.trabajos_con_error(sesion)
    st.caption(
        f"La sincronización transcribe hasta {cfg.transcripcion_por_ciclo} por ciclo, cada "
        f"{cfg.sync_intervalo_minutos} minutos. Un pedido que falla se reintenta tres veces "
        f"y después queda aquí. Hechas en total: {cola.get('hecho', 0)}."
    )
    if cfg.transcripcion_auto_min_segundos:
        st.caption(
            f"Las llamadas grabadas nuevas de {cfg.transcripcion_auto_min_segundos} s o más "
            "se agregan solas a la cola."
        )
    if not errores:
        st.success("No hay transcripciones con error.")
        return
    st.markdown(f"**Errores · {len(errores)}**")
    st.dataframe(
        pd.DataFrame(
            [
                {"Llamada": e.llamada, "Fecha": f"{e.inicio:%d/%m/%Y %H:%M}",
                 "Intentos": e.intentos, "Error": e.error}
                for e in errores
            ]
        ),
        hide_index=True,
        use_container_width=True,
    )
    if transcripcion is not None:
        _, costo = transcripcion.costo_de_lote([e.llamada_id for e in errores])
        if st.button(
            f"Reintentar las que fallaron ({len(errores)}) · {costo_texto(costo)}",
            icon=ICONOS["reintentar"],
        ):
            for error in errores:
                transcripcion.reintentar(error.id)
            avisos.dejar(f"{len(errores)} llamadas vuelven a la cola.")
            st.rerun()


def _meses(cantidad: int = 12) -> list[date]:
    hoy = date.today().replace(day=1)
    meses = [hoy]
    for _ in range(cantidad - 1):
        meses.append((meses[-1] - timedelta(days=1)).replace(day=1))
    return meses


def _usd(valor, decimales: int = 2) -> str:
    return numero(valor, decimales)


def _gasto(fabrica, cfg: Config) -> None:
    precios = {(m.proveedor, m.modelo): m.precio_minuto for m in cfg.transcripcion_modelos}
    mes = st.selectbox(
        "Período", _meses(), format_func=lambda m: f"{m:%m/%Y}", key="gasto-mes",
    )
    with unidad_de_trabajo(fabrica) as sesion:
        filas = consultas.precio_real(sesion, mes, precios)

    st.subheader(f"Gasto de {mes:%m/%Y}")
    st.caption("Lo que estimó el panel con el precio configurado al transcribir.")
    if not filas:
        st.caption("No hay transcripciones ni cobros cargados en ese mes.")
    else:
        st.dataframe(
            pd.DataFrame(
                [
                    {"Proveedor": titulo_proveedor(f.proveedor), "Modelo": f.modelo,
                     "Minutos": numero(f.minutos_panel, 1), "USD estimados": _usd(f.usd_estimado)}
                    for f in filas
                ]
            ),
            hide_index=True,
            use_container_width=True,
        )

    st.subheader("Precio real cobrado")
    st.caption(
        "Cargue lo que dice la factura o el panel de uso del proveedor para ese mes. "
        f"Una diferencia de más del {consultas.DESVIO_MAXIMO:.0%} con el precio "
        "configurado se marca como desviada."
    )
    if filas:
        tabla = pd.DataFrame(
            [
                {
                    "Estado": "Desviado" if f.desviado else "",
                    "Modelo": titulo_proveedor(f"{f.proveedor}:{f.modelo}"),
                    "Min cobrados": _usd(f.minutos_cobrados, 0),
                    "Min según el panel": f"{f.minutos_panel:.0f}",
                    "USD cobrados": _usd(f.usd_cobrados),
                    "USD/min real": _usd(f.precio_real, 4),
                    "USD/min configurado": _usd(f.precio_configurado, 4),
                    "Diferencia": "—" if f.diferencia is None else f"{'+' if f.diferencia > 0 else ''}{numero(f.diferencia * 100, 1)} %",
                }
                for f in filas
            ]
        )
        st.dataframe(tabla, hide_index=True, use_container_width=True)
        for fila in filas:
            if fila.desviado:
                diferencia = numero(fila.diferencia * 100, 1)
                st.warning(
                    f"{titulo_proveedor(fila.proveedor + ':' + fila.modelo)} cobra "
                    f"{'+' if fila.diferencia > 0 else ''}{diferencia} % respecto de lo "
                    f"configurado. Actualice el precio a {_usd(fila.precio_real, 4)} USD/min en "
                    "Configuración o revise si el proveedor redondea cada audio al minuto."
                )

    modelos = sorted(
        {(m.proveedor, m.modelo) for m in cfg.transcripcion_modelos} | {(f.proveedor, f.modelo) for f in filas}
    )
    if not modelos:
        return
    with st.form("cargar-cobro"):
        st.markdown(f"**Cargar lo cobrado en {mes:%m/%Y}**")
        uno, dos, tres = st.columns([2, 1, 1])
        elegido = uno.selectbox(
            "Modelo", modelos, format_func=lambda m: titulo_proveedor(f"{m[0]}:{m[1]}")
        )
        minutos = dos.number_input("Minutos cobrados", min_value=0.0, step=1.0)
        usd = tres.number_input("USD cobrados", min_value=0.0, step=0.01, format="%.4f")
        if st.form_submit_button("Guardar el cobro", icon=ICONOS["guardar"]):
            with unidad_de_trabajo(fabrica) as sesion:
                consultas.guardar_cobro(
                    sesion, mes, elegido[0], elegido[1],
                    Decimal(str(minutos)), Decimal(str(usd)),
                )
            avisos.dejar(f"Cobro de {mes:%m/%Y} guardado.")
            st.rerun()


def _comparar(fabrica, transcripcion) -> None:
    with unidad_de_trabajo(fabrica) as sesion:
        comparables = consultas.llamadas_comparables(sesion)
    if not comparables or transcripcion is None:
        st.info(
            "Cuando una llamada tenga dos transcripciones (con «Transcribir de nuevo» y otro "
            "modelo), aquí se ven lado a lado."
        )
        return
    elegida = st.selectbox(
        "Llamada",
        comparables,
        format_func=lambda c: f"{c.llamada} · {c.inicio:%d/%m/%Y %H:%M} · {c.transcripciones} versiones",
    )
    vistas = transcripcion.de_llamada(elegida.llamada_id)
    izquierda, derecha = st.columns(2)
    for columna, vista in zip((izquierda, derecha), vistas[:2]):
        with columna:
            st.caption(etiqueta_version(vista) + f" · {costo_texto(vista.costo_estimado)}")
            dialogo(vista)
