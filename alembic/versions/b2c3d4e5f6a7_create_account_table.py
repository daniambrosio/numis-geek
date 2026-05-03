"""create account table

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-02 00:01:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision: str = 'b2c3d4e5f6a7'
down_revision: str | None = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'account',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('workspace_id', sa.String(36), sa.ForeignKey('workspace.id'), nullable=False),
        sa.Column('financial_institution_id', sa.String(36), sa.ForeignKey('financial_institution.id'), nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('account_type', sa.Enum('checking', 'investment', name='accounttype'), nullable=False),
        sa.Column('currency', sa.Enum('BRL', 'USD', name='currency'), nullable=False),
        sa.Column('opening_balance', sa.Numeric(18, 4), nullable=True),
        sa.Column('account_info', sa.String(255), nullable=True),
        sa.Column('is_active', sa.Boolean, nullable=False, default=True),
        sa.Column('created_at', sa.DateTime, nullable=False),
        sa.Column('updated_at', sa.DateTime, nullable=False),
        sa.Column('created_by', sa.String(36), nullable=True),
        sa.Column('updated_by', sa.String(36), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('account')
