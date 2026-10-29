"""transcribir las llamadas

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('trabajos_transcripcion',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('llamada_id', sa.Integer(), nullable=False),
    sa.Column('proveedor', sa.String(length=50), nullable=True),
    sa.Column('estado', sa.String(length=20), server_default='pendiente', nullable=False),
    sa.Column('intentos', sa.Integer(), server_default='0', nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('creado_en', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('actualizado_en', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("estado IN ('pendiente', 'en_proceso', 'hecho', 'error')", name=op.f('ck_trabajos_transcripcion_estado_valido')),
    sa.ForeignKeyConstraint(['llamada_id'], ['llamadas.id'], name=op.f('fk_trabajos_transcripcion_llamada_id_llamadas'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_trabajos_transcripcion'))
    )
    op.create_index('ix_trabajos_transcripcion_estado', 'trabajos_transcripcion', ['estado', 'creado_en'], unique=False)
    op.create_index('uq_trabajos_transcripcion_uno_abierto', 'trabajos_transcripcion', ['llamada_id'], unique=True, postgresql_where=sa.text("estado IN ('pendiente', 'en_proceso')"))
    op.create_table('transcripciones',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('llamada_id', sa.Integer(), nullable=False),
    sa.Column('proveedor', sa.String(length=50), nullable=False),
    sa.Column('modelo', sa.String(length=100), nullable=False),
    sa.Column('idioma', sa.String(length=10), nullable=False),
    sa.Column('canales_audio', sa.String(length=20), nullable=False),
    sa.Column('segmentos', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('texto', sa.Text(), nullable=False),
    sa.Column('duracion_audio', sa.Float(), nullable=True),
    sa.Column('costo_estimado', sa.Numeric(precision=12, scale=4), nullable=True),
    sa.Column('principal', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('creado_en', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['llamada_id'], ['llamadas.id'], name=op.f('fk_transcripciones_llamada_id_llamadas'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_transcripciones'))
    )
    op.create_index('ix_transcripciones_llamada_id', 'transcripciones', ['llamada_id'], unique=False)
    op.create_index('uq_transcripciones_una_principal', 'transcripciones', ['llamada_id'], unique=True, postgresql_where=sa.text('principal'))
    op.add_column('llamadas', sa.Column('transcripcion_estado', sa.String(length=20), nullable=True))
    op.create_check_constraint(
        op.f("ck_llamadas_transcripcion_estado_valido"),
        "llamadas",
        "transcripcion_estado IS NULL OR transcripcion_estado IN ('transcrita', 'eliminada')",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_llamadas_transcripcion_estado_valido"), "llamadas", type_="check")
    op.drop_column('llamadas', 'transcripcion_estado')
    op.drop_index('uq_transcripciones_una_principal', table_name='transcripciones', postgresql_where=sa.text('principal'))
    op.drop_index('ix_transcripciones_llamada_id', table_name='transcripciones')
    op.drop_table('transcripciones')
    op.drop_index('uq_trabajos_transcripcion_uno_abierto', table_name='trabajos_transcripcion', postgresql_where=sa.text("estado IN ('pendiente', 'en_proceso')"))
    op.drop_index('ix_trabajos_transcripcion_estado', table_name='trabajos_transcripcion')
    op.drop_table('trabajos_transcripcion')
