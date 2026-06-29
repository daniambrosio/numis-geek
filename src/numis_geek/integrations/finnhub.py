"""Finnhub client for US equity quotes + fundamentals.

Endpoints:
  GET https://finnhub.io/api/v1/quote?symbol=<sym>&token=<tok>
  GET https://finnhub.io/api/v1/stock/metric?symbol=<sym>&metric=all&token=<tok>
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

import httpx

FINNHUB_QUOTE = "https://finnhub.io/api/v1/quote"
FINNHUB_METRIC = "https://finnhub.io/api/v1/stock/metric"
DEFAULT_TIMEOUT = 15.0


class FinnhubError(RuntimeError):
    pass


def _as_decimal(v: Any) -> Decimal | None:
    if v is None:
        return None
    try:
        d = Decimal(str(v))
        return d
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class FinnhubQuote:
    symbol: str
    price: Decimal


@dataclass(frozen=True)
class FinnhubFundamentals:
    """Subset of finnhub /stock/metric we map to AssetFundamentals.

    Finnhub returns ~60+ metrics under `metric`. We pick the ones we
    actually use in valuation. Percentage metrics like ROE are stored
    in our schema as fractions [0..1] — Finnhub returns them in
    percentage form (e.g. 12.34 for 12.34%) so we divide by 100.
    """

    symbol: str
    snapshot_date: date
    pe: Decimal | None = None
    pb: Decimal | None = None
    eps: Decimal | None = None
    bvps: Decimal | None = None
    roe: Decimal | None = None
    roic: Decimal | None = None
    net_margin: Decimal | None = None
    ebitda_margin: Decimal | None = None
    debt_ebitda: Decimal | None = None
    earnings_growth_5y: Decimal | None = None
    dividend_yield_12m: Decimal | None = None
    payout_ratio: Decimal | None = None
    dps_12m: Decimal | None = None
    raw: dict = field(default_factory=dict)


def _pct(v: Any) -> Decimal | None:
    """Convert Finnhub-style percentage (12.34 → 0.1234)."""
    d = _as_decimal(v)
    return d / Decimal("100") if d is not None else None


def fetch_basic_financials(symbol: str, token: str) -> FinnhubFundamentals:
    try:
        r = httpx.get(
            FINNHUB_METRIC,
            params={"symbol": symbol, "metric": "all", "token": token},
            timeout=DEFAULT_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
    except httpx.HTTPError as e:
        raise FinnhubError(f"Finnhub metric {symbol} failed: {e}") from e
    except ValueError as e:
        raise FinnhubError(f"Finnhub metric {symbol} returned non-JSON: {e}") from e

    if not isinstance(data, dict):
        raise FinnhubError(f"Finnhub metric {symbol} unexpected payload: {data!r}")
    metric = data.get("metric") or {}
    if not isinstance(metric, dict):
        raise FinnhubError(f"Finnhub metric {symbol} missing 'metric' dict")

    return FinnhubFundamentals(
        symbol=symbol,
        snapshot_date=datetime.now(timezone.utc).date(),
        pe=_as_decimal(metric.get("peTTM") or metric.get("peNormalizedAnnual")),
        pb=_as_decimal(metric.get("pbAnnual") or metric.get("pbQuarterly")),
        eps=_as_decimal(metric.get("epsTTM") or metric.get("epsAnnual")),
        bvps=_as_decimal(metric.get("bookValuePerShareQuarterly") or metric.get("bookValuePerShareAnnual")),
        roe=_pct(metric.get("roeTTM") or metric.get("roeAnnual")),
        roic=_pct(metric.get("roiTTM") or metric.get("roiAnnual")),
        net_margin=_pct(metric.get("netProfitMarginTTM") or metric.get("netProfitMarginAnnual")),
        ebitda_margin=_pct(metric.get("ebitdaMargin5Y") or metric.get("ebitdaMarginTTM")),
        debt_ebitda=_as_decimal(metric.get("totalDebt/totalEquityAnnual")),
        earnings_growth_5y=_pct(metric.get("epsGrowth5Y")),
        dividend_yield_12m=_pct(metric.get("dividendYieldIndicatedAnnual") or metric.get("currentDividendYieldTTM")),
        payout_ratio=_pct(metric.get("payoutRatioTTM") or metric.get("payoutRatioAnnual")),
        dps_12m=_as_decimal(metric.get("dividendPerShareTTM") or metric.get("dividendPerShareAnnual")),
        raw=metric,
    )


def fetch_quote(symbol: str, token: str) -> FinnhubQuote:
    try:
        r = httpx.get(
            FINNHUB_QUOTE,
            params={"symbol": symbol, "token": token},
            timeout=DEFAULT_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
    except httpx.HTTPError as e:
        raise FinnhubError(f"Finnhub {symbol} failed: {e}") from e
    except ValueError as e:
        raise FinnhubError(f"Finnhub {symbol} returned non-JSON: {e}") from e

    if not isinstance(data, dict) or "c" not in data:
        raise FinnhubError(f"Finnhub {symbol} unexpected payload: {data!r}")
    price = data["c"]
    if price in (None, 0, 0.0):
        raise FinnhubError(f"Finnhub {symbol} returned zero price (likely unknown ticker)")
    return FinnhubQuote(symbol=symbol, price=Decimal(str(price)))
