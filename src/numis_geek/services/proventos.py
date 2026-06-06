"""Spec 17 + 29 — unified income view with monthly aggregation.

Synthetic OPTION_PREMIUM rows are NOT persisted; they are computed on the
fly from AssetMovement rows where type IN (SELL_OPEN, BUY_TO_CLOSE) on
OPTION assets. The asset_id of the synthetic row is the option's
underlying_id (so /proventos shows the income alongside the underlying's
dividends — but DY/YoC calculations exclude OPTION_PREMIUM).

Spec 29 adds `aggregate_proventos(...)` which buckets the unioned rows by
month and breakdown dimension (klass / country / fi / type / total), in a
chosen currency (BRL or USD). The chart endpoint (spec 30) is a thin
wrapper over it.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from sqlalchemy.orm import Session

from numis_geek.models.account import Account
from numis_geek.models.asset import Asset, AssetClass
from numis_geek.models.asset_movement import AssetMovement, AssetMovementType
from numis_geek.models.distribution import Distribution, DistributionType
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.services.fx import FxRateNotFound, fx_rate_on


Breakdown = Literal["klass", "country", "fi", "type", "total"]
Currency = Literal["BRL", "USD"]
Period = Literal["12m", "24m", "ytd"]


# ── Constants: palettes & labels for chart segments ─────────────────────────

# Type palette — matches docs/prototype-deltas-2026-05-23.md §2.3.
# Distinct from the legacy DIST_TYPE_COLORS in frontend/lib/tokens.ts
# (which is used elsewhere); the chart endpoint dictates these.
TYPE_COLOR: dict[str, str] = {
    "DIVIDEND":           "#22c55e",
    "INTEREST":           "#3b82f6",
    "JCP":                "#f59e0b",
    "SECURITIES_LENDING": "#8b5cf6",
    "OPTION_PREMIUM":     "#a855f7",
}

TYPE_LABEL: dict[str, str] = {
    "DIVIDEND":           "Dividendo",
    "INTEREST":           "Juros / Cupom",
    "JCP":                "JCP",
    "SECURITIES_LENDING": "Aluguel",
    "OPTION_PREMIUM":     "Prêmio sintético",
}

# Fixed order so the "Por tipo" chip cards (specs 32/33) always render in
# the same sequence.
TYPE_ORDER: list[str] = [
    "DIVIDEND", "INTEREST", "JCP", "SECURITIES_LENDING", "OPTION_PREMIUM",
]

# Asset-class palette mirrors frontend/lib/tokens.ts KLASS to avoid the
# chart looking different from the rest of the app.
KLASS_COLOR: dict[str, str] = {
    "STOCK":           "#3b82f6",
    "REIT":            "#22c55e",
    "ETF":             "#8b5cf6",
    "FIXED_INCOME":    "#f59e0b",
    "FUND":            "#14b8a6",
    "CRYPTO":          "#eab308",
    "REAL_ESTATE":     "#ec4899",
    "VEHICLE":         "#ef4444",
    "CASH":            "#64748b",
    "FGTS":            "#84cc16",
    "PRIVATE_PENSION": "#06b6d4",
    "OPTION":          "#a855f7",
    "GENERIC":         "#94a3b8",   # for Distribution rows without asset_id
}

KLASS_LABEL: dict[str, str] = {
    "STOCK": "Ação", "REIT": "FII / REIT", "ETF": "ETF",
    "FIXED_INCOME": "Renda Fixa", "FUND": "Fundo", "CRYPTO": "Cripto",
    "REAL_ESTATE": "Imóvel", "VEHICLE": "Veículo", "CASH": "Dinheiro",
    "FGTS": "FGTS", "PRIVATE_PENSION": "Previdência", "OPTION": "Opção",
    "GENERIC": "Sem ticker",
}

COUNTRY_LABEL: dict[str, str] = {
    "BR": "Brasil", "US": "EUA", "_UNKNOWN": "—",
}
COUNTRY_COLOR: dict[str, str] = {
    "BR": "#22c55e", "US": "#3b82f6", "_UNKNOWN": "#94a3b8",
}

# Fallback palette for the "fi" breakdown (institutions don't have canonical
# colors on the backend side; reuse a small set).
_FI_PALETTE = [
    "#3b82f6", "#22c55e", "#f59e0b", "#a855f7", "#ec4899", "#14b8a6",
    "#ef4444", "#eab308", "#06b6d4", "#84cc16", "#64748b", "#8b5cf6",
]


# ── Data shapes ────────────────────────────────────────────────────────────


@dataclass
class ProventoRow:
    id: str
    source: str  # 'distribution' or 'option_premium'
    event_date: date
    type: str  # DistributionType.value or 'OPTION_PREMIUM'
    asset_id: str | None
    financial_institution_id: str | None
    gross_amount: Decimal
    net_amount: Decimal
    currency: str
    fx_rate: Decimal
    # Derived (spec 29):
    klass: str            # AssetClass.value of asset/underlying, or 'GENERIC'
    country: str | None   # 2-letter ISO or None
    ym: str               # 'YYYY-MM' from event_date


@dataclass
class ChartSegment:
    key: str
    label: str
    color: str
    value: Decimal | None = None  # None when used inside `legend`


@dataclass
class ChartRow:
    ym: str
    total: Decimal
    segments: list[ChartSegment]


@dataclass
class ChartTotals:
    sum: Decimal
    monthly_avg: Decimal
    max: Decimal


@dataclass
class ChartData:
    rows: list[ChartRow]
    legend: list[ChartSegment]
    totals: ChartTotals
    currency: Currency


# ── list_proventos: spec-17 unioning (now populates derived fields) ────────


def list_proventos(
    db: Session,
    workspace_id: str | None,
    *,
    include_synthetic: bool = True,
    from_date: date | None = None,
    to_date: date | None = None,
) -> list[ProventoRow]:
    rows: list[ProventoRow] = []

    # Cache asset metadata for both branches (klass + country lookups).
    asset_cache: dict[str, Asset] = {}

    def _ym(d: date) -> str:
        return f"{d.year:04d}-{d.month:02d}"

    def _asset(asset_id: str | None) -> Asset | None:
        if not asset_id:
            return None
        if asset_id not in asset_cache:
            asset_cache[asset_id] = db.get(Asset, asset_id)
        return asset_cache[asset_id]

    # Real distributions
    q = db.query(Distribution).filter(Distribution.is_active.is_(True))
    if workspace_id:
        q = q.filter(Distribution.workspace_id == workspace_id)
    if from_date:
        q = q.filter(Distribution.event_date >= from_date)
    if to_date:
        q = q.filter(Distribution.event_date <= to_date)
    for d in q.all():
        a = _asset(d.asset_id)
        klass = a.asset_class.value if a else "GENERIC"
        country = a.country if a else None
        rows.append(ProventoRow(
            id=d.id, source="distribution", event_date=d.event_date,
            type=d.type.value, asset_id=d.asset_id,
            financial_institution_id=d.financial_institution_id,
            gross_amount=d.gross_amount, net_amount=d.net_amount,
            currency=d.currency.value, fx_rate=d.fx_rate,
            klass=klass, country=country, ym=_ym(d.event_date),
        ))

    if not include_synthetic:
        return rows

    # Synthetic OPTION_PREMIUM rows from movements on OPTION assets.
    mq = (
        db.query(AssetMovement, Asset)
        .join(Asset, Asset.id == AssetMovement.asset_id)
        .filter(
            Asset.asset_class == AssetClass.OPTION,
            AssetMovement.type.in_([
                AssetMovementType.SELL_OPEN,
                AssetMovementType.BUY_TO_CLOSE,
            ]),
            AssetMovement.is_active.is_(True),
        )
    )
    if workspace_id:
        mq = mq.filter(AssetMovement.workspace_id == workspace_id)
    if from_date:
        mq = mq.filter(AssetMovement.event_date >= from_date)
    if to_date:
        mq = mq.filter(AssetMovement.event_date <= to_date)

    # Resolve FI via Asset.account_id (cache the lookup)
    account_cache: dict[str, str | None] = {}
    for m, opt in mq.all():
        if opt.account_id not in account_cache:
            acc = db.get(Account, opt.account_id)
            account_cache[opt.account_id] = acc.financial_institution_id if acc else None
        fi_id = account_cache.get(opt.account_id)

        # Attribute klass/country to the *underlying* — matches list_proventos
        # convention of asset_id = underlying_id for OPTION_PREMIUM.
        underlying = _asset(opt.underlying_id)
        klass = underlying.asset_class.value if underlying else "OPTION"
        country = underlying.country if underlying else opt.country

        rows.append(ProventoRow(
            id=m.id, source="option_premium", event_date=m.event_date,
            type="OPTION_PREMIUM",
            asset_id=opt.underlying_id,
            financial_institution_id=fi_id,
            gross_amount=m.net_amount, net_amount=m.net_amount,
            currency=m.currency.value, fx_rate=m.fx_rate,
            klass=klass, country=country, ym=_ym(m.event_date),
        ))

    rows.sort(key=lambda r: r.event_date, reverse=True)
    return rows


def dy_eligible_amount_brl(db: Session, asset_id: str, *, days: int = 365) -> Decimal:
    """Sum of DY-eligible distributions (excludes OPTION_PREMIUM) for a
    given asset over the last `days` days, in BRL.

    OPTION_PREMIUM is a synthetic view only — never a DistributionType row —
    so filtering on Distribution.type already excludes it. The explicit
    `.in_(list(DistributionType))` guard is kept as a regression fence.
    """
    cutoff = date.today() - timedelta(days=days)
    rows = db.query(Distribution).filter(
        Distribution.asset_id == asset_id,
        Distribution.is_active.is_(True),
        Distribution.event_date >= cutoff,
        Distribution.type.in_(list(DistributionType)),
    ).all()
    total = Decimal("0")
    for r in rows:
        net = r.net_amount or Decimal("0")
        # Spec 56 — BRL distributions já estão em BRL. fx_rate só converte USD.
        dist_ccy = r.currency.value if hasattr(r.currency, "value") else r.currency
        eff_fx = (r.fx_rate or Decimal("1")) if dist_ccy == "USD" else Decimal("1")
        total += net * eff_fx
    return total


# ── Spec 29: monthly aggregation ───────────────────────────────────────────


def period_range(period: Period, *, today: date | None = None) -> tuple[date, date]:
    """Return (from_date, to_date) inclusive for the period."""
    today = today or date.today()
    if period == "ytd":
        return date(today.year, 1, 1), today

    months = 12 if period == "12m" else 24
    # Walk back N-1 whole months from the first of the current month.
    year, month = today.year, today.month
    # Subtract (months - 1) months
    total = year * 12 + (month - 1) - (months - 1)
    from_year, from_month = divmod(total, 12)
    from_month += 1
    return date(from_year, from_month, 1), today


def _bucket_months(from_d: date, to_d: date) -> list[str]:
    """Inclusive list of YYYY-MM strings between from_d and to_d."""
    out: list[str] = []
    y, m = from_d.year, from_d.month
    while (y, m) <= (to_d.year, to_d.month):
        out.append(f"{y:04d}-{m:02d}")
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1
    return out


def _ptax_for_month(db: Session, cache: dict[str, Decimal], ym: str) -> Decimal | None:
    """PTAX rate for the last day of the month (walks back via fx_rate_on).
    Returns None if no rate is found within the walkback window."""
    if ym in cache:
        return cache[ym]
    year, month = int(ym[:4]), int(ym[5:7])
    # First day of the next month, minus 1 day = last day of `month`.
    if month == 12:
        end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)
    try:
        rate = fx_rate_on(db, end, max_walkback_days=15)
    except FxRateNotFound:
        rate = None
    cache[ym] = rate  # type: ignore[assignment]
    return rate


def _convert_amount(
    db: Session,
    cache: dict[str, Decimal],
    *,
    amount: Decimal,
    source_ccy: str,
    target_ccy: Currency,
    row_fx_rate: Decimal,
    ym: str,
) -> Decimal | None:
    """Convert `amount` from `source_ccy` to `target_ccy`.

    BRL→BRL or USD→USD: no-op.
    USD→BRL: multiply by the row's stored fx_rate (PTAX on event date).
    BRL→USD: divide by the month's PTAX. Returns None if PTAX unavailable.
    """
    if source_ccy == target_ccy:
        return amount

    if source_ccy == "USD" and target_ccy == "BRL":
        return amount * (row_fx_rate or Decimal("1"))

    if source_ccy == "BRL" and target_ccy == "USD":
        rate = _ptax_for_month(db, cache, ym)
        if rate is None or rate == 0:
            return None
        return amount / rate

    # Other currencies aren't supported.
    return None


def _segment_meta(
    db: Session, breakdown: Breakdown, fi_cache: dict[str, FinancialInstitution | None],
    key: str,
) -> tuple[str, str]:
    """(label, color) for a segment key in the given breakdown."""
    if breakdown == "type":
        return TYPE_LABEL.get(key, key), TYPE_COLOR.get(key, "#94a3b8")
    if breakdown == "klass":
        return KLASS_LABEL.get(key, key), KLASS_COLOR.get(key, "#94a3b8")
    if breakdown == "country":
        return COUNTRY_LABEL.get(key, key), COUNTRY_COLOR.get(key, "#94a3b8")
    if breakdown == "fi":
        if key not in fi_cache:
            fi_cache[key] = db.get(FinancialInstitution, key)
        fi = fi_cache.get(key)
        label = fi.short_name if fi else key[:8]
        # Stable color per FI by id hash → palette index.
        idx = int(key.replace("-", "")[:8], 16) % len(_FI_PALETTE) if fi else 0
        return label, _FI_PALETTE[idx]
    # total
    return "Total", "#6366f1"


def _row_key(breakdown: Breakdown, row: ProventoRow) -> str:
    if breakdown == "type":     return row.type
    if breakdown == "klass":    return row.klass
    if breakdown == "country":  return row.country or "_UNKNOWN"
    if breakdown == "fi":       return row.financial_institution_id or "_UNKNOWN"
    return "total"


def aggregate_proventos(
    db: Session,
    workspace_id: str | None,
    *,
    period: Period = "12m",
    breakdown: Breakdown = "klass",
    currency: Currency = "BRL",
    include_synthetic: bool = True,
    today: date | None = None,
) -> ChartData:
    """Aggregate distribution + synthetic option premium events into monthly
    buckets ready for a stacked-bar chart.

    See module docstring for behavior. The returned `legend` always contains
    every key that appears in any row plus, for breakdown='type', a fenced
    OPTION_PREMIUM entry even when synthetic rows are excluded — so the
    5-chip "Por tipo" UI can render the dim/dashed state of an off premium
    (specs 32/33).
    """
    from_d, to_d = period_range(period, today=today)

    raw_rows = list_proventos(
        db, workspace_id,
        include_synthetic=include_synthetic,
        from_date=from_d, to_date=to_d,
    )

    ptax_cache: dict[str, Decimal] = {}
    fi_cache: dict[str, FinancialInstitution | None] = {}

    # bucket[ym][key] = Decimal
    months = _bucket_months(from_d, to_d)
    bucket: dict[str, dict[str, Decimal]] = {ym: {} for ym in months}

    for r in raw_rows:
        if r.ym not in bucket:
            continue  # outside period (defensive — list_proventos already filters)
        converted = _convert_amount(
            db, ptax_cache,
            amount=r.net_amount or Decimal("0"),
            source_ccy=r.currency, target_ccy=currency,
            row_fx_rate=r.fx_rate, ym=r.ym,
        )
        if converted is None:
            continue
        key = _row_key(breakdown, r)
        bucket[r.ym][key] = bucket[r.ym].get(key, Decimal("0")) + converted

    # Build rows in chronological order.
    chart_rows: list[ChartRow] = []
    monthly_totals: list[Decimal] = []
    union_keys: set[str] = set()

    for ym in months:
        per_key = bucket[ym]
        total = sum(per_key.values(), Decimal("0"))
        monthly_totals.append(total)
        segments: list[ChartSegment] = []
        for key, value in per_key.items():
            union_keys.add(key)
            label, color = _segment_meta(db, breakdown, fi_cache, key)
            segments.append(ChartSegment(key=key, label=label, color=color, value=value))
        # Sort segments within the bar in a stable way:
        if breakdown == "type":
            segments.sort(key=lambda s: TYPE_ORDER.index(s.key) if s.key in TYPE_ORDER else 999)
        else:
            segments.sort(key=lambda s: s.key)
        chart_rows.append(ChartRow(ym=ym, total=total, segments=segments))

    # Build legend. For breakdown='type', always include all 5 TYPE_ORDER
    # entries (so OPTION_PREMIUM chip exists even when synthetic is off).
    if breakdown == "type":
        legend_keys = list(TYPE_ORDER)
    else:
        legend_keys = sorted(union_keys)

    legend: list[ChartSegment] = []
    for key in legend_keys:
        label, color = _segment_meta(db, breakdown, fi_cache, key)
        legend.append(ChartSegment(key=key, label=label, color=color, value=None))

    total_sum = sum(monthly_totals, Decimal("0"))
    monthly_avg = (total_sum / len(months)) if months else Decimal("0")
    max_month = max(monthly_totals, default=Decimal("0"))
    totals = ChartTotals(sum=total_sum, monthly_avg=monthly_avg, max=max_month)

    return ChartData(rows=chart_rows, legend=legend, totals=totals, currency=currency)
