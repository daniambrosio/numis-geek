"""corporate_action table

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-05-18 01:30:00.000000

Spec 13. New table for corporate actions (SPLIT/GROUPING/ASSET_CONVERSION).
Separate from AssetMovement — these are transformations, not trades.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "f5a6b7c8d9e0"
down_revision: str | None = "e4f5a6b7c8d9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "corporate_action",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("asset_id", sa.String(length=36), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column(
            "event_type",
            sa.Enum("SPLIT", "GROUPING", "ASSET_CONVERSION", name="corporateactiontype"),
            nullable=False,
        ),
        sa.Column("ratio", sa.Numeric(18, 8), nullable=False),
        sa.Column("target_asset_id", sa.String(length=36), nullable=True),
        sa.Column("target_ratio", sa.Numeric(18, 8), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], name="fk_corp_action_workspace"),
        sa.ForeignKeyConstraint(["asset_id"], ["asset.id"], name="fk_corp_action_asset"),
        sa.ForeignKeyConstraint(["target_asset_id"], ["asset.id"], name="fk_corp_action_target_asset"),
    )
    op.create_index("ix_corp_action_workspace_event_date", "corporate_action", ["workspace_id", "event_date"])
    op.create_index("ix_corp_action_asset_event_date", "corporate_action", ["asset_id", "event_date"])


def downgrade() -> None:
    op.drop_index("ix_corp_action_asset_event_date", table_name="corporate_action")
    op.drop_index("ix_corp_action_workspace_event_date", table_name="corporate_action")
    op.drop_table("corporate_action")
