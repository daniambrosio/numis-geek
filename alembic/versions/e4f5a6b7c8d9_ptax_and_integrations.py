"""ptax_rate + integration_credential tables

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-05-18 00:50:00.000000

Spec 11. Two new tables, no data ops:

1. `ptax_rate` — daily USD/BRL PTAX from BCB SGS (series 10813 venda).
   PTAX is a single rate fixed daily by BCB; there is no separate "compra"
   series in SGS. System-wide, no workspace_id.

2. `integration_credential` — system-wide credential store for external API
   tokens (brapi, Finnhub, etc.). workspace_id nullable (NULL = system-wide;
   the only mode used in spec 11). `secret_value` stored plaintext for now;
   encryption tracked as a follow-up security spec.

Downgrade drops both tables.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision: str = "e4f5a6b7c8d9"
down_revision: str | None = "d3e4f5a6b7c8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ptax_rate",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("rate", sa.Numeric(18, 8), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="BCB_SGS"),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("date", name="ux_ptax_rate_date"),
    )
    op.create_index("ix_ptax_rate_date", "ptax_rate", ["date"])

    op.create_table(
        "integration_credential",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=True),
        sa.Column(
            "provider",
            sa.Enum("BCB", "BRAPI", "FINNHUB", "YFINANCE", name="integrationprovider"),
            nullable=False,
        ),
        sa.Column("key_name", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=True),
        sa.Column("secret_value", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_tested_at", sa.DateTime(), nullable=True),
        sa.Column(
            "last_test_result",
            sa.Enum("UNTESTED", "SUCCESS", "FAILED", name="credentialtestresult"),
            nullable=False,
            server_default="UNTESTED",
        ),
        sa.Column("last_test_message", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspace.id"], name="fk_integration_credential_workspace"
        ),
        sa.UniqueConstraint(
            "workspace_id", "provider", "key_name", name="ux_cred_ws_provider_key"
        ),
    )


def downgrade() -> None:
    op.drop_table("integration_credential")
    op.drop_index("ix_ptax_rate_date", table_name="ptax_rate")
    op.drop_table("ptax_rate")
