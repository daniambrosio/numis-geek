"""Spec 61c — Markowitz portfolio optimizer.

Min-variance solver with hard equality constraints per asset class
(from `target_allocation`) and inequality caps per country + per asset.
Multi-currency portfolios are flattened to BRL (with the snapshot's
own fx_rate baked in) — caller accepts the cambial-noise tradeoff
(rationale: simpler v1, revisit in v2 per-currency).

Returns a `MarkowitzResult` with the efficient frontier (20 points),
the optimal portfolio (min-variance respecting class targets), current
weights, suggested trades, binding constraints, excluded assets, and
warnings.

Persistence: NONE v1 — caller recomputes per POST.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Iterable

import numpy as np
from scipy.optimize import linprog, minimize
from sqlalchemy import select
from sqlalchemy.orm import Session

from numis_geek.models.asset import Asset, AssetClass
from numis_geek.models.asset_movement import AssetMovement, AssetMovementType
from numis_geek.models.portfolio_snapshot import (
    PortfolioSnapshot, PortfolioSnapshotItem, SnapshotStatus,
)
from numis_geek.models.target_allocation import (
    TargetAllocation, TargetAllocationDimension,
)

logger = logging.getLogger(__name__)


# ── Inputs ────────────────────────────────────────────────────────────────────


@dataclass
class MarkowitzInput:
    workspace_id: str
    class_targets: dict[str, Decimal]
    asset_cap: Decimal = Decimal("0.15")
    country_caps: dict[str, Decimal] = field(default_factory=lambda: {"BR": Decimal("0.70")})
    min_months: int = 12
    ledoit_wolf_alpha: float = 0.05


# ── Internal types ────────────────────────────────────────────────────────────


@dataclass
class AssetReturn:
    asset_id: str
    ticker: str | None
    name: str
    asset_class: str
    country: str
    monthly_returns: list[float]
    months: list[date]
    current_value_brl: float


# ── Outputs ───────────────────────────────────────────────────────────────────


@dataclass
class FrontierPoint:
    ret: float
    vol: float


@dataclass
class OptimalAllocation:
    asset_id: str
    ticker: str | None
    name: str
    asset_class: str
    country: str
    weight: float
    current_weight: float
    delta: float
    target_value_brl: float
    current_value_brl: float
    trade_action: str  # "BUY" | "SELL" | "HOLD"
    trade_value_brl: float


@dataclass
class ExcludedAsset:
    asset_id: str
    ticker: str | None
    name: str
    asset_class: str
    reason: str
    current_value_brl: float


@dataclass
class MarkowitzResult:
    as_of: date | None
    n_assets: int
    n_excluded: int
    total_value_brl: float
    expected_return: float
    volatility: float
    frontier: list[FrontierPoint]
    optimal: list[OptimalAllocation]
    excluded: list[ExcludedAsset]
    binding_constraints: list[str]
    warnings: list[str]


# ── Errors ────────────────────────────────────────────────────────────────────


class MarkowitzError(ValueError):
    """Pre-solver infeasibility or solver failure. Carries diagnostic msg."""


# ── Step 1: build monthly returns ─────────────────────────────────────────────


_APORTE_TYPES = (
    AssetMovementType.BUY,
    AssetMovementType.SUBSCRIPTION,
)
_RESGATE_TYPES = (
    AssetMovementType.SELL,
    AssetMovementType.FULL_REDEMPTION,
    AssetMovementType.COME_COTAS,
)


def build_monthly_returns(
    db: Session, workspace_id: str, *, min_months: int = 12,
) -> tuple[list[AssetReturn], list[ExcludedAsset], date | None]:
    """Build the BRL monthly return series for each asset of the workspace.

    Snapshot source: PortfolioSnapshotItem.market_value_brl. Cash flow
    adjustment via AssetMovement (BUY/SUBSCRIPTION add inflow,
    SELL/FULL_REDEMPTION/COME_COTAS subtract). Multi-currency is
    converted to BRL via the snapshot's own fx_rate (no recalculation).

    Returns (eligible, excluded, as_of_date). Eligible = ≥ min_months
    returns. Excluded = assets with too little history.
    """
    closed = (
        db.query(PortfolioSnapshot)
        .filter(
            PortfolioSnapshot.workspace_id == workspace_id,
            PortfolioSnapshot.status == SnapshotStatus.CLOSED,
        )
        .order_by(PortfolioSnapshot.period_end_date)
        .all()
    )
    if not closed:
        return [], [], None
    as_of = closed[-1].period_end_date

    # snapshot_id → period_end_date
    snap_dates = {s.id: s.period_end_date for s in closed}
    snap_order = [s for s in closed]

    # asset_id → list of (period_end_date, market_value_brl, quantity)
    items_by_asset: dict[str, list[tuple[date, float, float]]] = {}
    for s in snap_order:
        items = (
            db.query(PortfolioSnapshotItem)
            .filter(PortfolioSnapshotItem.snapshot_id == s.id)
            .all()
        )
        for it in items:
            if it.market_value_brl is None:
                continue
            mv = float(it.market_value_brl)
            qty = float(it.quantity) if it.quantity is not None else 0.0
            items_by_asset.setdefault(it.asset_id, []).append(
                (s.period_end_date, mv, qty)
            )

    eligible: list[AssetReturn] = []
    excluded: list[ExcludedAsset] = []

    # All movements indexed by asset for cash-flow adjustment.
    movs_by_asset: dict[str, list[AssetMovement]] = {}
    movs = db.query(AssetMovement).join(
        Asset, AssetMovement.asset_id == Asset.id,
    ).filter(Asset.workspace_id == workspace_id).all()
    for m in movs:
        movs_by_asset.setdefault(m.asset_id, []).append(m)

    assets = (
        db.query(Asset)
        .filter(Asset.workspace_id == workspace_id, Asset.is_active == True)  # noqa: E712
        .all()
    )

    for asset in assets:
        if asset.asset_class == AssetClass.OPTION:
            continue  # options não entram em otimização de longo prazo
        series = sorted(items_by_asset.get(asset.id, []), key=lambda t: t[0])
        if len(series) < 2:
            if series:
                current = series[-1][1]
            else:
                current = 0.0
            excluded.append(ExcludedAsset(
                asset_id=asset.id, ticker=asset.ticker, name=asset.name,
                asset_class=asset.asset_class.value,
                reason="histórico insuficiente para retornos mensais",
                current_value_brl=current,
            ))
            continue

        returns: list[float] = []
        months: list[date] = []
        prev_date, prev_mv, _ = series[0]
        for cur_date, cur_mv, _ in series[1:]:
            if prev_mv <= 0:
                prev_date, prev_mv = cur_date, cur_mv
                continue
            # Net cash flow (BRL) in (prev_date, cur_date]
            net_flow_brl = 0.0
            for m in movs_by_asset.get(asset.id, []):
                if not (prev_date < m.event_date <= cur_date):
                    continue
                if m.net_amount is None:
                    continue
                amt_brl = float(m.net_amount) * float(m.fx_rate or Decimal("1"))
                if m.type in _APORTE_TYPES:
                    net_flow_brl += amt_brl
                elif m.type in _RESGATE_TYPES:
                    net_flow_brl -= amt_brl
            r = (cur_mv - net_flow_brl) / prev_mv - 1.0
            returns.append(r)
            months.append(cur_date)
            prev_date, prev_mv = cur_date, cur_mv

        if len(returns) < min_months:
            excluded.append(ExcludedAsset(
                asset_id=asset.id, ticker=asset.ticker, name=asset.name,
                asset_class=asset.asset_class.value,
                reason=f"apenas {len(returns)} retornos mensais (mínimo {min_months})",
                current_value_brl=series[-1][1] if series else 0.0,
            ))
            continue

        eligible.append(AssetReturn(
            asset_id=asset.id, ticker=asset.ticker, name=asset.name,
            asset_class=asset.asset_class.value,
            country=asset.country or "",
            monthly_returns=returns,
            months=months,
            current_value_brl=series[-1][1],
        ))

    return eligible, excluded, as_of


# ── Step 2: covariance with Ledoit-Wolf shrinkage ────────────────────────────


def _align_returns(eligible: list[AssetReturn]) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Align monthly returns into a common time grid (intersection of dates).

    Returns (mean_vector, return_matrix [T × N], asset_ids).
    """
    if not eligible:
        return np.zeros(0), np.zeros((0, 0)), []
    # Intersection of dates so every asset has a value in every month.
    common = set(eligible[0].months)
    for ar in eligible[1:]:
        common &= set(ar.months)
    common_sorted = sorted(common)
    if len(common_sorted) < 2:
        raise MarkowitzError(
            "Ativos elegíveis não compartilham 12+ meses em comum — "
            "verifique consistência dos snapshots."
        )

    n = len(eligible)
    t = len(common_sorted)
    mat = np.zeros((t, n))
    for j, ar in enumerate(eligible):
        idx = {d: i for i, d in enumerate(ar.months)}
        for i, d in enumerate(common_sorted):
            mat[i, j] = ar.monthly_returns[idx[d]]
    mean = mat.mean(axis=0) * 12  # annualize
    return mean, mat, [ar.asset_id for ar in eligible]


def covariance_matrix(
    returns: np.ndarray, alpha: float = 0.05,
) -> np.ndarray:
    """Annualized covariance with Ledoit-Wolf-style shrinkage to identity.

    Σ_shrunk = (1-α) Σ_sample + α μ I    where μ = trace(Σ)/n
    Stabilizes the matrix when assets are nearly collinear (e.g. BTC + IBIT).
    Returns are monthly; we annualize via × 12 on Σ_sample.
    """
    if returns.shape[0] < 2:
        raise MarkowitzError("Insuficientes pontos pra calcular covariância")
    sample = np.cov(returns, rowvar=False) * 12
    n = sample.shape[0]
    if n == 0:
        return sample
    mu = float(np.trace(sample) / n)
    return (1 - alpha) * sample + alpha * mu * np.eye(n)


# ── Step 3: solver ────────────────────────────────────────────────────────────


def _validate_inputs(
    inp: MarkowitzInput, eligible: list[AssetReturn],
) -> None:
    if not eligible:
        raise MarkowitzError("Nenhum ativo elegível pra otimização")

    total = sum(inp.class_targets.values(), Decimal("0"))
    if abs(total - Decimal("1")) > Decimal("0.0001"):
        raise MarkowitzError(
            f"Soma dos class_targets = {total}; deve ser 1.0"
        )

    if inp.asset_cap <= 0 or inp.asset_cap > 1:
        raise MarkowitzError("asset_cap deve estar em (0, 1]")

    # Pre-solver feasibility: each class with target > 0 must have at least
    # enough eligible assets × asset_cap to reach the target.
    by_class: dict[str, list[AssetReturn]] = {}
    for ar in eligible:
        by_class.setdefault(ar.asset_class, []).append(ar)
    asset_cap_f = float(inp.asset_cap)
    for cls, target in inp.class_targets.items():
        t = float(target)
        if t <= 0:
            continue
        cls_assets = by_class.get(cls, [])
        if not cls_assets:
            raise MarkowitzError(
                f"Classe {cls} tem target {t:.0%} mas nenhum ativo elegível"
            )
        max_possible = len(cls_assets) * asset_cap_f
        if max_possible + 1e-9 < t:
            raise MarkowitzError(
                f"Classe {cls}: {len(cls_assets)} ativos × cap "
                f"{asset_cap_f:.0%} = {max_possible:.0%} < target {t:.0%}"
            )

    # country caps must be ≥ class allocation possible there (loose check)
    for ctry, cap in inp.country_caps.items():
        cap_f = float(cap)
        if cap_f < 0 or cap_f > 1:
            raise MarkowitzError(f"country_cap {ctry} fora de [0,1]")


def _feasible_starting_point(
    n: int, asset_classes: list[str],
    countries: list[str],
    class_targets: dict[str, float],
    country_caps: dict[str, float],
    asset_cap: float,
) -> np.ndarray:
    """Solve LP feasibility to find a point that satisfies ALL constraints.

    SLSQP needs a feasible (or near-feasible) initial point — equality
    constraints AND inequality bounds. We use scipy.linprog with a dummy
    objective (sum of weights = 1, already a constraint) to find any
    feasible vector, then hand it to SLSQP.
    """
    # Equality matrix: A_eq @ w = b_eq
    A_eq_rows: list[np.ndarray] = []
    b_eq: list[float] = []
    # sum(w) = 1
    A_eq_rows.append(np.ones(n))
    b_eq.append(1.0)
    # class equalities
    for cls, t in class_targets.items():
        idxs = [i for i, c in enumerate(asset_classes) if c == cls]
        if not idxs:
            continue
        row = np.zeros(n)
        for i in idxs:
            row[i] = 1.0
        A_eq_rows.append(row)
        b_eq.append(float(t))
    A_eq = np.vstack(A_eq_rows) if A_eq_rows else None
    b_eq_arr = np.array(b_eq) if b_eq else None

    # Inequality: A_ub @ w <= b_ub (country caps)
    A_ub_rows: list[np.ndarray] = []
    b_ub: list[float] = []
    for ctry, cap in country_caps.items():
        idxs = [i for i, c in enumerate(countries) if c == ctry]
        if not idxs:
            continue
        row = np.zeros(n)
        for i in idxs:
            row[i] = 1.0
        A_ub_rows.append(row)
        b_ub.append(float(cap))
    A_ub = np.vstack(A_ub_rows) if A_ub_rows else None
    b_ub_arr = np.array(b_ub) if b_ub else None

    bounds = [(0.0, asset_cap)] * n
    # Dummy objective: minimize 0 (any feasible point works)
    c = np.zeros(n)
    res = linprog(
        c, A_eq=A_eq, b_eq=b_eq_arr,
        A_ub=A_ub, b_ub=b_ub_arr,
        bounds=bounds, method="highs",
    )
    if not res.success:
        # Fall back to uniform — caller's pre-validation should have
        # caught true infeasibility, but if linprog disagrees we let
        # SLSQP try its best.
        return np.ones(n) / n
    return res.x


def _solve(
    mean: np.ndarray, cov: np.ndarray,
    *, asset_classes: list[str], countries: list[str],
    class_targets: dict[str, float],
    country_caps: dict[str, float],
    asset_cap: float,
    target_return: float | None = None,
) -> np.ndarray:
    """SLSQP min-variance with equality on class + sum, inequality on country."""
    n = len(mean)
    if n == 0:
        raise MarkowitzError("Vazio")
    x0 = _feasible_starting_point(
        n, asset_classes, countries, class_targets, country_caps, asset_cap,
    )

    def objective(w):
        return float(w @ cov @ w)

    def jac_obj(w):
        return 2.0 * cov @ w

    constraints: list[dict] = [
        {"type": "eq", "fun": lambda w: float(w.sum()) - 1.0},
    ]
    # Class equality.
    for cls, t in class_targets.items():
        idxs = [i for i, c in enumerate(asset_classes) if c == cls]
        if not idxs:
            continue
        constraints.append({
            "type": "eq",
            "fun": (lambda w, idxs=idxs, t=t: float(w[idxs].sum()) - t),
        })
    # Country caps (inequality: sum(w_country) <= cap).
    for ctry, cap in country_caps.items():
        idxs = [i for i, c in enumerate(countries) if c == ctry]
        if not idxs:
            continue
        constraints.append({
            "type": "ineq",
            "fun": (lambda w, idxs=idxs, cap=cap: cap - float(w[idxs].sum())),
        })
    if target_return is not None:
        constraints.append({
            "type": "eq",
            "fun": (lambda w, mean=mean, tr=target_return: float(w @ mean) - tr),
        })

    bounds = [(0.0, asset_cap)] * n

    res = minimize(
        objective, x0,
        method="SLSQP",
        constraints=constraints,
        bounds=bounds,
        options={"maxiter": 500, "ftol": 1e-8},
    )
    # SLSQP sometimes returns success=False with "Positive directional
    # derivative for linesearch" when the optimum is on a constraint
    # boundary — but the result is still valid. Accept any solution
    # that satisfies constraints within tolerance, regardless of flag.
    w = res.x
    if _is_feasible(w, class_targets, country_caps, asset_classes, countries, asset_cap, tol=1e-4):
        w = np.clip(w, 0.0, asset_cap)
        s = w.sum()
        if s > 0:
            return w / s
    # Last resort: x0 itself if it was feasible — at least gives the user
    # a deterministic answer to start from.
    if _is_feasible(x0, class_targets, country_caps, asset_classes, countries, asset_cap, tol=1e-4):
        return x0
    raise MarkowitzError(f"Solver falhou: {res.message}")


def _is_feasible(
    w: np.ndarray,
    class_targets: dict[str, float], country_caps: dict[str, float],
    asset_classes: list[str], countries: list[str],
    asset_cap: float, *, tol: float = 1e-4,
) -> bool:
    if w.min() < -tol or w.max() > asset_cap + tol:
        return False
    if abs(w.sum() - 1.0) > tol:
        return False
    for cls, t in class_targets.items():
        idxs = [i for i, c in enumerate(asset_classes) if c == cls]
        if abs(sum(w[i] for i in idxs) - t) > tol:
            return False
    for ctry, cap in country_caps.items():
        idxs = [i for i, c in enumerate(countries) if c == ctry]
        if sum(w[i] for i in idxs) - cap > tol:
            return False
    return True


# ── Step 4: frontier ──────────────────────────────────────────────────────────


def build_frontier(
    mean: np.ndarray, cov: np.ndarray, *,
    asset_classes: list[str], countries: list[str],
    class_targets: dict[str, float],
    country_caps: dict[str, float],
    asset_cap: float,
    n_points: int = 20,
) -> list[FrontierPoint]:
    """Sweep target_return from min mean to max mean, solve min-var for each.

    Skips infeasible target returns silently — caller gets the points
    that actually converged.
    """
    if mean.size == 0:
        return []
    lo, hi = float(mean.min()), float(mean.max())
    if hi <= lo + 1e-9:
        # Degenerate case — single point.
        try:
            w = _solve(
                mean, cov,
                asset_classes=asset_classes, countries=countries,
                class_targets=class_targets, country_caps=country_caps,
                asset_cap=asset_cap,
            )
            return [FrontierPoint(ret=float(w @ mean), vol=float((w @ cov @ w) ** 0.5))]
        except MarkowitzError:
            return []
    targets = np.linspace(lo, hi, n_points)
    points: list[FrontierPoint] = []
    for tr in targets:
        try:
            w = _solve(
                mean, cov,
                asset_classes=asset_classes, countries=countries,
                class_targets=class_targets, country_caps=country_caps,
                asset_cap=asset_cap, target_return=float(tr),
            )
        except MarkowitzError:
            continue
        ret = float(w @ mean)
        vol = float((w @ cov @ w) ** 0.5)
        points.append(FrontierPoint(ret=ret, vol=vol))
    return points


# ── Step 5: entry point ──────────────────────────────────────────────────────


def _binding_constraints(
    w: np.ndarray, asset_cap: float,
    asset_classes: list[str], countries: list[str],
    class_targets: dict[str, float], country_caps: dict[str, float],
) -> list[str]:
    out: list[str] = []
    for i, wi in enumerate(w):
        if abs(wi - asset_cap) < 1e-4:
            out.append(f"cap {asset_cap:.0%} ativado em ativo {i}")
    for ctry, cap in country_caps.items():
        idxs = [i for i, c in enumerate(countries) if c == ctry]
        if not idxs:
            continue
        s = w[idxs].sum()
        if abs(s - cap) < 1e-4:
            out.append(f"cap {cap:.0%} do país {ctry} ativado")
    return out


def get_class_targets_from_db(
    db: Session, workspace_id: str,
) -> dict[str, float]:
    rows = (
        db.query(TargetAllocation)
        .filter(
            TargetAllocation.workspace_id == workspace_id,
            TargetAllocation.dimension == TargetAllocationDimension.CLASS,
        )
        .all()
    )
    return {r.key: float(r.target_pct) for r in rows}


def optimize_portfolio(
    db: Session, inp: MarkowitzInput,
) -> MarkowitzResult:
    eligible, excluded, as_of = build_monthly_returns(
        db, inp.workspace_id, min_months=inp.min_months,
    )

    if not eligible:
        raise MarkowitzError(
            "Sem ativos elegíveis (precisa de pelo menos %d meses de "
            "snapshots fechados)." % inp.min_months,
        )

    _validate_inputs(inp, eligible)

    mean, returns_mat, asset_ids = _align_returns(eligible)
    cov = covariance_matrix(returns_mat, alpha=inp.ledoit_wolf_alpha)

    asset_classes = [ar.asset_class for ar in eligible]
    countries = [ar.country for ar in eligible]
    class_targets_f = {k: float(v) for k, v in inp.class_targets.items()}
    country_caps_f = {k: float(v) for k, v in inp.country_caps.items()}
    asset_cap_f = float(inp.asset_cap)

    w_opt = _solve(
        mean, cov,
        asset_classes=asset_classes, countries=countries,
        class_targets=class_targets_f, country_caps=country_caps_f,
        asset_cap=asset_cap_f,
    )

    expected_return = float(w_opt @ mean)
    variance = float(w_opt @ cov @ w_opt)
    volatility = variance ** 0.5

    eligible_value = float(sum(ar.current_value_brl for ar in eligible))
    excluded_value = float(sum(e.current_value_brl for e in excluded))
    total_value = eligible_value + excluded_value
    if eligible_value <= 0:
        raise MarkowitzError("Valor total dos ativos elegíveis é zero")

    current_weights = np.array([
        ar.current_value_brl / eligible_value for ar in eligible
    ])

    optimal: list[OptimalAllocation] = []
    for i, ar in enumerate(eligible):
        target_value = float(w_opt[i] * eligible_value)
        current_value = float(ar.current_value_brl)
        trade_value = target_value - current_value
        if abs(trade_value) < max(1.0, current_value * 0.005):
            action = "HOLD"
        elif trade_value > 0:
            action = "BUY"
        else:
            action = "SELL"
        optimal.append(OptimalAllocation(
            asset_id=ar.asset_id, ticker=ar.ticker, name=ar.name,
            asset_class=ar.asset_class, country=ar.country,
            weight=float(w_opt[i]),
            current_weight=float(current_weights[i]),
            delta=float(w_opt[i] - current_weights[i]),
            target_value_brl=target_value,
            current_value_brl=current_value,
            trade_action=action,
            trade_value_brl=trade_value,
        ))

    frontier = build_frontier(
        mean, cov,
        asset_classes=asset_classes, countries=countries,
        class_targets=class_targets_f, country_caps=country_caps_f,
        asset_cap=asset_cap_f,
    )

    binding = _binding_constraints(
        w_opt, asset_cap_f, asset_classes, countries,
        class_targets_f, country_caps_f,
    )

    warnings: list[str] = []
    if excluded:
        warnings.append(
            f"{len(excluded)} ativo(s) excluído(s) por falta de histórico — "
            f"mantidos no peso atual."
        )
    if excluded_value > 0 and eligible_value > 0:
        warnings.append(
            f"Otimização cobre {eligible_value/(eligible_value+excluded_value):.0%} "
            f"do portfólio em BRL."
        )
    warnings.append(
        "Retornos USD convertidos a BRL incluem variação cambial PTAX (v1)."
    )

    return MarkowitzResult(
        as_of=as_of,
        n_assets=len(eligible),
        n_excluded=len(excluded),
        total_value_brl=total_value,
        expected_return=expected_return,
        volatility=volatility,
        frontier=frontier,
        optimal=optimal,
        excluded=excluded,
        binding_constraints=binding,
        warnings=warnings,
    )
