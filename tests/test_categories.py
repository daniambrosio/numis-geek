"""Spec 68 — Category CRUD, hierarchy rules, workspace scoping."""
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
    ws = WorkspaceService(db).create("Cat WS")
    ws2 = WorkspaceService(db).create("Cat WS 2")
    admin = UserService(db).create(ws.id, "cat_admin@test.com", "adminpass", UserRole.admin)
    member = UserService(db).create(ws.id, "cat_member@test.com", "memberpass", UserRole.member)
    admin2 = UserService(db).create(ws2.id, "cat_admin2@test.com", "adminpass", UserRole.admin)

    now = datetime.now(timezone.utc)
    sysadmin = User(
        id=str(uuid.uuid4()),
        workspace_id=None,
        email="cat_sysadmin@test.internal",
        name="SysAdmin",
        password_hash=bcrypt.hashpw(b"syspass", bcrypt.gensalt()).decode(),
        role=UserRole.sysadmin,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(sysadmin)
    db.commit()
    db.refresh(ws); db.refresh(ws2)

    admin_token = AuthService(db).login("cat_admin@test.com", "adminpass")
    member_token = AuthService(db).login("cat_member@test.com", "memberpass")
    admin2_token = AuthService(db).login("cat_admin2@test.com", "adminpass")
    sysadmin_token = AuthService(db).login("cat_sysadmin@test.internal", "syspass")
    db.close()
    return {
        "ws_id": ws.id,
        "ws2_id": ws2.id,
        "admin_token": admin_token,
        "member_token": member_token,
        "admin2_token": admin2_token,
        "sysadmin_token": sysadmin_token,
    }


def auth(token):
    return {"Authorization": f"Bearer {token}"}


# ── CRUD básico ───────────────────────────────────────────────────────────────

def test_member_cannot_create(client, seed):
    r = client.post("/api/categories", json={"name": "Casa", "kind": "EXPENSE"}, headers=auth(seed["member_token"]))
    assert r.status_code == 403


def test_create_root_requires_kind(client, seed):
    r = client.post("/api/categories", json={"name": "Mercado"}, headers=auth(seed["admin_token"]))
    assert r.status_code == 422


def test_create_root(client, seed):
    r = client.post("/api/categories", json={"name": "Casa", "kind": "EXPENSE", "color": "#8b5cf6"}, headers=auth(seed["admin_token"]))
    assert r.status_code == 201
    data = r.json()
    assert data["kind"] == "EXPENSE"
    assert data["parent_id"] is None
    seed["casa_id"] = data["id"]


def test_create_subcategory_inherits_kind_and_color(client, seed):
    r = client.post("/api/categories", json={"name": "Energia", "parent_id": seed["casa_id"]}, headers=auth(seed["admin_token"]))
    assert r.status_code == 201
    data = r.json()
    assert data["kind"] == "EXPENSE"
    assert data["color"] == "#8b5cf6"
    seed["energia_id"] = data["id"]


def test_no_second_nesting_level(client, seed):
    r = client.post("/api/categories", json={"name": "Sub-sub", "parent_id": seed["energia_id"]}, headers=auth(seed["admin_token"]))
    assert r.status_code == 422


def test_duplicate_name_same_parent_409(client, seed):
    r = client.post("/api/categories", json={"name": "Casa", "kind": "INCOME"}, headers=auth(seed["admin_token"]))
    assert r.status_code == 409


def test_homonym_under_different_parent_ok(client, seed):
    # "Energia" já existe sob Casa; raiz "Energia" é legal (unicidade por parent)
    r = client.post("/api/categories", json={"name": "Energia", "kind": "EXPENSE"}, headers=auth(seed["admin_token"]))
    assert r.status_code == 201


def test_subcategory_kind_override_on_create(client, seed):
    # Decisão 2026-08-09: raízes mistas — sub pode declarar kind próprio.
    r = client.post(
        "/api/categories",
        json={"name": "Venda Usados", "parent_id": seed["casa_id"], "kind": "INCOME"},
        headers=auth(seed["admin_token"]),
    )
    assert r.status_code == 201
    assert r.json()["kind"] == "INCOME"
    seed["venda_id"] = r.json()["id"]


def test_subcategory_kind_editable(client, seed):
    r = client.put(f"/api/categories/{seed['energia_id']}", json={"kind": "INCOME"}, headers=auth(seed["admin_token"]))
    assert r.status_code == 200
    assert r.json()["kind"] == "INCOME"
    # volta
    client.put(f"/api/categories/{seed['energia_id']}", json={"kind": "EXPENSE"}, headers=auth(seed["admin_token"]))


def test_root_kind_change_does_not_cascade(client, seed):
    # Com overrides por sub, mudar a raiz NÃO reescreve as filhas.
    r = client.put(f"/api/categories/{seed['casa_id']}", json={"kind": "INCOME"}, headers=auth(seed["admin_token"]))
    assert r.status_code == 200
    r2 = client.get("/api/categories", headers=auth(seed["admin_token"]))
    kinds = {c["id"]: c["kind"] for c in r2.json()}
    assert kinds[seed["energia_id"]] == "EXPENSE"   # manteve o próprio kind
    assert kinds[seed["venda_id"]] == "INCOME"      # override preservado
    # volta
    client.put(f"/api/categories/{seed['casa_id']}", json={"kind": "EXPENSE"}, headers=auth(seed["admin_token"]))


def test_deactivate_cascades_children(client, seed):
    r = client.put(f"/api/categories/{seed['casa_id']}/deactivate", headers=auth(seed["admin_token"]))
    assert r.status_code == 200
    r2 = client.get("/api/categories", headers=auth(seed["admin_token"]))
    ids = {c["id"] for c in r2.json()}
    assert seed["casa_id"] not in ids
    assert seed["energia_id"] not in ids
    r3 = client.get("/api/categories?include_inactive=true", headers=auth(seed["admin_token"]))
    ids3 = {c["id"] for c in r3.json()}
    assert seed["casa_id"] in ids3


# ── scoping ───────────────────────────────────────────────────────────────────

def test_other_workspace_cannot_see(client, seed):
    r = client.get("/api/categories", headers=auth(seed["admin2_token"]))
    assert r.status_code == 200
    assert all(c["workspace_id"] == seed["ws2_id"] for c in r.json())
    assert len(r.json()) == 0


def test_other_workspace_cannot_edit(client, seed):
    r = client.put(f"/api/categories/{seed['energia_id']}", json={"name": "Hack"}, headers=auth(seed["admin2_token"]))
    assert r.status_code == 404


def test_sysadmin_scopes_by_query_param(client, seed):
    r = client.get(f"/api/categories?workspace_id={seed['ws_id']}&include_inactive=true", headers=auth(seed["sysadmin_token"]))
    assert r.status_code == 200
    assert len(r.json()) >= 2
    r2 = client.post(
        f"/api/categories?workspace_id={seed['ws2_id']}",
        json={"name": "SysCat", "kind": "EXPENSE"},
        headers=auth(seed["sysadmin_token"]),
    )
    assert r2.status_code == 201
    assert r2.json()["workspace_id"] == seed["ws2_id"]
