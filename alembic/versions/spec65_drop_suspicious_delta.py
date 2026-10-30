"""spec 65 — remove pendências SUSPICIOUS_DELTA

O detector da spec 62 saiu do código: `PendencyReason.SUSPICIOUS_DELTA` e
`PendencyAction.CONFIRM_DELTA` não existem mais no enum, então qualquer row
remanescente quebraria a leitura (LookupError do SQLAlchemy Enum). No SQLite
o Enum é VARCHAR sem CHECK constraint — basta apagar as rows; não há DDL.

Prod em 2026-10-30: 5 rows, todas já resolvidas. O backup pré-deploy é o
safety net — o downgrade não restaura os dados.

Revision ID: spec65_drop_susp_delta
Revises: attachment_slot
Create Date: 2026-10-30
"""

from alembic import op


revision = "spec65_drop_susp_delta"
down_revision = "attachment_slot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DELETE FROM snapshot_pendency WHERE reason = 'SUSPICIOUS_DELTA'")
    # Postgres futuro: os valores nunca chegaram a ser adicionados ao tipo
    # (spec62_susp_delta era no-op), então não há DROP VALUE a fazer.


def downgrade() -> None:
    # Rows apagadas não voltam; o enum antigo aceitaria novas, mas o
    # detector não existe mais. No-op.
    pass
