from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from numis_geek.api.deps import get_current_user, get_db
from numis_geek.models.target_allocation import TargetAllocationDimension
from numis_geek.models.user import UserRole
from numis_geek.models.workspace import Workspace
from numis_geek.services.auth import UserContext
from numis_geek.services.target_allocation import (
    DimensionOut,
    TargetAllocationError,
    TargetEntryIn,
    get_targets,
    upsert_targets,
)

router = APIRouter(prefix="/workspaces", tags=["target-allocation"])


class TargetEntrySchema(BaseModel):
    key: str
    target_pct: Decimal = Field(ge=0, le=1)


class DimensionSchema(BaseModel):
    dimension: TargetAllocationDimension
    entries: list[TargetEntrySchema]
    total: Decimal
    is_valid: bool

    @classmethod
    def from_dataclass(cls, d: DimensionOut) -> "DimensionSchema":
        return cls(
            dimension=d.dimension,
            entries=[TargetEntrySchema(key=e.key, target_pct=e.target_pct) for e in d.entries],
            total=d.total,
            is_valid=d.is_valid,
        )


class TargetAllocationOut(BaseModel):
    workspace_id: str
    CLASS: DimensionSchema
    COUNTRY: DimensionSchema


class UpsertRequest(BaseModel):
    dimension: TargetAllocationDimension
    entries: list[TargetEntrySchema]


def _resolve_workspace(
    db: Session, workspace_id: str, current_user: UserContext
) -> str:
    """Allows sysadmin to act on any workspace; others restricted to their own."""
    if current_user.role == UserRole.sysadmin:
        ws = db.get(Workspace, workspace_id)
        if not ws:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found."
            )
        return ws.id
    if current_user.workspace_id != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Workspace access denied.",
        )
    return workspace_id


def _require_admin(current_user: UserContext) -> None:
    if current_user.role not in (UserRole.admin, UserRole.sysadmin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin only."
        )


def _build_response(db: Session, workspace_id: str) -> TargetAllocationOut:
    targets = get_targets(db, workspace_id)
    return TargetAllocationOut(
        workspace_id=workspace_id,
        CLASS=DimensionSchema.from_dataclass(targets["CLASS"]),
        COUNTRY=DimensionSchema.from_dataclass(targets["COUNTRY"]),
    )


@router.get(
    "/{workspace_id}/target-allocation", response_model=TargetAllocationOut
)
def get_target_allocation(
    workspace_id: str,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    ws_id = _resolve_workspace(db, workspace_id, current_user)
    return _build_response(db, ws_id)


@router.put(
    "/{workspace_id}/target-allocation", response_model=TargetAllocationOut
)
def put_target_allocation(
    workspace_id: str,
    body: UpsertRequest,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    _require_admin(current_user)
    ws_id = _resolve_workspace(db, workspace_id, current_user)
    entries_in = [
        TargetEntryIn(key=e.key, target_pct=e.target_pct) for e in body.entries
    ]
    try:
        upsert_targets(
            db,
            ws_id,
            body.dimension,
            entries_in,
            user_email=current_user.user_id,
            user_id=current_user.user_id,
        )
    except TargetAllocationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=exc.errors
        )
    return _build_response(db, ws_id)
