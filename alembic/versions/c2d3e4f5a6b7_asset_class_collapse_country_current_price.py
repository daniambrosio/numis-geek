"""asset_class collapse 14→11 + country + current_price + price_updated_at

Revision ID: c2d3e4f5a6b7
Revises: b1a2c3d4e5f6
Create Date: 2026-05-17 19:30:00.000000

Spec 09 cleanups on Asset:

1. Collapse asset_class enum 14→11. The "BR vs US" distinction moves
   out of the class into a dedicated `country` field. Merges:
   - STOCK_BR + STOCK_US → STOCK
   - FII + REIT → REIT
   - BOND + FIXED_INCOME → FIXED_INCOME

2. Add `country` (ISO-2, NOT NULL after backfill).

3. Add `current_price` (Numeric, nullable) + `price_updated_at`
   (DateTime, nullable). The user starts populating these via the UI
   to unlock Atual / Valor / Variação / Rentabilidade columns.

Country backfill rules — see specs/09. Asset Cleanup.md §Backfill rules.

Downgrade reverses everything: re-explodes the 3 merged classes back
to the 5 legacy codes (STOCK→STOCK_BR for BR rows, STOCK→STOCK_US for
US rows, etc.), drops country / current_price / price_updated_at.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "c2d3e4f5a6b7"
down_revision: str | None = "b1a2c3d4e5f6"
branch_labels = None
depends_on = None

_OLD_VALUES = (
    "STOCK_BR", "STOCK_US", "FII", "ETF", "REIT", "BOND", "FIXED_INCOME",
    "FUND", "CRYPTO", "REAL_ESTATE", "VEHICLE", "PRIVATE_PENSION",
    "FGTS", "CASH",
)
_NEW_VALUES = (
    "STOCK", "REIT", "ETF", "FIXED_INCOME", "FUND", "CRYPTO",
    "REAL_ESTATE", "VEHICLE", "CASH", "FGTS", "PRIVATE_PENSION",
)


def _backfill_country_and_class() -> None:
    """Per spec backfill table. Idempotent (skips already-set country)."""
    bind = op.get_bind()
    # Direct mappings (country independent of currency)
    direct = [
        ("STOCK_BR", "STOCK", "BR"),
        ("STOCK_US", "STOCK", "US"),
        ("FII", "REIT", "BR"),
        ("REIT", "REIT", "US"),
        ("BOND", "FIXED_INCOME", "US"),
        ("FIXED_INCOME", "FIXED_INCOME", "BR"),
        ("FUND", "FUND", "BR"),
        ("REAL_ESTATE", "REAL_ESTATE", "BR"),
        ("VEHICLE", "VEHICLE", "BR"),
        ("FGTS", "FGTS", "BR"),
        ("PRIVATE_PENSION", "PRIVATE_PENSION", "BR"),
    ]
    for old, new, ctry in direct:
        bind.execute(sa.text(
            "UPDATE asset SET country = :c, asset_class = :n "
            "WHERE asset_class = :o AND (country IS NULL OR country = '')"
        ), {"c": ctry, "n": new, "o": old})

    # Currency-driven (ETF, CRYPTO, CASH): country derived from asset.currency
    currency_driven = ["ETF", "CRYPTO", "CASH"]
    for cls in currency_driven:
        bind.execute(sa.text(
            "UPDATE asset SET country = CASE currency WHEN 'USD' THEN 'US' ELSE 'BR' END "
            "WHERE asset_class = :c AND (country IS NULL OR country = '')"
        ), {"c": cls})


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    # ── Step 1: add columns (all nullable initially) ─────────────────────────
    op.add_column("asset", sa.Column("country", sa.String(2), nullable=True))
    op.add_column("asset", sa.Column("current_price", sa.Numeric(18, 8), nullable=True))
    op.add_column("asset", sa.Column("price_updated_at", sa.DateTime, nullable=True))

    # ── Step 2: backfill country + remap asset_class to new codes ────────────
    _backfill_country_and_class()

    # Safety: every row must now have country set
    n_missing = bind.execute(sa.text(
        "SELECT COUNT(*) FROM asset WHERE country IS NULL OR country = ''"
    )).scalar()
    if n_missing:
        raise RuntimeError(
            f"{n_missing} assets still lack country after backfill. "
            "Extend the migration's backfill table or inspect the affected rows."
        )

    # ── Step 3: rewrite the asset_class enum to the 11 new codes ─────────────
    if is_postgres:
        op.execute(
            "CREATE TYPE assetclass_new AS ENUM ("
            + ", ".join(f"'{v}'" for v in _NEW_VALUES) + ")"
        )
        op.execute(
            "ALTER TABLE asset ALTER COLUMN asset_class TYPE assetclass_new "
            "USING asset_class::text::assetclass_new"
        )
        op.execute("DROP TYPE assetclass")
        op.execute("ALTER TYPE assetclass_new RENAME TO assetclass")
    else:
        with op.batch_alter_table("asset") as batch_op:
            batch_op.alter_column(
                "asset_class",
                existing_type=sa.Enum(*_OLD_VALUES, name="assetclass"),
                type_=sa.Enum(*_NEW_VALUES, name="assetclass"),
                existing_nullable=False,
            )

    # ── Step 4: set country NOT NULL ─────────────────────────────────────────
    with op.batch_alter_table("asset") as batch_op:
        batch_op.alter_column("country", existing_type=sa.String(2), nullable=False)


def downgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    # ── Step 1: re-explode merged classes back to legacy 14 ──────────────────
    # STOCK + country → STOCK_BR / STOCK_US
    bind.execute(sa.text(
        "UPDATE asset SET asset_class = CASE country "
        "WHEN 'BR' THEN 'STOCK_BR' WHEN 'US' THEN 'STOCK_US' "
        "ELSE 'STOCK_BR' END WHERE asset_class = 'STOCK'"
    ))
    # REIT + country → FII / REIT
    bind.execute(sa.text(
        "UPDATE asset SET asset_class = CASE country "
        "WHEN 'BR' THEN 'FII' WHEN 'US' THEN 'REIT' "
        "ELSE 'FII' END WHERE asset_class = 'REIT'"
    ))
    # FIXED_INCOME + country → BOND (US) / FIXED_INCOME (BR)
    bind.execute(sa.text(
        "UPDATE asset SET asset_class = 'BOND' "
        "WHERE asset_class = 'FIXED_INCOME' AND country = 'US'"
    ))

    # ── Step 2: rewrite enum back to legacy 14 ───────────────────────────────
    if is_postgres:
        op.execute(
            "CREATE TYPE assetclass_old AS ENUM ("
            + ", ".join(f"'{v}'" for v in _OLD_VALUES) + ")"
        )
        op.execute(
            "ALTER TABLE asset ALTER COLUMN asset_class TYPE assetclass_old "
            "USING asset_class::text::assetclass_old"
        )
        op.execute("DROP TYPE assetclass")
        op.execute("ALTER TYPE assetclass_old RENAME TO assetclass")
    else:
        with op.batch_alter_table("asset") as batch_op:
            batch_op.alter_column(
                "asset_class",
                existing_type=sa.Enum(*_NEW_VALUES, name="assetclass"),
                type_=sa.Enum(*_OLD_VALUES, name="assetclass"),
                existing_nullable=False,
            )

    # ── Step 3: drop new columns ─────────────────────────────────────────────
    with op.batch_alter_table("asset") as batch_op:
        batch_op.drop_column("price_updated_at")
        batch_op.drop_column("current_price")
        batch_op.drop_column("country")
