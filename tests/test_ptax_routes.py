"""Tests for /sysadmin/ptax routes."""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import patch

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
from numis_geek.integrations.bcb import PTAXRow
from numis_geek.models.ptax_rate import PTAXRate
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
    ws = WorkspaceService(db).create("PTAX Test WS")
    admin = UserService(db).create(ws.id, "ptx_admin@test.com", "adminpass", UserRole.admin)

    now = datetime.now(timezone.utc)
    sysadmin = User(
        id=str(uuid.uuid4()),
        workspace_id=None,
        email="ptx_sysadmin@test.internal",
        name="SA",
        password_hash=bcrypt.hashpw(b"syspass", bcrypt.gensalt()).decode(),
        role=UserRole.sysadmin,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(sysadmin)
    db.commit()

    admin_tok = AuthService(db).login("ptx_admin@test.com", "adminpass")
    sys_tok = AuthService(db).login("ptx_sysadmin@test.internal", "syspass")

    # Seed a few PTAX rows
    db.add_all([
        PTAXRate(date=date(2026, 5, 13), rate=Decimal("4.9112"),
                 source="BCB_SGS", fetched_at=now),
        PTAXRate(date=date(2026, 5, 14), rate=Decimal("4.9803"),
                 source="BCB_SGS", fetched_at=now),
        PTAXRate(date=date(2026, 5, 15), rate=Decimal("5.0648"),
                 source="BCB_SGS", fetched_at=now),
    ])
    db.commit()
    db.close()
    return {"admin_tok": admin_tok, "sys_tok": sys_tok}


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_status_requires_sysadmin(client, seed):
    r = client.get("/sysadmin/ptax/status", headers=auth(seed["admin_tok"]))
    assert r.status_code == 403


def test_status_returns_counts(client, seed):
    r = client.get("/sysadmin/ptax/status", headers=auth(seed["sys_tok"]))
    assert r.status_code == 200
    body = r.json()
    assert body["total_rows"] >= 3
    assert body["last_date"] == "2026-05-15"
    assert body["oldest_date"] == "2026-05-13"


def test_list_paginated_desc(client, seed):
    r = client.get("/sysadmin/ptax?page=1&page_size=2", headers=auth(seed["sys_tok"]))
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 2
    assert body["items"][0]["date"] == "2026-05-15"


def test_sync_route_calls_service(client, seed):
    captured = []

    def fake_sync(db, *, mode):
        captured.append(mode)
        from numis_geek.services.ptax_sync import PtaxSyncResult
        return PtaxSyncResult(
            mode=mode, fetched_count=0, inserted_count=0, updated_count=0,
            range_start=date(2026, 5, 18), range_end=date(2026, 5, 18), duration_ms=42,
        )

    with patch("numis_geek.api.routes.ptax.sync_ptax", side_effect=fake_sync):
        r = client.post(
            "/sysadmin/ptax/sync",
            headers=auth(seed["sys_tok"]),
            json={"mode": "incremental"},
        )
    assert r.status_code == 200
    assert captured == ["incremental"]
    assert r.json()["duration_ms"] == 42
