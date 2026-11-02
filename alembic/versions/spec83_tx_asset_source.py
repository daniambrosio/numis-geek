"""spec 83 — pagar e receber com ativos

- `transaction.source_type` ganha ASSET;
- `transaction.asset_movement_id` (FK nullable → asset_movement, RESTRICT;
  coluna compartilhada com a spec 82) + índice único parcial: um movimento
  tem no máximo UMA tx;
- `ck_transaction_one_source` amarra a fonte ao `source_type`: CHECKING →
  conta (movimento opcional, pra tx de caixa da spec 82), CREDIT_CARD →
  cartão, ASSET → só o movimento.

SQLite: batch_alter_table (recria a tabela). Sem data ops — nenhuma tx
existente muda; o backfill do Coinbase One é feito pela API depois do deploy.

Revision ID: spec83_tx_asset_source
Revises: spec71d_tx_original_amount
Create Date: 2026-11-02
"""
from alembic import op
import sqlalchemy as sa


revision = "spec83_tx_asset_source"
down_revision = "spec71d_tx_original_amount"
branch_labels = None
depends_on = None

OLD_CHECK = (
    "(checking_account_id IS NOT NULL AND credit_card_account_id IS NULL)"
    " OR (checking_account_id IS NULL AND credit_card_account_id IS NOT NULL)"
)
NEW_CHECK = (
    "(source_type = 'CHECKING' AND checking_account_id IS NOT NULL AND credit_card_account_id IS NULL)"
    " OR (source_type = 'CREDIT_CARD' AND credit_card_account_id IS NOT NULL"
    " AND checking_account_id IS NULL AND asset_movement_id IS NULL)"
    " OR (source_type = 'ASSET' AND asset_movement_id IS NOT NULL"
    " AND checking_account_id IS NULL AND credit_card_account_id IS NULL)"
)
OLD_ENUM = sa.Enum("CHECKING", "CREDIT_CARD", name="transactionsourcetype")
NEW_ENUM = sa.Enum("CHECKING", "CREDIT_CARD", "ASSET", name="transactionsourcetype")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TYPE transactionsourcetype ADD VALUE IF NOT EXISTS 'ASSET'")
    with op.batch_alter_table("transaction") as batch:
        batch.add_column(sa.Column("asset_movement_id", sa.String(36), nullable=True))
        batch.create_foreign_key(
            "fk_transaction_asset_movement", "asset_movement",
            ["asset_movement_id"], ["id"], ondelete="RESTRICT",
        )
        batch.alter_column("source_type", existing_type=OLD_ENUM, type_=NEW_ENUM, existing_nullable=False)
        batch.drop_constraint("ck_transaction_one_source", type_="check")
        batch.create_check_constraint("ck_transaction_one_source", NEW_CHECK)
    op.create_index(
        "uq_transaction_asset_movement", "transaction", ["asset_movement_id"], unique=True,
        sqlite_where=sa.text("asset_movement_id IS NOT NULL"),
        postgresql_where=sa.text("asset_movement_id IS NOT NULL"),
    )


def downgrade() -> None:
    n = op.get_bind().execute(sa.text(
        'SELECT COUNT(*) FROM "transaction" WHERE asset_movement_id IS NOT NULL'
    )).scalar()
    if n:
        raise RuntimeError(f"{n} tx ligadas a movimento de ativo — apague-as antes do downgrade.")
    op.drop_index("uq_transaction_asset_movement", table_name="transaction")
    with op.batch_alter_table("transaction") as batch:
        batch.drop_constraint("ck_transaction_one_source", type_="check")
        batch.create_check_constraint("ck_transaction_one_source", OLD_CHECK)
        batch.alter_column("source_type", existing_type=NEW_ENUM, type_=OLD_ENUM, existing_nullable=False)
        batch.drop_constraint("fk_transaction_asset_movement", type_="foreignkey")
        batch.drop_column("asset_movement_id")
