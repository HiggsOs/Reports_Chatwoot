"""guardar ajustes del panel y cobros de transcripción

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('ajustes',
    sa.Column('clave', sa.String(length=80), nullable=False),
    sa.Column('valor', sa.Text(), nullable=False),
    sa.Column('secreto', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('actualizado_en', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('clave', name=op.f('pk_ajustes'))
    )
    op.create_table('cobros_transcripcion',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('mes', sa.Date(), nullable=False),
    sa.Column('proveedor', sa.String(length=50), nullable=False),
    sa.Column('modelo', sa.String(length=100), nullable=False),
    sa.Column('minutos', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('usd', sa.Numeric(precision=12, scale=4), nullable=False),
    sa.Column('creado_en', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('actualizado_en', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('extract(day from mes) = 1', name=op.f('ck_cobros_transcripcion_mes_desde_el_dia_uno')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_cobros_transcripcion')),
    sa.UniqueConstraint('mes', 'proveedor', 'modelo', name='uq_cobros_transcripcion_mes_modelo')
    )


def downgrade() -> None:
    op.drop_table('cobros_transcripcion')
    op.drop_table('ajustes')
