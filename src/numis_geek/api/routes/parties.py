"""Spec 68 — Party CRUD + merge."""
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from numis_geek.api.deps import get_current_user, get_db
from numis_geek.models.party import Party, PartyAlias, PartyKind
from numis_geek.models.user import User, UserRole
from numis_geek.services.audit import AuditService
from numis_geek.services.auth import UserContext

router = APIRouter(prefix="/parties", tags=["parties"])


# ── schemas ───────────────────────────────────────────────────────────────────

class PartyOut(BaseModel):
    id: str
    workspace_id: str
    name: str
    kind: str
    notes: str | None
    is_active: bool
    alias_count: int
    created_at: str

    @classmethod
    def from_orm(cls, p: Party, alias_count: int = 0) -> "PartyOut":
        return cls(
            id=p.id,
            workspace_id=p.workspace_id,
            name=p.name,
            kind=p.kind.value,
            notes=p.notes,
            is_active=p.is_active,
            alias_count=alias_count,
            created_at=p.created_at.isoformat(),
        )


class PartyRequest(BaseModel):
    name: str
    kind: PartyKind = PartyKind.SUPPLIER
    notes: str | None = None


class PartyMergeRequest(BaseModel):
    source_party_id: str


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


def _get_scoped_or_404(db: Session, party_id: str, current_user: UserContext) -> Party:
    p = db.get(Party, party_id)
    if not p:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Party not found.")
    if current_user.role != UserRole.sysadmin and p.workspace_id != current_user.workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Party not found.")
    return p


def _audit(db: Session, current_user: UserContext, action: str, party: Party, details: dict | None = None) -> None:
    actor = db.get(User, current_user.user_id)
    AuditService(db).log(
        user_email=actor.email if actor else current_user.user_id,
        action=action,
        resource_type="party",
        resource_id=party.id,
        details=details or {"name": party.name},
        workspace_id=party.workspace_id,
    )


# ── routes ────────────────────────────────────────────────────────────────────

@router.get("", response_model=list[PartyOut])
def list_parties(
    workspace_id: str | None = Query(default=None),
    search: str | None = Query(default=None),
    include_inactive: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    ws = _resolve_ws(current_user, workspace_id)
    q = db.query(Party).filter(Party.workspace_id == ws)
    if not include_inactive:
        q = q.filter(Party.is_active == True)  # noqa: E712
    if search:
        q = q.filter(Party.name.ilike(f"%{search}%"))
    parties = q.order_by(Party.name).all()
    counts = dict(
        db.query(PartyAlias.party_id, func.count(PartyAlias.id))
        .filter(PartyAlias.workspace_id == ws)
        .group_by(PartyAlias.party_id)
        .all()
    )
    return [PartyOut.from_orm(p, counts.get(p.id, 0)) for p in parties]


@router.post("", response_model=PartyOut, status_code=status.HTTP_201_CREATED)
def create_party(
    body: PartyRequest,
    workspace_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    _require_admin(current_user)
    ws = _resolve_ws(current_user, workspace_id)
    now = datetime.now(timezone.utc)
    p = Party(
        id=str(uuid.uuid4()),
        workspace_id=ws,
        name=body.name,
        kind=body.kind,
        notes=body.notes,
        is_active=True,
        created_at=now,
        updated_at=now,
        created_by=current_user.user_id,
        updated_by=current_user.user_id,
    )
    db.add(p)
    db.flush()
    _audit(db, current_user, "party.created", p)
    return PartyOut.from_orm(p)


@router.put("/{party_id}", response_model=PartyOut)
def update_party(
    party_id: str,
    body: PartyRequest,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    _require_admin(current_user)
    p = _get_scoped_or_404(db, party_id, current_user)
    p.name = body.name
    p.kind = body.kind
    p.notes = body.notes
    p.updated_at = datetime.now(timezone.utc)
    p.updated_by = current_user.user_id
    db.flush()
    alias_count = db.query(PartyAlias).filter(PartyAlias.party_id == p.id).count()
    _audit(db, current_user, "party.updated", p)
    return PartyOut.from_orm(p, alias_count)


@router.put("/{party_id}/deactivate", response_model=PartyOut)
def deactivate_party(
    party_id: str,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    _require_admin(current_user)
    p = _get_scoped_or_404(db, party_id, current_user)
    p.is_active = False
    p.updated_at = datetime.now(timezone.utc)
    p.updated_by = current_user.user_id
    db.flush()
    _audit(db, current_user, "party.deactivated", p)
    return PartyOut.from_orm(p)


@router.post("/{party_id}/merge", response_model=PartyOut)
def merge_party(
    party_id: str,
    body: PartyMergeRequest,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    """Merge `source_party_id` INTO `party_id` (survivor).

    Re-points every referencing row to the survivor, moves aliases, then
    hard-deletes the source. Spec 68: the tables re-pointed grow as the
    trilha lands — transaction.party_id (spec 70), recurrence_rule /
    scheduled_transaction (spec 72) are re-pointed here once they exist.
    """
    _require_admin(current_user)
    survivor = _get_scoped_or_404(db, party_id, current_user)
    if body.source_party_id == party_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Cannot merge a party into itself.")
    source = _get_scoped_or_404(db, body.source_party_id, current_user)
    if source.workspace_id != survivor.workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Party not found.")

    # Move aliases to the survivor (workspace-unique constraint holds:
    # an alias points at exactly one party).
    db.query(PartyAlias).filter(PartyAlias.party_id == source.id).update({"party_id": survivor.id})

    # Future re-points land here as the referencing tables ship:
    #   transaction.party_id            (spec 70)
    #   recurrence_rule.party_id        (spec 72)
    #   scheduled_transaction.party_id  (spec 72)

    source_name = source.name
    db.delete(source)
    survivor.updated_at = datetime.now(timezone.utc)
    survivor.updated_by = current_user.user_id
    db.flush()
    alias_count = db.query(PartyAlias).filter(PartyAlias.party_id == survivor.id).count()
    _audit(
        db, current_user, "party.merged", survivor,
        details={"survivor": survivor.name, "merged": source_name, "merged_id": body.source_party_id},
    )
    return PartyOut.from_orm(survivor, alias_count)
