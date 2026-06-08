"""Position computation service for assets.

Computes per-asset position on-the-fly from active AssetMovements and
Distributions. No materialized storage — `position_snapshot` is deferred
per spec roadmap.

Behaviors:

- AssetMovements processed chronologically (event_date ASC, created_at ASC).
- After SELL or FULL_REDEMPTION, qty is subtracted. If `type == FULL_REDEMPTION`
  OR `abs(running_qty) < 1e-6`, both `running_qty` and `running_basis` reset
  to 0 — the "PRIO3 problem" fix: a closed-and-reopened position must not
  carry old prices forward into the new average.
- For non-cotado movements (quantity null but gross_amount present) on
  BUY/SUBSCRIPTION: running_basis adds (gross × fx); qty unchanged.
  On SELL/FULL_REDEMPTION: running_basis subtracts; qty unchanged.

Distribution income (DIVIDEND/INTEREST/JCP/SECURITIES_LENDING) feeds
`total_received_brl` via Σ net_amount × fx_rate.

Returned shape — see `compute_position`:
- quantity_held: Decimal
- average_cost: Decimal (native currency)
- average_cost_brl: Decimal
- total_invested_brl: Decimal
- total_received_brl: Decimal — sum of Distribution net_amount × fx_rate
- currency: str — asset's native currency
"""
from datetime import date
from decimal import Decimal
from typing import TypedDict

from sqlalchemy.orm import Session

from numis_geek.models.asset import Asset, AssetClass
from numis_geek.models.asset_movement import AssetMovement, AssetMovementType
from numis_geek.models.corporate_action import CorporateAction, CorporateActionType
from numis_geek.models.distribution import Distribution
from numis_geek.services.fx import FxRateNotFound, fx_rate_on


class Position(TypedDict):
    quantity_held: Decimal
    average_cost: Decimal
    average_cost_brl: Decimal
    total_invested_brl: Decimal
    total_received_brl: Decimal
    currency: str
    current_price: Decimal | None
    current_value: Decimal | None
    current_value_brl: Decimal | None
    variation: Decimal | None       # (current - avg) / avg, native currency
    rentabilidade: Decimal | None   # (gain + distributions) / cost, BRL terms


_BASIS_ADD_TYPES = {AssetMovementType.BUY, AssetMovementType.SUBSCRIPTION}
_BASIS_SUB_TYPES = {AssetMovementType.SELL, AssetMovementType.FULL_REDEMPTION}
_QTY_ADD_TYPES = {
    AssetMovementType.BUY, AssetMovementType.BONUS, AssetMovementType.SUBSCRIPTION,
    # Spec 17: options open positions add qty (model long/short via sign of net_amount)
    AssetMovementType.SELL_OPEN, AssetMovementType.BUY_TO_OPEN,
}
_QTY_SUB_TYPES = {
    AssetMovementType.SELL, AssetMovementType.FULL_REDEMPTION,
    AssetMovementType.SELL_TO_CLOSE, AssetMovementType.BUY_TO_CLOSE,
    AssetMovementType.EXERCISED, AssetMovementType.EXPIRED,
}

_TOLERANCE = Decimal("1e-6")


def asset_has_position(pos: "Position", asset: Asset | None = None) -> bool:
    """True when an asset still has a tracked position at the given moment.

    Centralizes the "is this asset present?" rule so every consumer
    (snapshot creation, snapshot reopen, portfolio listings, dashboards)
    treats VALUE-mode assets correctly. An asset has a position when:

    - CASH assets sempre — são saldos em conta digitados manualmente por
      snapshot, sem movement nenhum (qty=0, invested=0). Sem essa exceção,
      os 5 "Saldo em Conta (XP/Itaú/MP/Wise/Avenue)" somem do fechamento
      e o user não consegue atualizar o saldo do mês.
    - quantity_held != 0 (modo cotado: STOCK, ETF, REIT, CRYPTO, OPTION,
      FIXED_INCOME papéis), OR
    - total_invested_brl != 0 (modo valor: FUND, PRIVATE_PENSION, FGTS,
      FIXED_INCOME tipo cofrinho — onde os movimentos têm gross mas
      quantity=NULL, mantidos em non_cotado_basis_brl).

    Spec 49 hotfix #12: a guarda `qty == 0` em `create_snapshot` excluía
    silenciosamente todos os ativos VALUE-puros do fechamento. Esse
    helper é a fonte única da regra.
    """
    if asset is not None and asset.asset_class == AssetClass.CASH:
        return True
    qty = pos.get("quantity_held") or Decimal("0")
    invested = pos.get("total_invested_brl") or Decimal("0")
    return qty != 0 or invested != 0


def compute_position(db: Session, asset_id: str, *, as_of: date | None = None) -> Position:
    """Compute current position for an asset.

    `as_of` filters to events with event_date <= as_of. None = all-time.
    Inactive rows are skipped (soft-delete semantics).
    """
    asset = db.get(Asset, asset_id)
    currency = asset.currency.value if asset else "BRL"

    q = (
        db.query(AssetMovement)
        .filter(AssetMovement.asset_id == asset_id, AssetMovement.is_active == True)  # noqa: E712
    )
    if as_of is not None:
        q = q.filter(AssetMovement.event_date <= as_of)

    movements = q.order_by(AssetMovement.event_date.asc(), AssetMovement.created_at.asc()).all()

    # Merge with CorporateActions sorted by event_date. Movements come before
    # corporate actions of the same date (so a BUY on the morning of a split
    # still gets adjusted by the split that day).
    caq = (
        db.query(CorporateAction)
        .filter(CorporateAction.asset_id == asset_id, CorporateAction.is_active == True)  # noqa: E712
    )
    if as_of is not None:
        caq = caq.filter(CorporateAction.event_date <= as_of)
    corp_actions = caq.order_by(CorporateAction.event_date.asc(), CorporateAction.created_at.asc()).all()

    # Tagged timeline: ('mv', m) or ('ca', ca)
    timeline = (
        [("mv", m) for m in movements]
        + [("ca", c) for c in corp_actions]
    )
    timeline.sort(key=lambda kv: (
        kv[1].event_date,
        0 if kv[0] == "mv" else 1,
        kv[1].created_at,
    ))

    running_qty = Decimal("0")
    basis_qty = Decimal("0")          # qty contributing to native PM (cotado BUY/SUBSCRIPTION)
    basis_cost_native = Decimal("0")  # weighted native cost
    basis_cost_brl = Decimal("0")     # weighted BRL cost
    non_cotado_basis_brl = Decimal("0")  # standalone BRL basis for non-cotado movements

    def reset_basis() -> None:
        nonlocal basis_qty, basis_cost_native, basis_cost_brl, non_cotado_basis_brl
        basis_qty = Decimal("0")
        basis_cost_native = Decimal("0")
        basis_cost_brl = Decimal("0")
        non_cotado_basis_brl = Decimal("0")

    for kind, r in timeline:
        if kind == "ca":
            # Corporate action — transform position, preserve total cost
            if r.event_type in (CorporateActionType.SPLIT, CorporateActionType.GROUPING):
                ratio = r.ratio or Decimal("1")
                running_qty *= ratio
                basis_qty *= ratio
                # basis_cost_native / _brl preserved — avg_cost = cost / qty
                # scales down automatically.
            elif r.event_type == CorporateActionType.ASSET_CONVERSION:
                # Position closes for this asset; target asset has its own
                # AssetMovement records (created by importer or user).
                running_qty = Decimal("0")
                reset_basis()
            continue

        # kind == "mv"
        qty = r.quantity or Decimal("0")
        unit = r.unit_price or Decimal("0")
        fx = r.fx_rate or Decimal("1")
        gross = r.gross_amount or Decimal("0")
        # Spec 56 — movement BRL já tem gross/unit em BRL. fx_rate fica
        # armazenado pra exibir em USD depois (multicurrency design), mas
        # NÃO multiplica em conversões BRL→BRL.
        mv_ccy = r.currency.value if hasattr(r.currency, "value") else r.currency
        effective_fx = fx if mv_ccy == "USD" else Decimal("1")

        is_non_cotado_row = r.quantity is None and r.gross_amount is not None

        # ── Quantity update ─────────────────────────────────────────────────
        if r.type in _QTY_ADD_TYPES:
            running_qty += qty
        elif r.type in _QTY_SUB_TYPES:
            running_qty -= qty

        # ── Basis update ────────────────────────────────────────────────────
        if r.type in _BASIS_ADD_TYPES:
            if is_non_cotado_row:
                non_cotado_basis_brl += gross * effective_fx
            else:
                basis_qty += qty
                basis_cost_native += qty * unit
                basis_cost_brl += qty * unit * effective_fx
        elif r.type in _BASIS_SUB_TYPES:
            if is_non_cotado_row:
                non_cotado_basis_brl -= gross * effective_fx

        # ── Cost-basis reset (PRIO3 / FULL_REDEMPTION) ─────────────────────
        if r.type == AssetMovementType.FULL_REDEMPTION or (
            r.type == AssetMovementType.SELL and abs(running_qty) < _TOLERANCE
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
        total_invested_brl = non_cotado_basis_brl
    else:
        total_invested_brl = running_qty * average_cost_brl

    # ── Distribution income ────────────────────────────────────────────────
    dq = (
        db.query(Distribution)
        .filter(Distribution.asset_id == asset_id, Distribution.is_active == True)  # noqa: E712
    )
    if as_of is not None:
        dq = dq.filter(Distribution.event_date <= as_of)
    total_received_brl = Decimal("0")
    for d in dq.all():
        net = d.net_amount or Decimal("0")
        # Spec 56 — só USD distributions convertem via PTAX. Hoje BRL dist
        # sempre tem fx=1 (notion sync filtra), mas defesa contra futuro.
        dist_ccy = d.currency.value if hasattr(d.currency, "value") else d.currency
        eff_fx = (d.fx_rate or Decimal("1")) if dist_ccy == "USD" else Decimal("1")
        total_received_brl += net * eff_fx

    # ── Derived figures from current_price (when set) ─────────────────────
    current_price = asset.current_price if asset and asset.current_price is not None else None
    current_value: Decimal | None = None
    current_value_brl: Decimal | None = None
    variation: Decimal | None = None
    rentabilidade: Decimal | None = None
    if current_price is not None and running_qty != 0:
        current_value = running_qty * current_price
        if currency == "BRL":
            current_value_brl = current_value
        elif currency == "USD":
            try:
                fx = fx_rate_on(db, as_of or date.today())
                current_value_brl = current_value * fx
            except FxRateNotFound:
                current_value_brl = None
        if average_cost > 0:
            variation = (current_price - average_cost) / average_cost
        if total_invested_brl > 0 and current_value_brl is not None:
            paper_gain_brl = current_value_brl - total_invested_brl
            rentabilidade = (paper_gain_brl + total_received_brl) / total_invested_brl

    return Position(
        quantity_held=running_qty,
        average_cost=average_cost,
        average_cost_brl=average_cost_brl,
        total_invested_brl=total_invested_brl,
        total_received_brl=total_received_brl,
        currency=currency,
        current_price=current_price,
        current_value=current_value,
        current_value_brl=current_value_brl,
        variation=variation,
        rentabilidade=rentabilidade,
    )
