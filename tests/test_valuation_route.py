"""Spec 61b — Valuation route tests."""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import patch

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
from numis_geek.integrations.brapi import BrapiFundamentals
from numis_geek.models.account import Account, AccountType, Currency
from numis_geek.models.asset import Asset, AssetClass
from numis_geek.models.asset_fundamentals import (
    AssetFundamentals, FundamentalsSource,
)
from numis_geek.models.audit_log import AuditLog
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.integration_credential import (
    IntegrationCredential, IntegrationProvider,
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


@pytest.fixture(scope="module")
def seed():
    db = TestSession()
    ws = WorkspaceService(db).create("Val-WS")
    admin = UserService(db).create(ws.id, "val_admin@t.com", "pw", UserRole.admin)
    member = UserService(db).create(ws.id, "val_mem@t.com", "pw", UserRole.member)

    other_ws = WorkspaceService(db).create("Val-WS-Other")
    other_admin = UserService(db).create(other_ws.id, "val_other@t.com", "pw", UserRole.admin)

    now = datetime.now(timezone.utc)
    sysadmin = User(
        id=str(uuid.uuid4()), workspace_id=None,
        email="val_sys@t.internal", name="Sys",
        password_hash=bcrypt.hashpw(b"pw", bcrypt.gensalt()).decode(),
        role=UserRole.sysadmin, is_active=True,
        created_at=now, updated_at=now,
    )
    db.add(sysadmin)

    fi = FinancialInstitution(
        id=str(uuid.uuid4()), long_name="FI", short_name="FI",
        logo_slug=None, is_active=True, created_at=now, updated_at=now,
    )
    db.add(fi); db.flush()
    acc = Account(
        id=str(uuid.uuid4()), workspace_id=ws.id,
        financial_institution_id=fi.id, name="Acc",
        account_type=AccountType.investment, currency=Currency.BRL,
        opening_balance=Decimal("0"), is_active=True,
        created_at=now, updated_at=now,
    )
    db.add(acc); db.flush()
    # Stock with fundamentals (BUY scenario)
    asset_with = Asset(
        id=str(uuid.uuid4()), workspace_id=ws.id, account_id=acc.id,
        asset_class=AssetClass.STOCK, country="BR", name="TICK",
        ticker="TICK", currency=Currency.BRL,
        current_price=Decimal("20"), is_active=True,
        created_at=now, updated_at=now,
    )
    db.add(asset_with); db.flush()
    db.add(AssetFundamentals(
        workspace_id=ws.id, asset_id=asset_with.id,
        snapshot_date=date.today(), source=FundamentalsSource.MANUAL,
        dps_12m=Decimal("10"), eps=Decimal("4"), bvps=Decimal("10"),
        roe=Decimal("0.15"), debt_ebitda=Decimal("1.5"),
        earnings_growth_5y=Decimal("0.05"),
        dividend_yield_12m=Decimal("0.5"),
    ))
    # Asset without fundamentals (NA scenario)
    asset_without = Asset(
        id=str(uuid.uuid4()), workspace_id=ws.id, account_id=acc.id,
        asset_class=AssetClass.STOCK, country="BR", name="NOFUND",
        ticker="NOFUND", currency=Currency.BRL,
        current_price=Decimal("10"), is_active=True,
        created_at=now, updated_at=now,
    )
    db.add(asset_without)
    # Brapi credential for refresh test
    db.add(IntegrationCredential(
        workspace_id=None, provider=IntegrationProvider.BRAPI,
        key_name="default", secret_value="tok", is_active=True,
    ))
    db.commit()
    db.refresh(asset_with); db.refresh(asset_without)

    out = {
        "ws_id": ws.id,
        "other_ws_id": other_ws.id,
        "asset_with": asset_with.id,
        "asset_without": asset_without.id,
        "admin_token": AuthService(db).login("val_admin@t.com", "pw"),
        "member_token": AuthService(db).login("val_mem@t.com", "pw"),
        "other_admin_token": AuthService(db).login("val_other@t.com", "pw"),
        "sysadmin_token": AuthService(db).login("val_sys@t.internal", "pw"),
    }
    db.close()
    return out


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_get_valuation_buy(client, seed):
    r = client.get(
        f"/api/assets/{seed['asset_with']}/valuation",
        headers=auth(seed["admin_token"]),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["verdict"] == "BUY"
    assert body["asset_class"] == "STOCK"
    metric_names = {m["name"] for m in body["metrics"]}
    assert {"P/L", "Bazin", "Graham"}.issubset(metric_names)


def test_get_valuation_na_without_fundamentals(client, seed):
    r = client.get(
        f"/api/assets/{seed['asset_without']}/valuation",
        headers=auth(seed["admin_token"]),
    )
    assert r.status_code == 200
    assert r.json()["verdict"] == "NA"


def test_get_valuation_404_unknown_asset(client, seed):
    r = client.get(
        f"/api/assets/does-not-exist/valuation",
        headers=auth(seed["admin_token"]),
    )
    assert r.status_code == 404


def test_get_valuation_403_other_workspace(client, seed):
    r = client.get(
        f"/api/assets/{seed['asset_with']}/valuation",
        headers=auth(seed["other_admin_token"]),
    )
    assert r.status_code == 403


def test_get_valuation_sysadmin_any(client, seed):
    r = client.get(
        f"/api/assets/{seed['asset_with']}/valuation",
        headers=auth(seed["sysadmin_token"]),
    )
    assert r.status_code == 200


def test_get_fundamentals_returns_latest(client, seed):
    r = client.get(
        f"/api/assets/{seed['asset_with']}/fundamentals",
        headers=auth(seed["admin_token"]),
    )
    assert r.status_code == 200
    body = r.json()
    assert body is not None
    assert body["dps_12m"] == "10.0000"
    assert body["source"] == "MANUAL"


def test_get_fundamentals_null_when_none(client, seed):
    r = client.get(
        f"/api/assets/{seed['asset_without']}/fundamentals",
        headers=auth(seed["admin_token"]),
    )
    assert r.status_code == 200
    assert r.json() is None


def test_refresh_member_forbidden(client, seed):
    r = client.post(
        f"/api/assets/{seed['asset_with']}/fundamentals/refresh",
        headers=auth(seed["member_token"]),
    )
    assert r.status_code == 403


def test_refresh_admin_calls_provider(client, seed):
    fake = BrapiFundamentals(
        ticker="TICK", snapshot_date=date.today(),
        pe=Decimal("15"), eps=Decimal("3"),
    )
    with patch(
        "numis_geek.services.fundamentals_ingest.brapi.fetch_fundamentals",
        return_value=fake,
    ):
        r = client.post(
            f"/api/assets/{seed['asset_with']}/fundamentals/refresh",
            headers=auth(seed["admin_token"]),
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body is not None
    assert body["source"] == "BRAPI"
    # audit entry created
    db = TestSession()
    try:
        rows = db.query(AuditLog).filter(
            AuditLog.action == "fundamentals.refresh"
        ).all()
        assert any(r.resource_id == seed["asset_with"] for r in rows)
    finally:
        db.close()
