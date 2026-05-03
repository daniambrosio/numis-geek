import uuid
from datetime import datetime, timezone

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
from numis_geek.models.financial_institution import FinancialInstitution
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
    ws = WorkspaceService(db).create("Accounts WS")
    admin = UserService(db).create(ws.id, "acc_admin@test.com", "adminpass", UserRole.admin)
    member = UserService(db).create(ws.id, "acc_member@test.com", "memberpass", UserRole.member)

    now = datetime.now(timezone.utc)
    sysadmin = User(
        id=str(uuid.uuid4()),
        workspace_id=None,
        email="acc_sysadmin@test.internal",
        name="SysAdmin",
        password_hash=bcrypt.hashpw(b"syspass", bcrypt.gensalt()).decode(),
        role=UserRole.sysadmin,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(sysadmin)

    fi = FinancialInstitution(
        id=str(uuid.uuid4()),
        long_name="Banco Test S.A.",
        short_name="BTest",
        logo_slug=None,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(fi)
    db.commit()

    db.refresh(ws); db.refresh(admin); db.refresh(member); db.refresh(sysadmin); db.refresh(fi)
    admin_token = AuthService(db).login("acc_admin@test.com", "adminpass")
    member_token = AuthService(db).login("acc_member@test.com", "memberpass")
    sysadmin_token = AuthService(db).login("acc_sysadmin@test.internal", "syspass")
    db.close()
    return {
        "ws_id": ws.id,
        "admin_id": admin.id,
        "member_id": member.id,
        "sysadmin_id": sysadmin.id,
        "fi_id": fi.id,
        "admin_token": admin_token,
        "member_token": member_token,
        "sysadmin_token": sysadmin_token,
    }


def auth_header(token):
    return {"Authorization": f"Bearer {token}"}


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_list_accounts_empty(client, seed):
    r = client.get("/accounts", headers=auth_header(seed["admin_token"]))
    assert r.status_code == 200
    assert r.json() == []


def test_create_account_checking(client, seed):
    r = client.post("/accounts", json={
        "name": "BTest Corrente",
        "account_type": "checking",
        "financial_institution_id": seed["fi_id"],
        "currency": "BRL",
        "opening_balance": "1000.00",
    }, headers=auth_header(seed["admin_token"]))
    assert r.status_code == 201
    data = r.json()
    assert data["name"] == "BTest Corrente"
    assert data["account_type"] == "checking"
    assert data["currency"] == "BRL"
    assert data["opening_balance"] == 1000.0
    assert data["is_active"] is True


def test_create_account_investment(client, seed):
    r = client.post("/accounts", json={
        "name": "BTest Investimentos",
        "account_type": "investment",
        "financial_institution_id": seed["fi_id"],
        "currency": "BRL",
    }, headers=auth_header(seed["admin_token"]))
    assert r.status_code == 201
    data = r.json()
    assert data["account_type"] == "investment"
    assert data["opening_balance"] is None  # ignored for investment accounts


def test_create_account_member_forbidden(client, seed):
    r = client.post("/accounts", json={
        "name": "Should Fail",
        "account_type": "checking",
        "financial_institution_id": seed["fi_id"],
        "currency": "BRL",
    }, headers=auth_header(seed["member_token"]))
    assert r.status_code == 403


def test_list_shows_fi_name(client, seed):
    r = client.get("/accounts", headers=auth_header(seed["admin_token"]))
    assert r.status_code == 200
    items = r.json()
    assert len(items) >= 1
    for item in items:
        assert "financial_institution_name" in item
        assert item["financial_institution_name"] == "BTest"


def test_update_account(client, seed):
    # Create an account to update
    r = client.post("/accounts", json={
        "name": "Original Name",
        "account_type": "checking",
        "financial_institution_id": seed["fi_id"],
        "currency": "USD",
        "account_info": "Agencia 001",
    }, headers=auth_header(seed["admin_token"]))
    account_id = r.json()["id"]

    r2 = client.put(f"/accounts/{account_id}", json={
        "name": "Updated Name",
        "account_type": "checking",
        "financial_institution_id": seed["fi_id"],
        "currency": "USD",
        "account_info": "Agencia 002",
    }, headers=auth_header(seed["admin_token"]))
    assert r2.status_code == 200
    assert r2.json()["name"] == "Updated Name"
    assert r2.json()["account_info"] == "Agencia 002"


def test_deactivate_account(client, seed):
    # Create account then deactivate
    r = client.post("/accounts", json={
        "name": "To Deactivate",
        "account_type": "investment",
        "financial_institution_id": seed["fi_id"],
        "currency": "BRL",
    }, headers=auth_header(seed["admin_token"]))
    account_id = r.json()["id"]

    r2 = client.put(f"/accounts/{account_id}/deactivate", headers=auth_header(seed["admin_token"]))
    assert r2.status_code == 200
    assert r2.json()["is_active"] is False

    # Should no longer appear in list
    r3 = client.get("/accounts", headers=auth_header(seed["admin_token"]))
    ids = [a["id"] for a in r3.json()]
    assert account_id not in ids


def test_sysadmin_can_manage_accounts(client, seed):
    # Sysadmin has no workspace, so create under admin's workspace via a different path.
    # Sysadmin can LIST all accounts (not filtered by workspace)
    r = client.get("/accounts", headers=auth_header(seed["sysadmin_token"]))
    assert r.status_code == 200
    # sysadmin sees all — should see at least what admin created
    assert len(r.json()) >= 1
