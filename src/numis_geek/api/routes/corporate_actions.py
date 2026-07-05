"""CRUD for CorporateAction (splits/groupings/conversions)."""
import uuid
from datetime import date as date_t, datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from numis_geek.api.deps import get_current_user, get_db
from numis_geek.models.asset import Asset
from numis_geek.models.corporate_action import (
    CORPORATE_ACTION_TYPE_LABELS,
    CorporateAction,
    CorporateActionType,
)
from numis_geek.models.user import UserRole
from numis_geek.services.auth import UserContext
from numis_geek.services.snapshot import find_affected_snapshots

router = APIRouter(prefix="/corporate-actions", tags=["corporate-actions"])


class AffectedSnapshotLite(BaseModel):
    """Spec 51 Bloco 2 — mirror of routes/snapshots.AffectedSnapshotOut
    kept tiny on purpose so corp action callers can fold the list
    into their own response without circular import."""
    snapshot_id: str
    period_end_date: str
    ym: str
    status: str
    has_item: bool
    asset_id: str           # qual ativo foi alterado (relevante pra CONVERSION)
    old_quantity: str
    new_quantity: str
    old_market_value_brl: str | None
    new_market_value_brl: str | None
    old_total_invested_brl: str | None
    new_total_invested_brl: str | None


class CorporateActionOut(BaseModel):
    id: str
    workspace_id: str
    asset_id: str
    asset_ticker: str | None
    event_date: str
    event_type: str
    event_type_label: str
    ratio: str
    target_asset_id: str | None
    target_ratio: str | None
    notes: str | None
    is_active: bool

    @classmethod
    def from_orm(cls, c: CorporateAction, db: Session) -> "CorporateActionOut":
        asset = db.get(Asset, c.asset_id)
        return cls(
            id=c.id,
            workspace_id=c.workspace_id,
            asset_id=c.asset_id,
            asset_ticker=asset.ticker if asset else None,
            event_date=c.event_date.isoformat(),
            event_type=c.event_type.value,
            event_type_label=CORPORATE_ACTION_TYPE_LABELS[c.event_type],
            ratio=str(c.ratio),
            target_asset_id=c.target_asset_id,
            target_ratio=str(c.target_ratio) if c.target_ratio is not None else None,
            notes=c.notes,
            is_active=c.is_active,
        )


class CorporateActionRequest(BaseModel):
    asset_id: str
    event_date: date_t
    event_type: CorporateActionType
    ratio: Decimal
    target_asset_id: str | None = None
    target_ratio: Decimal | None = None
    notes: str | None = None


class CorporateActionCreateOut(BaseModel):
    """Spec 51 Bloco 2 — POST /corporate-actions devolve o CA criado +
    lista de fechamentos afetados pra UI seguir o flow de reconciliação."""
    corporate_action: CorporateActionOut
    affected_snapshots: list[AffectedSnapshotLite]


class CorporateActionPreviewRequest(BaseModel):
    """Spec 51 Bloco 2 — preview do impacto antes do CA estar persistido.
    Para CA do tipo SPLIT/GROUPING, basta asset_id + event_date. Para
    ASSET_CONVERSION, target_asset_id também entra na varredura."""
    asset_id: str
    event_date: date_t
    target_asset_id: str | None = None


def _affected_lite_for(
    db: Session, *, workspace_id: str, asset_id: str, event_date: date_t,
) -> list[AffectedSnapshotLite]:
    affected = find_affected_snapshots(
        db, workspace_id=workspace_id, asset_id=asset_id,
        earliest_event_date=event_date,
    )
    def _s(v):
        return None if v is None else str(v)
    return [
        AffectedSnapshotLite(
            snapshot_id=a.snapshot_id,
            period_end_date=a.period_end_date.isoformat(),
            ym=a.ym,
            status=a.status.value,
            has_item=a.has_item,
            asset_id=asset_id,
            old_quantity=str(a.old_quantity),
            new_quantity=str(a.new_quantity),
            old_market_value_brl=_s(a.old_market_value_brl),
            new_market_value_brl=_s(a.new_market_value_brl),
            old_total_invested_brl=_s(a.old_total_invested_brl),
            new_total_invested_brl=_s(a.new_total_invested_brl),
        )
        for a in affected
    ]


def _check_workspace(asset: Asset, current_user: UserContext) -> None:
    if current_user.role == UserRole.sysadmin:
        return
    if asset.workspace_id != current_user.workspace_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Workspace mismatch")


@router.get("", response_model=list[CorporateActionOut])
def list_corporate_actions(
    asset_id: str | None = Query(None),
    workspace_id: str | None = Query(None),
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    q = db.query(CorporateAction).filter(CorporateAction.is_active == True)  # noqa: E712
    if current_user.role == UserRole.sysadmin:
        # Sysadmin híbrido → default no do user; ?workspace_id= sobrescreve.
        target_ws = workspace_id or current_user.workspace_id
        if target_ws:
            q = q.filter(CorporateAction.workspace_id == target_ws)
    else:
        q = q.filter(CorporateAction.workspace_id == current_user.workspace_id)
    if asset_id:
        q = q.filter(CorporateAction.asset_id == asset_id)
    rows = q.order_by(CorporateAction.event_date.desc()).all()
    return [CorporateActionOut.from_orm(c, db) for c in rows]


@router.post("", response_model=CorporateActionCreateOut, status_code=status.HTTP_201_CREATED)
def create_corporate_action(
    body: CorporateActionRequest,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    asset = db.get(Asset, body.asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    _check_workspace(asset, current_user)

    # Convenção do modelo: SPLIT tem ratio > 1 (2:1, 4:1); GROUPING tem
    # ratio < 1 (25→1 é ratio=0.04, ver models/corporate_action.py). Bug
    # herdado do import Notion do BHIA3: gravou GROUPING 25:1 como
    # ratio=25, inflando qty 25× em todos os fechamentos afetados.
    if body.event_type == CorporateActionType.SPLIT and body.ratio <= 1:
        raise HTTPException(
            status_code=422,
            detail="SPLIT precisa ratio > 1 (2:1 → 2). Se é agrupamento, use GROUPING com ratio < 1.",
        )
    if body.event_type == CorporateActionType.GROUPING and body.ratio >= 1:
        raise HTTPException(
            status_code=422,
            detail="GROUPING precisa ratio < 1 (25→1 → 0.04). Se é desdobramento, use SPLIT com ratio > 1.",
        )

    target: Asset | None = None
    if body.event_type == CorporateActionType.ASSET_CONVERSION:
        if not body.target_asset_id or body.target_ratio is None:
            raise HTTPException(
                status_code=422,
                detail="ASSET_CONVERSION requires target_asset_id + target_ratio",
            )
        target = db.get(Asset, body.target_asset_id)
        if not target:
            raise HTTPException(status_code=422, detail="Target asset not found")

    now = datetime.now(timezone.utc)
    c = CorporateAction(
        id=str(uuid.uuid4()),
        workspace_id=asset.workspace_id,
        asset_id=body.asset_id,
        event_date=body.event_date,
        event_type=body.event_type,
        ratio=body.ratio,
        target_asset_id=body.target_asset_id,
        target_ratio=body.target_ratio,
        notes=body.notes,
        is_active=True,
        created_at=now, updated_at=now,
        created_by=current_user.user_id, updated_by=current_user.user_id,
    )
    db.add(c)
    db.flush()

    # Spec 51 Bloco 2 — varre snapshots afetados. Para CONVERSION inclui
    # também o target_asset_id (ativo destino que ganha posição).
    affected = _affected_lite_for(
        db, workspace_id=asset.workspace_id,
        asset_id=body.asset_id, event_date=body.event_date,
    )
    if target is not None:
        affected.extend(_affected_lite_for(
            db, workspace_id=target.workspace_id,
            asset_id=target.id, event_date=body.event_date,
        ))

    return CorporateActionCreateOut(
        corporate_action=CorporateActionOut.from_orm(c, db),
        affected_snapshots=affected,
    )


@router.post(
    "/preview-impact", response_model=list[AffectedSnapshotLite],
)
def preview_corporate_action_impact(
    body: CorporateActionPreviewRequest,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    """Spec 51 Bloco 2 — sonda o impacto de um CA hipotético em
    fechamentos do workspace, sem persistir."""
    asset = db.get(Asset, body.asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    _check_workspace(asset, current_user)

    out = _affected_lite_for(
        db, workspace_id=asset.workspace_id,
        asset_id=body.asset_id, event_date=body.event_date,
    )
    if body.target_asset_id:
        target = db.get(Asset, body.target_asset_id)
        if target is not None:
            _check_workspace(target, current_user)
            out.extend(_affected_lite_for(
                db, workspace_id=target.workspace_id,
                asset_id=target.id, event_date=body.event_date,
            ))
    return out


@router.delete("/{ca_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_corporate_action(
    ca_id: str,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    c = db.get(CorporateAction, ca_id)
    if not c:
        raise HTTPException(status_code=404, detail="Not found")
    asset = db.get(Asset, c.asset_id)
    if asset:
        _check_workspace(asset, current_user)
    c.is_active = False
    c.updated_at = datetime.now(timezone.utc)
    c.updated_by = current_user.user_id
    db.flush()
    return None


@router.get("/{ca_id}/affected-snapshots", response_model=list[AffectedSnapshotLite])
def list_affected_for_corp_action(
    ca_id: str,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    """Spec 51 Bloco 2 — segunda chance pra um CA já persistido:
    devolve a lista de snapshots ainda divergentes deste CA."""
    c = db.get(CorporateAction, ca_id)
    if not c:
        raise HTTPException(status_code=404, detail="Not found")
    asset = db.get(Asset, c.asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    _check_workspace(asset, current_user)

    out = _affected_lite_for(
        db, workspace_id=asset.workspace_id,
        asset_id=c.asset_id, event_date=c.event_date,
    )
    if c.target_asset_id:
        target = db.get(Asset, c.target_asset_id)
        if target is not None:
            out.extend(_affected_lite_for(
                db, workspace_id=target.workspace_id,
                asset_id=target.id, event_date=c.event_date,
            ))
    return out
