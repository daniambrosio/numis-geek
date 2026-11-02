"""spec 84 — transaction.original_currency: Enum(BRL, USD) → String(3)

Conta multimoeda (Wise, uma conta só em reais): o valor original de cada
gasto é o do jar que pagou — EUR, GBP, CLP, UYU… além de BRL/USD. Os
valores existentes ("BRL"/"USD") continuam válidos como texto.

SQLite: troca de tipo via batch_alter_table.

Revision ID: spec84_original_currency_str
Revises: spec83_tx_asset_source
Create Date: 2026-11-02
"""
from alembic import op
import sqlalchemy as sa


revision = "spec84_original_currency_str"
down_revision = "spec83_tx_asset_source"
branch_labels = None
depends_on = None

_OLD = sa.Enum("BRL", "USD", name="currency")


def upgrade() -> None:
    with op.batch_alter_table("transaction") as batch:
        batch.alter_column(
            "original_currency", existing_type=_OLD, type_=sa.String(length=3), existing_nullable=True,
        )


def downgrade() -> None:
    # Só reverte se todo valor ainda couber no enum antigo.
    bind = op.get_bind()
    n = bind.execute(sa.text(
        "SELECT COUNT(*) FROM \"transaction\" WHERE original_currency IS NOT NULL "
        "AND original_currency NOT IN ('BRL', 'USD')"
    )).scalar()
    if n:
        raise RuntimeError(f"{n} transações com original_currency fora de BRL/USD — downgrade bloqueado")
    with op.batch_alter_table("transaction") as batch:
        batch.alter_column(
            "original_currency", existing_type=sa.String(length=3), type_=_OLD, existing_nullable=True,
        )
