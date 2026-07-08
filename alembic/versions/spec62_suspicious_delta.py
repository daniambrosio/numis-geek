"""spec 62 — suspicious delta pendency

Adiciona PendencyReason.SUSPICIOUS_DELTA e PendencyAction.CONFIRM_DELTA.
No SQLite Enum é serializado como string (sem CHECK constraint separada),
então adicionar valores novos não requer DDL. Esta migration serve como
registro histórico e placeholder pra quando migrar pra Postgres —
lá vai precisar `ALTER TYPE pendency_reason ADD VALUE 'SUSPICIOUS_DELTA'`.

Revision ID: spec62_susp_delta
Revises: idx_snap_closed_lookup
Create Date: 2026-07-08
"""

from alembic import op  # noqa: F401


revision = "spec62_susp_delta"
down_revision = "idx_snap_closed_lookup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite: no-op — Enum values são strings livres.
    # Postgres futuro: op.execute("ALTER TYPE pendencyreason ADD VALUE 'SUSPICIOUS_DELTA'")
    #                  op.execute("ALTER TYPE pendencyaction ADD VALUE 'CONFIRM_DELTA'")
    pass


def downgrade() -> None:
    # Enum value drop não é reversível cleanly. No-op.
    pass
