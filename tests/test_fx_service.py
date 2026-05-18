"""Tests for fx_rate_on — PTAX resolution with weekend/holiday walkback."""
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from numis_geek.models.ptax_rate import PTAXRate
from numis_geek.services.fx import FxRateNotFound, fx_rate_on


def _seed_rate(db, d: date, rate: Decimal) -> None:
    db.add(PTAXRate(
        date=d, rate=rate, source="BCB_SGS", fetched_at=datetime.now(timezone.utc)
    ))
    db.flush()


def test_fx_rate_exact_match(db):
    _seed_rate(db, date(2026, 5, 15), Decimal("5.0648"))
    rate = fx_rate_on(db, date(2026, 5, 15))
    assert rate == Decimal("5.0648")


def test_fx_rate_walks_back_to_friday_on_saturday(db):
    _seed_rate(db, date(2026, 5, 15), Decimal("5.0648"))  # Friday
    rate = fx_rate_on(db, date(2026, 5, 16))  # Saturday
    assert rate == Decimal("5.0648")


def test_fx_rate_walks_back_to_friday_on_sunday(db):
    _seed_rate(db, date(2026, 5, 15), Decimal("5.0648"))
    rate = fx_rate_on(db, date(2026, 5, 17))  # Sunday
    assert rate == Decimal("5.0648")


def test_fx_rate_not_found_outside_window(db):
    _seed_rate(db, date(2026, 1, 1), Decimal("5.0"))
    with pytest.raises(FxRateNotFound):
        fx_rate_on(db, date(2026, 5, 18))


def test_fx_rate_respects_max_walkback(db):
    _seed_rate(db, date(2026, 5, 1), Decimal("5.0"))
    with pytest.raises(FxRateNotFound):
        fx_rate_on(db, date(2026, 5, 15), max_walkback_days=5)
    rate = fx_rate_on(db, date(2026, 5, 15), max_walkback_days=20)
    assert rate == Decimal("5.0")


def test_fx_rate_picks_latest_in_window(db):
    _seed_rate(db, date(2026, 5, 10), Decimal("5.0"))
    _seed_rate(db, date(2026, 5, 14), Decimal("5.1"))
    rate = fx_rate_on(db, date(2026, 5, 16))
    assert rate == Decimal("5.1")
