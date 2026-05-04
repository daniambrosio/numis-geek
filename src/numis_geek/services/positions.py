"""Position computation service for assets.

Computes per-asset position on-the-fly from active Lançamentos. No materialized
storage — the spec calls this out explicitly as "position_snapshot" being
deferred.

Returned shape (dict) — see `compute_position`:
- quantity_held: Decimal — sum of COMPRA + BONIFICACAO + SUBSCRICAO − VENDA.
- average_cost: Decimal — weighted-average unit cost in the asset's native currency,
  over basis-affecting events (COMPRA + SUBSCRICAO). Zero if no basis events.
- average_cost_brl: Decimal — same, but converted to BRL via each lançamento's
  fx_rate (so a USD asset's avg_cost_brl reflects the cost-basis in BRL terms).
- total_invested_brl: Decimal — quantity_held × average_cost_brl.
- total_received_brl: Decimal — sum of (net_amount × fx_rate) for income types
  (DIVIDENDO/JUROS/JCP) — what cash hit the workspace from the asset.
- currency: str — the asset's native currency (BRL or USD).
"""
from datetime import date
from decimal import Decimal
from typing import TypedDict

from sqlalchemy.orm import Session

from numis_geek.models.asset import Asset
from numis_geek.models.lancamento import Lancamento, LancamentoType


class Position(TypedDict):
    quantity_held: Decimal
    average_cost: Decimal
    average_cost_brl: Decimal
    total_invested_brl: Decimal
    total_received_brl: Decimal
    currency: str


_BASIS_TYPES = {LancamentoType.COMPRA, LancamentoType.SUBSCRICAO}
_QTY_ADD_TYPES = {LancamentoType.COMPRA, LancamentoType.BONIFICACAO, LancamentoType.SUBSCRICAO}
_INCOME_TYPES = {LancamentoType.DIVIDENDO, LancamentoType.JUROS, LancamentoType.JCP}


def compute_position(db: Session, asset_id: str, *, as_of: date | None = None) -> Position:
    """Compute current position for an asset.

    `as_of` filters to lançamentos with event_date <= as_of. None = all-time.
    Inactive lançamentos are skipped (soft-delete semantics).
    """
    asset = db.get(Asset, asset_id)
    currency = asset.currency.value if asset else "BRL"

    q = (
        db.query(Lancamento)
        .filter(Lancamento.asset_id == asset_id, Lancamento.is_active == True)  # noqa: E712
    )
    if as_of is not None:
        q = q.filter(Lancamento.event_date <= as_of)

    rows = q.all()

    quantity_held = Decimal("0")
    basis_qty = Decimal("0")
    basis_cost_native = Decimal("0")
    basis_cost_brl = Decimal("0")
    total_received_brl = Decimal("0")

    for r in rows:
        qty = r.quantity or Decimal("0")
        unit = r.unit_price or Decimal("0")
        fx = r.fx_rate or Decimal("1")
        net = r.net_amount or Decimal("0")

        if r.type in _QTY_ADD_TYPES:
            quantity_held += qty
        elif r.type == LancamentoType.VENDA:
            quantity_held -= qty

        if r.type in _BASIS_TYPES:
            basis_qty += qty
            basis_cost_native += qty * unit
            basis_cost_brl += qty * unit * fx

        if r.type in _INCOME_TYPES:
            total_received_brl += net * fx

    if basis_qty > 0:
        average_cost = basis_cost_native / basis_qty
        average_cost_brl = basis_cost_brl / basis_qty
    else:
        average_cost = Decimal("0")
        average_cost_brl = Decimal("0")

    total_invested_brl = quantity_held * average_cost_brl

    return Position(
        quantity_held=quantity_held,
        average_cost=average_cost,
        average_cost_brl=average_cost_brl,
        total_invested_brl=total_invested_brl,
        total_received_brl=total_received_brl,
        currency=currency,
    )
