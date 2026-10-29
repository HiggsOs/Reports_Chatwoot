"""Páginas Llamadas, Conversaciones y Sin asignar.

Llamadas y Conversaciones son la misma página con otra `Vista`: qué listar,
qué columnas mostrar y cómo enlazar a la plataforma.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

import pandas as pd
import streamlit as st
from sqlalchemy.orm import Session, sessionmaker

from config import Config
from panel.asignacion.servicio import ZONA_OPERACION_POR_DEFECTO
from panel.db.base import unidad_de_trabajo
from panel.db.repositorios.cuentas import RepositorioCuentas
from panel.db.repositorios.personas import RepositorioPersonas
from panel.servicios import consultas
from panel.servicios.interacciones import SIN_ASIGNAR, ServicioInteracciones

COLUMNAS_COMUNES = {
    "inicio": "Fecha",
    "cuenta": "Cuenta",
    "asesor": "Asesor",
    "area": "Área",
    "cliente": "Cliente",
    "telefono": "Teléfono",
    "asignacion": "Asignación",
    "motivo": "Motivo",
}


@dataclass(frozen=True)
class Vista:
    tipo: str  # «llamada» o «conversacion», como en ServicioInteracciones
    titulo: str
    plural: str
    plataforma: str
    listar: Callable
    columnas: dict[str, str]  # atributo → encabezado, para la tabla y el CSV
    archivo: str
    enlace: Callable[[consultas.FilaInteraccion, Config], tuple[str, str] | None]


def _enlace_llamada(fila, cfg):
    if fila.enlace_plataforma:
        return "Abrir en CloudTalk", fila.enlace_plataforma
    return None


def _enlace_conversacion(fila, cfg):
    return (
        "Abrir en Chatwoot",
        f"{cfg.base_url}/app/accounts/{cfg.account_id}/conversations/{fila.id_externo}",
    )


VISTAS = {
    "llamada": Vista(
        tipo="llamada",
        titulo="Llamadas",
        plural="llamadas",
        plataforma="cloudtalk",
        listar=consultas.listar_llamadas,
        columnas={
            "id_externo": "Id CloudTalk",
            **COLUMNAS_COMUNES,
            "direccion": "Dirección",
            "duracion_s": "Duración (s)",
            "grabada": "Grabada",
        },
        archivo="llamadas",
        enlace=_enlace_llamada,
    ),
    "conversacion": Vista(
        tipo="conversacion",
        titulo="Conversaciones",
        plural="conversaciones",
        plataforma="chatwoot",
        listar=consultas.listar_conversaciones,
        columnas={
            "id_externo": "Id Chatwoot",
            **COLUMNAS_COMUNES,
            "canal": "Canal",
            "estado": "Estado",
            "etiquetas": "Etiquetas",
            "direccion": "Dirección",
            "cierre": "Cierre",
            "horas_resolucion": "Horas de resolución",
            "cierre_aproximado": "Cierre aproximado",
        },
        archivo="conversaciones",
        enlace=_enlace_conversacion,
    ),
}


def _inicio_del_dia(dia: date) -> datetime:
    return datetime.combine(dia, time.min, tzinfo=ZONA_OPERACION_POR_DEFECTO)


def _rango(prefijo: str, dias: int) -> tuple[date, date] | None:
    hoy = date.today()
    izquierda, derecha = st.columns(2)
    desde = izquierda.date_input(
        "Desde", value=hoy - timedelta(days=dias), format="DD/MM/YYYY", key=f"{prefijo}-desde"
    )
    hasta = derecha.date_input("Hasta", value=hoy, format="DD/MM/YYYY", key=f"{prefijo}-hasta")
    if desde > hasta:
        st.warning("La fecha inicial no puede ser posterior a la final.")
        return None
    return desde, hasta


def _tabla(filas: list[consultas.FilaInteraccion], columnas: dict[str, str]) -> pd.DataFrame:
    datos = pd.DataFrame(
        [{titulo: getattr(fila, atributo) for atributo, titulo in columnas.items()} for fila in filas],
        columns=list(columnas.values()),
    )
    if "Fecha" in datos:
        datos["Fecha"] = pd.to_datetime(datos["Fecha"]).dt.strftime("%d/%m/%Y %H:%M")
    if "Cierre" in datos:
        datos["Cierre"] = pd.to_datetime(datos["Cierre"]).dt.strftime("%d/%m/%Y %H:%M")
    return datos


def _personas(fabrica):
    with unidad_de_trabajo(fabrica) as sesion:
        return RepositorioPersonas(sesion).listar()


def pagina(fabrica: sessionmaker[Session], cfg: Config, tipo: str) -> None:
    vista = VISTAS[tipo]
    st.title(vista.titulo)
    personas = _personas(fabrica)
    with unidad_de_trabajo(fabrica) as sesion:
        cuentas = {
            c.id: c.nombre
            for c in RepositorioCuentas(sesion).listar(incluir_inactivas=True)
            if c.plataforma == vista.plataforma
        }

    rango = _rango(tipo, 7)
    if rango is None:
        return
    izquierda, derecha = st.columns(2)
    persona_ids = izquierda.multiselect(
        "Asesores",
        [p.id for p in personas],
        format_func={p.id: p.etiqueta for p in personas}.get,
        placeholder="Todos",
        key=f"{tipo}-asesores",
    )
    cuenta_ids = derecha.multiselect(
        "Cuentas", list(cuentas), format_func=cuentas.get, placeholder="Todas",
        key=f"{tipo}-cuentas",
    )
    izquierda, derecha = st.columns(2)
    cliente = izquierda.text_input(
        "Cliente", placeholder="Nombre o teléfono", key=f"{tipo}-cliente"
    )
    solo_sin_asignar = derecha.checkbox("Solo sin asignar", key=f"{tipo}-sin-asignar")

    filtros = consultas.Filtros(
        desde=_inicio_del_dia(rango[0]),
        hasta=_inicio_del_dia(rango[1] + timedelta(days=1)),
        persona_ids=persona_ids,
        cuenta_ids=cuenta_ids,
        solo_sin_asignar=solo_sin_asignar,
        cliente=cliente,
    )
    with unidad_de_trabajo(fabrica) as sesion:
        filas = vista.listar(sesion, filtros)

    texto = f"{len(filas)} {vista.plural}"
    if len(filas) >= consultas.LIMITE_FILAS:
        texto += f" (se muestran las {consultas.LIMITE_FILAS} más recientes; acote el rango)"
    st.caption(texto + ". Elija una fila para ver el detalle o cambiar el asesor.")
    if not filas:
        return

    evento = st.dataframe(
        _tabla(filas, vista.columnas),
        hide_index=True,
        use_container_width=True,
        on_select="rerun",
        selection_mode="single-row",
        key=f"{tipo}-tabla",
    )
    st.download_button(
        "Descargar CSV",
        data=consultas.a_csv(filas, vista.columnas),
        file_name=f"{vista.archivo}_{rango[0]:%Y-%m-%d}_{rango[1]:%Y-%m-%d}.csv",
        mime="text/csv",
        key=f"{tipo}-csv",
    )

    seleccion = evento.selection.rows if evento else []
    if seleccion:
        _detalle(fabrica, cfg, vista, filas[seleccion[0]], personas)


def _detalle(fabrica, cfg, vista: Vista, fila, personas) -> None:
    st.subheader(f"{vista.titulo[:-1]} {fila.id_externo}")
    datos = {
        "Fecha": f"{fila.inicio:%d/%m/%Y %H:%M}",
        "Cuenta": fila.cuenta,
        "Cliente": " · ".join(p for p in (fila.cliente, fila.telefono) if p) or "—",
        "Asesor": fila.asesor or SIN_ASIGNAR,
        "Asignación": f"{fila.asignacion} — {fila.motivo}",
    }
    for etiqueta, valor in datos.items():
        st.markdown(f"**{etiqueta}:** {valor}")
    if enlace := vista.enlace(fila, cfg):
        st.link_button(enlace[0], enlace[1])

    ids = [None] + [p.id for p in personas]
    nombres = {p.id: p.etiqueta for p in personas}
    elegida = st.selectbox(
        "Asignar a mano",
        ids,
        index=ids.index(fila.persona_id) if fila.persona_id in ids else 0,
        format_func=lambda pid: SIN_ASIGNAR if pid is None else nombres[pid],
        key=f"{vista.tipo}-{fila.id}-persona",
        help="Una asignación hecha a mano no la cambian ni la sincronización ni las reglas.",
    )
    izquierda, derecha = st.columns(2)
    if izquierda.button("Guardar asignación", key=f"{vista.tipo}-{fila.id}-guardar"):
        with unidad_de_trabajo(fabrica) as sesion:
            ServicioInteracciones(sesion).asignar_manual(vista.tipo, fila.id, elegida)
        st.rerun()
    if fila.asignacion == "manual" and derecha.button(
        "Volver a la asignación automática", key=f"{vista.tipo}-{fila.id}-automatica"
    ):
        with unidad_de_trabajo(fabrica) as sesion:
            ServicioInteracciones(sesion).volver_a_automatica(vista.tipo, fila.id)
        st.rerun()


def sin_asignar(fabrica: sessionmaker[Session], cfg: Config) -> None:
    st.title("Sin asignar")
    st.caption(
        "Llamadas y conversaciones sin asesor: su cuenta no tiene regla, la regla no "
        "cubre ese horario o la conversación no tiene usuario en Chatwoot. Elija las "
        "filas y a quién asignarlas."
    )
    rango = _rango("sin-asignar", 30)
    if rango is None:
        return
    personas = _personas(fabrica)
    if not personas:
        st.warning("Primero cargue los asesores en la página Asesores.")
        return
    filtros = consultas.Filtros(
        desde=_inicio_del_dia(rango[0]),
        hasta=_inicio_del_dia(rango[1] + timedelta(days=1)),
        solo_sin_asignar=True,
    )
    nombres = {p.id: p.etiqueta for p in personas}

    for vista in VISTAS.values():
        st.subheader(vista.titulo)
        with unidad_de_trabajo(fabrica) as sesion:
            filas = vista.listar(sesion, filtros)
        if not filas:
            st.caption(f"No hay {vista.plural} sin asignar en el rango.")
            continue
        columnas = {"inicio": "Fecha", "cuenta": "Cuenta", "cliente": "Cliente",
                    "telefono": "Teléfono", "motivo": "Motivo"}
        tabla = _tabla(filas, columnas)
        tabla.insert(0, "Elegir", False)
        editada = st.data_editor(
            tabla,
            hide_index=True,
            use_container_width=True,
            disabled=list(columnas.values()),
            key=f"bandeja-{vista.tipo}",
        )
        elegidas = [filas[i].id for i, marcada in enumerate(editada["Elegir"]) if marcada]
        izquierda, derecha = st.columns([2, 1])
        persona = izquierda.selectbox(
            "Asignar a", list(nombres), format_func=nombres.get, key=f"bandeja-{vista.tipo}-persona"
        )
        derecha.write("")
        if derecha.button(
            f"Asignar {len(elegidas)}" if elegidas else "Asignar",
            disabled=not elegidas,
            type="primary",
            key=f"bandeja-{vista.tipo}-asignar",
        ):
            with unidad_de_trabajo(fabrica) as sesion:
                servicio = ServicioInteracciones(sesion)
                for interaccion_id in elegidas:
                    servicio.asignar_manual(vista.tipo, interaccion_id, persona)
            st.rerun()
