"""Normaliza qty=1 pra assets em modo valor.

Motivo: FUND/FIXED_INCOME/PRIVATE_PENSION/CASH/FGTS rodam em modo valor
(aporte-por-valor, não fração de cota). O import do Notion "marretou"
qty × unit_price = gross pra respeitar o schema — resultado é qty
absurdo (ex.: Fundo Verde BTG com 47670 "cotas"). Aqui:

- asset_movement:      quantity = 1, unit_price = gross_amount
- portfolio_snapshot_item: quantity = 1, unit_price = market_value_native

Preserva os totais (gross_amount, market_value_native/brl/usd,
total_invested_brl). Só reescreve as duas colunas informacionais.

Filtros:
- Só rows com quantity != 1 (idempotente)
- Só rows com o total definido (gross_amount / market_value_native NOT
  NULL) — evita quebrar linhas sem valor de referência

Revision ID: normalize_valor_qty
Revises: asset_ticker_32
Create Date: 2026-07-02 00:20:00.000000
"""
from __future__ import annotations

from alembic import op


revision: str = "normalize_valor_qty"
down_revision: str | None = "asset_ticker_32"
branch_labels = None
depends_on = None


_VALOR_CLASSES = ('FUND', 'FIXED_INCOME', 'PRIVATE_PENSION', 'CASH', 'FGTS')


def upgrade() -> None:
    placeholders = ",".join(f"'{c}'" for c in _VALOR_CLASSES)

    # 1. Movements
    op.execute(f"""
        UPDATE asset_movement
        SET quantity = 1, unit_price = gross_amount
        WHERE asset_id IN (
            SELECT id FROM asset WHERE asset_class IN ({placeholders})
        )
        AND quantity != 1
        AND gross_amount IS NOT NULL
    """)

    # 2a. Snapshot items com preço — item.market_value_native é o valor
    # congelado. Manter o mv, mudar qty=1 + unit=mv.
    op.execute(f"""
        UPDATE portfolio_snapshot_item
        SET quantity = 1, unit_price = market_value_native
        WHERE asset_id IN (
            SELECT id FROM asset WHERE asset_class IN ({placeholders})
        )
        AND quantity != 1
        AND market_value_native IS NOT NULL
    """)

    # 2b. Snapshot items sem preço — só zera o qty absurdo (deixa
    # unit_price NULL). O user vê "1 cota sem preço" em vez de "47670
    # cotas sem preço" no fechamento.
    op.execute(f"""
        UPDATE portfolio_snapshot_item
        SET quantity = 1
        WHERE asset_id IN (
            SELECT id FROM asset WHERE asset_class IN ({placeholders})
        )
        AND quantity != 1
        AND market_value_native IS NULL
    """)


def downgrade() -> None:
    # Sem downgrade — não guardamos os valores originais. Restore do
    # backup .bak-before-normalize-valor-qty se precisar.
    pass
