"""Notion sync routes — push entities to Notion.

All endpoints require workspace_id check (or sysadmin). Per-entity push
returns the new status; bulk push iterates and reports counts. Conflict
detection runs by default; /resolve forces overwrite.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from numis_geek.api.deps import get_current_user, get_db
from numis_geek.models.asset import Asset
from numis_geek.models.asset_movement import AssetMovement
from numis_geek.models.corporate_action import CorporateAction
from numis_geek.models.notion_sync import NotionSyncStatus
from numis_geek.models.portfolio_snapshot import PortfolioSnapshot
from numis_geek.models.user import UserRole
from numis_geek.services.auth import UserContext
from numis_geek.services.notion_sync import (
    NotionCredentialMissing,
    SyncResult,
    list_pending,
    push_asset,
    push_asset_movement,
    push_corporate_action,
    push_snapshot,
)

router = APIRouter(prefix="/notion-sync", tags=["notion-sync"])


# ── Schemas ──────────────────────────────────────────────────────────────────


class SyncOut(BaseModel):
    status: str
    entity_id: str
    notion_page_id: str | None
    notion_url: str | None
    error: str | None
    conflict_remote_edited_at: str | None = None


class BulkSyncOut(BaseModel):
    entity: str
    total: int
    synced: int
    conflicts: int
    errors: int
    results: list[SyncOut]


class PendingCountsOut(BaseModel):
    assets: int
    asset_movements: int
    snapshots: int
    corporate_actions: int


# ── Helpers ──────────────────────────────────────────────────────────────────


def _check_workspace(entity, current_user: UserContext) -> None:
    if current_user.role == UserRole.sysadmin:
        return
    if getattr(entity, "workspace_id", None) != current_user.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found.")


def _result_to_out(entity_id: str, r: SyncResult) -> SyncOut:
    return SyncOut(
        status=r.status.value,
        entity_id=entity_id,
        notion_page_id=r.notion_page_id,
        notion_url=r.notion_url,
        error=r.error,
        conflict_remote_edited_at=r.conflict_remote_edited_at,
    )


def _wrap(fn, db: Session, entity, force: bool) -> SyncResult:
    try:
        return fn(db, entity, force=force)
    except NotionCredentialMissing as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))


# ── Pending counts ───────────────────────────────────────────────────────────


@router.get("/pending", response_model=PendingCountsOut)
def get_pending(
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    ws_id = None if current_user.role == UserRole.sysadmin else current_user.workspace_id
    counts = list_pending(db, ws_id)
    return PendingCountsOut(**counts)


# ── Bulk push (declared BEFORE `{aid}` to avoid `bulk` being parsed as an id) ─


@router.post("/asset/bulk", response_model=BulkSyncOut)
def bulk_assets(
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    return _bulk(db, Asset, push_asset, "asset", current_user)


@router.post("/asset-movement/bulk", response_model=BulkSyncOut)
def bulk_movements(
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    return _bulk(db, AssetMovement, push_asset_movement, "asset-movement", current_user)


@router.post("/snapshot/bulk", response_model=BulkSyncOut)
def bulk_snapshots(
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    return _bulk(db, PortfolioSnapshot, push_snapshot, "snapshot", current_user)


@router.post("/corporate-action/bulk", response_model=BulkSyncOut)
def bulk_corporate_actions(
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    return _bulk(db, CorporateAction, push_corporate_action, "corporate-action", current_user)


def _bulk(db: Session, model, push_fn, entity_name: str, current_user: UserContext) -> BulkSyncOut:
    q = db.query(model).filter(
        model.notion_sync_status.in_(
            [NotionSyncStatus.PENDING, NotionSyncStatus.ERROR]
        )
    )
    if current_user.role != UserRole.sysadmin and hasattr(model, "workspace_id"):
        q = q.filter(model.workspace_id == current_user.workspace_id)
    rows = q.all()

    results: list[SyncOut] = []
    synced = conflicts = errors = 0
    for r in rows:
        try:
            res = push_fn(db, r, force=False)
        except NotionCredentialMissing as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))
        out = _result_to_out(r.id, res)
        results.append(out)
        if res.status == NotionSyncStatus.SYNCED:
            synced += 1
        elif res.status == NotionSyncStatus.CONFLICT:
            conflicts += 1
        else:
            errors += 1

    return BulkSyncOut(
        entity=entity_name,
        total=len(rows),
        synced=synced,
        conflicts=conflicts,
        errors=errors,
        results=results,
    )


# ── Per-entity push ──────────────────────────────────────────────────────────


@router.post("/asset/{aid}", response_model=SyncOut)
def push_asset_one(
    aid: str,
    force: bool = False,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    a = db.get(Asset, aid)
    if not a:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Asset not found.")
    _check_workspace(a, current_user)
    r = _wrap(push_asset, db, a, force)
    return _result_to_out(aid, r)


@router.post("/asset-movement/{mid}", response_model=SyncOut)
def push_movement_one(
    mid: str,
    force: bool = False,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    m = db.get(AssetMovement, mid)
    if not m:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="AssetMovement not found.")
    _check_workspace(m, current_user)
    r = _wrap(push_asset_movement, db, m, force)
    return _result_to_out(mid, r)


@router.post("/snapshot/{sid}", response_model=SyncOut)
def push_snapshot_one(
    sid: str,
    force: bool = False,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    s = db.get(PortfolioSnapshot, sid)
    if not s:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Snapshot not found.")
    _check_workspace(s, current_user)
    r = _wrap(push_snapshot, db, s, force)
    return _result_to_out(sid, r)


@router.post("/corporate-action/{cid}", response_model=SyncOut)
def push_corporate_action_one(
    cid: str,
    force: bool = False,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    ca = db.get(CorporateAction, cid)
    if not ca:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="CorporateAction not found.")
    _check_workspace(ca, current_user)
    r = _wrap(push_corporate_action, db, ca, force)
    return _result_to_out(cid, r)


# ── Resolve (force_push) ─────────────────────────────────────────────────────


@router.post("/{entity}/{eid}/resolve", response_model=SyncOut)
def resolve_conflict(
    entity: Literal["asset", "asset-movement", "snapshot", "corporate-action"],
    eid: str,
    action: Literal["force_push", "abort"] = "force_push",
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    if action == "abort":
        # Just clear CONFLICT, leave external_id as-is, mark PENDING
        e = _lookup_by_entity(db, entity, eid)
        _check_workspace(e, current_user)
        e.notion_sync_status = NotionSyncStatus.PENDING
        e.notion_sync_error = None
        return SyncOut(
            status=NotionSyncStatus.PENDING.value,
            entity_id=eid,
            notion_page_id=e.external_id,
            notion_url=None,
            error=None,
        )

    # force_push: same handler as POST /{entity}/{id} with force=True
    if entity == "asset":
        return push_asset_one(eid, True, db, current_user)
    if entity == "asset-movement":
        return push_movement_one(eid, True, db, current_user)
    if entity == "snapshot":
        return push_snapshot_one(eid, True, db, current_user)
    return push_corporate_action_one(eid, True, db, current_user)


def _lookup_by_entity(db: Session, entity: str, eid: str):
    model = {
        "asset": Asset,
        "asset-movement": AssetMovement,
        "snapshot": PortfolioSnapshot,
        "corporate-action": CorporateAction,
    }.get(entity)
    if not model:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Unknown entity.")
    obj = db.get(model, eid)
    if not obj:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found.")
    return obj


