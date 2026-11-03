"""Páginas Llamadas, Conversaciones y Sin asignar.

Llamadas y Conversaciones son la misma página con otra `Vista` (patrón
Strategy): qué listar, qué columnas mostrar, cómo enlazar a la plataforma y qué
mostrar en el detalle. Agregar otro tipo de interacción es agregar una Vista.
"""

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass

import pandas as pd
import streamlit as st
from sqlalchemy.orm import Session, sessionmaker

from config import Config
from panel.db.base import unidad_de_trabajo
from panel.db.repositorios.cuentas import RepositorioCuentas
from panel.db.repositorios.personas import RepositorioPersonas
from panel.servicios import consultas
from panel.servicios.interacciones import SIN_ASIGNAR, ServicioInteracciones
from ui import estado
from ui.componentes import avisos, chat
from ui.componentes import transcripcion as ui_transcripcion
from ui.componentes.asignacion import editor_asignacion, fila_elegida
from ui.componentes.audio import etiqueta_estado, reproductor
from ui.componentes.estilo import ICONOS, etiqueta_asignacion, franja_asesor
from ui.componentes.filtros import rango_fechas

# Orden de lectura del auditor: cuándo, quién y por qué, con quién; lo técnico al final.
COLUMNAS_COMUNES = {
    "inicio": "Fecha",
    "asesor": "Asesor",
    "asignacion": "Asignación",
    "motivo": "Motivo",
    "cliente": "Cliente",
    "telefono": "Teléfono",
}
COLUMNAS_FINALES = {"cuenta": "Cuenta", "area": "Área"}


@dataclass(frozen=True)
class Vista:
    tipo: str  # «llamada» o «conversacion», como en ServicioInteracciones
    titulo: str
    singular: str
    plural: str
    plataforma: str
    icono: str
    listar: Callable
    columnas: dict[str, str]  # atributo → encabezado, para la tabla y el CSV
    archivo: str
    enlace: Callable[[consultas.FilaInteraccion, Config], tuple[str, str] | None]


def _enlace_llamada(fila, cfg):
    if fila.enlace_plataforma:
        return "Abrir en CloudTalk", fila.enlace_plataforma
    return None


def _enlace_conversacion(fila, cfg):
    if not cfg.chatwoot_configurado:
        return None
    return (
        "Abrir en Chatwoot",
        f"{cfg.base_url}/app/accounts/{cfg.account_id}/conversations/{fila.id_externo}",
    )


VISTAS = {
    "llamada": Vista(
        tipo="llamada",
        titulo="Llamadas",
        singular="Llamada",
        plural="llamadas",
        plataforma="cloudtalk",
        icono=ICONOS["llamada"],
        listar=consultas.listar_llamadas,
        columnas={
            **COLUMNAS_COMUNES,
            "direccion": "Dirección",
            "duracion_s": "Duración",
            "audio_estado": "Audio",
            "transcripcion_estado": "Transcripción",
            **COLUMNAS_FINALES,
            "id_externo": "Id CloudTalk",
        },
        archivo="llamadas",
        enlace=_enlace_llamada,
    ),
    "conversacion": Vista(
        tipo="conversacion",
        titulo="Conversaciones",
        singular="Conversación",
        plural="conversaciones",
        plataforma="chatwoot",
        icono=ICONOS["conversacion"],
        listar=consultas.listar_conversaciones,
        columnas={
            **COLUMNAS_COMUNES,
            "canal": "Canal",
            "estado": "Estado",
            "etiquetas": "Etiquetas",
            "horas_resolucion": "Horas hasta la resolución",
            "cierre": "Cierre",
            **COLUMNAS_FINALES,
            "id_externo": "Id Chatwoot",
        },
        archivo="conversaciones",
        enlace=_enlace_conversacion,
    ),
}


def _duracion(segundos) -> str:
    if segundos is None or pd.isna(segundos):
        return ""
    minutos, resto = divmod(int(segundos), 60)
    return f"{minutos}:{resto:02d}"


def _tabla(filas: list[consultas.FilaInteraccion], columnas: dict[str, str]) -> pd.DataFrame:
    """La tabla para leer. El CSV sale de los mismos datos sin este formato."""
    datos = pd.DataFrame(
        [{titulo: getattr(fila, atributo) for atributo, titulo in columnas.items()} for fila in filas],
        columns=list(columnas.values()),
    )
    if "Asignación" in datos:
        datos["Asignación"] = [etiqueta_asignacion(f.asesor, f.asignacion) for f in filas]
    if "Asesor" in datos:
        datos["Asesor"] = datos["Asesor"].replace("", SIN_ASIGNAR)
    for columna in ("Fecha", "Cierre"):
        if columna in datos:
            datos[columna] = pd.to_datetime(datos[columna]).dt.strftime("%d/%m/%Y %H:%M")
    if "Duración" in datos:
        datos["Duración"] = datos["Duración"].map(_duracion)
    if "Dirección" in datos:
        datos["Dirección"] = datos["Dirección"].str.capitalize()
    if "Audio" in datos:
        datos["Audio"] = datos["Audio"].map(etiqueta_estado)
    if "Transcripción" in datos:
        datos["Transcripción"] = datos["Transcripción"].map(
            {"transcrita": "Hecha", "eliminada": "Borrada por plazo"}
        ).fillna("")
    return datos


def _personas(fabrica):
    with unidad_de_trabajo(fabrica) as sesion:
        return RepositorioPersonas(sesion).listar()


def pagina(
    fabrica: sessionmaker[Session],
    cfg: Config,
    tipo: str,
    paginas: dict | None = None,
    audio=None,
    transcripcion=None,
) -> None:
    """`paginas`: ruta → página, para ir al Historial del cliente desde el
    detalle. `audio` y `transcripcion`: los servicios, para escuchar y
    transcribir las llamadas."""
    historial = (paginas or {}).get("historial")
    vista = VISTAS[tipo]
    st.title(vista.titulo)
    avisos.mostrar()
    personas = _personas(fabrica)
    with unidad_de_trabajo(fabrica) as sesion:
        cuentas = {
            c.id: c.nombre
            for c in RepositorioCuentas(sesion).listar(incluir_inactivas=True)
            if c.plataforma == vista.plataforma
        }

    with st.container(border=True):
        columnas = st.columns([1, 1, 1.6, 1.4, 1.4, 0.9], vertical_alignment="bottom")
        rango = rango_fechas(tipo, 7, columnas[:2])
        persona_ids = columnas[2].multiselect(
            "Asesores", [p.id for p in personas],
            format_func={p.id: p.etiqueta for p in personas}.get,
            placeholder="Todos", key=f"{tipo}-asesores",
        )
        cuenta_ids = columnas[3].multiselect(
            "Cuentas", list(cuentas), format_func=cuentas.get, placeholder="Todas",
            key=f"{tipo}-cuentas",
        )
        cliente = columnas[4].text_input(
            "Cliente", placeholder="Nombre o teléfono", key=f"{tipo}-cliente"
        )
        solo_sin_asignar = columnas[5].checkbox("Solo sin asignar", key=f"{tipo}-sin-asignar")
    if rango is None:
        return
    desde, hasta, dia_desde, dia_hasta = rango

    filtros = consultas.Filtros(
        desde=desde, hasta=hasta, persona_ids=persona_ids, cuenta_ids=cuenta_ids,
        solo_sin_asignar=solo_sin_asignar, cliente=cliente,
    )
    with unidad_de_trabajo(fabrica) as sesion:
        filas = vista.listar(sesion, filtros)

    if not filas:
        st.info(f"No hay {vista.plural} con estos filtros.")
        return
    sin_asesor = sum(1 for f in filas if not f.asesor)
    texto = f"**{len(filas)} {vista.plural}**" + (f" · {sin_asesor} sin asignar" if sin_asesor else "")
    if len(filas) >= consultas.LIMITE_FILAS:
        texto += (
            f" · se muestran las {consultas.LIMITE_FILAS} más recientes: acote las fechas o "
            "descargue el CSV"
        )
    izquierda, derecha, _ = st.columns([3.2, 1.2, 1.6], vertical_alignment="center")
    izquierda.markdown(texto + ". Elija una fila para ver el detalle.")
    derecha.download_button(
        "Descargar CSV",
        data=consultas.a_csv(filas, vista.columnas),
        file_name=f"{vista.archivo}_{dia_desde:%Y-%m-%d}_{dia_hasta:%Y-%m-%d}.csv",
        mime="text/csv",
        key=f"{tipo}-csv",
        icon=ICONOS["descargar"],
        use_container_width=True,
    )

    if vista.tipo == "llamada":
        ui_transcripcion.lote(transcripcion, filas, cfg)

    evento = st.dataframe(
        _tabla(filas, vista.columnas),
        hide_index=True,
        use_container_width=True,
        height=400,
        on_select="rerun",
        selection_mode="single-row",
        key=f"{tipo}-tabla",
    )

    clave = f"{tipo}-elegida"
    fila = fila_elegida(clave, evento, filas, lambda f: f.id)
    if fila is not None:
        detalle(fabrica, cfg, vista, fila, personas, historial, audio, transcripcion, clave)


def detalle(fabrica, cfg, vista: Vista, fila, personas, historial, audio, transcripcion, clave: str) -> None:
    """El detalle de una fila: quién y por qué arriba; a la izquierda lo que se
    escucha o se lee, a la derecha los datos y la asignación."""
    with st.container(border=True):
        titulo, botones = st.columns([2, 3], vertical_alignment="center")
        titulo.subheader(f"{vista.icono} {vista.singular} {fila.id_externo}")
        titulo.caption(f"{fila.inicio:%d/%m/%Y %H:%M} · {fila.cuenta}")
        uno, dos, tres = botones.columns([1.3, 1.5, 0.35])
        if enlace := vista.enlace(fila, cfg):
            uno.link_button(enlace[0], enlace[1], icon=ICONOS["abrir"], use_container_width=True)
        if fila.cliente_id is not None and historial is not None:
            if dos.button("Ver historial del cliente", key=f"{vista.tipo}-{fila.id}-historial",
                          icon=ICONOS["historial"], use_container_width=True):
                st.session_state[estado.CLIENTE_ELEGIDO] = fila.cliente_id
                st.switch_page(historial)
        if tres.button("", key=f"{clave}-cerrar", icon=ICONOS["cerrar"], help="Cerrar el detalle"):
            st.session_state.pop(clave, None)
            st.rerun()

        franja_asesor(fila.asesor, fila.asignacion, fila.motivo)

        izquierda, derecha = st.columns([7, 5], gap="large")
        with izquierda:
            if vista.tipo == "llamada":
                reproductor(audio, fila.id, cfg.audio_retencion_dias)
                ui_transcripcion.panel(transcripcion, fila.id)
            else:
                chat.mostrar(fabrica, fila.id)
        with derecha:
            st.markdown("**Datos**")
            for etiqueta, valor in _datos(vista, fila).items():
                st.markdown(f"<small style='color:#255874'>{etiqueta}</small><br>{valor or '—'}",
                            unsafe_allow_html=True)
            st.divider()
            editor_asignacion(fabrica, vista.tipo, fila.id, fila.persona_id, fila.asignacion, personas)


def _datos(vista: Vista, fila) -> dict[str, str]:
    datos = {
        "Cliente": fila.cliente,
        "Teléfono": fila.telefono,
        "Cuenta": fila.cuenta,
        "Área": fila.area,
    }
    if vista.tipo == "llamada":
        datos |= {"Dirección": fila.direccion.capitalize(), "Duración": _duracion(fila.duracion_s)}
    else:
        datos |= {
            "Canal": fila.canal,
            "Estado": fila.estado,
            "Etiquetas": fila.etiquetas.replace(";", ", "),
            "Horas hasta la resolución": "" if fila.horas_resolucion is None else f"{fila.horas_resolucion:g}",
        }
    return datos


def sin_asignar(fabrica: sessionmaker[Session], cfg: Config, paginas: dict | None = None) -> None:
    """`paginas`: ruta → página, para ir a Cuentas a crear la regla que falta."""
    st.title("Sin asignar")
    st.caption(
        "Llamadas y chats que ninguna regla pudo asignar: su cuenta no tiene regla, la "
        "regla no cubre ese horario o el chat no tiene usuario en Chatwoot. Elija las "
        "filas y a quién asignarlas."
    )
    avisos.mostrar()
    rango = rango_fechas("sin-asignar", 30)
    if rango is None:
        return
    personas = _personas(fabrica)
    if not personas:
        st.warning("Todavía no hay asesores. Créelos en la página Asesores para poder asignar.")
        return
    desde, hasta, _, _ = rango
    filtros = consultas.Filtros(desde=desde, hasta=hasta, solo_sin_asignar=True)
    nombres = {p.id: p.etiqueta for p in personas}

    por_vista = {}
    with unidad_de_trabajo(fabrica) as sesion:
        for vista in VISTAS.values():
            por_vista[vista.tipo] = vista.listar(sesion, filtros)
    if not any(por_vista.values()):
        st.success("No hay nada sin asignar en el rango.")
        return

    _motivos(por_vista, (paginas or {}).get("cuentas"))
    for vista in VISTAS.values():
        filas = por_vista[vista.tipo]
        st.subheader(f"{vista.icono} {vista.titulo} · {len(filas)}")
        if not filas:
            st.caption(f"No hay {vista.plural} sin asignar en el rango.")
            continue
        _bandeja(fabrica, vista, filas, nombres)


def _motivos(por_vista, cuentas) -> None:
    """Por qué están sin asignar, agrupado: suele ser una cuenta sin regla."""
    conteo = Counter(
        (vista_tipo, fila.cuenta, fila.motivo or "Sin motivo")
        for vista_tipo, filas in por_vista.items()
        for fila in filas
    )
    with st.container(border=True):
        st.markdown("**Por qué están sin asignar**")
        st.dataframe(
            pd.DataFrame(
                [
                    {"Tipo": VISTAS[tipo].titulo, "Cuenta": cuenta, "Motivo": motivo, "Cantidad": n}
                    for (tipo, cuenta, motivo), n in conteo.most_common()
                ]
            ),
            hide_index=True,
            use_container_width=True,
        )
        if cuentas is not None:
            st.page_link(cuentas, label="Crear o corregir reglas en Cuentas", icon=ICONOS["ir"])


def _bandeja(fabrica, vista: Vista, filas, nombres) -> None:
    columnas = {"inicio": "Fecha", "cuenta": "Cuenta", "motivo": "Motivo",
                "cliente": "Cliente", "telefono": "Teléfono"}
    tabla = _tabla(filas, columnas)
    tabla.insert(0, "Elegir", False)
    izquierda, medio, derecha = st.columns([2, 1, 1], vertical_alignment="bottom")
    persona = izquierda.selectbox(
        "Asignar a", list(nombres), format_func=nombres.get, key=f"bandeja-{vista.tipo}-persona"
    )
    todas = medio.checkbox("Elegir todas", key=f"bandeja-{vista.tipo}-todas")
    if todas:
        tabla["Elegir"] = True
    editada = st.data_editor(
        tabla,
        hide_index=True,
        use_container_width=True,
        disabled=list(columnas.values()),
        key=f"bandeja-{vista.tipo}-{todas}",
    )
    elegidas = [filas[i].id for i, marcada in enumerate(editada["Elegir"]) if marcada]
    if derecha.button(
        f"Asignar {len(elegidas)}" if elegidas else "Asignar",
        disabled=not elegidas,
        type="primary",
        icon=ICONOS["asignar"],
        key=f"bandeja-{vista.tipo}-asignar",
        use_container_width=True,
    ):
        with unidad_de_trabajo(fabrica) as sesion:
            servicio = ServicioInteracciones(sesion)
            for interaccion_id in elegidas:
                servicio.asignar_manual(vista.tipo, interaccion_id, persona)
        avisos.dejar(f"{len(elegidas)} {vista.plural} asignadas a {nombres[persona]} (manual).")
        st.rerun()
