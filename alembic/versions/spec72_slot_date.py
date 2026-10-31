"""spec 72 (audit 2026-10-31) — scheduled_transaction.slot_date

Guarda o slot ORIGINAL de cada ocorrência (a data que a regra gerou).
Adiar muda só `due_date`; materialização e edição de regra passam a
deduplicar/descartar pelo slot. A UNIQUE da regra vira
`(recurrence_rule_id, slot_date)`.

Backfill: `slot_date = due_date` (em prod há 0 linhas nas tabelas da
spec 72 neste momento, mas o backfill vale pra qualquer base).

Revision ID: spec72_slot_date
Revises: spec72_scheduled_transactions
Create Date: 2026-10-31
"""
from alembic import op
import sqlalchemy as sa


revision = "spec72_slot_date"
down_revision = "spec72_scheduled_transactions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("scheduled_transaction") as batch:
        batch.add_column(sa.Column("slot_date", sa.Date(), nullable=True))
    op.execute("UPDATE scheduled_transaction SET slot_date = due_date WHERE slot_date IS NULL")
    with op.batch_alter_table("scheduled_transaction") as batch:
        batch.alter_column("slot_date", existing_type=sa.Date(), nullable=False)
        batch.drop_constraint("uq_scheduled_rule_due", type_="unique")
        batch.create_unique_constraint("uq_scheduled_rule_slot", ["recurrence_rule_id", "slot_date"])


def downgrade() -> None:
    with op.batch_alter_table("scheduled_transaction") as batch:
        batch.drop_constraint("uq_scheduled_rule_slot", type_="unique")
        batch.create_unique_constraint("uq_scheduled_rule_due", ["recurrence_rule_id", "due_date"])
        batch.drop_column("slot_date")
