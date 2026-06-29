"""Spec 61b — Fundamentals ingestion orchestrator.

Dispatch per (asset_class, country):
  BR STOCK/REIT/ETF        → brapi.fetch_fundamentals
  US STOCK/REIT            → finnhub.fetch_basic_financials
  US ETF                   → yfinance.fetch_fundamentals (expense_ratio + AUM)
  FIXED_INCOME             → MANUAL (skip in ingestion; user enters via UI)
  CRYPTO/REAL_ESTATE/...   → skip silently

Idempotent: writes one AssetFundamentals row per (asset_id, snapshot_date,
source). Cron runs once/day so the daily row is unique. Manual edits add
a second row with source=MANUAL for the same date — valuation reads the
most recent regardless of source.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from numis_geek.integrations import brapi, finnhub
from numis_geek.integrations import yfinance as yfin
from numis_geek.models.asset import Asset, AssetClass
from numis_geek.models.asset_fundamentals import (
    AssetFundamentals, FundamentalsSource,
)
from numis_geek.models.integration_credential import (
    IntegrationCredential, IntegrationProvider,
)

logger = logging.getLogger(__name__)


@dataclass
class IngestionSummary:
    ok: int = 0
    failed: int = 0
    skipped: int = 0
    details: list[tuple[str, str, str]] = field(default_factory=list)

    def record(self, asset_id: str, status: str, reason: str = "") -> None:
        self.details.append((asset_id, status, reason))
        if status == "ok":
            self.ok += 1
        elif status == "failed":
            self.failed += 1
        else:
            self.skipped += 1


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


def _dataclass_to_payload(obj: Any) -> dict:
    """Best-effort JSON-safe dict from a dataclass (skips non-serializable raw)."""
    out: dict[str, Any] = {}
    for k, v in obj.__dict__.items():
        if k == "raw":
            continue
        if isinstance(v, Decimal):
            out[k] = float(v)
        elif hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


def refresh_asset_fundamentals(
    db: Session, asset: Asset, *, force: bool = False,
) -> AssetFundamentals | None:
    """Fetch + persist fundamentals for one asset.

    Returns the persisted row, or None if no provider applied. Raises on
    provider-level exceptions (caller catches per-asset).
    """
    if asset.asset_class in (
        AssetClass.CRYPTO, AssetClass.REAL_ESTATE, AssetClass.VEHICLE,
        AssetClass.FGTS, AssetClass.CASH, AssetClass.PRIVATE_PENSION,
        AssetClass.OPTION, AssetClass.FUND,
    ):
        return None

    ticker = asset.ticker
    if not ticker:
        return None

    country = (asset.country or "").upper()
    today = datetime.now(timezone.utc).date()

    if asset.asset_class == AssetClass.FIXED_INCOME:
        return None  # manual only v1

    provider_source: FundamentalsSource | None = None
    fields: dict[str, Any] = {}
    raw_payload: dict | None = None

    if country == "BR":
        token = _get_token(db, IntegrationProvider.BRAPI)
        if not token:
            return None
        bf = brapi.fetch_fundamentals(ticker, token)
        provider_source = FundamentalsSource.BRAPI
        fields = {
            "pe": bf.pe,
            "pb": bf.pb,
            "eps": bf.eps,
            "bvps": bf.bvps,
            "roe": bf.roe,
            "dividend_yield_12m": bf.dividend_yield_12m,
            "dps_12m": bf.dps_12m,
            "p_vp": bf.p_vp,
        }
        raw_payload = bf.raw
    elif country == "US":
        if asset.asset_class == AssetClass.ETF and yfin.is_available():
            yf_f = yfin.fetch_fundamentals(ticker)
            provider_source = FundamentalsSource.YFINANCE
            fields = {
                "pe": yf_f.pe,
                "pb": yf_f.pb,
                "eps": yf_f.eps,
                "bvps": yf_f.bvps,
                "roe": yf_f.roe,
                "dividend_yield_12m": yf_f.dividend_yield_12m,
                "dps_12m": yf_f.dps_12m,
                "expense_ratio": yf_f.expense_ratio,
                "aum": yf_f.aum,
            }
            raw_payload = yf_f.raw
        else:
            token = _get_token(db, IntegrationProvider.FINNHUB)
            if not token:
                return None
            ff = finnhub.fetch_basic_financials(ticker, token)
            provider_source = FundamentalsSource.FINNHUB
            fields = {
                "pe": ff.pe,
                "pb": ff.pb,
                "eps": ff.eps,
                "bvps": ff.bvps,
                "roe": ff.roe,
                "roic": ff.roic,
                "net_margin": ff.net_margin,
                "ebitda_margin": ff.ebitda_margin,
                "debt_ebitda": ff.debt_ebitda,
                "earnings_growth_5y": ff.earnings_growth_5y,
                "dividend_yield_12m": ff.dividend_yield_12m,
                "payout_ratio": ff.payout_ratio,
                "dps_12m": ff.dps_12m,
            }
            raw_payload = ff.raw
    else:
        return None

    if provider_source is None:
        return None

    # Upsert: if a row for (asset, today, provider_source) already exists,
    # update in place; otherwise insert. force=True bumps date so a refresh
    # within the same day is recorded.
    existing = (
        db.query(AssetFundamentals)
        .filter(
            AssetFundamentals.asset_id == asset.id,
            AssetFundamentals.snapshot_date == today,
            AssetFundamentals.source == provider_source,
        )
        .first()
    )
    payload_json = json.dumps(
        {k: (float(v) if isinstance(v, Decimal) else v) for k, v in (raw_payload or {}).items()},
        default=str,
    )[:8192]
    if existing:
        for k, v in fields.items():
            setattr(existing, k, v)
        existing.raw_payload = payload_json
        existing.updated_at = datetime.now(timezone.utc)
        db.flush()
        return existing

    row = AssetFundamentals(
        workspace_id=asset.workspace_id,
        asset_id=asset.id,
        snapshot_date=today,
        source=provider_source,
        **fields,
        raw_payload=payload_json,
    )
    db.add(row)
    db.flush()
    return row


def refresh_workspace_fundamentals(
    db: Session, workspace_id: str,
) -> IngestionSummary:
    """Iterate active assets of a workspace and refresh each.

    Errors per-asset are caught and logged — one failure doesn't abort
    the rest. Returns a summary the caller logs to audit/console.
    """
    summary = IngestionSummary()
    assets = (
        db.query(Asset)
        .filter(Asset.workspace_id == workspace_id, Asset.is_active == True)  # noqa: E712
        .all()
    )
    for a in assets:
        try:
            row = refresh_asset_fundamentals(db, a)
        except Exception as e:
            summary.record(a.id, "failed", str(e)[:200])
            logger.exception("fundamentals refresh failed for %s", a.id)
            continue
        if row is None:
            summary.record(a.id, "skipped", "no provider applies")
        else:
            summary.record(a.id, "ok", row.source.value)
    return summary
