"""Spec 68 — Party CRUD + merge, Tag CRUD, normalize_description."""
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
from numis_geek.models.party import Party, PartyAlias
from numis_geek.models.user import User, UserRole
from numis_geek.services.auth import AuthService
from numis_geek.services.normalize import normalize_description
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
    ws = WorkspaceService(db).create("Party WS")
    admin = UserService(db).create(ws.id, "party_admin@test.com", "adminpass", UserRole.admin)
    member = UserService(db).create(ws.id, "party_member@test.com", "memberpass", UserRole.member)
    db.commit()
    db.refresh(ws)
    admin_token = AuthService(db).login("party_admin@test.com", "adminpass")
    member_token = AuthService(db).login("party_member@test.com", "memberpass")
    db.close()
    return {"ws_id": ws.id, "admin_token": admin_token, "member_token": member_token}


def auth(token):
    return {"Authorization": f"Bearer {token}"}


# ── normalize_description ─────────────────────────────────────────────────────

def test_normalize_strips_star_and_uppercases():
    assert normalize_description("Uber *Trip") == "UBER TRIP"


def test_normalize_drops_trailing_digits_and_uf():
    assert normalize_description("Pao Acucar 0042 SP") == "PAO ACUCAR"


def test_normalize_collapses_whitespace():
    assert normalize_description("  NETFLIX   COM  ") == "NETFLIX COM"


def test_normalize_empty():
    assert normalize_description("") == ""
    assert normalize_description(None) == ""


# ── Party CRUD ────────────────────────────────────────────────────────────────

def test_member_cannot_create_party(client, seed):
    r = client.post("/api/parties", json={"name": "Uber"}, headers=auth(seed["member_token"]))
    assert r.status_code == 403


def test_create_and_list_party(client, seed):
    r = client.post("/api/parties", json={"name": "Uber", "kind": "SUPPLIER"}, headers=auth(seed["admin_token"]))
    assert r.status_code == 201
    seed["uber_id"] = r.json()["id"]
    r2 = client.post("/api/parties", json={"name": "Uber Eats", "kind": "SUPPLIER"}, headers=auth(seed["admin_token"]))
    seed["uber_eats_id"] = r2.json()["id"]
    r3 = client.get("/api/parties", headers=auth(seed["admin_token"]))
    assert {p["name"] for p in r3.json()} == {"Uber", "Uber Eats"}


def test_search_filter(client, seed):
    r = client.get("/api/parties?search=eats", headers=auth(seed["admin_token"]))
    assert [p["name"] for p in r.json()] == ["Uber Eats"]


# ── merge ─────────────────────────────────────────────────────────────────────

def test_merge_moves_aliases_and_deletes_source(client, seed):
    # dá um alias pra cada party direto no DB (o import da spec 71 fará isso em produção)
    db = TestSession()
    for pid, alias in ((seed["uber_id"], "UBER TRIP"), (seed["uber_eats_id"], "UBER EATS")):
        db.add(PartyAlias(
            id=str(uuid.uuid4()),
            workspace_id=seed["ws_id"],
            party_id=pid,
            alias_normalized=alias,
            created_at=datetime.now(timezone.utc),
        ))
    db.commit()
    db.close()

    r = client.post(
        f"/api/parties/{seed['uber_id']}/merge",
        json={"source_party_id": seed["uber_eats_id"]},
        headers=auth(seed["admin_token"]),
    )
    assert r.status_code == 200
    assert r.json()["alias_count"] == 2

    db = TestSession()
    assert db.get(Party, seed["uber_eats_id"]) is None
    aliases = db.query(PartyAlias).filter(PartyAlias.party_id == seed["uber_id"]).count()
    assert aliases == 2
    logged = db.query(AuditLog).filter(AuditLog.action == "party.merged").first()
    assert logged is not None
    db.close()


def test_merge_into_itself_422(client, seed):
    r = client.post(
        f"/api/parties/{seed['uber_id']}/merge",
        json={"source_party_id": seed["uber_id"]},
        headers=auth(seed["admin_token"]),
    )
    assert r.status_code == 422


def test_merge_missing_source_404(client, seed):
    r = client.post(
        f"/api/parties/{seed['uber_id']}/merge",
        json={"source_party_id": str(uuid.uuid4())},
        headers=auth(seed["admin_token"]),
    )
    assert r.status_code == 404


# ── Tags ──────────────────────────────────────────────────────────────────────

def test_tag_create_normalizes_lowercase(client, seed):
    r = client.post("/api/tags", json={"name": "  Viagem-Japao-2026 "}, headers=auth(seed["admin_token"]))
    assert r.status_code == 201
    assert r.json()["name"] == "viagem-japao-2026"
    seed["tag_id"] = r.json()["id"]


def test_tag_duplicate_409(client, seed):
    r = client.post("/api/tags", json={"name": "VIAGEM-JAPAO-2026"}, headers=auth(seed["admin_token"]))
    assert r.status_code == 409


def test_tag_rename_and_delete(client, seed):
    r = client.put(f"/api/tags/{seed['tag_id']}", json={"name": "japao-26"}, headers=auth(seed["admin_token"]))
    assert r.status_code == 200
    assert r.json()["name"] == "japao-26"
    r2 = client.delete(f"/api/tags/{seed['tag_id']}", headers=auth(seed["admin_token"]))
    assert r2.status_code == 204
    r3 = client.get("/api/tags", headers=auth(seed["admin_token"]))
    assert r3.json() == []


def test_tag_member_read_only(client, seed):
    r = client.get("/api/tags", headers=auth(seed["member_token"]))
    assert r.status_code == 200
    r2 = client.post("/api/tags", json={"name": "x"}, headers=auth(seed["member_token"]))
    assert r2.status_code == 403
