"""drop notion sync columns

Revision ID: notion_removal
Revises: spec58_fi_id
Create Date: 2026-06-09 15:30:00.000000

User decision (2026-06-09): Notion sync feature removed — lost its
purpose. Drops the 4 sync-tracking columns from each of the 5 tables
that had them. Keeps `external_id` / `external_source` (generic
provenance, also used by B3 / BROKER_NOTE / MANUAL_CSV) and
`SnapshotSource.NOTION_BACKFILL` (historical attribute marking
backfilled snapshots).

Dropped columns:
- notion_last_synced_at
- notion_remote_last_edited_at
- notion_sync_status
- notion_sync_error

Tables: asset, asset_movement, corporate_action, portfolio_snapshot,
portfolio_snapshot_item.

Uses `batch_alter_table` since SQLite needs it for DROP COLUMN with
enum-typed columns.
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text


revision: str = "notion_removal"
down_revision: str | None = "spec58_fi_id"
branch_labels = None
depends_on = None


TABLES = [
    "asset",
    "asset_movement",
    "corporate_action",
    "portfolio_snapshot",
    "portfolio_snapshot_item",
]

COLUMNS = [
    "notion_last_synced_at",
    "notion_remote_last_edited_at",
    "notion_sync_status",
    "notion_sync_error",
]


def upgrade() -> None:
    for table in TABLES:
        with op.batch_alter_table(table) as batch:
            for col in COLUMNS:
                batch.drop_column(col)

    # Orphan NOTION credentials no longer have any consumer code; clear.
    op.execute(
        text("DELETE FROM integration_credential WHERE provider = 'NOTION'")
    )


def downgrade() -> None:
    # No re-add: feature removed. Restoring would require the original
    # column definitions from c0d1e2f3a4b5 / e8f9a0b1c2d3.
    raise NotImplementedError(
        "Downgrade unsupported — restore from .bak-before-notion-removal."
    )
