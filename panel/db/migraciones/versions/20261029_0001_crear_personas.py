"""crear personas

Revision ID: 0001
Revises:
Create Date: 2026-10-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Las áreas se copian aquí a propósito: una migración describe el esquema
    # de su momento y no debe cambiar si después cambia el código.
    op.create_table(
        "personas",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nombre", sa.String(length=200), nullable=True),
        sa.Column("correo", sa.String(length=320), nullable=False),
        sa.Column("area", sa.String(length=20), nullable=False),
        sa.Column("activa", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "creado_en",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "actualizado_en",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "area IN ('Comercial', 'RDC')", name=op.f("ck_personas_area_valida")
        ),
        sa.CheckConstraint(
            "correo = lower(btrim(correo))", name=op.f("ck_personas_correo_normalizado")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_personas")),
        sa.UniqueConstraint("correo", name=op.f("uq_personas_correo")),
    )


def downgrade() -> None:
    op.drop_table("personas")
