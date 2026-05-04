"""create lancamento table

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-05-03 18:00:00.000000

Fresh CREATE TABLE — no batch_alter_table needed (it's only required for
nullability/enum changes on SQLite).
"""
from alembic import op
import sqlalchemy as sa

revision: str = 'f6a7b8c9d0e1'
down_revision: str | None = 'e5f6a7b8c9d0'
branch_labels = None
depends_on = None


_LANCAMENTO_TYPE_VALUES = (
    'COMPRA',
    'VENDA',
    'DIVIDENDO',
    'JUROS',
    'JCP',
    'COME_COTAS',
    'BONIFICACAO',
    'SUBSCRICAO',
)


def upgrade() -> None:
    op.create_table(
        'lancamento',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('workspace_id', sa.String(36), sa.ForeignKey('workspace.id'), nullable=False),
        sa.Column('asset_id', sa.String(36), sa.ForeignKey('asset.id'), nullable=False),
        sa.Column(
            'type',
            sa.Enum(*_LANCAMENTO_TYPE_VALUES, name='lancamentotype'),
            nullable=False,
        ),
        sa.Column('event_date', sa.Date(), nullable=False),
        sa.Column('settlement_date', sa.Date(), nullable=True),
        sa.Column('quantity', sa.Numeric(18, 8), nullable=True),
        sa.Column('unit_price', sa.Numeric(18, 8), nullable=True),
        sa.Column('gross_amount', sa.Numeric(18, 2), nullable=True),
        sa.Column('fee', sa.Numeric(18, 2), nullable=True),
        sa.Column('tax', sa.Numeric(18, 2), nullable=True),
        sa.Column('net_amount', sa.Numeric(18, 2), nullable=False),
        sa.Column('currency', sa.Enum('BRL', 'USD', name='currency'), nullable=False),
        sa.Column('fx_rate', sa.Numeric(18, 8), nullable=False, server_default='1.0'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('created_by', sa.String(36), nullable=True),
        sa.Column('updated_by', sa.String(36), nullable=True),
    )
    op.create_index(
        'ix_lancamento_workspace_event_date',
        'lancamento',
        ['workspace_id', 'event_date'],
    )
    op.create_index(
        'ix_lancamento_asset_event_date',
        'lancamento',
        ['asset_id', 'event_date'],
    )
    op.create_index(
        'ix_lancamento_workspace_type_event_date',
        'lancamento',
        ['workspace_id', 'type', 'event_date'],
    )


def downgrade() -> None:
    op.drop_index('ix_lancamento_workspace_type_event_date', table_name='lancamento')
    op.drop_index('ix_lancamento_asset_event_date', table_name='lancamento')
    op.drop_index('ix_lancamento_workspace_event_date', table_name='lancamento')
    op.drop_table('lancamento')
    bind = op.get_bind()
    if bind.dialect.name == 'postgresql':
        op.execute("DROP TYPE IF EXISTS lancamentotype")
