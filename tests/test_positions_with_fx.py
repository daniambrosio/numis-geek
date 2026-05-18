"""Tests positions service uses PTAX for USD assets (spec 11)."""
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
from numis_geek.models.asset import Asset, AssetClass
from numis_geek.models.asset_movement import AssetMovement, AssetMovementType
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.ptax_rate import PTAXRate
from numis_geek.models.workspace import Workspace
from numis_geek.services.positions import compute_position


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
def db_session():
    s = TestSession()
    yield s
    s.rollback()
    s.close()


def _seed_usd_asset(db, with_ptax: bool = True) -> str:
    now = datetime.now(timezone.utc)
    ws = Workspace(id=str(uuid.uuid4()), name="FX WS")
    fi = FinancialInstitution(
        id=str(uuid.uuid4()),
        long_name="Avenue", short_name="Avenue", logo_slug="avenue",
        is_active=True, created_at=now, updated_at=now,
    )
    acc = Account(
        id=str(uuid.uuid4()), workspace_id=ws.id, financial_institution_id=fi.id,
        name="Avenue inv", account_type=AccountType.investment, currency=Currency.USD,
        is_active=True, created_at=now, updated_at=now,
    )
    asset = Asset(
        id=str(uuid.uuid4()), workspace_id=ws.id, account_id=acc.id,
        asset_class=AssetClass.STOCK, country="US", name="Apple", ticker="AAPL",
        currency=Currency.USD, current_price=Decimal("200.00"),
        is_active=True, created_at=now, updated_at=now,
    )
    db.add_all([ws, fi, acc, asset])
    db.flush()
    # 10 shares @ 150
    db.add(AssetMovement(
        id=str(uuid.uuid4()),
        workspace_id=ws.id, asset_id=asset.id,
        type=AssetMovementType.BUY,
        event_date=date(2026, 5, 14),
        quantity=Decimal("10"), unit_price=Decimal("150.00"),
        gross_amount=Decimal("1500.00"), net_amount=Decimal("1500.00"),
        currency=Currency.USD, fx_rate=Decimal("5.0"),
        is_active=True, created_at=now, updated_at=now,
    ))
    if with_ptax:
        db.add(PTAXRate(
            id=str(uuid.uuid4()), date=date(2026, 5, 18),
            rate=Decimal("5.10"), source="BCB_SGS", fetched_at=now,
        ))
    db.flush()
    return asset.id


def test_usd_position_converts_to_brl_using_ptax(db_session):
    asset_id = _seed_usd_asset(db_session, with_ptax=True)
    pos = compute_position(db_session, asset_id, as_of=date(2026, 5, 18))
    assert pos["currency"] == "USD"
    assert pos["current_value"] == Decimal("2000.00")
    assert pos["current_value_brl"] == Decimal("10200.000")


def test_usd_position_brl_none_when_no_ptax(db_session):
    asset_id = _seed_usd_asset(db_session, with_ptax=False)
    pos = compute_position(db_session, asset_id, as_of=date(2026, 5, 18))
    assert pos["current_value"] == Decimal("2000.00")
    assert pos["current_value_brl"] is None
