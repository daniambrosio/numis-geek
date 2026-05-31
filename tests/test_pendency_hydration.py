"""Unit tests for _hydrate_pendency — FI short_name + previous_unit_price
enrichment of SnapshotPendencyOut. Spec 35 hotfix #2."""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from numis_geek.api.routes.snapshots import (
    _hydrate_pendency,
    _previous_closed_snapshot,
)
from numis_geek.db.base import Base
import numis_geek.models  # noqa: F401
from numis_geek.models.account import Account, AccountType, Currency
from numis_geek.models.asset import Asset, AssetClass, PriceSource
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.portfolio_snapshot import (
    PendencyAction,
    PendencyReason,
    PortfolioSnapshot,
    PortfolioSnapshotItem,
    SnapshotPendency,
    SnapshotSource,
    SnapshotStatus,
)
from numis_geek.models.workspace import Workspace


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


def _world(db, *, with_previous_item: bool = True) -> dict:
    """Workspace + XP FI + 1 MANUAL asset + previous CLOSED snapshot
    (optionally with an item for the asset) + current IN_REVIEW snapshot
    + a MANUAL_SOURCE pendency for the asset."""
    now = datetime.now(timezone.utc)
    ws = Workspace(id=str(uuid.uuid4()), name="Hydration WS")
    fi = FinancialInstitution(
        id=str(uuid.uuid4()), long_name="XP", short_name="XP", logo_slug="xp",
        is_active=True, created_at=now, updated_at=now,
    )
    acc = Account(
        id=str(uuid.uuid4()), workspace_id=ws.id, financial_institution_id=fi.id,
        name="XP", account_type=AccountType.investment, currency=Currency.BRL,
        is_active=True, created_at=now, updated_at=now,
    )
    asset = Asset(
        id=str(uuid.uuid4()), workspace_id=ws.id, account_id=acc.id,
        asset_class=AssetClass.REAL_ESTATE, country="BR",
        name="Casa", ticker=None, currency=Currency.BRL,
        current_price=Decimal("820000"),
        price_source=PriceSource.MANUAL,
        is_active=True, created_at=now, updated_at=now,
    )
    prev_snap = PortfolioSnapshot(
        id=str(uuid.uuid4()), workspace_id=ws.id,
        period_end_date=date(2026, 3, 31),
        total_value_brl=Decimal("0"), total_value_usd=Decimal("0"),
        total_invested_brl=Decimal("0"), total_received_brl=Decimal("0"),
        source=SnapshotSource.MANUAL, status=SnapshotStatus.CLOSED,
        is_active=True, created_at=now, updated_at=now,
    )
    cur_snap = PortfolioSnapshot(
        id=str(uuid.uuid4()), workspace_id=ws.id,
        period_end_date=date(2026, 4, 30),
        total_value_brl=Decimal("0"), total_value_usd=Decimal("0"),
        total_invested_brl=Decimal("0"), total_received_brl=Decimal("0"),
        source=SnapshotSource.MANUAL, status=SnapshotStatus.IN_REVIEW,
        is_active=True, created_at=now, updated_at=now,
    )
    db.add_all([ws, fi, acc, asset, prev_snap, cur_snap])
    if with_previous_item:
        db.add(PortfolioSnapshotItem(
            id=str(uuid.uuid4()),
            snapshot_id=prev_snap.id, asset_id=asset.id,
            quantity=Decimal("1"), unit_price=Decimal("810000.00"),
            market_value_native=Decimal("810000"),
            market_value_brl=Decimal("810000"),
        ))
    pen = SnapshotPendency(
        id=str(uuid.uuid4()), snapshot_id=cur_snap.id, asset_id=asset.id,
        reason=PendencyReason.MANUAL_SOURCE,
        action_type=PendencyAction.EDIT_PRICE,
        created_at=now,
    )
    db.add(pen)
    db.flush()
    return {"cur_snap": cur_snap, "pen": pen}


def test_hydrate_pendency_includes_institution_short_name(db):
    w = _world(db)
    out = _hydrate_pendency(db, w["pen"], snap=w["cur_snap"])
    assert out.asset_institution_short_name == "XP"


def test_hydrate_pendency_includes_previous_unit_price(db):
    w = _world(db)
    out = _hydrate_pendency(db, w["pen"], snap=w["cur_snap"])
    assert out.previous_unit_price is not None
    assert Decimal(out.previous_unit_price) == Decimal("810000.00")
    assert out.previous_period_end == "2026-03-31"


def test_hydrate_pendency_null_price_when_no_previous_item(db):
    # Asset is new — prev CLOSED snapshot exists but has no item for it.
    # FE gates the Repetir button on previous_unit_price; previous_period_end
    # may stay populated (harmless context).
    w = _world(db, with_previous_item=False)
    out = _hydrate_pendency(db, w["pen"], snap=w["cur_snap"])
    assert out.previous_unit_price is None


def test_previous_closed_snapshot_skips_in_review(db):
    """A non-CLOSED snapshot between current and the last CLOSED must be
    ignored — we want the most recent CLOSED, not just the most recent."""
    w = _world(db)
    # Insert an IN_REVIEW snapshot in between.
    now = datetime.now(timezone.utc)
    middle = PortfolioSnapshot(
        id=str(uuid.uuid4()), workspace_id=w["cur_snap"].workspace_id,
        period_end_date=date(2026, 3, 15),
        total_value_brl=Decimal("0"), total_value_usd=Decimal("0"),
        total_invested_brl=Decimal("0"), total_received_brl=Decimal("0"),
        source=SnapshotSource.MANUAL, status=SnapshotStatus.IN_REVIEW,
        is_active=True, created_at=now, updated_at=now,
    )
    db.add(middle)
    db.flush()
    found = _previous_closed_snapshot(db, w["cur_snap"])
    assert found is not None
    assert found.period_end_date == date(2026, 3, 31)
