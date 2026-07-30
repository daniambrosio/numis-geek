"""Coinbase public spot price client (no token).

Endpoint: GET https://api.coinbase.com/v2/prices/<pair>/spot
Response: {"data": {"amount": "67100.42", "base": "BTC", "currency": "USD"}}

We always quote in USD here. If we ever need BRL spot for a coin, switch
the pair from <SYM>-USD to <SYM>-BRL.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import httpx

COINBASE_SPOT = "https://api.coinbase.com/v2/prices/{pair}/spot"
COINBASE_CANDLES = "https://api.exchange.coinbase.com/products/{pair}/candles"
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


def fetch_close_on(
    symbol: str, target_date: date, quote_currency: str = "USD"
) -> Decimal | None:
    """Fechamento diário de ``symbol`` em ``target_date`` na Coinbase Exchange.

    Consulta ``/products/{PAIR}/candles`` com granularity=86400 (1 dia) na
    janela [target_date, target_date+1d). Response é lista de
    ``[time, low, high, open, close, volume]``. Sem walkback: retorna None
    quando não vem candle para o dia pedido.
    """
    pair = f"{symbol.upper()}-{quote_currency.upper()}"
    url = COINBASE_CANDLES.format(pair=pair)
    params = {
        "start": target_date.isoformat(),
        "end": (target_date + timedelta(days=1)).isoformat(),
        "granularity": 86400,
    }
    try:
        r = httpx.get(url, params=params, timeout=DEFAULT_TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except httpx.HTTPError as e:
        raise CoinbaseError(f"coinbase candles {pair} failed: {e}") from e
    except ValueError as e:
        raise CoinbaseError(f"coinbase candles {pair} returned non-JSON: {e}") from e

    if not isinstance(data, list) or not data:
        return None
    for row in data:
        if not isinstance(row, (list, tuple)) or len(row) < 5:
            continue
        try:
            candle_date = datetime.fromtimestamp(int(row[0]), tz=timezone.utc).date()
        except (TypeError, ValueError, OSError):
            continue
        if candle_date == target_date:
            try:
                return Decimal(str(row[4]))
            except (ArithmeticError, ValueError):
                return None
    return None
