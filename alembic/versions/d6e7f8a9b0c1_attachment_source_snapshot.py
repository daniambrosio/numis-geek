"""Spec 48 — add SNAPSHOT to AttachmentSourceType enum.

Bulk extract upload anexa o arquivo no escopo do snapshot (não de um
asset específico). Em SQLite enum é VARCHAR + CHECK constraint, então
extender precisa de `batch_alter_table`.

Backup: copy `numis_geek.db` to `numis_geek.db.bak-before-48` before
upgrading.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "d6e7f8a9b0c1"
down_revision: str | None = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


SOURCE_OLD = sa.Enum(
    "asset", "movement", "distribution", name="attachmentsourcetype",
)
SOURCE_NEW = sa.Enum(
    "asset", "movement", "distribution", "snapshot",
    name="attachmentsourcetype",
)


def upgrade() -> None:
    with op.batch_alter_table("attachment") as batch:
        batch.alter_column(
            "source_type",
            existing_type=SOURCE_OLD,
            type_=SOURCE_NEW,
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("attachment") as batch:
        batch.alter_column(
            "source_type",
            existing_type=SOURCE_NEW,
            type_=SOURCE_OLD,
            existing_nullable=False,
        )
