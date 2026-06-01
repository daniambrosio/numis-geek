"""Portfolio snapshot service — fotografia of positions at a period_end.

Spec 14 originally; Spec 35 extends with lifecycle (SCHEDULED/IN_REVIEW/
CLOSED), pendency detection per source, confirm/reopen flows, and audit.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from numis_geek.models.account import Account
from numis_geek.models.asset import Asset, PriceSource
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.portfolio_snapshot import (
    PendencyAction,
    PendencyReason,
    PortfolioSnapshot,
    PortfolioSnapshotItem,
    SnapshotPendency,
    SnapshotSource,
    SnapshotStatus,
)
from numis_geek.services.audit import AuditService
from numis_geek.services.fx import FxRateNotFound, fx_rate_on
from numis_geek.services.positions import compute_position
from numis_geek.services.price_freshness import (
    AUTOMATED_SOURCES,
    PriceTier,
    freshness_tier,
)


@dataclass
class SnapshotResult:
    snapshot_id: str
    period_end_date: date
    items_count: int
    total_value_brl: Decimal
    total_value_usd: Decimal
    fx_rate_usd_brl: Decimal | None
    status: SnapshotStatus = SnapshotStatus.CLOSED
    pendencies_count: int = 0
    pendency_ids: list[str] = field(default_factory=list)


# ── Pendency detection ──────────────────────────────────────────────────────


def _is_avenue_generic(db: Session, asset: Asset) -> bool:
    """UPLOAD heuristic: assets that arrive without ticker via Avenue's
    generic 'rendimento' feed are flagged as upload-required.

    Cheap path: ticker IS NULL + asset's account is at an institution
    whose short_name is 'Avenue'. Refine as we learn the data better.
    """
    if asset.ticker:
        return False
    acc = db.get(Account, asset.account_id) if asset.account_id else None
    if not acc:
        return False
    fi = db.get(FinancialInstitution, acc.financial_institution_id)
    if not fi:
        return False
    return (fi.short_name or "").lower() == "avenue"


def detect_pendencies(
    db: Session,
    asset: Asset,
    *,
    period_end: date,
    now: datetime | None = None,
) -> tuple[PendencyReason, PendencyAction, str] | None:
    """Inspect a single asset and return (reason, action, detail) when it
    blocks closing the snapshot. None when the asset is fine.

    Rules (spec 35 §2.2):
    - NULL / no source            → skip (no pendency)
    - MANUAL                      → MANUAL_SOURCE (or UPLOAD_REQUIRED via heuristic)
    - Automated source + price OK (tier FRESH or STALE) → no pendency
    - Automated source + tier OLD → STALE_PRICE
    - Automated source + never refreshed (price_updated_at IS NULL) → API_FAILED
    """
    source = asset.price_source
    if source is None:
        return None

    if source == PriceSource.MANUAL:
        if _is_avenue_generic(db, asset):
            return (
                PendencyReason.UPLOAD_REQUIRED,
                PendencyAction.UPLOAD_FILE,
                "Avenue generic feed — upload extract",
            )
        return (
            PendencyReason.MANUAL_SOURCE,
            PendencyAction.EDIT_PRICE,
            "Manual price source — needs user edit",
        )

    if source in AUTOMATED_SOURCES:
        if asset.price_updated_at is None:
            return (
                PendencyReason.API_FAILED,
                PendencyAction.RETRY_API,
                f"{source.value}: never refreshed",
            )
        tier = freshness_tier(asset.price_updated_at, source, now=now)
        if tier == PriceTier.OLD:
            return (
                PendencyReason.STALE_PRICE,
                PendencyAction.RETRY_API,
                f"{source.value}: price older than 7 days at {period_end}",
            )

    return None


# ── Snapshot creation ───────────────────────────────────────────────────────


def _delete_snapshot_cascade(db: Session, snap: PortfolioSnapshot) -> None:
    db.query(SnapshotPendency).filter(
        SnapshotPendency.snapshot_id == snap.id
    ).delete()
    db.query(PortfolioSnapshotItem).filter(
        PortfolioSnapshotItem.snapshot_id == snap.id
    ).delete()
    db.delete(snap)
    db.flush()


def create_snapshot(
    db: Session,
    *,
    workspace_id: str,
    period_end: date,
    user_id: str | None = None,
    source: SnapshotSource = SnapshotSource.MANUAL,
    initial_status: SnapshotStatus = SnapshotStatus.CLOSED,
    replace_if_exists: bool = True,
    force_reopen: bool = False,
) -> SnapshotResult:
    """Create or replace a snapshot for workspace at period_end.

    `initial_status` is the desired status when no pendencies exist.
    Detected pendencies will downgrade the status to IN_REVIEW
    automatically.

    `force_reopen=True` is required to overwrite an existing CLOSED
    snapshot — protects against accidental data loss.
    """
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
        if existing.status == SnapshotStatus.CLOSED and not force_reopen:
            raise ValueError(
                f"Snapshot for {period_end} is CLOSED. Pass force_reopen=True to overwrite."
            )
        _delete_snapshot_cascade(db, existing)

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
        status=initial_status,
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
    pendency_ids: list[str] = []

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

        # Detect pendency for this asset at this snapshot.
        det = detect_pendencies(db, asset, period_end=period_end, now=now)
        if det is not None:
            reason, action, detail = det
            pen = SnapshotPendency(
                id=str(uuid.uuid4()),
                snapshot_id=snap.id,
                asset_id=asset.id,
                reason=reason,
                action_type=action,
                detail=detail,
                created_at=now,
            )
            db.add(pen)
            db.flush()
            pendency_ids.append(pen.id)

    snap.total_value_brl = total_brl
    snap.total_value_usd = total_usd
    snap.total_invested_brl = total_inv_brl
    snap.total_received_brl = total_rec_brl

    # Downgrade to IN_REVIEW if there are open pendencies and the caller asked for CLOSED.
    if pendency_ids and initial_status == SnapshotStatus.CLOSED:
        snap.status = SnapshotStatus.IN_REVIEW
    elif snap.status == SnapshotStatus.CLOSED:
        # Cleanly closed — stamp closed_at/by.
        snap.closed_at = now
        snap.closed_by = user_id

    db.flush()

    return SnapshotResult(
        snapshot_id=snap.id,
        period_end_date=period_end,
        items_count=items_count,
        total_value_brl=total_brl,
        total_value_usd=total_usd,
        fx_rate_usd_brl=fx,
        status=snap.status,
        pendencies_count=len(pendency_ids),
        pendency_ids=pendency_ids,
    )


# ── Lifecycle transitions ───────────────────────────────────────────────────


class PendencyOpenError(RuntimeError):
    """Raised by confirm_snapshot when at least one pendency is unresolved."""


def confirm_snapshot(
    db: Session,
    *,
    snapshot_id: str,
    user_id: str | None,
    user_email: str | None = None,
) -> PortfolioSnapshot:
    """Close a snapshot. Refuses if any pendency is unresolved.

    Recomputes totals from the persisted items (prices may have moved
    after creation via PATCH /assets/{id}/price or refresh).
    """
    snap = db.get(PortfolioSnapshot, snapshot_id)
    if snap is None:
        raise ValueError(f"Snapshot {snapshot_id} not found")

    open_pendencies = (
        db.query(SnapshotPendency)
        .filter(
            SnapshotPendency.snapshot_id == snap.id,
            SnapshotPendency.resolved_at.is_(None),
        )
        .count()
    )
    if open_pendencies > 0:
        raise PendencyOpenError(
            f"Cannot confirm: {open_pendencies} open pendency(ies)"
        )

    # Recompute totals from items (prices may have changed via resolution).
    items = (
        db.query(PortfolioSnapshotItem)
        .filter(PortfolioSnapshotItem.snapshot_id == snap.id)
        .all()
    )
    total_brl = sum((i.market_value_brl or Decimal("0") for i in items), Decimal("0"))
    total_usd = sum((i.market_value_usd or Decimal("0") for i in items), Decimal("0"))
    snap.total_value_brl = total_brl
    snap.total_value_usd = total_usd

    now = datetime.now(timezone.utc)
    snap.status = SnapshotStatus.CLOSED
    snap.closed_at = now
    snap.closed_by = user_id
    db.flush()

    AuditService(db).log(
        user_email=user_email or (user_id or "system"),
        action="snapshot.confirm",
        workspace_id=snap.workspace_id,
        user_id=user_id,
        resource_type="snapshot",
        resource_id=snap.id,
        details={
            "period_end_date": snap.period_end_date.isoformat(),
            "total_value_brl": str(total_brl),
        },
    )
    return snap


def reopen_snapshot(
    db: Session,
    *,
    snapshot_id: str,
    user_id: str | None,
    user_email: str | None = None,
    reason: str,
    now: datetime | None = None,
) -> PortfolioSnapshot:
    """Reopen any snapshot — moves to IN_REVIEW and re-detects pendencies.

    Reopening an older snapshot does NOT cascade-recompute later
    snapshots. The user accepts the historical drift consciously.
    """
    snap = db.get(PortfolioSnapshot, snapshot_id)
    if snap is None:
        raise ValueError(f"Snapshot {snapshot_id} not found")

    now = now or datetime.now(timezone.utc)

    # Drop existing pendencies (we'll re-detect fresh state).
    db.query(SnapshotPendency).filter(
        SnapshotPendency.snapshot_id == snap.id
    ).delete()

    # Re-detect based on current asset state.
    items = (
        db.query(PortfolioSnapshotItem)
        .filter(PortfolioSnapshotItem.snapshot_id == snap.id)
        .all()
    )
    pendency_ids: list[str] = []
    for it in items:
        asset = db.get(Asset, it.asset_id)
        if asset is None:
            continue
        det = detect_pendencies(db, asset, period_end=snap.period_end_date, now=now)
        if det is None:
            continue
        r, a, d = det
        pen = SnapshotPendency(
            id=str(uuid.uuid4()),
            snapshot_id=snap.id, asset_id=asset.id,
            reason=r, action_type=a, detail=d, created_at=now,
        )
        db.add(pen)
        pendency_ids.append(pen.id)

    snap.status = SnapshotStatus.IN_REVIEW
    snap.closed_at = None
    snap.closed_by = None
    db.flush()

    AuditService(db).log(
        user_email=user_email or (user_id or "system"),
        action="snapshot.reopen",
        workspace_id=snap.workspace_id,
        user_id=user_id,
        resource_type="snapshot",
        resource_id=snap.id,
        details={
            "period_end_date": snap.period_end_date.isoformat(),
            "reason": reason,
            "pendencies_recreated": len(pendency_ids),
        },
    )
    return snap


# ── Pendency resolution ─────────────────────────────────────────────────────


def resolve_pendency(
    db: Session,
    *,
    pendency_id: str,
    user_id: str | None,
    user_email: str | None = None,
    new_price: Decimal | None = None,
    file_id: str | None = None,
    note: str | None = None,
) -> SnapshotPendency:
    """Mark a pendency as resolved.

    If `new_price`: update Asset.current_price + the corresponding
    PortfolioSnapshotItem for this snapshot. If `file_id`: attach to the
    pendency note (LLM extraction is a future spec).
    """
    pen = db.get(SnapshotPendency, pendency_id)
    if pen is None:
        raise ValueError(f"Pendency {pendency_id} not found")

    snap = db.get(PortfolioSnapshot, pen.snapshot_id)
    asset = db.get(Asset, pen.asset_id)
    now = datetime.now(timezone.utc)

    if new_price is not None and asset is not None:
        asset.current_price = new_price
        asset.price_updated_at = now
        item = (
            db.query(PortfolioSnapshotItem)
            .filter(
                PortfolioSnapshotItem.snapshot_id == pen.snapshot_id,
                PortfolioSnapshotItem.asset_id == pen.asset_id,
            )
            .first()
        )
        if item is None:
            # Spec 49 hotfix #5 — create the missing item so the asset shows
            # up in the snapshot's frozen positions table. compute_position
            # gives us the cumulative quantity at period_end; fallback to 1
            # when zero (typical previdência / no-movement asset).
            position = compute_position(db, pen.asset_id, as_of=snap.period_end_date) if snap else {}
            qty = position.get("quantity_held") or Decimal("0")
            if qty == 0:
                qty = Decimal("1")
            item = PortfolioSnapshotItem(
                id=str(uuid.uuid4()),
                snapshot_id=pen.snapshot_id,
                asset_id=pen.asset_id,
                quantity=qty,
                average_cost_brl=position.get("average_cost_brl"),
                total_invested_brl=position.get("total_invested_brl"),
            )
            db.add(item)
        item.unit_price = new_price
        if item.quantity is not None:
            mv_native = item.quantity * new_price
            item.market_value_native = mv_native
            # Recompute BRL/USD using snapshot fx_rate.
            ccy = asset.currency.value if asset else "BRL"
            fx = snap.fx_rate_usd_brl if snap else None
            if ccy == "BRL":
                item.market_value_brl = mv_native
                if fx and fx > 0:
                    item.market_value_usd = mv_native / fx
            elif ccy == "USD":
                item.market_value_usd = mv_native
                if fx and fx > 0:
                    item.market_value_brl = mv_native * fx

    pen.resolved_at = now
    pen.resolved_by = user_id
    pen.resolution_note = note
    db.flush()

    # Refresh snapshot totals from items so the UI doesn't show stale headers.
    if snap is not None:
        items = (
            db.query(PortfolioSnapshotItem)
            .filter(PortfolioSnapshotItem.snapshot_id == snap.id)
            .all()
        )
        snap.total_value_brl = sum(
            (i.market_value_brl or Decimal("0") for i in items), Decimal("0")
        )
        snap.total_value_usd = sum(
            (i.market_value_usd or Decimal("0") for i in items), Decimal("0")
        )
        db.flush()

    AuditService(db).log(
        user_email=user_email or (user_id or "system"),
        action="snapshot.pendency.resolve",
        workspace_id=snap.workspace_id if snap else None,
        user_id=user_id,
        resource_type="pendency",
        resource_id=pen.id,
        details={
            "snapshot_id": pen.snapshot_id,
            "asset_id": pen.asset_id,
            "reason": pen.reason.value,
            "new_price": str(new_price) if new_price is not None else None,
            "file_id": file_id,
            "note": note,
        },
    )
    return pen


def retry_pendency_api(
    db: Session,
    *,
    pendency_id: str,
    user_id: str | None,
    user_email: str | None = None,
) -> SnapshotPendency:
    """Re-run the price refresh adapter for an API_FAILED/STALE_PRICE
    pendency. If the refresh succeeds and the price tier becomes
    FRESH/STALE, marks the pendency resolved automatically.
    """
    from numis_geek.services.price_update import refresh_one

    pen = db.get(SnapshotPendency, pendency_id)
    if pen is None:
        raise ValueError(f"Pendency {pendency_id} not found")
    asset = db.get(Asset, pen.asset_id)
    if asset is None:
        raise ValueError(f"Asset {pen.asset_id} not found")

    if pen.action_type != PendencyAction.RETRY_API:
        raise ValueError(
            f"Pendency {pendency_id} is not RETRY_API (got {pen.action_type.value})"
        )

    result = refresh_one(db, asset, user_email=user_email or "system")
    now = datetime.now(timezone.utc)

    if result.status == "ok":
        snap = db.get(PortfolioSnapshot, pen.snapshot_id)
        # Re-evaluate pendency.
        det = detect_pendencies(
            db, asset, period_end=snap.period_end_date if snap else asset.price_updated_at.date(),
            now=now,
        )
        if det is None:
            pen.resolved_at = now
            pen.resolved_by = user_id
            pen.resolution_note = f"API refresh ok: {result.new_price}"
            # Also bump the item price.
            if snap is not None:
                item = (
                    db.query(PortfolioSnapshotItem)
                    .filter(
                        PortfolioSnapshotItem.snapshot_id == snap.id,
                        PortfolioSnapshotItem.asset_id == asset.id,
                    )
                    .first()
                )
                if item is not None and result.new_price is not None:
                    item.unit_price = result.new_price
                    if item.quantity is not None:
                        mv_native = item.quantity * result.new_price
                        item.market_value_native = mv_native
                        ccy = asset.currency.value
                        fx = snap.fx_rate_usd_brl
                        if ccy == "BRL":
                            item.market_value_brl = mv_native
                            if fx and fx > 0:
                                item.market_value_usd = mv_native / fx
                        elif ccy == "USD":
                            item.market_value_usd = mv_native
                            if fx and fx > 0:
                                item.market_value_brl = mv_native * fx
        else:
            pen.detail = f"API refresh succeeded but pendency persists: {det[2]}"
    else:
        pen.detail = f"API refresh {result.status}: {result.error}"

    db.flush()

    AuditService(db).log(
        user_email=user_email or (user_id or "system"),
        action="snapshot.pendency.retry_api",
        workspace_id=db.get(PortfolioSnapshot, pen.snapshot_id).workspace_id
            if pen.snapshot_id else None,
        user_id=user_id,
        resource_type="pendency",
        resource_id=pen.id,
        details={
            "asset_id": asset.id,
            "ticker": asset.ticker,
            "status": result.status,
            "old_price": str(result.old_price) if result.old_price is not None else None,
            "new_price": str(result.new_price) if result.new_price is not None else None,
            "error": result.error,
        },
    )
    return pen


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


def list_pendencies(db: Session, snapshot_id: str) -> list[SnapshotPendency]:
    return (
        db.query(SnapshotPendency)
        .filter(SnapshotPendency.snapshot_id == snapshot_id)
        .order_by(SnapshotPendency.created_at.asc())
        .all()
    )
