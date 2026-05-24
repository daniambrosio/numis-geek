"""Spec 19 — Attachment table + FinancialInstitution.country

Revision ID: f9a0b1c2d3e4
Revises: e8f9a0b1c2d3
Create Date: 2026-05-24 00:30:00.000000

Two bundled changes:

1. **financial_institution.country (ISO-2)** — new NOT NULL column. Backfill:
   `Avenue`, `Coinbase`, `Wise` → `US`; everything else → `BR` (covered by
   server_default).

2. **attachment** — polymorphic user-attachments table. `source_type` ∈
   {asset, movement, distribution}. Storage path lives in `storage_key`
   (relative to `./data/attachments/`).

Backup: numis_geek.db.bak-before-19.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "f9a0b1c2d3e4"
down_revision: str | None = "e8f9a0b1c2d3"
branch_labels = None
depends_on = None


ATTACHMENT_SOURCE_TYPE = sa.Enum(
    "asset", "movement", "distribution", name="attachmentsourcetype"
)
ATTACHMENT_KIND = sa.Enum(
    "image", "pdf", "csv", "other", name="attachmentkind"
)


def upgrade() -> None:
    # 1) FinancialInstitution.country (server_default 'BR' covers existing rows)
    with op.batch_alter_table("financial_institution") as batch:
        batch.add_column(
            sa.Column("country", sa.String(2), nullable=False, server_default="BR")
        )

    # Backfill the 3 US-domiciled FIs.
    op.execute(
        "UPDATE financial_institution SET country = 'US' "
        "WHERE short_name IN ('Avenue', 'Coinbase', 'Wise')"
    )

    # 2) Attachment table.
    op.create_table(
        "attachment",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id", sa.String(36),
            sa.ForeignKey("workspace.id"), nullable=False,
        ),
        sa.Column("source_type", ATTACHMENT_SOURCE_TYPE, nullable=False),
        sa.Column("source_id", sa.String(36), nullable=False),
        sa.Column("kind", ATTACHMENT_KIND, nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=False),
        sa.Column(
            "uploaded_at", sa.DateTime(), nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "uploaded_by", sa.String(36),
            sa.ForeignKey("user.id"), nullable=True,
        ),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False,
            server_default=sa.text("1"),
        ),
    )
    op.create_index(
        "ix_attachment_source", "attachment", ["source_type", "source_id"]
    )
    op.create_index(
        "ix_attachment_workspace", "attachment", ["workspace_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_attachment_workspace", table_name="attachment")
    op.drop_index("ix_attachment_source", table_name="attachment")
    op.drop_table("attachment")

    with op.batch_alter_table("financial_institution") as batch:
        batch.drop_column("country")
