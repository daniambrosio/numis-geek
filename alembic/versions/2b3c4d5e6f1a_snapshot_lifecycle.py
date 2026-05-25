"""Spec 35 — PortfolioSnapshot lifecycle + SnapshotPendency

Revision ID: 2b3c4d5e6f1a
Revises: 1a2b3c4d5e6f
Create Date: 2026-05-25 00:00:00.000000

Adds the snapshot review lifecycle:
- status enum on portfolio_snapshot (SCHEDULED/IN_REVIEW/CLOSED),
  default CLOSED to preserve existing rows.
- closed_at/closed_by/scheduled_at/auto_run_at audit columns.
- snapshot_pendency table — one row per asset blocking a close.

Backfill: existing snapshots get status=CLOSED, closed_at=created_at,
closed_by=created_by. The 28 Notion-imported rows in the prod DB
remain valid for downstream consumers (portfolio + dashboard).

Backup: numis_geek.db.bak-before-35.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "2b3c4d5e6f1a"
down_revision: str | None = "1a2b3c4d5e6f"
branch_labels = None
depends_on = None


SNAPSHOT_STATUS = sa.Enum(
    "SCHEDULED", "IN_REVIEW", "CLOSED", name="snapshotstatus"
)
PENDENCY_REASON = sa.Enum(
    "API_FAILED", "MANUAL_SOURCE", "UPLOAD_REQUIRED", "STALE_PRICE",
    name="pendencyreason",
)
PENDENCY_ACTION = sa.Enum(
    "RETRY_API", "EDIT_PRICE", "UPLOAD_FILE", name="pendencyaction",
)


def upgrade() -> None:
    # Add lifecycle columns to portfolio_snapshot.
    # SQLite needs batch_alter_table for enum + nullable changes.
    with op.batch_alter_table("portfolio_snapshot") as batch:
        batch.add_column(sa.Column(
            "status", SNAPSHOT_STATUS, nullable=False, server_default="CLOSED",
        ))
        batch.add_column(sa.Column("closed_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("closed_by", sa.String(36), nullable=True))
        batch.add_column(sa.Column("scheduled_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("auto_run_at", sa.DateTime(), nullable=True))

    # Backfill closed_at + closed_by for existing rows from created_at/created_by.
    op.execute(
        "UPDATE portfolio_snapshot SET closed_at = created_at WHERE closed_at IS NULL"
    )
    op.execute(
        "UPDATE portfolio_snapshot SET closed_by = created_by "
        "WHERE closed_by IS NULL AND created_by IS NOT NULL"
    )

    # Create snapshot_pendency table.
    op.create_table(
        "snapshot_pendency",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("snapshot_id", sa.String(36),
                  sa.ForeignKey("portfolio_snapshot.id"), nullable=False),
        sa.Column("asset_id", sa.String(36),
                  sa.ForeignKey("asset.id"), nullable=False),
        sa.Column("reason", PENDENCY_REASON, nullable=False),
        sa.Column("action_type", PENDENCY_ACTION, nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_by", sa.String(36), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("snapshot_id", "asset_id",
                            name="ux_pendency_snap_asset"),
    )
    op.create_index("ix_pendency_snapshot", "snapshot_pendency", ["snapshot_id"])


def downgrade() -> None:
    op.drop_index("ix_pendency_snapshot", table_name="snapshot_pendency")
    op.drop_table("snapshot_pendency")
    with op.batch_alter_table("portfolio_snapshot") as batch:
        batch.drop_column("auto_run_at")
        batch.drop_column("scheduled_at")
        batch.drop_column("closed_by")
        batch.drop_column("closed_at")
        batch.drop_column("status")
