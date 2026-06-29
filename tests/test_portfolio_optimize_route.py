"""Spec 61c — POST /portfolio/optimize route tests."""
import uuid
from datetime import date, datetime, timedelta, timezone
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
    PortfolioSnapshot, PortfolioSnapshotItem, SnapshotSource, SnapshotStatus,
)
from numis_geek.models.target_allocation import (
    TargetAllocation, TargetAllocationDimension,
)
from numis_geek.models.user import User, UserRole
from numis_geek.services.auth import AuthService
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
        yield db; db.commit()
    except Exception:
        db.rollback(); raise
    finally:
        db.close()


@pytest.fixture(scope="module")
def client():
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _build_3asset(db, ws_id, *, n_months=20):
    now = datetime.now(timezone.utc)
    fi = FinancialInstitution(
        id=str(uuid.uuid4()), long_name="FI", short_name="FI",
        logo_slug=None, is_active=True, created_at=now, updated_at=now,
    )
    db.add(fi); db.flush()
    acc = Account(
        id=str(uuid.uuid4()), workspace_id=ws_id,
        financial_institution_id=fi.id, name="Acc",
        account_type=AccountType.investment, currency=Currency.BRL,
        opening_balance=Decimal("0"), is_active=True,
        created_at=now, updated_at=now,
    )
    db.add(acc); db.flush()
    assets = []
    for klass, country, ticker, cur in [
        (AssetClass.STOCK, "BR", "ITUB4", Currency.BRL),
        (AssetClass.STOCK, "US", "AAPL", Currency.USD),
        (AssetClass.REIT, "BR", "XPLG11", Currency.BRL),
    ]:
        a = Asset(
            id=str(uuid.uuid4()), workspace_id=ws_id, account_id=acc.id,
            asset_class=klass, country=country, name=ticker, ticker=ticker,
            currency=cur, is_active=True,
            created_at=now, updated_at=now,
        )
        db.add(a)
        assets.append(a)
    db.flush()
    # Simple growing series for each
    base = 100.0
    today_d = date.today()
    for i in range(n_months):
        period_end = today_d - timedelta(days=30 * (n_months - 1 - i))
        snap = PortfolioSnapshot(
            workspace_id=ws_id, period_end_date=period_end,
            fx_rate_usd_brl=Decimal("5"), source=SnapshotSource.AUTOMATED,
            status=SnapshotStatus.CLOSED,
        )
        db.add(snap); db.flush()
        for j, a in enumerate(assets):
            mv = base * (1.01 ** i) * (1.0 + j * 0.001)  # slightly different per asset
            it = PortfolioSnapshotItem(
                snapshot_id=snap.id, asset_id=a.id,
                quantity=Decimal("1"),
                unit_price=Decimal(str(mv)),
                market_value_brl=Decimal(str(mv)),
                market_value_native=Decimal(str(mv)),
            )
            db.add(it)
    db.flush()
    return assets


@pytest.fixture(scope="module")
def seed():
    db = TestSession()
    ws = WorkspaceService(db).create("Opt-WS")
    admin = UserService(db).create(ws.id, "opt_admin@t.com", "pw", UserRole.admin)
    UserService(db).create(ws.id, "opt_mem@t.com", "pw", UserRole.member)
    now = datetime.now(timezone.utc)
    sysadmin = User(
        id=str(uuid.uuid4()), workspace_id=None,
        email="opt_sys@t.internal", name="Sys",
        password_hash=bcrypt.hashpw(b"pw", bcrypt.gensalt()).decode(),
        role=UserRole.sysadmin, is_active=True,
        created_at=now, updated_at=now,
    )
    db.add(sysadmin)
    _build_3asset(db, ws.id, n_months=20)
    # Seed target_allocation
    for k, v in [("STOCK", "0.7"), ("REIT", "0.3")]:
        db.add(TargetAllocation(
            workspace_id=ws.id, dimension=TargetAllocationDimension.CLASS,
            key=k, target_pct=Decimal(v),
        ))
    db.commit()
    out = {
        "ws_id": ws.id,
        "admin_token": AuthService(db).login("opt_admin@t.com", "pw"),
        "member_token": AuthService(db).login("opt_mem@t.com", "pw"),
        "sysadmin_token": AuthService(db).login("opt_sys@t.internal", "pw"),
    }
    db.close()
    return out


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_optimize_with_explicit_targets(client, seed):
    payload = {
        "class_targets": {"STOCK": "0.7", "REIT": "0.3"},
        "asset_cap": "0.5",
        "country_caps": {"BR": "0.7"},
    }
    r = client.post(
        "/api/portfolio/optimize", json=payload,
        headers=auth(seed["admin_token"]),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["n_assets"] == 3
    total = sum(o["weight"] for o in body["optimal"])
    assert abs(total - 1.0) < 1e-4
    stock_w = sum(o["weight"] for o in body["optimal"] if o["asset_class"] == "STOCK")
    assert abs(stock_w - 0.7) < 1e-3


def test_optimize_uses_db_targets_when_not_provided(client, seed):
    payload = {"asset_cap": "0.5"}
    r = client.post(
        "/api/portfolio/optimize", json=payload,
        headers=auth(seed["admin_token"]),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    stock_w = sum(o["weight"] for o in body["optimal"] if o["asset_class"] == "STOCK")
    # Seeded as 0.7
    assert abs(stock_w - 0.7) < 1e-3


def test_optimize_infeasible_returns_422(client, seed):
    # REIT 1.0 mas só 1 REIT × cap 0.15 = 0.15 < 1.0
    payload = {
        "class_targets": {"REIT": "1.0"},
        "asset_cap": "0.15",
    }
    r = client.post(
        "/api/portfolio/optimize", json=payload,
        headers=auth(seed["admin_token"]),
    )
    assert r.status_code == 422
    assert "REIT" in r.json()["detail"] or "elegív" in r.json()["detail"]


def test_optimize_targets_not_summing_returns_422(client, seed):
    payload = {
        "class_targets": {"STOCK": "0.4"},
        "asset_cap": "0.5",
    }
    r = client.post(
        "/api/portfolio/optimize", json=payload,
        headers=auth(seed["admin_token"]),
    )
    assert r.status_code == 422


def test_optimize_member_can_use(client, seed):
    payload = {"asset_cap": "0.5"}
    r = client.post(
        "/api/portfolio/optimize", json=payload,
        headers=auth(seed["member_token"]),
    )
    assert r.status_code == 200


def test_optimize_response_includes_trades(client, seed):
    payload = {
        "class_targets": {"STOCK": "0.7", "REIT": "0.3"},
        "asset_cap": "0.5",
    }
    r = client.post(
        "/api/portfolio/optimize", json=payload,
        headers=auth(seed["admin_token"]),
    )
    body = r.json()
    actions = {o["trade_action"] for o in body["optimal"]}
    assert actions <= {"BUY", "SELL", "HOLD"}
    assert "warnings" in body
    assert isinstance(body["warnings"], list)
