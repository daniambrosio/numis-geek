"""Portfolio snapshot routes (Spec 14 + 35).

Spec 35 adds:
- status, closed_at/by, pendencies counts on SnapshotOut.
- GET /snapshots/{id}/pendencies
- POST /snapshots/{id}/confirm
- POST /snapshots/{id}/reopen
- POST /snapshots/pendencies/{pid}/resolve
- POST /snapshots/pendencies/{pid}/retry-api
"""
import json
from datetime import date as date_t
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from numis_geek.api.deps import get_current_user, get_db
from numis_geek.models.account import Account
from numis_geek.models.asset import Asset
from numis_geek.models.audit_log import AuditLog
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
    add_snapshot_item,
    apply_recompute_to_snapshot,
    apply_skip_recompute,
    confirm_delta_pendency,
    confirm_snapshot,
    create_snapshot,
    delete_snapshot_item,
    detect_suspicious_deltas,
    find_affected_snapshots,
    list_mom_deltas,
    list_pendencies,
    list_snapshots,
    reopen_snapshot,
    resolve_pendency,
    retry_pendency_api,
    sync_snapshot_items,
    update_snapshot_item_price,
)
from numis_geek.utils.business_day import last_day_of_month

router = APIRouter(prefix="/snapshots", tags=["snapshots"])


# ── Schemas ─────────────────────────────────────────────────────────────────


class SnapshotItemOut(BaseModel):
    id: str
    asset_id: str
    quantity: str
    unit_price: str | None
    market_value_native: str | None
    market_value_brl: str | None
    market_value_usd: str | None
    average_cost_brl: str | None
    total_invested_brl: str | None
    updated_at: str

    @classmethod
    def from_orm(cls, i: PortfolioSnapshotItem) -> "SnapshotItemOut":
        return cls(
            id=i.id,
            asset_id=i.asset_id,
            quantity=str(i.quantity),
            unit_price=str(i.unit_price) if i.unit_price is not None else None,
            market_value_native=str(i.market_value_native) if i.market_value_native is not None else None,
            market_value_brl=str(i.market_value_brl) if i.market_value_brl is not None else None,
            market_value_usd=str(i.market_value_usd) if i.market_value_usd is not None else None,
            average_cost_brl=str(i.average_cost_brl) if i.average_cost_brl is not None else None,
            total_invested_brl=str(i.total_invested_brl) if i.total_invested_brl is not None else None,
            updated_at=i.updated_at.isoformat(),
        )


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

    `quantity` (opcional) — override do qty do item quando o histórico de
    movements ficou fora de sincronia com o extrato do custodiante (ex:
    fundos com bonificação/come-cotas não capturada). Persiste no
    snapshot_item.quantity; NÃO cria movement nem reescreve a posição
    calculada. Se omitido, o qty herdado do movement history é mantido.
    """
    price: Decimal = Field(..., ge=0)
    value_mode: str | None = Field(default=None, pattern=r"^(unit|total)$")
    quantity: Decimal | None = Field(default=None, ge=0)
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
    # Spec 58 — when set, the job was scoped to this FI at creation time.
    institution_id: str | None
    institution_short_name: str | None
    # Spec 58 Stage 4 — distinguishes positions (BROKER_POSITION) from
    # proventos (BROKER_INCOME) so the UI can show each in its own bucket.
    source_hint: str

    @classmethod
    def from_orm(cls, j: ExtractionJob) -> "BulkExtractionJobOut":
        # Items count varies by source_hint: positions[] for BROKER_POSITION,
        # events[] for BROKER_INCOME. Use whichever the payload has.
        items_count = 0
        if j.extracted_json:
            items_count = (
                len(j.extracted_json.get("positions") or [])
                or len(j.extracted_json.get("events") or [])
            )
        fi_short = None
        if j.institution_id:
            from numis_geek.models.financial_institution import (
                FinancialInstitution,
            )
            from sqlalchemy.orm.session import Session as _SessionType
            sess = _SessionType.object_session(j)
            if sess is not None:
                fi = sess.get(FinancialInstitution, j.institution_id)
                fi_short = fi.short_name if fi else None
        return cls(
            id=j.id,
            attachment_id=j.attachment_id,
            status=j.status.value,
            positions_count=items_count,
            error_message=j.error_message,
            created_at=j.created_at.isoformat() if j.created_at else "",
            completed_at=j.completed_at.isoformat() if j.completed_at else None,
            confirmed_at=j.confirmed_at.isoformat() if j.confirmed_at else None,
            model=j.model,
            input_tokens=j.input_tokens,
            output_tokens=j.output_tokens,
            cost_usd=str(j.cost_usd) if j.cost_usd is not None else None,
            institution_id=j.institution_id,
            institution_short_name=fi_short,
            source_hint=j.source_hint.value,
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
    asset_currency: str | None
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
            asset_currency=(
                asset.currency.value if asset and asset.currency else None
            ),
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
    # Sysadmin sem workspace_id (o "puro", CLAUDE.md classic) precisa
    # scoping explícito por query param. Sysadmin COM workspace_id
    # (padrão híbrido — user promovido mas mantido na workspace de uso
    # diária) opera na dele por default. Antes ambos batiam 400 e o
    # front engolia (setSnaps nunca chamado, virava "0 apurações").
    if current_user.role == UserRole.sysadmin and not current_user.workspace_id:
        raise HTTPException(
            status_code=400,
            detail="Sysadmin sem workspace precisa especificar workspace_id.",
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
    return [SnapshotItemOut.from_orm(i) for i in items]


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
            new_quantity=body.quantity,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return SnapshotItemOut.from_orm(item)


@router.delete(
    "/{snapshot_id}/items/{asset_id}", status_code=204,
)
def delete_snapshot_item_route(
    snapshot_id: str,
    asset_id: str,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    """Spec 49 hotfix #11 — remove an asset entry from a frozen snapshot.

    Used when a retroactive movement means the asset shouldn't appear
    in the period at all. Only allowed on IN_REVIEW snapshots."""
    ws_id = _workspace_id(current_user)
    snap = db.get(PortfolioSnapshot, snapshot_id)
    if not snap or snap.workspace_id != ws_id:
        raise HTTPException(status_code=404, detail="Not found")
    try:
        delete_snapshot_item(
            db,
            snapshot_id=snapshot_id,
            asset_id=asset_id,
            user_id=current_user.user_id,
            user_email=_user_email(db, current_user),
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return None


class SyncItemsOut(BaseModel):
    """Spec 49 hotfix #12 — summary returned by the sync-items endpoint."""
    items_added: int
    pendencies_added: int


class AddSnapshotItemRequest(BaseModel):
    """Spec 49 hotfix #12 — manual single-asset add to an IN_REVIEW snapshot."""
    asset_id: str


class AffectedSnapshotPreviewRequest(BaseModel):
    """Spec 51 — preview the impact a (proposed or saved) retroactive
    event would have on existing snapshots."""
    asset_id: str
    event_date: date_t


class AffectedSnapshotOut(BaseModel):
    snapshot_id: str
    period_end_date: str           # YYYY-MM-DD
    ym: str                        # YYYY-MM
    status: str
    has_item: bool
    old_quantity: str
    new_quantity: str
    old_market_value_brl: str | None
    new_market_value_brl: str | None
    old_total_invested_brl: str | None
    new_total_invested_brl: str | None
    snapshot_total_value_brl: str


class RecomputeRequest(BaseModel):
    trigger_event_type: str = Field(..., max_length=64)
    trigger_event_id: str = Field(..., max_length=64)


class SkipRecomputeRequest(BaseModel):
    trigger_event_type: str = Field(..., max_length=64)
    trigger_event_id: str = Field(..., max_length=64)
    reason: str = Field(..., min_length=1, max_length=500)


class DriftEntryOut(BaseModel):
    """Spec 51 Bloco 3 — entrada do painel 'Divergências aceitas' no
    SnapshotDetail. Cada item vem do audit_log
    (action='snapshot.recompute.skipped')."""
    asset_id: str
    asset_name: str | None
    asset_ticker: str | None
    trigger_event_type: str
    trigger_event_id: str
    reason: str
    user_email: str
    created_at: str


@router.post(
    "/{snapshot_id}/sync-items", response_model=SyncItemsOut,
)
def sync_snapshot_items_route(
    snapshot_id: str,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    """Spec 49 hotfix #12 — add missing items to an IN_REVIEW snapshot.

    Picks up assets that should be in the snapshot (have a position at
    period_end) but aren't — typically VALUE-mode assets excluded by
    the historical `qty == 0` guard. Existing items remain frozen."""
    ws_id = _workspace_id(current_user)
    snap = db.get(PortfolioSnapshot, snapshot_id)
    if not snap or snap.workspace_id != ws_id:
        raise HTTPException(status_code=404, detail="Not found")
    try:
        result = sync_snapshot_items(
            db,
            snapshot_id=snapshot_id,
            user_id=current_user.user_id,
            user_email=_user_email(db, current_user),
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return SyncItemsOut(
        items_added=result["items_added"],
        pendencies_added=result["pendencies_added"],
    )


@router.post(
    "/{snapshot_id}/items", response_model=SnapshotItemOut, status_code=201,
)
def add_snapshot_item_route(
    snapshot_id: str,
    body: AddSnapshotItemRequest,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    """Spec 49 hotfix #12 — manually add a single asset to a snapshot.

    Validates workspace/active/duplicate/IN_REVIEW. Initial market_value
    reflects the asset's current_price (NULL → user edits later)."""
    ws_id = _workspace_id(current_user)
    snap = db.get(PortfolioSnapshot, snapshot_id)
    if not snap or snap.workspace_id != ws_id:
        raise HTTPException(status_code=404, detail="Not found")
    try:
        item = add_snapshot_item(
            db,
            snapshot_id=snapshot_id,
            asset_id=body.asset_id,
            user_id=current_user.user_id,
            user_email=_user_email(db, current_user),
        )
    except ValueError as e:
        msg = str(e)
        status = 404 if "not found" in msg.lower() else 409
        raise HTTPException(status_code=status, detail=msg)
    return SnapshotItemOut.from_orm(item)


# ── Spec 51 — Retroactive Event Reconciliation ─────────────────────────────


def _aff_out(a) -> AffectedSnapshotOut:
    def s(v):
        return None if v is None else str(v)
    return AffectedSnapshotOut(
        snapshot_id=a.snapshot_id,
        period_end_date=a.period_end_date.isoformat(),
        ym=a.ym,
        status=a.status.value,
        has_item=a.has_item,
        old_quantity=str(a.old_quantity),
        new_quantity=str(a.new_quantity),
        old_market_value_brl=s(a.old_market_value_brl),
        new_market_value_brl=s(a.new_market_value_brl),
        old_total_invested_brl=s(a.old_total_invested_brl),
        new_total_invested_brl=s(a.new_total_invested_brl),
        snapshot_total_value_brl=str(a.snapshot_total_value_brl),
    )


@router.post(
    "/affected-snapshots", response_model=list[AffectedSnapshotOut],
)
def preview_affected_snapshots(
    body: AffectedSnapshotPreviewRequest,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    """Spec 51 — preview do impacto que um evento (já salvo ou hipotético)
    teria em fechamentos existentes do ativo."""
    ws_id = _workspace_id(current_user)
    if ws_id is None:
        raise HTTPException(status_code=400, detail="workspace required")
    affected = find_affected_snapshots(
        db,
        workspace_id=ws_id,
        asset_id=body.asset_id,
        earliest_event_date=body.event_date,
    )
    return [_aff_out(a) for a in affected]


@router.post(
    "/{snapshot_id}/items/{asset_id}/recompute",
    response_model=SnapshotItemOut,
)
def recompute_snapshot_item_route(
    snapshot_id: str,
    asset_id: str,
    body: RecomputeRequest,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    """Spec 51 — recomputa o item, com auto-reopen se CLOSED."""
    ws_id = _workspace_id(current_user)
    snap = db.get(PortfolioSnapshot, snapshot_id)
    if not snap or snap.workspace_id != ws_id:
        raise HTTPException(status_code=404, detail="Not found")
    try:
        item = apply_recompute_to_snapshot(
            db,
            snapshot_id=snapshot_id,
            asset_id=asset_id,
            trigger_event_type=body.trigger_event_type,
            trigger_event_id=body.trigger_event_id,
            user_id=current_user.user_id,
            user_email=_user_email(db, current_user),
        )
    except ValueError as e:
        msg = str(e)
        status_code = 404 if "not found" in msg.lower() else 409
        raise HTTPException(status_code=status_code, detail=msg)
    return SnapshotItemOut.from_orm(item)


@router.post(
    "/{snapshot_id}/items/{asset_id}/skip-recompute",
    status_code=204,
)
def skip_recompute_route(
    snapshot_id: str,
    asset_id: str,
    body: SkipRecomputeRequest,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    """Spec 51 — grava no audit que o usuário decidiu NÃO recomputar."""
    ws_id = _workspace_id(current_user)
    snap = db.get(PortfolioSnapshot, snapshot_id)
    if not snap or snap.workspace_id != ws_id:
        raise HTTPException(status_code=404, detail="Not found")
    try:
        apply_skip_recompute(
            db,
            snapshot_id=snapshot_id,
            asset_id=asset_id,
            trigger_event_type=body.trigger_event_type,
            trigger_event_id=body.trigger_event_id,
            reason=body.reason,
            user_id=current_user.user_id,
            user_email=_user_email(db, current_user),
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return None


@router.get(
    "/{snapshot_id}/drift", response_model=list[DriftEntryOut],
)
def list_snapshot_drift(
    snapshot_id: str,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    """Spec 51 Bloco 3 — lista entradas de 'drift consciente' do snapshot:
    items onde o usuário viu o impacto de um evento retroativo e
    escolheu 'Manter divergência'. Source: audit_log
    (action='snapshot.recompute.skipped')."""
    ws_id = _workspace_id(current_user)
    snap = db.get(PortfolioSnapshot, snapshot_id)
    if not snap or snap.workspace_id != ws_id:
        raise HTTPException(status_code=404, detail="Not found")

    rows = (
        db.query(AuditLog)
        .filter(
            AuditLog.action == "snapshot.recompute.skipped",
            AuditLog.workspace_id == snap.workspace_id,
            AuditLog.resource_id.like(f"{snapshot_id}:%"),
        )
        .order_by(AuditLog.created_at.desc())
        .all()
    )

    out: list[DriftEntryOut] = []
    seen_assets: set[str] = set()
    for r in rows:
        try:
            details = json.loads(r.details or "{}")
        except Exception:
            details = {}
        asset_id = details.get("asset_id") or ""
        # Só mostra a entrada MAIS RECENTE por ativo (audit é DESC).
        if asset_id in seen_assets:
            continue
        seen_assets.add(asset_id)
        asset = db.get(Asset, asset_id) if asset_id else None
        out.append(DriftEntryOut(
            asset_id=asset_id,
            asset_name=asset.name if asset else None,
            asset_ticker=asset.ticker if asset else None,
            trigger_event_type=details.get("trigger_event_type") or "",
            trigger_event_id=details.get("trigger_event_id") or "",
            reason=details.get("reason") or "",
            user_email=r.user_email,
            created_at=r.created_at.isoformat() if r.created_at else "",
        ))
    return out


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


# ═══════════════════════════════════════════════════════════════════════════
# Spec 62 — SUSPICIOUS_DELTA endpoints
# ═══════════════════════════════════════════════════════════════════════════


class MoMDeltaRowOut(BaseModel):
    asset_id: str
    asset_name: str
    asset_ticker: str | None
    asset_class: str
    currency: str
    previous_mv_native: str | None
    current_mv_native: str | None
    delta_native: str | None
    delta_pct: str | None
    threshold_pct: str
    status: str
    pendency_id: str | None
    pendency_resolved: bool


class MoMDeltaResponse(BaseModel):
    snapshot_id: str
    previous_snapshot_id: str | None
    previous_period_end: str | None
    rows: list[MoMDeltaRowOut]


class ConfirmDeltaRequest(BaseModel):
    note: str | None = None


@router.get("/{snapshot_id}/mom-deltas", response_model=MoMDeltaResponse)
def list_snapshot_mom_deltas(
    snapshot_id: str,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    """Spec 62 — retorna comparativo MoM ativo-a-ativo do snapshot vs
    o snapshot CLOSED anterior. Popula o bloco MoMDeltaBlock no topo do
    Snapshot Detail."""
    ws_id = _workspace_id(current_user)
    snap = db.get(PortfolioSnapshot, snapshot_id)
    if snap is None or snap.workspace_id != ws_id:
        raise HTTPException(status_code=404, detail="Snapshot not found")

    rows = list_mom_deltas(db, snapshot_id)
    prev = (
        db.query(PortfolioSnapshot)
        .filter(
            PortfolioSnapshot.workspace_id == snap.workspace_id,
            PortfolioSnapshot.is_active == True,  # noqa: E712
            PortfolioSnapshot.status == SnapshotStatus.CLOSED,
            PortfolioSnapshot.period_end_date < snap.period_end_date,
        )
        .order_by(PortfolioSnapshot.period_end_date.desc())
        .first()
    )
    return MoMDeltaResponse(
        snapshot_id=snapshot_id,
        previous_snapshot_id=prev.id if prev else None,
        previous_period_end=prev.period_end_date.isoformat() if prev else None,
        rows=[
            MoMDeltaRowOut(
                asset_id=r.asset_id,
                asset_name=r.asset_name,
                asset_ticker=r.asset_ticker,
                asset_class=r.asset_class,
                currency=r.currency,
                previous_mv_native=str(r.previous_mv_native) if r.previous_mv_native is not None else None,
                current_mv_native=str(r.current_mv_native) if r.current_mv_native is not None else None,
                delta_native=str(r.delta_native) if r.delta_native is not None else None,
                delta_pct=str(r.delta_pct) if r.delta_pct is not None else None,
                threshold_pct=str(r.threshold_pct),
                status=r.status,
                pendency_id=r.pendency_id,
                pendency_resolved=r.pendency_resolved,
            )
            for r in rows
        ],
    )


@router.post("/{snapshot_id}/recheck-deltas", response_model=list[SnapshotPendencyOut])
def recheck_snapshot_deltas(
    snapshot_id: str,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    """Spec 62 — re-avalia SUSPICIOUS_DELTA em items existentes.

    Útil quando o user editou items manualmente e quer forçar
    re-avaliação. Só cria pendencies novas; não remove existentes."""
    ws_id = _workspace_id(current_user)
    snap = db.get(PortfolioSnapshot, snapshot_id)
    if snap is None or snap.workspace_id != ws_id:
        raise HTTPException(status_code=404, detail="Snapshot not found")

    new_ids = detect_suspicious_deltas(db, snapshot_id)
    new_pens = [db.get(SnapshotPendency, pid) for pid in new_ids]
    return [
        _hydrate_pendency(db, p) for p in new_pens if p is not None
    ]


@router.post(
    "/pendencies/{pendency_id}/confirm-delta",
    response_model=SnapshotPendencyOut,
)
def confirm_delta(
    pendency_id: str,
    body: ConfirmDeltaRequest,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    """Spec 62 — user confirma "sim, esse delta é real" sem editar dado."""
    ws_id = _workspace_id(current_user)
    _pendency_or_404(db, pendency_id, ws_id)
    try:
        pen = confirm_delta_pendency(
            db, pendency_id=pendency_id,
            user_id=current_user.user_id,
            user_email=_user_email(db, current_user),
            note=body.note,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _hydrate_pendency(db, pen)


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


# ── Spec 58 Stage 4 — bulk income (proventos) scoped to one FI ──────────────


@router.post(
    "/{snapshot_id}/institutions/{fi_id}/bulk-income",
    status_code=status.HTTP_201_CREATED,
)
def bulk_income_per_fi(
    snapshot_id: str,
    fi_id: str,
    body: BulkExtractRequest,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    """Spec 58 Stage 4 — bulk income (proventos) extraction.

    Creates an ExtractionJob with source_hint=BROKER_INCOME scoped to
    the given FI. Deterministic parsers (parse_avenue_proventos_csv,
    etc.) handle known broker formats without LLM cost; everything else
    falls back to the placeholder BROKER_INCOME LLM template.
    """
    ws_id = _workspace_id(current_user)
    snap = db.get(PortfolioSnapshot, snapshot_id)
    if not snap or snap.workspace_id != ws_id:
        raise HTTPException(status_code=404, detail="Not found")
    if snap.status != SnapshotStatus.IN_REVIEW:
        raise HTTPException(
            status_code=409,
            detail="Bulk income only allowed on IN_REVIEW snapshots",
        )
    fi = db.get(FinancialInstitution, fi_id)
    if not fi:
        raise HTTPException(status_code=404, detail="Institution not found")
    try:
        job = extraction_service.create_and_run(
            db,
            workspace_id=ws_id,
            attachment_id=body.attachment_id,
            source_hint=ExtractionSourceHint.BROKER_INCOME,
            snapshot_id=snapshot_id,
            institution_id=fi_id,
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
        "institution_id": job.institution_id,
        "institution_short_name": fi.short_name,
    }


# ── Spec 58 — bulk extract scoped to one FI ─────────────────────────────────


@router.post(
    "/{snapshot_id}/institutions/{fi_id}/bulk-extract",
    status_code=status.HTTP_201_CREATED,
)
def bulk_extract_per_fi(
    snapshot_id: str,
    fi_id: str,
    body: BulkExtractRequest,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    """Spec 58 — create + run an ExtractionJob scoped to a single FI.

    Same as POST /snapshots/{id}/bulk-extract but the job carries
    `institution_id`, which downstream limits the candidate Asset pool
    and skips the FI-dropdown in the review modal.
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
    fi = db.get(FinancialInstitution, fi_id)
    if not fi:
        raise HTTPException(status_code=404, detail="Institution not found")
    try:
        job = extraction_service.create_and_run(
            db,
            workspace_id=ws_id,
            attachment_id=body.attachment_id,
            source_hint=ExtractionSourceHint.BROKER_POSITION,
            snapshot_id=snapshot_id,
            institution_id=fi_id,
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
        "institution_id": job.institution_id,
        "institution_short_name": fi.short_name,
    }
