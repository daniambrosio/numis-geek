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

    ws = WorkspaceService(db).create("IF Test WS")
    admin = UserService(db).create(ws.id, "if_admin@test.com", "adminpass", UserRole.admin)

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
    db.refresh(sysadmin)

    admin_token = AuthService(db).login("if_admin@test.com", "adminpass")
    sysadmin_token = AuthService(db).login("sysadmin@test.internal", "syspass")

    ws_id = ws.id
    admin_id = admin.id
    sysadmin_id = sysadmin.id
    db.close()

    return {
        "ws_id": ws_id,
        "admin_id": admin_id,
        "sysadmin_id": sysadmin_id,
        "admin_token": admin_token,
        "sysadmin_token": sysadmin_token,
    }


def auth(token):
    return {"Authorization": f"Bearer {token}"}


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_list_empty_authenticated(client, seed):
    r = client.get("/financial-institutions", headers=auth(seed["admin_token"]))
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_create_fi_sysadmin(client, seed):
    r = client.post("/financial-institutions", json={
        "long_name": "Banco Teste S.A.",
        "short_name": "Teste",
        "logo_slug": "teste",
    }, headers=auth(seed["sysadmin_token"]))
    assert r.status_code == 201
    data = r.json()
    assert data["long_name"] == "Banco Teste S.A."
    assert data["short_name"] == "Teste"
    assert data["is_active"] is True
    seed["fi_id"] = data["id"]


def test_create_fi_admin_forbidden(client, seed):
    r = client.post("/financial-institutions", json={
        "long_name": "Not Allowed",
        "short_name": "NA",
    }, headers=auth(seed["admin_token"]))
    assert r.status_code == 403


def test_list_shows_created(client, seed):
    r = client.get("/financial-institutions", headers=auth(seed["admin_token"]))
    assert r.status_code == 200
    short_names = [fi["short_name"] for fi in r.json()]
    assert "Teste" in short_names


def test_update_fi(client, seed):
    fi_id = seed["fi_id"]
    r = client.put(f"/financial-institutions/{fi_id}", json={
        "long_name": "Banco Teste Atualizado S.A.",
        "short_name": "Teste2",
        "logo_slug": "teste2",
    }, headers=auth(seed["sysadmin_token"]))
    assert r.status_code == 200
    assert r.json()["short_name"] == "Teste2"


def test_deactivate_fi(client, seed):
    fi_id = seed["fi_id"]
    r = client.put(f"/financial-institutions/{fi_id}/deactivate", headers=auth(seed["sysadmin_token"]))
    assert r.status_code == 200
    assert r.json()["is_active"] is False


def test_deactivated_excluded_from_list(client, seed):
    r = client.get("/financial-institutions", headers=auth(seed["admin_token"]))
    ids = [fi["id"] for fi in r.json()]
    assert seed["fi_id"] not in ids


def test_deactivate_admin_forbidden(client, seed):
    # Create a fresh IF to try to deactivate
    r_create = client.post("/financial-institutions", json={
        "long_name": "Banco Guard",
        "short_name": "Guard",
    }, headers=auth(seed["sysadmin_token"]))
    fi_id = r_create.json()["id"]
    r = client.put(f"/financial-institutions/{fi_id}/deactivate", headers=auth(seed["admin_token"]))
    assert r.status_code == 403


# ── Spec 19: country (ISO-2) ─────────────────────────────────────────────────

def test_create_fi_with_country(client, seed):
    r = client.post("/financial-institutions", json={
        "long_name": "Avenue Securities",
        "short_name": "Avenue-T",
        "country": "US",
    }, headers=auth(seed["sysadmin_token"]))
    assert r.status_code == 201
    assert r.json()["country"] == "US"


def test_country_defaults_to_br_when_omitted(client, seed):
    r = client.post("/financial-institutions", json={
        "long_name": "Banco BR S.A.",
        "short_name": "BR-Default",
    }, headers=auth(seed["sysadmin_token"]))
    assert r.status_code == 201
    assert r.json()["country"] == "BR"


def test_update_changes_country(client, seed):
    r = client.post("/financial-institutions", json={
        "long_name": "Some FI",
        "short_name": "Some-FI",
        "country": "BR",
    }, headers=auth(seed["sysadmin_token"]))
    fi_id = r.json()["id"]
    r2 = client.put(f"/financial-institutions/{fi_id}", json={
        "long_name": "Some FI",
        "short_name": "Some-FI",
        "country": "US",
    }, headers=auth(seed["sysadmin_token"]))
    assert r2.status_code == 200
    assert r2.json()["country"] == "US"
