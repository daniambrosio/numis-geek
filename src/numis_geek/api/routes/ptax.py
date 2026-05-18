"""Sysadmin routes for PTAX (USD/BRL daily rates from BCB)."""
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from numis_geek.api.deps import get_current_user, get_db
from numis_geek.integrations.bcb import BCBError
from numis_geek.models.ptax_rate import PTAXRate
from numis_geek.models.user import UserRole
from numis_geek.services.auth import UserContext
from numis_geek.services.ptax_sync import PtaxSyncResult, sync_ptax

router = APIRouter(prefix="/sysadmin/ptax", tags=["ptax"])


class PTAXRateOut(BaseModel):
    id: str
    date: str
    rate: str
    source: str
    fetched_at: str

    @classmethod
    def from_orm(cls, p: PTAXRate) -> "PTAXRateOut":
        return cls(
            id=p.id,
            date=p.date.isoformat(),
            rate=str(p.rate),
            source=p.source,
            fetched_at=p.fetched_at.isoformat(),
        )


class PTAXListOut(BaseModel):
    items: list[PTAXRateOut]
    total: int
    page: int
    page_size: int


class PTAXStatusOut(BaseModel):
    total_rows: int
    last_date: str | None
    oldest_date: str | None
    last_fetched_at: str | None


class PTAXSyncRequest(BaseModel):
    mode: Literal["incremental", "full"] = "incremental"


class PTAXSyncResultOut(BaseModel):
    mode: str
    fetched_count: int
    inserted_count: int
    updated_count: int
    range_start: str
    range_end: str
    duration_ms: int

    @classmethod
    def from_dto(cls, r: PtaxSyncResult) -> "PTAXSyncResultOut":
        return cls(
            mode=r.mode,
            fetched_count=r.fetched_count,
            inserted_count=r.inserted_count,
            updated_count=r.updated_count,
            range_start=r.range_start.isoformat(),
            range_end=r.range_end.isoformat(),
            duration_ms=r.duration_ms,
        )


def _require_sysadmin(current_user: UserContext) -> None:
    if current_user.role != UserRole.sysadmin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="SysAdmin only.")


@router.get("/status", response_model=PTAXStatusOut)
def ptax_status(
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    _require_sysadmin(current_user)
    total: int = db.query(func.count(PTAXRate.id)).scalar() or 0
    last_date = db.query(func.max(PTAXRate.date)).scalar()
    oldest_date = db.query(func.min(PTAXRate.date)).scalar()
    last_fetched = db.query(func.max(PTAXRate.fetched_at)).scalar()
    return PTAXStatusOut(
        total_rows=total,
        last_date=last_date.isoformat() if last_date else None,
        oldest_date=oldest_date.isoformat() if oldest_date else None,
        last_fetched_at=last_fetched.isoformat() if last_fetched else None,
    )


@router.get("", response_model=PTAXListOut)
def list_ptax(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    _require_sysadmin(current_user)
    total = db.query(func.count(PTAXRate.id)).scalar() or 0
    rows = (
        db.query(PTAXRate)
        .order_by(PTAXRate.date.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return PTAXListOut(
        items=[PTAXRateOut.from_orm(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/sync", response_model=PTAXSyncResultOut)
def trigger_sync(
    body: PTAXSyncRequest,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    _require_sysadmin(current_user)
    try:
        result = sync_ptax(db, mode=body.mode)
    except BCBError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"BCB SGS unreachable or malformed: {e}",
        )
    return PTAXSyncResultOut.from_dto(result)
