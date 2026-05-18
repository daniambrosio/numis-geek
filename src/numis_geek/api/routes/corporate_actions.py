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

router = APIRouter(prefix="/corporate-actions", tags=["corporate-actions"])


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


def _check_workspace(asset: Asset, current_user: UserContext) -> None:
    if current_user.role == UserRole.sysadmin:
        return
    if asset.workspace_id != current_user.workspace_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Workspace mismatch")


@router.get("", response_model=list[CorporateActionOut])
def list_corporate_actions(
    asset_id: str | None = Query(None),
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    q = db.query(CorporateAction).filter(CorporateAction.is_active == True)  # noqa: E712
    if current_user.role != UserRole.sysadmin:
        q = q.filter(CorporateAction.workspace_id == current_user.workspace_id)
    if asset_id:
        q = q.filter(CorporateAction.asset_id == asset_id)
    rows = q.order_by(CorporateAction.event_date.desc()).all()
    return [CorporateActionOut.from_orm(c, db) for c in rows]


@router.post("", response_model=CorporateActionOut, status_code=status.HTTP_201_CREATED)
def create_corporate_action(
    body: CorporateActionRequest,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    asset = db.get(Asset, body.asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    _check_workspace(asset, current_user)

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
    return CorporateActionOut.from_orm(c, db)


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
