"""Spec 38 — HTTP-level tests for POST/GET/confirm/reject /extractions."""
from __future__ import annotations

import json
import shutil
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

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
from numis_geek.models.attachment import Attachment, AttachmentKind, AttachmentSourceType
from numis_geek.models.extraction_job import ExtractionStatus
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.user import User, UserRole
from numis_geek.services import attachment_storage
from numis_geek.services.auth import AuthService
from numis_geek.services.user import UserService
from numis_geek.services.workspace import WorkspaceService
from numis_geek.integrations.llm import LLMCall, set_llm_client


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
    target = tmp_path_factory.mktemp("extractions_route")
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
    ws = WorkspaceService(db).create("RouteWS")
    admin = UserService(db).create(ws.id, "route@test.com", "pw", UserRole.admin)

    now = datetime.now(timezone.utc)
    fi = FinancialInstitution(
        id=str(uuid.uuid4()), long_name="FI", short_name="FI", country="BR",
        is_active=True, created_at=now, updated_at=now,
    )
    acc = Account(
        id=str(uuid.uuid4()), workspace_id=ws.id, financial_institution_id=fi.id,
        name="Conta", account_type=AccountType.investment,
        currency=Currency.BRL, opening_balance=Decimal("0"),
        is_active=True, created_at=now, updated_at=now,
    )
    asset = Asset(
        id=str(uuid.uuid4()), workspace_id=ws.id, account_id=acc.id,
        asset_class=AssetClass.STOCK, country="BR", name="VALE3",
        ticker="VALE3", currency=Currency.BRL, current_price=Decimal("60.00"),
        is_active=True, created_at=now, updated_at=now,
    )
    db.add_all([fi, acc, asset])
    db.commit()

    fake_png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000a49444154789c6300010000000500010d0a2db40000000049454e44ae426082"
    )
    saved = attachment_storage.save_bytes(ws.id, fake_png, "image/png")
    att = Attachment(
        id=str(uuid.uuid4()), workspace_id=ws.id,
        source_type=AttachmentSourceType.ASSET, source_id=asset.id,
        kind=AttachmentKind.IMAGE, filename="x.png", mime_type="image/png",
        size_bytes=saved.size_bytes, storage_key=saved.storage_key,
        uploaded_at=now, is_active=True,
    )
    db.add(att)
    db.commit()

    token = AuthService(db).login("route@test.com", "pw")
    out = {
        "ws_id": ws.id, "asset_id": asset.id, "att_id": att.id, "token": token,
    }
    db.close()
    return out


class _Fake:
    def __init__(self, payload):
        self._payload = payload

    def call(self, *, system, user_text, image_bytes=None, image_mime=None,
             model="claude-sonnet-4-5", max_tokens=4096):
        text = self._payload if isinstance(self._payload, str) else json.dumps(self._payload)
        return LLMCall(text=text, input_tokens=10, output_tokens=10, model=model)


@pytest.fixture(autouse=True)
def reset_llm():
    yield
    set_llm_client(None)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_post_extraction_runs_inline_and_returns_extracted(client, seed):
    set_llm_client(_Fake({
        "ticker": "VALE3", "price": 65.00, "currency": "BRL",
        "as_of_timestamp": None, "source_app": None, "confidence": 0.9,
    }))
    r = client.post(
        "/extractions",
        json={"attachment_id": seed["att_id"], "source_hint": "SCREENSHOT_PRICE"},
        headers=_auth(seed["token"]),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "EXTRACTED"
    assert body["extracted_json"]["price"] == 65.00
    seed["job_id"] = body["id"]


def test_get_extraction(client, seed):
    job_id = seed["job_id"]
    r = client.get(f"/extractions/{job_id}", headers=_auth(seed["token"]))
    assert r.status_code == 200
    assert r.json()["id"] == job_id


def test_confirm_extraction_applies_price(client, seed):
    job_id = seed["job_id"]
    r = client.post(
        f"/extractions/{job_id}/confirm",
        json={},
        headers=_auth(seed["token"]),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["applied_count"] == 1
    assert body["skipped_count"] == 0

    db = TestSession()
    try:
        asset = db.get(Asset, seed["asset_id"])
        assert asset.current_price == Decimal("65.00")
    finally:
        db.close()


def test_reject_extraction(client, seed):
    set_llm_client(_Fake({
        "ticker": "VALE3", "price": 9999, "currency": "BRL",
        "as_of_timestamp": None, "source_app": None, "confidence": 0.1,
    }))
    r1 = client.post(
        "/extractions",
        json={"attachment_id": seed["att_id"], "source_hint": "SCREENSHOT_PRICE"},
        headers=_auth(seed["token"]),
    )
    new_job_id = r1.json()["id"]

    r2 = client.post(
        f"/extractions/{new_job_id}/reject",
        json={"reason": "no quero"},
        headers=_auth(seed["token"]),
    )
    assert r2.status_code == 200
    assert r2.json()["status"] == "REJECTED"
