"""Tablas de la base de datos.

Cada etapa del plan suma sus tablas aquí y una migración de Alembic que las
crea; nunca se edita una migración ya aplicada.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

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


PLATAFORMAS = ("cloudtalk", "chatwoot")


class Cuenta(MarcasDeTiempo, Base):
    """Una cuenta de una plataforma: un agente de CloudTalk o un usuario de
    Chatwoot. Puede ser de una persona o compartida; quién atendió lo decide su
    regla de asignación vigente.
    """

    __tablename__ = "cuentas"

    id: Mapped[int] = mapped_column(primary_key=True)
    plataforma: Mapped[str] = mapped_column(String(20))
    id_externo: Mapped[str] = mapped_column(String(64))
    nombre: Mapped[str] = mapped_column(String(200))
    correo: Mapped[str | None] = mapped_column(String(320))
    # La plataforma ya no la devuelve. Se conserva por su historia.
    activa: Mapped[bool] = mapped_column(default=True, server_default=true())

    reglas: Mapped[list["ReglaAsignacion"]] = relationship(
        back_populates="cuenta", order_by="ReglaAsignacion.vigente_desde"
    )

    __table_args__ = (
        UniqueConstraint("plataforma", "id_externo", name="uq_cuentas_plataforma_id_externo"),
        CheckConstraint(
            "plataforma IN (" + ", ".join(f"'{p}'" for p in PLATAFORMAS) + ")",
            name="plataforma_valida",
        ),
    )


class ReglaAsignacion(Base):
    """Qué estrategia reparte una cuenta, con qué parámetros y desde cuándo.

    Las reglas no se editan ni se borran: un cambio crea una regla nueva y
    cierra la anterior, así cada interacción se explica con la regla que regía
    en su fecha. Una regla corregida el mismo día queda con vigencia vacía
    (desde = hasta) y nunca rige.
    """

    __tablename__ = "reglas_asignacion"

    id: Mapped[int] = mapped_column(primary_key=True)
    cuenta_id: Mapped[int] = mapped_column(ForeignKey("cuentas.id", ondelete="RESTRICT"))
    estrategia: Mapped[str] = mapped_column(String(50))
    # Validados con el modelo Pydantic de la estrategia al guardar y al leer.
    parametros: Mapped[dict[str, Any]] = mapped_column(JSONB)
    vigente_desde: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    vigente_hasta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    creado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    cuenta: Mapped[Cuenta] = relationship(back_populates="reglas")

    __table_args__ = (
        CheckConstraint(
            "vigente_hasta IS NULL OR vigente_hasta >= vigente_desde",
            name="vigencia_ordenada",
        ),
        # Una sola regla vigente por cuenta en cada momento.
        ExcludeConstraint(
            ("cuenta_id", "="),
            (func.tstzrange(vigente_desde, vigente_hasta, "[)"), "&&"),
            using="gist",
            name="ex_reglas_asignacion_vigencias_sin_superponer",
        ),
    )
