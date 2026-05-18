"""Tests for spec 14 — PortfolioSnapshot creation."""
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
from numis_geek.models.portfolio_snapshot import PortfolioSnapshot, PortfolioSnapshotItem
from numis_geek.models.ptax_rate import PTAXRate
from numis_geek.models.workspace import Workspace
from numis_geek.services.snapshot import create_snapshot


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


def _seed_full(db) -> dict:
    now = datetime.now(timezone.utc)
    ws = Workspace(id=str(uuid.uuid4()), name="Snap WS")
    fi = FinancialInstitution(
        id=str(uuid.uuid4()), long_name="XP", short_name="XP", logo_slug="xp",
        is_active=True, created_at=now, updated_at=now,
    )
    acc = Account(
        id=str(uuid.uuid4()), workspace_id=ws.id, financial_institution_id=fi.id,
        name="X", account_type=AccountType.investment, currency=Currency.BRL,
        is_active=True, created_at=now, updated_at=now,
    )
    asset_br = Asset(
        id=str(uuid.uuid4()), workspace_id=ws.id, account_id=acc.id,
        asset_class=AssetClass.STOCK, country="BR", name="Petr", ticker="PETR4",
        currency=Currency.BRL, current_price=Decimal("38.50"),
        is_active=True, created_at=now, updated_at=now,
    )
    asset_us = Asset(
        id=str(uuid.uuid4()), workspace_id=ws.id, account_id=acc.id,
        asset_class=AssetClass.STOCK, country="US", name="Apple", ticker="AAPL",
        currency=Currency.USD, current_price=Decimal("200"),
        is_active=True, created_at=now, updated_at=now,
    )
    db.add_all([ws, fi, acc, asset_br, asset_us])
    db.add_all([
        AssetMovement(
            id=str(uuid.uuid4()), workspace_id=ws.id, asset_id=asset_br.id,
            type=AssetMovementType.BUY, event_date=date(2026, 1, 10),
            quantity=Decimal("100"), unit_price=Decimal("30"),
            gross_amount=Decimal("3000"), net_amount=Decimal("3000"),
            currency=Currency.BRL, fx_rate=Decimal("1"),
            is_active=True, created_at=now, updated_at=now,
        ),
        AssetMovement(
            id=str(uuid.uuid4()), workspace_id=ws.id, asset_id=asset_us.id,
            type=AssetMovementType.BUY, event_date=date(2026, 2, 10),
            quantity=Decimal("10"), unit_price=Decimal("150"),
            gross_amount=Decimal("1500"), net_amount=Decimal("1500"),
            currency=Currency.USD, fx_rate=Decimal("5.0"),
            is_active=True, created_at=now, updated_at=now,
        ),
        PTAXRate(
            id=str(uuid.uuid4()), date=date(2026, 4, 30),
            rate=Decimal("5.10"), source="BCB_SGS", fetched_at=now,
        ),
    ])
    db.flush()
    return {"ws_id": ws.id, "asset_br_id": asset_br.id, "asset_us_id": asset_us.id}


def test_create_snapshot_captures_positions(db):
    world = _seed_full(db)
    result = create_snapshot(db, workspace_id=world["ws_id"], period_end=date(2026, 4, 30))
    assert result.items_count == 2
    assert result.fx_rate_usd_brl == Decimal("5.10")
    # BRL: 100 * 38.50 = 3850. USD: 10 * 200 = 2000 USD = 10200 BRL @ 5.10
    assert result.total_value_brl == Decimal("3850") + Decimal("10200.00")


def test_create_snapshot_replaces_existing(db):
    world = _seed_full(db)
    r1 = create_snapshot(db, workspace_id=world["ws_id"], period_end=date(2026, 4, 30))
    r2 = create_snapshot(db, workspace_id=world["ws_id"], period_end=date(2026, 4, 30))
    assert r1.snapshot_id != r2.snapshot_id
    count = db.query(PortfolioSnapshot).filter(
        PortfolioSnapshot.workspace_id == world["ws_id"]
    ).count()
    assert count == 1


def test_snapshot_skips_zero_quantity_assets(db):
    world = _seed_full(db)
    # Sell all BR
    now = datetime.now(timezone.utc)
    db.add(AssetMovement(
        id=str(uuid.uuid4()), workspace_id=world["ws_id"], asset_id=world["asset_br_id"],
        type=AssetMovementType.SELL, event_date=date(2026, 3, 15),
        quantity=Decimal("100"), unit_price=Decimal("40"),
        gross_amount=Decimal("4000"), net_amount=Decimal("4000"),
        currency=Currency.BRL, fx_rate=Decimal("1"),
        is_active=True, created_at=now, updated_at=now,
    ))
    db.flush()
    result = create_snapshot(db, workspace_id=world["ws_id"], period_end=date(2026, 4, 30))
    assert result.items_count == 1  # Only US asset remains
