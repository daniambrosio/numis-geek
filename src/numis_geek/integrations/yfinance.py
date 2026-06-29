"""Yahoo Finance scraper client (no credential).

Used as fallback for US equities/ETFs where Finnhub doesn't carry the
data (e.g. expense_ratio for ETFs) and for monthly historical prices
(Spec 53 successor). yfinance scrapes Yahoo's web endpoints; it has no
ToS guarantee but is widely used in research/personal projects.

All network access is wrapped in try/except — failures raise
YFinanceError so the ingestion service can degrade gracefully.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

try:
    import yfinance as yf  # type: ignore[import-untyped]
    _HAS_YFINANCE = True
except Exception:
    yf = None  # type: ignore[assignment]
    _HAS_YFINANCE = False


class YFinanceError(RuntimeError):
    pass


def _as_decimal(v: Any) -> Decimal | None:
    if v is None:
        return None
    try:
        return Decimal(str(v))
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class YFinanceFundamentals:
    symbol: str
    snapshot_date: date
    pe: Decimal | None = None
    pb: Decimal | None = None
    eps: Decimal | None = None
    bvps: Decimal | None = None
    roe: Decimal | None = None
    dividend_yield_12m: Decimal | None = None
    dps_12m: Decimal | None = None
    expense_ratio: Decimal | None = None  # for ETFs
    aum: Decimal | None = None
    sector: str | None = None
    raw: dict = field(default_factory=dict)


@dataclass(frozen=True)
class YFinanceMonthlyPoint:
    date: date
    close: Decimal


def is_available() -> bool:
    return _HAS_YFINANCE


def fetch_fundamentals(symbol: str) -> YFinanceFundamentals:
    if not _HAS_YFINANCE:
        raise YFinanceError("yfinance package not installed")
    try:
        tk = yf.Ticker(symbol)
        info = tk.info or {}
    except Exception as e:
        raise YFinanceError(f"yfinance {symbol} failed: {e}") from e
    if not isinstance(info, dict) or not info:
        raise YFinanceError(f"yfinance {symbol} returned empty info")

    return YFinanceFundamentals(
        symbol=symbol,
        snapshot_date=datetime.now(timezone.utc).date(),
        pe=_as_decimal(info.get("trailingPE")),
        pb=_as_decimal(info.get("priceToBook")),
        eps=_as_decimal(info.get("trailingEps")),
        bvps=_as_decimal(info.get("bookValue")),
        roe=_as_decimal(info.get("returnOnEquity")),
        dividend_yield_12m=_as_decimal(info.get("dividendYield")),
        dps_12m=_as_decimal(info.get("dividendRate")),
        expense_ratio=_as_decimal(info.get("netExpenseRatio") or info.get("annualReportExpenseRatio")),
        aum=_as_decimal(info.get("totalAssets") or info.get("marketCap")),
        sector=info.get("sector") or info.get("category"),
        raw={k: v for k, v in info.items() if isinstance(v, (int, float, str, bool, type(None)))},
    )


def fetch_history_monthly(
    symbol: str, *, start: date, end: date,
) -> list[YFinanceMonthlyPoint]:
    """Monthly close series. start inclusive, end exclusive (yfinance semantics)."""
    if not _HAS_YFINANCE:
        raise YFinanceError("yfinance package not installed")
    try:
        tk = yf.Ticker(symbol)
        hist = tk.history(
            start=start.isoformat(),
            end=end.isoformat(),
            interval="1mo",
            auto_adjust=True,
        )
    except Exception as e:
        raise YFinanceError(f"yfinance history {symbol} failed: {e}") from e
    if hist is None or hist.empty:
        raise YFinanceError(f"yfinance history {symbol} empty")
    points: list[YFinanceMonthlyPoint] = []
    for idx, row in hist.iterrows():
        close = row.get("Close")
        if close is None:
            continue
        d = idx.date() if hasattr(idx, "date") else idx
        points.append(YFinanceMonthlyPoint(date=d, close=_as_decimal(close) or Decimal("0")))
    return points
