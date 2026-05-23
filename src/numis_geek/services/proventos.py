"""Spec 17 — unified income view (Distribution + synthetic OPTION_PREMIUM).

Synthetic OPTION_PREMIUM rows are NOT persisted; they are computed on the
fly from AssetMovement rows where type IN (SELL_OPEN, BUY_TO_CLOSE) on
OPTION assets. The asset_id of the synthetic row is the option's
underlying_id (so /proventos shows the income alongside the underlying's
dividends — but DY/YoC calculations exclude OPTION_PREMIUM).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from numis_geek.models.account import Account
from numis_geek.models.asset import Asset, AssetClass
from numis_geek.models.asset_movement import AssetMovement, AssetMovementType
from numis_geek.models.distribution import Distribution, DistributionType


@dataclass
class ProventoRow:
    id: str
    source: str  # 'distribution' or 'option_premium'
    event_date: date
    type: str  # DistributionType.value or 'OPTION_PREMIUM'
    asset_id: str | None
    financial_institution_id: str | None
    gross_amount: Decimal
    net_amount: Decimal
    currency: str
    fx_rate: Decimal


def list_proventos(
    db: Session,
    workspace_id: str | None,
    *,
    include_synthetic: bool = True,
    from_date: date | None = None,
    to_date: date | None = None,
) -> list[ProventoRow]:
    rows: list[ProventoRow] = []

    # Real distributions
    q = db.query(Distribution).filter(Distribution.is_active.is_(True))
    if workspace_id:
        q = q.filter(Distribution.workspace_id == workspace_id)
    if from_date:
        q = q.filter(Distribution.event_date >= from_date)
    if to_date:
        q = q.filter(Distribution.event_date <= to_date)
    for d in q.all():
        rows.append(ProventoRow(
            id=d.id, source="distribution", event_date=d.event_date,
            type=d.type.value, asset_id=d.asset_id,
            financial_institution_id=d.financial_institution_id,
            gross_amount=d.gross_amount, net_amount=d.net_amount,
            currency=d.currency.value, fx_rate=d.fx_rate,
        ))

    if not include_synthetic:
        return rows

    # Synthetic OPTION_PREMIUM rows from movements on OPTION assets.
    mq = (
        db.query(AssetMovement, Asset)
        .join(Asset, Asset.id == AssetMovement.asset_id)
        .filter(
            Asset.asset_class == AssetClass.OPTION,
            AssetMovement.type.in_([
                AssetMovementType.SELL_OPEN,
                AssetMovementType.BUY_TO_CLOSE,
            ]),
            AssetMovement.is_active.is_(True),
        )
    )
    if workspace_id:
        mq = mq.filter(AssetMovement.workspace_id == workspace_id)
    if from_date:
        mq = mq.filter(AssetMovement.event_date >= from_date)
    if to_date:
        mq = mq.filter(AssetMovement.event_date <= to_date)

    # Resolve FI via Asset.account_id (cache the lookup)
    account_cache: dict[str, str] = {}
    for m, opt in mq.all():
        if opt.account_id not in account_cache:
            acc = db.get(Account, opt.account_id)
            account_cache[opt.account_id] = acc.financial_institution_id if acc else None
        fi_id = account_cache.get(opt.account_id)
        rows.append(ProventoRow(
            id=m.id, source="option_premium", event_date=m.event_date,
            type="OPTION_PREMIUM",
            asset_id=opt.underlying_id,  # attribute to underlying
            financial_institution_id=fi_id,
            gross_amount=m.net_amount,  # premium = cash flow
            net_amount=m.net_amount,
            currency=m.currency.value, fx_rate=m.fx_rate,
        ))

    rows.sort(key=lambda r: r.event_date, reverse=True)
    return rows


def dy_eligible_amount_brl(db: Session, asset_id: str, *, days: int = 365) -> Decimal:
    """Sum of DY-eligible distributions (excludes OPTION_PREMIUM) for a
    given asset over the last `days` days, in BRL."""
    from datetime import timedelta
    cutoff = date.today() - timedelta(days=days)
    rows = db.query(Distribution).filter(
        Distribution.asset_id == asset_id,
        Distribution.is_active.is_(True),
        Distribution.event_date >= cutoff,
        # All DistributionType values are DY-eligible. OPTION_PREMIUM does
        # not exist as a DistributionType (it's view-only).
        Distribution.type.in_(list(DistributionType)),
    ).all()
    total = Decimal("0")
    for r in rows:
        total += (r.net_amount or Decimal("0")) * (r.fx_rate or Decimal("1"))
    return total
