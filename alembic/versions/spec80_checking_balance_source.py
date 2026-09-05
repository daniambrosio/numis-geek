"""spec 80 — conta corrente como fonte do saldo

- `asset.linked_account_id`: liga um ativo CASH "Saldo em Conta" à conta
  corrente que é a fonte de verdade do saldo (spec 70 troca a origem do valor
  do fechamento pra esse vínculo).
- `account.opening_balance_date`: sem ela o `opening_balance` que já existia é
  ambíguo — o saldo derivado precisa saber a partir de quando somar transações.
- índice único parcial: no máximo um ativo por conta corrente.

Revision ID: spec80_checking_bal
Revises: fi_logo_upload
Create Date: 2026-09-05
"""

import sqlalchemy as sa
from alembic import op


revision = "spec80_checking_bal"
down_revision = "fi_logo_upload"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("asset") as batch:
        batch.add_column(sa.Column("linked_account_id", sa.String(36), nullable=True))
    with op.batch_alter_table("account") as batch:
        batch.add_column(sa.Column("opening_balance_date", sa.Date(), nullable=True))
    op.create_index(
        "ux_asset_linked_account",
        "asset",
        ["linked_account_id"],
        unique=True,
        sqlite_where=sa.text("linked_account_id IS NOT NULL"),
        postgresql_where=sa.text("linked_account_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ux_asset_linked_account", table_name="asset")
    with op.batch_alter_table("account") as batch:
        batch.drop_column("opening_balance_date")
    with op.batch_alter_table("asset") as batch:
        batch.drop_column("linked_account_id")
