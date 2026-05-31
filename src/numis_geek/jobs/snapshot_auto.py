"""Spec 35 — monthly auto-snapshot job.

Runs on the 1st of each month at 06:30 America/Sao_Paulo. For each
active workspace:
  1. period_end = last_day_of_month(previous_month)  (calendar day,
     even if weekend/holiday — fx_rate_on walks back to PTAX)
  2. Skip if a CLOSED snapshot already exists (idempotent)
  3. Refresh all automated-source assets (spec 23 service)
  4. create_snapshot(source=AUTOMATED, initial_status=CLOSED) —
     downgrades to IN_REVIEW automatically when pendencies remain
  5. Audit log entry per workspace
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from numis_geek.db.session import SessionLocal
from numis_geek.models.portfolio_snapshot import (
    PortfolioSnapshot,
    SnapshotSource,
    SnapshotStatus,
)
from numis_geek.models.workspace import Workspace
from numis_geek.services.audit import AuditService
from numis_geek.services.price_update import refresh_all_automated
from numis_geek.services.snapshot import SnapshotResult, create_snapshot
from numis_geek.utils.business_day import (
    last_day_of_month,
    previous_month_ym,
)

logger = logging.getLogger(__name__)

JOB_ID = "monthly_snapshot"
USER_EMAIL = "system@cron"
AUDIT_ACTION = "snapshot.auto_create"


@dataclass
class WorkspaceJobResult:
    workspace_id: str
    period_end: date
    status: str   # "skipped" | "created"
    snapshot_id: str | None = None
    items_count: int = 0
    pendencies_count: int = 0
    error: str | None = None


def _has_closed_snapshot(db: Session, workspace_id: str, period_end: date) -> bool:
    snap = (
        db.query(PortfolioSnapshot)
        .filter(
            PortfolioSnapshot.workspace_id == workspace_id,
            PortfolioSnapshot.period_end_date == period_end,
            PortfolioSnapshot.status == SnapshotStatus.CLOSED,
        )
        .first()
    )
    return snap is not None


def _run_one_workspace(
    db: Session, workspace_id: str, *, target_ym: str,
) -> WorkspaceJobResult:
    period_end = last_day_of_month(target_ym)
    now = datetime.now(timezone.utc)

    if _has_closed_snapshot(db, workspace_id, period_end):
        logger.info("snapshot already CLOSED for ws=%s %s — skipping", workspace_id, period_end)
        return WorkspaceJobResult(
            workspace_id=workspace_id, period_end=period_end, status="skipped",
        )

    # 1. Refresh prices so create_snapshot sees fresh values.
    try:
        refresh_summary = refresh_all_automated(
            db, workspace_id=workspace_id,
            user_email=USER_EMAIL,
            audit_action="price.refresh.cron",
        )
        logger.info(
            "auto snapshot price refresh ws=%s ok=%d failed=%d skipped=%d",
            workspace_id, refresh_summary.ok, refresh_summary.failed,
            refresh_summary.skipped,
        )
    except Exception as e:
        logger.exception("auto snapshot price refresh failed ws=%s", workspace_id)
        return WorkspaceJobResult(
            workspace_id=workspace_id, period_end=period_end,
            status="error", error=str(e),
        )

    # 2. Create snapshot — auto-downgrades to IN_REVIEW on pendencies.
    result: SnapshotResult = create_snapshot(
        db, workspace_id=workspace_id, period_end=period_end,
        user_id=None,
        source=SnapshotSource.AUTOMATED,
        initial_status=SnapshotStatus.CLOSED,
        force_reopen=True,  # replaces a SCHEDULED/IN_REVIEW row if one exists
    )

    # Stamp auto_run_at
    snap = db.get(PortfolioSnapshot, result.snapshot_id)
    if snap is not None:
        snap.auto_run_at = now
        db.flush()

    AuditService(db).log(
        user_email=USER_EMAIL,
        action=AUDIT_ACTION,
        workspace_id=workspace_id,
        resource_type="snapshot",
        resource_id=result.snapshot_id,
        details={
            "period_end_date": period_end.isoformat(),
            "items_count": result.items_count,
            "pendencies_count": result.pendencies_count,
            "status": result.status.value,
        },
    )
    return WorkspaceJobResult(
        workspace_id=workspace_id, period_end=period_end, status="created",
        snapshot_id=result.snapshot_id,
        items_count=result.items_count,
        pendencies_count=result.pendencies_count,
    )


def run_monthly_snapshot(
    db: Session | None = None, *, target_ym: str | None = None,
) -> list[WorkspaceJobResult]:
    """Run the auto-snapshot for every workspace.

    `target_ym=None` means "previous calendar month relative to today".
    Pass a session explicitly to integrate with tests; otherwise we
    open one via SessionLocal.
    """
    owns_session = db is None
    if db is None:
        db = SessionLocal()

    try:
        if target_ym is None:
            target_ym = previous_month_ym(date.today())

        results: list[WorkspaceJobResult] = []
        for ws in db.query(Workspace).all():
            try:
                r = _run_one_workspace(db, ws.id, target_ym=target_ym)
                if owns_session:
                    db.commit()
                results.append(r)
            except Exception as e:
                if owns_session:
                    db.rollback()
                logger.exception("auto snapshot failed for ws=%s", ws.id)
                results.append(WorkspaceJobResult(
                    workspace_id=ws.id, period_end=date.today(),
                    status="error", error=str(e),
                ))
        return results
    finally:
        if owns_session:
            db.close()
