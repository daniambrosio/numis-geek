"""HTTP-level tests para os endpoints de bulk extraction/income (specs 48 + 58).

Cobre gaps de teste identificados no audit:
- POST /snapshots/{id}/bulk-extract
- GET  /snapshots/{id}/extractions
- POST /snapshots/{id}/institutions/{fi_id}/bulk-extract
- POST /snapshots/{id}/institutions/{fi_id}/bulk-income
- POST /extractions/{job_id}/preview

Padrão de referência: tests/test_extractions_route.py (module-scoped in-memory
SQLite + StaticPool, override_get_db com commit-on-success, FakeLLM injetado
via set_llm_client).
"""
from __future__ import annotations

import json
import shutil
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

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
from numis_geek.models.asset import Asset, AssetClass, PriceSource
from numis_geek.models.attachment import (
    Attachment, AttachmentKind, AttachmentSourceType,
)
from numis_geek.models.distribution import Distribution
from numis_geek.models.extraction_job import ExtractionJob, ExtractionStatus
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.portfolio_snapshot import (
    PendencyAction, PendencyReason, PortfolioSnapshot, SnapshotPendency,
    SnapshotSource, SnapshotStatus,
)
from numis_geek.models.user import UserRole
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
    target = tmp_path_factory.mktemp("bulk_extract_routes")
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


# ── FakeLLM: mesma interface do injetável em src/numis_geek/integrations/llm.py.
class _FakeLLM:
    def __init__(self, payload: dict[str, Any] | str):
        self.payload = payload

    def call(self, *, system, user_text, image_bytes=None, image_mime=None,
             image_parts=None, model="claude-sonnet-4-5", max_tokens=4096):
        text = (
            self.payload if isinstance(self.payload, str)
            else json.dumps(self.payload)
        )
        return LLMCall(text=text, input_tokens=10, output_tokens=10, model=model)


@pytest.fixture(autouse=True)
def _reset_llm():
    yield
    set_llm_client(None)


def _fake_png() -> bytes:
    # Menor PNG válido (1×1) — mesmo blob usado em test_bulk_extract.py.
    return bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000a49444154789c6300010000000500010d0a2db40000000049454e44ae426082"
    )


def _make_attachment(ws_id: str, mime: str = "image/png", blob: bytes | None = None) -> str:
    db = TestSession()
    payload = blob if blob is not None else _fake_png()
    saved = attachment_storage.save_bytes(ws_id, payload, mime)
    att = Attachment(
        id=str(uuid.uuid4()), workspace_id=ws_id,
        source_type=AttachmentSourceType.SNAPSHOT, source_id=ws_id,
        kind=AttachmentKind.IMAGE if mime.startswith("image/") else AttachmentKind.OTHER,
        filename="extrato.bin", mime_type=mime,
        size_bytes=saved.size_bytes, storage_key=saved.storage_key,
        uploaded_at=datetime.now(timezone.utc), is_active=True,
    )
    db.add(att)
    db.commit()
    att_id = att.id
    db.close()
    return att_id


@pytest.fixture(scope="module")
def seed():
    """Um workspace principal (admin + member), FI XP, conta de investimento,
    2 assets (PETR4 com pendency + ITUB4 sem pendency), snapshots IN_REVIEW e
    CLOSED. Também cria um segundo workspace pra teste cross-workspace."""
    db = TestSession()
    now = datetime.now(timezone.utc)

    ws = WorkspaceService(db).create("BulkRoutes")
    admin = UserService(db).create(
        ws.id, "bulk-admin@test.com", "adminpass", UserRole.admin,
    )
    member = UserService(db).create(
        ws.id, "bulk-member@test.com", "memberpass", UserRole.member,
    )

    fi_xp = FinancialInstitution(
        id=str(uuid.uuid4()), long_name="XP Investimentos",
        short_name="XP", country="BR",
        is_active=True, created_at=now, updated_at=now,
    )
    acc = Account(
        id=str(uuid.uuid4()), workspace_id=ws.id,
        financial_institution_id=fi_xp.id, name="XP Inv",
        account_type=AccountType.investment, currency=Currency.BRL,
        opening_balance=Decimal("0"),
        is_active=True, created_at=now, updated_at=now,
    )
    petr = Asset(
        id=str(uuid.uuid4()), workspace_id=ws.id, account_id=acc.id,
        asset_class=AssetClass.STOCK, country="BR",
        name="Petrobras", ticker="PETR4",
        currency=Currency.BRL, current_price=Decimal("30.00"),
        price_source=PriceSource.MANUAL,
        is_active=True, created_at=now, updated_at=now,
    )
    itub = Asset(
        id=str(uuid.uuid4()), workspace_id=ws.id, account_id=acc.id,
        asset_class=AssetClass.STOCK, country="BR",
        name="Itau Unibanco", ticker="ITUB4",
        currency=Currency.BRL, current_price=Decimal("32.00"),
        price_source=PriceSource.MANUAL,
        is_active=True, created_at=now, updated_at=now,
    )
    snap_ir = PortfolioSnapshot(
        id=str(uuid.uuid4()), workspace_id=ws.id,
        period_end_date=date(2026, 4, 30),
        total_value_brl=Decimal("0"), total_value_usd=Decimal("0"),
        total_invested_brl=Decimal("0"), total_received_brl=Decimal("0"),
        source=SnapshotSource.MANUAL, status=SnapshotStatus.IN_REVIEW,
    )
    snap_closed = PortfolioSnapshot(
        id=str(uuid.uuid4()), workspace_id=ws.id,
        period_end_date=date(2026, 3, 31),
        total_value_brl=Decimal("0"), total_value_usd=Decimal("0"),
        total_invested_brl=Decimal("0"), total_received_brl=Decimal("0"),
        source=SnapshotSource.MANUAL, status=SnapshotStatus.CLOSED,
    )
    db.add_all([fi_xp, acc, petr, itub, snap_ir, snap_closed])
    db.flush()

    pen_petr = SnapshotPendency(
        id=str(uuid.uuid4()), snapshot_id=snap_ir.id, asset_id=petr.id,
        reason=PendencyReason.MANUAL_SOURCE,
        action_type=PendencyAction.EDIT_PRICE,
        created_at=now,
    )
    db.add(pen_petr)
    db.commit()

    # Segundo workspace, isolado — pra cross-workspace guard.
    ws_other = WorkspaceService(db).create("OtherWS")
    other_admin = UserService(db).create(
        ws_other.id, "other-admin@test.com", "otherpass", UserRole.admin,
    )
    db.commit()

    admin_tok = AuthService(db).login("bulk-admin@test.com", "adminpass")
    member_tok = AuthService(db).login("bulk-member@test.com", "memberpass")
    other_tok = AuthService(db).login("other-admin@test.com", "otherpass")

    out = {
        "ws_id": ws.id,
        "ws_other_id": ws_other.id,
        "fi_xp_id": fi_xp.id,
        "petr_id": petr.id,
        "itub_id": itub.id,
        "pen_petr_id": pen_petr.id,
        "snap_ir_id": snap_ir.id,
        "snap_closed_id": snap_closed.id,
        "admin_tok": admin_tok,
        "member_tok": member_tok,
        "other_tok": other_tok,
    }
    db.close()
    return out


def _auth(tok: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {tok}"}


# ═══════════════════════════════════════════════════════════════════════════
# POST /snapshots/{id}/bulk-extract  (spec 48)
# ═══════════════════════════════════════════════════════════════════════════


def test_post_bulk_extract_creates_extracted_job(client, seed):
    """Happy path: FakeLLM devolve payload BROKER_POSITION válido; endpoint
    devolve 201 com job EXTRACTED + payload preservado."""
    set_llm_client(_FakeLLM({
        "as_of_date": "2026-04-30",
        "broker_name": "XP",
        "positions": [
            {"ticker_raw": "PETR4", "ticker_normalized": "PETR4",
             "quantity": 100, "unit_price": 38.50, "confidence": 0.95},
        ],
    }))
    att_id = _make_attachment(seed["ws_id"])
    r = client.post(
        f"/api/snapshots/{seed['snap_ir_id']}/bulk-extract",
        json={"attachment_id": att_id},
        headers=_auth(seed["admin_tok"]),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "EXTRACTED"
    assert body["error_message"] is None
    positions = body["extracted_json"]["positions"]
    assert len(positions) == 1
    assert positions[0]["ticker_raw"] == "PETR4"


def test_bulk_extract_rejects_closed_snapshot(client, seed):
    """Snapshot fechado → 409 (bulk extract só em IN_REVIEW)."""
    att_id = _make_attachment(seed["ws_id"])
    r = client.post(
        f"/api/snapshots/{seed['snap_closed_id']}/bulk-extract",
        json={"attachment_id": att_id},
        headers=_auth(seed["admin_tok"]),
    )
    assert r.status_code == 409
    assert "IN_REVIEW" in r.json()["detail"]


def test_bulk_extract_cross_workspace_returns_404(client, seed):
    """Admin de outro workspace tenta rodar bulk extract no snapshot alheio
    → 404 (não deve vazar existência do snapshot)."""
    att_id = _make_attachment(seed["ws_other_id"])
    r = client.post(
        f"/api/snapshots/{seed['snap_ir_id']}/bulk-extract",
        json={"attachment_id": att_id},
        headers=_auth(seed["other_tok"]),
    )
    assert r.status_code == 404


def test_bulk_extract_member_can_upload(client, seed):
    """Member (role != admin) do próprio workspace consegue rodar bulk
    extract — bulk-extract não é gated por admin."""
    set_llm_client(_FakeLLM({
        "positions": [
            {"ticker_raw": "PETR4", "quantity": 10, "unit_price": 40.0,
             "confidence": 0.9},
        ],
    }))
    att_id = _make_attachment(seed["ws_id"])
    r = client.post(
        f"/api/snapshots/{seed['snap_ir_id']}/bulk-extract",
        json={"attachment_id": att_id},
        headers=_auth(seed["member_tok"]),
    )
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "EXTRACTED"


# ═══════════════════════════════════════════════════════════════════════════
# GET /snapshots/{id}/extractions
# ═══════════════════════════════════════════════════════════════════════════


def test_list_bulk_extractions_returns_created_job(client, seed):
    """Depois de rodar bulk extract, GET .../extractions devolve o job na
    lista com o shape BulkExtractionJobOut (positions_count agregado)."""
    set_llm_client(_FakeLLM({
        "positions": [
            {"ticker_raw": "PETR4", "quantity": 5, "unit_price": 41.0,
             "confidence": 0.88},
            {"ticker_raw": "ITUB4", "quantity": 3, "unit_price": 33.0,
             "confidence": 0.88},
        ],
    }))
    att_id = _make_attachment(seed["ws_id"])
    created = client.post(
        f"/api/snapshots/{seed['snap_ir_id']}/bulk-extract",
        json={"attachment_id": att_id},
        headers=_auth(seed["admin_tok"]),
    )
    assert created.status_code == 201, created.text
    job_id = created.json()["id"]

    r = client.get(
        f"/api/snapshots/{seed['snap_ir_id']}/extractions",
        headers=_auth(seed["admin_tok"]),
    )
    assert r.status_code == 200
    jobs = r.json()
    matches = [j for j in jobs if j["id"] == job_id]
    assert len(matches) == 1
    row = matches[0]
    assert row["status"] == "EXTRACTED"
    assert row["positions_count"] == 2
    assert row["source_hint"] == "BROKER_POSITION"


def test_list_bulk_extractions_cross_workspace_404(client, seed):
    r = client.get(
        f"/api/snapshots/{seed['snap_ir_id']}/extractions",
        headers=_auth(seed["other_tok"]),
    )
    assert r.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════
# POST /extractions/{job_id}/preview  (spec 57)
# ═══════════════════════════════════════════════════════════════════════════


def test_preview_extraction_returns_apply_plan_without_writes(client, seed):
    """Preview classifica as posições em applied/matched_no_pendency/orphan
    idem confirm faria, mas sem tocar em Asset.current_price nem em Pendency."""
    set_llm_client(_FakeLLM({
        "positions": [
            # matched + pendency → applied bucket
            {"ticker_raw": "PETR4", "quantity": 100, "unit_price": 38.5,
             "confidence": 0.95},
            # matched sem pendency → matched_no_pendency
            {"ticker_raw": "ITUB4", "quantity": 200, "unit_price": 32.0,
             "confidence": 0.9},
            # não existe no workspace → orphan
            {"ticker_raw": "ABEV3", "quantity": 50, "unit_price": 12.0,
             "confidence": 0.9},
        ],
    }))
    att_id = _make_attachment(seed["ws_id"])
    created = client.post(
        f"/api/snapshots/{seed['snap_ir_id']}/bulk-extract",
        json={"attachment_id": att_id},
        headers=_auth(seed["admin_tok"]),
    )
    assert created.status_code == 201, created.text
    job_id = created.json()["id"]

    # Snapshot dos preços ANTES do preview.
    db = TestSession()
    petr_price_before = db.get(Asset, seed["petr_id"]).current_price
    itub_price_before = db.get(Asset, seed["itub_id"]).current_price
    pen_before = db.get(SnapshotPendency, seed["pen_petr_id"]).resolved_at
    db.close()

    r = client.post(
        f"/api/extractions/{job_id}/preview",
        json={},
        headers=_auth(seed["admin_tok"]),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    detail = body["bulk_detail"]
    assert detail is not None
    assert {a["ticker"] for a in detail["applied"]} == {"PETR4"}
    assert {m["ticker"] for m in detail["matched_no_pendency"]} == {"ITUB4"}
    assert {o["ticker"] for o in detail["orphan"]} == {"ABEV3"}
    assert body["applied_count"] == 1

    # Preview NÃO altera nada.
    db = TestSession()
    try:
        assert db.get(Asset, seed["petr_id"]).current_price == petr_price_before
        assert db.get(Asset, seed["itub_id"]).current_price == itub_price_before
        assert db.get(SnapshotPendency, seed["pen_petr_id"]).resolved_at == pen_before
    finally:
        db.close()


def test_preview_extraction_cross_workspace_404(client, seed):
    set_llm_client(_FakeLLM({
        "positions": [
            {"ticker_raw": "PETR4", "quantity": 1, "unit_price": 10.0,
             "confidence": 0.9},
        ],
    }))
    att_id = _make_attachment(seed["ws_id"])
    created = client.post(
        f"/api/snapshots/{seed['snap_ir_id']}/bulk-extract",
        json={"attachment_id": att_id},
        headers=_auth(seed["admin_tok"]),
    )
    assert created.status_code == 201, created.text
    job_id = created.json()["id"]

    r = client.post(
        f"/api/extractions/{job_id}/preview",
        json={},
        headers=_auth(seed["other_tok"]),
    )
    assert r.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════
# POST /snapshots/{id}/institutions/{fi_id}/bulk-extract  (spec 58)
# ═══════════════════════════════════════════════════════════════════════════


def test_bulk_extract_per_fi_creates_scoped_job(client, seed):
    """Endpoint per-FI cria job com institution_id preenchido, o que o
    BulkExtractionJobOut expõe como institution_short_name."""
    set_llm_client(_FakeLLM({
        "positions": [
            {"ticker_raw": "PETR4", "quantity": 10, "unit_price": 39.0,
             "confidence": 0.9},
        ],
    }))
    att_id = _make_attachment(seed["ws_id"])
    r = client.post(
        f"/api/snapshots/{seed['snap_ir_id']}/institutions/{seed['fi_xp_id']}/bulk-extract",
        json={"attachment_id": att_id},
        headers=_auth(seed["admin_tok"]),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "EXTRACTED"
    assert body["institution_id"] == seed["fi_xp_id"]
    assert body["institution_short_name"] == "XP"

    # E aparece na lista com institution_short_name já hidratado.
    listed = client.get(
        f"/api/snapshots/{seed['snap_ir_id']}/extractions",
        headers=_auth(seed["admin_tok"]),
    )
    assert listed.status_code == 200
    row = next(j for j in listed.json() if j["id"] == body["id"])
    assert row["institution_short_name"] == "XP"
    assert row["source_hint"] == "BROKER_POSITION"


def test_bulk_extract_per_fi_unknown_fi_returns_404(client, seed):
    att_id = _make_attachment(seed["ws_id"])
    r = client.post(
        f"/api/snapshots/{seed['snap_ir_id']}/institutions/{uuid.uuid4()}/bulk-extract",
        json={"attachment_id": att_id},
        headers=_auth(seed["admin_tok"]),
    )
    assert r.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════
# POST /snapshots/{id}/institutions/{fi_id}/bulk-income  (spec 58 Stage 4)
# ═══════════════════════════════════════════════════════════════════════════


def _income_payload(event_date_iso: str, gross: float) -> dict:
    return {
        "as_of_date": event_date_iso,
        "broker_name": "XP",
        "events": [
            {
                "event_date": event_date_iso,
                "ticker_raw": "PETR4",
                "type": "DIVIDEND",
                "gross_amount": gross,
                "tax_amount": 0.0,
                "net_amount": gross,
                "currency": "BRL",
                "confidence": 0.95,
            }
        ],
        "option_events": [],
    }


def test_bulk_income_creates_distribution_and_is_idempotent(client, seed):
    """POST bulk-income + confirm cria uma Distribution. Re-upload do mesmo
    payload (mesmo external_id derivado do content) NÃO duplica — a segunda
    entrada aparece no bucket 'duplicate' (matched_no_pendency, repurposed
    pelo _apply_bulk_income_to_snapshot).
    """
    payload = _income_payload("2026-04-15", 12.34)
    set_llm_client(_FakeLLM(payload))
    att_id = _make_attachment(seed["ws_id"])

    r1 = client.post(
        f"/api/snapshots/{seed['snap_ir_id']}/institutions/{seed['fi_xp_id']}/bulk-income",
        json={"attachment_id": att_id},
        headers=_auth(seed["admin_tok"]),
    )
    assert r1.status_code == 201, r1.text
    job1_id = r1.json()["id"]
    assert r1.json()["institution_short_name"] == "XP"

    # Confirm → cria Distribution.
    confirm1 = client.post(
        f"/api/extractions/{job1_id}/confirm",
        json={},
        headers=_auth(seed["admin_tok"]),
    )
    assert confirm1.status_code == 200, confirm1.text
    assert confirm1.json()["applied_count"] == 1

    db = TestSession()
    try:
        rows = (
            db.query(Distribution)
            .filter(
                Distribution.workspace_id == seed["ws_id"],
                Distribution.event_date == date(2026, 4, 15),
            )
            .all()
        )
        assert len(rows) == 1
        ext_id_original = rows[0].external_id
    finally:
        db.close()

    # Segundo upload do MESMO payload → job novo, mas confirm devolve
    # duplicate (repurposed matched_no_pendency), Distribution não duplica.
    set_llm_client(_FakeLLM(payload))
    att_id2 = _make_attachment(seed["ws_id"])
    r2 = client.post(
        f"/api/snapshots/{seed['snap_ir_id']}/institutions/{seed['fi_xp_id']}/bulk-income",
        json={"attachment_id": att_id2},
        headers=_auth(seed["admin_tok"]),
    )
    assert r2.status_code == 201, r2.text
    confirm2 = client.post(
        f"/api/extractions/{r2.json()['id']}/confirm",
        json={},
        headers=_auth(seed["admin_tok"]),
    )
    assert confirm2.status_code == 200, confirm2.text
    body2 = confirm2.json()
    assert body2["applied_count"] == 0
    dup_ext_ids = {
        row["external_id"]
        for row in body2["bulk_detail"]["matched_no_pendency"]
    }
    assert ext_id_original in dup_ext_ids

    db = TestSession()
    try:
        rows = (
            db.query(Distribution)
            .filter(
                Distribution.workspace_id == seed["ws_id"],
                Distribution.event_date == date(2026, 4, 15),
                Distribution.external_id == ext_id_original,
            )
            .all()
        )
        assert len(rows) == 1
    finally:
        db.close()


def test_bulk_income_closed_snapshot_returns_409(client, seed):
    att_id = _make_attachment(seed["ws_id"])
    r = client.post(
        f"/api/snapshots/{seed['snap_closed_id']}/institutions/{seed['fi_xp_id']}/bulk-income",
        json={"attachment_id": att_id},
        headers=_auth(seed["admin_tok"]),
    )
    assert r.status_code == 409
    assert "IN_REVIEW" in r.json()["detail"]


def test_bulk_income_unknown_fi_returns_404(client, seed):
    att_id = _make_attachment(seed["ws_id"])
    r = client.post(
        f"/api/snapshots/{seed['snap_ir_id']}/institutions/{uuid.uuid4()}/bulk-income",
        json={"attachment_id": att_id},
        headers=_auth(seed["admin_tok"]),
    )
    assert r.status_code == 404
