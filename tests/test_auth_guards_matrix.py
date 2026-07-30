"""Auth-guard matrix for sysadmin-only endpoints.

For each endpoint we assert:
- member (any workspace) → 403
- admin (own workspace)  → 403
- admin (other workspace / cross-workspace) → 403
- sysadmin               → 200 (happy path)

Endpoints covered:
- POST /api/sysadmin/backup
- GET  /api/sysadmin/backup
- GET  /api/sysadmin/logs/tail?n=…
- GET  /api/workspaces

Pattern follows tests/test_integrations_routes.py: TestClient against the
real FastAPI app with get_db overridden to a shared in-memory SQLite.
"""
import uuid
from datetime import datetime, timezone
from pathlib import Path
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
from numis_geek.models.user import User, UserRole
from numis_geek.services.auth import AuthService
from numis_geek.services.backup import BackupResult, RotationResult
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
def tokens():
    """Seed the auth matrix (member, admin-A, admin-B, sysadmin) and
    return each user's JWT."""
    db = TestSession()
    ws_a = WorkspaceService(db).create("AuthMatrix WS A")
    ws_b = WorkspaceService(db).create("AuthMatrix WS B")
    UserService(db).create(ws_a.id, "matrix_member_a@t.com", "pw", UserRole.member)
    UserService(db).create(ws_a.id, "matrix_admin_a@t.com", "pw", UserRole.admin)
    UserService(db).create(ws_b.id, "matrix_admin_b@t.com", "pw", UserRole.admin)

    now = datetime.now(timezone.utc)
    sa = User(
        id=str(uuid.uuid4()),
        workspace_id=None,
        email="matrix_sysadmin@t.internal",
        name="SA",
        password_hash=bcrypt.hashpw(b"pw", bcrypt.gensalt()).decode(),
        role=UserRole.sysadmin,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(sa)
    db.commit()

    svc = AuthService(db)
    out = {
        "member_a": svc.login("matrix_member_a@t.com", "pw"),
        "admin_a": svc.login("matrix_admin_a@t.com", "pw"),
        "admin_b": svc.login("matrix_admin_b@t.com", "pw"),
        "sysadmin": svc.login("matrix_sysadmin@t.internal", "pw"),
    }
    db.close()
    return out


def _h(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


NON_SYSADMIN_ROLES = ["member_a", "admin_a", "admin_b"]


# ---------- POST /api/sysadmin/backup ----------

@pytest.mark.parametrize("role", NON_SYSADMIN_ROLES)
def test_post_backup_forbidden_for_non_sysadmin(client, tokens, role):
    r = client.post("/api/sysadmin/backup", headers=_h(tokens[role]))
    assert r.status_code == 403, r.text


def test_post_backup_requires_auth(client):
    r = client.post("/api/sysadmin/backup")
    # HTTPBearer(auto_error=True) → 401 or 403 depending on FastAPI version.
    assert r.status_code in (401, 403)


def test_post_backup_ok_for_sysadmin(client, tokens):
    fake = BackupResult(
        path=Path("data/backups/x.db"), size_bytes=100,
        duration_ms=1, pages_copied=1,
    )
    with patch(
        "numis_geek.api.routes.backup.create_backup", return_value=fake,
    ), patch(
        "numis_geek.api.routes.backup.rotate_backups",
        return_value=RotationResult(kept=[Path("x.db")], deleted=[]),
    ):
        r = client.post("/api/sysadmin/backup", headers=_h(tokens["sysadmin"]))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["filename"] == "x.db"
    assert body["kept_count"] == 1
    assert body["deleted_count"] == 0


# ---------- GET /api/sysadmin/backup ----------

@pytest.mark.parametrize("role", NON_SYSADMIN_ROLES)
def test_list_backups_forbidden_for_non_sysadmin(client, tokens, role):
    r = client.get("/api/sysadmin/backup", headers=_h(tokens[role]))
    assert r.status_code == 403, r.text


def test_list_backups_ok_for_sysadmin_missing_dir(
    client, tokens, tmp_path, monkeypatch,
):
    monkeypatch.setattr(
        "numis_geek.api.routes.backup.BACKUP_DIR", tmp_path / "nope",
    )
    r = client.get("/api/sysadmin/backup", headers=_h(tokens["sysadmin"]))
    assert r.status_code == 200
    body = r.json()
    assert body["items"] == []
    assert body["total_bytes"] == 0


def test_list_backups_ok_for_sysadmin_lists_files(
    client, tokens, tmp_path, monkeypatch,
):
    d = tmp_path / "backups"
    d.mkdir()
    (d / "numis_geek-20260101-070000.db").write_bytes(b"x" * 42)
    (d / "not-a-backup.txt").write_text("ignore me")
    monkeypatch.setattr("numis_geek.api.routes.backup.BACKUP_DIR", d)
    r = client.get("/api/sysadmin/backup", headers=_h(tokens["sysadmin"]))
    assert r.status_code == 200
    body = r.json()
    names = [it["filename"] for it in body["items"]]
    assert "numis_geek-20260101-070000.db" in names
    assert "not-a-backup.txt" not in names
    assert body["total_bytes"] == 42


# ---------- GET /api/sysadmin/logs/tail ----------

@pytest.mark.parametrize("role", NON_SYSADMIN_ROLES)
def test_logs_tail_forbidden_for_non_sysadmin(client, tokens, role):
    r = client.get(
        "/api/sysadmin/logs/tail?n=10",
        headers=_h(tokens[role]),
    )
    assert r.status_code == 403, r.text


def test_logs_tail_404_when_no_file_logging(client, tokens, monkeypatch):
    monkeypatch.delenv("LOG_DIR", raising=False)
    r = client.get(
        "/api/sysadmin/logs/tail?n=10",
        headers=_h(tokens["sysadmin"]),
    )
    assert r.status_code == 404


def test_logs_tail_ok_returns_last_n_lines(
    client, tokens, tmp_path, monkeypatch,
):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "numis.log").write_text(
        "\n".join(f"line-{i}" for i in range(100)) + "\n",
    )
    monkeypatch.setenv("LOG_DIR", str(log_dir))
    r = client.get(
        "/api/sysadmin/logs/tail?n=5",
        headers=_h(tokens["sysadmin"]),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["lines"]) == 5
    assert body["lines"][-1] == "line-99"
    assert body["size_bytes"] > 0


@pytest.mark.parametrize("bad_n", [0, 5000])
def test_logs_tail_rejects_out_of_range_n(client, tokens, bad_n):
    # Query is defined as ge=1, le=2000 — anything outside is a 422.
    r = client.get(
        f"/api/sysadmin/logs/tail?n={bad_n}",
        headers=_h(tokens["sysadmin"]),
    )
    assert r.status_code == 422


# ---------- GET /api/workspaces ----------

@pytest.mark.parametrize("role", NON_SYSADMIN_ROLES)
def test_list_workspaces_forbidden_for_non_sysadmin(client, tokens, role):
    r = client.get("/api/workspaces", headers=_h(tokens[role]))
    assert r.status_code == 403, r.text


def test_list_workspaces_ok_for_sysadmin(client, tokens):
    r = client.get("/api/workspaces", headers=_h(tokens["sysadmin"]))
    assert r.status_code == 200
    names = [w["name"] for w in r.json()]
    assert "AuthMatrix WS A" in names
    assert "AuthMatrix WS B" in names


def test_list_workspaces_requires_auth(client):
    r = client.get("/api/workspaces")
    assert r.status_code in (401, 403)
