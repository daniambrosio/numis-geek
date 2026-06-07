"""Spec 48 — tests for bulk extract apply (snapshot-level)."""
from __future__ import annotations

import json
import shutil
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

import bcrypt
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from numis_geek.db.base import Base
import numis_geek.models  # noqa: F401
from numis_geek.models.account import Account, AccountType, Currency
from numis_geek.models.asset import Asset, AssetClass, PriceSource
from numis_geek.models.attachment import Attachment, AttachmentKind, AttachmentSourceType
from numis_geek.models.audit_log import AuditLog
from numis_geek.models.extraction_job import ExtractionSourceHint, ExtractionStatus
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.portfolio_snapshot import (
    PendencyAction, PendencyReason, PortfolioSnapshot, PortfolioSnapshotItem,
    SnapshotPendency, SnapshotSource, SnapshotStatus,
)
from numis_geek.models.user import User, UserRole
from numis_geek.services import attachment_storage
from numis_geek.services import extraction as extraction_service
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
    target = tmp_path_factory.mktemp("bulk_atts")
    original = attachment_storage.ROOT
    attachment_storage.ROOT = target
    yield target
    attachment_storage.ROOT = original
    shutil.rmtree(target, ignore_errors=True)


@pytest.fixture
def db():
    s = TestSession()
    yield s
    s.rollback()
    s.close()


@pytest.fixture(autouse=True)
def reset_llm():
    yield
    set_llm_client(None)


class FakeLLM:
    def __init__(self, payload: dict[str, Any] | str):
        self.payload = payload

    def call(self, *, system, user_text, image_bytes=None, image_mime=None,
             image_parts=None, model="claude-sonnet-4-5", max_tokens=4096):
        text = self.payload if isinstance(self.payload, str) else json.dumps(self.payload)
        return LLMCall(text=text, input_tokens=100, output_tokens=50, model=model)


def _make_attachment(ws_id: str) -> str:
    db = TestSession()
    fake_png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000a49444154789c6300010000000500010d0a2db40000000049454e44ae426082"
    )
    saved = attachment_storage.save_bytes(ws_id, fake_png, "image/png")
    att = Attachment(
        id=str(uuid.uuid4()), workspace_id=ws_id,
        source_type=AttachmentSourceType.ASSET, source_id=ws_id,
        kind=AttachmentKind.IMAGE, filename="extrato.png", mime_type="image/png",
        size_bytes=saved.size_bytes, storage_key=saved.storage_key,
        uploaded_at=datetime.now(timezone.utc), is_active=True,
    )
    db.add(att)
    db.commit()
    att_id = att.id
    db.close()
    return att_id


def _world(db) -> dict:
    """A workspace with two FIs (XP and Avenue), three assets with open
    pendencies (PETR4@XP, ITUB4@XP, AAPL@Avenue), one extra asset without
    a pendency (VALE3@XP). Snapshot is IN_REVIEW for 2026-04-30.

    Tickers are unique per call (suffixed with a UUID) so module-scoped
    test_engine can host multiple invocations without UNIQUE collisions.
    """
    suffix = uuid.uuid4().hex[:6]
    now = datetime.now(timezone.utc)
    ws = WorkspaceService(db).create(f"BulkWS-{suffix}")
    user = User(
        id=str(uuid.uuid4()), workspace_id=ws.id,
        email=f"bulk-{suffix}@test.com", name="Bulk",
        password_hash=bcrypt.hashpw(b"x", bcrypt.gensalt()).decode(),
        role=UserRole.admin, is_active=True,
        created_at=now, updated_at=now,
    )
    fi_xp = FinancialInstitution(
        id=str(uuid.uuid4()), long_name="XP", short_name="XP", country="BR",
        is_active=True, created_at=now, updated_at=now,
    )
    fi_av = FinancialInstitution(
        id=str(uuid.uuid4()), long_name="Avenue", short_name="Avenue", country="US",
        is_active=True, created_at=now, updated_at=now,
    )
    acc_xp = Account(
        id=str(uuid.uuid4()), workspace_id=ws.id,
        financial_institution_id=fi_xp.id, name="XP Inv",
        account_type=AccountType.investment, currency=Currency.BRL,
        is_active=True, created_at=now, updated_at=now,
    )
    acc_av = Account(
        id=str(uuid.uuid4()), workspace_id=ws.id,
        financial_institution_id=fi_av.id, name="Avenue Inv",
        account_type=AccountType.investment, currency=Currency.USD,
        is_active=True, created_at=now, updated_at=now,
    )

    def _asset(name, ticker, account, current):
        return Asset(
            id=str(uuid.uuid4()), workspace_id=ws.id, account_id=account.id,
            asset_class=AssetClass.STOCK, country="BR" if account is acc_xp else "US",
            name=name, ticker=ticker,
            currency=Currency.BRL if account is acc_xp else Currency.USD,
            current_price=Decimal(str(current)),
            price_source=PriceSource.MANUAL,
            is_active=True, created_at=now, updated_at=now,
        )

    petr = _asset("Petrobras", "PETR4", acc_xp, "30.00")
    itub = _asset("Itaú", "ITUB4", acc_xp, "35.00")
    aapl = _asset("Apple", "AAPL", acc_av, "200.00")
    vale = _asset("Vale", "VALE3", acc_xp, "60.00")  # No pendency.

    snap = PortfolioSnapshot(
        id=str(uuid.uuid4()), workspace_id=ws.id,
        period_end_date=date(2026, 4, 30),
        total_value_brl=Decimal("0"), total_value_usd=Decimal("0"),
        total_invested_brl=Decimal("0"), total_received_brl=Decimal("0"),
        source=SnapshotSource.MANUAL, status=SnapshotStatus.IN_REVIEW,
        notion_sync_status="PENDING",
    )

    db.add_all([user, fi_xp, fi_av, acc_xp, acc_av, petr, itub, aapl, vale, snap])
    db.flush()

    def _pen(asset):
        return SnapshotPendency(
            id=str(uuid.uuid4()), snapshot_id=snap.id, asset_id=asset.id,
            reason=PendencyReason.MANUAL_SOURCE,
            action_type=PendencyAction.EDIT_PRICE,
            created_at=now,
        )

    pen_petr = _pen(petr)
    pen_itub = _pen(itub)
    pen_aapl = _pen(aapl)
    db.add_all([pen_petr, pen_itub, pen_aapl])
    db.flush()
    return {
        "ws_id": ws.id, "user_id": user.id,
        "snap_id": snap.id,
        "petr_id": petr.id, "itub_id": itub.id,
        "aapl_id": aapl.id, "vale_id": vale.id,
        "pen_petr": pen_petr.id, "pen_itub": pen_itub.id, "pen_aapl": pen_aapl.id,
    }


def _make_bulk_job(db, ws_id: str, snap_id: str, user_id: str, payload: dict) -> str:
    """Run create_and_run for a bulk job (no pendency_id) using FakeLLM."""
    set_llm_client(FakeLLM(payload))
    att_id = _make_attachment(ws_id)
    job = extraction_service.create_and_run(
        db,
        workspace_id=ws_id,
        attachment_id=att_id,
        source_hint=ExtractionSourceHint.BROKER_POSITION,
        snapshot_id=snap_id,
        pendency_id=None,
        user_id=user_id,
        user_email="bulk@test.com",
    )
    assert job.status == ExtractionStatus.EXTRACTED, job.error_message
    return job.id


def test_bulk_apply_matches_by_name_when_no_ticker(db):
    """Spec 48 + BTG fix — quando o ticker do extrato bate com Asset.name
    (fundos sem ticker de bolsa), o applier resolve a pendência."""
    from numis_geek.services.workspace import WorkspaceService
    from numis_geek.models.financial_institution import FinancialInstitution
    from numis_geek.models.user import User, UserRole
    import bcrypt

    now = datetime.now(timezone.utc)
    ws = WorkspaceService(db).create("BTG-WS")
    user = User(
        id=str(uuid.uuid4()), workspace_id=ws.id,
        email="btg@test.com", name="BTG",
        password_hash=bcrypt.hashpw(b"x", bcrypt.gensalt()).decode(),
        role=UserRole.admin, is_active=True,
        created_at=now, updated_at=now,
    )
    fi = FinancialInstitution(
        id=str(uuid.uuid4()), long_name="BTG", short_name="BTG", country="BR",
        is_active=True, created_at=now, updated_at=now,
    )
    acc = Account(
        id=str(uuid.uuid4()), workspace_id=ws.id, financial_institution_id=fi.id,
        name="BTG Inv", account_type=AccountType.investment, currency=Currency.BRL,
        is_active=True, created_at=now, updated_at=now,
    )
    # Asset whose ticker IS the fund name (typical for unlisted funds).
    fund = Asset(
        id=str(uuid.uuid4()), workspace_id=ws.id, account_id=acc.id,
        asset_class=AssetClass.STOCK, country="BR",
        name="Fundo Verde BTG (Fundo de Investimento)",
        ticker="Fundo Verde BTG",
        currency=Currency.BRL, current_price=Decimal("100.00"),
        price_source=PriceSource.MANUAL,
        is_active=True, created_at=now, updated_at=now,
    )
    snap = PortfolioSnapshot(
        id=str(uuid.uuid4()), workspace_id=ws.id,
        period_end_date=date(2026, 4, 30),
        total_value_brl=Decimal("0"), total_value_usd=Decimal("0"),
        total_invested_brl=Decimal("0"), total_received_brl=Decimal("0"),
        source=SnapshotSource.MANUAL, status=SnapshotStatus.IN_REVIEW,
        notion_sync_status="PENDING",
    )
    db.add_all([user, fi, acc, fund, snap])
    db.flush()
    pen = SnapshotPendency(
        id=str(uuid.uuid4()), snapshot_id=snap.id, asset_id=fund.id,
        reason=PendencyReason.MANUAL_SOURCE,
        action_type=PendencyAction.EDIT_PRICE,
        created_at=now,
    )
    db.add(pen)
    db.flush()

    # LLM returned the fund name as ticker_raw (since no exchange ticker).
    job_id = _make_bulk_job(db, ws.id, snap.id, user.id, {
        "positions": [
            {"ticker_raw": "Fundo Verde BTG", "quantity": 819.12, "unit_price": 100.0, "confidence": 0.9},
        ]
    })
    result = extraction_service.confirm_extraction(
        db, job_id=job_id, user_id=user.id, user_email="btg@test.com",
    )
    assert result.applied_count == 1
    assert db.get(SnapshotPendency, pen.id).resolved_at is not None


def test_bulk_apply_matches_by_substring_in_name(db):
    """Step 3 fallback — LLM extracted a slightly longer label, but the name
    contains it (or vice versa) unambiguously."""
    from numis_geek.services.workspace import WorkspaceService
    from numis_geek.models.financial_institution import FinancialInstitution
    from numis_geek.models.user import User, UserRole
    import bcrypt

    now = datetime.now(timezone.utc)
    ws = WorkspaceService(db).create("BTG2-WS")
    user = User(
        id=str(uuid.uuid4()), workspace_id=ws.id,
        email="btg2@test.com", name="BTG",
        password_hash=bcrypt.hashpw(b"x", bcrypt.gensalt()).decode(),
        role=UserRole.admin, is_active=True,
        created_at=now, updated_at=now,
    )
    fi = FinancialInstitution(
        id=str(uuid.uuid4()), long_name="BTG", short_name="BTG", country="BR",
        is_active=True, created_at=now, updated_at=now,
    )
    acc = Account(
        id=str(uuid.uuid4()), workspace_id=ws.id, financial_institution_id=fi.id,
        name="BTG Inv", account_type=AccountType.investment, currency=Currency.BRL,
        is_active=True, created_at=now, updated_at=now,
    )
    fund = Asset(
        id=str(uuid.uuid4()), workspace_id=ws.id, account_id=acc.id,
        asset_class=AssetClass.STOCK, country="BR",
        name="Tesouro IPCA+ 2029 com Juros Semestrais",
        ticker="Tesouro IPCA+ 2029",
        currency=Currency.BRL, current_price=Decimal("3500.00"),
        price_source=PriceSource.MANUAL,
        is_active=True, created_at=now, updated_at=now,
    )
    snap = PortfolioSnapshot(
        id=str(uuid.uuid4()), workspace_id=ws.id,
        period_end_date=date(2026, 4, 30),
        total_value_brl=Decimal("0"), total_value_usd=Decimal("0"),
        total_invested_brl=Decimal("0"), total_received_brl=Decimal("0"),
        source=SnapshotSource.MANUAL, status=SnapshotStatus.IN_REVIEW,
        notion_sync_status="PENDING",
    )
    db.add_all([user, fi, acc, fund, snap])
    db.flush()
    pen = SnapshotPendency(
        id=str(uuid.uuid4()), snapshot_id=snap.id, asset_id=fund.id,
        reason=PendencyReason.MANUAL_SOURCE,
        action_type=PendencyAction.EDIT_PRICE,
        created_at=now,
    )
    db.add(pen)
    db.flush()

    # LLM gave a shorter form than the stored ticker (substring case).
    job_id = _make_bulk_job(db, ws.id, snap.id, user.id, {
        "positions": [
            {"ticker_raw": "IPCA+ 2029", "quantity": 1.0, "unit_price": 3650.0, "confidence": 0.85},
        ]
    })
    result = extraction_service.confirm_extraction(
        db, job_id=job_id, user_id=user.id, user_email="btg2@test.com",
    )
    assert result.applied_count == 1


def test_bulk_apply_resolves_matched_pendencies(db):
    w = _world(db)
    # Two matches (PETR4 + ITUB4), one orphan (ABEV3 not in workspace).
    job_id = _make_bulk_job(db, w["ws_id"], w["snap_id"], w["user_id"], {
        "positions": [
            {"ticker_raw": "PETR4", "ticker_normalized": "PETR4", "quantity": 100, "unit_price": 38.50, "confidence": 0.95},
            {"ticker_raw": "ITUB4", "ticker_normalized": "ITUB4", "quantity": 200, "unit_price": 32.10, "confidence": 0.94},
            {"ticker_raw": "ABEV3", "ticker_normalized": "ABEV3", "quantity": 50, "unit_price": 12.00, "confidence": 0.90},
        ]
    })
    result = extraction_service.confirm_extraction(
        db, job_id=job_id, user_id=w["user_id"], user_email="bulk@test.com",
    )
    assert result.applied_count == 2
    assert result.bulk_detail is not None
    applied_tickers = {a["ticker"] for a in result.bulk_detail.applied}
    assert applied_tickers == {"PETR4", "ITUB4"}
    orphan_tickers = {o["ticker"] for o in result.bulk_detail.orphan}
    assert orphan_tickers == {"ABEV3"}
    # PETR4 and ITUB4 pendencies are resolved; AAPL is still open.
    petr = db.get(Asset, w["petr_id"])
    assert petr.current_price == Decimal("38.50")
    pen_petr = db.get(SnapshotPendency, w["pen_petr"])
    assert pen_petr.resolved_at is not None
    pen_aapl = db.get(SnapshotPendency, w["pen_aapl"])
    assert pen_aapl.resolved_at is None
    # AAPL surfaces in pendency_not_in_extract.
    not_in = {p["pendency_id"] for p in result.bulk_detail.pendency_not_in_extract}
    assert w["pen_aapl"] in not_in


def test_bulk_apply_categorizes_matched_without_pendency(db):
    w = _world(db)
    # VALE3 exists but has no pendency — should land in matched_no_pendency,
    # and its current_price should NOT change.
    vale_before = db.get(Asset, w["vale_id"]).current_price
    job_id = _make_bulk_job(db, w["ws_id"], w["snap_id"], w["user_id"], {
        "positions": [
            {"ticker_raw": "VALE3", "ticker_normalized": "VALE3", "quantity": 10, "unit_price": 99.99, "confidence": 0.9},
        ]
    })
    result = extraction_service.confirm_extraction(
        db, job_id=job_id, user_id=w["user_id"], user_email="bulk@test.com",
    )
    assert result.applied_count == 0
    assert result.bulk_detail is not None
    no_pen_tickers = {m["ticker"] for m in result.bulk_detail.matched_no_pendency}
    assert no_pen_tickers == {"VALE3"}
    # Price untouched — bulk path only changes prices that close pendencies.
    assert db.get(Asset, w["vale_id"]).current_price == vale_before


def test_bulk_apply_scopes_by_institution(db):
    w = _world(db)
    # Same extract covers PETR4 (XP) and AAPL (Avenue); user marks FI=XP at
    # review time, so only PETR4 closes.
    job_id = _make_bulk_job(db, w["ws_id"], w["snap_id"], w["user_id"], {
        "positions": [
            {"ticker_raw": "PETR4", "ticker_normalized": "PETR4", "quantity": 100, "unit_price": 40.00, "confidence": 0.9},
            {"ticker_raw": "AAPL", "ticker_normalized": "AAPL", "quantity": 5, "unit_price": 210.00, "confidence": 0.9},
        ]
    })
    result = extraction_service.confirm_extraction(
        db, job_id=job_id, user_id=w["user_id"], user_email="bulk@test.com",
        institution_short_name="XP",
    )
    assert result.applied_count == 1
    applied_tickers = {a["ticker"] for a in result.bulk_detail.applied}
    assert applied_tickers == {"PETR4"}
    # AAPL pendency remains open (FI filter excluded it).
    assert db.get(SnapshotPendency, w["pen_aapl"]).resolved_at is None
    # AAPL doesn't appear in pendency_not_in_extract either — out of FI scope.
    pendency_ids = {p["pendency_id"] for p in result.bulk_detail.pendency_not_in_extract}
    assert w["pen_aapl"] not in pendency_ids


def test_delete_attachment_cascades_extracted_job(db):
    """Spec 49 — anexo com job EXTRACTED (não confirmado) pode ser deletado;
    o job é cascateado."""
    from fastapi.testclient import TestClient
    from numis_geek.api.app import app
    from numis_geek.api.deps import get_db
    from numis_geek.models.attachment import Attachment
    from numis_geek.models.extraction_job import ExtractionJob, ExtractionStatus
    from numis_geek.services.auth import AuthService

    w = _world(db)
    job_id = _make_bulk_job(db, w["ws_id"], w["snap_id"], w["user_id"], {
        "positions": [
            {"ticker_raw": "PETR4", "ticker_normalized": "PETR4", "quantity": 100, "unit_price": 38.50, "confidence": 0.95},
        ]
    })
    job = db.get(ExtractionJob, job_id)
    att_id = job.attachment_id
    db.commit()
    user_email = db.get(__import__("numis_geek.models.user", fromlist=["User"]).User, w["user_id"]).email
    token = AuthService(db).login(user_email, "x")
    app.dependency_overrides[get_db] = lambda: (yield db)
    try:
        with TestClient(app) as c:
            r = c.delete(f"/api/attachments/{att_id}", headers={"Authorization": f"Bearer {token}"})
            assert r.status_code == 204, r.text
    finally:
        app.dependency_overrides.clear()
    # Both the attachment and the EXTRACTED job are gone.
    assert db.get(Attachment, att_id) is None
    assert db.get(ExtractionJob, job_id) is None


def test_delete_attachment_allowed_when_confirmed_job_snapshot_deleted(db):
    """Spec 49 hotfix #8 — quando o snapshot do CONFIRMED job foi
    destruído (cron force_reopen anterior, revert manual), o job é
    órfão e NÃO deve mais bloquear delete do anexo."""
    from fastapi.testclient import TestClient
    from numis_geek.api.app import app
    from numis_geek.api.deps import get_db
    from numis_geek.models.attachment import Attachment
    from numis_geek.models.extraction_job import ExtractionJob
    from numis_geek.services.auth import AuthService

    w = _world(db)
    job_id = _make_bulk_job(db, w["ws_id"], w["snap_id"], w["user_id"], {
        "positions": [
            {"ticker_raw": "PETR4", "ticker_normalized": "PETR4",
             "quantity": 100, "unit_price": 38.50, "confidence": 0.95},
        ]
    })
    extraction_service.confirm_extraction(
        db, job_id=job_id, user_id=w["user_id"], user_email="bulk@test.com",
    )
    job = db.get(ExtractionJob, job_id)
    att_id = job.attachment_id

    # Simula o cron destruir o snapshot — job vira órfão.
    snap = db.get(PortfolioSnapshot, w["snap_id"])
    db.delete(snap)
    db.flush()
    assert db.get(PortfolioSnapshot, w["snap_id"]) is None
    # Job still references the deleted snapshot id.
    job = db.get(ExtractionJob, job_id)
    assert job.status.value == "CONFIRMED"
    db.commit()

    user_email = db.get(__import__("numis_geek.models.user", fromlist=["User"]).User, w["user_id"]).email
    token = AuthService(db).login(user_email, "x")
    app.dependency_overrides[get_db] = lambda: (yield db)
    try:
        with TestClient(app) as c:
            r = c.delete(f"/api/attachments/{att_id}", headers={"Authorization": f"Bearer {token}"})
            assert r.status_code == 204, r.text
    finally:
        app.dependency_overrides.clear()
    assert db.get(Attachment, att_id) is None


def test_delete_attachment_blocked_when_job_confirmed(db):
    """Spec 49 — anexo com job CONFIRMED bloqueia delete com 409 claro."""
    from fastapi.testclient import TestClient
    from numis_geek.api.app import app
    from numis_geek.api.deps import get_db
    from numis_geek.models.extraction_job import ExtractionJob
    from numis_geek.services.auth import AuthService

    w = _world(db)
    job_id = _make_bulk_job(db, w["ws_id"], w["snap_id"], w["user_id"], {
        "positions": [
            {"ticker_raw": "PETR4", "ticker_normalized": "PETR4", "quantity": 100, "unit_price": 38.50, "confidence": 0.95},
        ]
    })
    extraction_service.confirm_extraction(
        db, job_id=job_id, user_id=w["user_id"], user_email="bulk@test.com",
    )
    job = db.get(ExtractionJob, job_id)
    att_id = job.attachment_id
    db.commit()
    user_email = db.get(__import__("numis_geek.models.user", fromlist=["User"]).User, w["user_id"]).email
    token = AuthService(db).login(user_email, "x")
    app.dependency_overrides[get_db] = lambda: (yield db)
    try:
        with TestClient(app) as c:
            r = c.delete(f"/api/attachments/{att_id}", headers={"Authorization": f"Bearer {token}"})
            assert r.status_code == 409
            assert "Reabra o fechamento" in r.json()["detail"]
    finally:
        app.dependency_overrides.clear()


def test_manual_mapping_resolves_orphan(db):
    """Spec 49 hotfix — usuário mapeia órfã ('Fundos de Investimento') pra
    pendência aberta via manual_mappings; o applier honra o override."""
    w = _world(db)
    # PETR4 está cadastrado normalmente; o extrato traz um label genérico
    # ("XYZ Generic Fund") que NÃO bate com nenhum asset.
    job_id = _make_bulk_job(db, w["ws_id"], w["snap_id"], w["user_id"], {
        "positions": [
            {"ticker_raw": "XYZ Generic Fund", "quantity": 1, "unit_price": 81912.21, "confidence": 0.9},
        ]
    })
    # Sem mapping → orphan, sem applied.
    result_no_map = extraction_service.confirm_extraction(
        db, job_id=_make_bulk_job(db, w["ws_id"], w["snap_id"], w["user_id"], {
            "positions": [
                {"ticker_raw": "XYZ Generic Fund", "quantity": 1, "unit_price": 81912.21, "confidence": 0.9},
            ]
        }),
        user_id=w["user_id"], user_email="bulk@test.com",
    )
    assert result_no_map.applied_count == 0
    assert len(result_no_map.bulk_detail.orphan) == 1

    # Com mapping → órfã vira applied resolvendo a pendência alvo (PETR4).
    result = extraction_service.confirm_extraction(
        db, job_id=job_id,
        user_id=w["user_id"], user_email="bulk@test.com",
        manual_mappings={"XYZ Generic Fund": w["pen_petr"]},
    )
    assert result.applied_count == 1
    applied_pendency_ids = {a["pendency_id"] for a in result.bulk_detail.applied}
    assert w["pen_petr"] in applied_pendency_ids
    # Pendency está resolvida com o preço extraído.
    from numis_geek.models.portfolio_snapshot import SnapshotPendency
    pen = db.get(SnapshotPendency, w["pen_petr"])
    assert pen.resolved_at is not None


def test_manual_mapping_with_price_override_when_extract_lacks_price(db):
    """Spec 49 hotfix #2 — extratos de previdência têm posição mas sem preço
    unitário. Usuário mapeia + informa o preço manualmente. Aplica."""
    w = _world(db)
    job_id = _make_bulk_job(db, w["ws_id"], w["snap_id"], w["user_id"], {
        "positions": [
            {"ticker_raw": "FOLHAPREV", "quantity": 1.0, "unit_price": None, "confidence": 0.95},
        ]
    })
    # Sem manual_prices → permanece órfã (preço null + sem fallback).
    result_no_price = extraction_service.confirm_extraction(
        db, job_id=_make_bulk_job(db, w["ws_id"], w["snap_id"], w["user_id"], {
            "positions": [
                {"ticker_raw": "FOLHAPREV", "quantity": 1.0, "unit_price": None, "confidence": 0.95},
            ]
        }),
        user_id=w["user_id"], user_email="bulk@test.com",
        manual_mappings={"FOLHAPREV": w["pen_petr"]},
    )
    # Mapeou mas sem preço — pula com erro descritivo.
    assert result_no_price.applied_count == 0
    assert any("sem preço" in e.lower() for e in result_no_price.errors)

    # Com manual_prices → resolve.
    result = extraction_service.confirm_extraction(
        db, job_id=job_id,
        user_id=w["user_id"], user_email="bulk@test.com",
        manual_mappings={"FOLHAPREV": w["pen_petr"]},
        manual_prices={"FOLHAPREV": 81912.21},
    )
    assert result.applied_count == 1
    from numis_geek.models.portfolio_snapshot import SnapshotPendency
    pen = db.get(SnapshotPendency, w["pen_petr"])
    assert pen.resolved_at is not None


def test_bulk_apply_falls_back_to_market_value_when_unit_price_null(db):
    """When the LLM extracts market_value but not unit_price (common in
    consolidated statements), the applier uses market_value."""
    w = _world(db)
    job_id = _make_bulk_job(db, w["ws_id"], w["snap_id"], w["user_id"], {
        "positions": [
            {"ticker_raw": "PETR4", "ticker_normalized": "PETR4",
             "quantity": 100, "unit_price": None, "market_value": 3850.0,
             "confidence": 0.9},
        ]
    })
    result = extraction_service.confirm_extraction(
        db, job_id=job_id, user_id=w["user_id"], user_email="bulk@test.com",
    )
    assert result.applied_count == 1


def test_manual_mapping_bypasses_fi_filter(db):
    """User maps an orphan to a pendency at FI X even though FI scope
    is set to Y (e.g. forced override). Manual mapping wins."""
    w = _world(db)
    # AAPL belongs to Avenue. User scopes to XP, but maps the orphan
    # explicitly to the AAPL pendency.
    job_id = _make_bulk_job(db, w["ws_id"], w["snap_id"], w["user_id"], {
        "positions": [
            {"ticker_raw": "MYSTERY APPLE", "quantity": 5, "unit_price": 220.0, "confidence": 0.85},
        ]
    })
    result = extraction_service.confirm_extraction(
        db, job_id=job_id, user_id=w["user_id"], user_email="bulk@test.com",
        institution_short_name="XP",
        manual_mappings={"MYSTERY APPLE": w["pen_aapl"]},
    )
    assert result.applied_count == 1
    from numis_geek.models.portfolio_snapshot import SnapshotPendency
    assert db.get(SnapshotPendency, w["pen_aapl"]).resolved_at is not None


def test_bulk_apply_total_mode_for_fund_divides_by_quantity(db):
    """Spec 49 hotfix #4 — quando asset_class é FUND, LLM frequentemente
    retorna o valor total como unit_price. Backend deve detectar e dividir
    pela quantidade existente em vez de multiplicar e explodir o mv."""
    from numis_geek.services.workspace import WorkspaceService
    from numis_geek.models.financial_institution import FinancialInstitution
    from numis_geek.models.asset_movement import AssetMovement, AssetMovementType
    from numis_geek.models.user import User, UserRole
    import bcrypt

    now = datetime.now(timezone.utc)
    ws = WorkspaceService(db).create("FundTotal-WS")
    user = User(
        id=str(uuid.uuid4()), workspace_id=ws.id,
        email="fund@test.com", name="Fund",
        password_hash=bcrypt.hashpw(b"x", bcrypt.gensalt()).decode(),
        role=UserRole.admin, is_active=True,
        created_at=now, updated_at=now,
    )
    fi = FinancialInstitution(
        id=str(uuid.uuid4()), long_name="BTG", short_name="BTG", country="BR",
        is_active=True, created_at=now, updated_at=now,
    )
    acc = Account(
        id=str(uuid.uuid4()), workspace_id=ws.id, financial_institution_id=fi.id,
        name="BTG Inv", account_type=AccountType.investment, currency=Currency.BRL,
        is_active=True, created_at=now, updated_at=now,
    )
    fund = Asset(
        id=str(uuid.uuid4()), workspace_id=ws.id, account_id=acc.id,
        asset_class=AssetClass.FUND, country="BR",
        name="Fundo Verde BTG",
        ticker="Fundo Verde BTG",
        currency=Currency.BRL, current_price=Decimal("1.50"),
        price_source=PriceSource.MANUAL,
        is_active=True, created_at=now, updated_at=now,
    )
    snap = PortfolioSnapshot(
        id=str(uuid.uuid4()), workspace_id=ws.id,
        period_end_date=date(2026, 4, 30),
        total_value_brl=Decimal("0"), total_value_usd=Decimal("0"),
        total_invested_brl=Decimal("0"), total_received_brl=Decimal("0"),
        source=SnapshotSource.MANUAL, status=SnapshotStatus.IN_REVIEW,
        notion_sync_status="PENDING",
    )
    db.add_all([user, fi, acc, fund, snap])
    db.flush()
    # Movement gives quantity 47670 cotas at average cost 1 — typical fund.
    db.add(AssetMovement(
        id=str(uuid.uuid4()), workspace_id=ws.id, asset_id=fund.id,
        type=AssetMovementType.BUY,
        event_date=date(2024, 1, 10),
        quantity=Decimal("47670.305643"), unit_price=Decimal("1.00"),
        gross_amount=Decimal("47670.31"), net_amount=Decimal("47670.31"),
        currency=Currency.BRL, fx_rate=Decimal("1"),
        is_active=True, created_at=now, updated_at=now,
    ))
    pen = SnapshotPendency(
        id=str(uuid.uuid4()), snapshot_id=snap.id, asset_id=fund.id,
        reason=PendencyReason.MANUAL_SOURCE,
        action_type=PendencyAction.EDIT_PRICE,
        created_at=now,
    )
    db.add(pen)
    db.flush()

    # LLM returned 81912.21 as unit_price (but it's really the total!).
    job_id = _make_bulk_job(db, ws.id, snap.id, user.id, {
        "positions": [
            {"ticker_raw": "Fundo Verde BTG", "quantity": 47670.305643,
             "unit_price": 81912.21, "confidence": 0.9},
        ]
    })
    # Seed an existing snapshot item (production path goes through
    # create_snapshot which always creates one).
    db.add(PortfolioSnapshotItem(
        id=str(uuid.uuid4()),
        snapshot_id=snap.id, asset_id=fund.id,
        quantity=Decimal("47670.305643"),
        unit_price=Decimal("1.00"),
        market_value_native=Decimal("47670.31"),
        market_value_brl=Decimal("47670.31"),
    ))
    db.flush()

    result = extraction_service.confirm_extraction(
        db, job_id=job_id, user_id=user.id, user_email="fund@test.com",
    )
    assert result.applied_count == 1
    # market_value brl must be ~81912, NOT 3.9 billion.
    item = (
        db.query(PortfolioSnapshotItem)
        .filter_by(snapshot_id=snap.id, asset_id=fund.id)
        .first()
    )
    assert item is not None
    assert Decimal("81000") < item.market_value_brl < Decimal("82000"), \
        f"expected ~81912 but got {item.market_value_brl}"


def test_confirm_stays_extracted_when_zero_applied(db):
    """Spec 49 hotfix #6 — quando nada foi aplicado (ex: matched sem
    preço), job mantém status EXTRACTED pra user poder retry sem
    re-rodar o LLM. O CONFIRMED com applied=0 antes travava o modal."""
    from numis_geek.models.extraction_job import ExtractionJob, ExtractionStatus

    w = _world(db)
    job_id = _make_bulk_job(db, w["ws_id"], w["snap_id"], w["user_id"], {
        "positions": [
            {"ticker_raw": "PETR4", "ticker_normalized": "PETR4",
             "quantity": 100, "unit_price": None, "confidence": 0.95},
        ]
    })
    result = extraction_service.confirm_extraction(
        db, job_id=job_id, user_id=w["user_id"], user_email="bulk@test.com",
    )
    assert result.applied_count == 0
    job = db.get(ExtractionJob, job_id)
    assert job.status == ExtractionStatus.EXTRACTED  # NÃO confirmado!

    # Agora retry com manual_prices preenchendo → sucesso → CONFIRMED.
    result2 = extraction_service.confirm_extraction(
        db, job_id=job_id, user_id=w["user_id"], user_email="bulk@test.com",
        manual_prices={"PETR4": 42.0},
    )
    assert result2.applied_count == 1
    job = db.get(ExtractionJob, job_id)
    assert job.status == ExtractionStatus.CONFIRMED


def test_resolve_pendency_auto_total_mode_for_fixed_income(db):
    """Spec 49 hotfix #9 — quando user usa o botão Editar (path direto
    resolve_pendency, fora do bulk extract), assets FIXED_INCOME tratam
    o input como TOTAL e dividem por qty antes de armazenar. Caso real:
    SELIC 2029 R$ 124.215,29 / 6.51 cotas = unit ~19080, NOT 124k × 6.51."""
    from numis_geek.services.workspace import WorkspaceService
    from numis_geek.models.financial_institution import FinancialInstitution
    from numis_geek.models.user import User, UserRole
    from numis_geek.models.asset_movement import AssetMovement, AssetMovementType
    from numis_geek.services.snapshot import resolve_pendency
    import bcrypt

    now = datetime.now(timezone.utc)
    ws = WorkspaceService(db).create("SELIC-WS")
    user = User(
        id=str(uuid.uuid4()), workspace_id=ws.id,
        email="selic@test.com", name="S",
        password_hash=bcrypt.hashpw(b"x", bcrypt.gensalt()).decode(),
        role=UserRole.admin, is_active=True,
        created_at=now, updated_at=now,
    )
    fi = FinancialInstitution(
        id=str(uuid.uuid4()), long_name="XP", short_name="XP", country="BR",
        is_active=True, created_at=now, updated_at=now,
    )
    acc = Account(
        id=str(uuid.uuid4()), workspace_id=ws.id, financial_institution_id=fi.id,
        name="XP", account_type=AccountType.investment, currency=Currency.BRL,
        is_active=True, created_at=now, updated_at=now,
    )
    selic = Asset(
        id=str(uuid.uuid4()), workspace_id=ws.id, account_id=acc.id,
        asset_class=AssetClass.FIXED_INCOME, country="BR",
        name="Tesouro Selic 2029 (LFT)", ticker="LFT mar/2029 (SELIC)",
        currency=Currency.BRL, current_price=None,
        price_source=PriceSource.MANUAL,
        is_active=True, created_at=now, updated_at=now,
    )
    db.add_all([user, fi, acc, selic])
    db.add(AssetMovement(
        id=str(uuid.uuid4()), workspace_id=ws.id, asset_id=selic.id,
        type=AssetMovementType.BUY,
        event_date=date(2024, 1, 10),
        quantity=Decimal("6.51"), unit_price=Decimal("10000"),
        gross_amount=Decimal("65100"), net_amount=Decimal("65100"),
        currency=Currency.BRL, fx_rate=Decimal("1"),
        is_active=True, created_at=now, updated_at=now,
    ))
    snap = PortfolioSnapshot(
        id=str(uuid.uuid4()), workspace_id=ws.id,
        period_end_date=date(2026, 4, 30),
        total_value_brl=Decimal("0"), total_value_usd=Decimal("0"),
        total_invested_brl=Decimal("0"), total_received_brl=Decimal("0"),
        source=SnapshotSource.MANUAL, status=SnapshotStatus.IN_REVIEW,
        notion_sync_status="PENDING",
    )
    db.add(snap)
    db.flush()
    db.add(PortfolioSnapshotItem(
        id=str(uuid.uuid4()),
        snapshot_id=snap.id, asset_id=selic.id,
        quantity=Decimal("6.51"),
        unit_price=Decimal("10000"),
        market_value_native=Decimal("65100"),
        market_value_brl=Decimal("65100"),
    ))
    pen = SnapshotPendency(
        id=str(uuid.uuid4()), snapshot_id=snap.id, asset_id=selic.id,
        reason=PendencyReason.MANUAL_SOURCE,
        action_type=PendencyAction.EDIT_PRICE,
        created_at=now,
    )
    db.add(pen)
    db.flush()

    # User types the TOTAL value he sees on his statement.
    resolve_pendency(
        db, pendency_id=pen.id, user_id=user.id,
        new_price=Decimal("124215.29"),
    )

    # Item should have market_value = 124k, NOT 808k.
    item = (
        db.query(PortfolioSnapshotItem)
        .filter_by(snapshot_id=snap.id, asset_id=selic.id)
        .first()
    )
    assert item is not None
    assert Decimal("124000") < item.market_value_brl < Decimal("125000")
    # unit_price stored is 124215.29 / 6.51 ~= 19080
    assert Decimal("19000") < item.unit_price < Decimal("19200")


def test_resolve_pendency_explicit_unit_mode_keeps_price(db):
    """When the user explicitly chooses 'unit' mode (e.g. via FE toggle),
    resolve_pendency stores it as-is even for FIXED_INCOME."""
    from numis_geek.services.snapshot import resolve_pendency

    w = _world(db)
    # PETR4 (STOCK) — default mode is "unit" but we pass it explicitly too.
    resolve_pendency(
        db, pendency_id=w["pen_petr"], user_id=w["user_id"],
        new_price=Decimal("42.00"), value_mode="unit",
    )
    petr = db.get(Asset, w["petr_id"])
    assert petr.current_price == Decimal("42.00")


def test_resolve_pendency_creates_item_when_missing(db):
    """Spec 49 hotfix #5 — resolve_pendency precisa CRIAR o snapshot item
    quando ele não existe (caso típico: ativo sem movimentos como
    previdência, ou item deletado por revert manual)."""
    w = _world(db)
    # Forçar caso: deletar o item da pendency do PETR4 (simula ativo sem item).
    db.query(PortfolioSnapshotItem).filter_by(
        snapshot_id=w["snap_id"], asset_id=w["petr_id"],
    ).delete()
    db.flush()
    assert db.query(PortfolioSnapshotItem).filter_by(
        snapshot_id=w["snap_id"], asset_id=w["petr_id"]
    ).first() is None

    # Apply via bulk com price = 42.00
    job_id = _make_bulk_job(db, w["ws_id"], w["snap_id"], w["user_id"], {
        "positions": [
            {"ticker_raw": "PETR4", "ticker_normalized": "PETR4",
             "quantity": 100, "unit_price": 42.00, "confidence": 0.95},
        ]
    })
    result = extraction_service.confirm_extraction(
        db, job_id=job_id, user_id=w["user_id"], user_email="bulk@test.com",
    )
    assert result.applied_count == 1
    # Item foi CRIADO com market_value = 100 × 42 = 4200.
    item = db.query(PortfolioSnapshotItem).filter_by(
        snapshot_id=w["snap_id"], asset_id=w["petr_id"],
    ).first()
    assert item is not None
    # _world não cria AssetMovements, então compute_position devolve 0 e
    # o fallback do hotfix força qty=1 (caso típico de previdência).
    assert item.quantity == Decimal("1")
    assert item.unit_price == Decimal("42.00")
    assert item.market_value_brl == Decimal("42.00")


def test_bulk_apply_unit_mode_for_stock_uses_price_as_is(db):
    """STOCK asset_class keeps the unit_price semantic (default)."""
    w = _world(db)
    job_id = _make_bulk_job(db, w["ws_id"], w["snap_id"], w["user_id"], {
        "positions": [
            {"ticker_raw": "PETR4", "ticker_normalized": "PETR4",
             "quantity": 100, "unit_price": 38.50, "confidence": 0.95},
        ]
    })
    result = extraction_service.confirm_extraction(
        db, job_id=job_id, user_id=w["user_id"], user_email="bulk@test.com",
    )
    assert result.applied_count == 1
    petr = db.get(Asset, w["petr_id"])
    assert petr.current_price == Decimal("38.50")  # NOT divided by 100


def test_bulk_apply_stores_attachment_in_audit(db):
    w = _world(db)
    job_id = _make_bulk_job(db, w["ws_id"], w["snap_id"], w["user_id"], {
        "positions": [
            {"ticker_raw": "PETR4", "ticker_normalized": "PETR4", "quantity": 100, "unit_price": 38.50, "confidence": 0.95},
        ]
    })
    extraction_service.confirm_extraction(
        db, job_id=job_id, user_id=w["user_id"], user_email="bulk@test.com",
        institution_short_name="XP",
    )
    db.commit()
    # extraction.confirmed audit row carries institution_short_name in details.
    rows = (
        db.query(AuditLog)
        .filter(AuditLog.action == "extraction.confirmed")
        .all()
    )
    assert len(rows) >= 1
    assert any(
        r.details and '"institution_short_name": "XP"' in r.details
        for r in rows
    )


# ── Avenue regression: ticker normalization + auto-priced skip ──────────────


def test_bulk_apply_matches_ticker_case_insensitive_with_whitespace(db):
    """Ticker comparison must strip + lowercase both sides — LLM output
    isn't guaranteed to be uppercase or trimmed."""
    w = _world(db)
    job_id = _make_bulk_job(db, w["ws_id"], w["snap_id"], w["user_id"], {
        "positions": [
            # lowercase, trailing space
            {"ticker_raw": "petr4 ", "ticker_normalized": "petr4 ",
             "quantity": 100, "unit_price": 41.00, "confidence": 0.9},
            # mixed case, leading space
            {"ticker_raw": " Itub4", "ticker_normalized": " Itub4",
             "quantity": 200, "unit_price": 33.00, "confidence": 0.9},
        ]
    })
    result = extraction_service.confirm_extraction(
        db, job_id=job_id, user_id=w["user_id"], user_email="bulk@test.com",
    )
    assert result.applied_count == 2, result.bulk_detail
    assert result.bulk_detail.orphan == []
    assert db.get(Asset, w["petr_id"]).current_price == Decimal("41.00")
    assert db.get(Asset, w["itub_id"]).current_price == Decimal("33.00")


def test_bulk_apply_skips_auto_priced_assets(db):
    """Assets with automated price source (BRAPI/FINNHUB/...) must be
    ignored by extract apply — their price is owned by the provider and
    even an open RETRY_API pendency must not be resolved this way."""
    from numis_geek.services.workspace import WorkspaceService
    from numis_geek.models.user import User, UserRole

    now = datetime.now(timezone.utc)
    ws = WorkspaceService(db).create(f"AutoPriced-{uuid.uuid4().hex[:6]}")
    user = User(
        id=str(uuid.uuid4()), workspace_id=ws.id,
        email=f"auto-{uuid.uuid4().hex[:6]}@test.com", name="Auto",
        password_hash=bcrypt.hashpw(b"x", bcrypt.gensalt()).decode(),
        role=UserRole.admin, is_active=True,
        created_at=now, updated_at=now,
    )
    fi = FinancialInstitution(
        id=str(uuid.uuid4()), long_name="Avenue", short_name="Avenue",
        country="US", is_active=True, created_at=now, updated_at=now,
    )
    acc = Account(
        id=str(uuid.uuid4()), workspace_id=ws.id, financial_institution_id=fi.id,
        name="Avenue Inv", account_type=AccountType.investment,
        currency=Currency.USD, is_active=True, created_at=now, updated_at=now,
    )
    # Auto-priced via FINNHUB (typical for AAPL/MSFT etc). Pre-existing
    # current_price must NOT be overwritten by the extract.
    aapl = Asset(
        id=str(uuid.uuid4()), workspace_id=ws.id, account_id=acc.id,
        asset_class=AssetClass.STOCK, country="US",
        name="Apple Inc", ticker="AAPL",
        currency=Currency.USD,
        current_price=Decimal("200.00"),
        price_source=PriceSource.FINNHUB,
        is_active=True, created_at=now, updated_at=now,
    )
    snap = PortfolioSnapshot(
        id=str(uuid.uuid4()), workspace_id=ws.id,
        period_end_date=date(2026, 4, 30),
        total_value_brl=Decimal("0"), total_value_usd=Decimal("0"),
        total_invested_brl=Decimal("0"), total_received_brl=Decimal("0"),
        source=SnapshotSource.MANUAL, status=SnapshotStatus.IN_REVIEW,
        notion_sync_status="PENDING",
    )
    db.add_all([user, fi, acc, aapl, snap])
    db.flush()
    # Open RETRY_API pendency — should NOT be resolved by the extract.
    pen = SnapshotPendency(
        id=str(uuid.uuid4()), snapshot_id=snap.id, asset_id=aapl.id,
        reason=PendencyReason.STALE_PRICE,
        action_type=PendencyAction.RETRY_API,
        created_at=now,
    )
    db.add(pen)
    db.flush()

    job_id = _make_bulk_job(db, ws.id, snap.id, user.id, {
        "positions": [
            {"ticker_raw": "AAPL", "ticker_normalized": "AAPL",
             "quantity": 5, "unit_price": 999.99, "confidence": 0.95},
        ]
    })
    result = extraction_service.confirm_extraction(
        db, job_id=job_id, user_id=user.id, user_email="auto@test.com",
    )
    # Skipped silently — neither applied, nor matched_no_pendency, nor orphan.
    assert result.applied_count == 0
    assert result.bulk_detail.applied == []
    assert result.bulk_detail.matched_no_pendency == []
    assert result.bulk_detail.orphan == []
    # Price untouched, RETRY_API pendency still open.
    assert db.get(Asset, aapl.id).current_price == Decimal("200.00")
    assert db.get(SnapshotPendency, pen.id).resolved_at is None
    # And the RETRY_API pendency does NOT leak into pendency_not_in_extract,
    # because the bulk path filters it out from the open list entirely.
    not_in_ids = {p["pendency_id"] for p in result.bulk_detail.pendency_not_in_extract}
    assert pen.id not in not_in_ids
    # Spec 57 follow-up — auto-priced match is surfaced in auto_skipped,
    # NOT orphan, so the UI can show "recognized, no action needed".
    auto_tickers = {a["ticker"] for a in result.bulk_detail.auto_skipped}
    assert auto_tickers == {"AAPL"}
    orphan_tickers = {o["ticker"] for o in result.bulk_detail.orphan}
    assert "AAPL" not in orphan_tickers


def test_preview_bulk_extract_classifies_without_writes(db):
    """preview_bulk_extract returns the same buckets that confirm would,
    but performs no DB writes — Asset prices/pendencies unchanged."""
    w = _world(db)
    # PETR4 (matched), VALE3 (matched but no pendency), ABEV3 (orphan).
    job_id = _make_bulk_job(db, w["ws_id"], w["snap_id"], w["user_id"], {
        "positions": [
            {"ticker_raw": "PETR4", "ticker_normalized": "PETR4",
             "quantity": 100, "unit_price": 38.50, "confidence": 0.95},
            {"ticker_raw": "VALE3", "ticker_normalized": "VALE3",
             "quantity": 10, "unit_price": 99.00, "confidence": 0.9},
            {"ticker_raw": "ABEV3", "ticker_normalized": "ABEV3",
             "quantity": 50, "unit_price": 12.00, "confidence": 0.9},
        ]
    })
    petr_before = db.get(Asset, w["petr_id"]).current_price
    vale_before = db.get(Asset, w["vale_id"]).current_price
    pen_petr_before = db.get(SnapshotPendency, w["pen_petr"]).resolved_at

    result = extraction_service.preview_bulk_extract(db, job_id=job_id)

    # Classification mirrors confirm.
    assert {a["ticker"] for a in result.bulk_detail.applied} == {"PETR4"}
    assert {m["ticker"] for m in result.bulk_detail.matched_no_pendency} == {"VALE3"}
    assert {o["ticker"] for o in result.bulk_detail.orphan} == {"ABEV3"}
    # No writes happened.
    assert db.get(Asset, w["petr_id"]).current_price == petr_before
    assert db.get(Asset, w["vale_id"]).current_price == vale_before
    assert db.get(SnapshotPendency, w["pen_petr"]).resolved_at == pen_petr_before


# ── Step 3 substring: ticker + aggressive normalization (Franklin case) ─────


def _make_minimal_world(db, fund_name: str, fund_ticker: str):
    """Single-asset workspace fixture for matcher edge cases."""
    from numis_geek.services.workspace import WorkspaceService
    from numis_geek.models.user import User, UserRole

    now = datetime.now(timezone.utc)
    ws = WorkspaceService(db).create(f"Match-{uuid.uuid4().hex[:6]}")
    user = User(
        id=str(uuid.uuid4()), workspace_id=ws.id,
        email=f"m-{uuid.uuid4().hex[:6]}@test.com", name="M",
        password_hash=bcrypt.hashpw(b"x", bcrypt.gensalt()).decode(),
        role=UserRole.admin, is_active=True,
        created_at=now, updated_at=now,
    )
    fi = FinancialInstitution(
        id=str(uuid.uuid4()), long_name="Avenue", short_name="Avenue",
        country="US", is_active=True, created_at=now, updated_at=now,
    )
    acc = Account(
        id=str(uuid.uuid4()), workspace_id=ws.id, financial_institution_id=fi.id,
        name="Avenue Inv", account_type=AccountType.investment,
        currency=Currency.USD, is_active=True, created_at=now, updated_at=now,
    )
    fund = Asset(
        id=str(uuid.uuid4()), workspace_id=ws.id, account_id=acc.id,
        asset_class=AssetClass.STOCK, country="US",
        name=fund_name, ticker=fund_ticker,
        currency=Currency.USD, current_price=Decimal("100.00"),
        price_source=PriceSource.MANUAL,
        is_active=True, created_at=now, updated_at=now,
    )
    snap = PortfolioSnapshot(
        id=str(uuid.uuid4()), workspace_id=ws.id,
        period_end_date=date(2026, 4, 30),
        total_value_brl=Decimal("0"), total_value_usd=Decimal("0"),
        total_invested_brl=Decimal("0"), total_received_brl=Decimal("0"),
        source=SnapshotSource.MANUAL, status=SnapshotStatus.IN_REVIEW,
        notion_sync_status="PENDING",
    )
    db.add_all([user, fi, acc, fund, snap])
    db.flush()
    pen = SnapshotPendency(
        id=str(uuid.uuid4()), snapshot_id=snap.id, asset_id=fund.id,
        reason=PendencyReason.MANUAL_SOURCE,
        action_type=PendencyAction.EDIT_PRICE,
        created_at=now,
    )
    db.add(pen)
    db.flush()
    return {"ws_id": ws.id, "user_id": user.id, "snap_id": snap.id,
            "asset_id": fund.id, "pen_id": pen.id}


def test_resolve_uses_ticker_substring_with_punctuation():
    """Spec 57 follow-up — Step 3 matches Asset.ticker (not only name) and
    normalizes punctuation. Real case: Asset.ticker='Franklin U.S. Dollar'
    + Asset.name='Franklin U.S. Dollar S/T MMF A(acc)USD' must resolve
    when extract emits 'Franklin U.S. Dollar-ST MMF Adv'."""
    from numis_geek.services.extraction import _resolve_asset_by_ticker_or_name

    s = TestSession()
    try:
        w = _make_minimal_world(
            s,
            fund_name="Franklin U.S. Dollar S/T MMF A(acc)USD",
            fund_ticker="Franklin U.S. Dollar",
        )
        hit = _resolve_asset_by_ticker_or_name(
            s, w["ws_id"], "Franklin U.S. Dollar-ST MMF Adv",
        )
        assert hit is not None
        assert hit.id == w["asset_id"]
    finally:
        s.rollback()
        s.close()


def test_resolve_ambiguous_match_returns_none():
    """Two assets whose normalized form is substring of the same candidate
    is too risky to auto-resolve — returns None and lets user map manually."""
    from numis_geek.services.extraction import _resolve_asset_by_ticker_or_name
    from numis_geek.services.workspace import WorkspaceService
    from numis_geek.models.user import User, UserRole

    s = TestSession()
    try:
        now = datetime.now(timezone.utc)
        ws = WorkspaceService(s).create(f"Amb-{uuid.uuid4().hex[:6]}")
        user = User(
            id=str(uuid.uuid4()), workspace_id=ws.id,
            email=f"amb-{uuid.uuid4().hex[:6]}@test.com", name="A",
            password_hash=bcrypt.hashpw(b"x", bcrypt.gensalt()).decode(),
            role=UserRole.admin, is_active=True,
            created_at=now, updated_at=now,
        )
        fi = FinancialInstitution(
            id=str(uuid.uuid4()), long_name="X", short_name="X", country="BR",
            is_active=True, created_at=now, updated_at=now,
        )
        acc = Account(
            id=str(uuid.uuid4()), workspace_id=ws.id, financial_institution_id=fi.id,
            name="Inv", account_type=AccountType.investment, currency=Currency.BRL,
            is_active=True, created_at=now, updated_at=now,
        )
        # Both tickers normalize to substring of 'tesouroipca2029notas...'.
        a1 = Asset(
            id=str(uuid.uuid4()), workspace_id=ws.id, account_id=acc.id,
            asset_class=AssetClass.STOCK, country="BR",
            name="Tesouro IPCA Long", ticker="Tesouro IPCA",
            currency=Currency.BRL, current_price=Decimal("1"),
            price_source=PriceSource.MANUAL,
            is_active=True, created_at=now, updated_at=now,
        )
        a2 = Asset(
            id=str(uuid.uuid4()), workspace_id=ws.id, account_id=acc.id,
            asset_class=AssetClass.STOCK, country="BR",
            name="Tesouro IPCA 2029 Curto", ticker="Tesouro IPCA 2029",
            currency=Currency.BRL, current_price=Decimal("1"),
            price_source=PriceSource.MANUAL,
            is_active=True, created_at=now, updated_at=now,
        )
        s.add_all([user, fi, acc, a1, a2])
        s.flush()
        # Both tickers normalize to substrings of 'tesouroipca2029longo':
        # 'tesouroipca' (a1.ticker) ⊂ … and 'tesouroipca2029' (a2.ticker) ⊂ …
        # → multi-match → None.
        hit = _resolve_asset_by_ticker_or_name(s, ws.id, "Tesouro IPCA 2029 Longo")
        assert hit is None
    finally:
        s.rollback()
        s.close()


def test_resolve_minimum_length_guard():
    """Candidate with < 4 alphanumeric chars after normalize must not
    trigger substring match (would over-match)."""
    from numis_geek.services.extraction import _resolve_asset_by_ticker_or_name

    s = TestSession()
    try:
        w = _make_minimal_world(
            s, fund_name="Apple Inc", fund_ticker="AAPL",
        )
        # 'A.A.' normalizes to 'aa' (2 chars) → guard returns None.
        hit = _resolve_asset_by_ticker_or_name(s, w["ws_id"], "A.A.")
        assert hit is None
    finally:
        s.rollback()
        s.close()


# ── Step 4 date-based match: cross-format treasury / bond matching ──────────


def test_resolve_date_match_jpm_cross_format():
    """Real Avenue case: extract emits 'JPMorgan Chase 2033-09-14' (ISO),
    asset is registered as 'JPM 5.717 14/09/33' (BR DD/MM/YY). Step 3
    substring fails (no shared tokens), but Step 4 date match wins."""
    from numis_geek.services.extraction import _resolve_asset_by_ticker_or_name

    s = TestSession()
    try:
        w = _make_minimal_world(
            s, fund_name="JPM 5.717 14/09/33", fund_ticker="JPM 5.717 14/09/33",
        )
        hit = _resolve_asset_by_ticker_or_name(
            s, w["ws_id"], "JPMorgan Chase 2033-09-14",
        )
        assert hit is not None
        assert hit.id == w["asset_id"]
    finally:
        s.rollback()
        s.close()


def test_resolve_date_match_no_overlap_returns_none():
    """Different maturity dates → no Step-4 hit. (And no Step-3 hit since
    'US Treasury' isn't a substring of 'T 3.875 15/08/34'.)"""
    from numis_geek.services.extraction import _resolve_asset_by_ticker_or_name

    s = TestSession()
    try:
        w = _make_minimal_world(
            s, fund_name="T 3.875 15/08/34", fund_ticker="T 3.875 15/08/34",
        )
        # Extract date 2034-05-16 vs asset 2034-08-15 → no overlap.
        hit = _resolve_asset_by_ticker_or_name(
            s, w["ws_id"], "US Treasury 2034-05-16",
        )
        assert hit is None
    finally:
        s.rollback()
        s.close()


def test_resolve_date_match_ambiguous_multi_match_returns_none():
    """Candidate date overlaps with two assets → None (don't guess)."""
    from numis_geek.services.extraction import _resolve_asset_by_ticker_or_name
    from numis_geek.services.workspace import WorkspaceService
    from numis_geek.models.user import User, UserRole

    s = TestSession()
    try:
        now = datetime.now(timezone.utc)
        ws = WorkspaceService(s).create(f"DateAmb-{uuid.uuid4().hex[:6]}")
        user = User(
            id=str(uuid.uuid4()), workspace_id=ws.id,
            email=f"da-{uuid.uuid4().hex[:6]}@test.com", name="DA",
            password_hash=bcrypt.hashpw(b"x", bcrypt.gensalt()).decode(),
            role=UserRole.admin, is_active=True,
            created_at=now, updated_at=now,
        )
        fi = FinancialInstitution(
            id=str(uuid.uuid4()), long_name="X", short_name="X", country="US",
            is_active=True, created_at=now, updated_at=now,
        )
        acc = Account(
            id=str(uuid.uuid4()), workspace_id=ws.id, financial_institution_id=fi.id,
            name="Inv", account_type=AccountType.investment, currency=Currency.USD,
            is_active=True, created_at=now, updated_at=now,
        )
        # Two bonds with the same maturity date → ambiguous.
        a1 = Asset(
            id=str(uuid.uuid4()), workspace_id=ws.id, account_id=acc.id,
            asset_class=AssetClass.STOCK, country="US",
            name="Bond A 14/09/33", ticker="A 14/09/33",
            currency=Currency.USD, current_price=Decimal("100"),
            price_source=PriceSource.MANUAL,
            is_active=True, created_at=now, updated_at=now,
        )
        a2 = Asset(
            id=str(uuid.uuid4()), workspace_id=ws.id, account_id=acc.id,
            asset_class=AssetClass.STOCK, country="US",
            name="Bond B 14/09/33", ticker="B 14/09/33",
            currency=Currency.USD, current_price=Decimal("100"),
            price_source=PriceSource.MANUAL,
            is_active=True, created_at=now, updated_at=now,
        )
        s.add_all([user, fi, acc, a1, a2])
        s.flush()
        hit = _resolve_asset_by_ticker_or_name(s, ws.id, "Random Bond 2033-09-14")
        assert hit is None
    finally:
        s.rollback()
        s.close()


def test_resolve_date_match_no_date_in_candidate_skipped():
    """No date in candidate → Step 4 doesn't fire (no false match against
    asset that happens to have a date)."""
    from numis_geek.services.extraction import _resolve_asset_by_ticker_or_name

    s = TestSession()
    try:
        w = _make_minimal_world(
            s, fund_name="T 3.875 15/08/34", fund_ticker="T 3.875 15/08/34",
        )
        # 'AAPL' has no date → Step 4 doesn't try → None.
        hit = _resolve_asset_by_ticker_or_name(s, w["ws_id"], "AAPL")
        assert hit is None
    finally:
        s.rollback()
        s.close()
