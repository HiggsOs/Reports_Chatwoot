"""Armado del reporte de conversaciones a partir de los datos de Chatwoot."""

import csv
import io
import re
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

AREAS_VALIDAS = ("Comercial", "RDC")
SIN_MAPEAR = "SIN_MAPEAR"
SIN_ASIGNAR = "SIN_ASIGNAR"

_ENCABEZADOS_ASESORES = ("email_asesor", "area")

TZ = ZoneInfo("America/Bogota")

ENTRANTE = "Entrante"
SALIENTE = "Saliente"
INDETERMINADO = "Indeterminado"

TIPO_ENTRANTE = 0
TIPO_SALIENTE = 1
TIPO_ACTIVIDAD = 2

# El texto de la actividad depende del idioma configurado en Chatwoot.
_PATRON_RESOLUCION = re.compile(r"resolv(ed|ió)|resuelt[ao]", re.IGNORECASE)
_PATRON_REAPERTURA = re.compile(r"reopen|reabr", re.IGNORECASE)

_ESTADOS = {
    "open": "abierta",
    "pending": "pendiente",
    "resolved": "resuelta",
    "snoozed": "pospuesta",
}


def traducir_estado(estado: str) -> str:
    return _ESTADOS.get(estado, estado)


def a_fecha_local(epoch: int | float | None) -> datetime | None:
    if not epoch:
        return None
    return datetime.fromtimestamp(float(epoch), TZ)


def detectar_direccion(mensajes: list[dict]) -> str:
    """Mira el primer mensaje real: define si el contacto o el asesor inició."""
    for msg in mensajes:
        tipo = msg.get("message_type")
        if tipo == TIPO_ENTRANTE:
            return ENTRANTE
        if tipo == TIPO_SALIENTE:
            return SALIENTE
    return INDETERMINADO


def detectar_cierre(
    conversacion: dict, mensajes: list[dict]
) -> tuple[datetime | None, bool]:
    """Devuelve (fecha de cierre, si es aproximada). Ver sección 5.3 del diseño."""
    if conversacion.get("status") != "resolved":
        return None, False

    resoluciones = [
        msg.get("created_at")
        for msg in mensajes
        if msg.get("message_type") == TIPO_ACTIVIDAD
        and _PATRON_RESOLUCION.search(msg.get("content") or "")
        and not _PATRON_REAPERTURA.search(msg.get("content") or "")
    ]
    if resoluciones:
        return a_fecha_local(max(resoluciones)), False

    return a_fecha_local(conversacion.get("last_activity_at")), True


def cargar_asesores(ruta: Path) -> dict[str, str]:
    """Lee el mapeo correo → área. Devuelve vacío si el archivo no existe."""
    if not ruta.exists():
        return {}

    with ruta.open(encoding="utf-8-sig", newline="") as archivo:
        filas = csv.DictReader(archivo)
        return {
            (fila.get("email_asesor") or "").strip().lower(): (
                fila.get("area") or ""
            ).strip()
            for fila in filas
            if (fila.get("email_asesor") or "").strip()
        }


def guardar_asesores(ruta: Path, mapeo: dict[str, str]) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8", newline="") as archivo:
        escritor = csv.writer(archivo)
        escritor.writerow(_ENCABEZADOS_ASESORES)
        for correo in sorted(mapeo):
            escritor.writerow([correo, mapeo[correo]])


def resolver_area(email: str | None, mapeo: dict[str, str]) -> str:
    if not email or not email.strip():
        return SIN_ASIGNAR
    return mapeo.get(email.strip().lower(), SIN_MAPEAR)


COLUMNAS = (
    "conversacion_id",
    "asesor",
    "email_asesor",
    "area",
    "fecha_creacion",
    "canal",
    "etiquetas",
    "direccion",
    "estado",
    "fecha_cierre",
    "tiempo_resolucion_horas",
    "cierre_aproximado",
)

FORMATO_FECHA = "%Y-%m-%d %H:%M"


def _texto_fecha(momento: datetime | None) -> str:
    return momento.strftime(FORMATO_FECHA) if momento else ""


SIN_CANAL = "SIN_CANAL"


def resolver_canal(conversacion: dict, inboxes: dict[int, str]) -> str:
    """Nombre del inbox por el que entró la conversación."""
    inbox_id = conversacion.get("inbox_id")
    if inbox_id is None:
        return SIN_CANAL
    return inboxes.get(inbox_id) or f"inbox {inbox_id}"


def construir_fila(
    conversacion: dict,
    mensajes: list[dict],
    mapeo: dict[str, str],
    inboxes: dict[int, str] | None = None,
) -> dict[str, str]:
    asignado = (conversacion.get("meta") or {}).get("assignee") or {}
    email = asignado.get("email") or ""
    creacion = a_fecha_local(conversacion.get("created_at"))
    cierre, aproximado = detectar_cierre(conversacion, mensajes)

    if cierre and creacion:
        horas = f"{(cierre - creacion).total_seconds() / 3600:.1f}"
    else:
        horas = ""

    return {
        "conversacion_id": str(conversacion.get("id", "")),
        "asesor": asignado.get("name") or "",
        "email_asesor": email,
        "area": resolver_area(email, mapeo),
        "fecha_creacion": _texto_fecha(creacion),
        "canal": resolver_canal(conversacion, inboxes or {}),
        "etiquetas": ";".join(conversacion.get("labels") or []),
        "direccion": detectar_direccion(mensajes),
        "estado": traducir_estado(conversacion.get("status", "")),
        "fecha_cierre": _texto_fecha(cierre),
        "tiempo_resolucion_horas": horas,
        "cierre_aproximado": "Sí" if cierre and aproximado else "",
    }


def generar_filas(
    cliente,
    desde: datetime,
    hasta: datetime,
    mapeo: dict[str, str],
    cache=None,
    al_avanzar=None,
) -> list[dict[str, str]]:
    """Trae las conversaciones del rango y arma una fila por cada una."""
    conversaciones = cliente.listar_conversaciones(desde, hasta)
    inboxes = cliente.listar_inboxes()
    total = len(conversaciones)
    filas = []

    for indice, conversacion in enumerate(conversaciones, start=1):
        conversacion_id = conversacion["id"]
        resuelta = conversacion.get("status") == "resolved"

        mensajes = cache.leer(conversacion_id) if cache and resuelta else None
        if mensajes is None:
            mensajes = cliente.listar_mensajes(conversacion_id)
            # Solo se cachean las resueltas: las abiertas todavía pueden cambiar.
            if cache and resuelta:
                cache.guardar(conversacion_id, mensajes)

        filas.append(construir_fila(conversacion, mensajes, mapeo, inboxes))
        if al_avanzar:
            al_avanzar(indice, total)

    return filas


def escribir_csv(filas: list[dict[str, str]]) -> bytes:
    """CSV con BOM para que Excel en Windows respete los acentos."""
    memoria = io.StringIO()
    escritor = csv.DictWriter(memoria, fieldnames=list(COLUMNAS), lineterminator="\r\n")
    escritor.writeheader()
    escritor.writerows(filas)
    return memoria.getvalue().encode("utf-8-sig")


def nombre_archivo(desde: date, hasta: date) -> str:
    return f"reporte-chatwoot-{desde:%Y-%m-%d}-a-{hasta:%Y-%m-%d}.csv"
