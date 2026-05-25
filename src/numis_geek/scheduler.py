"""Spec 24 — background scheduler (APScheduler).

A single in-process BackgroundScheduler that fires `run_daily_price_refresh`
at 18:00 America/Sao_Paulo every day. Wired into FastAPI via a lifespan
context manager in `api/app.py`.

Multi-worker note: when this app moves to gunicorn with N workers, this
scheduler will fire N times. Resolve before VPS deploy. Options:
  (a) gunicorn --preload + worker_id == 0 guard
  (b) systemd timer / OS cron calling the endpoint instead
  (c) APScheduler with a DB jobstore + SELECT FOR UPDATE lock
"""
from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from numis_geek.db.session import SessionLocal
from numis_geek.jobs.snapshot_auto import (
    JOB_ID as SNAPSHOT_JOB_ID,
    run_monthly_snapshot,
)
from numis_geek.models.workspace import Workspace
from numis_geek.services.price_update import refresh_all_automated

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)


CRON_JOB_ID = "price_refresh_daily"
CRON_AUDIT_ACTION = "price.refresh.cron"
CRON_USER_EMAIL = "system@cron"


def run_daily_price_refresh() -> None:
    """Iterate active workspaces and refresh all automated-source assets.

    Each asset's audit event is logged as `price.refresh.cron` (not
    the user-triggered `price.refresh`).
    """
    db = SessionLocal()
    try:
        workspace_ids = [w.id for w in db.query(Workspace).all()]
        for ws_id in workspace_ids:
            try:
                summary = refresh_all_automated(
                    db, workspace_id=ws_id,
                    user_email=CRON_USER_EMAIL,
                    audit_action=CRON_AUDIT_ACTION,
                )
                db.commit()
                logger.info(
                    "cron price refresh ws=%s ok=%d failed=%d skipped=%d",
                    ws_id, summary.ok, summary.failed, summary.skipped,
                )
            except Exception:
                db.rollback()
                logger.exception("cron price refresh failed for ws=%s", ws_id)
    finally:
        db.close()


def _enabled() -> bool:
    """Disable via DISABLE_SCHEDULER=true (pytest, dev opt-out)."""
    return os.environ.get("DISABLE_SCHEDULER", "").lower() not in (
        "1", "true", "yes", "on",
    )


def start_scheduler(app: "FastAPI") -> BackgroundScheduler | None:
    if not _enabled():
        logger.info("scheduler disabled via DISABLE_SCHEDULER")
        return None

    sched = BackgroundScheduler(timezone="America/Sao_Paulo")
    sched.add_job(
        run_daily_price_refresh,
        CronTrigger(hour=18, minute=0),
        id=CRON_JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    # Spec 35 — auto monthly snapshot at 06:30 on the 1st of each month.
    sched.add_job(
        run_monthly_snapshot,
        CronTrigger(day=1, hour=6, minute=30),
        id=SNAPSHOT_JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    sched.start()
    next_price = sched.get_job(CRON_JOB_ID).next_run_time
    next_snap = sched.get_job(SNAPSHOT_JOB_ID).next_run_time
    logger.info(
        "scheduler started: %s next=%s; %s next=%s",
        CRON_JOB_ID, next_price, SNAPSHOT_JOB_ID, next_snap,
    )
    app.state.scheduler = sched
    return sched


def stop_scheduler(app: "FastAPI") -> None:
    sched = getattr(app.state, "scheduler", None)
    if sched is not None:
        sched.shutdown(wait=False)
        logger.info("scheduler shut down")
