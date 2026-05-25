"""Spec 35 — tests for utils/business_day."""
from datetime import date

from numis_geek.utils.business_day import (
    first_business_day,
    first_business_day_of_month,
    is_business_day,
    last_business_day,
    last_business_day_of_month,
    previous_month_ym,
)


def test_is_business_day_weekends_excluded():
    # 2026-05-23 is a Saturday, 2026-05-24 a Sunday.
    assert is_business_day(date(2026, 5, 23)) is False
    assert is_business_day(date(2026, 5, 24)) is False
    # Monday is a business day.
    assert is_business_day(date(2026, 5, 25)) is True


def test_is_business_day_excludes_br_holiday():
    # 2026-04-21 is Tiradentes (federal holiday).
    assert is_business_day(date(2026, 4, 21)) is False


def test_last_business_day_walks_back_over_weekend():
    # Sunday 2026-05-24 -> walks back to Friday 2026-05-22.
    assert last_business_day(date(2026, 5, 24)) == date(2026, 5, 22)


def test_first_business_day_walks_forward_over_weekend():
    # Saturday 2026-05-23 -> walks forward to Monday 2026-05-25.
    assert first_business_day(date(2026, 5, 23)) == date(2026, 5, 25)


def test_last_business_day_of_month_picks_last_weekday():
    # May 2026: last calendar day is Sunday 2026-05-31 -> walks back to
    # Friday 2026-05-29.
    assert last_business_day_of_month("2026-05") == date(2026, 5, 29)


def test_last_business_day_of_month_skips_holiday():
    # April 2026: 2026-04-30 is a Thursday and not a holiday -> returns 30.
    assert last_business_day_of_month("2026-04") == date(2026, 4, 30)


def test_first_business_day_of_month_handles_weekend_start():
    # Feb 2026 starts on a Sunday -> first BD is Monday 2026-02-02.
    assert first_business_day_of_month("2026-02") == date(2026, 2, 2)


def test_previous_month_ym_basic():
    assert previous_month_ym(date(2026, 5, 25)) == "2026-04"


def test_previous_month_ym_year_boundary():
    assert previous_month_ym(date(2026, 1, 10)) == "2025-12"
