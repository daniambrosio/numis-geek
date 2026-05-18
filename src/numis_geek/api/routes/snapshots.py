"""Portfolio snapshot routes."""
from datetime import date as date_t

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from numis_geek.api.deps import get_current_user, get_db
from numis_geek.models.portfolio_snapshot import (
    PortfolioSnapshot,
    PortfolioSnapshotItem,
    SnapshotSource,
)
from numis_geek.models.user import UserRole
from numis_geek.services.auth import UserContext
from numis_geek.services.snapshot import create_snapshot, list_snapshots

router = APIRouter(prefix="/snapshots", tags=["snapshots"])


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

    @classmethod
    def from_orm(cls, s: PortfolioSnapshot, items_count: int) -> "SnapshotOut":
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
        )


class SnapshotCreateRequest(BaseModel):
    period_end_date: date_t


def _workspace_id(current_user: UserContext) -> str:
    if current_user.role == UserRole.sysadmin:
        raise HTTPException(status_code=400, detail="Sysadmin must call CLI with explicit workspace")
    return current_user.workspace_id


@router.get("", response_model=list[SnapshotOut])
def list_workspace_snapshots(
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    ws_id = _workspace_id(current_user)
    rows = list_snapshots(db, ws_id)
    out: list[SnapshotOut] = []
    for s in rows:
        count = db.query(PortfolioSnapshotItem).filter(
            PortfolioSnapshotItem.snapshot_id == s.id
        ).count()
        out.append(SnapshotOut.from_orm(s, count))
    return out


@router.post("", response_model=SnapshotOut, status_code=status.HTTP_201_CREATED)
def create_workspace_snapshot(
    body: SnapshotCreateRequest,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    ws_id = _workspace_id(current_user)
    result = create_snapshot(
        db,
        workspace_id=ws_id,
        period_end=body.period_end_date,
        user_id=current_user.user_id,
        source=SnapshotSource.MANUAL,
    )
    snap = db.get(PortfolioSnapshot, result.snapshot_id)
    return SnapshotOut.from_orm(snap, result.items_count)


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
