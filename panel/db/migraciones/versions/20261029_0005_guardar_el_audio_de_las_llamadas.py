"""guardar el audio de las llamadas

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('audios_pendientes',
    sa.Column('llamada_id', sa.Integer(), nullable=False),
    sa.Column('contenido', sa.LargeBinary(), nullable=False),
    sa.Column('intentos', sa.Integer(), server_default='0', nullable=False),
    sa.Column('ultimo_error', sa.Text(), nullable=True),
    sa.Column('creado_en', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['llamada_id'], ['llamadas.id'], name=op.f('fk_audios_pendientes_llamada_id_llamadas'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('llamada_id', name=op.f('pk_audios_pendientes'))
    )
    op.add_column('llamadas', sa.Column('audio_estado', sa.String(length=20), nullable=True))
    op.add_column('llamadas', sa.Column('audio_ruta', sa.Text(), nullable=True))
    op.add_column('llamadas', sa.Column('audio_canales', sa.Integer(), nullable=True))
    op.add_column('llamadas', sa.Column('audio_bytes', sa.Integer(), nullable=True))
    op.add_column('llamadas', sa.Column('audio_guardado_en', sa.DateTime(timezone=True), nullable=True))
    # Los estados se copian aquí a propósito: la migración describe el esquema
    # de su momento.
    op.create_check_constraint(
        op.f("ck_llamadas_audio_estado_valido"),
        "llamadas",
        "audio_estado IS NULL OR audio_estado IN "
        "('guardado', 'pendiente', 'sin_grabacion', 'vencido', 'eliminado')",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_llamadas_audio_estado_valido"), "llamadas", type_="check")
    op.drop_column('llamadas', 'audio_guardado_en')
    op.drop_column('llamadas', 'audio_bytes')
    op.drop_column('llamadas', 'audio_canales')
    op.drop_column('llamadas', 'audio_ruta')
    op.drop_column('llamadas', 'audio_estado')
    op.drop_table('audios_pendientes')
