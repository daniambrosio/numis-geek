import math

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from numis_geek.api.deps import get_current_user, get_db
from numis_geek.models.audit_log import AuditLog
from numis_geek.models.user import UserRole
from numis_geek.services.auth import UserContext

router = APIRouter(prefix="/audit", tags=["audit"])


class AuditLogOut:
    pass


from pydantic import BaseModel


class AuditLogOut(BaseModel):
    id: str
    workspace_id: str | None
    user_id: str | None
    user_email: str
    action: str
    resource_type: str | None
    resource_id: str | None
    details: str | None
    created_at: str

    @classmethod
    def from_orm(cls, a: AuditLog) -> "AuditLogOut":
        return cls(
            id=a.id,
            workspace_id=a.workspace_id,
            user_id=a.user_id,
            user_email=a.user_email,
            action=a.action,
            resource_type=a.resource_type,
            resource_id=a.resource_id,
            details=a.details,
            created_at=a.created_at.isoformat(),
        )


class AuditPage(BaseModel):
    items: list[AuditLogOut]
    total: int
    page: int
    pages: int


@router.get("", response_model=AuditPage)
def list_audit(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    action: str | None = Query(None),
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    if current_user.role not in (UserRole.admin, UserRole.sysadmin):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only.")

    q = db.query(AuditLog)
    if current_user.role == UserRole.admin:
        q = q.filter(AuditLog.workspace_id == current_user.workspace_id)
    if action:
        q = q.filter(AuditLog.action == action)
    q = q.order_by(AuditLog.created_at.desc())

    total = q.count()
    items = q.offset((page - 1) * limit).limit(limit).all()

    return AuditPage(
        items=[AuditLogOut.from_orm(a) for a in items],
        total=total,
        page=page,
        pages=max(1, math.ceil(total / limit)),
    )
