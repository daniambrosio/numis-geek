"""Spec 23 — generic price refresh endpoint.

  POST /api/prices/refresh
    body: { "source": PriceSource | null, "asset_ids": str[] | null }
    rules:
      - both null / null body → refresh everything with automated source
      - source only           → only that source
      - asset_ids only        → only those (MANUAL ones are skipped, not failed)
      - source + asset_ids    → AND
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from numis_geek.api.deps import get_current_user, get_db
from numis_geek.models.asset import PriceSource
from numis_geek.models.user import User, UserRole
from numis_geek.models.workspace import Workspace
from numis_geek.services.auth import UserContext
from numis_geek.services.price_update import (
    RefreshSummary,
    refresh_all_automated,
    refresh_by_ids,
    refresh_by_source,
)


router = APIRouter(prefix="/prices", tags=["prices"])


class RefreshRequest(BaseModel):
    source: PriceSource | None = None
    asset_ids: list[str] | None = None


class RefreshError(BaseModel):
    asset_id: str
    ticker: str | None
    reason: str | None


class RefreshSummaryOut(BaseModel):
    ok: int
    failed: int
    skipped: int
    errors: list[RefreshError]
    ran_at: str


def _resolve_workspace(
    current_user: UserContext, workspace_id: str | None, db: Session
) -> str | None:
    """Sysadmin gets cross-workspace by default (None) but can target one."""
    if current_user.role == UserRole.sysadmin:
        if workspace_id and not db.get(Workspace, workspace_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found."
            )
        return workspace_id
    if not current_user.workspace_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No workspace bound to user."
        )
    if workspace_id and workspace_id != current_user.workspace_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Cross-workspace not allowed."
        )
    return current_user.workspace_id


def _to_out(summary: RefreshSummary) -> RefreshSummaryOut:
    return RefreshSummaryOut(
        ok=summary.ok,
        failed=summary.failed,
        skipped=summary.skipped,
        errors=[RefreshError(**e) for e in summary.errors],
        ran_at=summary.ran_at.isoformat(),
    )


@router.post("/refresh", response_model=RefreshSummaryOut)
def refresh_prices(
    body: RefreshRequest | None = None,
    workspace_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    ws = _resolve_workspace(current_user, workspace_id, db)
    actor = db.get(User, current_user.user_id)
    email = actor.email if actor else current_user.user_id

    body = body or RefreshRequest()

    if body.asset_ids is not None:
        # asset_ids takes precedence; combine with optional source filter via
        # the underlying query (refresh_by_ids matches against price_source via
        # the AUTOMATED gate in refresh_one — MANUAL ones come back as skipped).
        summary = refresh_by_ids(
            db, body.asset_ids, workspace_id=ws, user_email=email,
        )
        # If source was also specified, drop results that don't match.
        if body.source is not None:
            filtered = [r for r in summary.results if r.source == body.source.value]
            from numis_geek.services.price_update import _summarize  # local helper
            summary = _summarize(filtered)
    elif body.source is not None:
        summary = refresh_by_source(
            db, body.source, workspace_id=ws, user_email=email,
        )
    else:
        summary = refresh_all_automated(
            db, workspace_id=ws, user_email=email,
        )

    return _to_out(summary)
