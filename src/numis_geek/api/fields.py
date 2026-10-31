"""Shared request-field types (audit spec 70, 2026-10-31).

Money and rate inputs land in Numeric(18,2) / Numeric(18,8) columns and go
through `Decimal.quantize`. Without bounds, `1e30` or `1e-30` made quantize
raise InvalidOperation (500) and `0.004` slipped past the "não pode ser
zero" check before being stored as 0.00. These annotated types reject
out-of-range values with 422 and quantize up front, so routes and services
always see cents / 8-decimal rates.

Floats coming from the frontend (`0.1 + 0.2`) are accepted and rounded,
which is why this uses validators instead of `decimal_places=2`.
"""
from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated

from pydantic import AfterValidator

CENT = Decimal("0.01")
RATE_STEP = Decimal("0.00000001")
# Numeric(18,2): 16 integer digits.
MAX_MONEY = Decimal("1e14")
MAX_RATE = Decimal("1e9")
MIN_DATE = date(1900, 1, 1)
MAX_DATE = date(2200, 12, 31)


def _money(v: Decimal) -> Decimal:
    if not v.is_finite():
        raise ValueError("valor inválido")
    if abs(v) >= MAX_MONEY:
        raise ValueError("valor fora do limite")
    return v.quantize(CENT, ROUND_HALF_UP)


def _rate(v: Decimal) -> Decimal:
    if not v.is_finite() or v <= 0:
        raise ValueError("cotação deve ser positiva")
    if v >= MAX_RATE:
        raise ValueError("cotação fora do limite")
    q = v.quantize(RATE_STEP, ROUND_HALF_UP)
    if q <= 0:
        raise ValueError("cotação deve ser positiva")
    return q


def _bounded_date(v: date) -> date:
    if not MIN_DATE <= v <= MAX_DATE:
        raise ValueError(f"data fora do intervalo {MIN_DATE.isoformat()}..{MAX_DATE.isoformat()}")
    return v


Money = Annotated[Decimal, AfterValidator(_money)]
Rate = Annotated[Decimal, AfterValidator(_rate)]
BoundedDate = Annotated[date, AfterValidator(_bounded_date)]
