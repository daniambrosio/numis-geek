"""Spec 19 — attachment upload / list / download / delete tests.

Covers: MIME whitelist, size limit, source validation, workspace isolation,
sysadmin cross-workspace, soft-delete behavior, path-traversal safety.
"""
import io
import shutil
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

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
from numis_geek.models.account import Account, AccountType, Currency
from numis_geek.models.asset import Asset, AssetClass
from numis_geek.models.asset_movement import AssetMovement, AssetMovementType
from numis_geek.models.attachment import Attachment
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.user import User, UserRole
from numis_geek.services import attachment_storage
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


@pytest.fixture(scope="module", autouse=True)
def tmp_attachment_root(tmp_path_factory):
    """Redirect filesystem writes to a module-shared temp dir, so files
    written in test_upload_* survive for test_download_* / test_list_*."""
    target = tmp_path_factory.mktemp("attachments")
    original = attachment_storage.ROOT
    attachment_storage.ROOT = target
    yield target
    attachment_storage.ROOT = original
    shutil.rmtree(target, ignore_errors=True)


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
    ws_a = WorkspaceService(db).create("Att WS A")
    ws_b = WorkspaceService(db).create("Att WS B")

    admin_a = UserService(db).create(ws_a.id, "att_admin_a@test.com", "adminpass", UserRole.admin)
    admin_b = UserService(db).create(ws_b.id, "att_admin_b@test.com", "adminpass", UserRole.admin)

    now = datetime.now(timezone.utc)
    sysadmin = User(
        id=str(uuid.uuid4()),
        workspace_id=None,
        email="att_sysadmin@test.internal",
        name="SysAdmin",
        password_hash=bcrypt.hashpw(b"syspass", bcrypt.gensalt()).decode(),
        role=UserRole.sysadmin,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(sysadmin)

    fi = FinancialInstitution(
        id=str(uuid.uuid4()),
        long_name="Test FI",
        short_name="TFI",
        country="BR",
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(fi)
    db.flush()

    # Workspace A has an investment account + asset + movement.
    acc_a = Account(
        id=str(uuid.uuid4()),
        workspace_id=ws_a.id,
        financial_institution_id=fi.id,
        name="Conta A",
        account_type=AccountType.investment,
        currency=Currency.BRL,
        opening_balance=Decimal("0"),
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    asset_a = Asset(
        id=str(uuid.uuid4()),
        workspace_id=ws_a.id,
        account_id=acc_a.id,
        asset_class=AssetClass.STOCK,
        country="BR",
        name="PETR4",
        ticker="PETR4",
        currency=Currency.BRL,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    movement_a = AssetMovement(
        id=str(uuid.uuid4()),
        workspace_id=ws_a.id,
        asset_id=asset_a.id,
        type=AssetMovementType.BUY,
        event_date=date(2026, 1, 15),
        quantity=Decimal("100"),
        unit_price=Decimal("30.00"),
        net_amount=Decimal("-3000.00"),
        currency=Currency.BRL,
        fx_rate=Decimal("1.0"),
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    # Workspace B has its own asset (used to test cross-workspace blocks).
    acc_b = Account(
        id=str(uuid.uuid4()),
        workspace_id=ws_b.id,
        financial_institution_id=fi.id,
        name="Conta B",
        account_type=AccountType.investment,
        currency=Currency.BRL,
        opening_balance=Decimal("0"),
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    asset_b = Asset(
        id=str(uuid.uuid4()),
        workspace_id=ws_b.id,
        account_id=acc_b.id,
        asset_class=AssetClass.STOCK,
        country="BR",
        name="ITUB4",
        ticker="ITUB4",
        currency=Currency.BRL,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add_all([acc_a, asset_a, movement_a, acc_b, asset_b])
    db.commit()

    admin_a_token = AuthService(db).login("att_admin_a@test.com", "adminpass")
    admin_b_token = AuthService(db).login("att_admin_b@test.com", "adminpass")
    sysadmin_token = AuthService(db).login("att_sysadmin@test.internal", "syspass")

    out = {
        "ws_a": ws_a.id,
        "ws_b": ws_b.id,
        "asset_a": asset_a.id,
        "asset_b": asset_b.id,
        "movement_a": movement_a.id,
        "admin_a_token": admin_a_token,
        "admin_b_token": admin_b_token,
        "sysadmin_token": sysadmin_token,
    }
    db.close()
    return out


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def png_bytes() -> bytes:
    # 1x1 transparent PNG.
    return bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000a49444154789c6300010000000500010d0a2db40000000049454e44ae426082"
    )


# ── Upload ────────────────────────────────────────────────────────────────────

def test_upload_png_to_asset(client, seed):
    r = client.post(
        "/api/attachments",
        data={"source_type": "asset", "source_id": seed["asset_a"]},
        files={"file": ("logo.png", io.BytesIO(png_bytes()), "image/png")},
        headers=auth(seed["admin_a_token"]),
    )
    assert r.status_code == 201
    data = r.json()
    assert data["kind"] == "image"
    assert data["mime_type"] == "image/png"
    assert data["filename"] == "logo.png"
    assert data["workspace_id"] == seed["ws_a"]
    assert data["is_active"] is True
    seed["att_id"] = data["id"]


def test_upload_to_movement(client, seed):
    r = client.post(
        "/api/attachments",
        data={"source_type": "movement", "source_id": seed["movement_a"]},
        files={"file": ("nota.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
        headers=auth(seed["admin_a_token"]),
    )
    assert r.status_code == 201
    assert r.json()["kind"] == "pdf"


def test_upload_rejects_disallowed_mime(client, seed):
    r = client.post(
        "/api/attachments",
        data={"source_type": "asset", "source_id": seed["asset_a"]},
        files={"file": ("exec.sh", io.BytesIO(b"#!/bin/bash"), "application/x-sh")},
        headers=auth(seed["admin_a_token"]),
    )
    assert r.status_code == 415


def test_upload_rejects_oversize(client, seed):
    big = b"\x00" * (attachment_storage.MAX_BYTES + 1)
    r = client.post(
        "/api/attachments",
        data={"source_type": "asset", "source_id": seed["asset_a"]},
        files={"file": ("big.png", io.BytesIO(big), "image/png")},
        headers=auth(seed["admin_a_token"]),
    )
    assert r.status_code == 413


def test_upload_rejects_unknown_source(client, seed):
    r = client.post(
        "/api/attachments",
        data={"source_type": "asset", "source_id": str(uuid.uuid4())},
        files={"file": ("logo.png", io.BytesIO(png_bytes()), "image/png")},
        headers=auth(seed["admin_a_token"]),
    )
    assert r.status_code == 404


def test_upload_rejects_invalid_source_type(client, seed):
    r = client.post(
        "/api/attachments",
        data={"source_type": "transaction", "source_id": seed["asset_a"]},
        files={"file": ("logo.png", io.BytesIO(png_bytes()), "image/png")},
        headers=auth(seed["admin_a_token"]),
    )
    assert r.status_code == 400


def test_upload_cross_workspace_blocked(client, seed):
    # admin_b tries to upload to an asset in workspace A
    r = client.post(
        "/api/attachments",
        data={"source_type": "asset", "source_id": seed["asset_a"]},
        files={"file": ("logo.png", io.BytesIO(png_bytes()), "image/png")},
        headers=auth(seed["admin_b_token"]),
    )
    assert r.status_code == 404  # Masked as not-found


def test_upload_sysadmin_cross_workspace_works(client, seed):
    r = client.post(
        "/api/attachments",
        data={"source_type": "asset", "source_id": seed["asset_b"]},
        files={"file": ("logo.png", io.BytesIO(png_bytes()), "image/png")},
        headers=auth(seed["sysadmin_token"]),
    )
    assert r.status_code == 201
    assert r.json()["workspace_id"] == seed["ws_b"]


# ── List ──────────────────────────────────────────────────────────────────────

def test_list_returns_uploaded(client, seed):
    r = client.get(
        "/api/attachments",
        params={"source_type": "asset", "source_id": seed["asset_a"]},
        headers=auth(seed["admin_a_token"]),
    )
    assert r.status_code == 200
    items = r.json()
    assert len(items) >= 1
    assert any(it["id"] == seed["att_id"] for it in items)


def test_list_cross_workspace_blocked(client, seed):
    r = client.get(
        "/api/attachments",
        params={"source_type": "asset", "source_id": seed["asset_a"]},
        headers=auth(seed["admin_b_token"]),
    )
    assert r.status_code == 404


# ── Download ──────────────────────────────────────────────────────────────────

def test_download_works(client, seed):
    r = client.get(
        f"/api/attachments/{seed['att_id']}/download",
        headers=auth(seed["admin_a_token"]),
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/png")
    assert r.content == png_bytes()


def test_download_cross_workspace_blocked(client, seed):
    r = client.get(
        f"/api/attachments/{seed['att_id']}/download",
        headers=auth(seed["admin_b_token"]),
    )
    assert r.status_code == 404


# ── Delete (soft) ─────────────────────────────────────────────────────────────

def test_delete_hard_removes_row_and_file(client, seed):
    """Spec 43 — DELETE is now a HARD delete: row is gone and the file
    on disk is unlinked."""
    # Capture the on-disk path before deleting.
    db = TestSession()
    try:
        att_row = db.get(Attachment, seed["att_id"])
        assert att_row is not None
        full_path = attachment_storage.absolute_path(att_row.storage_key)
        assert full_path.exists()
    finally:
        db.close()

    r = client.delete(
        f"/api/attachments/{seed['att_id']}",
        headers=auth(seed["admin_a_token"]),
    )
    assert r.status_code == 204

    # No longer appears in list.
    r2 = client.get(
        "/api/attachments",
        params={"source_type": "asset", "source_id": seed["asset_a"]},
        headers=auth(seed["admin_a_token"]),
    )
    ids = [it["id"] for it in r2.json()]
    assert seed["att_id"] not in ids

    # Row is gone from the DB.
    db2 = TestSession()
    try:
        assert db2.get(Attachment, seed["att_id"]) is None
    finally:
        db2.close()

    # File is gone from disk.
    assert not full_path.exists()


def test_delete_missing_returns_404(client, seed):
    r = client.delete(
        f"/api/attachments/{seed['att_id']}",
        headers=auth(seed["admin_a_token"]),
    )
    assert r.status_code == 404


# ── Storage safety ────────────────────────────────────────────────────────────

def test_absolute_path_blocks_traversal():
    with pytest.raises(ValueError):
        attachment_storage.absolute_path("../../etc/passwd")


def test_save_bytes_creates_per_workspace_dir():
    saved = attachment_storage.save_bytes("ws-xyz", png_bytes(), "image/png")
    assert saved.storage_key.startswith("ws-xyz/")
    assert saved.size_bytes == len(png_bytes())
    full = attachment_storage.absolute_path(saved.storage_key)
    assert full.exists()
    assert full.read_bytes() == png_bytes()


# ── Spec 43 §2 — workspace storage_key validation ─────────────────────────────


def _stub_attachment(workspace_id: str, storage_key: str) -> Attachment:
    """Cheap in-memory Attachment instance — we only exercise the two
    fields the storage helper looks at, not a full DB round-trip."""
    return Attachment(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        source_type='asset',
        source_id=str(uuid.uuid4()),
        kind='image',
        filename='probe.png',
        mime_type='image/png',
        size_bytes=1,
        storage_key=storage_key,
        is_active=True,
        uploaded_at=datetime.now(timezone.utc),
        uploaded_by=None,
    )


def test_absolute_path_for_accepts_matching_workspace_prefix():
    """storage_key under the row's own workspace subdir → resolves cleanly."""
    att = _stub_attachment("ws-good", "ws-good/file.png")
    # No exception; returns a Path under ROOT.
    resolved = attachment_storage.absolute_path_for(att)
    assert str(resolved).endswith("ws-good/file.png")


def test_absolute_path_for_rejects_cross_workspace_storage_key():
    """Defense-in-depth: a corrupted row pointing at another workspace's
    file must raise — even though the path-traversal check alone would
    pass (it's still under ROOT)."""
    att = _stub_attachment("ws-A", "ws-B/file.png")
    with pytest.raises(ValueError) as exc:
        attachment_storage.absolute_path_for(att)
    assert "escapes its workspace subdir" in str(exc.value)


def test_delete_for_rejects_cross_workspace_storage_key():
    """`delete_for` shares the validation — the FS file (if any) is
    NOT touched when the row is corrupted."""
    att = _stub_attachment("ws-A", "ws-B/file.png")
    with pytest.raises(ValueError):
        attachment_storage.delete_for(att)
