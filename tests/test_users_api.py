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

# StaticPool forces a single shared connection so all sessions (seed + requests) see the same data
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
    ws = WorkspaceService(db).create("Test WS")
    admin = UserService(db).create(ws.id, "admin@test.com", "adminpass", UserRole.admin)
    member = UserService(db).create(ws.id, "member@test.com", "memberpass", UserRole.member)

    now = datetime.now(timezone.utc)
    sysadmin = User(
        id=str(uuid.uuid4()),
        workspace_id=None,
        email="sysadmin@test.internal",
        name="SysAdmin",
        password_hash=bcrypt.hashpw(b"syspass", bcrypt.gensalt()).decode(),
        role=UserRole.sysadmin,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(sysadmin)
    db.commit()
    db.refresh(ws)
    db.refresh(admin)
    db.refresh(member)
    db.refresh(sysadmin)
    ws_id, admin_id, member_id, sysadmin_id = ws.id, admin.id, member.id, sysadmin.id
    admin_token = AuthService(db).login("admin@test.com", "adminpass")
    member_token = AuthService(db).login("member@test.com", "memberpass")
    sysadmin_token = AuthService(db).login("sysadmin@test.internal", "syspass")
    db.close()
    return {
        "ws_id": ws_id,
        "admin_id": admin_id,
        "member_id": member_id,
        "sysadmin_id": sysadmin_id,
        "admin_token": admin_token,
        "member_token": member_token,
        "sysadmin_token": sysadmin_token,
    }


def auth_header(token):
    return {"Authorization": f"Bearer {token}"}


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_list_users_admin(client, seed):
    r = client.get("/api/users", headers=auth_header(seed["admin_token"]))
    assert r.status_code == 200
    emails = [u["email"] for u in r.json()]
    assert "admin@test.com" in emails
    assert "member@test.com" in emails


def test_list_users_member_forbidden(client, seed):
    r = client.get("/api/users", headers=auth_header(seed["member_token"]))
    assert r.status_code == 403


def test_invite_user(client, seed):
    r = client.post("/api/users/invite", json={
        "email": "invited@test.com",
        "name": "Novo Usuário",
        "password": "pass123",
        "role": "member",
    }, headers=auth_header(seed["admin_token"]))
    assert r.status_code == 201
    assert r.json()["email"] == "invited@test.com"
    assert r.json()["name"] == "Novo Usuário"


def test_change_role(client, seed):
    member_id = seed["member_id"]
    r = client.put(f"/api/users/{member_id}/role", json={"role": "admin"}, headers=auth_header(seed["admin_token"]))
    assert r.status_code == 200
    assert r.json()["role"] == "admin"
    # restore
    client.put(f"/api/users/{member_id}/role", json={"role": "member"}, headers=auth_header(seed["admin_token"]))


def test_deactivate_user(client, seed):
    r = client.post("/api/users/invite", json={
        "email": "todeactivate@test.com",
        "password": "pass",
    }, headers=auth_header(seed["admin_token"]))
    user_id = r.json()["id"]
    r2 = client.put(f"/api/users/{user_id}/deactivate", headers=auth_header(seed["admin_token"]))
    assert r2.status_code == 200
    assert r2.json()["is_active"] is False


def test_get_me(client, seed):
    r = client.get("/api/users/me", headers=auth_header(seed["member_token"]))
    assert r.status_code == 200
    assert r.json()["email"] == "member@test.com"


def test_update_name(client, seed):
    r = client.put("/api/users/me", json={"name": "Daniel"}, headers=auth_header(seed["member_token"]))
    assert r.status_code == 200
    assert r.json()["name"] == "Daniel"


def test_change_password_success(client, seed):
    r = client.put("/api/users/me/password", json={
        "current_password": "memberpass",
        "new_password": "newpass123",
    }, headers=auth_header(seed["member_token"]))
    assert r.status_code == 204


def test_change_password_wrong_current(client, seed):
    r = client.put("/api/users/me/password", json={
        "current_password": "wrongpass",
        "new_password": "irrelevant",
    }, headers=auth_header(seed["admin_token"]))
    assert r.status_code == 400


# ── Regression tests ──────────────────────────────────────────────────────────

def test_sysadmin_can_list_users(client, seed):
    r = client.get("/api/users", headers=auth_header(seed["sysadmin_token"]))
    assert r.status_code == 200
    emails = [u["email"] for u in r.json()]
    assert "admin@test.com" in emails
    assert "member@test.com" in emails
    assert "sysadmin@test.internal" in emails


def test_sysadmin_sees_workspace_name_for_users(client, seed):
    r = client.get("/api/users", headers=auth_header(seed["sysadmin_token"]))
    assert r.status_code == 200
    users = {u["email"]: u for u in r.json()}
    assert users["admin@test.com"]["workspace_name"] == "Test WS"
    assert users["sysadmin@test.internal"]["workspace_name"] is None


def test_update_user_name_admin(client, seed):
    member_id = seed["member_id"]
    r = client.put(f"/api/users/{member_id}/name", json={"name": "Updated Name"},
                   headers=auth_header(seed["admin_token"]))
    assert r.status_code == 200
    assert r.json()["name"] == "Updated Name"


def test_update_user_name_sysadmin(client, seed):
    admin_id = seed["admin_id"]
    r = client.put(f"/api/users/{admin_id}/name", json={"name": "Admin Renamed"},
                   headers=auth_header(seed["sysadmin_token"]))
    assert r.status_code == 200
    assert r.json()["name"] == "Admin Renamed"


def test_update_user_name_member_forbidden(client, seed):
    admin_id = seed["admin_id"]
    r = client.put(f"/api/users/{admin_id}/name", json={"name": "Hacked"},
                   headers=auth_header(seed["member_token"]))
    assert r.status_code == 403


def test_updated_name_visible_in_list(client, seed):
    member_id = seed["member_id"]
    client.put(f"/api/users/{member_id}/name", json={"name": "FinalName"},
               headers=auth_header(seed["admin_token"]))
    r = client.get("/api/users", headers=auth_header(seed["admin_token"]))
    users = {u["id"]: u for u in r.json()}
    assert users[member_id]["name"] == "FinalName"
