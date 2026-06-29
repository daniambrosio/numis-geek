"""Spec 61b — asset_fundamentals table

Snapshot temporal de fundamentos por ativo (brapi/Finnhub/yfinance/manual).
Lê-se sempre o snapshot_date mais recente por asset; multiple sources
podem coexistir.

Revision ID: spec61b_fund
Revises: spec61a_target
Create Date: 2026-06-29 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision: str = "spec61b_fund"
down_revision: str | None = "spec61a_target"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "asset_fundamentals",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("asset_id", sa.String(length=36), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column(
            "source",
            sa.Enum("MANUAL", "BRAPI", "FINNHUB", "YFINANCE", name="fundamentalssource"),
            nullable=False,
        ),
        # Stocks
        sa.Column("pe", sa.Numeric(12, 4), nullable=True),
        sa.Column("pb", sa.Numeric(12, 4), nullable=True),
        sa.Column("eps", sa.Numeric(18, 4), nullable=True),
        sa.Column("bvps", sa.Numeric(18, 4), nullable=True),
        sa.Column("roe", sa.Numeric(10, 6), nullable=True),
        sa.Column("roic", sa.Numeric(10, 6), nullable=True),
        sa.Column("net_margin", sa.Numeric(10, 6), nullable=True),
        sa.Column("ebitda_margin", sa.Numeric(10, 6), nullable=True),
        sa.Column("debt_ebitda", sa.Numeric(10, 4), nullable=True),
        sa.Column("earnings_growth_5y", sa.Numeric(10, 6), nullable=True),
        sa.Column("dividend_yield_12m", sa.Numeric(10, 6), nullable=True),
        sa.Column("payout_ratio", sa.Numeric(10, 6), nullable=True),
        sa.Column("dps_12m", sa.Numeric(18, 4), nullable=True),
        # REITs
        sa.Column("p_ffo", sa.Numeric(12, 4), nullable=True),
        sa.Column("p_vp", sa.Numeric(12, 4), nullable=True),
        sa.Column("ffo_per_share", sa.Numeric(18, 4), nullable=True),
        sa.Column("affo_per_share", sa.Numeric(18, 4), nullable=True),
        sa.Column("vacancy", sa.Numeric(10, 6), nullable=True),
        sa.Column("distribution_coverage", sa.Numeric(10, 4), nullable=True),
        # ETFs
        sa.Column("expense_ratio", sa.Numeric(10, 6), nullable=True),
        sa.Column("tracking_error", sa.Numeric(10, 6), nullable=True),
        sa.Column("aum", sa.Numeric(20, 2), nullable=True),
        # Fixed income
        sa.Column("ytm", sa.Numeric(10, 6), nullable=True),
        sa.Column("duration", sa.Numeric(10, 4), nullable=True),
        # debug
        sa.Column("raw_payload", sa.Text(), nullable=True),
        # audit
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspace.id"], name="fk_fundamentals_workspace"
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"], ["asset.id"], name="fk_fundamentals_asset"
        ),
        sa.UniqueConstraint(
            "asset_id", "snapshot_date", "source",
            name="ux_fundamentals_asset_date_source",
        ),
    )
    op.create_index(
        "ix_fundamentals_asset_recent",
        "asset_fundamentals",
        ["asset_id", "snapshot_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_fundamentals_asset_recent", table_name="asset_fundamentals")
    op.drop_table("asset_fundamentals")
    sa.Enum(name="fundamentalssource").drop(op.get_bind(), checkfirst=True)
