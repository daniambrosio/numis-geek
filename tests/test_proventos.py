"""Spec 29 — tests for proventos aggregation + DY regression fence."""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from numis_geek.db.base import Base
import numis_geek.models  # noqa: F401
from numis_geek.models.account import Account, AccountType, Currency
from numis_geek.models.asset import Asset, AssetClass, OptionType, PriceSource
from numis_geek.models.asset_movement import AssetMovement, AssetMovementType
from numis_geek.models.distribution import Distribution, DistributionType
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.ptax_rate import PTAXRate
from numis_geek.models.workspace import Workspace
from numis_geek.services.proventos import (
    aggregate_proventos,
    dy_eligible_amount_brl,
    list_proventos,
    period_range,
)


TEST_ENGINE = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(bind=TEST_ENGINE, autoflush=False, autocommit=False)


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    Base.metadata.create_all(TEST_ENGINE)
    yield
    Base.metadata.drop_all(TEST_ENGINE)


@pytest.fixture
def db():
    s = TestSession()
    yield s
    s.rollback()
    s.close()


# ── period_range ────────────────────────────────────────────────────────────


def test_period_range_12m_walks_back_11_months():
    fd, td = period_range("12m", today=date(2026, 5, 24))
    assert fd == date(2025, 6, 1)
    assert td == date(2026, 5, 24)


def test_period_range_24m_walks_back_23_months():
    fd, td = period_range("24m", today=date(2026, 5, 24))
    assert fd == date(2024, 6, 1)


def test_period_range_ytd_starts_on_january_first():
    fd, td = period_range("ytd", today=date(2026, 5, 24))
    assert fd == date(2026, 1, 1)
    assert td == date(2026, 5, 24)


def test_period_range_handles_year_boundary():
    fd, _ = period_range("12m", today=date(2026, 1, 15))
    assert fd == date(2025, 2, 1)


# ── Seed fixtures ───────────────────────────────────────────────────────────


def _seed(db) -> dict:
    now = datetime.now(timezone.utc)
    ws = Workspace(id=str(uuid.uuid4()), name="Proventos WS")
    fi_br = FinancialInstitution(
        id=str(uuid.uuid4()), long_name="XP", short_name="XP", logo_slug="xp",
        country="BR", is_active=True, created_at=now, updated_at=now,
    )
    fi_us = FinancialInstitution(
        id=str(uuid.uuid4()), long_name="Avenue", short_name="Avenue", logo_slug="avenue",
        country="US", is_active=True, created_at=now, updated_at=now,
    )
    acc_br = Account(
        id=str(uuid.uuid4()), workspace_id=ws.id, financial_institution_id=fi_br.id,
        name="XP", account_type=AccountType.investment, currency=Currency.BRL,
        is_active=True, created_at=now, updated_at=now,
    )
    acc_us = Account(
        id=str(uuid.uuid4()), workspace_id=ws.id, financial_institution_id=fi_us.id,
        name="Avenue", account_type=AccountType.investment, currency=Currency.USD,
        is_active=True, created_at=now, updated_at=now,
    )
    petr = Asset(
        id=str(uuid.uuid4()), workspace_id=ws.id, account_id=acc_br.id,
        asset_class=AssetClass.STOCK, country="BR", name="Petrobras", ticker="PETR4",
        currency=Currency.BRL, price_source=PriceSource.BRAPI,
        is_active=True, created_at=now, updated_at=now,
    )
    aapl = Asset(
        id=str(uuid.uuid4()), workspace_id=ws.id, account_id=acc_us.id,
        asset_class=AssetClass.STOCK, country="US", name="Apple", ticker="AAPL",
        currency=Currency.USD, price_source=PriceSource.FINNHUB,
        is_active=True, created_at=now, updated_at=now,
    )
    # An OPTION on PETR4 (PUT) with a related SELL_OPEN
    petr_put = Asset(
        id=str(uuid.uuid4()), workspace_id=ws.id, account_id=acc_br.id,
        asset_class=AssetClass.OPTION, country="BR", name="PETR4 PUT",
        ticker="PETRR300", currency=Currency.BRL, price_source=PriceSource.MANUAL,
        underlying_id=petr.id, option_type=OptionType.PUT,
        strike_price=Decimal("30"), expiration_date=date(2026, 6, 19),
        contract_size=100,
        is_active=True, created_at=now, updated_at=now,
    )

    # Distributions: PETR4 dividend 100 BRL in 2026-04; AAPL dividend 10 USD
    # in 2026-04 (fx_rate=5.0); SECURITIES_LENDING 5 BRL with no asset.
    db.add_all([ws, fi_br, fi_us, acc_br, acc_us, petr, aapl, petr_put])

    db.add(Distribution(
        id=str(uuid.uuid4()), workspace_id=ws.id,
        financial_institution_id=fi_br.id, asset_id=petr.id,
        type=DistributionType.DIVIDEND, event_date=date(2026, 4, 15),
        gross_amount=Decimal("100"), net_amount=Decimal("100"),
        currency=Currency.BRL, fx_rate=Decimal("1"),
        is_active=True, created_at=now, updated_at=now,
    ))
    db.add(Distribution(
        id=str(uuid.uuid4()), workspace_id=ws.id,
        financial_institution_id=fi_us.id, asset_id=aapl.id,
        type=DistributionType.DIVIDEND, event_date=date(2026, 4, 20),
        gross_amount=Decimal("10"), net_amount=Decimal("10"),
        currency=Currency.USD, fx_rate=Decimal("5.0"),
        is_active=True, created_at=now, updated_at=now,
    ))
    db.add(Distribution(
        id=str(uuid.uuid4()), workspace_id=ws.id,
        financial_institution_id=fi_us.id, asset_id=None,  # genérico
        type=DistributionType.SECURITIES_LENDING, event_date=date(2026, 4, 25),
        gross_amount=Decimal("5"), net_amount=Decimal("5"),
        currency=Currency.BRL, fx_rate=Decimal("1"),
        is_active=True, created_at=now, updated_at=now,
    ))

    # Synthetic OPTION_PREMIUM source — a SELL_OPEN movement on petr_put
    db.add(AssetMovement(
        id=str(uuid.uuid4()), workspace_id=ws.id, asset_id=petr_put.id,
        type=AssetMovementType.SELL_OPEN, event_date=date(2026, 4, 10),
        quantity=Decimal("100"), unit_price=Decimal("1.50"),
        gross_amount=Decimal("150"), fee=Decimal("0"),
        net_amount=Decimal("150"),
        currency=Currency.BRL, fx_rate=Decimal("1"),
        is_active=True, created_at=now, updated_at=now,
    ))

    # PTAX for BRL→USD conversion of 2026-04 (and a couple neighbors)
    db.add(PTAXRate(
        id=str(uuid.uuid4()), date=date(2026, 4, 30),
        rate=Decimal("5.0"), source="BCB_SGS", fetched_at=now,
    ))

    db.flush()
    return {
        "ws_id": ws.id, "petr_id": petr.id, "aapl_id": aapl.id,
        "petr_put_id": petr_put.id, "fi_br_id": fi_br.id, "fi_us_id": fi_us.id,
    }


# ── list_proventos: derived fields ──────────────────────────────────────────


def test_list_proventos_populates_klass_country_ym(db):
    w = _seed(db)
    rows = list_proventos(db, w["ws_id"])
    by_type = {r.type: r for r in rows}
    assert by_type["DIVIDEND"].klass in ("STOCK",)
    assert by_type["DIVIDEND"].ym  # "YYYY-MM"
    # Securities lending without asset → GENERIC klass, country None
    sl = [r for r in rows if r.type == "SECURITIES_LENDING"][0]
    assert sl.klass == "GENERIC"
    assert sl.country is None
    # OPTION_PREMIUM rolls up to the underlying's STOCK klass + BR country
    op = [r for r in rows if r.type == "OPTION_PREMIUM"][0]
    assert op.klass == "STOCK"
    assert op.country == "BR"


# ── aggregate_proventos: breakdown × currency × include_synthetic ──────────


def test_aggregate_by_type_brl_includes_synthetic(db):
    w = _seed(db)
    data = aggregate_proventos(
        db, w["ws_id"], period="12m", breakdown="type", currency="BRL",
        include_synthetic=True, today=date(2026, 5, 24),
    )
    # 12 buckets (Jun/25 → May/26 inclusive)
    assert len(data.rows) == 12
    # Legend always has all 5 types in fixed order
    legend_keys = [s.key for s in data.legend]
    assert legend_keys == ["DIVIDEND", "INTEREST", "JCP", "SECURITIES_LENDING", "OPTION_PREMIUM"]
    # April 2026 totals: 100 BRL + 50 USD*5=50 BRL + 5 BRL + 150 OPTION_PREMIUM
    apr = next(r for r in data.rows if r.ym == "2026-04")
    assert apr.total == Decimal("305")  # 100 + 50 + 5 + 150


def test_aggregate_legend_keeps_option_premium_when_synthetic_off(db):
    w = _seed(db)
    data = aggregate_proventos(
        db, w["ws_id"], period="12m", breakdown="type", currency="BRL",
        include_synthetic=False, today=date(2026, 5, 24),
    )
    legend_keys = [s.key for s in data.legend]
    assert "OPTION_PREMIUM" in legend_keys
    # No OPTION_PREMIUM segments anywhere
    for r in data.rows:
        assert all(s.key != "OPTION_PREMIUM" for s in r.segments)
    # April total drops by 150
    apr = next(r for r in data.rows if r.ym == "2026-04")
    assert apr.total == Decimal("155")  # 100 + 50 + 5


def test_aggregate_by_klass_rolls_option_premium_into_underlying(db):
    w = _seed(db)
    data = aggregate_proventos(
        db, w["ws_id"], period="12m", breakdown="klass", currency="BRL",
        include_synthetic=True, today=date(2026, 5, 24),
    )
    apr = next(r for r in data.rows if r.ym == "2026-04")
    by_key = {s.key: s.value for s in apr.segments}
    # PETR4 (STOCK BR) dividend 100 + AAPL (STOCK US) dividend 50 BRL +
    # OPTION_PREMIUM on PETR4 underlying (STOCK) 150 → STOCK = 300
    assert by_key.get("STOCK") == Decimal("300")
    assert by_key.get("GENERIC") == Decimal("5")  # SL row without asset


def test_aggregate_in_usd_converts_brl_via_ptax_month(db):
    w = _seed(db)
    data = aggregate_proventos(
        db, w["ws_id"], period="12m", breakdown="total", currency="USD",
        include_synthetic=True, today=date(2026, 5, 24),
    )
    apr = next(r for r in data.rows if r.ym == "2026-04")
    # BRL events in April: 100 + 5 + 150 = 255 BRL → /5.0 = 51 USD
    # USD event: 10 USD (already USD)
    # Total: 61 USD
    assert apr.total == Decimal("61")


def test_aggregate_period_24m_returns_24_buckets(db):
    w = _seed(db)
    data = aggregate_proventos(
        db, w["ws_id"], period="24m", breakdown="total",
        today=date(2026, 5, 24),
    )
    assert len(data.rows) == 24


def test_aggregate_totals_sum_avg_max(db):
    w = _seed(db)
    data = aggregate_proventos(
        db, w["ws_id"], period="12m", breakdown="total", currency="BRL",
        include_synthetic=True, today=date(2026, 5, 24),
    )
    # Only April has values: 100 + 50 + 5 + 150 = 305
    assert data.totals.sum == Decimal("305")
    assert data.totals.max == Decimal("305")
    # monthly_avg = 305 / 12 buckets
    assert data.totals.monthly_avg == Decimal("305") / Decimal("12")


# ── Regression: DY exclusion preserved ──────────────────────────────────────


def test_dy_eligible_amount_brl_excludes_option_premium(db):
    """OPTION_PREMIUM rows are synthetic (not DistributionType rows), so
    dy_eligible_amount_brl must not pick them up even after the spec 29
    refactor."""
    w = _seed(db)
    # Sum DY-eligible for PETR4 — should be exactly the 100 BRL dividend.
    total = dy_eligible_amount_brl(db, w["petr_id"], days=365)
    assert total == Decimal("100")
