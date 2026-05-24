"""Spec 20 — portfolio summary tests."""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import bcrypt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from numis_geek.api.app import app
from numis_geek.api.deps import get_db
from numis_geek.db.base import Base
import numis_geek.models  # noqa: F401
from numis_geek.models.account import Account, AccountType, Currency
from numis_geek.models.asset import Asset, AssetClass
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.portfolio_snapshot import (
    PortfolioSnapshot,
    PortfolioSnapshotItem,
    SnapshotSource,
)
from numis_geek.models.user import User, UserRole
from numis_geek.services.auth import AuthService
from numis_geek.services.portfolio_summary import compute_portfolio_summary
from numis_geek.services.user import UserService
from numis_geek.services.workspace import WorkspaceService


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


def override_get_db():
    db = TestSession()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@pytest.fixture(scope="module")
def client():
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(scope="module")
def seed():
    db = TestSession()
    ws = WorkspaceService(db).create("Portfolio Test WS")
    admin = UserService(db).create(ws.id, "pf_admin@test.com", "adminpass", UserRole.admin)

    now = datetime.now(timezone.utc)
    sysadmin = User(
        id=str(uuid.uuid4()),
        workspace_id=None,
        email="pf_sysadmin@test.internal",
        name="SysAdmin",
        password_hash=bcrypt.hashpw(b"syspass", bcrypt.gensalt()).decode(),
        role=UserRole.sysadmin,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(sysadmin)

    # 2 FIs (BR + US), 2 investment accounts, 3 assets.
    fi_xp = FinancialInstitution(
        id=str(uuid.uuid4()),
        long_name="XP", short_name="XP", logo_slug="xp",
        country="BR", is_active=True, created_at=now, updated_at=now,
    )
    fi_av = FinancialInstitution(
        id=str(uuid.uuid4()),
        long_name="Avenue", short_name="Avenue", logo_slug="avenue",
        country="US", is_active=True, created_at=now, updated_at=now,
    )
    db.add_all([fi_xp, fi_av])
    db.flush()

    acc_xp = Account(
        id=str(uuid.uuid4()), workspace_id=ws.id,
        financial_institution_id=fi_xp.id, name="XP Inv",
        account_type=AccountType.investment, currency=Currency.BRL,
        opening_balance=Decimal("0"), is_active=True,
        created_at=now, updated_at=now,
    )
    acc_av = Account(
        id=str(uuid.uuid4()), workspace_id=ws.id,
        financial_institution_id=fi_av.id, name="Avenue Inv",
        account_type=AccountType.investment, currency=Currency.USD,
        opening_balance=Decimal("0"), is_active=True,
        created_at=now, updated_at=now,
    )
    db.add_all([acc_xp, acc_av])
    db.flush()

    petr = Asset(
        id=str(uuid.uuid4()), workspace_id=ws.id, account_id=acc_xp.id,
        asset_class=AssetClass.STOCK, country="BR", name="PETR4", ticker="PETR4",
        currency=Currency.BRL, is_active=True, created_at=now, updated_at=now,
    )
    itub = Asset(
        id=str(uuid.uuid4()), workspace_id=ws.id, account_id=acc_xp.id,
        asset_class=AssetClass.STOCK, country="BR", name="ITUB4", ticker="ITUB4",
        currency=Currency.BRL, is_active=True, created_at=now, updated_at=now,
    )
    aapl = Asset(
        id=str(uuid.uuid4()), workspace_id=ws.id, account_id=acc_av.id,
        asset_class=AssetClass.STOCK, country="US", name="Apple", ticker="AAPL",
        currency=Currency.USD, is_active=True, created_at=now, updated_at=now,
    )
    db.add_all([petr, itub, aapl])
    db.flush()

    # Two snapshots — Mar + Apr.
    snap_mar = PortfolioSnapshot(
        id=str(uuid.uuid4()), workspace_id=ws.id,
        period_end_date=date(2026, 3, 31),
        fx_rate_usd_brl=Decimal("5.10"),
        total_value_brl=Decimal("100000.00"), total_value_usd=Decimal("19607.84"),
        total_invested_brl=Decimal("80000.00"), total_received_brl=Decimal("2000.00"),
        source=SnapshotSource.MANUAL, is_active=True,
        created_at=now, updated_at=now,
    )
    snap_apr = PortfolioSnapshot(
        id=str(uuid.uuid4()), workspace_id=ws.id,
        period_end_date=date(2026, 4, 30),
        fx_rate_usd_brl=Decimal("5.12"),
        total_value_brl=Decimal("110000.00"), total_value_usd=Decimal("21484.38"),
        total_invested_brl=Decimal("80000.00"), total_received_brl=Decimal("2500.00"),
        source=SnapshotSource.MANUAL, is_active=True,
        created_at=now, updated_at=now,
    )
    db.add_all([snap_mar, snap_apr])
    db.flush()

    # Items for snap_apr (the one PortfolioSummary will use as "current"):
    items = [
        PortfolioSnapshotItem(
            id=str(uuid.uuid4()), snapshot_id=snap_apr.id, asset_id=petr.id,
            quantity=Decimal("100"), unit_price=Decimal("40"),
            market_value_native=Decimal("4000"), market_value_brl=Decimal("4000"),
            market_value_usd=Decimal("781.25"),
        ),
        PortfolioSnapshotItem(
            id=str(uuid.uuid4()), snapshot_id=snap_apr.id, asset_id=itub.id,
            quantity=Decimal("200"), unit_price=Decimal("30"),
            market_value_native=Decimal("6000"), market_value_brl=Decimal("6000"),
            market_value_usd=Decimal("1171.88"),
        ),
        PortfolioSnapshotItem(
            id=str(uuid.uuid4()), snapshot_id=snap_apr.id, asset_id=aapl.id,
            quantity=Decimal("50"), unit_price=Decimal("200"),
            market_value_native=Decimal("10000"),
            market_value_brl=Decimal("51200"),  # 10000 USD * 5.12 PTAX
            market_value_usd=Decimal("10000"),
        ),
    ]
    db.add_all(items)
    # Items for snap_mar (smaller — just enough to verify history shape)
    db.add(PortfolioSnapshotItem(
        id=str(uuid.uuid4()), snapshot_id=snap_mar.id, asset_id=petr.id,
        quantity=Decimal("100"), unit_price=Decimal("38"),
        market_value_native=Decimal("3800"), market_value_brl=Decimal("3800"),
        market_value_usd=Decimal("745.10"),
    ))
    db.commit()

    admin_token = AuthService(db).login("pf_admin@test.com", "adminpass")
    sysadmin_token = AuthService(db).login("pf_sysadmin@test.internal", "syspass")

    out = {
        "ws_id": ws.id,
        "petr_id": petr.id,
        "itub_id": itub.id,
        "aapl_id": aapl.id,
        "admin_token": admin_token,
        "sysadmin_token": sysadmin_token,
    }
    db.close()
    return out


def auth(token):
    return {"Authorization": f"Bearer {token}"}


# ── Service-level ────────────────────────────────────────────────────────────

def test_summary_uses_latest_snapshot(seed):
    db = TestSession()
    try:
        s = compute_portfolio_summary(db, seed["ws_id"])
    finally:
        db.close()

    assert s.source == "snapshot"
    assert s.as_of == "2026-04-30"
    assert s.total_value_brl == Decimal("110000.00")
    assert s.ptax_rate == Decimal("5.12")
    # 3 classes? Actually all STOCK. So 1 class entry.
    assert len(s.by_class) == 1
    assert s.by_class[0].asset_class == "STOCK"
    # 2 countries: BR + US
    assert {c.country for c in s.by_country} == {"BR", "US"}
    # 2 custodians: XP + Avenue
    assert len(s.by_custodian) == 2
    # 3 holdings.
    assert len(s.top_holdings) == 3
    # History has 2 points (snap_mar + snap_apr).
    assert len(s.history) == 2
    assert s.history[0].period_end == "2026-03-31"
    assert s.history[1].period_end == "2026-04-30"


def test_summary_empty_workspace_returns_empty():
    db = TestSession()
    try:
        # Create an empty workspace.
        ws2 = WorkspaceService(db).create("Empty WS")
        db.commit()
        s = compute_portfolio_summary(db, ws2.id)
    finally:
        db.close()
    assert s.source == "empty"
    assert s.as_of is None
    assert s.total_value_brl == Decimal("0")


# ── Endpoint ─────────────────────────────────────────────────────────────────

def test_get_portfolio_authenticated(client, seed):
    r = client.get("/portfolio", headers=auth(seed["admin_token"]))
    assert r.status_code == 200
    data = r.json()
    assert data["source"] == "snapshot"
    assert data["as_of"] == "2026-04-30"
    assert data["total_value_brl"] == 110000.0
    assert len(data["top_holdings"]) == 3
    # Top holding is AAPL (51200 BRL) > ITUB (6000) > PETR (4000).
    assert data["top_holdings"][0]["ticker"] == "AAPL"


def test_get_portfolio_requires_auth(client):
    r = client.get("/portfolio")
    assert r.status_code in (401, 403)


def test_sysadmin_needs_workspace_id(client, seed):
    r = client.get("/portfolio", headers=auth(seed["sysadmin_token"]))
    assert r.status_code == 400


def test_sysadmin_with_workspace_id(client, seed):
    r = client.get(
        "/portfolio", params={"workspace_id": seed["ws_id"]},
        headers=auth(seed["sysadmin_token"]),
    )
    assert r.status_code == 200
    assert r.json()["as_of"] == "2026-04-30"


def test_admin_cant_query_other_workspace(client, seed):
    r = client.get(
        "/portfolio", params={"workspace_id": "some-other-ws"},
        headers=auth(seed["admin_token"]),
    )
    assert r.status_code == 403
