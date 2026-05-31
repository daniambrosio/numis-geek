"""Spec 35 — business day helpers (BR calendar only in V1).

PTAX is anchored to BR business days (BCB closes interbank trades on
those), so we align the snapshot period_end to the BR calendar even
for workspaces that hold US assets.
"""
from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

import holidays


@lru_cache(maxsize=8)
def _br_holidays_for_year(year: int) -> set[date]:
    return set(holidays.country_holidays("BR", years=year))


def is_business_day(d: date) -> bool:
    """True iff d is Mon-Fri and not a BR federal holiday."""
    if d.weekday() >= 5:
        return False
    return d not in _br_holidays_for_year(d.year)


def last_business_day(d: date) -> date:
    """Latest business day on or before d."""
    cur = d
    while not is_business_day(cur):
        cur -= timedelta(days=1)
    return cur


def first_business_day(d: date) -> date:
    """Earliest business day on or after d."""
    cur = d
    while not is_business_day(cur):
        cur += timedelta(days=1)
    return cur


def last_day_of_month(ym: str) -> date:
    """Last calendar day of the month (e.g. '2026-05' -> 2026-05-31).

    This is the canonical period_end for portfolio snapshots — anchored to
    the calendar month, not the trading calendar. fx_rate_on() walks back to
    the most recent PTAX when the date falls on a weekend/holiday.
    """
    year, month = int(ym[:4]), int(ym[5:7])
    if month == 12:
        return date(year + 1, 1, 1) - timedelta(days=1)
    return date(year, month + 1, 1) - timedelta(days=1)


def last_business_day_of_month(ym: str) -> date:
    """Last business day of the calendar month (e.g. '2026-05' -> 2026-05-29)."""
    return last_business_day(last_day_of_month(ym))


def first_business_day_of_month(ym: str) -> date:
    """First business day of the calendar month."""
    year, month = int(ym[:4]), int(ym[5:7])
    return first_business_day(date(year, month, 1))


def previous_month_ym(d: date) -> str:
    """ym (YYYY-MM) for the calendar month before d."""
    year, month = d.year, d.month
    if month == 1:
        return f"{year - 1:04d}-12"
    return f"{year:04d}-{month - 1:02d}"
