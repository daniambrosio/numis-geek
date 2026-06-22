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
from datetime import datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from sqlalchemy import func

from pathlib import Path

from numis_geek.config import DATABASE_URL
from numis_geek.db.session import SessionLocal
from numis_geek.jobs.snapshot_auto import (
    JOB_ID as SNAPSHOT_JOB_ID,
    run_monthly_snapshot,
)
from numis_geek.models.ptax_rate import PTAXRate
from numis_geek.models.workspace import Workspace
from numis_geek.services.backup import create_backup, rotate_backups
from numis_geek.services.option_lifecycle import auto_settle_expired_options
from numis_geek.services.price_update import refresh_all_automated
from numis_geek.services.ptax_sync import sync_ptax

if TYPE_CHECKING:
    from fastapi import FastAPI

logger = logging.getLogger(__name__)


CRON_JOB_ID = "price_refresh_daily"
CRON_AUDIT_ACTION = "price.refresh.cron"
CRON_USER_EMAIL = "system@cron"

PTAX_JOB_ID = "ptax_sync_daily"
PTAX_CATCHUP_JOB_ID = "ptax_sync_startup_catchup"

BACKUP_JOB_ID = "backup_daily"
BACKUP_DIR = Path("data/backups")

OPTION_SETTLE_JOB_ID = "option_auto_settle_daily"


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


def run_daily_backup() -> None:
    """Spec 37 — daily SQLite snapshot + rotation.

    Atomic via SQLite native backup API. Idempotent — re-running on the
    same day creates a second timestamped file; rotation keeps only the
    latest per day (up to 7 days) + last-of-month (up to 12 months).
    """
    try:
        result = create_backup(DATABASE_URL, BACKUP_DIR)
        rotated = rotate_backups(BACKUP_DIR)
        logger.info(
            "cron daily backup: path=%s size=%dMB pages=%d kept=%d deleted=%d",
            result.path.name, result.size_bytes // (1024 * 1024),
            result.pages_copied, len(rotated.kept), len(rotated.deleted),
        )
    except Exception:
        logger.exception("cron daily backup failed")


def run_daily_ptax_sync() -> None:
    """Spec 11 finalizer — sync PTAX incremental from BCB.

    Idempotent: re-runs over the same range upsert in-place. Weekends and
    holidays return fetched_count=0 (BCB does not publish on those days).
    """
    db = SessionLocal()
    try:
        result = sync_ptax(db, mode="incremental")
        db.commit()
        logger.info(
            "cron ptax sync: mode=%s range=%s..%s fetched=%d inserted=%d updated=%d",
            result.mode, result.range_start, result.range_end,
            result.fetched_count, result.inserted_count, result.updated_count,
        )
    except Exception:
        db.rollback()
        logger.exception("cron ptax sync failed")
    finally:
        db.close()


def run_option_auto_settle() -> None:
    """Detecta opções vencidas e marca como EXPIRED (pó) ou EXERCISED
    (atribuídas) usando o current_price do underlying.

    Roda logo após o price_refresh_daily (18:00 SP) pra usar current_price
    fresh. Opções sem preço disponível ficam como pendência (logged warning)
    e o user resolve manualmente.
    """
    db = SessionLocal()
    try:
        results = auto_settle_expired_options(
            db, created_by=CRON_USER_EMAIL,
        )
        if not results:
            logger.info("cron option auto-settle: nenhuma opção vencida ativa")
            db.commit()
            return
        expired = sum(1 for r in results if r.decision == "expired")
        exercised = sum(1 for r in results if r.decision == "exercised")
        skipped = sum(1 for r in results if r.decision == "skipped")
        for r in results:
            logger.info(
                "cron option auto-settle %s: %s (%s)",
                r.decision, r.ticker or r.option_id, r.reason,
            )
        db.commit()
        logger.info(
            "cron option auto-settle: expired=%d exercised=%d skipped=%d total=%d",
            expired, exercised, skipped, len(results),
        )
    except Exception:
        db.rollback()
        logger.exception("cron option auto-settle failed")
    finally:
        db.close()


def run_ptax_catchup() -> None:
    """Spec 44 follow-up — startup safety net for missed PTAX cron.

    The in-process scheduler only fires while the FastAPI server is up.
    Local-dev usage closes the laptop / kills ./dev.sh, so the 20h SP
    daily cron is routinely missed. On every app boot, if today's PTAX
    isn't already in the DB (and BCB has had time to publish it), fire
    an incremental sync.

    Skips work when `last_date == today (SP)` — idempotent anyway, but
    saves a BCB roundtrip when the user restarts the dev server mid-day.
    """
    db = SessionLocal()
    try:
        last_date = db.query(func.max(PTAXRate.date)).scalar()
        today_sp = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
        if last_date == today_sp:
            logger.info("ptax catchup: already up-to-date (last_date=%s)", last_date)
            return
        logger.info(
            "ptax catchup: last_date=%s today_sp=%s → syncing",
            last_date, today_sp,
        )
        result = sync_ptax(db, mode="incremental")
        db.commit()
        logger.info(
            "ptax catchup done: range=%s..%s fetched=%d inserted=%d updated=%d",
            result.range_start, result.range_end,
            result.fetched_count, result.inserted_count, result.updated_count,
        )
    except Exception:
        db.rollback()
        logger.exception("ptax catchup failed")
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
    # Spec 11 finalizer — daily PTAX sync at 20:00 SP. BCB publishes the
    # day's PTAX venda between 13h-17h SP; 20h is a safe margin and
    # avoids colliding with the 18h price refresh.
    sched.add_job(
        run_daily_ptax_sync,
        CronTrigger(hour=20, minute=0),
        id=PTAX_JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    # Spec 37 — daily DB backup at 07:00 SP. Aligned with start of
    # business day, before the user starts adding new movements.
    sched.add_job(
        run_daily_backup,
        CronTrigger(hour=7, minute=0),
        id=BACKUP_JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    # Auto-settlement de opções vencidas. Roda às 18:05 SP, 5 min após o
    # price_refresh_daily (18:00 SP) — assim current_price reflete o
    # fechamento do dia útil. PUT in-the-money exerce, CALL in-the-money
    # exerce, fora-do-dinheiro vira pó. Sem preço → skip (log warning).
    sched.add_job(
        run_option_auto_settle,
        CronTrigger(hour=18, minute=5),
        id=OPTION_SETTLE_JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    # Spec 44 follow-up — one-shot PTAX catchup right after start. The
    # 20h SP cron is missed whenever ./dev.sh isn't running at 20h
    # (laptop closed, weekend, etc.). DateTrigger(now) fires once as
    # soon as the scheduler picks it up.
    sched.add_job(
        run_ptax_catchup,
        DateTrigger(run_date=datetime.now()),
        id=PTAX_CATCHUP_JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    sched.start()
    next_price = sched.get_job(CRON_JOB_ID).next_run_time
    next_snap = sched.get_job(SNAPSHOT_JOB_ID).next_run_time
    next_ptax = sched.get_job(PTAX_JOB_ID).next_run_time
    next_backup = sched.get_job(BACKUP_JOB_ID).next_run_time
    next_settle = sched.get_job(OPTION_SETTLE_JOB_ID).next_run_time
    logger.info(
        "scheduler started: %s next=%s; %s next=%s; %s next=%s; %s next=%s; %s next=%s",
        CRON_JOB_ID, next_price, SNAPSHOT_JOB_ID, next_snap,
        PTAX_JOB_ID, next_ptax, BACKUP_JOB_ID, next_backup,
        OPTION_SETTLE_JOB_ID, next_settle,
    )
    app.state.scheduler = sched
    return sched


def stop_scheduler(app: "FastAPI") -> None:
    sched = getattr(app.state, "scheduler", None)
    if sched is not None:
        sched.shutdown(wait=False)
        logger.info("scheduler shut down")
