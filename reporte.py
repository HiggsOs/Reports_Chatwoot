"""Armado del reporte de conversaciones a partir de los datos de Chatwoot."""

import csv
from pathlib import Path

AREAS_VALIDAS = ("Comercial", "RDC")
SIN_MAPEAR = "SIN_MAPEAR"
SIN_ASIGNAR = "SIN_ASIGNAR"

_ENCABEZADOS_ASESORES = ("email_asesor", "area")


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
