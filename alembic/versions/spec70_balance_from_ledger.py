"""spec 70 fase 3 — account.balance_from_ledger

Interruptor por conta corrente: o fechamento só puxa o saldo derivado do
ledger quando ligado. Nasce desligado (server_default 0) — nenhum fechamento
muda com o deploy.

Revision ID: spec70_balance_from_ledger
Revises: spec70_transaction
Create Date: 2026-10-31
"""
from alembic import op
import sqlalchemy as sa


revision = "spec70_balance_from_ledger"
down_revision = "spec70_transaction"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("account") as batch:
        batch.add_column(sa.Column("balance_from_ledger", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("account") as batch:
        batch.drop_column("balance_from_ledger")
