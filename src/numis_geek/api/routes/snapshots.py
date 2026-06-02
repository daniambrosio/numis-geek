"""Portfolio snapshot routes (Spec 14 + 35).

Spec 35 adds:
- status, closed_at/by, pendencies counts on SnapshotOut.
- GET /snapshots/{id}/pendencies
- POST /snapshots/{id}/confirm
- POST /snapshots/{id}/reopen
- POST /snapshots/pendencies/{pid}/resolve
- POST /snapshots/pendencies/{pid}/retry-api
"""
from datetime import date as date_t
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from numis_geek.api.deps import get_current_user, get_db
from numis_geek.models.account import Account
from numis_geek.models.asset import Asset
from numis_geek.models.extraction_job import (
    ExtractionJob,
    ExtractionSourceHint,
    ExtractionStatus,
)
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.portfolio_snapshot import (
    PortfolioSnapshot,
    PortfolioSnapshotItem,
    SnapshotPendency,
    SnapshotSource,
    SnapshotStatus,
)
from numis_geek.models.user import User, UserRole
from numis_geek.services import extraction as extraction_service
from numis_geek.services.auth import UserContext
from numis_geek.services.snapshot import (
    PendencyOpenError,
    confirm_snapshot,
    create_snapshot,
    list_pendencies,
    list_snapshots,
    reopen_snapshot,
    resolve_pendency,
    retry_pendency_api,
    update_snapshot_item_price,
)
from numis_geek.utils.business_day import last_day_of_month

router = APIRouter(prefix="/snapshots", tags=["snapshots"])


# ── Schemas ─────────────────────────────────────────────────────────────────


class SnapshotItemOut(BaseModel):
    asset_id: str
    quantity: str
    unit_price: str | None
    market_value_native: str | None
    market_value_brl: str | None
    market_value_usd: str | None
    average_cost_brl: str | None
    total_invested_brl: str | None


class SnapshotOut(BaseModel):
    id: str
    workspace_id: str
    period_end_date: str
    fx_rate_usd_brl: str | None
    total_value_brl: str
    total_value_usd: str
    total_invested_brl: str
    total_received_brl: str
    source: str
    items_count: int
    # Spec 35 lifecycle fields
    status: str
    closed_at: str | None
    closed_by: str | None
    scheduled_at: str | None
    auto_run_at: str | None
    pendencies_total: int
    pendencies_open: int

    @classmethod
    def from_orm(
        cls, s: PortfolioSnapshot,
        items_count: int,
        pendencies_total: int = 0,
        pendencies_open: int = 0,
    ) -> "SnapshotOut":
        return cls(
            id=s.id,
            workspace_id=s.workspace_id,
            period_end_date=s.period_end_date.isoformat(),
            fx_rate_usd_brl=str(s.fx_rate_usd_brl) if s.fx_rate_usd_brl else None,
            total_value_brl=str(s.total_value_brl),
            total_value_usd=str(s.total_value_usd),
            total_invested_brl=str(s.total_invested_brl),
            total_received_brl=str(s.total_received_brl),
            source=s.source.value,
            items_count=items_count,
            status=s.status.value,
            closed_at=s.closed_at.isoformat() if s.closed_at else None,
            closed_by=s.closed_by,
            scheduled_at=s.scheduled_at.isoformat() if s.scheduled_at else None,
            auto_run_at=s.auto_run_at.isoformat() if s.auto_run_at else None,
            pendencies_total=pendencies_total,
            pendencies_open=pendencies_open,
        )


class SnapshotCreateRequest(BaseModel):
    period_end_date: date_t | None = None
    target_ym: str | None = Field(
        default=None,
        pattern=r"^\d{4}-\d{2}$",
        description="YYYY-MM. Backend resolves period_end via last_day_of_month (calendar).",
    )
    auto: bool = False


class SnapshotReopenRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)


class BulkExtractRequest(BaseModel):
    """Spec 48 — create a bulk-extract job for a snapshot."""
    attachment_id: str


class SnapshotItemPatchRequest(BaseModel):
    """Spec 49 hotfix #10 — inline edit a snapshot item.

    `price` is the user-typed value. `value_mode` chooses interpretation:
    - "unit"  : per-share / per-cota price
    - "total" : consolidated market value (divide by quantity to derive
                unit_price)
    - None    : auto-detect from asset_class (matches the per-pendency
                resolve path).
    """
    price: Decimal = Field(..., gt=0)
    value_mode: str | None = Field(default=None, pattern=r"^(unit|total)$")
    note: str | None = Field(default=None, max_length=500)


class BulkExtractionJobOut(BaseModel):
    """Spec 49 — lightweight job summary for the attachment-row badge."""
    id: str
    attachment_id: str
    status: str
    positions_count: int
    error_message: str | None
    created_at: str
    completed_at: str | None
    confirmed_at: str | None
    # Spec 49 hotfix — LLM usage so cost is visible in the UI.
    model: str | None
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: str | None

    @classmethod
    def from_orm(cls, j: ExtractionJob) -> "BulkExtractionJobOut":
        positions = 0
        if j.extracted_json:
            payload_positions = j.extracted_json.get("positions") or []
            positions = len(payload_positions)
        return cls(
            id=j.id,
            attachment_id=j.attachment_id,
            status=j.status.value,
            positions_count=positions,
            error_message=j.error_message,
            created_at=j.created_at.isoformat() if j.created_at else "",
            completed_at=j.completed_at.isoformat() if j.completed_at else None,
            confirmed_at=j.confirmed_at.isoformat() if j.confirmed_at else None,
            model=j.model,
            input_tokens=j.input_tokens,
            output_tokens=j.output_tokens,
            cost_usd=str(j.cost_usd) if j.cost_usd is not None else None,
        )


class PendencyResolveRequest(BaseModel):
    new_price: Decimal | None = None
    file_id: str | None = None
    note: str | None = None


class SnapshotPendencyOut(BaseModel):
    id: str
    snapshot_id: str
    asset_id: str
    asset_ticker: str | None
    asset_name: str
    asset_institution_short_name: str | None
    reason: str
    action_type: str
    detail: str | None
    resolved_at: str | None
    resolved_by: str | None
    resolution_note: str | None
    created_at: str
    # Spec 35 hotfix #2 — previous CLOSED snapshot's price for this asset,
    # used by the "Repetir" button on the pendency row.
    previous_unit_price: str | None
    previous_period_end: str | None

    @classmethod
    def from_orm(
        cls, p: SnapshotPendency, asset: Asset | None,
        *,
        institution_short_name: str | None = None,
        previous_unit_price: Decimal | None = None,
        previous_period_end: date_t | None = None,
    ) -> "SnapshotPendencyOut":
        return cls(
            id=p.id,
            snapshot_id=p.snapshot_id,
            asset_id=p.asset_id,
            asset_ticker=asset.ticker if asset else None,
            asset_name=asset.name if asset else p.asset_id[:8],
            asset_institution_short_name=institution_short_name,
            reason=p.reason.value,
            action_type=p.action_type.value,
            detail=p.detail,
            resolved_at=p.resolved_at.isoformat() if p.resolved_at else None,
            resolved_by=p.resolved_by,
            resolution_note=p.resolution_note,
            created_at=p.created_at.isoformat() if p.created_at else "",
            previous_unit_price=(
                str(previous_unit_price) if previous_unit_price is not None else None
            ),
            previous_period_end=(
                previous_period_end.isoformat() if previous_period_end else None
            ),
        )


# ── Helpers ─────────────────────────────────────────────────────────────────


def _workspace_id(current_user: UserContext) -> str:
    if current_user.role == UserRole.sysadmin:
        raise HTTPException(
            status_code=400,
            detail="Sysadmin must call CLI with explicit workspace",
        )
    return current_user.workspace_id


def _pendency_counts(db: Session, snapshot_id: str) -> tuple[int, int]:
    total = db.query(func.count(SnapshotPendency.id)).filter(
        SnapshotPendency.snapshot_id == snapshot_id
    ).scalar() or 0
    open_ = db.query(func.count(SnapshotPendency.id)).filter(
        SnapshotPendency.snapshot_id == snapshot_id,
        SnapshotPendency.resolved_at.is_(None),
    ).scalar() or 0
    return int(total), int(open_)


def _user_email(db: Session, ctx: UserContext) -> str:
    actor = db.get(User, ctx.user_id)
    return actor.email if actor else ctx.user_id


def _hydrate_snapshot(db: Session, snap: PortfolioSnapshot) -> SnapshotOut:
    count = db.query(PortfolioSnapshotItem).filter(
        PortfolioSnapshotItem.snapshot_id == snap.id
    ).count()
    p_total, p_open = _pendency_counts(db, snap.id)
    return SnapshotOut.from_orm(snap, count, p_total, p_open)


def _previous_closed_snapshot(
    db: Session, snap: PortfolioSnapshot,
) -> PortfolioSnapshot | None:
    return (
        db.query(PortfolioSnapshot)
        .filter(
            PortfolioSnapshot.workspace_id == snap.workspace_id,
            PortfolioSnapshot.period_end_date < snap.period_end_date,
            PortfolioSnapshot.status == SnapshotStatus.CLOSED,
        )
        .order_by(PortfolioSnapshot.period_end_date.desc())
        .first()
    )


def _institution_short_name(db: Session, asset: Asset | None) -> str | None:
    if asset is None:
        return None
    acc = db.get(Account, asset.account_id) if asset.account_id else None
    if acc is None or not acc.financial_institution_id:
        return None
    fi = db.get(FinancialInstitution, acc.financial_institution_id)
    return fi.short_name if fi else None


def _previous_unit_price(
    db: Session, prev_snap: PortfolioSnapshot | None, asset_id: str,
) -> Decimal | None:
    if prev_snap is None:
        return None
    item = (
        db.query(PortfolioSnapshotItem)
        .filter(
            PortfolioSnapshotItem.snapshot_id == prev_snap.id,
            PortfolioSnapshotItem.asset_id == asset_id,
        )
        .first()
    )
    return item.unit_price if item and item.unit_price is not None else None


def _hydrate_pendency(
    db: Session, pen: SnapshotPendency,
    *,
    snap: PortfolioSnapshot | None = None,
    prev_snap: PortfolioSnapshot | None = None,
) -> SnapshotPendencyOut:
    """Build SnapshotPendencyOut with FI short_name + previous price hydrated.

    Pass `prev_snap` to avoid re-querying when hydrating many pendencies in a
    loop. When omitted, looks up via `snap` (or via the pendency's snapshot
    when both are None).
    """
    asset = db.get(Asset, pen.asset_id)
    if prev_snap is None:
        cur = snap or db.get(PortfolioSnapshot, pen.snapshot_id)
        prev_snap = _previous_closed_snapshot(db, cur) if cur else None
    return SnapshotPendencyOut.from_orm(
        pen, asset,
        institution_short_name=_institution_short_name(db, asset),
        previous_unit_price=_previous_unit_price(db, prev_snap, pen.asset_id),
        previous_period_end=prev_snap.period_end_date if prev_snap else None,
    )


# ── Routes ──────────────────────────────────────────────────────────────────


@router.get("", response_model=list[SnapshotOut])
def list_workspace_snapshots(
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    ws_id = _workspace_id(current_user)
    rows = list_snapshots(db, ws_id)
    return [_hydrate_snapshot(db, s) for s in rows]


@router.post("", response_model=SnapshotOut, status_code=status.HTTP_201_CREATED)
def create_workspace_snapshot(
    body: SnapshotCreateRequest,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    ws_id = _workspace_id(current_user)
    if (body.period_end_date is None) == (body.target_ym is None):
        raise HTTPException(
            status_code=400,
            detail="Provide exactly one of period_end_date or target_ym.",
        )
    period_end = (
        body.period_end_date
        if body.period_end_date is not None
        else last_day_of_month(body.target_ym)
    )
    src = SnapshotSource.AUTOMATED if body.auto else SnapshotSource.MANUAL
    try:
        result = create_snapshot(
            db,
            workspace_id=ws_id,
            period_end=period_end,
            user_id=current_user.user_id,
            source=src,
            initial_status=SnapshotStatus.CLOSED,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    snap = db.get(PortfolioSnapshot, result.snapshot_id)
    return _hydrate_snapshot(db, snap)


@router.get("/{snapshot_id}/items", response_model=list[SnapshotItemOut])
def list_snapshot_items(
    snapshot_id: str,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    ws_id = _workspace_id(current_user)
    snap = db.get(PortfolioSnapshot, snapshot_id)
    if not snap or snap.workspace_id != ws_id:
        raise HTTPException(status_code=404, detail="Not found")
    items = db.query(PortfolioSnapshotItem).filter(
        PortfolioSnapshotItem.snapshot_id == snapshot_id
    ).all()
    return [
        SnapshotItemOut(
            asset_id=i.asset_id,
            quantity=str(i.quantity),
            unit_price=str(i.unit_price) if i.unit_price is not None else None,
            market_value_native=str(i.market_value_native) if i.market_value_native is not None else None,
            market_value_brl=str(i.market_value_brl) if i.market_value_brl is not None else None,
            market_value_usd=str(i.market_value_usd) if i.market_value_usd is not None else None,
            average_cost_brl=str(i.average_cost_brl) if i.average_cost_brl is not None else None,
            total_invested_brl=str(i.total_invested_brl) if i.total_invested_brl is not None else None,
        )
        for i in items
    ]


@router.patch(
    "/{snapshot_id}/items/{asset_id}", response_model=SnapshotItemOut,
)
def patch_snapshot_item(
    snapshot_id: str,
    asset_id: str,
    body: SnapshotItemPatchRequest,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    """Spec 49 hotfix #10 — inline edit of a snapshot item from the
    Posições Congeladas table. Only IN_REVIEW snapshots are editable."""
    ws_id = _workspace_id(current_user)
    snap = db.get(PortfolioSnapshot, snapshot_id)
    if not snap or snap.workspace_id != ws_id:
        raise HTTPException(status_code=404, detail="Not found")
    try:
        item = update_snapshot_item_price(
            db,
            snapshot_id=snapshot_id,
            asset_id=asset_id,
            user_id=current_user.user_id,
            user_email=_user_email(db, current_user),
            new_price=body.price,
            value_mode=body.value_mode,
            note=body.note,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return SnapshotItemOut(
        asset_id=item.asset_id,
        quantity=str(item.quantity),
        unit_price=str(item.unit_price) if item.unit_price is not None else None,
        market_value_native=str(item.market_value_native) if item.market_value_native is not None else None,
        market_value_brl=str(item.market_value_brl) if item.market_value_brl is not None else None,
        market_value_usd=str(item.market_value_usd) if item.market_value_usd is not None else None,
        average_cost_brl=str(item.average_cost_brl) if item.average_cost_brl is not None else None,
        total_invested_brl=str(item.total_invested_brl) if item.total_invested_brl is not None else None,
    )


# ── Spec 35 endpoints ───────────────────────────────────────────────────────


@router.get("/{snapshot_id}/pendencies", response_model=list[SnapshotPendencyOut])
def list_snapshot_pendencies(
    snapshot_id: str,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    ws_id = _workspace_id(current_user)
    snap = db.get(PortfolioSnapshot, snapshot_id)
    if not snap or snap.workspace_id != ws_id:
        raise HTTPException(status_code=404, detail="Not found")
    rows = list_pendencies(db, snapshot_id)
    prev_snap = _previous_closed_snapshot(db, snap)
    return [_hydrate_pendency(db, p, snap=snap, prev_snap=prev_snap) for p in rows]


@router.post("/{snapshot_id}/confirm", response_model=SnapshotOut)
def confirm(
    snapshot_id: str,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    ws_id = _workspace_id(current_user)
    snap = db.get(PortfolioSnapshot, snapshot_id)
    if not snap or snap.workspace_id != ws_id:
        raise HTTPException(status_code=404, detail="Not found")
    try:
        snap = confirm_snapshot(
            db, snapshot_id=snapshot_id,
            user_id=current_user.user_id,
            user_email=_user_email(db, current_user),
        )
    except PendencyOpenError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    return _hydrate_snapshot(db, snap)


@router.post("/{snapshot_id}/reopen", response_model=SnapshotOut)
def reopen(
    snapshot_id: str,
    body: SnapshotReopenRequest,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    ws_id = _workspace_id(current_user)
    snap = db.get(PortfolioSnapshot, snapshot_id)
    if not snap or snap.workspace_id != ws_id:
        raise HTTPException(status_code=404, detail="Not found")
    snap = reopen_snapshot(
        db, snapshot_id=snapshot_id,
        user_id=current_user.user_id,
        user_email=_user_email(db, current_user),
        reason=body.reason,
    )
    return _hydrate_snapshot(db, snap)


def _pendency_or_404(db: Session, pendency_id: str, ws_id: str) -> SnapshotPendency:
    pen = db.get(SnapshotPendency, pendency_id)
    if not pen:
        raise HTTPException(status_code=404, detail="Pendency not found")
    snap = db.get(PortfolioSnapshot, pen.snapshot_id)
    if not snap or snap.workspace_id != ws_id:
        raise HTTPException(status_code=404, detail="Pendency not found")
    return pen


@router.post("/pendencies/{pendency_id}/resolve", response_model=SnapshotPendencyOut)
def resolve(
    pendency_id: str,
    body: PendencyResolveRequest,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    ws_id = _workspace_id(current_user)
    _pendency_or_404(db, pendency_id, ws_id)
    pen = resolve_pendency(
        db, pendency_id=pendency_id,
        user_id=current_user.user_id,
        user_email=_user_email(db, current_user),
        new_price=body.new_price,
        file_id=body.file_id,
        note=body.note,
    )
    return _hydrate_pendency(db, pen)


@router.post("/pendencies/{pendency_id}/retry-api", response_model=SnapshotPendencyOut)
def retry_api(
    pendency_id: str,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    ws_id = _workspace_id(current_user)
    _pendency_or_404(db, pendency_id, ws_id)
    try:
        pen = retry_pendency_api(
            db, pendency_id=pendency_id,
            user_id=current_user.user_id,
            user_email=_user_email(db, current_user),
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return _hydrate_pendency(db, pen)


# ── Spec 48 — bulk extract upload ───────────────────────────────────────────


@router.post("/{snapshot_id}/bulk-extract", status_code=status.HTTP_201_CREATED)
def bulk_extract(
    snapshot_id: str,
    body: BulkExtractRequest,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    """Spec 48 — create + run an ExtractionJob scoped to the snapshot.

    Forces source_hint=BROKER_POSITION. No pendency_id (the bulk applier
    resolves N pendencies in one go at confirm time).
    """
    ws_id = _workspace_id(current_user)
    snap = db.get(PortfolioSnapshot, snapshot_id)
    if not snap or snap.workspace_id != ws_id:
        raise HTTPException(status_code=404, detail="Not found")
    if snap.status != SnapshotStatus.IN_REVIEW:
        raise HTTPException(
            status_code=409,
            detail="Bulk extract only allowed on IN_REVIEW snapshots",
        )
    try:
        job = extraction_service.create_and_run(
            db,
            workspace_id=ws_id,
            attachment_id=body.attachment_id,
            source_hint=ExtractionSourceHint.BROKER_POSITION,
            snapshot_id=snapshot_id,
            pendency_id=None,
            asset_id=None,
            user_id=current_user.user_id,
            user_email=_user_email(db, current_user),
        )
    except extraction_service.ExtractionError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "id": job.id,
        "status": job.status.value,
        "extracted_json": job.extracted_json,
        "error_message": job.error_message,
    }


@router.get("/{snapshot_id}/extractions", response_model=list[BulkExtractionJobOut])
def list_bulk_extractions(
    snapshot_id: str,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    """Spec 49 — list bulk ExtractionJobs scoped to this snapshot.

    Filters out per-pendency jobs (`pendency_id IS NOT NULL`) since those
    belong to the single-asset Spec 38 flow, not the bulk UX.
    """
    ws_id = _workspace_id(current_user)
    snap = db.get(PortfolioSnapshot, snapshot_id)
    if not snap or snap.workspace_id != ws_id:
        raise HTTPException(status_code=404, detail="Not found")
    rows = (
        db.query(ExtractionJob)
        .filter(
            ExtractionJob.snapshot_id == snapshot_id,
            ExtractionJob.pendency_id.is_(None),
        )
        .order_by(ExtractionJob.created_at.desc())
        .all()
    )
    return [BulkExtractionJobOut.from_orm(j) for j in rows]
