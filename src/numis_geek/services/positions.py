"""Position computation service for assets.

Computes per-asset position on-the-fly from active Lançamentos. No materialized
storage — the spec calls this out explicitly as "position_snapshot" being
deferred.

Behaviors implemented in this version (per spec 07c):

- Lançamentos are processed in chronological order (event_date ASC,
  created_at ASC).
- After each `VENDA` or `RESGATE_TOTAL`, qty is subtracted. If `type ==
  RESGATE_TOTAL` OR `abs(running_qty) < 1e-6`, both `running_qty` and
  `running_basis` reset to 0 — the next COMPRA starts fresh PM. This is the
  "PRIO3 problem" fix: a closed-and-reopened position must not carry old
  prices forward into the new average.
- For non-cotado lançamentos (quantity null but gross_amount present) on
  COMPRA/SUBSCRICAO: running_basis adds (gross × fx); qty unchanged.
  On VENDA/RESGATE_TOTAL: running_basis subtracts; qty unchanged. After
  RESGATE_TOTAL on a non-cotado, basis resets to 0 too.

Returned shape (dict) — see `compute_position`:
- quantity_held: Decimal — running_qty after the chronological walk.
- average_cost: Decimal — running_basis_native / basis_qty (cotado only).
- average_cost_brl: Decimal — same, but in BRL (per-row fx_rate weighted).
- total_invested_brl: Decimal — for cotado: quantity_held × average_cost_brl.
  For non-cotado: running_basis_brl directly.
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


_BASIS_ADD_TYPES = {LancamentoType.COMPRA, LancamentoType.SUBSCRICAO}
_BASIS_SUB_TYPES = {LancamentoType.VENDA, LancamentoType.RESGATE_TOTAL}
_QTY_ADD_TYPES = {LancamentoType.COMPRA, LancamentoType.BONIFICACAO, LancamentoType.SUBSCRICAO}
_QTY_SUB_TYPES = {LancamentoType.VENDA, LancamentoType.RESGATE_TOTAL}
_INCOME_TYPES = {LancamentoType.DIVIDENDO, LancamentoType.JUROS, LancamentoType.JCP}

_TOLERANCE = Decimal("1e-6")


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

    rows = q.order_by(Lancamento.event_date.asc(), Lancamento.created_at.asc()).all()

    running_qty = Decimal("0")
    basis_qty = Decimal("0")          # qty contributing to native PM (cotado COMPRA/SUBSCRICAO)
    basis_cost_native = Decimal("0")  # weighted native cost
    basis_cost_brl = Decimal("0")     # weighted BRL cost
    non_cotado_basis_brl = Decimal("0")  # standalone BRL basis for non-cotado lançamentos
    total_received_brl = Decimal("0")

    def reset_basis() -> None:
        nonlocal basis_qty, basis_cost_native, basis_cost_brl, non_cotado_basis_brl
        basis_qty = Decimal("0")
        basis_cost_native = Decimal("0")
        basis_cost_brl = Decimal("0")
        non_cotado_basis_brl = Decimal("0")

    for r in rows:
        qty = r.quantity or Decimal("0")
        unit = r.unit_price or Decimal("0")
        fx = r.fx_rate or Decimal("1")
        gross = r.gross_amount or Decimal("0")
        net = r.net_amount or Decimal("0")

        is_non_cotado_row = r.quantity is None and r.gross_amount is not None

        # ── Quantity update ─────────────────────────────────────────────────
        if r.type in _QTY_ADD_TYPES:
            running_qty += qty
        elif r.type in _QTY_SUB_TYPES:
            running_qty -= qty

        # ── Basis update ────────────────────────────────────────────────────
        if r.type in _BASIS_ADD_TYPES:
            if is_non_cotado_row:
                non_cotado_basis_brl += gross * fx
            else:
                basis_qty += qty
                basis_cost_native += qty * unit
                basis_cost_brl += qty * unit * fx
        elif r.type in _BASIS_SUB_TYPES:
            if is_non_cotado_row:
                non_cotado_basis_brl -= gross * fx

        # ── Income accumulation ─────────────────────────────────────────────
        if r.type in _INCOME_TYPES:
            total_received_brl += net * fx

        # ── Cost-basis reset (PRIO3 / RESGATE_TOTAL) ────────────────────────
        if r.type == LancamentoType.RESGATE_TOTAL or (
            r.type == LancamentoType.VENDA and abs(running_qty) < _TOLERANCE
        ):
            running_qty = Decimal("0")
            reset_basis()

    if basis_qty > 0:
        average_cost = basis_cost_native / basis_qty
        average_cost_brl = basis_cost_brl / basis_qty
    else:
        average_cost = Decimal("0")
        average_cost_brl = Decimal("0")

    if non_cotado_basis_brl != 0:
        # Non-cotado position: total_invested is the standalone BRL basis.
        total_invested_brl = non_cotado_basis_brl
    else:
        total_invested_brl = running_qty * average_cost_brl

    return Position(
        quantity_held=running_qty,
        average_cost=average_cost,
        average_cost_brl=average_cost_brl,
        total_invested_brl=total_invested_brl,
        total_received_brl=total_received_brl,
        currency=currency,
    )
