"""Entorno de Alembic.

La URL se toma de `sqlalchemy.url` si quien llama la fijó (las pruebas lo
hacen) y, si no, de la variable DATABASE_URL.
"""

import os

from alembic import context
from sqlalchemy import engine_from_config, pool, text

from config import ConfigError, normalizar_url_bd
from panel.db import modelos  # noqa: F401  (registra las tablas en el metadata)
from panel.db.base import Base

configuracion = context.config
target_metadata = Base.metadata

# La app y el proceso de sincronización aplican las migraciones al arrancar. Si
# arrancan a la vez, este bloqueo hace que el segundo espere al primero en vez
# de intentar crear las mismas tablas.
CLAVE_BLOQUEO_MIGRACIONES = 7_420_001


def _url() -> str:
    fijada = configuracion.get_main_option("sqlalchemy.url")
    if fijada:
        return fijada
    bruta = os.environ.get("DATABASE_URL", "")
    if not bruta.strip():
        raise ConfigError("Falta la variable de entorno DATABASE_URL.")
    return normalizar_url_bd(bruta)


def ejecutar_sin_conexion() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def ejecutar_con_conexion() -> None:
    conexion_existente = configuracion.attributes.get("conexion")
    if conexion_existente is not None:
        _migrar(conexion_existente)
        return

    motor = engine_from_config(
        {"sqlalchemy.url": _url()}, prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with motor.connect() as conexion:
        _migrar(conexion)


def _migrar(conexion) -> None:
    context.configure(
        connection=conexion, target_metadata=target_metadata, compare_type=True
    )
    with context.begin_transaction():
        conexion.execute(
            text("SELECT pg_advisory_xact_lock(:clave)"),
            {"clave": CLAVE_BLOQUEO_MIGRACIONES},
        )
        context.run_migrations()


if context.is_offline_mode():
    ejecutar_sin_conexion()
else:
    ejecutar_con_conexion()
