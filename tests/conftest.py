"""Fixtures de base de datos.

Las pruebas que usan `motor` o `fabrica` corren contra un PostgreSQL real
indicado en TEST_DATABASE_URL, y se saltan si no está definida. La base de
pruebas se vacía al empezar, así que su nombre tiene que contener «test».
"""

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config as ConfigAlembic
from sqlalchemy import Engine, create_engine, make_url, text
from sqlalchemy.orm import sessionmaker

from config import normalizar_url_bd

RAIZ = Path(__file__).resolve().parents[1]


def configuracion_alembic(conexion) -> ConfigAlembic:
    configuracion = ConfigAlembic(str(RAIZ / "alembic.ini"))
    configuracion.attributes["conexion"] = conexion
    return configuracion


@pytest.fixture(scope="session")
def motor() -> Engine:
    bruta = os.environ.get("TEST_DATABASE_URL", "")
    if not bruta.strip():
        pytest.skip("Defina TEST_DATABASE_URL para correr las pruebas de base de datos.")

    url = normalizar_url_bd(bruta)
    if "test" not in (make_url(url).database or ""):
        pytest.fail(
            "TEST_DATABASE_URL debe apuntar a una base cuyo nombre contenga "
            "«test»: las pruebas la vacían."
        )

    motor = create_engine(url)
    with motor.begin() as conexion:
        conexion.execute(text("DROP SCHEMA public CASCADE"))
        conexion.execute(text("CREATE SCHEMA public"))
        command.upgrade(configuracion_alembic(conexion), "head")
    yield motor
    motor.dispose()


@pytest.fixture
def fabrica(motor: Engine):
    """Fábrica de sesiones cuyo trabajo se deshace al terminar cada prueba,
    aunque el código bajo prueba haga commit."""
    conexion = motor.connect()
    transaccion = conexion.begin()
    yield sessionmaker(
        bind=conexion,
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
    )
    transaccion.rollback()
    conexion.close()
