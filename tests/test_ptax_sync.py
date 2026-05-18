"""Tests for ptax_sync service — idempotent upsert + window resolution."""
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import patch

from numis_geek.integrations.bcb import PTAXRow
from numis_geek.models.ptax_rate import PTAXRate
from numis_geek.services.ptax_sync import sync_ptax


def _mock_fetch(rows: list[PTAXRow]):
    return patch("numis_geek.services.ptax_sync.fetch_ptax_range", return_value=rows)


def test_sync_full_inserts_all_rows(db):
    rows = [
        PTAXRow(date=date(2026, 5, 14), rate=Decimal("4.9803")),
        PTAXRow(date=date(2026, 5, 15), rate=Decimal("5.0648")),
    ]
    with _mock_fetch(rows):
        result = sync_ptax(db, mode="full")
    assert result.fetched_count == 2
    assert result.inserted_count == 2
    assert result.updated_count == 0
    assert db.query(PTAXRate).count() == 2


def test_sync_idempotent_re_run_updates_zero(db):
    rows = [PTAXRow(date=date(2026, 5, 14), rate=Decimal("4.9803"))]
    with _mock_fetch(rows):
        sync_ptax(db, mode="full")
        result2 = sync_ptax(db, mode="full")
    assert result2.inserted_count == 0
    assert result2.updated_count == 0


def test_sync_updates_when_rate_changes(db):
    db.add(PTAXRate(
        date=date(2026, 5, 14),
        rate=Decimal("4.0000"),
        source="BCB_SGS",
        fetched_at=datetime.now(timezone.utc),
    ))
    db.flush()
    rows = [PTAXRow(date=date(2026, 5, 14), rate=Decimal("4.9803"))]
    with _mock_fetch(rows):
        result = sync_ptax(db, mode="full")
    assert result.updated_count == 1
    row = db.query(PTAXRate).filter(PTAXRate.date == date(2026, 5, 14)).first()
    assert row.rate == Decimal("4.9803")


def test_sync_incremental_resolves_window_from_max(db):
    db.add(PTAXRate(
        date=date(2026, 5, 10),
        rate=Decimal("4.0"),
        source="BCB_SGS",
        fetched_at=datetime.now(timezone.utc),
    ))
    db.flush()
    captured = {}

    def fake_fetch(start, end):
        captured["start"] = start
        captured["end"] = end
        return []

    with patch("numis_geek.services.ptax_sync.fetch_ptax_range", side_effect=fake_fetch):
        sync_ptax(db, mode="incremental")

    assert captured["start"] == date(2026, 5, 11)
    assert captured["end"] == date.today()
