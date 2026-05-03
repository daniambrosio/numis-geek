"""create asset, fixed_income_asset and physical_asset tables

Revision ID: d4e5f6a7b8c9
Revises: b2c3d4e5f6a7
Create Date: 2026-05-03 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision: str = 'd4e5f6a7b8c9'
down_revision: str | None = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


_ASSET_CLASS_VALUES = (
    'STOCK_BR', 'STOCK_US', 'FII', 'ETF', 'REIT', 'BOND',
    'FIXED_INCOME', 'FUND', 'CRYPTO', 'REAL_ESTATE', 'VEHICLE',
)
_INDEXER_VALUES = ('CDI', 'IPCA', 'SELIC', 'PREFIXED', 'USD')


def upgrade() -> None:
    op.create_table(
        'asset',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('workspace_id', sa.String(36), sa.ForeignKey('workspace.id'), nullable=False),
        sa.Column(
            'financial_institution_id',
            sa.String(36),
            sa.ForeignKey('financial_institution.id', ondelete='RESTRICT'),
            nullable=False,
        ),
        sa.Column('asset_class', sa.Enum(*_ASSET_CLASS_VALUES, name='assetclass'), nullable=False),
        sa.Column('subtype', sa.String(100), nullable=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('ticker', sa.String(20), nullable=True),
        sa.Column('cnpj', sa.String(18), nullable=True),
        sa.Column('currency', sa.Enum('BRL', 'USD', name='currency'), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, default=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('created_by', sa.String(36), nullable=True),
        sa.Column('updated_by', sa.String(36), nullable=True),
    )
    # Partial unique index — same workspace + ticker + custodian rejected regardless of class,
    # to catch class typos (e.g., PETR4 mistakenly registered as STOCK_US instead of STOCK_BR).
    # NULL tickers (FIXED_INCOME, REAL_ESTATE, VEHICLE) are unconstrained.
    op.create_index(
        'ux_asset_workspace_ticker_fi',
        'asset',
        ['workspace_id', 'ticker', 'financial_institution_id'],
        unique=True,
        sqlite_where=sa.text('ticker IS NOT NULL'),
        postgresql_where=sa.text('ticker IS NOT NULL'),
    )

    op.create_table(
        'fixed_income_asset',
        sa.Column('asset_id', sa.String(36), sa.ForeignKey('asset.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('issuer', sa.String(255), nullable=False),
        sa.Column('issue_date', sa.Date(), nullable=True),
        sa.Column('maturity_date', sa.Date(), nullable=False),
        sa.Column('indexer', sa.Enum(*_INDEXER_VALUES, name='fixedincomeindexer'), nullable=False),
        sa.Column('rate', sa.Numeric(8, 4), nullable=False),
        sa.Column('face_value', sa.Numeric(15, 2), nullable=True),
    )

    op.create_table(
        'physical_asset',
        sa.Column('asset_id', sa.String(36), sa.ForeignKey('asset.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('address', sa.String(500), nullable=True),
        sa.Column('city', sa.String(100), nullable=True),
        sa.Column('state', sa.String(50), nullable=True),
        sa.Column('country', sa.String(2), nullable=True),
        sa.Column('area_m2', sa.Numeric(10, 2), nullable=True),
        sa.Column('registration_number', sa.String(100), nullable=True),
        sa.Column('make', sa.String(100), nullable=True),
        sa.Column('model', sa.String(100), nullable=True),
        sa.Column('year', sa.Integer(), nullable=True),
        sa.Column('license_plate', sa.String(20), nullable=True),
        sa.Column('chassis', sa.String(50), nullable=True),
    )


def downgrade() -> None:
    op.drop_table('physical_asset')
    op.drop_table('fixed_income_asset')
    op.drop_index('ux_asset_workspace_ticker_fi', table_name='asset')
    op.drop_table('asset')
    bind = op.get_bind()
    if bind.dialect.name == 'postgresql':
        op.execute("DROP TYPE IF EXISTS fixedincomeindexer")
        op.execute("DROP TYPE IF EXISTS assetclass")
