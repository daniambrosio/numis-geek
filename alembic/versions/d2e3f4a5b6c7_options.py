"""Options B3 — AssetClass OPTION + 6 new AssetMovement types + 5 Asset
columns + AssetMovement.related_movement_id (self-FK)

Revision ID: d2e3f4a5b6c7
Revises: c0d1e2f3a4b5
Create Date: 2026-05-23 19:00:00.000000

Spec 17. Source of truth: docs/options-rationale.md (approved 2026-05-06).

Schema additions (all nullable; required only for asset_class=OPTION):
- asset.underlying_id     (FK → asset.id)
- asset.option_type       (enum CALL | PUT)
- asset.strike_price      (Numeric(18, 8))
- asset.expiration_date   (Date)
- asset.contract_size     (Integer, default 100 when OPTION)
- asset_movement.related_movement_id (self-FK; links underlying BUY/SELL
  to the EXERCISED movement on the option that triggered it)

Enum extensions:
- AssetClass += OPTION
- AssetMovementType += SELL_OPEN, BUY_TO_OPEN, BUY_TO_CLOSE,
  SELL_TO_CLOSE, EXERCISED, EXPIRED

Uses batch_alter_table since SQLite needs it for ALTER ADD and FK.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "d2e3f4a5b6c7"
down_revision: str | None = "c0d1e2f3a4b5"
branch_labels = None
depends_on = None


OPTION_TYPE = sa.Enum("CALL", "PUT", name="optiontype")


def upgrade() -> None:
    # asset additions
    with op.batch_alter_table("asset") as batch:
        batch.add_column(sa.Column("underlying_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("option_type", OPTION_TYPE, nullable=True))
        batch.add_column(sa.Column("strike_price", sa.Numeric(18, 8), nullable=True))
        batch.add_column(sa.Column("expiration_date", sa.Date(), nullable=True))
        batch.add_column(sa.Column("contract_size", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_asset_underlying", "asset",
            ["underlying_id"], ["id"],
        )
    op.create_index(
        "ix_asset_underlying", "asset", ["underlying_id"],
        sqlite_where=sa.text("underlying_id IS NOT NULL"),
        postgresql_where=sa.text("underlying_id IS NOT NULL"),
    )

    # asset_movement.related_movement_id (self-FK, nullable)
    with op.batch_alter_table("asset_movement") as batch:
        batch.add_column(sa.Column("related_movement_id", sa.String(36), nullable=True))
        batch.create_foreign_key(
            "fk_movement_related", "asset_movement",
            ["related_movement_id"], ["id"],
        )
    op.create_index(
        "ix_movement_related", "asset_movement", ["related_movement_id"],
        sqlite_where=sa.text("related_movement_id IS NOT NULL"),
        postgresql_where=sa.text("related_movement_id IS NOT NULL"),
    )

    # Enum values for AssetClass + AssetMovementType are stored as plain
    # VARCHAR in SQLite (no native enum constraint). Postgres would need
    # ALTER TYPE ADD VALUE; not needed for SQLite-only deploy.


def downgrade() -> None:
    op.drop_index("ix_movement_related", table_name="asset_movement")
    with op.batch_alter_table("asset_movement") as batch:
        batch.drop_constraint("fk_movement_related", type_="foreignkey")
        batch.drop_column("related_movement_id")

    op.drop_index("ix_asset_underlying", table_name="asset")
    with op.batch_alter_table("asset") as batch:
        batch.drop_constraint("fk_asset_underlying", type_="foreignkey")
        batch.drop_column("contract_size")
        batch.drop_column("expiration_date")
        batch.drop_column("strike_price")
        batch.drop_column("option_type")
        batch.drop_column("underlying_id")
