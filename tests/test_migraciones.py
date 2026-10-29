from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect

from panel.db import modelos  # noqa: F401
from panel.db.base import Base
from tests.conftest import configuracion_alembic

TABLAS = ("personas", "cuentas", "reglas_asignacion")


def test_los_modelos_coinciden_con_las_migraciones(motor):
    # Si falla, se cambió un modelo sin escribir su migración.
    with motor.connect() as conexion:
        diferencias = compare_metadata(
            MigrationContext.configure(conexion, opts={"compare_type": True}),
            Base.metadata,
        )
    assert diferencias == []


def test_las_migraciones_se_deshacen_y_se_rehacen(motor):
    with motor.begin() as conexion:
        command.downgrade(configuracion_alembic(conexion), "base")
        assert not set(TABLAS) & set(inspect(conexion).get_table_names())

        command.upgrade(configuracion_alembic(conexion), "head")
        assert set(TABLAS) <= set(inspect(conexion).get_table_names())
