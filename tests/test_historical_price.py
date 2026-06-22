"""Cobertura do services/historical_price.py — fonte hierárquica + walkback."""
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
from numis_geek.models.asset import Asset, AssetClass, PriceSource
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.integration_credential import (
    CredentialTestResult, IntegrationCredential, IntegrationProvider,
)
from numis_geek.models.portfolio_snapshot import (
    PortfolioSnapshot, PortfolioSnapshotItem, SnapshotStatus,
)
from numis_geek.models.workspace import Workspace
from numis_geek.services import historical_price as hp_module
from numis_geek.services.historical_price import (
    HistoricalPriceNotFound, fetch_price_on,
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


def _world(db) -> dict:
    now = datetime.now(timezone.utc)
    ws = Workspace(id=str(uuid.uuid4()), name=f"WS-{uuid.uuid4().hex[:6]}")
    fi = FinancialInstitution(
        id=str(uuid.uuid4()), long_name="XP", short_name="XP", logo_slug="xp",
        is_active=True, created_at=now, updated_at=now,
    )
    acc = Account(
        id=str(uuid.uuid4()), workspace_id=ws.id, financial_institution_id=fi.id,
        name="acc", account_type=AccountType.investment, currency=Currency.BRL,
        is_active=True, created_at=now, updated_at=now,
    )
    db.add_all([ws, fi, acc])
    db.flush()
    return {"ws": ws, "fi": fi, "acc": acc, "now": now}


def _brapi_asset(db, w, *, ticker="ITUB4", current_price=None, updated_at=None):
    a = Asset(
        id=str(uuid.uuid4()), workspace_id=w["ws"].id, account_id=w["acc"].id,
        asset_class=AssetClass.STOCK, country="BR",
        name=ticker, ticker=ticker, currency=Currency.BRL,
        price_source=PriceSource.BRAPI,
        current_price=current_price,
        price_updated_at=updated_at,
        is_active=True, created_at=w["now"], updated_at=w["now"],
    )
    db.add(a)
    db.flush()
    return a


def _seed_brapi_token(db):
    now = datetime.now(timezone.utc)
    cred = IntegrationCredential(
        id=str(uuid.uuid4()),
        provider=IntegrationProvider.BRAPI,
        key_name="default", secret_value="testtok",
        is_active=True,
        last_tested_at=None, last_test_result=CredentialTestResult.UNTESTED,
        last_test_message=None,
        created_at=now, updated_at=now,
    )
    db.add(cred)
    db.flush()


def test_current_price_wins_when_updated_today(db):
    w = _world(db)
    # price_updated_at = mesmo dia da target_date
    asset = _brapi_asset(
        db, w, current_price=Decimal("42.00"),
        updated_at=datetime(2026, 6, 19, 18, 0, tzinfo=timezone.utc),
    )
    hp = fetch_price_on(db, asset, date(2026, 6, 19))
    assert hp.source == "current_price"
    assert hp.price == Decimal("42.00")
    assert hp.effective_date == date(2026, 6, 19)


def test_brapi_history_walkback_skips_weekend(db, monkeypatch):
    """Vencimento numa segunda. BRAPI só tem fechamento na sexta anterior."""
    from numis_geek.integrations.brapi import BrapiHistoryPoint
    w = _world(db)
    _seed_brapi_token(db)
    asset = _brapi_asset(db, w)
    points = [
        BrapiHistoryPoint(date=date(2026, 6, 12), close=Decimal("39.00")),  # sex
        BrapiHistoryPoint(date=date(2026, 6, 18), close=Decimal("41.00")),  # qui
        BrapiHistoryPoint(date=date(2026, 6, 19), close=Decimal("39.87")),  # sex
    ]
    monkeypatch.setattr(hp_module, "brapi_history", lambda *a, **kw: points)
    # Target em uma segunda (22/06) — BRAPI não tem; walkback pega sex 19/06.
    hp = fetch_price_on(db, asset, date(2026, 6, 22))
    assert hp.source == "brapi"
    assert hp.price == Decimal("39.87")
    assert hp.effective_date == date(2026, 6, 19)


def test_brapi_history_returns_exact_date_when_available(db, monkeypatch):
    from numis_geek.integrations.brapi import BrapiHistoryPoint
    w = _world(db)
    _seed_brapi_token(db)
    asset = _brapi_asset(db, w)
    points = [BrapiHistoryPoint(date=date(2026, 6, 19), close=Decimal("39.87"))]
    monkeypatch.setattr(hp_module, "brapi_history", lambda *a, **kw: points)
    hp = fetch_price_on(db, asset, date(2026, 6, 19))
    assert hp.source == "brapi"
    assert hp.price == Decimal("39.87")
    assert hp.effective_date == date(2026, 6, 19)


def test_snapshot_fallback_when_brapi_unavailable(db, monkeypatch):
    """Sem BRAPI mas com PortfolioSnapshotItem no dia exato."""
    w = _world(db)
    asset = _brapi_asset(db, w)
    # snapshot fechado em 19/06 com unit_price 39.87 pra esse asset
    snap = PortfolioSnapshot(
        id=str(uuid.uuid4()),
        workspace_id=w["ws"].id,
        period_end_date=date(2026, 6, 19),
        status=SnapshotStatus.CLOSED,
        total_invested_brl=Decimal("0"),
        total_received_brl=Decimal("0"),
        total_value_brl=Decimal("0"),
        created_at=w["now"], updated_at=w["now"],
    )
    item = PortfolioSnapshotItem(
        id=str(uuid.uuid4()),
        snapshot_id=snap.id, asset_id=asset.id,
        quantity=Decimal("100"),
        unit_price=Decimal("39.87"),
        market_value_brl=Decimal("3987"),
        average_cost_brl=Decimal("35"),
        total_invested_brl=Decimal("3500"),
        created_at=w["now"], updated_at=w["now"],
    )
    db.add_all([snap, item])
    db.flush()
    # Sem token BRAPI nesse worker → _try_brapi devolve None
    hp = fetch_price_on(db, asset, date(2026, 6, 19))
    assert hp.source == "snapshot"
    assert hp.price == Decimal("39.87")
    assert hp.effective_date == date(2026, 6, 19)


def test_raises_when_no_source_resolves(db):
    """current_price stale + sem BRAPI + sem snapshot → raise."""
    w = _world(db)
    asset = _brapi_asset(db, w)  # sem current_price, sem token, sem snapshot
    with pytest.raises(HistoricalPriceNotFound):
        fetch_price_on(db, asset, date(2026, 6, 19))


def test_current_price_skipped_when_updated_on_different_day(db):
    """price_updated_at != target_date → ignora current_price (evita decisão errada)."""
    w = _world(db)
    asset = _brapi_asset(
        db, w, current_price=Decimal("45.00"),
        updated_at=datetime(2026, 6, 22, 18, 0, tzinfo=timezone.utc),
    )
    with pytest.raises(HistoricalPriceNotFound):
        fetch_price_on(db, asset, date(2026, 6, 19))
