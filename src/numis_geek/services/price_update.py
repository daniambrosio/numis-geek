"""Asset price update service — routes brapi for BR / Finnhub for US."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from sqlalchemy.orm import Session

from numis_geek.integrations.brapi import BrapiError, fetch_quote as brapi_quote
from numis_geek.integrations.finnhub import FinnhubError, fetch_quote as finnhub_quote
from numis_geek.models.asset import Asset, AssetClass
from numis_geek.models.integration_credential import (
    IntegrationCredential,
    IntegrationProvider,
)

PRICEABLE_CLASSES = {
    AssetClass.STOCK,
    AssetClass.REIT,
    AssetClass.ETF,
    AssetClass.FUND,
    AssetClass.CRYPTO,
}


@dataclass
class PriceUpdateResult:
    asset_id: str
    ticker: str | None
    country: str | None
    status: Literal["ok", "skipped", "failed"]
    provider: str | None
    old_price: Decimal | None
    new_price: Decimal | None
    error: str | None


def _get_token(db: Session, provider: IntegrationProvider) -> str | None:
    cred = (
        db.query(IntegrationCredential)
        .filter(
            IntegrationCredential.workspace_id.is_(None),
            IntegrationCredential.provider == provider,
            IntegrationCredential.is_active == True,  # noqa: E712
        )
        .first()
    )
    return cred.secret_value if cred else None


def refresh_one(db: Session, asset: Asset) -> PriceUpdateResult:
    """Refresh a single asset's current_price. Provider routed by country."""
    base = PriceUpdateResult(
        asset_id=asset.id,
        ticker=asset.ticker,
        country=asset.country,
        status="skipped",
        provider=None,
        old_price=asset.current_price,
        new_price=None,
        error=None,
    )

    if not asset.ticker:
        return base.__class__(**{**base.__dict__, "error": "no ticker"})
    if asset.asset_class not in PRICEABLE_CLASSES:
        return base.__class__(**{**base.__dict__, "error": f"class {asset.asset_class.value} not priceable"})

    country = (asset.country or "").upper()
    try:
        if country == "BR":
            token = _get_token(db, IntegrationProvider.BRAPI)
            if not token:
                return base.__class__(**{**base.__dict__, "error": "BRAPI credential missing"})
            quote = brapi_quote(asset.ticker, token)
            new_price = quote.price
            provider = "brapi"
        elif country == "US":
            token = _get_token(db, IntegrationProvider.FINNHUB)
            if not token:
                return base.__class__(**{**base.__dict__, "error": "FINNHUB credential missing"})
            quote = finnhub_quote(asset.ticker, token)
            new_price = quote.price
            provider = "finnhub"
        else:
            return base.__class__(**{**base.__dict__, "error": f"country {country} not supported"})
    except (BrapiError, FinnhubError) as e:
        return base.__class__(**{**base.__dict__, "status": "failed", "error": str(e)})

    asset.current_price = new_price
    asset.price_updated_at = datetime.now(timezone.utc)
    db.flush()
    return PriceUpdateResult(
        asset_id=asset.id,
        ticker=asset.ticker,
        country=asset.country,
        status="ok",
        provider=provider,
        old_price=base.old_price,
        new_price=new_price,
        error=None,
    )


@dataclass
class BulkRefreshSummary:
    total: int
    ok: int
    skipped: int
    failed: int
    results: list[PriceUpdateResult]


def refresh_bulk(
    db: Session,
    *,
    workspace_id: str | None = None,
    only_country: str | None = None,
) -> BulkRefreshSummary:
    """Refresh prices for all priceable, active, tickered assets."""
    q = db.query(Asset).filter(
        Asset.is_active == True,  # noqa: E712
        Asset.ticker.isnot(None),
        Asset.asset_class.in_(list(PRICEABLE_CLASSES)),
    )
    if workspace_id is not None:
        q = q.filter(Asset.workspace_id == workspace_id)
    if only_country is not None:
        q = q.filter(Asset.country == only_country.upper())

    results: list[PriceUpdateResult] = []
    ok = skipped = failed = 0
    for asset in q.all():
        r = refresh_one(db, asset)
        results.append(r)
        if r.status == "ok":
            ok += 1
        elif r.status == "failed":
            failed += 1
        else:
            skipped += 1

    return BulkRefreshSummary(
        total=len(results), ok=ok, skipped=skipped, failed=failed, results=results
    )
