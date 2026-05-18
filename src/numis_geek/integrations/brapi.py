"""brapi.dev client for BR assets (B3, FIIs, Tesouro).

Free tier requires a token (stored in IntegrationCredential). Endpoint:
  GET https://brapi.dev/api/quote/<ticker>?token=...
"""
from __future__ import annotations

from dataclasses import dataclass
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
