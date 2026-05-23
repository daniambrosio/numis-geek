"""notion_sync fields on 4 entities

Revision ID: c0d1e2f3a4b5
Revises: a6b7c8d9e0f1
Create Date: 2026-05-23 16:00:00.000000

Spec 16. Adds Notion sync tracking fields to asset, asset_movement,
portfolio_snapshot, portfolio_snapshot_item, and corporate_action. Also
adds external_id/external_source pair to the 3 tables that don't have it
yet (snapshot, snapshot_item, corporate_action).

Sync fields (4 per table):
- notion_last_synced_at: when we last pushed successfully
- notion_remote_last_edited_at: Notion's last_edited_time at last sync
- notion_sync_status: PENDING | SYNCED | CONFLICT | ERROR
- notion_sync_error: last error message if status=ERROR

Uses `batch_alter_table` since SQLite needs it for ALTER ADD with enum.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "c0d1e2f3a4b5"
down_revision: str | None = "a6b7c8d9e0f1"
branch_labels = None
depends_on = None


NOTION_SYNC_STATUS = sa.Enum(
    "PENDING", "SYNCED", "CONFLICT", "ERROR", name="notionsyncstatus"
)
EXTERNAL_SOURCE = sa.Enum(
    "NOTION", "B3", "BROKER_NOTE", "MANUAL_CSV", name="externalsource"
)


def _add_sync_fields(table: str, with_external: bool) -> None:
    with op.batch_alter_table(table) as batch:
        if with_external:
            batch.add_column(sa.Column("external_id", sa.String(255), nullable=True))
            batch.add_column(sa.Column("external_source", EXTERNAL_SOURCE, nullable=True))
        batch.add_column(sa.Column("notion_last_synced_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("notion_remote_last_edited_at", sa.DateTime(), nullable=True))
        batch.add_column(
            sa.Column(
                "notion_sync_status",
                NOTION_SYNC_STATUS,
                nullable=False,
                server_default="PENDING",
            )
        )
        batch.add_column(sa.Column("notion_sync_error", sa.Text(), nullable=True))


def _drop_sync_fields(table: str, with_external: bool) -> None:
    with op.batch_alter_table(table) as batch:
        batch.drop_column("notion_sync_error")
        batch.drop_column("notion_sync_status")
        batch.drop_column("notion_remote_last_edited_at")
        batch.drop_column("notion_last_synced_at")
        if with_external:
            batch.drop_column("external_source")
            batch.drop_column("external_id")


def upgrade() -> None:
    _add_sync_fields("asset", with_external=False)
    _add_sync_fields("asset_movement", with_external=False)
    _add_sync_fields("portfolio_snapshot", with_external=True)
    _add_sync_fields("portfolio_snapshot_item", with_external=True)
    _add_sync_fields("corporate_action", with_external=True)

    op.create_index(
        "ix_snapshot_external", "portfolio_snapshot", ["external_source", "external_id"],
        sqlite_where=sa.text("external_id IS NOT NULL"),
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )
    op.create_index(
        "ix_snapshot_item_external", "portfolio_snapshot_item",
        ["external_source", "external_id"],
        sqlite_where=sa.text("external_id IS NOT NULL"),
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )
    op.create_index(
        "ix_corp_action_external", "corporate_action", ["external_source", "external_id"],
        sqlite_where=sa.text("external_id IS NOT NULL"),
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_corp_action_external", table_name="corporate_action")
    op.drop_index("ix_snapshot_item_external", table_name="portfolio_snapshot_item")
    op.drop_index("ix_snapshot_external", table_name="portfolio_snapshot")

    _drop_sync_fields("corporate_action", with_external=True)
    _drop_sync_fields("portfolio_snapshot_item", with_external=True)
    _drop_sync_fields("portfolio_snapshot", with_external=True)
    _drop_sync_fields("asset_movement", with_external=False)
    _drop_sync_fields("asset", with_external=False)
