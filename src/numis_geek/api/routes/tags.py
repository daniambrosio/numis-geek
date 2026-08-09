"""Spec 68 — Tag CRUD (delete only while unused; usage check grows with spec 70)."""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from numis_geek.api.deps import get_current_user, get_db
from numis_geek.models.tag import Tag
from numis_geek.models.user import User, UserRole
from numis_geek.services.audit import AuditService
from numis_geek.services.auth import UserContext

router = APIRouter(prefix="/tags", tags=["tags"])


class TagOut(BaseModel):
    id: str
    workspace_id: str
    name: str
    created_at: str

    @classmethod
    def from_orm(cls, t: Tag) -> "TagOut":
        return cls(id=t.id, workspace_id=t.workspace_id, name=t.name, created_at=t.created_at.isoformat())


class TagRequest(BaseModel):
    name: str


def _require_admin(current_user: UserContext) -> None:
    if current_user.role not in (UserRole.admin, UserRole.sysadmin):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only.")


def _resolve_ws(current_user: UserContext, workspace_id: str | None) -> str:
    if current_user.role == UserRole.sysadmin:
        target = workspace_id or current_user.workspace_id
        if not target:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="workspace_id required for sysadmin.")
        return target
    return current_user.workspace_id


def _norm(name: str) -> str:
    return name.strip().lower()


def _get_scoped_or_404(db: Session, tag_id: str, current_user: UserContext) -> Tag:
    t = db.get(Tag, tag_id)
    if not t:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag not found.")
    if current_user.role != UserRole.sysadmin and t.workspace_id != current_user.workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag not found.")
    return t


def _audit(db: Session, current_user: UserContext, action: str, t: Tag) -> None:
    actor = db.get(User, current_user.user_id)
    AuditService(db).log(
        user_email=actor.email if actor else current_user.user_id,
        action=action,
        resource_type="tag",
        resource_id=t.id,
        details={"name": t.name},
        workspace_id=t.workspace_id,
    )


@router.get("", response_model=list[TagOut])
def list_tags(
    workspace_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    ws = _resolve_ws(current_user, workspace_id)
    tags = db.query(Tag).filter(Tag.workspace_id == ws).order_by(Tag.name).all()
    return [TagOut.from_orm(t) for t in tags]


@router.post("", response_model=TagOut, status_code=status.HTTP_201_CREATED)
def create_tag(
    body: TagRequest,
    workspace_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    _require_admin(current_user)
    ws = _resolve_ws(current_user, workspace_id)
    name = _norm(body.name)
    if not name:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Tag name cannot be empty.")
    dup = db.query(Tag).filter(Tag.workspace_id == ws, Tag.name == name).first()
    if dup:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Tag already exists.")
    t = Tag(
        id=str(uuid.uuid4()),
        workspace_id=ws,
        name=name,
        created_at=datetime.now(timezone.utc),
        created_by=current_user.user_id,
    )
    db.add(t)
    db.flush()
    _audit(db, current_user, "tag.created", t)
    return TagOut.from_orm(t)


@router.put("/{tag_id}", response_model=TagOut)
def rename_tag(
    tag_id: str,
    body: TagRequest,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    _require_admin(current_user)
    t = _get_scoped_or_404(db, tag_id, current_user)
    name = _norm(body.name)
    if not name:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Tag name cannot be empty.")
    dup = db.query(Tag).filter(Tag.workspace_id == t.workspace_id, Tag.name == name, Tag.id != t.id).first()
    if dup:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Tag already exists.")
    t.name = name
    db.flush()
    _audit(db, current_user, "tag.renamed", t)
    return TagOut.from_orm(t)


@router.delete("/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tag(
    tag_id: str,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    """Spec 70 adds the transaction_tag usage check here (409 when in use)."""
    _require_admin(current_user)
    t = _get_scoped_or_404(db, tag_id, current_user)
    _audit(db, current_user, "tag.deleted", t)
    db.delete(t)
    db.flush()
