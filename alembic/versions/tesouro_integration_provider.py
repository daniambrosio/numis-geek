"""adiciona TESOURO ao enum IntegrationProvider

Registra a possibilidade de guardar credenciais/config para o adapter
Tesouro Transparente. No SQLite os Enums são serializados como strings
livres, então adicionar o valor não requer DDL — a migration existe
como marco histórico e placeholder para Postgres, onde vai ser preciso
`ALTER TYPE integrationprovider ADD VALUE 'TESOURO'`.

Revision ID: tesouro_integ_prov
Revises: spec62_susp_delta
Create Date: 2026-07-30
"""
from __future__ import annotations

from alembic import op  # noqa: F401


revision = "tesouro_integ_prov"
down_revision = "spec62_susp_delta"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite: no-op — Enum values são strings livres.
    # Postgres futuro:
    #   op.execute("ALTER TYPE integrationprovider ADD VALUE IF NOT EXISTS 'TESOURO'")
    pass


def downgrade() -> None:
    # Enum value drop não é reversível cleanly. No-op.
    pass
