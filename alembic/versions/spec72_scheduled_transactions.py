"""spec 72 — recurrence_rule + scheduled_transaction (Contas a Pagar/Receber)

Duas tabelas novas, aditivas — nenhuma row existente muda.
`UNIQUE(recurrence_rule_id, due_date)` garante a idempotência da
materialização; `recurrence_rule.materialized_through` é o watermark do
materializador (ocorrência adiada/excluída não é recriada).

Revision ID: spec72_scheduled_transactions
Revises: spec70_balance_from_ledger
Create Date: 2026-10-31
"""
from alembic import op
import sqlalchemy as sa


revision = "spec72_scheduled_transactions"
down_revision = "spec70_balance_from_ledger"
branch_labels = None
depends_on = None


def _direction():
    return sa.Enum("PAYABLE", "RECEIVABLE", name="scheduleddirection")


def upgrade() -> None:
    op.create_table(
        "recurrence_rule",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("direction", _direction(), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("party_id", sa.String(length=36), nullable=True),
        sa.Column("category_id", sa.String(length=36), nullable=True),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("currency", sa.Enum("BRL", "USD", name="currency"), nullable=False),
        sa.Column(
            "frequency",
            sa.Enum("MONTHLY", "YEARLY", "INSTALLMENT", name="recurrencefrequency"),
            nullable=False,
        ),
        sa.Column("day_of_month", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=True),
        sa.Column("installment_total", sa.Integer(), nullable=True),
        sa.Column("installment_paid", sa.Integer(), nullable=True),
        sa.Column("expected_account_id", sa.String(length=36), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("materialized_through", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"]),
        sa.ForeignKeyConstraint(["party_id"], ["party.id"]),
        sa.ForeignKeyConstraint(["category_id"], ["category.id"]),
        sa.ForeignKeyConstraint(["expected_account_id"], ["account.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_recurrence_rule_ws", "recurrence_rule", ["workspace_id", "is_active"])

    op.create_table(
        "scheduled_transaction",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("direction", _direction(), nullable=False),
        sa.Column("recurrence_rule_id", sa.String(length=36), nullable=True),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("party_id", sa.String(length=36), nullable=True),
        sa.Column("category_id", sa.String(length=36), nullable=True),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("currency", sa.Enum("BRL", "USD", name="currency"), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("installment_number", sa.Integer(), nullable=True),
        sa.Column("installment_total", sa.Integer(), nullable=True),
        sa.Column("expected_account_id", sa.String(length=36), nullable=True),
        sa.Column(
            "status",
            sa.Enum("PENDING", "PAID", "CANCELED", name="scheduledstatus"),
            nullable=False,
        ),
        sa.Column("paid_at", sa.Date(), nullable=True),
        sa.Column("paid_by_transaction_id", sa.String(length=36), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"]),
        sa.ForeignKeyConstraint(["recurrence_rule_id"], ["recurrence_rule.id"]),
        sa.ForeignKeyConstraint(["party_id"], ["party.id"]),
        sa.ForeignKeyConstraint(["category_id"], ["category.id"]),
        sa.ForeignKeyConstraint(["expected_account_id"], ["account.id"]),
        sa.ForeignKeyConstraint(["paid_by_transaction_id"], ["transaction.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("recurrence_rule_id", "due_date", name="uq_scheduled_rule_due"),
    )
    op.create_index("ix_scheduled_ws_due", "scheduled_transaction", ["workspace_id", "due_date"])
    op.create_index("ix_scheduled_ws_status", "scheduled_transaction", ["workspace_id", "status"])
    op.create_index("ix_scheduled_paid_by_tx", "scheduled_transaction", ["paid_by_transaction_id"])


def downgrade() -> None:
    op.drop_index("ix_scheduled_paid_by_tx", table_name="scheduled_transaction")
    op.drop_index("ix_scheduled_ws_status", table_name="scheduled_transaction")
    op.drop_index("ix_scheduled_ws_due", table_name="scheduled_transaction")
    op.drop_table("scheduled_transaction")
    op.drop_index("ix_recurrence_rule_ws", table_name="recurrence_rule")
    op.drop_table("recurrence_rule")
