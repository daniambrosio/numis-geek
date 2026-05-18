"""FX rate resolution service.

`fx_rate_on(date)` returns the BCB PTAX (venda) for that date. When the
requested date has no rate (weekend/holiday), walks back to the previous
business day's rate up to `max_walkback_days` calendar days.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from numis_geek.models.ptax_rate import PTAXRate


class FxRateNotFound(Exception):
    """Raised when no PTAX rate is found within the walkback window."""


def fx_rate_on(
    db: Session,
    target_date: date,
    *,
    max_walkback_days: int = 10,
) -> Decimal:
    """Resolve PTAX USD/BRL for `target_date`.

    Returns PTAX venda (series 10813) — the canonical rate used by BCB and
    referenced in IRPF for USD-denominated income.

    Walks back up to `max_walkback_days` calendar days to find the previous
    business day's rate when the target date is a weekend/holiday.
    """
    row = (
        db.query(PTAXRate)
        .filter(PTAXRate.date <= target_date)
        .filter(PTAXRate.date >= target_date - timedelta(days=max_walkback_days))
        .order_by(PTAXRate.date.desc())
        .first()
    )
    if row is None:
        raise FxRateNotFound(
            f"No PTAX rate found within {max_walkback_days} days of {target_date}"
        )
    return row.rate
