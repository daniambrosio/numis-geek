"""Extend NotionSyncStatus enum with SKIPPED value

Revision ID: e8f9a0b1c2d3
Revises: d2e3f4a5b6c7
Create Date: 2026-05-23 23:30:00.000000

Spec 18 follow-up. Adds `SKIPPED` to NotionSyncStatus so option-lifecycle
asset_movements (SELL_OPEN/BUY_TO_OPEN/SELL_TO_CLOSE/BUY_TO_CLOSE/EXERCISED/
EXPIRED) can be marked as intentionally-not-synced (the upstream Notion DB
schema doesn't model option types). Excluded from pending counts.

Touches 5 tables (asset, asset_movement, portfolio_snapshot,
portfolio_snapshot_item, corporate_action). SQLite enum widening requires
`op.batch_alter_table`.

Backup taken: numis_geek.db.bak-before-18-skipped (2026-05-23).
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "e8f9a0b1c2d3"
down_revision: str | None = "d2e3f4a5b6c7"
branch_labels = None
depends_on = None


OLD_STATUS = sa.Enum(
    "PENDING", "SYNCED", "CONFLICT", "ERROR", name="notionsyncstatus"
)
NEW_STATUS = sa.Enum(
    "PENDING", "SYNCED", "CONFLICT", "ERROR", "SKIPPED", name="notionsyncstatus"
)

TABLES = (
    "asset",
    "asset_movement",
    "portfolio_snapshot",
    "portfolio_snapshot_item",
    "corporate_action",
)


def upgrade() -> None:
    for table in TABLES:
        with op.batch_alter_table(table) as batch:
            batch.alter_column(
                "notion_sync_status",
                existing_type=OLD_STATUS,
                type_=NEW_STATUS,
                existing_nullable=False,
                existing_server_default="PENDING",
            )


def downgrade() -> None:
    # Any rows currently SKIPPED must be neutralized before narrowing the enum.
    op.execute(
        "UPDATE asset SET notion_sync_status = 'PENDING' "
        "WHERE notion_sync_status = 'SKIPPED'"
    )
    op.execute(
        "UPDATE asset_movement SET notion_sync_status = 'PENDING' "
        "WHERE notion_sync_status = 'SKIPPED'"
    )
    op.execute(
        "UPDATE portfolio_snapshot SET notion_sync_status = 'PENDING' "
        "WHERE notion_sync_status = 'SKIPPED'"
    )
    op.execute(
        "UPDATE portfolio_snapshot_item SET notion_sync_status = 'PENDING' "
        "WHERE notion_sync_status = 'SKIPPED'"
    )
    op.execute(
        "UPDATE corporate_action SET notion_sync_status = 'PENDING' "
        "WHERE notion_sync_status = 'SKIPPED'"
    )

    for table in TABLES:
        with op.batch_alter_table(table) as batch:
            batch.alter_column(
                "notion_sync_status",
                existing_type=NEW_STATUS,
                type_=OLD_STATUS,
                existing_nullable=False,
                existing_server_default="PENDING",
            )
