"""Tests for /sysadmin/integrations CRUD + masking + role guard."""
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
    ws = WorkspaceService(db).create("Integration Test WS")
    admin = UserService(db).create(ws.id, "int_admin@test.com", "adminpass", UserRole.admin)

    now = datetime.now(timezone.utc)
    sysadmin = User(
        id=str(uuid.uuid4()),
        workspace_id=None,
        email="int_sysadmin@test.internal",
        name="SA",
        password_hash=bcrypt.hashpw(b"syspass", bcrypt.gensalt()).decode(),
        role=UserRole.sysadmin,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(sysadmin)
    db.commit()

    admin_tok = AuthService(db).login("int_admin@test.com", "adminpass")
    sys_tok = AuthService(db).login("int_sysadmin@test.internal", "syspass")
    db.close()
    return {"admin_tok": admin_tok, "sys_tok": sys_tok}


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_list_credentials_requires_sysadmin(client, seed):
    r = client.get("/sysadmin/integrations", headers=auth(seed["admin_tok"]))
    assert r.status_code == 403


def test_providers_listed(client, seed):
    r = client.get("/sysadmin/integrations/providers", headers=auth(seed["sys_tok"]))
    assert r.status_code == 200
    providers = [p["provider"] for p in r.json()]
    assert {"BCB", "BRAPI", "FINNHUB", "YFINANCE"}.issubset(set(providers))


def test_create_and_mask_credential(client, seed):
    r = client.post(
        "/sysadmin/integrations",
        headers=auth(seed["sys_tok"]),
        json={
            "provider": "FINNHUB",
            "key_name": "API_TOKEN",
            "label": "Main Finnhub token",
            "secret_value": "abcd1234secrettokenxyz",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["provider"] == "FINNHUB"
    assert body["secret_preview"].startswith("••••")
    assert "secrettokenxyz"[-4:] in body["secret_preview"]
    assert "abcd1234secrettokenxyz" not in body["secret_preview"]


def test_duplicate_credential_rejected(client, seed):
    payload = {
        "provider": "BRAPI",
        "key_name": "API_TOKEN",
        "label": "x",
        "secret_value": "tokenA",
    }
    r1 = client.post("/sysadmin/integrations", headers=auth(seed["sys_tok"]), json=payload)
    assert r1.status_code == 201
    r2 = client.post("/sysadmin/integrations", headers=auth(seed["sys_tok"]), json=payload)
    assert r2.status_code == 409


def test_patch_credential_resets_test_state(client, seed):
    r = client.post(
        "/sysadmin/integrations",
        headers=auth(seed["sys_tok"]),
        json={"provider": "FINNHUB", "key_name": "ALT_TOKEN", "secret_value": "old"},
    )
    cid = r.json()["id"]
    r2 = client.patch(
        f"/sysadmin/integrations/{cid}",
        headers=auth(seed["sys_tok"]),
        json={"secret_value": "newvalue1234"},
    )
    assert r2.status_code == 200
    assert r2.json()["last_test_result"] == "UNTESTED"


def test_delete_credential(client, seed):
    r = client.post(
        "/sysadmin/integrations",
        headers=auth(seed["sys_tok"]),
        json={"provider": "BRAPI", "key_name": "TO_DELETE", "secret_value": "x"},
    )
    cid = r.json()["id"]
    r2 = client.delete(f"/sysadmin/integrations/{cid}", headers=auth(seed["sys_tok"]))
    assert r2.status_code == 204
