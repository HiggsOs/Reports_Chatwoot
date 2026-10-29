"""crear interacciones

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('clientes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('telefono', sa.String(length=32), nullable=False),
    sa.Column('telefono_original', sa.String(length=64), nullable=False),
    sa.Column('nombre', sa.String(length=200), nullable=True),
    sa.Column('revisar', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('creado_en', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('actualizado_en', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_clientes')),
    sa.UniqueConstraint('telefono', name=op.f('uq_clientes_telefono'))
    )
    op.create_table('puntos_sincronizacion',
    sa.Column('fuente', sa.String(length=50), nullable=False),
    sa.Column('hasta', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ultimo_intento', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ultimo_exito', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ultimo_error', sa.Text(), nullable=True),
    sa.Column('resumen', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.PrimaryKeyConstraint('fuente', name=op.f('pk_puntos_sincronizacion'))
    )
    op.create_table('conversaciones',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('id_externo', sa.String(length=64), nullable=False),
    sa.Column('cuenta_id', sa.Integer(), nullable=True),
    sa.Column('inicio', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ultima_actividad', sa.DateTime(timezone=True), nullable=True),
    sa.Column('canal', sa.String(length=200), nullable=False),
    sa.Column('estado', sa.String(length=20), nullable=False),
    sa.Column('etiquetas', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('direccion', sa.String(length=20), nullable=False),
    sa.Column('cierre', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cierre_aproximado', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('datos_origen', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('asignacion', sa.String(length=20), server_default='automatica', nullable=False),
    sa.Column('motivo_asignacion', sa.Text(), server_default='', nullable=False),
    sa.Column('persona_id', sa.Integer(), nullable=True),
    sa.Column('regla_id', sa.Integer(), nullable=True),
    sa.Column('cliente_id', sa.Integer(), nullable=True),
    sa.Column('creado_en', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('actualizado_en', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("asignacion IN ('automatica', 'manual')", name=op.f('ck_conversaciones_asignacion_valida')),
    sa.ForeignKeyConstraint(['cliente_id'], ['clientes.id'], name=op.f('fk_conversaciones_cliente_id_clientes'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['cuenta_id'], ['cuentas.id'], name=op.f('fk_conversaciones_cuenta_id_cuentas'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['persona_id'], ['personas.id'], name=op.f('fk_conversaciones_persona_id_personas'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['regla_id'], ['reglas_asignacion.id'], name=op.f('fk_conversaciones_regla_id_reglas_asignacion'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_conversaciones')),
    sa.UniqueConstraint('id_externo', name=op.f('uq_conversaciones_id_externo'))
    )
    op.create_index('ix_conversaciones_cliente_id', 'conversaciones', ['cliente_id'], unique=False)
    op.create_index('ix_conversaciones_cuenta_id_inicio', 'conversaciones', ['cuenta_id', 'inicio'], unique=False)
    op.create_index('ix_conversaciones_inicio', 'conversaciones', ['inicio'], unique=False)
    op.create_index('ix_conversaciones_persona_id', 'conversaciones', ['persona_id'], unique=False)
    op.create_table('llamadas',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('id_externo', sa.String(length=64), nullable=False),
    sa.Column('cuenta_id', sa.Integer(), nullable=False),
    sa.Column('inicio', sa.DateTime(timezone=True), nullable=False),
    sa.Column('duracion_s', sa.Integer(), nullable=True),
    sa.Column('direccion', sa.String(length=20), nullable=False),
    sa.Column('grabada', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('enlace_plataforma', sa.Text(), nullable=True),
    sa.Column('datos_origen', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('asignacion', sa.String(length=20), server_default='automatica', nullable=False),
    sa.Column('motivo_asignacion', sa.Text(), server_default='', nullable=False),
    sa.Column('persona_id', sa.Integer(), nullable=True),
    sa.Column('regla_id', sa.Integer(), nullable=True),
    sa.Column('cliente_id', sa.Integer(), nullable=True),
    sa.Column('creado_en', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('actualizado_en', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("asignacion IN ('automatica', 'manual')", name=op.f('ck_llamadas_asignacion_valida')),
    sa.ForeignKeyConstraint(['cliente_id'], ['clientes.id'], name=op.f('fk_llamadas_cliente_id_clientes'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['cuenta_id'], ['cuentas.id'], name=op.f('fk_llamadas_cuenta_id_cuentas'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['persona_id'], ['personas.id'], name=op.f('fk_llamadas_persona_id_personas'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['regla_id'], ['reglas_asignacion.id'], name=op.f('fk_llamadas_regla_id_reglas_asignacion'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_llamadas')),
    sa.UniqueConstraint('id_externo', name=op.f('uq_llamadas_id_externo'))
    )
    op.create_index('ix_llamadas_cliente_id', 'llamadas', ['cliente_id'], unique=False)
    op.create_index('ix_llamadas_cuenta_id_inicio', 'llamadas', ['cuenta_id', 'inicio'], unique=False)
    op.create_index('ix_llamadas_inicio', 'llamadas', ['inicio'], unique=False)
    op.create_index('ix_llamadas_persona_id', 'llamadas', ['persona_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_llamadas_persona_id', table_name='llamadas')
    op.drop_index('ix_llamadas_inicio', table_name='llamadas')
    op.drop_index('ix_llamadas_cuenta_id_inicio', table_name='llamadas')
    op.drop_index('ix_llamadas_cliente_id', table_name='llamadas')
    op.drop_table('llamadas')
    op.drop_index('ix_conversaciones_persona_id', table_name='conversaciones')
    op.drop_index('ix_conversaciones_inicio', table_name='conversaciones')
    op.drop_index('ix_conversaciones_cuenta_id_inicio', table_name='conversaciones')
    op.drop_index('ix_conversaciones_cliente_id', table_name='conversaciones')
    op.drop_table('conversaciones')
    op.drop_table('puntos_sincronizacion')
    op.drop_table('clientes')
