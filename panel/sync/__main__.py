"""Proceso de sincronización: `python -m panel.sync`.

Sin argumentos corre para siempre, un ciclo cada SYNC_INTERVALO_MINUTOS.
Con --una-vez corre un ciclo y termina. Con --desde carga el historial de un
rango (por ejemplo, la primera vez, para traer meses anteriores).
"""

import argparse
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta

from sqlalchemy.exc import SQLAlchemyError

from config import Config, ConfigError, cargar_config
from panel.ajustes import entorno_efectivo
from panel.asignacion.servicio import ZONA_OPERACION_POR_DEFECTO
from panel.composicion import sincronizadores
from panel.db.base import crear_fabrica_sesiones, crear_motor
from panel.sync.sincronizadores import ejecutar_ciclo

registro = logging.getLogger("panel.sync")


def _dia(texto: str) -> date:
    try:
        return date.fromisoformat(texto)
    except ValueError:
        raise argparse.ArgumentTypeError(f"fecha inválida {texto!r}; use AAAA-MM-DD") from None


def _inicio_del_dia(dia: date) -> datetime:
    """Medianoche en hora de España."""
    return datetime.combine(dia, datetime.min.time(), tzinfo=ZONA_OPERACION_POR_DEFECTO)


def main(argumentos: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m panel.sync", description=__doc__)
    parser.add_argument("--una-vez", action="store_true", help="corre un solo ciclo")
    parser.add_argument("--desde", type=_dia, help="AAAA-MM-DD: carga el historial desde ese día")
    parser.add_argument(
        "--hasta", type=_dia, help="AAAA-MM-DD: último día del historial (incluido)"
    )
    opciones = parser.parse_args(argumentos)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        cfg = cargar_config(os.environ)
    except ConfigError as error:
        registro.error("La configuración no es válida: %s", error)
        return 2

    fabrica = crear_fabrica_sesiones(crear_motor(cfg.database_url))
    desde = _inicio_del_dia(opciones.desde) if opciones.desde else None
    hasta = _inicio_del_dia(opciones.hasta) + timedelta(days=1) if opciones.hasta else None

    while True:
        # En cada ciclo: los ajustes cargados en el panel valen sin reiniciar.
        cfg = config_del_ciclo(cfg, fabrica)
        resultados = ejecutar_ciclo(fabrica, sincronizadores(fabrica, cfg), desde, hasta)
        hubo_error = any(r.error for r in resultados or [])
        if opciones.una_vez or desde is not None:
            return 1 if hubo_error else 0
        time.sleep(cfg.sync_intervalo_minutos * 60)


def config_del_ciclo(base: Config, fabrica, entorno=None) -> Config:
    """El entorno con los ajustes del panel encima. Si los ajustes no se pueden
    leer o no son válidos, se sigue con lo del entorno y queda en el log."""
    entorno = dict(os.environ if entorno is None else entorno)
    try:
        efectivo, lectura = entorno_efectivo(entorno, fabrica)
        if lectura.ilegibles:
            registro.warning(
                "Ajustes cifrados con otra llave, cárguelos de nuevo en el panel: %s",
                ", ".join(lectura.ilegibles),
            )
        return cargar_config(efectivo)
    except ConfigError as error:
        registro.error("Los ajustes del panel no son válidos (%s); se usa el entorno.", error)
    except SQLAlchemyError:
        registro.exception("No se pudieron leer los ajustes del panel; se usa el entorno.")
    return base


if __name__ == "__main__":
    sys.exit(main())
