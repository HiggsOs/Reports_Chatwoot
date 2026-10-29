"""crear cuentas y reglas de asignación

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # La restricción de vigencias combina un entero (=) con un rango (&&) en un
    # mismo índice GiST, y para el entero hace falta btree_gist. Es una
    # extensión «trusted»: la puede crear el dueño de la base.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    op.create_table(
        "cuentas",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("plataforma", sa.String(length=20), nullable=False),
        sa.Column("id_externo", sa.String(length=64), nullable=False),
        sa.Column("nombre", sa.String(length=200), nullable=False),
        sa.Column("correo", sa.String(length=320), nullable=True),
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
            "plataforma IN ('cloudtalk', 'chatwoot')",
            name=op.f("ck_cuentas_plataforma_valida"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cuentas")),
        sa.UniqueConstraint(
            "plataforma", "id_externo", name="uq_cuentas_plataforma_id_externo"
        ),
    )

    op.create_table(
        "reglas_asignacion",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("cuenta_id", sa.Integer(), nullable=False),
        sa.Column("estrategia", sa.String(length=50), nullable=False),
        sa.Column("parametros", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("vigente_desde", sa.DateTime(timezone=True), nullable=False),
        sa.Column("vigente_hasta", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "creado_en",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        postgresql.ExcludeConstraint(
            (sa.column("cuenta_id"), "="),
            (sa.text("tstzrange(vigente_desde, vigente_hasta, '[)')"), "&&"),
            using="gist",
            name="ex_reglas_asignacion_vigencias_sin_superponer",
        ),
        sa.CheckConstraint(
            "vigente_hasta IS NULL OR vigente_hasta >= vigente_desde",
            name=op.f("ck_reglas_asignacion_vigencia_ordenada"),
        ),
        sa.ForeignKeyConstraint(
            ["cuenta_id"],
            ["cuentas.id"],
            name=op.f("fk_reglas_asignacion_cuenta_id_cuentas"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reglas_asignacion")),
    )


def downgrade() -> None:
    op.drop_table("reglas_asignacion")
    op.drop_table("cuentas")
    # btree_gist se deja: otras bases o tablas pueden usarla.
