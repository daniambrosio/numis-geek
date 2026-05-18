"""portfolio_snapshot + portfolio_snapshot_item tables

Revision ID: a6b7c8d9e0f1
Revises: f5a6b7c8d9e0
Create Date: 2026-05-18 02:00:00.000000

Spec 14. Monthly portfolio snapshots — header + items.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "a6b7c8d9e0f1"
down_revision: str | None = "f5a6b7c8d9e0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "portfolio_snapshot",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("period_end_date", sa.Date(), nullable=False),
        sa.Column("fx_rate_usd_brl", sa.Numeric(18, 8), nullable=True),
        sa.Column("total_value_brl", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("total_value_usd", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("total_invested_brl", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("total_received_brl", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column(
            "source",
            sa.Enum("MANUAL", "NOTION_BACKFILL", "AUTOMATED", name="snapshotsource"),
            nullable=False,
            server_default="MANUAL",
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], name="fk_snapshot_workspace"),
        sa.UniqueConstraint("workspace_id", "period_end_date", name="ux_snapshot_ws_period"),
    )
    op.create_index("ix_snapshot_workspace_period", "portfolio_snapshot", ["workspace_id", "period_end_date"])

    op.create_table(
        "portfolio_snapshot_item",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("asset_id", sa.String(length=36), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 8), nullable=False),
        sa.Column("unit_price", sa.Numeric(18, 8), nullable=True),
        sa.Column("market_value_native", sa.Numeric(18, 2), nullable=True),
        sa.Column("market_value_brl", sa.Numeric(18, 2), nullable=True),
        sa.Column("market_value_usd", sa.Numeric(18, 2), nullable=True),
        sa.Column("average_cost_brl", sa.Numeric(18, 8), nullable=True),
        sa.Column("total_invested_brl", sa.Numeric(18, 2), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["snapshot_id"], ["portfolio_snapshot.id"], name="fk_snapshot_item_snapshot"),
        sa.ForeignKeyConstraint(["asset_id"], ["asset.id"], name="fk_snapshot_item_asset"),
    )
    op.create_index("ix_snapshot_item_snapshot", "portfolio_snapshot_item", ["snapshot_id"])
    op.create_index("ix_snapshot_item_asset", "portfolio_snapshot_item", ["asset_id"])


def downgrade() -> None:
    op.drop_index("ix_snapshot_item_asset", table_name="portfolio_snapshot_item")
    op.drop_index("ix_snapshot_item_snapshot", table_name="portfolio_snapshot_item")
    op.drop_table("portfolio_snapshot_item")
    op.drop_index("ix_snapshot_workspace_period", table_name="portfolio_snapshot")
    op.drop_table("portfolio_snapshot")
