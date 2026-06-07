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
    r = client.get("/api/accounts", headers=auth_header(seed["admin_token"]))
    assert r.status_code == 200
    assert r.json() == []


def test_create_account_checking(client, seed):
    r = client.post("/api/accounts", json={
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
    r = client.post("/api/accounts", json={
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
    r = client.post("/api/accounts", json={
        "name": "Should Fail",
        "account_type": "checking",
        "financial_institution_id": seed["fi_id"],
        "currency": "BRL",
    }, headers=auth_header(seed["member_token"]))
    assert r.status_code == 403


def test_list_shows_fi_name(client, seed):
    r = client.get("/api/accounts", headers=auth_header(seed["admin_token"]))
    assert r.status_code == 200
    items = r.json()
    assert len(items) >= 1
    for item in items:
        assert "financial_institution_name" in item
        assert item["financial_institution_name"] == "BTest"


def test_update_account(client, seed):
    # Create an account to update
    r = client.post("/api/accounts", json={
        "name": "Original Name",
        "account_type": "checking",
        "financial_institution_id": seed["fi_id"],
        "currency": "USD",
        "account_info": "Agencia 001",
    }, headers=auth_header(seed["admin_token"]))
    account_id = r.json()["id"]

    r2 = client.put(f"/api/accounts/{account_id}", json={
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
    r = client.post("/api/accounts", json={
        "name": "To Deactivate",
        "account_type": "investment",
        "financial_institution_id": seed["fi_id"],
        "currency": "BRL",
    }, headers=auth_header(seed["admin_token"]))
    account_id = r.json()["id"]

    r2 = client.put(f"/api/accounts/{account_id}/deactivate", headers=auth_header(seed["admin_token"]))
    assert r2.status_code == 200
    assert r2.json()["is_active"] is False

    # Should no longer appear in list
    r3 = client.get("/api/accounts", headers=auth_header(seed["admin_token"]))
    ids = [a["id"] for a in r3.json()]
    assert account_id not in ids


def test_sysadmin_can_manage_accounts(client, seed):
    # Sysadmin has no workspace, so create under admin's workspace via a different path.
    # Sysadmin can LIST all accounts (not filtered by workspace)
    r = client.get("/api/accounts", headers=auth_header(seed["sysadmin_token"]))
    assert r.status_code == 200
    # sysadmin sees all — should see at least what admin created
    assert len(r.json()) >= 1


# ── /accounts/by-custodian tests ─────────────────────────────────────────────

def test_by_custodian_basic_shape(client, seed):
    """Returns list of {financial_institution, accounts, assets} groups."""
    r = client.get("/api/accounts/by-custodian", headers=auth_header(seed["admin_token"]))
    assert r.status_code == 200, r.text
    groups = r.json()
    assert isinstance(groups, list)
    if groups:
        g = groups[0]
        assert "financial_institution" in g
        assert "accounts" in g
        assert "assets" in g
        assert "id" in g["financial_institution"]
        assert "short_name" in g["financial_institution"]
        assert "logo_slug" in g["financial_institution"]


def test_by_custodian_includes_investment_accounts_only(client, seed):
    """The 'accounts' inside each group are limited to investment-type accounts."""
    # Create both a checking and an investment account at the same FI (using existing seed FI).
    client.post("/api/accounts", json={
        "name": "BC Investimentos",
        "account_type": "investment",
        "financial_institution_id": seed["fi_id"],
        "currency": "BRL",
    }, headers=auth_header(seed["admin_token"]))

    r = client.get("/api/accounts/by-custodian", headers=auth_header(seed["admin_token"]))
    groups = r.json()
    for g in groups:
        for a in g["accounts"]:
            assert a["account_type"] == "investment"


def test_by_custodian_skips_fi_with_neither(client, seed):
    """FIs with neither investment accounts nor assets in the workspace are skipped."""
    # Create a fresh FI with no associations
    r_fi = client.post("/api/financial-institutions", json={
        "long_name": "Custodian-Empty Bank",
        "short_name": "CEmpty",
    }, headers=auth_header(seed["sysadmin_token"]))
    new_fi_id = r_fi.json()["id"]

    r = client.get("/api/accounts/by-custodian", headers=auth_header(seed["admin_token"]))
    groups = r.json()
    fi_ids = [g["financial_institution"]["id"] for g in groups]
    assert new_fi_id not in fi_ids


def test_by_custodian_workspace_isolation(client, seed):
    """Members only see their own workspace's accounts/assets."""
    # Create a separate workspace + admin
    db = TestSession()
    other_ws = WorkspaceService(db).create("Other WS for by-custodian")
    UserService(db).create(other_ws.id, "other_admin@test.com", "otherpass", UserRole.admin)
    other_token = AuthService(db).login("other_admin@test.com", "otherpass")

    # Create an investment account in OTHER workspace at the seed FI
    db.close()
    r_create = client.post("/api/accounts", json={
        "name": "Other WS Investimentos",
        "account_type": "investment",
        "financial_institution_id": seed["fi_id"],
        "currency": "BRL",
    }, headers=auth_header(other_token))
    other_acc_id = r_create.json()["id"]

    # Original WS admin should NOT see other_acc_id in their by-custodian view
    r = client.get("/api/accounts/by-custodian", headers=auth_header(seed["admin_token"]))
    all_account_ids = [
        a["id"]
        for g in r.json()
        for a in g["accounts"]
    ]
    assert other_acc_id not in all_account_ids


def test_by_custodian_sysadmin_cross_workspace(client, seed):
    """Sysadmin without workspace_id sees groups across workspaces."""
    r = client.get("/api/accounts/by-custodian", headers=auth_header(seed["sysadmin_token"]))
    assert r.status_code == 200
    groups = r.json()
    # We have at least one investment account from earlier tests in this module.
    assert len(groups) >= 1
