"""Finnhub client for US equity quotes.

Endpoint: GET https://finnhub.io/api/v1/quote?symbol=<sym>&token=<tok>
Response: {c: current, h: high, l: low, o: open, pc: previous_close, t: ts}
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import httpx

FINNHUB_QUOTE = "https://finnhub.io/api/v1/quote"
DEFAULT_TIMEOUT = 15.0


class FinnhubError(RuntimeError):
    pass


@dataclass(frozen=True)
class FinnhubQuote:
    symbol: str
    price: Decimal


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
