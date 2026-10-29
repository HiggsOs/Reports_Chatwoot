"""Motor, sesiones y base declarativa de SQLAlchemy."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import DateTime, Engine, MetaData, create_engine, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

# Nombres fijos para índices y restricciones. Sin ellos Postgres inventa
# nombres distintos en cada base, y Alembic no puede borrarlos ni renombrarlos
# en una migración posterior.
CONVENCION_NOMBRES = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=CONVENCION_NOMBRES)


class MarcasDeTiempo:
    """Columnas comunes a todas las tablas. Las fechas se guardan en UTC."""

    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    actualizado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


def crear_motor(url: str) -> Engine:
    # pool_pre_ping descarta conexiones que Postgres cerró mientras la app
    # estaba inactiva, en vez de fallar en la primera consulta.
    return create_engine(url, pool_pre_ping=True)


def crear_fabrica_sesiones(motor: Engine) -> sessionmaker[Session]:
    return sessionmaker(motor, expire_on_commit=False)


def comprobar_conexion(fabrica: sessionmaker[Session]) -> None:
    """Lanza la excepción de SQLAlchemy si la base no responde."""
    with fabrica() as sesion:
        sesion.execute(text("SELECT 1"))


@contextmanager
def unidad_de_trabajo(fabrica: sessionmaker[Session]) -> Iterator[Session]:
    """Abre una sesión y confirma todo al salir, o deshace todo si hubo un error."""
    with fabrica() as sesion:
        try:
            yield sesion
            sesion.commit()
        except BaseException:
            sesion.rollback()
            raise
