"""Spec 37 — tests for SQLite backup service + rotation."""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from numis_geek.services.backup import (
    create_backup,
    rotate_backups,
)


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    """Create a tiny SQLite DB with one table + one row."""
    db_path = tmp_path / "src.db"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO t (id, name) VALUES (1, 'first')")
        conn.commit()
    finally:
        conn.close()
    return db_path


def test_create_backup_writes_valid_sqlite_file(tmp_db, tmp_path):
    backup_dir = tmp_path / "backups"
    db_url = f"sqlite:///{tmp_db}"

    result = create_backup(db_url, backup_dir)

    assert result.path.exists()
    assert result.path.parent == backup_dir
    assert result.path.name.startswith("numis_geek-")
    assert result.path.name.endswith(".db")
    assert result.size_bytes > 0
    assert result.pages_copied > 0

    # Backup is a working SQLite file with the same data.
    conn = sqlite3.connect(str(result.path))
    try:
        row = conn.execute("SELECT id, name FROM t").fetchone()
        assert row == (1, "first")
    finally:
        conn.close()


def test_create_backup_with_label(tmp_db, tmp_path):
    db_url = f"sqlite:///{tmp_db}"
    result = create_backup(db_url, tmp_path / "backups", label="pre-spec-37")
    assert "-pre-spec-37.db" in result.path.name


def test_create_backup_creates_target_dir(tmp_db, tmp_path):
    """target_dir is created if it doesn't exist."""
    db_url = f"sqlite:///{tmp_db}"
    target = tmp_path / "does" / "not" / "exist" / "yet"
    assert not target.exists()
    create_backup(db_url, target)
    assert target.exists()


def test_rotate_backups_keeps_last_7_days_and_last_of_month(tmp_path):
    """Rotation keeps last N daily + last-of-month for M months."""
    backups = tmp_path / "backups"
    backups.mkdir()

    # Seed: 1 file per day from 2026-01-01 through 2026-05-25 (146 days).
    # Filenames follow `numis_geek-YYYYMMDD-HHMMSS.db`.
    from datetime import date, timedelta

    start = date(2026, 1, 1)
    end = date(2026, 5, 25)
    cur = start
    created: list[Path] = []
    while cur <= end:
        name = f"numis_geek-{cur.strftime('%Y%m%d')}-120000.db"
        p = backups / name
        p.write_bytes(b"x")  # placeholder content
        created.append(p)
        cur += timedelta(days=1)

    result = rotate_backups(backups, keep_daily=7, keep_monthly=12)

    # Expected to keep:
    #  - last 7 daily: May 19, 20, 21, 22, 23, 24, 25
    #  - last-of-month for Jan, Feb, Mar, Apr, May
    #    (May's last is 25, same as one of the dailies — dedup)
    expected_keep_names = {
        # Daily window (last 7)
        "numis_geek-20260519-120000.db",
        "numis_geek-20260520-120000.db",
        "numis_geek-20260521-120000.db",
        "numis_geek-20260522-120000.db",
        "numis_geek-20260523-120000.db",
        "numis_geek-20260524-120000.db",
        "numis_geek-20260525-120000.db",
        # Last-of-month
        "numis_geek-20260131-120000.db",
        "numis_geek-20260228-120000.db",
        "numis_geek-20260331-120000.db",
        "numis_geek-20260430-120000.db",
        # 2026-05-31 doesn't exist; 2026-05-25 (already in dailies) covers May
    }

    kept_names = {p.name for p in result.kept}
    deleted_names = {p.name for p in result.deleted}

    assert kept_names == expected_keep_names
    assert len(result.kept) + len(result.deleted) == len(created)
    assert kept_names.isdisjoint(deleted_names)

    # Deleted files are actually gone.
    for p in result.deleted:
        assert not p.exists()
    # Kept files still exist.
    for p in result.kept:
        assert p.exists()


def test_rotate_ignores_non_matching_files(tmp_path):
    """Files that don't match the backup pattern are not touched."""
    backups = tmp_path / "backups"
    backups.mkdir()

    (backups / "README.md").write_text("notes")
    (backups / "random.db").write_bytes(b"x")
    (backups / "numis_geek-20260524-002332.sql.gz").write_bytes(b"x")
    matched = backups / "numis_geek-20260520-120000.db"
    matched.write_bytes(b"x")

    result = rotate_backups(backups, keep_daily=7, keep_monthly=12)

    # Only the matched file is considered; nothing to delete since it's
    # within the keep window.
    assert result.kept == [matched]
    assert result.deleted == []
    # Non-matching files survived.
    assert (backups / "README.md").exists()
    assert (backups / "random.db").exists()
    assert (backups / "numis_geek-20260524-002332.sql.gz").exists()


def test_rotate_handles_empty_dir(tmp_path):
    result = rotate_backups(tmp_path / "missing", keep_daily=7, keep_monthly=12)
    assert result.kept == []
    assert result.deleted == []


def test_rotate_keeps_latest_per_day_when_multiple(tmp_path):
    """If a single day has multiple backups (manual + automated), keep newest."""
    backups = tmp_path / "backups"
    backups.mkdir()

    earlier = backups / "numis_geek-20260525-070000.db"
    later = backups / "numis_geek-20260525-150000-manual.db"
    earlier.write_bytes(b"x")
    later.write_bytes(b"x")

    result = rotate_backups(backups, keep_daily=7, keep_monthly=12)
    kept_names = {p.name for p in result.kept}
    assert later.name in kept_names
    assert earlier.name not in kept_names
    assert not earlier.exists()
