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
from numis_geek.models.portfolio_snapshot import (
    PortfolioSnapshot, PortfolioSnapshotItem, SnapshotSource, SnapshotStatus,
)
from numis_geek.services.positions import compute_position
from numis_geek.services.snapshot import find_affected_snapshots


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


# ── Spec 51 Bloco 2 — CA × reconciliation ─────────────────────────────────


def _create_snapshot_with_item(db, ws_id: str, asset_id: str, period_end: date,
                               qty: str, unit_price: str, status: SnapshotStatus = SnapshotStatus.CLOSED):
    """Helper minimal — snapshot + item, sem ir pelo create_snapshot service
    (que tem suas próprias regras de pendência)."""
    now = datetime.now(timezone.utc)
    snap = PortfolioSnapshot(
        id=str(uuid.uuid4()), workspace_id=ws_id, period_end_date=period_end,
        source=SnapshotSource.MANUAL, status=status,
        fx_rate_usd_brl=Decimal("5.0"),
        total_value_brl=Decimal("0"), total_value_usd=Decimal("0"),
        total_invested_brl=Decimal("0"), total_received_brl=Decimal("0"),
        is_active=True, created_at=now, updated_at=now,
    )
    db.add(snap)
    db.flush()
    qty_d = Decimal(qty)
    up = Decimal(unit_price)
    db.add(PortfolioSnapshotItem(
        id=str(uuid.uuid4()), snapshot_id=snap.id, asset_id=asset_id,
        quantity=qty_d, unit_price=up,
        market_value_native=qty_d * up,
        market_value_brl=qty_d * up,
        total_invested_brl=qty_d * up,
        created_at=now,
    ))
    db.flush()
    return snap


def test_split_affects_all_snapshots_after_event_date(db):
    """Adicionar SPLIT 10:1 com event_date=jun/24 deve aparecer em
    snapshots de jun, jul, ago (todos com qty inflada pra 1000)."""
    world = _seed(db)
    # Snapshots já fechados com qty=100 (sem o split).
    _create_snapshot_with_item(
        db, world["ws_id"], world["asset_id"], date(2024, 6, 30),
        qty="100", unit_price="30",
    )
    _create_snapshot_with_item(
        db, world["ws_id"], world["asset_id"], date(2024, 7, 31),
        qty="100", unit_price="32",
    )
    _create_snapshot_with_item(
        db, world["ws_id"], world["asset_id"], date(2024, 8, 31),
        qty="100", unit_price="34",
    )
    # Adiciona SPLIT 10:1 em jun/24.
    db.add(CorporateAction(
        id=str(uuid.uuid4()), workspace_id=world["ws_id"], asset_id=world["asset_id"],
        event_date=date(2024, 6, 1), event_type=CorporateActionType.SPLIT,
        ratio=Decimal("10"), is_active=True,
        created_at=world["now"], updated_at=world["now"],
    ))
    db.flush()
    affected = find_affected_snapshots(
        db, workspace_id=world["ws_id"], asset_id=world["asset_id"],
        earliest_event_date=date(2024, 6, 1),
    )
    yms = sorted(a.ym for a in affected)
    assert yms == ["2024-06", "2024-07", "2024-08"]
    for a in affected:
        assert a.old_quantity == Decimal("100")
        assert a.new_quantity == Decimal("1000")


def test_split_before_oldest_snapshot_still_picked_up(db):
    """SPLIT muito antigo só afeta snapshots a partir da event_date.
    Não deve regredir."""
    world = _seed(db)
    # Snapshot em maio/24 — anterior ao split de jun/24.
    _create_snapshot_with_item(
        db, world["ws_id"], world["asset_id"], date(2024, 5, 31),
        qty="100", unit_price="30",
    )
    _create_snapshot_with_item(
        db, world["ws_id"], world["asset_id"], date(2024, 6, 30),
        qty="100", unit_price="30",
    )
    db.add(CorporateAction(
        id=str(uuid.uuid4()), workspace_id=world["ws_id"], asset_id=world["asset_id"],
        event_date=date(2024, 6, 1), event_type=CorporateActionType.SPLIT,
        ratio=Decimal("10"), is_active=True,
        created_at=world["now"], updated_at=world["now"],
    ))
    db.flush()
    affected = find_affected_snapshots(
        db, workspace_id=world["ws_id"], asset_id=world["asset_id"],
        earliest_event_date=date(2024, 6, 1),
    )
    yms = sorted(a.ym for a in affected)
    # Maio/24 fica de fora — anterior ao event_date.
    assert yms == ["2024-06"]


def test_asset_conversion_source_drops_qty_to_zero(db):
    """ASSET_CONVERSION zera qty no ativo origem nos snapshots ≥
    event_date."""
    world = _seed(db)
    target = Asset(
        id=str(uuid.uuid4()), workspace_id=world["ws_id"],
        account_id=db.query(Account).first().id,
        asset_class=AssetClass.STOCK, country="BR", name="NewCo", ticker="NEWC4",
        currency=Currency.BRL, is_active=True,
        created_at=world["now"], updated_at=world["now"],
    )
    db.add(target)
    db.flush()
    _create_snapshot_with_item(
        db, world["ws_id"], world["asset_id"], date(2024, 7, 31),
        qty="100", unit_price="30",
    )
    db.add(CorporateAction(
        id=str(uuid.uuid4()), workspace_id=world["ws_id"], asset_id=world["asset_id"],
        event_date=date(2024, 6, 1), event_type=CorporateActionType.ASSET_CONVERSION,
        ratio=Decimal("1"), target_asset_id=target.id, target_ratio=Decimal("0.5"),
        is_active=True, created_at=world["now"], updated_at=world["now"],
    ))
    db.flush()
    affected = find_affected_snapshots(
        db, workspace_id=world["ws_id"], asset_id=world["asset_id"],
        earliest_event_date=date(2024, 6, 1),
    )
    assert len(affected) == 1
    a = affected[0]
    assert a.old_quantity == Decimal("100")
    assert a.new_quantity == Decimal("0")
