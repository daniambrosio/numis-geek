"""extend AssetClass enum with PRIVATE_PENSION, FGTS, CASH

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-05-03 12:00:00.000000

SQLite enums are CHECK constraints embedded in the column DDL — to add a value
we must recreate the column via batch_alter_table. On Postgres we use
`ALTER TYPE ... ADD VALUE`, which is the canonical, non-rewriting path.
"""
from alembic import op
import sqlalchemy as sa

revision: str = 'e5f6a7b8c9d0'
down_revision: str | None = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


_OLD_VALUES = (
    'STOCK_BR', 'STOCK_US', 'FII', 'ETF', 'REIT', 'BOND',
    'FIXED_INCOME', 'FUND', 'CRYPTO', 'REAL_ESTATE', 'VEHICLE',
)
_NEW_VALUES = _OLD_VALUES + ('PRIVATE_PENSION', 'FGTS', 'CASH')


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == 'postgresql':
        # Postgres ENUM types support in-place ADD VALUE.
        for v in ('PRIVATE_PENSION', 'FGTS', 'CASH'):
            op.execute(f"ALTER TYPE assetclass ADD VALUE IF NOT EXISTS '{v}'")
    else:
        # SQLite stores enums as a CHECK constraint inside the column DDL —
        # batch_alter_table rebuilds the table to swap the constraint.
        with op.batch_alter_table('asset') as batch_op:
            batch_op.alter_column(
                'asset_class',
                existing_type=sa.Enum(*_OLD_VALUES, name='assetclass'),
                type_=sa.Enum(*_NEW_VALUES, name='assetclass'),
                existing_nullable=False,
            )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == 'postgresql':
        # Postgres can't DROP a single enum value cleanly; recreate the type.
        # If any rows reference the new values they must be migrated first.
        op.execute("ALTER TYPE assetclass RENAME TO assetclass_old")
        op.execute(
            "CREATE TYPE assetclass AS ENUM ("
            + ", ".join(f"'{v}'" for v in _OLD_VALUES)
            + ")"
        )
        op.execute(
            "ALTER TABLE asset ALTER COLUMN asset_class TYPE assetclass "
            "USING asset_class::text::assetclass"
        )
        op.execute("DROP TYPE assetclass_old")
    else:
        with op.batch_alter_table('asset') as batch_op:
            batch_op.alter_column(
                'asset_class',
                existing_type=sa.Enum(*_NEW_VALUES, name='assetclass'),
                type_=sa.Enum(*_OLD_VALUES, name='assetclass'),
                existing_nullable=False,
            )
