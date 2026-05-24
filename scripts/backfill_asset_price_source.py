"""Spec 22 — heuristic backfill of Asset.price_source.

Mapping rules:
    CRYPTO                          → COINBASE
    STOCK | REIT | ETF, country=BR  → BRAPI
    STOCK | REIT | ETF, country=US  → FINNHUB
    Everything else                 → MANUAL

Notes:
- Tesouro Direto assets fall into MANUAL by design — the TESOURO source
  value remains in the enum but no adapter is built in V1.
- B3 OPTIONs also fall into MANUAL — brapi's coverage of OPTION tickers
  is too sparse to be reliable (decision 2026-05-24, after live sync
  failed on the 2 existing options).

CLI:
    uv run python -m scripts.backfill_asset_price_source           # dry-run (preview only)
    uv run python -m scripts.backfill_asset_price_source --apply   # actually write
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter

from sqlalchemy.orm import Session

from numis_geek.db.session import SessionLocal
from numis_geek.models.asset import Asset, AssetClass, PriceSource


def classify(asset: Asset) -> PriceSource:
    klass = asset.asset_class
    country = (asset.country or "").upper()
    name = (asset.name or "").lower()

    if klass == AssetClass.CRYPTO:
        return PriceSource.COINBASE

    if klass in (AssetClass.STOCK, AssetClass.REIT, AssetClass.ETF):
        if country == "BR":
            return PriceSource.BRAPI
        if country == "US":
            return PriceSource.FINNHUB

    # OPTION falls through to MANUAL — brapi coverage is too sparse to be
    # reliable for B3 options. Revisit if/when a dedicated adapter exists.
    return PriceSource.MANUAL


def preview(db: Session) -> tuple[Counter, list[tuple[str, str, str, str]]]:
    counts: Counter = Counter()
    sample: list[tuple[str, str, str, str]] = []  # (source, class, country, name)
    seen_sample: set[str] = set()

    for asset in db.query(Asset).filter(Asset.price_source.is_(None)).all():
        target = classify(asset)
        counts[target.value] += 1
        key = f"{target.value}|{asset.asset_class.value}|{asset.country}"
        if key not in seen_sample:
            seen_sample.add(key)
            sample.append((
                target.value, asset.asset_class.value, asset.country or "-", asset.name[:40],
            ))

    sample.sort()
    return counts, sample


def render(counts: Counter, sample: list[tuple[str, str, str, str]]) -> None:
    total = sum(counts.values())
    print(f"\nAssets without price_source: {total}\n")
    print("Backfill mapping:")
    for source in ("BRAPI", "FINNHUB", "COINBASE", "TESOURO", "MANUAL"):
        n = counts.get(source, 0)
        bar = "█" * min(40, n)
        print(f"  {source:<10} {n:>5}  {bar}")

    print("\nSample (one per source/class/country combo):")
    print(f"  {'SOURCE':<10} {'CLASS':<14} {'CTRY':<5} NAME")
    for s, c, ctry, n in sample[:30]:
        print(f"  {s:<10} {c:<14} {ctry:<5} {n}")
    if len(sample) > 30:
        print(f"  ... +{len(sample) - 30} more combos")


def apply(db: Session) -> int:
    updated = 0
    for asset in db.query(Asset).filter(Asset.price_source.is_(None)).all():
        asset.price_source = classify(asset)
        updated += 1
    db.commit()
    return updated


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Actually write changes")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        counts, sample = preview(db)
        render(counts, sample)

        if not args.apply:
            print("\nDry-run only. Re-run with --apply to commit.")
            return 0

        n = apply(db)
        print(f"\nApplied: {n} assets updated.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
