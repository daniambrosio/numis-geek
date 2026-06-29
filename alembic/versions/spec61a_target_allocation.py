"""Spec 61a — target_allocation table

Creates the workspace-scoped table that holds allocation targets per
class and per country. Used by Decision Support v1.

Revision ID: spec61a_target
Revises: notion_removal
Create Date: 2026-06-26 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision: str = "spec61a_target"
down_revision: str | None = "notion_removal"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "target_allocation",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column(
            "dimension",
            sa.Enum("CLASS", "COUNTRY", name="targetallocationdimension"),
            nullable=False,
        ),
        sa.Column("key", sa.String(length=32), nullable=False),
        sa.Column("target_pct", sa.Numeric(7, 4), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspace.id"], name="fk_target_allocation_workspace"
        ),
        sa.UniqueConstraint(
            "workspace_id", "dimension", "key",
            name="ux_target_allocation_ws_dim_key",
        ),
    )
    op.create_index(
        "ix_target_allocation_workspace",
        "target_allocation",
        ["workspace_id", "dimension"],
    )


def downgrade() -> None:
    op.drop_index("ix_target_allocation_workspace", table_name="target_allocation")
    op.drop_table("target_allocation")
    # Drop the enum type for Postgres compatibility (no-op on SQLite).
    sa.Enum(name="targetallocationdimension").drop(op.get_bind(), checkfirst=True)
