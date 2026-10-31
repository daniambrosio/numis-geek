"""spec 70 — transaction + transaction_tag + invoice.paid_by_transaction_id

Spec 70 — Movimentações. Cria a tabela `transaction` (ledger único com
discriminador source_type), a join table `transaction_tag` (spec 68), o
espelho `invoice.paid_by_transaction_id` e o valor TRANSACTION no enum
AttachmentSourceType. Tudo aditivo — nenhuma row existente muda.

SQLite: add column com FK e troca de enum exigem batch_alter_table.

Revision ID: spec70_transaction
Revises: spec65_drop_susp_delta
Create Date: 2026-10-30
"""
from alembic import op
import sqlalchemy as sa


revision = "spec70_transaction"
down_revision = "spec65_drop_susp_delta"
branch_labels = None
depends_on = None


SOURCE_OLD = sa.Enum(
    "asset", "movement", "distribution", "snapshot", "snapshot_item",
    name="attachmentsourcetype",
)
SOURCE_NEW = sa.Enum(
    "asset", "movement", "distribution", "snapshot", "snapshot_item", "transaction",
    name="attachmentsourcetype",
)


def upgrade() -> None:
    op.create_table(
        "transaction",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("source_type", sa.Enum("CHECKING", "CREDIT_CARD", name="transactionsourcetype"), nullable=False),
        sa.Column("checking_account_id", sa.String(length=36), nullable=True),
        sa.Column("credit_card_account_id", sa.String(length=36), nullable=True),
        sa.Column("invoice_id", sa.String(length=36), nullable=True),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("currency", sa.Enum("BRL", "USD", name="currency"), nullable=False),
        sa.Column("fx_rate", sa.Numeric(precision=18, scale=8), nullable=False),
        sa.Column("fx_source", sa.Enum("STATEMENT", "PTAX", name="fxsource"), nullable=False),
        sa.Column("amount_brl", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("amount_usd", sa.Numeric(precision=18, scale=2), nullable=False),
        sa.Column("category_id", sa.String(length=36), nullable=True),
        sa.Column("party_id", sa.String(length=36), nullable=True),
        sa.Column("installment_number", sa.Integer(), nullable=True),
        sa.Column("installment_total", sa.Integer(), nullable=True),
        sa.Column("parent_transaction_id", sa.String(length=36), nullable=True),
        sa.Column("paid_invoice_id", sa.String(length=36), nullable=True),
        sa.Column("transfer_group_id", sa.String(length=36), nullable=True),
        sa.Column("fingerprint", sa.String(length=40), nullable=False),
        sa.Column("is_reconciled", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        sa.CheckConstraint(
            "(checking_account_id IS NOT NULL AND credit_card_account_id IS NULL)"
            " OR (checking_account_id IS NULL AND credit_card_account_id IS NOT NULL)",
            name="ck_transaction_one_source",
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"]),
        sa.ForeignKeyConstraint(["checking_account_id"], ["account.id"]),
        sa.ForeignKeyConstraint(["credit_card_account_id"], ["credit_card_account.id"]),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoice.id"]),
        sa.ForeignKeyConstraint(["category_id"], ["category.id"]),
        sa.ForeignKeyConstraint(["party_id"], ["party.id"]),
        sa.ForeignKeyConstraint(["parent_transaction_id"], ["transaction.id"]),
        sa.ForeignKeyConstraint(["paid_invoice_id"], ["invoice.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_transaction_ws_date", "transaction", ["workspace_id", "event_date"])
    op.create_index("ix_transaction_invoice", "transaction", ["invoice_id"])
    op.create_index("ix_transaction_category", "transaction", ["category_id"])
    op.create_index("ix_transaction_party", "transaction", ["party_id"])
    op.create_index("ix_transaction_ws_fingerprint", "transaction", ["workspace_id", "fingerprint"])
    op.create_index("ix_transaction_checking", "transaction", ["checking_account_id", "event_date"])
    op.create_index("ix_transaction_transfer_group", "transaction", ["transfer_group_id"])

    op.create_table(
        "transaction_tag",
        sa.Column("transaction_id", sa.String(length=36), nullable=False),
        sa.Column("tag_id", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["transaction_id"], ["transaction.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["tag.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("transaction_id", "tag_id"),
    )
    op.create_index("ix_transaction_tag_tag", "transaction_tag", ["tag_id"])

    with op.batch_alter_table("invoice") as batch:
        batch.add_column(sa.Column("paid_by_transaction_id", sa.String(length=36), nullable=True))
        batch.create_foreign_key(
            "fk_invoice_paid_by_transaction", "transaction", ["paid_by_transaction_id"], ["id"],
        )

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
    with op.batch_alter_table("invoice") as batch:
        batch.drop_constraint("fk_invoice_paid_by_transaction", type_="foreignkey")
        batch.drop_column("paid_by_transaction_id")
    op.drop_index("ix_transaction_tag_tag", table_name="transaction_tag")
    op.drop_table("transaction_tag")
    for ix in (
        "ix_transaction_transfer_group", "ix_transaction_checking", "ix_transaction_ws_fingerprint",
        "ix_transaction_party", "ix_transaction_category", "ix_transaction_invoice", "ix_transaction_ws_date",
    ):
        op.drop_index(ix, table_name="transaction")
    op.drop_table("transaction")
