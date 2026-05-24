"""Spec 22 — tests for services/price_freshness."""
from datetime import datetime, timedelta, timezone

import pytest

from numis_geek.models.asset import PriceSource
from numis_geek.services.price_freshness import (
    AUTOMATED_SOURCES,
    PriceTier,
    aggregate_tier,
    freshness_tier,
)


NOW = datetime(2026, 5, 24, 12, 0, 0, tzinfo=timezone.utc)


# ---------- freshness_tier ---------------------------------------------------


def test_freshness_tier_unknown_when_no_timestamp():
    assert freshness_tier(None, PriceSource.BRAPI, now=NOW) == PriceTier.UNKNOWN


def test_freshness_tier_unknown_when_no_source():
    assert freshness_tier(NOW - timedelta(hours=1), None, now=NOW) == PriceTier.UNKNOWN


@pytest.mark.parametrize("source", list(AUTOMATED_SOURCES))
def test_api_fresh_under_24h(source):
    updated = NOW - timedelta(hours=23, minutes=30)
    assert freshness_tier(updated, source, now=NOW) == PriceTier.FRESH


@pytest.mark.parametrize("source", list(AUTOMATED_SOURCES))
def test_api_stale_under_7d(source):
    updated = NOW - timedelta(days=3)
    assert freshness_tier(updated, source, now=NOW) == PriceTier.STALE


@pytest.mark.parametrize("source", list(AUTOMATED_SOURCES))
def test_api_old_at_or_over_7d(source):
    updated = NOW - timedelta(days=7)
    assert freshness_tier(updated, source, now=NOW) == PriceTier.OLD


def test_manual_fresh_under_30d():
    updated = NOW - timedelta(days=29)
    assert freshness_tier(updated, PriceSource.MANUAL, now=NOW) == PriceTier.FRESH


def test_manual_stale_between_30d_and_90d():
    updated = NOW - timedelta(days=60)
    assert freshness_tier(updated, PriceSource.MANUAL, now=NOW) == PriceTier.STALE


def test_manual_old_at_or_over_90d():
    updated = NOW - timedelta(days=90)
    assert freshness_tier(updated, PriceSource.MANUAL, now=NOW) == PriceTier.OLD


def test_freshness_handles_naive_datetime_as_utc():
    # SQLAlchemy stores DateTime naive by default; helper should treat as UTC.
    naive = (NOW - timedelta(hours=1)).replace(tzinfo=None)
    assert freshness_tier(naive, PriceSource.BRAPI, now=NOW) == PriceTier.FRESH


# ---------- aggregate_tier ---------------------------------------------------


class _FakeAsset:
    def __init__(self, source, updated_at):
        self.price_source = source
        self.price_updated_at = updated_at


def test_aggregate_returns_worst_automated_tier():
    assets = [
        _FakeAsset(PriceSource.BRAPI, NOW - timedelta(hours=1)),       # FRESH
        _FakeAsset(PriceSource.FINNHUB, NOW - timedelta(days=2)),      # STALE
        _FakeAsset(PriceSource.COINBASE, NOW - timedelta(days=10)),    # OLD
    ]
    assert aggregate_tier(assets, now=NOW) == PriceTier.OLD


def test_aggregate_ignores_manual_assets():
    # MANUAL alone → no automated → UNKNOWN.
    assets = [
        _FakeAsset(PriceSource.MANUAL, NOW - timedelta(days=200)),
    ]
    assert aggregate_tier(assets, now=NOW) == PriceTier.UNKNOWN


def test_aggregate_picks_worst_among_automated_when_manual_present():
    # OLD manual is ignored; BRAPI FRESH wins.
    assets = [
        _FakeAsset(PriceSource.MANUAL, NOW - timedelta(days=200)),
        _FakeAsset(PriceSource.BRAPI, NOW - timedelta(hours=2)),
    ]
    assert aggregate_tier(assets, now=NOW) == PriceTier.FRESH


def test_aggregate_empty_list_is_unknown():
    assert aggregate_tier([], now=NOW) == PriceTier.UNKNOWN


def test_aggregate_skips_assets_with_null_updated_at():
    assets = [
        _FakeAsset(PriceSource.BRAPI, None),                           # UNKNOWN → skipped from worst
        _FakeAsset(PriceSource.FINNHUB, NOW - timedelta(days=3)),      # STALE
    ]
    assert aggregate_tier(assets, now=NOW) == PriceTier.STALE
