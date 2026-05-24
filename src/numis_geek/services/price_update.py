"""Asset price update service — dispatches by `Asset.price_source`.

Spec 23 generalization of the original Spec 12 routing-by-country logic.
Supports:
- refresh_one        (single asset)
- refresh_by_ids     (filter by asset_ids)
- refresh_by_source  (filter by PriceSource)
- refresh_all_automated (everything where source ∈ AUTOMATED_SOURCES)

The deprecated refresh_bulk/BulkRefreshSummary are kept so the existing
/assets/refresh-prices/bulk route keeps working; new callers should use
the functions above.

Audit: each successful refresh emits an audit event (`price.refresh` by
default, overridable for cron via `audit_action="price.refresh.cron"`).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Iterable, Literal

# Crypto symbols on Coinbase: 2-10 uppercase alphanumeric (BTC, ETH, USDC, MATIC).
_CRYPTO_TICKER_RE = re.compile(r"^[A-Z0-9]{2,10}$")

from sqlalchemy.orm import Session

from numis_geek.integrations.brapi import BrapiError, fetch_quote as brapi_quote
from numis_geek.integrations.coinbase import CoinbaseError, fetch_spot as coinbase_spot
from numis_geek.integrations.finnhub import FinnhubError, fetch_quote as finnhub_quote
from numis_geek.models.asset import Asset, AssetClass, PriceSource
from numis_geek.models.integration_credential import (
    IntegrationCredential,
    IntegrationProvider,
)
from numis_geek.services.audit import AuditService
from numis_geek.services.price_freshness import AUTOMATED_SOURCES


@dataclass
class PriceUpdateResult:
    asset_id: str
    ticker: str | None
    country: str | None
    status: Literal["ok", "skipped", "failed"]
    provider: str | None  # legacy field — same as source.value when set
    source: str | None    # PriceSource value
    old_price: Decimal | None
    new_price: Decimal | None
    error: str | None


@dataclass
class RefreshSummary:
    ok: int
    failed: int
    skipped: int
    errors: list[dict]  # [{asset_id, ticker, reason}, ...]
    ran_at: datetime
    results: list[PriceUpdateResult]


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


class _SkipReason(RuntimeError):
    """Configuration / data condition that should yield status=skipped."""


def _fetch_price(db: Session, asset: Asset) -> tuple[Decimal, str]:
    """Dispatch to the right adapter.

    Raises `_SkipReason` for config-level issues (missing credential, unsupported
    source). Raises adapter-specific errors (BrapiError / FinnhubError /
    CoinbaseError) for transient failures.

    Returns (price, provider_label).
    """
    source = asset.price_source
    if source == PriceSource.BRAPI:
        token = _get_token(db, IntegrationProvider.BRAPI)
        if not token:
            raise _SkipReason("BRAPI credential missing")
        quote = brapi_quote(asset.ticker, token)
        return quote.price, "brapi"

    if source == PriceSource.FINNHUB:
        token = _get_token(db, IntegrationProvider.FINNHUB)
        if not token:
            raise _SkipReason("FINNHUB credential missing")
        quote = finnhub_quote(asset.ticker, token)
        return quote.price, "finnhub"

    if source == PriceSource.COINBASE:
        if not _CRYPTO_TICKER_RE.match((asset.ticker or "").upper()):
            raise _SkipReason(
                f"ticker {asset.ticker!r} is not a valid Coinbase symbol "
                "(expected 2-10 uppercase alphanumerics)"
            )
        quote = coinbase_spot(asset.ticker)
        return quote.price, "coinbase"

    if source == PriceSource.TESOURO:
        raise _SkipReason("TESOURO adapter not implemented in V1")

    # MANUAL / None handled before reaching here
    raise _SkipReason(f"source {source} is not auto-refreshable")


def refresh_one(
    db: Session,
    asset: Asset,
    *,
    user_email: str = "system@cron",
    audit_action: str = "price.refresh",
) -> PriceUpdateResult:
    """Refresh a single asset's current_price; emit audit on success.

    The MANUAL gate is the caller's responsibility for endpoints that
    should 422 (e.g. /assets/{id}/refresh-price). Here we simply return
    a `skipped` result with an explanatory error.
    """
    base = PriceUpdateResult(
        asset_id=asset.id,
        ticker=asset.ticker,
        country=asset.country,
        status="skipped",
        provider=None,
        source=asset.price_source.value if asset.price_source else None,
        old_price=asset.current_price,
        new_price=None,
        error=None,
    )

    if asset.price_source not in AUTOMATED_SOURCES:
        base.error = "source is MANUAL or unset"
        return base
    if not asset.ticker:
        base.error = "no ticker"
        return base

    try:
        new_price, provider = _fetch_price(db, asset)
    except _SkipReason as e:
        base.error = str(e)
        return base  # status remains "skipped"
    except (BrapiError, FinnhubError, CoinbaseError) as e:
        base.status = "failed"
        base.error = str(e)
        return base

    old_price = asset.current_price
    asset.current_price = new_price
    asset.price_updated_at = datetime.now(timezone.utc)
    db.flush()

    AuditService(db).log(
        user_email=user_email,
        action=audit_action,
        workspace_id=asset.workspace_id,
        resource_type="asset",
        resource_id=asset.id,
        details={
            "ticker": asset.ticker,
            "name": asset.name,
            "old_price": str(old_price) if old_price is not None else None,
            "new_price": str(new_price),
            "source": asset.price_source.value,
        },
    )

    return PriceUpdateResult(
        asset_id=asset.id,
        ticker=asset.ticker,
        country=asset.country,
        status="ok",
        provider=provider,
        source=asset.price_source.value,
        old_price=old_price,
        new_price=new_price,
        error=None,
    )


def _summarize(results: list[PriceUpdateResult]) -> RefreshSummary:
    ok = sum(1 for r in results if r.status == "ok")
    failed = sum(1 for r in results if r.status == "failed")
    skipped = sum(1 for r in results if r.status == "skipped")
    errors = [
        {"asset_id": r.asset_id, "ticker": r.ticker, "reason": r.error}
        for r in results
        if r.status == "failed"
    ]
    return RefreshSummary(
        ok=ok, failed=failed, skipped=skipped,
        errors=errors, ran_at=datetime.now(timezone.utc), results=results,
    )


def _iter_assets(
    db: Session,
    *,
    workspace_id: str | None,
    source: PriceSource | None = None,
    asset_ids: Iterable[str] | None = None,
    automated_only: bool = False,
) -> list[Asset]:
    q = db.query(Asset).filter(Asset.is_active == True)  # noqa: E712
    if workspace_id is not None:
        q = q.filter(Asset.workspace_id == workspace_id)
    if source is not None:
        q = q.filter(Asset.price_source == source)
    if asset_ids is not None:
        ids = list(asset_ids)
        if not ids:
            return []
        q = q.filter(Asset.id.in_(ids))
    if automated_only:
        q = q.filter(Asset.price_source.in_(list(AUTOMATED_SOURCES)))
    return q.all()


def refresh_by_source(
    db: Session,
    source: PriceSource,
    *,
    workspace_id: str | None,
    user_email: str = "system@cron",
    audit_action: str = "price.refresh",
) -> RefreshSummary:
    if source not in AUTOMATED_SOURCES:
        return RefreshSummary(
            ok=0, failed=0, skipped=0, errors=[],
            ran_at=datetime.now(timezone.utc), results=[],
        )
    assets = _iter_assets(db, workspace_id=workspace_id, source=source)
    results = [
        refresh_one(db, a, user_email=user_email, audit_action=audit_action)
        for a in assets
    ]
    return _summarize(results)


def refresh_by_ids(
    db: Session,
    asset_ids: Iterable[str],
    *,
    workspace_id: str | None,
    user_email: str = "system@cron",
    audit_action: str = "price.refresh",
) -> RefreshSummary:
    assets = _iter_assets(db, workspace_id=workspace_id, asset_ids=asset_ids)
    results = [
        refresh_one(db, a, user_email=user_email, audit_action=audit_action)
        for a in assets
    ]
    return _summarize(results)


def refresh_all_automated(
    db: Session,
    *,
    workspace_id: str | None,
    user_email: str = "system@cron",
    audit_action: str = "price.refresh",
) -> RefreshSummary:
    assets = _iter_assets(db, workspace_id=workspace_id, automated_only=True)
    results = [
        refresh_one(db, a, user_email=user_email, audit_action=audit_action)
        for a in assets
    ]
    return _summarize(results)


# ── Legacy / deprecated ──────────────────────────────────────────────────────

PRICEABLE_CLASSES = {
    AssetClass.STOCK,
    AssetClass.REIT,
    AssetClass.ETF,
    AssetClass.FUND,
    AssetClass.CRYPTO,
}


@dataclass
class BulkRefreshSummary:
    """Deprecated — kept for /assets/refresh-prices/bulk back-compat."""
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
    user_email: str = "system@cron",
) -> BulkRefreshSummary:
    """Legacy endpoint handler. Delegates to refresh_all_automated with an
    optional country filter."""
    q = db.query(Asset).filter(
        Asset.is_active == True,  # noqa: E712
        Asset.price_source.in_(list(AUTOMATED_SOURCES)),
    )
    if workspace_id is not None:
        q = q.filter(Asset.workspace_id == workspace_id)
    if only_country is not None:
        q = q.filter(Asset.country == only_country.upper())

    results = [refresh_one(db, a, user_email=user_email) for a in q.all()]
    summary = _summarize(results)
    return BulkRefreshSummary(
        total=len(results),
        ok=summary.ok, skipped=summary.skipped, failed=summary.failed,
        results=results,
    )
