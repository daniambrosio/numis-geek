"""brapi.dev client for BR assets (B3, FIIs, Tesouro).

Free tier requires a token (stored in IntegrationCredential). Endpoint:
  GET https://brapi.dev/api/quote/<ticker>?token=...
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

import httpx

BRAPI_BASE = "https://brapi.dev/api/quote/{ticker}"
DEFAULT_TIMEOUT = 15.0


class BrapiError(RuntimeError):
    pass


def _as_decimal(v: Any) -> Decimal | None:
    if v is None:
        return None
    try:
        return Decimal(str(v))
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class BrapiQuote:
    ticker: str
    price: Decimal


@dataclass(frozen=True)
class BrapiHistoryPoint:
    date: date
    close: Decimal


@dataclass(frozen=True)
class BrapiFundamentals:
    """Subset of brapi modules we map to AssetFundamentals.

    brapi.dev exposes `?modules=summaryProfile,defaultKeyStatistics,
    financialData,balanceSheetHistory` (and others). PRO-tier features
    such as `historicalDataPrice` are paid. We grab whatever the user's
    token returns and gracefully fall back to None for missing keys.
    """

    ticker: str
    snapshot_date: date
    pe: Decimal | None = None
    pb: Decimal | None = None
    eps: Decimal | None = None
    bvps: Decimal | None = None
    roe: Decimal | None = None
    dividend_yield_12m: Decimal | None = None
    dps_12m: Decimal | None = None
    p_vp: Decimal | None = None
    sector: str | None = None
    raw: dict = field(default_factory=dict)


_FUNDAMENTAL_MODULES = (
    "summaryProfile,"
    "defaultKeyStatistics,"
    "financialData,"
    "balanceSheetHistory,"
    "incomeStatementHistory"
)


def fetch_fundamentals(ticker: str, token: str) -> BrapiFundamentals:
    """Single brapi call requesting fundamental modules.

    For stocks: defaultKeyStatistics provides P/E (trailingPE), P/B, etc.
    For FIIs (FII tickers like XPLG11): brapi returns a different shape
    centered on dividends + priceToBookValueRatio. We try both layouts.
    Returns a BrapiFundamentals with all-None when nothing maps — caller
    decides whether to persist or skip.
    """
    url = BRAPI_BASE.format(ticker=ticker)
    params = {
        "token": token,
        "fundamental": "true",
        "dividends": "true",
        "modules": _FUNDAMENTAL_MODULES,
    }
    try:
        r = httpx.get(url, params=params, timeout=DEFAULT_TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except httpx.HTTPError as e:
        raise BrapiError(f"brapi fundamentals {ticker} failed: {e}") from e
    except ValueError as e:
        raise BrapiError(f"brapi fundamentals {ticker} returned non-JSON: {e}") from e

    results = data.get("results") if isinstance(data, dict) else None
    if not results:
        raise BrapiError(f"brapi fundamentals {ticker} empty: {data!r}")
    row = results[0]

    dks = row.get("defaultKeyStatistics") or {}
    fin = row.get("financialData") or {}
    summary = row.get("summaryProfile") or {}

    return BrapiFundamentals(
        ticker=ticker,
        snapshot_date=datetime.now(timezone.utc).date(),
        pe=_as_decimal(row.get("priceEarnings") or dks.get("trailingPE")),
        pb=_as_decimal(row.get("priceToBookValueRatio") or dks.get("priceToBook")),
        eps=_as_decimal(row.get("earningsPerShare") or dks.get("trailingEps")),
        bvps=_as_decimal(dks.get("bookValuePerShare")),
        roe=_as_decimal(fin.get("returnOnEquity")),
        dividend_yield_12m=_as_decimal(row.get("dividendYield")),
        dps_12m=_as_decimal(row.get("dividendRate")),
        # FII / brapi convenience field
        p_vp=_as_decimal(row.get("priceToBookValueRatio")),
        sector=summary.get("sector") if isinstance(summary, dict) else None,
        raw=row if isinstance(row, dict) else {},
    )


def fetch_quote(ticker: str, token: str) -> BrapiQuote:
    url = BRAPI_BASE.format(ticker=ticker)
    try:
        r = httpx.get(url, params={"token": token}, timeout=DEFAULT_TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except httpx.HTTPError as e:
        raise BrapiError(f"brapi {ticker} failed: {e}") from e
    except ValueError as e:
        raise BrapiError(f"brapi {ticker} returned non-JSON: {e}") from e

    results = data.get("results") if isinstance(data, dict) else None
    if not results:
        raise BrapiError(f"brapi {ticker} returned empty results: {data!r}")

    row = results[0]
    price = row.get("regularMarketPrice")
    if price is None:
        raise BrapiError(f"brapi {ticker} missing regularMarketPrice: {row!r}")
    return BrapiQuote(ticker=ticker, price=Decimal(str(price)))


def _range_for_target(target_date: date, *, today: date | None = None) -> str:
    """Pick smallest brapi range that covers ``today - target_date``.

    Aceita 1d/5d/1mo/3mo/6mo/1y/2y/5y/10y/max. Retorna a menor janela
    suficiente pra reduzir payload — walkback é responsabilidade do
    caller, não do adapter.
    """
    ref = today or datetime.now(timezone.utc).date()
    days = max((ref - target_date).days, 0)
    for threshold, label in (
        (5, "5d"),
        (30, "1mo"),
        (90, "3mo"),
        (180, "6mo"),
        (365, "1y"),
        (730, "2y"),
        (1825, "5y"),
        (3650, "10y"),
    ):
        if days <= threshold:
            return label
    return "max"


def fetch_close_on(
    ticker: str, token: str, target_date: date
) -> Decimal | None:
    """Preço de fechamento em ``target_date`` (ou None se não houver ponto exato).

    Wrapper puro em torno de :func:`fetch_history`: escolhe a janela mínima
    que cobre a data pedida e filtra a série. Sem walkback — datas sem
    candle (fins-de-semana, feriados) retornam None e o service decide.
    """
    range_ = _range_for_target(target_date)
    points = fetch_history(ticker, token, range_=range_)
    for p in points:
        if p.date == target_date:
            return p.close
    return None


def fetch_history(
    ticker: str,
    token: str,
    *,
    range_: str = "3mo",
    interval: str = "1d",
) -> list[BrapiHistoryPoint]:
    """Fecha diário do BRAPI. Janelas válidas: 1d, 5d, 1mo, 3mo, 6mo, 1y...

    Retorna lista ordenada por data crescente. Lança BrapiError quando o
    payload não traz `historicalDataPrice`.
    """
    url = BRAPI_BASE.format(ticker=ticker)
    try:
        r = httpx.get(
            url,
            params={"token": token, "range": range_, "interval": interval},
            timeout=DEFAULT_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
    except httpx.HTTPError as e:
        raise BrapiError(f"brapi history {ticker} failed: {e}") from e
    except ValueError as e:
        raise BrapiError(f"brapi history {ticker} returned non-JSON: {e}") from e

    results = data.get("results") if isinstance(data, dict) else None
    if not results:
        raise BrapiError(f"brapi history {ticker} returned empty results: {data!r}")
    row = results[0]
    hist = row.get("historicalDataPrice")
    if not isinstance(hist, list) or not hist:
        raise BrapiError(f"brapi history {ticker} missing historicalDataPrice: {row!r}")

    points: list[BrapiHistoryPoint] = []
    for h in hist:
        ts = h.get("date")
        close = h.get("close")
        if ts is None or close is None:
            continue
        d = datetime.fromtimestamp(int(ts), tz=timezone.utc).date()
        points.append(BrapiHistoryPoint(date=d, close=Decimal(str(close))))
    points.sort(key=lambda p: p.date)
    return points
