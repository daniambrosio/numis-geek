"""Spec 22 — price freshness tiers.

Two threshold profiles depending on the source:

  Automated (BRAPI, FINNHUB, COINBASE, TESOURO):
      fresh  < 24h
      stale  < 7d
      old    >= 7d

  Manual:
      fresh  < 30d
      stale  < 90d
      old    >= 90d

Manuals have looser thresholds because imóvel/veículo/FGTS are not
expected to move daily — keeping them in the API tier would paint
the dashboard red forever.
"""
from __future__ import annotations

import enum
from datetime import datetime, timedelta, timezone
from typing import Iterable

from numis_geek.models.asset import Asset, PriceSource


class PriceTier(str, enum.Enum):
    FRESH = "FRESH"
    STALE = "STALE"
    OLD = "OLD"
    UNKNOWN = "UNKNOWN"


AUTOMATED_SOURCES: frozenset[PriceSource] = frozenset({
    PriceSource.BRAPI,
    PriceSource.FINNHUB,
    PriceSource.COINBASE,
    PriceSource.TESOURO,
})


_TIER_RANK = {
    PriceTier.FRESH: 0,
    PriceTier.STALE: 1,
    PriceTier.OLD: 2,
    PriceTier.UNKNOWN: 3,
}


def freshness_tier(
    updated_at: datetime | None,
    source: PriceSource | None,
    *,
    now: datetime | None = None,
) -> PriceTier:
    """Return the freshness tier for an asset's price.

    `now` is overridable for tests.
    """
    if updated_at is None or source is None:
        return PriceTier.UNKNOWN

    now = now or datetime.now(timezone.utc)
    if updated_at.tzinfo is None:
        # Stored as naive UTC by SQLAlchemy default. Treat as UTC.
        updated_at = updated_at.replace(tzinfo=timezone.utc)

    age = now - updated_at

    if source == PriceSource.MANUAL:
        if age < timedelta(days=30):
            return PriceTier.FRESH
        if age < timedelta(days=90):
            return PriceTier.STALE
        return PriceTier.OLD

    # Automated
    if age < timedelta(hours=24):
        return PriceTier.FRESH
    if age < timedelta(days=7):
        return PriceTier.STALE
    return PriceTier.OLD


def aggregate_tier(assets: Iterable[Asset], *, now: datetime | None = None) -> PriceTier:
    """Worst tier across assets with automated sources. MANUAL is ignored.

    Returns UNKNOWN if no automated-source asset is in the input.
    """
    worst = PriceTier.UNKNOWN
    seen_automated = False
    for asset in assets:
        if asset.price_source not in AUTOMATED_SOURCES:
            continue
        seen_automated = True
        tier = freshness_tier(asset.price_updated_at, asset.price_source, now=now)
        if _TIER_RANK[tier] > _TIER_RANK[worst] and tier != PriceTier.UNKNOWN:
            worst = tier
        elif worst == PriceTier.UNKNOWN and tier != PriceTier.UNKNOWN:
            worst = tier

    if not seen_automated:
        return PriceTier.UNKNOWN
    return worst
