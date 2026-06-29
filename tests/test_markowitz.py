"""Spec 61c — Markowitz solver tests.

Synthetic fixtures with known analytical properties. Tests cover:
- build_monthly_returns (cotado, modo-valor com aporte)
- covariance_matrix shrinkage stability
- solver respeita class targets, asset cap, country cap
- pre-solver infeasibility detection (422)
- excluded assets (< min_months) handled gracefully
"""
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import numpy as np
import pytest

from numis_geek.models.account import Account, AccountType, Currency
from numis_geek.models.asset import Asset, AssetClass
from numis_geek.models.asset_movement import AssetMovement, AssetMovementType
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.portfolio_snapshot import (
    PortfolioSnapshot, PortfolioSnapshotItem, SnapshotSource, SnapshotStatus,
)
from numis_geek.models.workspace import Workspace
from numis_geek.services.markowitz import (
    MarkowitzError, MarkowitzInput, build_monthly_returns,
    covariance_matrix, optimize_portfolio,
)


# ── Fixture builders ─────────────────────────────────────────────────────────


def _setup_workspace(db):
    ws = Workspace(name=f"WS-mk-{uuid.uuid4().hex[:6]}")
    db.add(ws); db.flush()
    fi = FinancialInstitution(
        id=str(uuid.uuid4()), long_name="FI", short_name="FI",
        logo_slug=None, is_active=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(fi); db.flush()
    acc = Account(
        id=str(uuid.uuid4()), workspace_id=ws.id,
        financial_institution_id=fi.id, name="Acc",
        account_type=AccountType.investment, currency=Currency.BRL,
        opening_balance=Decimal("0"), is_active=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(acc); db.flush()
    return ws, acc


def _add_asset(db, ws, acc, *, name="A", ticker="A",
               asset_class=AssetClass.STOCK, country="BR",
               currency=Currency.BRL):
    asset = Asset(
        id=str(uuid.uuid4()), workspace_id=ws.id, account_id=acc.id,
        asset_class=asset_class, country=country, name=name,
        ticker=ticker, currency=currency, is_active=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(asset); db.flush()
    return asset


def _add_snapshots_with_items(
    db, ws, *, n_months=14, items: dict,
):
    """items: dict[asset_id] -> list of mv_brl (length == n_months)."""
    today = date.today()
    snaps = []
    for i in range(n_months):
        period_end = (today - timedelta(days=30 * (n_months - 1 - i)))
        snap = PortfolioSnapshot(
            workspace_id=ws.id, period_end_date=period_end,
            fx_rate_usd_brl=Decimal("5"),
            source=SnapshotSource.AUTOMATED,
            status=SnapshotStatus.CLOSED,
        )
        db.add(snap); db.flush()
        for asset_id, values in items.items():
            mv = values[i]
            it = PortfolioSnapshotItem(
                snapshot_id=snap.id, asset_id=asset_id,
                quantity=Decimal("1"),
                unit_price=Decimal(str(mv)),
                market_value_brl=Decimal(str(mv)),
                market_value_native=Decimal(str(mv)),
            )
            db.add(it)
        snaps.append(snap)
    db.flush()
    return snaps


def _add_movement(db, asset, *, type_, event_date, net_amount):
    m = AssetMovement(
        workspace_id=asset.workspace_id, asset_id=asset.id, type=type_,
        event_date=event_date, quantity=Decimal("1"),
        unit_price=Decimal("1"), gross_amount=Decimal(str(net_amount)),
        net_amount=Decimal(str(net_amount)), fx_rate=Decimal("1"),
        currency=Currency.BRL,
    )
    db.add(m); db.flush()
    return m


# ── build_monthly_returns ────────────────────────────────────────────────────


def test_build_returns_simple_no_flows(db):
    ws, acc = _setup_workspace(db)
    a = _add_asset(db, ws, acc, name="A", ticker="A")
    # 14 months of values doubling each month: r ≈ 100% per month
    values = [100 * (1.01 ** i) for i in range(14)]  # 1% per month
    _add_snapshots_with_items(db, ws, n_months=14, items={a.id: values})

    eligible, excluded, as_of = build_monthly_returns(db, ws.id, min_months=12)
    assert len(eligible) == 1
    assert len(excluded) == 0
    ar = eligible[0]
    # We had 14 snapshots → 13 returns
    assert len(ar.monthly_returns) == 13
    # Each return should be ~0.01 (Decimal→float roundtrip introduces ~1e-5 drift)
    assert all(abs(r - 0.01) < 1e-4 for r in ar.monthly_returns)


def test_build_returns_with_cash_flow_aporte(db):
    ws, acc = _setup_workspace(db)
    a = _add_asset(db, ws, acc, name="A", ticker="A")
    # Without flow: mv stays flat → return 0
    # Insert an aporte in month 6 of 50 → mv jumps from 100 to 150
    # cash-flow-adjusted return = (150 - 50) / 100 - 1 = 0
    values = [100.0] * 6 + [150.0] * 8
    snaps = _add_snapshots_with_items(db, ws, n_months=14, items={a.id: values})
    # Add aporte in month 6 (between snap[5] and snap[6])
    flow_date = snaps[5].period_end_date + timedelta(days=10)
    _add_movement(db, a, type_=AssetMovementType.BUY,
                  event_date=flow_date, net_amount=50)

    eligible, _, _ = build_monthly_returns(db, ws.id, min_months=12)
    assert len(eligible) == 1
    r6 = eligible[0].monthly_returns[5]
    # Should be ~0 thanks to the aporte adjustment (float roundtrip drift OK)
    assert abs(r6) < 1e-4


def test_build_returns_excludes_too_short(db):
    ws, acc = _setup_workspace(db)
    a = _add_asset(db, ws, acc)
    _add_snapshots_with_items(db, ws, n_months=5, items={a.id: [100.0] * 5})
    eligible, excluded, _ = build_monthly_returns(db, ws.id, min_months=12)
    assert eligible == []
    assert len(excluded) == 1
    assert "histórico" in excluded[0].reason or "retornos" in excluded[0].reason


def test_build_returns_skips_options(db):
    ws, acc = _setup_workspace(db)
    opt = _add_asset(db, ws, acc, asset_class=AssetClass.OPTION,
                     ticker="OPT")
    _add_snapshots_with_items(db, ws, n_months=14, items={opt.id: [10.0] * 14})
    eligible, excluded, _ = build_monthly_returns(db, ws.id, min_months=12)
    assert eligible == []
    assert excluded == []  # options não vão nem pra excluded


# ── covariance shrinkage ─────────────────────────────────────────────────────


def test_covariance_shrinkage_stabilizes_singular():
    # Two perfectly correlated assets → sample cov is singular
    rng = np.random.default_rng(42)
    base = rng.normal(0.01, 0.05, size=24)
    mat = np.column_stack([base, base * 1.0001])
    cov = covariance_matrix(mat, alpha=0.05)
    # eigenvalues should all be positive (regularized)
    eigs = np.linalg.eigvalsh(cov)
    assert all(e > 1e-6 for e in eigs)


def test_covariance_alpha_zero_keeps_sample():
    rng = np.random.default_rng(1)
    mat = rng.normal(0.0, 0.05, size=(24, 3))
    cov_sample = np.cov(mat, rowvar=False) * 12
    cov_shrunk = covariance_matrix(mat, alpha=0.0)
    assert np.allclose(cov_shrunk, cov_sample)


# ── Full optimize ────────────────────────────────────────────────────────────


def _setup_3asset_portfolio(db, *, n_months=14):
    """3 assets: 2 STOCK (BR + US) + 1 REIT (BR)."""
    ws, acc = _setup_workspace(db)
    a_br_stock = _add_asset(
        db, ws, acc, name="ItauBR", ticker="ITUB4",
        asset_class=AssetClass.STOCK, country="BR", currency=Currency.BRL,
    )
    a_us_stock = _add_asset(
        db, ws, acc, name="AAPL", ticker="AAPL",
        asset_class=AssetClass.STOCK, country="US", currency=Currency.USD,
    )
    a_reit = _add_asset(
        db, ws, acc, name="XPLOG", ticker="XPLG11",
        asset_class=AssetClass.REIT, country="BR", currency=Currency.BRL,
    )
    rng = np.random.default_rng(7)
    # 3 series with different mean/vol but uncorrelated noise
    s1 = [100.0 * float(np.exp(np.cumsum(rng.normal(0.01, 0.04, n_months))[i])) for i in range(n_months)]
    s2 = [100.0 * float(np.exp(np.cumsum(rng.normal(0.008, 0.05, n_months))[i])) for i in range(n_months)]
    s3 = [100.0 * float(np.exp(np.cumsum(rng.normal(0.005, 0.02, n_months))[i])) for i in range(n_months)]
    _add_snapshots_with_items(db, ws, n_months=n_months, items={
        a_br_stock.id: s1, a_us_stock.id: s2, a_reit.id: s3,
    })
    return ws, [a_br_stock, a_us_stock, a_reit]


def test_optimize_happy_respects_class_targets(db):
    ws, _ = _setup_3asset_portfolio(db, n_months=20)
    inp = MarkowitzInput(
        workspace_id=ws.id,
        class_targets={"STOCK": Decimal("0.7"), "REIT": Decimal("0.3")},
        asset_cap=Decimal("0.5"),  # 2 STOCK × 50% = 100% ≥ 70%
    )
    result = optimize_portfolio(db, inp)
    # 3 eligible assets, no exclusions
    assert result.n_assets == 3
    assert result.n_excluded == 0
    # Total weights sum to 1
    total = sum(o.weight for o in result.optimal)
    assert abs(total - 1.0) < 1e-5
    # STOCK weights sum to 0.7
    stock_w = sum(o.weight for o in result.optimal if o.asset_class == "STOCK")
    assert abs(stock_w - 0.7) < 1e-4
    # REIT weights sum to 0.3
    reit_w = sum(o.weight for o in result.optimal if o.asset_class == "REIT")
    assert abs(reit_w - 0.3) < 1e-4
    # Frontier may have 0+ points (depends on feasibility under tight
    # class+country constraints); the main solution is what matters.
    assert isinstance(result.frontier, list)


def test_optimize_country_cap(db):
    ws, _ = _setup_3asset_portfolio(db, n_months=20)
    inp = MarkowitzInput(
        workspace_id=ws.id,
        class_targets={"STOCK": Decimal("0.7"), "REIT": Decimal("0.3")},
        country_caps={"BR": Decimal("0.5")},  # restritivo
        asset_cap=Decimal("0.7"),  # permitir concentração maior
    )
    result = optimize_portfolio(db, inp)
    br_w = sum(o.weight for o in result.optimal if o.country == "BR")
    assert br_w <= 0.5 + 1e-4


def test_optimize_asset_cap_binding(db):
    ws, assets = _setup_3asset_portfolio(db, n_months=20)
    # STOCK target 70% requires 2 STOCK × cap; minimum cap = 0.35
    inp = MarkowitzInput(
        workspace_id=ws.id,
        class_targets={"STOCK": Decimal("0.7"), "REIT": Decimal("0.3")},
        asset_cap=Decimal("0.40"),  # cada ativo no máximo 40%
    )
    # 2 STOCK × 40% = 80% >= 70% target → feasible
    result = optimize_portfolio(db, inp)
    for o in result.optimal:
        assert o.weight <= 0.40 + 1e-4


# ── Infeasibility ────────────────────────────────────────────────────────────


def test_optimize_targets_dont_sum_to_one_raises(db):
    ws, _ = _setup_3asset_portfolio(db, n_months=20)
    inp = MarkowitzInput(
        workspace_id=ws.id,
        class_targets={"STOCK": Decimal("0.4")},  # incomplete
    )
    with pytest.raises(MarkowitzError, match="1.0"):
        optimize_portfolio(db, inp)


def test_optimize_class_target_no_assets_raises(db):
    ws, _ = _setup_3asset_portfolio(db, n_months=20)
    # STOCK target 30% feasible (2 STOCK × 50% cap), FUND has no assets.
    inp = MarkowitzInput(
        workspace_id=ws.id,
        class_targets={"STOCK": Decimal("0.3"), "REIT": Decimal("0.2"),
                       "FUND": Decimal("0.5")},
        asset_cap=Decimal("0.5"),
    )
    with pytest.raises(MarkowitzError, match="FUND"):
        optimize_portfolio(db, inp)


def test_optimize_class_cap_infeasible_raises(db):
    ws, _ = _setup_3asset_portfolio(db, n_months=20)
    # REIT target 50% but only 1 REIT × cap 15% = 15% < 50%
    inp = MarkowitzInput(
        workspace_id=ws.id,
        class_targets={"STOCK": Decimal("0.5"), "REIT": Decimal("0.5")},
        asset_cap=Decimal("0.15"),
    )
    with pytest.raises(MarkowitzError):
        optimize_portfolio(db, inp)


def test_optimize_no_eligible_assets_raises(db):
    ws, acc = _setup_workspace(db)
    # 1 asset com só 4 meses → excluded; nada elegível
    a = _add_asset(db, ws, acc)
    _add_snapshots_with_items(db, ws, n_months=4, items={a.id: [100.0] * 4})
    inp = MarkowitzInput(
        workspace_id=ws.id,
        class_targets={"STOCK": Decimal("1.0")},
    )
    with pytest.raises(MarkowitzError, match="elegíveis|elegível"):
        optimize_portfolio(db, inp)
