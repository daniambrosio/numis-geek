"""Tests for spec 13 — CorporateAction effect on positions."""
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
from numis_geek.models.corporate_action import CorporateAction, CorporateActionType
from numis_geek.models.financial_institution import FinancialInstitution
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
def db():
    s = TestSession()
    yield s
    s.rollback()
    s.close()


def _seed(db) -> dict:
    now = datetime.now(timezone.utc)
    ws = Workspace(id=str(uuid.uuid4()), name="CA WS")
    fi = FinancialInstitution(
        id=str(uuid.uuid4()), long_name="XP", short_name="XP", logo_slug="xp",
        is_active=True, created_at=now, updated_at=now,
    )
    acc = Account(
        id=str(uuid.uuid4()), workspace_id=ws.id, financial_institution_id=fi.id,
        name="X", account_type=AccountType.investment, currency=Currency.BRL,
        is_active=True, created_at=now, updated_at=now,
    )
    asset = Asset(
        id=str(uuid.uuid4()), workspace_id=ws.id, account_id=acc.id,
        asset_class=AssetClass.STOCK, country="BR", name="X", ticker="XPTO3",
        currency=Currency.BRL, is_active=True, created_at=now, updated_at=now,
    )
    db.add_all([ws, fi, acc, asset])
    # Buy 100 @ 30 on 2024-01-10
    db.add(AssetMovement(
        id=str(uuid.uuid4()), workspace_id=ws.id, asset_id=asset.id,
        type=AssetMovementType.BUY, event_date=date(2024, 1, 10),
        quantity=Decimal("100"), unit_price=Decimal("30"),
        gross_amount=Decimal("3000"), net_amount=Decimal("3000"),
        currency=Currency.BRL, fx_rate=Decimal("1"),
        is_active=True, created_at=now, updated_at=now,
    ))
    db.flush()
    return {"ws_id": ws.id, "asset_id": asset.id, "now": now}


def test_split_scales_quantity_and_unit_price(db):
    world = _seed(db)
    # 1:10 split on 2024-06-01
    db.add(CorporateAction(
        id=str(uuid.uuid4()), workspace_id=world["ws_id"], asset_id=world["asset_id"],
        event_date=date(2024, 6, 1), event_type=CorporateActionType.SPLIT,
        ratio=Decimal("10"), is_active=True,
        created_at=world["now"], updated_at=world["now"],
    ))
    db.flush()
    pos = compute_position(db, world["asset_id"], as_of=date(2024, 12, 31))
    assert pos["quantity_held"] == Decimal("1000")
    # avg cost drops from 30 to 3 (cost basis preserved)
    assert pos["average_cost"] == Decimal("3")


def test_grouping_reduces_quantity_raises_price(db):
    world = _seed(db)
    # 10:1 grouping (inplit) on 2024-06-01 → ratio = 0.1
    db.add(CorporateAction(
        id=str(uuid.uuid4()), workspace_id=world["ws_id"], asset_id=world["asset_id"],
        event_date=date(2024, 6, 1), event_type=CorporateActionType.GROUPING,
        ratio=Decimal("0.1"), is_active=True,
        created_at=world["now"], updated_at=world["now"],
    ))
    db.flush()
    pos = compute_position(db, world["asset_id"], as_of=date(2024, 12, 31))
    assert pos["quantity_held"] == Decimal("10")
    assert pos["average_cost"] == Decimal("300")


def test_inactive_corporate_action_ignored(db):
    world = _seed(db)
    db.add(CorporateAction(
        id=str(uuid.uuid4()), workspace_id=world["ws_id"], asset_id=world["asset_id"],
        event_date=date(2024, 6, 1), event_type=CorporateActionType.SPLIT,
        ratio=Decimal("10"), is_active=False,
        created_at=world["now"], updated_at=world["now"],
    ))
    db.flush()
    pos = compute_position(db, world["asset_id"], as_of=date(2024, 12, 31))
    assert pos["quantity_held"] == Decimal("100")
    assert pos["average_cost"] == Decimal("30")


def test_asset_conversion_closes_position(db):
    world = _seed(db)
    target = Asset(
        id=str(uuid.uuid4()), workspace_id=world["ws_id"],
        account_id=db.query(Account).first().id,
        asset_class=AssetClass.STOCK, country="BR", name="NewCo", ticker="NEWC3",
        currency=Currency.BRL, is_active=True,
        created_at=world["now"], updated_at=world["now"],
    )
    db.add(target)
    db.flush()
    db.add(CorporateAction(
        id=str(uuid.uuid4()), workspace_id=world["ws_id"], asset_id=world["asset_id"],
        event_date=date(2024, 6, 1), event_type=CorporateActionType.ASSET_CONVERSION,
        ratio=Decimal("1"), target_asset_id=target.id, target_ratio=Decimal("0.5"),
        is_active=True, created_at=world["now"], updated_at=world["now"],
    ))
    db.flush()
    pos = compute_position(db, world["asset_id"], as_of=date(2024, 12, 31))
    assert pos["quantity_held"] == Decimal("0")
