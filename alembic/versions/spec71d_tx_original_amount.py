"""spec 71d — transaction.original_amount / original_currency

Linha de extrato em outra moeda convertida pela PTAX (spec 71): guarda o
valor e a moeda ORIGINAIS. O fingerprint (chave de dedup) passa a usá-los
quando presentes, então editar a tx convertida não quebra o re-import.

Backfill: tx convertidas antes desta migration (deploy de 8a6f8eb) têm o
original só nas notas ("US$ 25,00 × PTAX 5,4321 (03/09)") — lido de lá, com
o sinal do valor convertido. O fingerprint delas já é o do original.

SQLite: add column via batch_alter_table.

Revision ID: spec71d_tx_original_amount
Revises: spec71c_category_example
Create Date: 2026-11-02
"""
import re
from decimal import Decimal

from alembic import op
import sqlalchemy as sa


revision = "spec71d_tx_original_amount"
down_revision = "spec71c_category_example"
branch_labels = None
depends_on = None

_NOTE = re.compile(r"^(US\$|R\$) ([\d.]+,\d{2}) [×÷] (PTAX|cotação do documento) ")


def upgrade() -> None:
    with op.batch_alter_table("transaction") as batch:
        batch.add_column(sa.Column("original_amount", sa.Numeric(precision=18, scale=2), nullable=True))
        batch.add_column(sa.Column("original_currency", sa.Enum("BRL", "USD", name="currency"), nullable=True))
    bind = op.get_bind()
    rows = bind.execute(sa.text(
        'SELECT id, amount, notes FROM "transaction" WHERE extraction_job_id IS NOT NULL '
        "AND (notes LIKE 'US$ %' OR notes LIKE 'R$ %')"
    )).fetchall()
    n = 0
    for tx_id, amount, notes in rows:
        m = _NOTE.match(notes or "")
        if not m:
            continue
        value = Decimal(m.group(2).replace(".", "").replace(",", "."))
        if Decimal(str(amount)) < 0:
            value = -value
        bind.execute(
            sa.text('UPDATE "transaction" SET original_amount = :a, original_currency = :c WHERE id = :id'),
            {"a": str(value), "c": "USD" if m.group(1) == "US$" else "BRL", "id": tx_id},
        )
        n += 1
    print(f"[spec71d] original_amount backfill: {n} tx convertidas")


def downgrade() -> None:
    with op.batch_alter_table("transaction") as batch:
        batch.drop_column("original_currency")
        batch.drop_column("original_amount")
