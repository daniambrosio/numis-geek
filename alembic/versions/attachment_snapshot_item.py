"""Add SNAPSHOT_ITEM to AttachmentSourceType enum.

Anexar extrato do custodiante direto na linha do item do fechamento
(source_type=snapshot_item, source_id=portfolio_snapshot_item.id) pra
rastreabilidade: cada valor typado no fechamento aponta pra prova
documental (extrato PDF/PNG). Em SQLite enum é VARCHAR + CHECK, então
precisa batch_alter_table (mesmo padrão da d6e7f8a9b0c1).

Revision ID: att_snap_item
Revises: normalize_valor_qty
Create Date: 2026-07-02 23:20:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "att_snap_item"
down_revision: str | None = "normalize_valor_qty"
branch_labels = None
depends_on = None


SOURCE_OLD = sa.Enum(
    "asset", "movement", "distribution", "snapshot",
    name="attachmentsourcetype",
)
SOURCE_NEW = sa.Enum(
    "asset", "movement", "distribution", "snapshot", "snapshot_item",
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
