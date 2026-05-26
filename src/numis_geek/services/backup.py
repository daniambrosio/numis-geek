"""Spec 37 — backup automation.

Atomic SQLite snapshots via the native `conn.backup()` API + rotation.

Local-only for now. Off-host (S3, R2) and Postgres portability come
pre-VPS. See `memory/db_is_production_no_reset.md` for context.
"""
from __future__ import annotations

import logging
import re
import sqlite3
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


BACKUP_FILENAME_PREFIX = "numis_geek"
BACKUP_FILENAME_RE = re.compile(
    r"^numis_geek-(\d{8})-(\d{6})(?:-([^.]+))?\.db$"
)


@dataclass
class BackupResult:
    path: Path
    size_bytes: int
    duration_ms: int
    pages_copied: int


@dataclass
class RotationResult:
    kept: list[Path] = field(default_factory=list)
    deleted: list[Path] = field(default_factory=list)


def _resolve_sqlite_path(db_url: str) -> Path:
    """Extract the file path from a SQLite URL.

    SQLite URL conventions (per SQLAlchemy):
      - `sqlite:///rel/path.db`  → relative to cwd: `rel/path.db`
      - `sqlite:////abs/path.db` → absolute: `/abs/path.db`
    The third slash is the empty-host separator; we strip it.
    """
    if not db_url.startswith("sqlite"):
        raise ValueError(f"Backup service only supports SQLite; got {db_url!r}")
    after_scheme = db_url.split("://", 1)[1]
    if after_scheme.startswith("/"):
        after_scheme = after_scheme[1:]
    return Path(after_scheme)


def create_backup(
    db_url: str,
    target_dir: Path,
    label: str | None = None,
    now: datetime | None = None,
) -> BackupResult:
    """Atomic SQLite snapshot via the native backup API.

    Filename: `numis_geek-YYYYMMDD-HHMMSS.db`
              (or `-<label>.db` when label given).
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    src_path = _resolve_sqlite_path(db_url)
    if not src_path.exists():
        raise FileNotFoundError(f"Source DB not found: {src_path}")

    ts = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    suffix = f"-{label}" if label else ""
    dst_path = target_dir / f"{BACKUP_FILENAME_PREFIX}-{ts}{suffix}.db"

    start_t = time.monotonic()
    pages_copied = 0

    src_conn = sqlite3.connect(str(src_path))
    dst_conn = sqlite3.connect(str(dst_path))
    try:
        def _progress(status, remaining, total):
            nonlocal pages_copied
            pages_copied = total
        src_conn.backup(dst_conn, progress=_progress)
    finally:
        dst_conn.close()
        src_conn.close()

    duration_ms = int((time.monotonic() - start_t) * 1000)
    size_bytes = dst_path.stat().st_size
    return BackupResult(
        path=dst_path,
        size_bytes=size_bytes,
        duration_ms=duration_ms,
        pages_copied=pages_copied,
    )


def _parse_backup_filename(name: str) -> datetime | None:
    m = BACKUP_FILENAME_RE.match(name)
    if not m:
        return None
    date_str, time_str = m.group(1), m.group(2)
    try:
        return datetime.strptime(f"{date_str}{time_str}", "%Y%m%d%H%M%S")
    except ValueError:
        return None


def rotate_backups(
    target_dir: Path,
    keep_daily: int = 7,
    keep_monthly: int = 12,
) -> RotationResult:
    """Keep last N daily snapshots + last-of-month for last M months.

    Files not matching `numis_geek-YYYYMMDD-HHMMSS*.db` are ignored.
    """
    result = RotationResult()
    if not target_dir.exists():
        return result

    parsed: list[tuple[datetime, Path]] = []
    for p in target_dir.iterdir():
        if not p.is_file():
            continue
        dt = _parse_backup_filename(p.name)
        if dt is None:
            continue
        parsed.append((dt, p))

    if not parsed:
        return result

    parsed.sort(key=lambda x: x[0], reverse=True)  # newest first

    # Daily: per-date latest, up to keep_daily distinct dates.
    by_date: dict[str, Path] = {}
    for dt, path in parsed:
        date_key = dt.strftime("%Y-%m-%d")
        if date_key not in by_date:
            by_date[date_key] = path  # first encountered = newest of that day
    daily_dates = list(by_date.keys())[:keep_daily]
    keep_set: set[Path] = {by_date[d] for d in daily_dates}

    # Monthly: per-month latest, up to keep_monthly distinct months.
    by_month: dict[str, Path] = {}
    for dt, path in parsed:
        month_key = dt.strftime("%Y-%m")
        if month_key not in by_month:
            by_month[month_key] = path
    monthly_months = list(by_month.keys())[:keep_monthly]
    keep_set.update(by_month[m] for m in monthly_months)

    for _dt, path in parsed:
        if path in keep_set:
            result.kept.append(path)
        else:
            try:
                path.unlink()
                result.deleted.append(path)
            except OSError:
                logger.exception("failed to delete rotated backup %s", path)

    return result
