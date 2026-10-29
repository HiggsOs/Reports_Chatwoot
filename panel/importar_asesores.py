"""Importación única de `asesores.csv` a la base de datos.

Hasta la etapa 1 el mapeo correo → área vivía en `DATA_DIR/asesores.csv`. Al
arrancar con la base vacía se copia ese archivo a la tabla `personas` y se
renombra a `asesores.csv.migrado`: queda como respaldo y no se vuelve a leer.
"""

import logging
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session, sessionmaker

from panel.db.base import unidad_de_trabajo
from panel.db.repositorios.personas import RepositorioPersonas
from panel.esquemas.personas import AsesorArea
from reporte import cargar_asesores

SUFIJO_MIGRADO = ".migrado"

registro = logging.getLogger(__name__)


class ResultadoImportacion(BaseModel):
    importados: int
    # Filas que no se pudieron importar (correo y área tal como venían).
    descartados: list[str]
    # Si la base ya tenía asesores, el archivo no se importa: la base manda.
    omitido_por_base_con_datos: bool
    respaldo: Path


def _ruta_respaldo(ruta: Path) -> Path:
    respaldo = ruta.with_name(ruta.name + SUFIJO_MIGRADO)
    if respaldo.exists():
        marca = datetime.now().strftime("%Y%m%d%H%M%S")
        respaldo = ruta.with_name(f"{ruta.name}{SUFIJO_MIGRADO}.{marca}")
    return respaldo


def importar_asesores_csv(
    ruta: Path, fabrica: sessionmaker[Session]
) -> ResultadoImportacion | None:
    """Importa el archivo si existe. Devuelve None si no había nada que importar."""
    if not ruta.exists():
        return None

    mapeo = cargar_asesores(ruta)
    validos: list[AsesorArea] = []
    descartados: list[str] = []
    for correo, area in mapeo.items():
        try:
            validos.append(AsesorArea(correo=correo, area=area))
        except ValidationError:
            descartados.append(f"{correo} ({area or 'sin área'})")

    with unidad_de_trabajo(fabrica) as sesion:
        repositorio = RepositorioPersonas(sesion)
        omitido = repositorio.hay_personas()
        if not omitido:
            repositorio.sincronizar_areas(validos)

    # Se renombra después de confirmar: si la importación falla, el archivo
    # sigue en su lugar y se reintenta en el próximo arranque.
    respaldo = _ruta_respaldo(ruta)
    ruta.rename(respaldo)

    resultado = ResultadoImportacion(
        importados=0 if omitido else len(validos),
        descartados=[] if omitido else descartados,
        omitido_por_base_con_datos=omitido,
        respaldo=respaldo,
    )
    registro.info("Importación de asesores: %s", resultado.model_dump())
    return resultado
