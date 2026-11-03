"""ligar las conversaciones abandonadas a la conversación que finalizan

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("conversaciones", sa.Column("continua_de_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f("fk_conversaciones_continua_de_id_conversaciones"),
        "conversaciones",
        "conversaciones",
        ["continua_de_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_conversaciones_continua_de_id", "conversaciones", ["continua_de_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_conversaciones_continua_de_id", table_name="conversaciones")
    op.drop_constraint(
        op.f("fk_conversaciones_continua_de_id_conversaciones"),
        "conversaciones",
        type_="foreignkey",
    )
    op.drop_column("conversaciones", "continua_de_id")
