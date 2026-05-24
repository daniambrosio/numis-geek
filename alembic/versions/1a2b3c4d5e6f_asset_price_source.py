"""Spec 22 — Asset.price_source column + PriceSource enum

Revision ID: 1a2b3c4d5e6f
Revises: f9a0b1c2d3e4
Create Date: 2026-05-24 12:45:00.000000

Adds the `price_source` enum column to `asset`. Nullable; the heuristic
backfill is performed by `scripts/backfill_asset_price_source.py` (with
dry-run + --apply pattern). New rows created after this migration must
set their source at creation time.

Uses `batch_alter_table` since SQLite needs it for ALTER ADD with enum.

Backup: numis_geek.db.bak-before-22.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "1a2b3c4d5e6f"
down_revision: str | None = "f9a0b1c2d3e4"
branch_labels = None
depends_on = None


PRICE_SOURCE = sa.Enum(
    "BRAPI", "FINNHUB", "COINBASE", "TESOURO", "MANUAL", name="pricesource"
)


def upgrade() -> None:
    with op.batch_alter_table("asset") as batch:
        batch.add_column(sa.Column("price_source", PRICE_SOURCE, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("asset") as batch:
        batch.drop_column("price_source")
