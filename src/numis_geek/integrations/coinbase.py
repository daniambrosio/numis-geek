"""Coinbase public spot price client (no token).

Endpoint: GET https://api.coinbase.com/v2/prices/<pair>/spot
Response: {"data": {"amount": "67100.42", "base": "BTC", "currency": "USD"}}

We always quote in USD here. If we ever need BRL spot for a coin, switch
the pair from <SYM>-USD to <SYM>-BRL.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import httpx

COINBASE_SPOT = "https://api.coinbase.com/v2/prices/{pair}/spot"
DEFAULT_TIMEOUT = 15.0


class CoinbaseError(RuntimeError):
    pass


@dataclass(frozen=True)
class CoinbaseQuote:
    symbol: str
    price: Decimal
    currency: str  # "USD"


def fetch_spot(symbol: str, quote_currency: str = "USD") -> CoinbaseQuote:
    pair = f"{symbol.upper()}-{quote_currency.upper()}"
    url = COINBASE_SPOT.format(pair=pair)
    try:
        r = httpx.get(url, timeout=DEFAULT_TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except httpx.HTTPError as e:
        raise CoinbaseError(f"coinbase {pair} failed: {e}") from e
    except ValueError as e:
        raise CoinbaseError(f"coinbase {pair} returned non-JSON: {e}") from e

    payload = data.get("data") if isinstance(data, dict) else None
    if not payload or "amount" not in payload:
        raise CoinbaseError(f"coinbase {pair} unexpected payload: {data!r}")

    try:
        price = Decimal(str(payload["amount"]))
    except (ArithmeticError, ValueError) as e:
        raise CoinbaseError(f"coinbase {pair} bad amount: {payload['amount']!r}") from e

    return CoinbaseQuote(
        symbol=symbol.upper(),
        price=price,
        currency=payload.get("currency", quote_currency).upper(),
    )
