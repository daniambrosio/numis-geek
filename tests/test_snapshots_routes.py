"""Tests for POST /snapshots — target_ym + auto support (spec 35 hotfix)."""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from numis_geek.api.app import app
from numis_geek.api.deps import get_db
from numis_geek.db.base import Base
import numis_geek.models  # noqa: F401
from numis_geek.models.ptax_rate import PTAXRate
from numis_geek.models.user import UserRole
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
    ws = WorkspaceService(db).create("Snap Routes WS")
    UserService(db).create(ws.id, "snap_admin@test.com", "adminpass", UserRole.admin)
    now = datetime.now(timezone.utc)
    # PTAX rows for all the target period_ends used below — keeps fx_rate
    # non-null on the snapshot so the response always serializes cleanly.
    # PTAX rows seeded a few days before each calendar month-end so
    # fx_rate_on() walks back successfully when period_end falls on a
    # weekend (Jan 31 = Sat, Feb 28 = Sat in 2026).
    db.add_all([
        PTAXRate(id=str(uuid.uuid4()), date=date(2026, 1, 30),
                 rate=Decimal("5.10"), source="BCB_SGS", fetched_at=now),
        PTAXRate(id=str(uuid.uuid4()), date=date(2026, 2, 27),
                 rate=Decimal("5.10"), source="BCB_SGS", fetched_at=now),
        PTAXRate(id=str(uuid.uuid4()), date=date(2026, 3, 31),
                 rate=Decimal("5.10"), source="BCB_SGS", fetched_at=now),
        PTAXRate(id=str(uuid.uuid4()), date=date(2026, 12, 31),
                 rate=Decimal("5.10"), source="BCB_SGS", fetched_at=now),
    ])
    db.commit()
    ws_id = ws.id
    tok = AuthService(db).login("snap_admin@test.com", "adminpass")
    db.close()
    return {"ws_id": ws_id, "admin_tok": tok}


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_post_target_ym_resolves_to_last_calendar_day(client, seed):
    r = client.post(
        "/snapshots",
        json={"target_ym": "2026-01"},
        headers=auth(seed["admin_tok"]),
    )
    assert r.status_code == 201, r.text
    data = r.json()
    # Jan 31, 2026 is Saturday — period_end is still last calendar day.
    assert data["period_end_date"] == "2026-01-31"
    assert data["source"] == "MANUAL"
    assert data["status"] == "CLOSED"


def test_post_target_ym_with_auto_uses_automated_source(client, seed):
    r = client.post(
        "/snapshots",
        json={"target_ym": "2026-02", "auto": True},
        headers=auth(seed["admin_tok"]),
    )
    assert r.status_code == 201, r.text
    data = r.json()
    # Feb 28, 2026 is Saturday — last calendar day.
    assert data["period_end_date"] == "2026-02-28"
    assert data["source"] == "AUTOMATED"


def test_post_period_end_date_still_works(client, seed):
    r = client.post(
        "/snapshots",
        json={"period_end_date": "2026-03-31"},
        headers=auth(seed["admin_tok"]),
    )
    assert r.status_code == 201, r.text
    assert r.json()["period_end_date"] == "2026-03-31"


def test_post_409_when_closed_snapshot_already_exists(client, seed):
    # First POST creates CLOSED. Second POST hits the force_reopen guard.
    body = {"target_ym": "2026-12", "auto": True}
    r1 = client.post("/snapshots", json=body, headers=auth(seed["admin_tok"]))
    assert r1.status_code == 201, r1.text
    r2 = client.post("/snapshots", json=body, headers=auth(seed["admin_tok"]))
    assert r2.status_code == 409, r2.text
    assert "CLOSED" in r2.json()["detail"]


def test_post_400_when_neither_field(client, seed):
    r = client.post("/snapshots", json={}, headers=auth(seed["admin_tok"]))
    assert r.status_code == 400


def test_post_400_when_both_fields(client, seed):
    r = client.post(
        "/snapshots",
        json={"period_end_date": "2026-04-30", "target_ym": "2026-04"},
        headers=auth(seed["admin_tok"]),
    )
    assert r.status_code == 400
