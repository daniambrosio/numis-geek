"""Spec 61b — Valuation engine.

Per-class verdict (Comprar/Manter/Vender) computed from fundamentals +
current price. Pure-fn calculators (Bazin, Graham, Lynch PEG) + per-class
orchestrators. Reads `asset_fundamentals` (most recent snapshot per
asset, any source).

Required yields are workspace-fixed v1 (BRL=8%, USD=5%); per-asset
overrides are deferred to Spec 61.5.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Literal

from sqlalchemy.orm import Session

from numis_geek.models.asset import Asset, AssetClass
from numis_geek.models.asset_fundamentals import AssetFundamentals
from numis_geek.services import valuation_settings as VS


Verdict = Literal["BUY", "HOLD", "SELL", "NA"]


@dataclass(frozen=True)
class ValuationMetric:
    name: str
    value: Decimal | None
    unit: Literal["price", "ratio", "pct", "currency"]
    interpretation: Literal["cheap", "fair", "expensive", "na"] = "na"


@dataclass
class ValuationResult:
    asset_id: str
    asset_class: str
    currency: str
    verdict: Verdict
    verdict_reason: str
    metrics: list[ValuationMetric] = field(default_factory=list)
    disqualifying: list[str] = field(default_factory=list)
    fundamentals_as_of: date | None = None
    fundamentals_source: str | None = None
    is_stale: bool = False


# ── Pure-fn calculators ───────────────────────────────────────────────────────


def bazin_ceiling(
    dps_12m: Decimal | None, required_yield: Decimal
) -> Decimal | None:
    """Preço-teto Bazin = DPS_anual / required_yield.

    Returns None if dps_12m is missing/zero/negative or required_yield
    is non-positive.
    """
    if dps_12m is None or dps_12m <= 0 or required_yield <= 0:
        return None
    try:
        return dps_12m / required_yield
    except (InvalidOperation, ZeroDivisionError):
        return None


def graham_intrinsic(
    eps: Decimal | None, bvps: Decimal | None
) -> Decimal | None:
    """Valor justo Graham = √(22.5 × EPS × BVPS).

    Returns None when EPS or BVPS missing or non-positive (formula
    assumes positive earnings and book value).
    """
    if eps is None or bvps is None or eps <= 0 or bvps <= 0:
        return None
    try:
        raw = Decimal("22.5") * eps * bvps
        return _sqrt(raw)
    except (InvalidOperation, ZeroDivisionError):
        return None


def lynch_peg(
    pe: Decimal | None, earnings_growth: Decimal | None
) -> Decimal | None:
    """PEG = P/E ÷ (growth_rate × 100). growth_rate é fração ([0..1])."""
    if pe is None or earnings_growth is None or earnings_growth <= 0:
        return None
    growth_pct = earnings_growth * Decimal("100")
    if growth_pct <= 0:
        return None
    try:
        return pe / growth_pct
    except (InvalidOperation, ZeroDivisionError):
        return None


def _sqrt(x: Decimal) -> Decimal:
    """Newton's method square root in Decimal — keeps precision predictable."""
    if x < 0:
        raise InvalidOperation("sqrt of negative")
    if x == 0:
        return Decimal("0")
    guess = x / Decimal("2")
    for _ in range(40):
        next_guess = (guess + x / guess) / Decimal("2")
        if abs(next_guess - guess) < Decimal("1e-12"):
            break
        guess = next_guess
    return guess.quantize(Decimal("0.0001"))


# ── Required yield resolution ─────────────────────────────────────────────────


def required_yield_for(currency: str) -> Decimal:
    if currency.upper() == "USD":
        return VS.REQUIRED_YIELD_USD
    return VS.REQUIRED_YIELD_BRL


# ── Latest fundamentals lookup ────────────────────────────────────────────────


def latest_fundamentals(db: Session, asset_id: str) -> AssetFundamentals | None:
    """Most recent fundamentals row regardless of source."""
    return (
        db.query(AssetFundamentals)
        .filter(AssetFundamentals.asset_id == asset_id)
        .order_by(AssetFundamentals.snapshot_date.desc())
        .first()
    )


def _staleness(snapshot_date: date | None) -> bool:
    if snapshot_date is None:
        return True
    age = (datetime.now(timezone.utc).date() - snapshot_date).days
    return age > VS.FUNDAMENTALS_STALE_DAYS


# ── Per-class orchestrators ───────────────────────────────────────────────────


def _na(asset: Asset, reason: str) -> ValuationResult:
    return ValuationResult(
        asset_id=asset.id,
        asset_class=asset.asset_class.value,
        currency=asset.currency.value,
        verdict="NA",
        verdict_reason=reason,
    )


def _make_result(
    asset: Asset, fund: AssetFundamentals, verdict: Verdict, reason: str,
    metrics: list[ValuationMetric], gates: list[str],
) -> ValuationResult:
    return ValuationResult(
        asset_id=asset.id,
        asset_class=asset.asset_class.value,
        currency=asset.currency.value,
        verdict=verdict,
        verdict_reason=reason,
        metrics=metrics,
        disqualifying=gates,
        fundamentals_as_of=fund.snapshot_date,
        fundamentals_source=fund.source.value,
        is_stale=_staleness(fund.snapshot_date),
    )


def value_stock(asset: Asset, fund: AssetFundamentals) -> ValuationResult:
    """Verdict per rationale §12 STOCK row."""
    price = asset.current_price
    req_yield = required_yield_for(asset.currency.value)

    bazin = bazin_ceiling(fund.dps_12m, req_yield)
    graham = graham_intrinsic(fund.eps, fund.bvps)
    peg = lynch_peg(fund.pe, fund.earnings_growth_5y)

    metrics = [
        ValuationMetric("P/L", fund.pe, "ratio"),
        ValuationMetric("DY 12m", fund.dividend_yield_12m, "pct"),
        ValuationMetric("ROE", fund.roe, "pct"),
        ValuationMetric("Bazin", bazin, "price",
                        _interpret_ceiling(price, bazin)),
        ValuationMetric("Graham", graham, "price",
                        _interpret_ceiling(price, graham)),
        ValuationMetric("Lynch PEG", peg, "ratio"),
    ]

    gates: list[str] = []
    if fund.roe is not None and fund.roe < VS.GATE_ROE_MIN:
        gates.append("ROE negativo")
    if fund.debt_ebitda is not None and fund.debt_ebitda > VS.GATE_DEBT_EBITDA_MAX:
        gates.append(f"Dívida/EBITDA = {fund.debt_ebitda:.1f}x (limite {VS.GATE_DEBT_EBITDA_MAX})")
    if (
        fund.earnings_growth_5y is not None
        and fund.earnings_growth_5y < VS.GATE_EARNINGS_GROWTH_MIN
    ):
        gates.append("Lucros em queda nos últimos 5 anos")

    if price is None:
        return _make_result(
            asset, fund, "NA", "Sem preço atual cadastrado", metrics, gates,
        )

    cheap_bazin = bazin is not None and price < bazin
    cheap_graham = graham is not None and price < graham * VS.GRAHAM_BUY_MULTIPLIER

    if cheap_bazin and cheap_graham and not gates:
        reason = "Preço abaixo de Bazin e Graham × 1.2 sem disqualifying gates"
        return _make_result(asset, fund, "BUY", reason, metrics, gates)

    expensive_graham = (
        graham is not None and price > graham * VS.GRAHAM_SELL_MULTIPLIER
    )
    low_dy = (
        fund.dividend_yield_12m is not None
        and fund.dividend_yield_12m < req_yield * VS.SELL_DY_RATIO
    )
    if expensive_graham and low_dy:
        reason = "Preço acima de Graham × 1.5 e DY < 50% do required yield"
        return _make_result(asset, fund, "SELL", reason, metrics, gates)

    if gates:
        reason = "Disqualifying gates impedem BUY: " + "; ".join(gates)
    else:
        reason = "Sem sinais fortes — Manter"
    return _make_result(asset, fund, "HOLD", reason, metrics, gates)


def value_reit(asset: Asset, fund: AssetFundamentals) -> ValuationResult:
    """Verdict per rationale §12 REIT/FII row.

    BR REITs (FII): usa P/VP. US REITs: usa P/FFO se disponível;
    fallback pra P/VP.
    """
    req_yield = required_yield_for(asset.currency.value)
    is_br = (asset.country or "").upper() == "BR"
    pvp = fund.p_vp
    pffo = fund.p_ffo
    dy = fund.dividend_yield_12m

    metrics: list[ValuationMetric] = [
        ValuationMetric("P/VP", pvp, "ratio"),
        ValuationMetric("DY 12m", dy, "pct"),
    ]
    if not is_br:
        metrics.append(ValuationMetric("P/FFO", pffo, "ratio"))
        metrics.append(ValuationMetric("Cobertura", fund.distribution_coverage, "ratio"))
    metrics.append(ValuationMetric("Vacância", fund.vacancy, "pct"))

    gates: list[str] = []
    if fund.vacancy is not None and fund.vacancy > VS.REIT_VACANCY_MAX:
        gates.append(f"Vacância {fund.vacancy:.0%} acima do limite 20%")
    if (
        not is_br
        and fund.distribution_coverage is not None
        and fund.distribution_coverage < VS.REIT_DIST_COVERAGE_MIN
    ):
        gates.append("Distribution coverage < 1.0")

    cheap_book = pvp is not None and pvp < VS.REIT_PVP_BUY_MAX
    rich_book = pvp is not None and pvp > VS.REIT_PVP_SELL_MIN
    high_dy = dy is not None and dy > req_yield * VS.REIT_DY_BUY_RATIO
    low_dy = dy is not None and dy < req_yield * VS.REIT_DY_SELL_RATIO

    if cheap_book and high_dy and not gates:
        reason = f"P/VP {pvp:.2f} abaixo de 0.95 e DY {dy:.1%} > {VS.REIT_DY_BUY_RATIO}× required yield"
        return _make_result(asset, fund, "BUY", reason, metrics, gates)
    if rich_book and low_dy:
        reason = f"P/VP {pvp:.2f} acima de 1.2 e DY {dy:.1%} < 0.7× required yield"
        return _make_result(asset, fund, "SELL", reason, metrics, gates)
    if gates:
        reason = "Disqualifying gates impedem BUY: " + "; ".join(gates)
    else:
        reason = "Dentro da faixa neutra — Manter"
    return _make_result(asset, fund, "HOLD", reason, metrics, gates)


def value_etf(asset: Asset, fund: AssetFundamentals) -> ValuationResult:
    """ETF v1: sem verdict opinativo (sinais são informacionais)."""
    metrics = [
        ValuationMetric("Expense ratio", fund.expense_ratio, "pct"),
        ValuationMetric("AUM", fund.aum, "currency"),
        ValuationMetric("Tracking error", fund.tracking_error, "pct"),
        ValuationMetric("DY 12m", fund.dividend_yield_12m, "pct"),
    ]
    reason = "ETFs em v1 mostram métricas sem verdict — decisão segue alocação alvo"
    return ValuationResult(
        asset_id=asset.id,
        asset_class=asset.asset_class.value,
        currency=asset.currency.value,
        verdict="NA",
        verdict_reason=reason,
        metrics=metrics,
        fundamentals_as_of=fund.snapshot_date,
        fundamentals_source=fund.source.value,
        is_stale=_staleness(fund.snapshot_date),
    )


def value_fixed_income(asset: Asset, fund: AssetFundamentals) -> ValuationResult:
    metrics = [
        ValuationMetric("YTM", fund.ytm, "pct"),
        ValuationMetric("Duration", fund.duration, "ratio"),
    ]
    reason = "Renda fixa: decisão é de timing (curva de juros) — sem verdict v1"
    return ValuationResult(
        asset_id=asset.id,
        asset_class=asset.asset_class.value,
        currency=asset.currency.value,
        verdict="NA",
        verdict_reason=reason,
        metrics=metrics,
        fundamentals_as_of=fund.snapshot_date,
        fundamentals_source=fund.source.value,
        is_stale=_staleness(fund.snapshot_date),
    )


def _interpret_ceiling(price: Decimal | None, ceiling: Decimal | None
                       ) -> Literal["cheap", "fair", "expensive", "na"]:
    if price is None or ceiling is None:
        return "na"
    if price < ceiling:
        return "cheap"
    if price > ceiling * Decimal("1.2"):
        return "expensive"
    return "fair"


# ── Public entry point ────────────────────────────────────────────────────────


_NO_VERDICT_CLASSES = {
    AssetClass.FUND, AssetClass.CRYPTO, AssetClass.REAL_ESTATE,
    AssetClass.VEHICLE, AssetClass.FGTS, AssetClass.CASH,
    AssetClass.PRIVATE_PENSION, AssetClass.OPTION,
}


def value_asset(db: Session, asset: Asset) -> ValuationResult:
    """Single entry point — dispatches by asset_class."""
    if asset.asset_class in _NO_VERDICT_CLASSES:
        return _na(
            asset,
            f"Classe {asset.asset_class.value} fora do escopo de valuation v1",
        )

    fund = latest_fundamentals(db, asset.id)
    if fund is None:
        return _na(asset, "Sem fundamentos cadastrados/disponíveis")

    if asset.asset_class == AssetClass.STOCK:
        return value_stock(asset, fund)
    if asset.asset_class == AssetClass.REIT:
        return value_reit(asset, fund)
    if asset.asset_class == AssetClass.ETF:
        return value_etf(asset, fund)
    if asset.asset_class == AssetClass.FIXED_INCOME:
        return value_fixed_income(asset, fund)
    return _na(asset, f"Classe {asset.asset_class.value} sem orchestrator")
