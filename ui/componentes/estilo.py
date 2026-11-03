"""El sistema visual del panel: estilos, insignias de estado e iconos.

El tema base (colores, fuente) está en `.streamlit/config.toml`. Aquí va lo que
el tema no cubre: la densidad de las tablas, las insignias de estado y la
franja de «quién atendió y por qué», que se ve en cada detalle.

Los iconos son de Material Symbols, los que Streamlit trae con
`:material/nombre:`. No se usan emojis.
"""

import html

import streamlit as st

# Iconos por tipo de interacción y por acción, para no repetir los nombres.
ICONOS = {
    "llamada": ":material/call:",
    "conversacion": ":material/chat:",
    "escuchar": ":material/play_arrow:",
    "abrir": ":material/open_in_new:",
    "historial": ":material/history:",
    "descargar": ":material/download:",
    "guardar": ":material/save:",
    "probar": ":material/network_check:",
    "sincronizar": ":material/sync:",
    "cerrar": ":material/close:",
    "reintentar": ":material/refresh:",
    "ir": ":material/arrow_forward:",
    "transcribir": ":material/graphic_eq:",
    "asignar": ":material/person_add:",
    "general": ":material/settings:",
}

# Texto + color, nunca solo color. Cada tono es (fondo, texto, borde).
TONOS = {
    "auto": ("#D8E9F3", "#255874", None),  # asignada por una regla
    "manual": ("#E5DEED", "#4A3663", None),  # la corrigió el auditor
    "sin": ("#F1EBDA", "#6E5D2B", None),  # sin asignar
    "cola": ("#D0EAFB", "#0B5A8E", None),  # en cola o en proceso
    "ok": ("#E3F4E8", "#1E6B3A", None),  # hecha, correcta
    "error": ("#FAD1D1", "#8B0E10", None),
    "desviado": ("#FFFFFF", "#8B0E10", "#ED4548"),  # precio real fuera de margen
    "vence": ("#F1EBDA", "#6E5D2B", "#C6AF6C"),  # audio por vencer
    "neutro": ("#ECF4F9", "#193B4D", None),
}

_CSS = """
<style>
/* Densidad: el auditor pasa horas aquí. */
.block-container {padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1320px;}
h1 {font-size: 1.75rem !important; font-weight: 700 !important;}
h2, h3 {font-weight: 600 !important;}
[data-testid="stMetricValue"] {font-variant-numeric: tabular-nums;}
[data-testid="stCaptionContainer"] {color: #255874;}
[data-testid="stSidebarNav"] [data-testid="stNavSectionHeader"] {
  text-transform: uppercase; letter-spacing: .06em; font-size: .72rem; font-weight: 700; color: #255874;
}
.insignia {
  display: inline-flex; align-items: center; gap: 4px; height: 20px; padding: 0 8px;
  border-radius: 10px; font-size: 12px; font-weight: 600; white-space: nowrap; vertical-align: middle;
}
.franja-asesor {
  display: flex; flex-wrap: wrap; align-items: center; gap: 10px;
  padding: 10px 14px; border-radius: 8px; border: 1px solid #D8E9F3; background: #F5FAFD; margin-bottom: .6rem;
}
.franja-asesor.sin {border-color: #C6AF6C; background: #F8F5ED;}
.franja-asesor b {font-size: 1rem;}
.franja-asesor .motivo {color: #193B4D; font-size: .9rem;}
</style>
"""


def aplicar() -> None:
    """Se llama una vez por carga, antes de dibujar la página."""
    st.markdown(_CSS, unsafe_allow_html=True)


def insignia(texto: str, tono: str = "neutro") -> str:
    """HTML de una insignia, para usar con `st.markdown(..., unsafe_allow_html=True)`."""
    fondo, color, borde = TONOS.get(tono, TONOS["neutro"])
    sombra = f"box-shadow: inset 0 0 0 1px {borde};" if borde else ""
    return (
        f'<span class="insignia" style="background:{fondo};color:{color};{sombra}">'
        f"{html.escape(texto)}</span>"
    )


def franja_asesor(asesor: str | None, asignacion: str, motivo: str) -> None:
    """Quién atendió y por qué. Siempre visible: las cuentas son compartidas."""
    if not asesor:
        nombre, tono, etiqueta = "Sin asignar", "sin", "Sin asignar"
    elif asignacion == "manual":
        nombre, tono, etiqueta = asesor, "manual", "Manual"
    else:
        nombre, tono, etiqueta = asesor, "auto", "Regla"
    clase = "franja-asesor sin" if not asesor else "franja-asesor"
    st.markdown(
        f'<div class="{clase}"><b>{html.escape(nombre)}</b>{insignia(etiqueta, tono)}'
        f'<span class="motivo">{html.escape(motivo or "")}</span></div>',
        unsafe_allow_html=True,
    )


def numero(valor, decimales: int = 2) -> str:
    """1234.5 → «1.234,50»: coma decimal y punto de miles, como en España."""
    if valor is None:
        return "—"
    texto = f"{float(valor):,.{decimales}f}"
    return texto.replace(",", "§").replace(".", ",").replace("§", ".")


def usd(valor, decimales: int = 2) -> str:
    return "—" if valor is None else f"{numero(valor, decimales)} USD"


def etiqueta_asignacion(asesor: str | None, asignacion: str) -> str:
    """La misma idea en texto plano, para las celdas de st.dataframe."""
    if not asesor:
        return "Sin asignar"
    return "Manual" if asignacion == "manual" else "Regla"
