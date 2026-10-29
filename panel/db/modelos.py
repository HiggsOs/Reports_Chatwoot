"""Tablas de la base de datos.

Cada etapa del plan suma sus tablas aquí y una migración de Alembic que las
crea; nunca se edita una migración ya aplicada.
"""

from sqlalchemy import CheckConstraint, String, true
from sqlalchemy.orm import Mapped, mapped_column

from panel.db.base import Base, MarcasDeTiempo
from panel.esquemas.personas import AREAS


class Persona(MarcasDeTiempo, Base):
    """Un asesor real. Reemplaza a `asesores.csv`.

    Las personas no se borran: quitarlas de la lista las desactiva, para que
    las llamadas, reglas y auditorías que las nombren sigan siendo válidas.
    """

    __tablename__ = "personas"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str | None] = mapped_column(String(200))
    correo: Mapped[str] = mapped_column(String(320), unique=True)
    area: Mapped[str] = mapped_column(String(20))
    activa: Mapped[bool] = mapped_column(default=True, server_default=true())

    __table_args__ = (
        CheckConstraint(
            "area IN (" + ", ".join(f"'{area}'" for area in AREAS) + ")",
            name="area_valida",
        ),
        CheckConstraint("correo = lower(btrim(correo))", name="correo_normalizado"),
    )
