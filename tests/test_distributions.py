"""Tests for the Distribution entity — created in spec 08.

DIVIDEND / INTEREST / JCP / SECURITIES_LENDING. asset_id is nullable
(Avenue's "rendimento de aluguel" has no ticker).
"""
import uuid
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from numis_geek.api.app import app
from numis_geek.api.deps import get_db
from numis_geek.db.base import Base
import numis_geek.models  # noqa: F401
from numis_geek.models.asset import Asset, AssetClass
from numis_geek.models.account import Account, AccountType, Currency
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.user import UserRole
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
    ws = WorkspaceService(db).create("Dist WS")
    UserService(db).create(ws.id, "dist_admin@test.com", "adminpass", UserRole.admin)

    now = datetime.now(timezone.utc)
    fi = FinancialInstitution(
        id=str(uuid.uuid4()),
        long_name="Avenue Securities",
        short_name="Avenue",
        logo_slug="avenue",
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(fi)

    # Spec 10: every asset needs an investment account
    account = Account(
        id=str(uuid.uuid4()),
        workspace_id=ws.id,
        financial_institution_id=fi.id,
        name="Test investment account",
        account_type=AccountType.investment,
        currency=Currency.BRL,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(account)
    asset_usd = Asset(
        id=str(uuid.uuid4()),
        workspace_id=ws.id,
        account_id=account.id,
        asset_class=AssetClass.STOCK,
        country="BR",
        name="Realty Income",
        ticker="O",
        currency=Currency.USD,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    asset_brl = Asset(
        id=str(uuid.uuid4()),
        workspace_id=ws.id,
        account_id=account.id,
        asset_class=AssetClass.STOCK,
        country="BR",
        name="Petrobras PN",
        ticker="PETR4",
        currency=Currency.BRL,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add_all([asset_usd, asset_brl])
    db.commit()
    db.refresh(ws); db.refresh(fi); db.refresh(asset_usd); db.refresh(asset_brl)
    token = AuthService(db).login("dist_admin@test.com", "adminpass")
    out = {
        "ws_id": ws.id,
        "fi_id": fi.id,
        "asset_usd": asset_usd.id,
        "asset_brl": asset_brl.id,
        "admin_token": token,
    }
    db.close()
    return out


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def _today():
    return date.today().isoformat()


# ── Basic CRUD ─────────────────────────────────────────────────────────────

def test_list_distributions_empty(client, seed):
    r = client.get("/distributions", headers=auth(seed["admin_token"]))
    assert r.status_code == 200
    assert r.json()["items"] == []


def test_create_dividend(client, seed):
    r = client.post("/distributions", json={
        "financial_institution_id": seed["fi_id"],
        "asset_id": seed["asset_usd"],
        "type": "DIVIDEND",
        "event_date": _today(),
        "gross_amount": 10.50,
        "tax": 1.50,
        "currency": "USD",
        "fx_rate": 5.0,
    }, headers=auth(seed["admin_token"]))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["type"] == "DIVIDEND"
    assert body["type_label"] == "Dividendo"
    assert body["gross_amount"] == 10.5
    assert body["net_amount"] == 9.0  # gross - tax
    assert body["asset_ticker"] == "O"


def test_create_interest(client, seed):
    r = client.post("/distributions", json={
        "financial_institution_id": seed["fi_id"],
        "asset_id": seed["asset_brl"],
        "type": "INTEREST",
        "event_date": _today(),
        "gross_amount": 25.00,
        "currency": "BRL",
    }, headers=auth(seed["admin_token"]))
    assert r.status_code == 201, r.text
    assert r.json()["type"] == "INTEREST"
    assert r.json()["net_amount"] == 25.0


def test_create_jcp(client, seed):
    r = client.post("/distributions", json={
        "financial_institution_id": seed["fi_id"],
        "asset_id": seed["asset_brl"],
        "type": "JCP",
        "event_date": _today(),
        "gross_amount": 40.00,
        "tax": 6.00,  # 15% IR on JCP
        "currency": "BRL",
    }, headers=auth(seed["admin_token"]))
    assert r.status_code == 201, r.text
    assert r.json()["net_amount"] == 34.0


def test_securities_lending_without_asset(client, seed):
    """Avenue case: 'rendimento de aluguel' has no specific ticker."""
    r = client.post("/distributions", json={
        "financial_institution_id": seed["fi_id"],
        "asset_id": None,
        "type": "SECURITIES_LENDING",
        "event_date": _today(),
        "gross_amount": 8.40,
        "currency": "USD",
        "fx_rate": 5.1,
    }, headers=auth(seed["admin_token"]))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["asset_id"] is None
    assert body["type"] == "SECURITIES_LENDING"
    assert body["type_label"] == "Aluguel"


def test_gross_must_be_positive(client, seed):
    r = client.post("/distributions", json={
        "financial_institution_id": seed["fi_id"],
        "asset_id": seed["asset_brl"],
        "type": "DIVIDEND",
        "event_date": _today(),
        "gross_amount": 0,
        "currency": "BRL",
    }, headers=auth(seed["admin_token"]))
    assert r.status_code == 422


def test_currency_must_match_asset(client, seed):
    r = client.post("/distributions", json={
        "financial_institution_id": seed["fi_id"],
        "asset_id": seed["asset_brl"],
        "type": "DIVIDEND",
        "event_date": _today(),
        "gross_amount": 10.00,
        "currency": "USD",
    }, headers=auth(seed["admin_token"]))
    assert r.status_code == 400
    assert "currency" in r.json()["detail"].lower()


def test_event_date_not_future(client, seed):
    from datetime import timedelta
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    r = client.post("/distributions", json={
        "financial_institution_id": seed["fi_id"],
        "asset_id": seed["asset_brl"],
        "type": "DIVIDEND",
        "event_date": tomorrow,
        "gross_amount": 10.00,
        "currency": "BRL",
    }, headers=auth(seed["admin_token"]))
    assert r.status_code == 422


def test_update_distribution(client, seed):
    r = client.post("/distributions", json={
        "financial_institution_id": seed["fi_id"],
        "asset_id": seed["asset_brl"],
        "type": "DIVIDEND",
        "event_date": _today(),
        "gross_amount": 5.00,
        "currency": "BRL",
    }, headers=auth(seed["admin_token"]))
    did = r.json()["id"]

    r2 = client.put(f"/distributions/{did}", json={
        "financial_institution_id": seed["fi_id"],
        "asset_id": seed["asset_brl"],
        "type": "JCP",
        "event_date": _today(),
        "gross_amount": 12.00,
        "tax": 1.80,
        "currency": "BRL",
    }, headers=auth(seed["admin_token"]))
    assert r2.status_code == 200
    assert r2.json()["type"] == "JCP"
    assert r2.json()["net_amount"] == 10.2


def test_deactivate_distribution(client, seed):
    r = client.post("/distributions", json={
        "financial_institution_id": seed["fi_id"],
        "asset_id": seed["asset_brl"],
        "type": "DIVIDEND",
        "event_date": _today(),
        "gross_amount": 3.00,
        "currency": "BRL",
    }, headers=auth(seed["admin_token"]))
    did = r.json()["id"]
    r2 = client.put(f"/distributions/{did}/deactivate", headers=auth(seed["admin_token"]))
    assert r2.status_code == 200
    assert r2.json()["is_active"] is False


def test_filter_by_type(client, seed):
    r = client.get("/distributions?type=DIVIDEND", headers=auth(seed["admin_token"]))
    assert r.status_code == 200
    items = r.json()["items"]
    assert all(it["type"] == "DIVIDEND" for it in items)
