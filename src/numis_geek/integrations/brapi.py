"""brapi.dev client for BR assets (B3, FIIs, Tesouro).

Free tier requires a token (stored in IntegrationCredential). Endpoint:
  GET https://brapi.dev/api/quote/<ticker>?token=...
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

import httpx

BRAPI_BASE = "https://brapi.dev/api/quote/{ticker}"
DEFAULT_TIMEOUT = 15.0


class BrapiError(RuntimeError):
    pass


@dataclass(frozen=True)
class BrapiQuote:
    ticker: str
    price: Decimal


@dataclass(frozen=True)
class BrapiHistoryPoint:
    date: date
    close: Decimal


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
