"""Spec 69 — CreditCardAccount CRUD + Invoice lifecycle."""
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
    ws = WorkspaceService(db).create("CC WS")
    ws2 = WorkspaceService(db).create("CC WS 2")
    admin = UserService(db).create(ws.id, "cc_admin@test.com", "adminpass", UserRole.admin)
    member = UserService(db).create(ws.id, "cc_member@test.com", "memberpass", UserRole.member)
    admin2 = UserService(db).create(ws2.id, "cc_admin2@test.com", "adminpass", UserRole.admin)

    now = datetime.now(timezone.utc)
    fi = FinancialInstitution(
        id=str(uuid.uuid4()),
        long_name="Banco CC S.A.",
        short_name="BCC",
        logo_slug=None,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(fi)
    db.commit()
    db.refresh(ws); db.refresh(ws2); db.refresh(fi)
    admin_token = AuthService(db).login("cc_admin@test.com", "adminpass")
    member_token = AuthService(db).login("cc_member@test.com", "memberpass")
    admin2_token = AuthService(db).login("cc_admin2@test.com", "adminpass")
    db.close()
    return {
        "ws_id": ws.id,
        "fi_id": fi.id,
        "admin_token": admin_token,
        "member_token": member_token,
        "admin2_token": admin2_token,
    }


def auth(token):
    return {"Authorization": f"Bearer {token}"}


# ── card CRUD ─────────────────────────────────────────────────────────────────

def test_member_cannot_create_card(client, seed):
    r = client.post("/api/credit-cards", json={
        "name": "X", "financial_institution_id": seed["fi_id"], "currency": "BRL",
        "close_day": 5, "due_day": 15,
    }, headers=auth(seed["member_token"]))
    assert r.status_code == 403


def test_create_card(client, seed):
    r = client.post("/api/credit-cards", json={
        "name": "BCC Visa Infinite", "financial_institution_id": seed["fi_id"],
        "currency": "BRL", "brand": "Visa", "last4": "4421",
        "credit_limit": "35000", "close_day": 5, "due_day": 15,
    }, headers=auth(seed["admin_token"]))
    assert r.status_code == 201
    data = r.json()
    assert data["open_invoice_total"] == 0
    assert data["limit_used_pct"] == 0
    assert data["financial_institution_name"] == "BCC"
    seed["card_id"] = data["id"]


def test_close_day_out_of_range(client, seed):
    r = client.post("/api/credit-cards", json={
        "name": "Bad", "financial_institution_id": seed["fi_id"], "currency": "BRL",
        "close_day": 31, "due_day": 15,
    }, headers=auth(seed["admin_token"]))
    assert r.status_code == 422


def test_other_workspace_cannot_see_card(client, seed):
    r = client.get("/api/credit-cards", headers=auth(seed["admin2_token"]))
    assert r.json() == []
    r2 = client.put(f"/api/credit-cards/{seed['card_id']}", json={
        "name": "Hack", "financial_institution_id": seed["fi_id"], "currency": "BRL",
        "close_day": 5, "due_day": 15,
    }, headers=auth(seed["admin2_token"]))
    assert r2.status_code == 404


# ── invoice lifecycle ─────────────────────────────────────────────────────────

def test_create_invoice(client, seed):
    r = client.post(f"/api/credit-cards/{seed['card_id']}/invoices", json={
        "close_date": "2026-08-05", "due_date": "2026-08-15",
    }, headers=auth(seed["admin_token"]))
    assert r.status_code == 201
    data = r.json()
    assert data["status"] == "OPEN"
    assert data["total_amount"] is None
    assert data["currency"] == "BRL"
    seed["inv_id"] = data["id"]


def test_duplicate_close_date_409(client, seed):
    r = client.post(f"/api/credit-cards/{seed['card_id']}/invoices", json={
        "close_date": "2026-08-05", "due_date": "2026-08-20",
    }, headers=auth(seed["admin_token"]))
    assert r.status_code == 409


def test_due_before_close_422(client, seed):
    r = client.post(f"/api/credit-cards/{seed['card_id']}/invoices", json={
        "close_date": "2026-09-05", "due_date": "2026-09-01",
    }, headers=auth(seed["admin_token"]))
    assert r.status_code == 422


def test_open_invoice_total_flows_to_card(client, seed):
    # invoice OPEN com total manual reflete no derived do cartão
    client.post(f"/api/invoices/{seed['inv_id']}/close", json={}, headers=auth(seed["admin_token"]))  # sem total → 422, invoice segue OPEN
    r = client.post(f"/api/credit-cards/{seed['card_id']}/invoices", json={
        "close_date": "2026-09-05", "due_date": "2026-09-15", "total_amount": "1000",
    }, headers=auth(seed["admin_token"]))
    assert r.status_code == 201
    r2 = client.get("/api/credit-cards", headers=auth(seed["admin_token"]))
    card = next(c for c in r2.json() if c["id"] == seed["card_id"])
    assert card["open_invoice_total"] == 1000.0
    assert abs(card["limit_used_pct"] - 1000.0 / 35000.0) < 1e-9


def test_close_requires_total_for_now(client, seed):
    r = client.post(f"/api/invoices/{seed['inv_id']}/close", json={}, headers=auth(seed["admin_token"]))
    assert r.status_code == 422


def test_close_with_total(client, seed):
    r = client.post(f"/api/invoices/{seed['inv_id']}/close", json={"total_amount": "6842.30"}, headers=auth(seed["admin_token"]))
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "CLOSED"
    assert data["total_amount"] == 6842.30


def test_close_twice_409(client, seed):
    r = client.post(f"/api/invoices/{seed['inv_id']}/close", json={"total_amount": "6842.30"}, headers=auth(seed["admin_token"]))
    assert r.status_code == 409


def test_negative_total_422(client, seed):
    r = client.post(f"/api/credit-cards/{seed['card_id']}/invoices", json={
        "close_date": "2026-10-05", "due_date": "2026-10-15", "total_amount": "-50",
    }, headers=auth(seed["admin_token"]))
    assert r.status_code == 422


def test_list_invoices_filters(client, seed):
    r = client.get("/api/invoices?status=CLOSED", headers=auth(seed["admin_token"]))
    assert all(i["status"] == "CLOSED" for i in r.json())
    assert len(r.json()) == 1
    r2 = client.get(f"/api/invoices?card_id={seed['card_id']}", headers=auth(seed["admin_token"]))
    assert len(r2.json()) == 2
    r3 = client.get("/api/invoices?status=NOPE", headers=auth(seed["admin_token"]))
    assert r3.status_code == 422


def test_cannot_deactivate_card_with_open_invoices(client, seed):
    r = client.put(f"/api/credit-cards/{seed['card_id']}/deactivate", headers=auth(seed["admin_token"]))
    assert r.status_code == 409
