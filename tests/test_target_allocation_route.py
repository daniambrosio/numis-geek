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
from numis_geek.models.audit_log import AuditLog
from numis_geek.models.target_allocation import TargetAllocation
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
    ws_a = WorkspaceService(db).create("TA WS-A")
    ws_b = WorkspaceService(db).create("TA WS-B")

    admin_a = UserService(db).create(ws_a.id, "ta_admin_a@test.com", "pw", UserRole.admin)
    member_a = UserService(db).create(ws_a.id, "ta_member_a@test.com", "pw", UserRole.member)
    admin_b = UserService(db).create(ws_b.id, "ta_admin_b@test.com", "pw", UserRole.admin)

    now = datetime.now(timezone.utc)
    sysadmin = User(
        id=str(uuid.uuid4()), workspace_id=None,
        email="ta_sysadmin@test.internal", name="Sys",
        password_hash=bcrypt.hashpw(b"pw", bcrypt.gensalt()).decode(),
        role=UserRole.sysadmin, is_active=True,
        created_at=now, updated_at=now,
    )
    db.add(sysadmin)
    db.commit()
    db.refresh(ws_a); db.refresh(ws_b)
    db.refresh(admin_a); db.refresh(member_a); db.refresh(admin_b); db.refresh(sysadmin)

    out = {
        "ws_a": ws_a.id, "ws_b": ws_b.id,
        "admin_a_token": AuthService(db).login("ta_admin_a@test.com", "pw"),
        "member_a_token": AuthService(db).login("ta_member_a@test.com", "pw"),
        "admin_b_token": AuthService(db).login("ta_admin_b@test.com", "pw"),
        "sysadmin_token": AuthService(db).login("ta_sysadmin@test.internal", "pw"),
    }
    db.close()
    return out


def auth(token):
    return {"Authorization": f"Bearer {token}"}


# ── GET ───────────────────────────────────────────────────────────────────────


def test_get_empty_returns_structure(client, seed):
    r = client.get(
        f"/api/workspaces/{seed['ws_a']}/target-allocation",
        headers=auth(seed["admin_a_token"]),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["workspace_id"] == seed["ws_a"]
    assert body["CLASS"]["entries"] == []
    assert body["COUNTRY"]["entries"] == []
    assert body["CLASS"]["is_valid"] is False


def test_member_can_read_own_workspace(client, seed):
    r = client.get(
        f"/api/workspaces/{seed['ws_a']}/target-allocation",
        headers=auth(seed["member_a_token"]),
    )
    assert r.status_code == 200


def test_member_cannot_read_other_workspace(client, seed):
    r = client.get(
        f"/api/workspaces/{seed['ws_b']}/target-allocation",
        headers=auth(seed["member_a_token"]),
    )
    assert r.status_code == 403


def test_sysadmin_can_read_any_workspace(client, seed):
    r = client.get(
        f"/api/workspaces/{seed['ws_b']}/target-allocation",
        headers=auth(seed["sysadmin_token"]),
    )
    assert r.status_code == 200


# ── PUT ───────────────────────────────────────────────────────────────────────


def test_put_happy_class(client, seed):
    payload = {
        "dimension": "CLASS",
        "entries": [
            {"key": "STOCK", "target_pct": "0.5"},
            {"key": "REIT", "target_pct": "0.3"},
            {"key": "FIXED_INCOME", "target_pct": "0.2"},
        ],
    }
    r = client.put(
        f"/api/workspaces/{seed['ws_a']}/target-allocation",
        json=payload,
        headers=auth(seed["admin_a_token"]),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["CLASS"]["is_valid"] is True
    keys = [e["key"] for e in body["CLASS"]["entries"]]
    assert keys == ["FIXED_INCOME", "REIT", "STOCK"]


def test_put_happy_country(client, seed):
    payload = {
        "dimension": "COUNTRY",
        "entries": [
            {"key": "BR", "target_pct": "0.7"},
            {"key": "US", "target_pct": "0.3"},
        ],
    }
    r = client.put(
        f"/api/workspaces/{seed['ws_a']}/target-allocation",
        json=payload,
        headers=auth(seed["admin_a_token"]),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["COUNTRY"]["is_valid"] is True
    # CLASS deve continuar populado do teste anterior (test_put_happy_class
    # rodou antes neste módulo). Confirma isolamento entre dimensões.
    assert len(body["CLASS"]["entries"]) == 3


def test_put_validation_sum_not_one(client, seed):
    payload = {
        "dimension": "CLASS",
        "entries": [
            {"key": "STOCK", "target_pct": "0.4"},
            {"key": "REIT", "target_pct": "0.4"},
        ],
    }
    r = client.put(
        f"/api/workspaces/{seed['ws_a']}/target-allocation",
        json=payload,
        headers=auth(seed["admin_a_token"]),
    )
    assert r.status_code == 400


def test_put_validation_invalid_class_key(client, seed):
    payload = {
        "dimension": "CLASS",
        "entries": [{"key": "BOGUS", "target_pct": "1.0"}],
    }
    r = client.put(
        f"/api/workspaces/{seed['ws_a']}/target-allocation",
        json=payload,
        headers=auth(seed["admin_a_token"]),
    )
    assert r.status_code == 400


def test_put_member_forbidden(client, seed):
    payload = {
        "dimension": "CLASS",
        "entries": [{"key": "STOCK", "target_pct": "1.0"}],
    }
    r = client.put(
        f"/api/workspaces/{seed['ws_a']}/target-allocation",
        json=payload,
        headers=auth(seed["member_a_token"]),
    )
    assert r.status_code == 403


def test_put_other_workspace_forbidden(client, seed):
    payload = {
        "dimension": "CLASS",
        "entries": [{"key": "STOCK", "target_pct": "1.0"}],
    }
    r = client.put(
        f"/api/workspaces/{seed['ws_b']}/target-allocation",
        json=payload,
        headers=auth(seed["admin_a_token"]),
    )
    assert r.status_code == 403


def test_put_sysadmin_any_workspace(client, seed):
    payload = {
        "dimension": "CLASS",
        "entries": [{"key": "STOCK", "target_pct": "1.0"}],
    }
    r = client.put(
        f"/api/workspaces/{seed['ws_b']}/target-allocation",
        json=payload,
        headers=auth(seed["sysadmin_token"]),
    )
    assert r.status_code == 200


def test_put_creates_audit_entry(client, seed):
    payload = {
        "dimension": "CLASS",
        "entries": [{"key": "ETF", "target_pct": "1.0"}],
    }
    r = client.put(
        f"/api/workspaces/{seed['ws_a']}/target-allocation",
        json=payload,
        headers=auth(seed["admin_a_token"]),
    )
    assert r.status_code == 200
    db = TestSession()
    try:
        rows = (
            db.query(AuditLog)
            .filter(AuditLog.action == "target_allocation.update")
            .filter(AuditLog.workspace_id == seed["ws_a"])
            .all()
        )
        assert len(rows) >= 1
    finally:
        db.close()


def test_persistence_visible_on_subsequent_get(client, seed):
    r = client.get(
        f"/api/workspaces/{seed['ws_a']}/target-allocation",
        headers=auth(seed["admin_a_token"]),
    )
    assert r.status_code == 200
    body = r.json()
    # Last PUT in this module was ETF=1.0 → only one CLASS entry.
    keys = [e["key"] for e in body["CLASS"]["entries"]]
    assert keys == ["ETF"]


def test_database_row_count(client, seed):
    db = TestSession()
    try:
        rows = (
            db.query(TargetAllocation)
            .filter(TargetAllocation.workspace_id == seed["ws_a"])
            .all()
        )
        # CLASS (ETF) + COUNTRY (BR, US)
        assert len(rows) == 3
    finally:
        db.close()
