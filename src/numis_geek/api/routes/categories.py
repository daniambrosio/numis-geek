"""Spec 68 — Category CRUD."""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from numis_geek.api.deps import get_current_user, get_db
from numis_geek.models.category import Category, CategoryKind
from numis_geek.models.user import User, UserRole
from numis_geek.services.audit import AuditService
from numis_geek.services.auth import UserContext

router = APIRouter(prefix="/categories", tags=["categories"])


# ── schemas ───────────────────────────────────────────────────────────────────

class CategoryOut(BaseModel):
    id: str
    workspace_id: str
    name: str
    parent_id: str | None
    kind: str
    color: str | None
    is_active: bool
    created_at: str

    @classmethod
    def from_orm(cls, c: Category) -> "CategoryOut":
        return cls(
            id=c.id,
            workspace_id=c.workspace_id,
            name=c.name,
            parent_id=c.parent_id,
            kind=c.kind.value,
            color=c.color,
            is_active=c.is_active,
            created_at=c.created_at.isoformat(),
        )


class CategoryCreateRequest(BaseModel):
    name: str
    parent_id: str | None = None
    # Roots: required. Subs: optional — inherits the parent's kind when
    # omitted, but MAY override it (decisão 2026-08-09: raízes mistas como
    # "Bens Móveis" têm subs EXPENSE e INCOME juntas).
    kind: CategoryKind | None = None
    color: str | None = None


class CategoryUpdateRequest(BaseModel):
    name: str | None = None
    color: str | None = None
    kind: CategoryKind | None = None  # editável em qualquer nível


# ── helpers ───────────────────────────────────────────────────────────────────

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


def _get_scoped_or_404(db: Session, category_id: str, current_user: UserContext) -> Category:
    c = db.get(Category, category_id)
    if not c:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found.")
    if current_user.role != UserRole.sysadmin and c.workspace_id != current_user.workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found.")
    return c


def _audit(db: Session, current_user: UserContext, action: str, category: Category) -> None:
    actor = db.get(User, current_user.user_id)
    AuditService(db).log(
        user_email=actor.email if actor else current_user.user_id,
        action=action,
        resource_type="category",
        resource_id=category.id,
        details={"name": category.name},
        workspace_id=category.workspace_id,
    )


# ── routes ────────────────────────────────────────────────────────────────────

@router.get("", response_model=list[CategoryOut])
def list_categories(
    workspace_id: str | None = Query(default=None),
    include_inactive: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    ws = _resolve_ws(current_user, workspace_id)
    q = db.query(Category).filter(Category.workspace_id == ws)
    if not include_inactive:
        q = q.filter(Category.is_active == True)  # noqa: E712
    return [CategoryOut.from_orm(c) for c in q.order_by(Category.name).all()]


@router.post("", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
def create_category(
    body: CategoryCreateRequest,
    workspace_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    _require_admin(current_user)
    ws = _resolve_ws(current_user, workspace_id)

    parent: Category | None = None
    if body.parent_id:
        parent = _get_scoped_or_404(db, body.parent_id, current_user)
        if parent.workspace_id != ws:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found.")
        if parent.parent_id is not None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Only one nesting level: parent is already a subcategory.",
            )
        kind = body.kind or parent.kind  # inherit by default, override allowed
        color = body.color or parent.color
    else:
        if body.kind is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="kind is required for root categories.",
            )
        kind = body.kind
        color = body.color

    dup = db.query(Category).filter(
        Category.workspace_id == ws,
        Category.parent_id == body.parent_id,
        Category.name == body.name,
    ).first()
    if dup:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Category name already exists under this parent.")

    now = datetime.now(timezone.utc)
    c = Category(
        id=str(uuid.uuid4()),
        workspace_id=ws,
        name=body.name,
        parent_id=body.parent_id,
        kind=kind,
        color=color,
        is_active=True,
        created_at=now,
        updated_at=now,
        created_by=current_user.user_id,
        updated_by=current_user.user_id,
    )
    db.add(c)
    db.flush()
    _audit(db, current_user, "category.created", c)
    return CategoryOut.from_orm(c)


@router.put("/{category_id}", response_model=CategoryOut)
def update_category(
    category_id: str,
    body: CategoryUpdateRequest,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    _require_admin(current_user)
    c = _get_scoped_or_404(db, category_id, current_user)
    if body.name is not None and body.name != c.name:
        dup = db.query(Category).filter(
            Category.workspace_id == c.workspace_id,
            Category.parent_id == c.parent_id,
            Category.name == body.name,
            Category.id != c.id,
        ).first()
        if dup:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Category name already exists under this parent.")
        c.name = body.name
    if body.color is not None:
        c.color = body.color
    if body.kind is not None:
        # Kind é editável em qualquer nível. Mudar a raiz NÃO cascateia
        # pras filhas: cada sub mantém o próprio kind (herdado na criação
        # ou sobrescrito depois) — semântica previsível com overrides.
        c.kind = body.kind
    c.updated_at = datetime.now(timezone.utc)
    c.updated_by = current_user.user_id
    db.flush()
    _audit(db, current_user, "category.updated", c)
    return CategoryOut.from_orm(c)


@router.put("/{category_id}/deactivate", response_model=CategoryOut)
def deactivate_category(
    category_id: str,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    _require_admin(current_user)
    c = _get_scoped_or_404(db, category_id, current_user)
    c.is_active = False
    # children follow the parent out of the pickers
    db.query(Category).filter(Category.parent_id == c.id).update({"is_active": False})
    c.updated_at = datetime.now(timezone.utc)
    c.updated_by = current_user.user_id
    db.flush()
    _audit(db, current_user, "category.deactivated", c)
    return CategoryOut.from_orm(c)
