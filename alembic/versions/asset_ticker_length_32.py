"""Bump asset.ticker length from VARCHAR(20) to VARCHAR(64).

Motivos:
1. OCC option symbols (US) chegam a 21 chars — ex.: AAPL260724C00295000.
2. O banco já tem nomes de fundos/CDBs sendo guardados em `ticker` com
   até 45 chars (resíduo da importação do Notion); SQLite não força
   VARCHAR length, mas Postgres forçaria. Subir pra 64 dá folga pra
   OCC + cobre o legacy sem precisar migrar dado.

Revision ID: asset_ticker_32
Revises: spec61b_fund
Create Date: 2026-06-30 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "asset_ticker_32"
down_revision: str | None = "spec61b_fund"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("asset") as batch:
        batch.alter_column(
            "ticker",
            existing_type=sa.String(length=20),
            type_=sa.String(length=64),
            existing_nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("asset") as batch:
        batch.alter_column(
            "ticker",
            existing_type=sa.String(length=64),
            type_=sa.String(length=20),
            existing_nullable=True,
        )
