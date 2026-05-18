"""PTAX sync orchestrator.

Wraps the BCB SGS client + ptax_rate upsert. Two modes:

  - incremental: from max(ptax_rate.date) + 1 day to today
  - full: from min(asset_movement.event_date) - 30 days to today
          (fallback: today - 5y if no movements exist)

Idempotent: re-running over an existing range updates rows in place.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from sqlalchemy import func
from sqlalchemy.orm import Session

from numis_geek.integrations.bcb import PTAXRow, fetch_ptax_range
from numis_geek.models.asset_movement import AssetMovement
from numis_geek.models.ptax_rate import PTAXRate


SyncMode = Literal["incremental", "full"]


@dataclass
class PtaxSyncResult:
    mode: SyncMode
    fetched_count: int
    inserted_count: int
    updated_count: int
    range_start: date
    range_end: date
    duration_ms: int


def _resolve_range(db: Session, mode: SyncMode) -> tuple[date, date]:
    today = date.today()

    if mode == "incremental":
        last: date | None = db.query(func.max(PTAXRate.date)).scalar()
        if last is None:
            return _resolve_range(db, "full")
        return (last + timedelta(days=1), today)

    earliest_movement: date | None = db.query(func.min(AssetMovement.event_date)).scalar()
    if earliest_movement is None:
        start = today - timedelta(days=365 * 5)
    else:
        start = earliest_movement - timedelta(days=30)
    return (start, today)


def _upsert_rows(db: Session, rows: list[PTAXRow]) -> tuple[int, int]:
    if not rows:
        return (0, 0)

    fetched_dates = [r.date for r in rows]
    existing = {
        r.date: r
        for r in db.query(PTAXRate).filter(PTAXRate.date.in_(fetched_dates)).all()
    }

    inserted = 0
    updated = 0
    now = datetime.now(timezone.utc)

    for row in rows:
        existing_row = existing.get(row.date)
        if existing_row is None:
            db.add(PTAXRate(
                date=row.date,
                rate=row.rate,
                source="BCB_SGS",
                fetched_at=now,
            ))
            inserted += 1
        elif existing_row.rate != row.rate:
            existing_row.rate = row.rate
            existing_row.fetched_at = now
            updated += 1

    db.flush()
    return (inserted, updated)


def sync_ptax(db: Session, *, mode: SyncMode = "incremental") -> PtaxSyncResult:
    """Synchronously fetch PTAX from BCB and upsert into `ptax_rate`."""
    start_t = time.monotonic()
    range_start, range_end = _resolve_range(db, mode)

    if range_end < range_start:
        return PtaxSyncResult(
            mode=mode,
            fetched_count=0,
            inserted_count=0,
            updated_count=0,
            range_start=range_start,
            range_end=range_end,
            duration_ms=int((time.monotonic() - start_t) * 1000),
        )

    rows = fetch_ptax_range(range_start, range_end)
    inserted, updated = _upsert_rows(db, rows)

    return PtaxSyncResult(
        mode=mode,
        fetched_count=len(rows),
        inserted_count=inserted,
        updated_count=updated,
        range_start=range_start,
        range_end=range_end,
        duration_ms=int((time.monotonic() - start_t) * 1000),
    )
