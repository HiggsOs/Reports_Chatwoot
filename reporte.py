"""Armado del reporte de conversaciones a partir de los datos de Chatwoot."""

import csv
import re
from datetime import datetime
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
