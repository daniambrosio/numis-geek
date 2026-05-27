"""Spec 38 — ExtractionJob table + ANTHROPIC integration provider.

Two changes bundled:

1. `extraction_job` — new table. One row per LLM extraction attempt.
2. `integrationprovider` enum — add ANTHROPIC value.

In SQLite enums are stored as VARCHAR with a CHECK constraint, so the
enum extension requires `batch_alter_table` (per CLAUDE.md).

Backup: copy `numis_geek.db` to `numis_geek.db.bak-before-38` before
upgrading.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "2b3c4d5e6f1a"
branch_labels = None
depends_on = None


EXTRACTION_STATUS = sa.Enum(
    "PENDING", "RUNNING", "EXTRACTED", "CONFIRMED", "REJECTED", "FAILED",
    name="extractionstatus",
)
EXTRACTION_SOURCE_HINT = sa.Enum(
    "BROKER_POSITION", "BROKER_INCOME", "B3_TRADE_NOTE",
    "FGTS_BALANCE", "SCREENSHOT_PRICE", "GENERIC",
    name="extractionsourcehint",
)


def upgrade() -> None:
    # 1) Extend integrationprovider enum with ANTHROPIC.
    # SQLite CHECK constraint — recreate enum via batch_alter_table.
    with op.batch_alter_table("integration_credential") as batch:
        batch.alter_column(
            "provider",
            existing_type=sa.Enum(
                "BCB", "BRAPI", "FINNHUB", "YFINANCE", "NOTION",
                name="integrationprovider",
            ),
            type_=sa.Enum(
                "BCB", "BRAPI", "FINNHUB", "YFINANCE", "NOTION", "ANTHROPIC",
                name="integrationprovider",
            ),
        )

    # 2) extraction_job table.
    op.create_table(
        "extraction_job",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id", sa.String(36),
            sa.ForeignKey("workspace.id"), nullable=False,
        ),
        sa.Column(
            "snapshot_id", sa.String(36),
            sa.ForeignKey("portfolio_snapshot.id"), nullable=True,
        ),
        sa.Column(
            "pendency_id", sa.String(36),
            sa.ForeignKey("snapshot_pendency.id"), nullable=True,
        ),
        sa.Column(
            "asset_id", sa.String(36),
            sa.ForeignKey("asset.id"), nullable=True,
        ),
        sa.Column(
            "attachment_id", sa.String(36),
            sa.ForeignKey("attachment.id"), nullable=False,
        ),
        sa.Column(
            "source_hint", EXTRACTION_SOURCE_HINT,
            nullable=False, server_default="GENERIC",
        ),
        sa.Column(
            "status", EXTRACTION_STATUS,
            nullable=False, server_default="PENDING",
        ),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("prompt_version", sa.String(20), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(10, 4), nullable=True),
        sa.Column("extracted_json", sa.JSON(), nullable=True),
        sa.Column("confidence", sa.Numeric(3, 2), nullable=True),
        sa.Column("detected_hint", EXTRACTION_SOURCE_HINT, nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("confirmed_by", sa.String(36), nullable=True),
        sa.Column("user_edits", sa.JSON(), nullable=True),
    )
    op.create_index(
        "ix_extraction_workspace_status", "extraction_job",
        ["workspace_id", "status"],
    )
    op.create_index(
        "ix_extraction_pendency", "extraction_job", ["pendency_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_extraction_pendency", table_name="extraction_job")
    op.drop_index("ix_extraction_workspace_status", table_name="extraction_job")
    op.drop_table("extraction_job")

    with op.batch_alter_table("integration_credential") as batch:
        batch.alter_column(
            "provider",
            existing_type=sa.Enum(
                "BCB", "BRAPI", "FINNHUB", "YFINANCE", "NOTION", "ANTHROPIC",
                name="integrationprovider",
            ),
            type_=sa.Enum(
                "BCB", "BRAPI", "FINNHUB", "YFINANCE", "NOTION",
                name="integrationprovider",
            ),
        )
