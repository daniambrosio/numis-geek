"""Portfolio snapshot service — fotografia of positions at a period_end."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from numis_geek.models.asset import Asset
from numis_geek.models.portfolio_snapshot import (
    PortfolioSnapshot,
    PortfolioSnapshotItem,
    SnapshotSource,
)
from numis_geek.services.fx import FxRateNotFound, fx_rate_on
from numis_geek.services.positions import compute_position


@dataclass
class SnapshotResult:
    snapshot_id: str
    period_end_date: date
    items_count: int
    total_value_brl: Decimal
    total_value_usd: Decimal
    fx_rate_usd_brl: Decimal | None


def create_snapshot(
    db: Session,
    *,
    workspace_id: str,
    period_end: date,
    user_id: str | None = None,
    source: SnapshotSource = SnapshotSource.MANUAL,
    replace_if_exists: bool = True,
) -> SnapshotResult:
    """Create a snapshot for workspace at period_end. Uses current_price as a
    photograph — for backfilling historical periods, set Asset.current_price
    appropriately beforehand or use a separate historical-price strategy."""

    existing = (
        db.query(PortfolioSnapshot)
        .filter(
            PortfolioSnapshot.workspace_id == workspace_id,
            PortfolioSnapshot.period_end_date == period_end,
        )
        .first()
    )
    if existing:
        if not replace_if_exists:
            raise ValueError(f"Snapshot already exists for {period_end}")
        db.query(PortfolioSnapshotItem).filter(
            PortfolioSnapshotItem.snapshot_id == existing.id
        ).delete()
        db.delete(existing)
        db.flush()

    try:
        fx = fx_rate_on(db, period_end)
    except FxRateNotFound:
        fx = None

    now = datetime.now(timezone.utc)
    snap = PortfolioSnapshot(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        period_end_date=period_end,
        fx_rate_usd_brl=fx,
        total_value_brl=Decimal("0"),
        total_value_usd=Decimal("0"),
        total_invested_brl=Decimal("0"),
        total_received_brl=Decimal("0"),
        source=source,
        is_active=True,
        created_at=now, updated_at=now,
        created_by=user_id, updated_by=user_id,
    )
    db.add(snap)
    db.flush()

    total_brl = Decimal("0")
    total_usd = Decimal("0")
    total_inv_brl = Decimal("0")
    total_rec_brl = Decimal("0")
    items_count = 0

    assets = (
        db.query(Asset)
        .filter(
            Asset.workspace_id == workspace_id,
            Asset.is_active == True,  # noqa: E712
        )
        .all()
    )

    for asset in assets:
        pos = compute_position(db, asset.id, as_of=period_end)
        qty = pos["quantity_held"]
        if qty == 0:
            continue

        mv_native = pos["current_value"]
        mv_brl = pos["current_value_brl"]
        mv_usd: Decimal | None = None

        currency = asset.currency.value
        if mv_brl is not None:
            if currency == "USD":
                mv_usd = mv_native
            elif currency == "BRL" and fx is not None and fx > 0:
                mv_usd = mv_brl / fx

        db.add(PortfolioSnapshotItem(
            id=str(uuid.uuid4()),
            snapshot_id=snap.id,
            asset_id=asset.id,
            quantity=qty,
            unit_price=pos["current_price"],
            market_value_native=mv_native,
            market_value_brl=mv_brl,
            market_value_usd=mv_usd,
            average_cost_brl=pos["average_cost_brl"],
            total_invested_brl=pos["total_invested_brl"],
            created_at=now,
        ))
        items_count += 1

        if mv_brl is not None:
            total_brl += mv_brl
        if mv_usd is not None:
            total_usd += mv_usd
        total_inv_brl += pos["total_invested_brl"]
        total_rec_brl += pos["total_received_brl"]

    snap.total_value_brl = total_brl
    snap.total_value_usd = total_usd
    snap.total_invested_brl = total_inv_brl
    snap.total_received_brl = total_rec_brl
    db.flush()

    return SnapshotResult(
        snapshot_id=snap.id,
        period_end_date=period_end,
        items_count=items_count,
        total_value_brl=total_brl,
        total_value_usd=total_usd,
        fx_rate_usd_brl=fx,
    )


def list_snapshots(db: Session, workspace_id: str) -> list[PortfolioSnapshot]:
    return (
        db.query(PortfolioSnapshot)
        .filter(
            PortfolioSnapshot.workspace_id == workspace_id,
            PortfolioSnapshot.is_active == True,  # noqa: E712
        )
        .order_by(PortfolioSnapshot.period_end_date.desc())
        .all()
    )
