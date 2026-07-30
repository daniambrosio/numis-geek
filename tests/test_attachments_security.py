"""Spec 19 / 43 — hardening dos attachments.

Cobre:
- Path traversal via `GET /api/attachments/{id}/download` — rota nunca
  serve arquivo fora do storage dir mesmo com storage_key malicioso.
- `attachment_storage.save_bytes` aceita todos os MIMEs whitelisted,
  cada um retorna storage_key único, kind e extensão corretos.
- `save_bytes` com payload > MAX_BYTES levanta AttachmentTooLargeError
  com mensagem clara.
"""
from __future__ import annotations

import io
import shutil
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

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
from numis_geek.models.attachment import (
    Attachment,
    AttachmentKind,
    AttachmentSourceType,
)
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
    target = tmp_path_factory.mktemp("att-security")
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
    ws = WorkspaceService(db).create("Sec WS")
    UserService(db).create(ws.id, "sec_admin@test.com", "adminpass", UserRole.admin)

    now = datetime.now(timezone.utc)
    fi = FinancialInstitution(
        id=str(uuid.uuid4()),
        long_name="XP", short_name="XP", logo_slug="xp",
        country="BR", is_active=True, created_at=now, updated_at=now,
    )
    db.add(fi)
    db.flush()
    acc = Account(
        id=str(uuid.uuid4()), workspace_id=ws.id,
        financial_institution_id=fi.id, name="Inv",
        account_type=AccountType.investment, currency=Currency.BRL,
        opening_balance=Decimal("0"), is_active=True,
        created_at=now, updated_at=now,
    )
    asset = Asset(
        id=str(uuid.uuid4()), workspace_id=ws.id, account_id=acc.id,
        asset_class=AssetClass.STOCK, country="BR", name="PETR4", ticker="PETR4",
        currency=Currency.BRL, is_active=True, created_at=now, updated_at=now,
    )
    db.add_all([acc, asset])
    db.commit()

    token = AuthService(db).login("sec_admin@test.com", "adminpass")
    out = {"ws_id": ws.id, "asset_id": asset.id, "token": token}
    db.close()
    return out


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def _png_bytes() -> bytes:
    return bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000a49444154789c6300010000000500010d0a2db40000000049454e44ae426082"
    )


def _seed_malicious_attachment(
    db, ws_id: str, asset_id: str, storage_key: str,
) -> str:
    """Insere row de Attachment direto no DB com storage_key sob o
    workspace mas contendo traversal (../). Bypassa a rota de upload,
    que sanitiza; simula uma corrupção de dado / bug histórico."""
    att = Attachment(
        id=str(uuid.uuid4()),
        workspace_id=ws_id,
        source_type=AttachmentSourceType.ASSET,
        source_id=asset_id,
        kind=AttachmentKind.IMAGE,
        filename="malicious.png",
        mime_type="image/png",
        size_bytes=1,
        storage_key=storage_key,
        uploaded_at=datetime.now(timezone.utc),
        uploaded_by=None,
        is_active=True,
    )
    db.add(att)
    db.commit()
    return att.id


# ── Path traversal via download route ───────────────────────────────────────


def test_download_rejects_traversal_within_workspace_prefix(client, seed):
    """storage_key = 'ws/../../etc/x.png' PASSA o prefix check
    (workspace_id/) mas o resolver detecta escape de ROOT. Rota NÃO deve
    devolver 200 nem servir arquivo fora do storage dir."""
    db = TestSession()
    try:
        malicious_key = f"{seed['ws_id']}/../../etc/passwd.png"
        att_id = _seed_malicious_attachment(
            db, seed["ws_id"], seed["asset_id"], malicious_key,
        )
    finally:
        db.close()

    r = client.get(
        f"/api/attachments/{att_id}/download", headers=auth(seed["token"]),
    )
    # Task 58 fix (2026-07-29): rota converte ValueError em 400 explícito.
    assert r.status_code == 400
    body = r.content or b""
    # Não vazou nada que pareça conteúdo de /etc/passwd.
    assert b"root:" not in body


def test_download_rejects_cross_workspace_storage_key(client, seed):
    """storage_key aponta pra workspace diferente do próprio row →
    absolute_path_for detecta e a rota nunca serve o arquivo."""
    other_ws = "another-workspace"
    db = TestSession()
    try:
        att_id = _seed_malicious_attachment(
            db, seed["ws_id"], seed["asset_id"],
            f"{other_ws}/file.png",
        )
    finally:
        db.close()

    r = client.get(
        f"/api/attachments/{att_id}/download", headers=auth(seed["token"]),
    )
    assert r.status_code != 200
    assert r.status_code in (400, 404, 500)


def test_download_missing_returns_404(client, seed):
    r = client.get(
        f"/api/attachments/{uuid.uuid4()}/download", headers=auth(seed["token"]),
    )
    assert r.status_code == 404


# ── save_bytes MIME whitelist ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "mime,expected_kind,expected_ext",
    [
        ("image/png", AttachmentKind.IMAGE, "png"),
        ("image/jpeg", AttachmentKind.IMAGE, "jpg"),
        ("image/webp", AttachmentKind.IMAGE, "webp"),
        ("application/pdf", AttachmentKind.PDF, "pdf"),
        ("text/csv", AttachmentKind.CSV, "csv"),
    ],
)
def test_save_bytes_accepts_whitelisted_mimes(
    mime, expected_kind, expected_ext, tmp_attachment_root,
):
    payload = b"fake-body-for-" + mime.encode()
    saved = attachment_storage.save_bytes("ws-mime", payload, mime)
    assert saved.mime_type == mime
    assert saved.kind == expected_kind
    assert saved.storage_key.startswith("ws-mime/")
    assert saved.storage_key.endswith(f".{expected_ext}")
    assert saved.size_bytes == len(payload)
    full = attachment_storage.absolute_path(saved.storage_key)
    assert full.exists()
    assert full.read_bytes() == payload


def test_save_bytes_generates_unique_storage_keys(tmp_attachment_root):
    """Dois uploads do mesmo MIME nunca colidem — filename = uuid4()."""
    keys = {
        attachment_storage.save_bytes(
            "ws-unique", b"payload", "image/png",
        ).storage_key
        for _ in range(5)
    }
    assert len(keys) == 5


def test_save_bytes_rejects_unknown_mime(tmp_attachment_root):
    with pytest.raises(attachment_storage.AttachmentMimeNotAllowedError):
        attachment_storage.save_bytes(
            "ws-bad", b"payload", "application/x-sh",
        )


# ── Size limit ───────────────────────────────────────────────────────────────


def test_save_bytes_rejects_oversize_with_clear_message(tmp_attachment_root):
    big = b"\x00" * (attachment_storage.MAX_BYTES + 1)
    with pytest.raises(attachment_storage.AttachmentTooLargeError) as exc:
        attachment_storage.save_bytes("ws-big", big, "image/png")
    msg = str(exc.value)
    # Mensagem menciona o limite em MB pra UX ("50 MB").
    assert "MB" in msg
    assert "limite" in msg.lower() or "excede" in msg.lower()


def test_save_bytes_accepts_exactly_max_bytes(tmp_attachment_root):
    """Boundary: exatamente MAX_BYTES é permitido (limit exclusivo com >)."""
    at_limit = b"\x00" * attachment_storage.MAX_BYTES
    saved = attachment_storage.save_bytes("ws-boundary", at_limit, "image/png")
    assert saved.size_bytes == attachment_storage.MAX_BYTES
