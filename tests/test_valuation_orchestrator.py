"""Spec 61b — Per-class valuation orchestrator tests."""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from numis_geek.models.account import Account, AccountType, Currency
from numis_geek.models.asset import Asset, AssetClass
from numis_geek.models.asset_fundamentals import (
    AssetFundamentals, FundamentalsSource,
)
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.workspace import Workspace
from numis_geek.services.valuation import value_asset


def _setup(db, *, asset_class=AssetClass.STOCK, country="BR",
           currency=Currency.BRL, current_price=Decimal("20")):
    ws = Workspace(name=f"WS-val-{uuid.uuid4().hex[:6]}")
    db.add(ws); db.flush()
    fi = FinancialInstitution(
        id=str(uuid.uuid4()), long_name="FI Test", short_name="FT",
        logo_slug=None, is_active=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(fi); db.flush()
    acc = Account(
        id=str(uuid.uuid4()), workspace_id=ws.id,
        financial_institution_id=fi.id, name="Acc",
        account_type=AccountType.investment, currency=currency,
        opening_balance=Decimal("0"), is_active=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(acc); db.flush()
    asset = Asset(
        id=str(uuid.uuid4()), workspace_id=ws.id, account_id=acc.id,
        asset_class=asset_class, country=country, name="Asset",
        ticker="TICK", currency=currency, current_price=current_price,
        is_active=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(asset); db.flush()
    return ws, asset


def _add_fund(db, asset, *, source=FundamentalsSource.MANUAL, **kwargs):
    f = AssetFundamentals(
        workspace_id=asset.workspace_id, asset_id=asset.id,
        snapshot_date=date.today(), source=source, **kwargs,
    )
    db.add(f); db.flush()
    return f


# ── No-verdict classes ───────────────────────────────────────────────────────


@pytest.mark.parametrize("klass", [
    AssetClass.FUND, AssetClass.CRYPTO, AssetClass.REAL_ESTATE,
    AssetClass.VEHICLE, AssetClass.FGTS, AssetClass.CASH,
    AssetClass.PRIVATE_PENSION, AssetClass.OPTION,
])
def test_class_outside_scope_returns_na(db, klass):
    ws, asset = _setup(db, asset_class=klass)
    res = value_asset(db, asset)
    assert res.verdict == "NA"
    assert "fora do escopo" in res.verdict_reason


def test_stock_without_fundamentals_returns_na(db):
    ws, asset = _setup(db, asset_class=AssetClass.STOCK)
    res = value_asset(db, asset)
    assert res.verdict == "NA"
    assert "Sem fundamentos" in res.verdict_reason


# ── STOCK happy paths ────────────────────────────────────────────────────────


def test_stock_buy_when_cheap_no_gates(db):
    # Bazin = 10 / 0.08 = 125; Graham = √(22.5×4×10) = 30
    # Price 20 < both → BUY
    ws, asset = _setup(db, current_price=Decimal("20"))
    _add_fund(db, asset,
              dps_12m=Decimal("10"), eps=Decimal("4"), bvps=Decimal("10"),
              roe=Decimal("0.15"), debt_ebitda=Decimal("1.5"),
              earnings_growth_5y=Decimal("0.05"),
              dividend_yield_12m=Decimal("0.50"))
    res = value_asset(db, asset)
    assert res.verdict == "BUY"


def test_stock_sell_when_expensive_low_dy(db):
    # Graham=30, price=50 > 30×1.5=45; DY=2% < 8%×0.5=4% → SELL
    ws, asset = _setup(db, current_price=Decimal("50"))
    _add_fund(db, asset,
              dps_12m=Decimal("0.5"), eps=Decimal("4"), bvps=Decimal("10"),
              roe=Decimal("0.10"), debt_ebitda=Decimal("2"),
              earnings_growth_5y=Decimal("0.03"),
              dividend_yield_12m=Decimal("0.02"))
    res = value_asset(db, asset)
    assert res.verdict == "SELL"


def test_stock_hold_when_neutral(db):
    # Bazin = 3/0.08 = 37.5, Graham = 30, Graham×1.2 = 36
    # Price 40 > 36 (cheap_graham=False) and > 37.5 (cheap_bazin=False)
    # but < 30×1.5=45 → not SELL. HOLD.
    ws, asset = _setup(db, current_price=Decimal("40"))
    _add_fund(db, asset,
              dps_12m=Decimal("3"), eps=Decimal("4"), bvps=Decimal("10"),
              roe=Decimal("0.10"), debt_ebitda=Decimal("2"),
              earnings_growth_5y=Decimal("0.05"),
              dividend_yield_12m=Decimal("0.08"))
    res = value_asset(db, asset)
    assert res.verdict == "HOLD"


def test_stock_gate_negative_roe_blocks_buy(db):
    ws, asset = _setup(db, current_price=Decimal("20"))
    _add_fund(db, asset,
              dps_12m=Decimal("10"), eps=Decimal("4"), bvps=Decimal("10"),
              roe=Decimal("-0.05"),  # gate violation
              debt_ebitda=Decimal("1"),
              earnings_growth_5y=Decimal("0.05"))
    res = value_asset(db, asset)
    assert res.verdict == "HOLD"
    assert "ROE negativo" in " ".join(res.disqualifying)


def test_stock_gate_high_debt_blocks_buy(db):
    ws, asset = _setup(db, current_price=Decimal("20"))
    _add_fund(db, asset,
              dps_12m=Decimal("10"), eps=Decimal("4"), bvps=Decimal("10"),
              roe=Decimal("0.10"), debt_ebitda=Decimal("8"),  # > 5
              earnings_growth_5y=Decimal("0.05"))
    res = value_asset(db, asset)
    assert res.verdict == "HOLD"
    assert any("Dívida" in g for g in res.disqualifying)


def test_stock_gate_earnings_decline_blocks_buy(db):
    ws, asset = _setup(db, current_price=Decimal("20"))
    _add_fund(db, asset,
              dps_12m=Decimal("10"), eps=Decimal("4"), bvps=Decimal("10"),
              roe=Decimal("0.10"), debt_ebitda=Decimal("1"),
              earnings_growth_5y=Decimal("-0.05"))  # gate
    res = value_asset(db, asset)
    assert res.verdict == "HOLD"
    assert any("Lucros em queda" in g for g in res.disqualifying)


def test_stock_no_current_price_returns_na(db):
    ws, asset = _setup(db, current_price=None)
    _add_fund(db, asset,
              dps_12m=Decimal("10"), eps=Decimal("4"), bvps=Decimal("10"),
              roe=Decimal("0.10"))
    res = value_asset(db, asset)
    assert res.verdict == "NA"


# ── REIT ─────────────────────────────────────────────────────────────────────


def test_reit_buy_when_cheap_high_dy(db):
    # P/VP=0.85 < 0.95; DY=12% > 8%*1.2=9.6%
    ws, asset = _setup(db, asset_class=AssetClass.REIT, country="BR",
                       current_price=Decimal("100"))
    _add_fund(db, asset,
              p_vp=Decimal("0.85"),
              dividend_yield_12m=Decimal("0.12"),
              vacancy=Decimal("0.05"))
    res = value_asset(db, asset)
    assert res.verdict == "BUY"


def test_reit_sell_when_expensive_low_dy(db):
    ws, asset = _setup(db, asset_class=AssetClass.REIT, country="BR",
                       current_price=Decimal("100"))
    _add_fund(db, asset,
              p_vp=Decimal("1.5"),
              dividend_yield_12m=Decimal("0.04"),
              vacancy=Decimal("0.05"))
    res = value_asset(db, asset)
    assert res.verdict == "SELL"


def test_reit_gate_vacancy_blocks_buy(db):
    ws, asset = _setup(db, asset_class=AssetClass.REIT, country="BR",
                       current_price=Decimal("100"))
    _add_fund(db, asset,
              p_vp=Decimal("0.85"),
              dividend_yield_12m=Decimal("0.12"),
              vacancy=Decimal("0.30"))  # > 20%
    res = value_asset(db, asset)
    assert res.verdict == "HOLD"
    assert any("Vacância" in g for g in res.disqualifying)


def test_reit_us_distribution_coverage_gate(db):
    ws, asset = _setup(db, asset_class=AssetClass.REIT, country="US",
                       currency=Currency.USD,
                       current_price=Decimal("50"))
    _add_fund(db, asset,
              p_vp=Decimal("0.85"),
              dividend_yield_12m=Decimal("0.07"),  # > 5%*1.2=6%
              distribution_coverage=Decimal("0.8"))  # < 1.0 gate
    res = value_asset(db, asset)
    assert res.verdict == "HOLD"


# ── ETF + FIXED_INCOME (NA v1) ───────────────────────────────────────────────


def test_etf_returns_na_with_metrics(db):
    ws, asset = _setup(db, asset_class=AssetClass.ETF,
                       current_price=Decimal("100"))
    _add_fund(db, asset, expense_ratio=Decimal("0.003"),
              aum=Decimal("5000000000"))
    res = value_asset(db, asset)
    assert res.verdict == "NA"
    metric_names = {m.name for m in res.metrics}
    assert "Expense ratio" in metric_names
    assert "AUM" in metric_names


def test_fixed_income_returns_na_with_metrics(db):
    ws, asset = _setup(db, asset_class=AssetClass.FIXED_INCOME,
                       current_price=Decimal("100"))
    _add_fund(db, asset, ytm=Decimal("0.12"), duration=Decimal("4.5"))
    res = value_asset(db, asset)
    assert res.verdict == "NA"
    metric_names = {m.name for m in res.metrics}
    assert "YTM" in metric_names
