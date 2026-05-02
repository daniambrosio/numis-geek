import bcrypt
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from numis_geek.api.deps import get_current_user, get_db
from numis_geek.models.user import User, UserRole
from numis_geek.models.workspace import Workspace
from numis_geek.services.audit import AuditService
from numis_geek.services.auth import UserContext
from numis_geek.services.user import UserService

router = APIRouter(prefix="/users", tags=["users"])


# ── schemas ──────────────────────────────────────────────────────────────────

class UserOut(BaseModel):
    id: str
    email: str
    name: str | None
    role: str
    is_active: bool
    created_at: str
    workspace_id: str | None = None
    workspace_name: str | None = None

    @classmethod
    def from_orm(cls, u: User, workspace_name: str | None = None) -> "UserOut":
        return cls(
            id=u.id,
            email=u.email,
            name=u.name,
            role=u.role.value,
            is_active=u.is_active,
            created_at=u.created_at.isoformat(),
            workspace_id=u.workspace_id,
            workspace_name=workspace_name,
        )


class InviteRequest(BaseModel):
    email: EmailStr
    name: str | None = None
    password: str
    role: UserRole = UserRole.member


class ChangeRoleRequest(BaseModel):
    role: UserRole


class UpdateMeRequest(BaseModel):
    name: str


class UpdateNameRequest(BaseModel):
    name: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


# ── helpers ───────────────────────────────────────────────────────────────────

def _require_admin(current_user: UserContext) -> None:
    if current_user.role not in (UserRole.admin, UserRole.sysadmin):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only.")


def _get_user_or_404(db: Session, user_id: str) -> User:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
    return user


# ── admin routes ──────────────────────────────────────────────────────────────

@router.get("", response_model=list[UserOut])
def list_users(
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    _require_admin(current_user)
    q = db.query(User)
    if current_user.role != UserRole.sysadmin:
        q = q.filter(User.workspace_id == current_user.workspace_id)
    users = q.all()
    workspace_ids = {u.workspace_id for u in users if u.workspace_id}
    ws_names = {
        ws.id: ws.name
        for ws in db.query(Workspace).filter(Workspace.id.in_(workspace_ids)).all()
    }
    return [UserOut.from_orm(u, workspace_name=ws_names.get(u.workspace_id)) for u in users]


@router.post("/invite", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def invite_user(
    body: InviteRequest,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    _require_admin(current_user)
    acting = _get_user_or_404(db, current_user.user_id)
    svc = UserService(db)
    new_user = svc.invite(current_user.workspace_id, body.email, body.password, acting_user=acting)
    if body.name:
        new_user.name = body.name
    if body.role == UserRole.admin:
        new_user.role = UserRole.admin
    db.flush()
    AuditService(db).log(
        user_email=acting.email,
        action="user.invited",
        workspace_id=current_user.workspace_id,
        user_id=current_user.user_id,
        resource_type="user",
        resource_id=new_user.id,
        details={"invited_email": body.email, "role": body.role.value},
    )
    return UserOut.from_orm(new_user)


@router.put("/{user_id}/role", response_model=UserOut)
def change_role(
    user_id: str,
    body: ChangeRoleRequest,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    _require_admin(current_user)
    acting = _get_user_or_404(db, current_user.user_id)
    user = _get_user_or_404(db, user_id)
    old_role = user.role.value
    user.role = body.role
    db.flush()
    AuditService(db).log(
        user_email=acting.email,
        action="user.role_changed",
        workspace_id=current_user.workspace_id,
        user_id=current_user.user_id,
        resource_type="user",
        resource_id=user_id,
        details={"from": old_role, "to": body.role.value},
    )
    return UserOut.from_orm(user)


@router.put("/{user_id}/deactivate", response_model=UserOut)
def deactivate_user(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    _require_admin(current_user)
    acting = _get_user_or_404(db, current_user.user_id)
    target = _get_user_or_404(db, user_id)
    UserService(db).deactivate(user_id, acting_user=acting)
    AuditService(db).log(
        user_email=acting.email,
        action="user.deactivated",
        workspace_id=current_user.workspace_id,
        user_id=current_user.user_id,
        resource_type="user",
        resource_id=user_id,
        details={"target_email": target.email},
    )
    return UserOut.from_orm(_get_user_or_404(db, user_id))


@router.put("/{user_id}/name", response_model=UserOut)
def update_user_name(
    user_id: str,
    body: UpdateNameRequest,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    _require_admin(current_user)
    acting = _get_user_or_404(db, current_user.user_id)
    target = _get_user_or_404(db, user_id)
    target.name = body.name
    db.flush()
    AuditService(db).log(
        user_email=acting.email,
        action="user.name_changed",
        workspace_id=current_user.workspace_id,
        user_id=current_user.user_id,
        resource_type="user",
        resource_id=user_id,
        details={"name": body.name},
    )
    return UserOut.from_orm(target)


# ── current user routes ───────────────────────────────────────────────────────

@router.get("/me", response_model=UserOut)
def get_me(
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    return UserOut.from_orm(_get_user_or_404(db, current_user.user_id))


@router.put("/me", response_model=UserOut)
def update_me(
    body: UpdateMeRequest,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    user = _get_user_or_404(db, current_user.user_id)
    user.name = body.name
    db.flush()
    AuditService(db).log(
        user_email=user.email,
        action="profile.name_changed",
        workspace_id=current_user.workspace_id,
        user_id=current_user.user_id,
        resource_type="user",
        resource_id=user.id,
    )
    return UserOut.from_orm(user)


@router.put("/me/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    body: ChangePasswordRequest,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    user = _get_user_or_404(db, current_user.user_id)
    if not bcrypt.checkpw(body.current_password.encode(), user.password_hash.encode()):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect.")
    user.password_hash = bcrypt.hashpw(body.new_password.encode(), bcrypt.gensalt()).decode()
    db.flush()
    AuditService(db).log(
        user_email=user.email,
        action="profile.password_changed",
        workspace_id=current_user.workspace_id,
        user_id=current_user.user_id,
        resource_type="user",
        resource_id=user.id,
    )
