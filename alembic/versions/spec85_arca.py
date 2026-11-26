"""spec 85 — metas ARCA

- asset.arca_category / asset.arca_subcategory (String(32), nullable): override
  manual da classificação ARCA. NULL = regra derivada (services/arca.py).
- target_allocation.min_pct / max_pct (nullable): banda da letra ARCA.
- target_allocation.dimension ganha ARCA e ARCA_SUB.

SQLite: troca do enum via batch_alter_table.

Revision ID: spec85_arca
Revises: spec84_original_currency_str
Create Date: 2026-11-26
"""
from alembic import op
import sqlalchemy as sa


revision = "spec85_arca"
down_revision = "spec84_original_currency_str"
branch_labels = None
depends_on = None

_OLD = sa.Enum("CLASS", "COUNTRY", name="targetallocationdimension")
_NEW = sa.Enum("CLASS", "COUNTRY", "ARCA", "ARCA_SUB", name="targetallocationdimension")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TYPE targetallocationdimension ADD VALUE IF NOT EXISTS 'ARCA'")
        op.execute("ALTER TYPE targetallocationdimension ADD VALUE IF NOT EXISTS 'ARCA_SUB'")
    with op.batch_alter_table("target_allocation") as batch:
        if bind.dialect.name != "postgresql":
            batch.alter_column(
                "dimension", existing_type=_OLD, type_=_NEW, existing_nullable=False,
            )
        batch.add_column(sa.Column("min_pct", sa.Numeric(7, 4), nullable=True))
        batch.add_column(sa.Column("max_pct", sa.Numeric(7, 4), nullable=True))
    with op.batch_alter_table("asset") as batch:
        batch.add_column(sa.Column("arca_category", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("arca_subcategory", sa.String(length=32), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    n = bind.execute(sa.text(
        "SELECT COUNT(*) FROM target_allocation WHERE dimension IN ('ARCA', 'ARCA_SUB')"
    )).scalar()
    if n:
        raise RuntimeError(f"{n} metas ARCA gravadas — apague antes do downgrade")
    with op.batch_alter_table("asset") as batch:
        batch.drop_column("arca_subcategory")
        batch.drop_column("arca_category")
    with op.batch_alter_table("target_allocation") as batch:
        batch.drop_column("max_pct")
        batch.drop_column("min_pct")
        if bind.dialect.name != "postgresql":
            batch.alter_column(
                "dimension", existing_type=_NEW, type_=_OLD, existing_nullable=False,
            )
