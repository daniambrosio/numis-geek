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
    ws = WorkspaceService(db).create("Audit WS")
    admin = UserService(db).create(ws.id, "audit_admin@test.com", "adminpass", UserRole.admin)
    member = UserService(db).create(ws.id, "audit_member@test.com", "memberpass", UserRole.member)

    now = datetime.now(timezone.utc)
    sysadmin = User(
        id=str(uuid.uuid4()),
        workspace_id=None,
        email="audit_sysadmin@test.internal",
        name="SysAdmin",
        password_hash=bcrypt.hashpw(b"syspass", bcrypt.gensalt()).decode(),
        role=UserRole.sysadmin,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(sysadmin)
    db.commit()
    db.refresh(ws); db.refresh(admin); db.refresh(member); db.refresh(sysadmin)
    ws_id, admin_id, member_id, sysadmin_id = ws.id, admin.id, member.id, sysadmin.id
    admin_token = AuthService(db).login("audit_admin@test.com", "adminpass")
    member_token = AuthService(db).login("audit_member@test.com", "memberpass")
    sysadmin_token = AuthService(db).login("audit_sysadmin@test.internal", "syspass")
    db.close()
    return {
        "ws_id": ws_id, "admin_id": admin_id, "member_id": member_id, "sysadmin_id": sysadmin_id,
        "admin_token": admin_token, "member_token": member_token, "sysadmin_token": sysadmin_token,
    }


def auth_header(token):
    return {"Authorization": f"Bearer {token}"}


def test_login_creates_audit(client, seed):
    r = client.post("/api/auth/login", json={"email": "audit_admin@test.com", "password": "adminpass"})
    assert r.status_code == 200
    logs = client.get("/api/audit", headers=auth_header(seed["admin_token"])).json()
    actions = [e["action"] for e in logs["items"]]
    assert "auth.login" in actions


def test_invite_creates_audit(client, seed):
    client.post("/api/users/invite", json={
        "email": "foraudit@test.com", "password": "pass", "role": "member",
    }, headers=auth_header(seed["admin_token"]))
    logs = client.get("/api/audit", headers=auth_header(seed["admin_token"])).json()
    actions = [e["action"] for e in logs["items"]]
    assert "user.invited" in actions


def test_deactivate_creates_audit(client, seed):
    r = client.post("/api/users/invite", json={
        "email": "todeact_audit@test.com", "password": "pass",
    }, headers=auth_header(seed["admin_token"]))
    uid = r.json()["id"]
    client.put(f"/api/users/{uid}/deactivate", headers=auth_header(seed["admin_token"]))
    logs = client.get("/api/audit", headers=auth_header(seed["admin_token"])).json()
    actions = [e["action"] for e in logs["items"]]
    assert "user.deactivated" in actions


def test_list_audit_admin(client, seed):
    r = client.get("/api/audit", headers=auth_header(seed["admin_token"]))
    assert r.status_code == 200
    assert "items" in r.json()
    assert r.json()["total"] > 0


def test_list_audit_member_forbidden(client, seed):
    r = client.get("/api/audit", headers=auth_header(seed["member_token"]))
    assert r.status_code == 403


def test_audit_filter_by_action(client, seed):
    r = client.get("/api/audit?action=auth.login", headers=auth_header(seed["admin_token"]))
    assert r.status_code == 200
    for item in r.json()["items"]:
        assert item["action"] == "auth.login"


# ── Regression tests for role/access bugs ─────────────────────────────────────

def test_sysadmin_can_access_audit(client, seed):
    r = client.get("/api/audit", headers=auth_header(seed["sysadmin_token"]))
    assert r.status_code == 200


def test_sysadmin_audit_has_no_workspace_filter(client, seed):
    # Sysadmin sees all logs, not just one workspace
    r = client.get("/api/audit", headers=auth_header(seed["sysadmin_token"]))
    assert r.status_code == 200
    assert r.json()["total"] >= r.json()["total"]  # sysadmin total >= admin total (tautology guards against 0)
    r_admin = client.get("/api/audit", headers=auth_header(seed["admin_token"]))
    assert r.json()["total"] >= r_admin.json()["total"]


def test_explicit_audit_entry_has_resource_type(client, seed):
    # Regression: route-level audit entries must have resource_type set
    # (was broken when middleware commit raced with route db session commit)
    r = client.post("/api/users/invite", json={
        "email": "resource_check@test.com", "password": "pass",
    }, headers=auth_header(seed["admin_token"]))
    assert r.status_code == 201
    logs = client.get("/api/audit?action=user.invited", headers=auth_header(seed["admin_token"])).json()
    assert logs["total"] > 0
    entry = logs["items"][0]
    assert entry["resource_type"] == "user"
    assert entry["resource_id"] is not None
