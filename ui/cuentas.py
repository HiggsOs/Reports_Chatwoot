"""Pestaña Cuentas: cuentas de CloudTalk y Chatwoot y sus reglas de asignación."""

from datetime import date, datetime, timezone

import pandas as pd
import streamlit as st
from sqlalchemy.orm import Session, sessionmaker

from chatwoot import ChatwootError, ClienteChatwoot
from cloudtalk import ClienteCloudTalk, CloudTalkError
from config import Config
from panel.asignacion import registro
from panel.asignacion.base import DIAS_SEMANA
from panel.asignacion.servicio import (
    DESDE_SIEMPRE,
    ReglaInvalida,
    ServicioAsignacion,
    ocupacion_semanal,
)
from panel.db.base import unidad_de_trabajo
from panel.db.repositorios.cuentas import RepositorioCuentas, RepositorioReglas
from panel.db.repositorios.personas import RepositorioPersonas
from panel.fuentes.cuentas import cuentas_de_chatwoot, cuentas_de_cloudtalk
from panel.servicios.cuentas import ServicioCuentas
from panel.servicios.interacciones import ResumenReasignacion, ServicioInteracciones
from ui import formularios_asignacion

NOMBRES_PLATAFORMA = {"cloudtalk": "CloudTalk", "chatwoot": "Chatwoot"}
CLAVE_AVISO = "aviso_cuentas"
SIN_ASIGNAR = "Sin asignar"
# Colores suaves que se leen bien con texto oscuro; se repiten si hay más personas.
COLORES = ("#cfe3ff", "#ffe0b8", "#d4f0d0", "#f3d1f4", "#fff3b0", "#d9d9f7")


def _actualizar_cuentas(fabrica: sessionmaker[Session], cfg: Config) -> None:
    mensajes, errores = [], []
    fuentes = [
        ("chatwoot", lambda: cuentas_de_chatwoot(
            ClienteChatwoot(cfg.base_url, cfg.account_id, cfg.api_token).listar_agentes()
        )),
    ]
    if cfg.cloudtalk_configurado:
        fuentes.insert(0, ("cloudtalk", lambda: cuentas_de_cloudtalk(
            ClienteCloudTalk(
                cfg.cloudtalk_key_id, cfg.cloudtalk_key_secret, cfg.cloudtalk_base_url,
                intentos_limite=1,
            ).listar_agentes()
        )))

    for plataforma, traer in fuentes:
        nombre = NOMBRES_PLATAFORMA[plataforma]
        try:
            externas = traer()
        except (ChatwootError, CloudTalkError) as error:
            errores.append(f"{nombre}: {error}")
            continue
        with unidad_de_trabajo(fabrica) as sesion:
            r = ServicioCuentas(sesion).actualizar(plataforma, externas)
        mensajes.append(
            f"{nombre}: {len(externas)} cuentas ({r.nuevas} nuevas, {r.actualizadas} "
            f"con cambios, {r.reactivadas} reactivadas, {r.desactivadas} desactivadas"
            + (f", {r.reglas_automaticas} reglas creadas por correo" if r.reglas_automaticas else "")
            + ")."
        )
    if mensajes:
        st.success("\n\n".join(mensajes))
    for error in errores:
        st.error(error)
    if not cfg.cloudtalk_configurado:
        st.info("CloudTalk no está configurado: solo se actualizaron las cuentas de Chatwoot.")


def _tabla_cuentas(sesion: Session) -> tuple[pd.DataFrame, dict[int, str]]:
    servicio = ServicioAsignacion(sesion)
    reglas = RepositorioReglas(sesion)
    ahora = datetime.now(timezone.utc)
    filas, etiquetas = [], {}
    for cuenta in RepositorioCuentas(sesion).listar():
        regla = reglas.vigente(cuenta.id, ahora)
        if regla is None:
            estrategia, detalle, aviso = "—", "", "Sin regla: sus interacciones quedan sin asignar"
        else:
            estrategia = registro.obtener(regla.estrategia).titulo
            detalle = " · ".join(servicio.describir(regla))
            inactivas = servicio.personas_inactivas(regla)
            aviso = f"Nombra asesores inactivos: {', '.join(inactivas)}" if inactivas else ""
        plataforma = NOMBRES_PLATAFORMA[cuenta.plataforma]
        etiquetas[cuenta.id] = f"{plataforma} · {cuenta.nombre}"
        filas.append(
            {
                "Plataforma": plataforma,
                "Cuenta": cuenta.nombre,
                "Correo": cuenta.correo or "",
                "Regla vigente": estrategia,
                "Detalle": detalle,
                "Aviso": aviso,
            }
        )
    return pd.DataFrame(filas), etiquetas


def _horario_semanal(estrategia, parametros, nombres: dict[int, str]) -> None:
    celdas = ocupacion_semanal(estrategia, parametros, paso_minutos=30)
    tabla: dict[str, dict[str, str]] = {}
    for celda in celdas:
        persona = celda.resultado.persona_id
        valor = nombres.get(persona, "?") if persona is not None else SIN_ASIGNAR
        tabla.setdefault(f"{celda.hora:%H:%M}", {})[DIAS_SEMANA[celda.dia].capitalize()] = valor
    # Los tramos seguidos con el mismo reparto en todos los días se juntan en
    # una fila («08:00–14:00»), para que el horario se lea de un vistazo.
    horas = list(tabla)
    filas, etiquetas = [], []
    for i, hora in enumerate(horas):
        if filas and tabla[hora] == filas[-1]:
            continue
        siguiente = next(
            (h for h in horas[i + 1 :] if tabla[h] != tabla[hora]), "24:00"
        )
        filas.append(tabla[hora])
        etiquetas.append(f"{hora}–{siguiente}")
    marco = pd.DataFrame(filas, index=etiquetas)

    colores = {
        nombre: COLORES[i % len(COLORES)]
        for i, nombre in enumerate(sorted(set(marco.stack()) - {SIN_ASIGNAR}))
    }
    colores[SIN_ASIGNAR] = "#eeeeee"
    estilo = marco.style.map(
        lambda valor: f"background-color: {colores.get(valor, '#ffffff')}; color: #1f1f1f"
    )
    st.dataframe(estilo, use_container_width=True)


def _historial(sesion: Session, cuenta_id: int) -> None:
    servicio = ServicioAsignacion(sesion)
    filas = []
    for regla in RepositorioReglas(sesion).historial(cuenta_id):
        sin_vigencia = regla.vigente_hasta == regla.vigente_desde
        filas.append(
            {
                "Estrategia": registro.obtener(regla.estrategia).titulo,
                "Desde": servicio.formatear_fecha(regla.vigente_desde),
                "Hasta": (
                    "corregida, nunca rigió"
                    if sin_vigencia
                    else servicio.formatear_fecha(regla.vigente_hasta)
                    if regla.vigente_hasta
                    else "vigente"
                ),
                "Detalle": " · ".join(servicio.describir(regla)),
            }
        )
    if filas:
        st.dataframe(pd.DataFrame(filas), hide_index=True, use_container_width=True)
    else:
        st.caption("Esta cuenta todavía no tiene reglas.")


def _nueva_regla(fabrica: sessionmaker[Session], cuenta_id: int) -> None:
    with unidad_de_trabajo(fabrica) as sesion:
        personas = RepositorioPersonas(sesion).listar()
        ultima = RepositorioReglas(sesion).ultima(cuenta_id)
        ultima_estrategia = ultima.estrategia if ultima else None
        ultimos_parametros = dict(ultima.parametros) if ultima else None
        ultima_desde = ultima.vigente_desde if ultima else None

    if len(personas) < 1:
        st.warning("Primero cargue los asesores en la página Asesores.")
        return

    estrategias = registro.disponibles()
    nombres = [e.nombre for e in estrategias]
    elegida = st.radio(
        "Estrategia",
        nombres,
        index=nombres.index(ultima_estrategia) if ultima_estrategia in nombres else 0,
        format_func=lambda nombre: registro.obtener(nombre).titulo,
        horizontal=True,
        key=f"estrategia-{cuenta_id}",
    )
    st.caption(registro.obtener(elegida).descripcion)

    formulario = formularios_asignacion.obtener(elegida)
    if formulario is None:
        st.error("Esta estrategia todavía no tiene formulario en el panel.")
        return
    parametros = formulario(
        personas,
        ultimos_parametros if elegida == ultima_estrategia else None,
        f"regla-{cuenta_id}-{elegida}",
    )

    desde_siempre = False
    if ultima is None:
        desde_siempre = st.checkbox(
            "Vale desde siempre (también para las interacciones anteriores)",
            value=True,
            key=f"siempre-{cuenta_id}",
        )
    dia = None
    if not desde_siempre:
        dia = st.date_input(
            "Vigente desde (00:00, hora de España)",
            value=date.today(),
            format="DD/MM/YYYY",
            key=f"desde-{cuenta_id}",
        )
        if ultima_desde is not None:
            st.caption(
                "Al guardar, la regla actual deja de regir en esa fecha. Si es la misma "
                "fecha en que empezó, queda como corregida."
            )

    if isinstance(parametros, list):
        for error in parametros:
            st.warning(error)

    incompleto = isinstance(parametros, list)
    izquierda, derecha = st.columns(2)
    previa = izquierda.button("Ver vista previa", disabled=incompleto, key=f"previa-{cuenta_id}")
    guardar = derecha.button(
        "Guardar regla", type="primary", disabled=incompleto, key=f"guardar-{cuenta_id}"
    )
    if not (previa or guardar):
        return

    try:
        with unidad_de_trabajo(fabrica) as sesion:
            servicio = ServicioInteracciones(sesion)
            vigente_desde = (
                DESDE_SIEMPRE if desde_siempre else servicio.asignacion.inicio_del_dia(dia)
            )
            if previa:
                resumen = servicio.simular_regla(cuenta_id, elegida, parametros, vigente_desde)
            else:
                servicio.asignacion.crear_regla(cuenta_id, elegida, parametros, vigente_desde)
                resumen = servicio.reasignar_cuenta(cuenta_id, vigente_desde)
    except ReglaInvalida as error:
        for mensaje in error.errores:
            st.error(mensaje)
        return

    detalle = _describir_reasignacion(resumen)
    if previa:
        st.info("Si guarda esta regla: " + detalle)
        return
    st.session_state[CLAVE_AVISO] = "Regla guardada. " + detalle[0].upper() + detalle[1:]
    st.rerun()


def _describir_reasignacion(resumen: ResumenReasignacion) -> str:
    if not resumen.revisadas:
        return "Todavía no hay llamadas ni conversaciones de esta cuenta en ese período."
    reparto = ", ".join(f"{nombre}: {cantidad}" for nombre, cantidad in resumen.por_persona.items())
    return (
        f"de las {resumen.revisadas} interacciones del período ({reparto}), "
        f"cambian de asesor {resumen.cambiaron}. Las asignadas a mano no se tocan."
    )


def mostrar(fabrica: sessionmaker[Session], cfg: Config) -> None:
    st.title("Cuentas")
    st.caption(
        "Cada cuenta de CloudTalk o de Chatwoot tiene una regla que dice qué asesor "
        "atendió cada llamada o conversación. Las horas son de España."
    )
    if aviso := st.session_state.pop(CLAVE_AVISO, None):
        st.success(aviso)

    if st.button("Actualizar cuentas desde las plataformas"):
        _actualizar_cuentas(fabrica, cfg)

    with unidad_de_trabajo(fabrica) as sesion:
        tabla, etiquetas = _tabla_cuentas(sesion)

    if tabla.empty:
        st.info("Todavía no hay cuentas. Presione «Actualizar cuentas desde las plataformas».")
        return
    st.dataframe(tabla, hide_index=True, use_container_width=True)

    ids = list(etiquetas)
    cuenta_id = st.selectbox(
        "Cuenta", ids, format_func=lambda cid: etiquetas[cid], key="cuenta_elegida"
    )

    with unidad_de_trabajo(fabrica) as sesion:
        regla = RepositorioReglas(sesion).vigente(cuenta_id, datetime.now(timezone.utc))
        if regla is not None:
            estrategia = registro.obtener(regla.estrategia)
            parametros = estrategia.Parametros.model_validate(regla.parametros)
            nombres = {
                pid: p.etiqueta
                for pid, p in RepositorioPersonas(sesion).por_ids(
                    estrategia.personas(parametros)
                ).items()
            }
            st.subheader("Horario de la regla vigente")
            _horario_semanal(estrategia, parametros, nombres)
        st.subheader("Historial de reglas")
        _historial(sesion, cuenta_id)

    st.subheader("Nueva regla")
    _nueva_regla(fabrica, cuenta_id)
