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
    PendencyAction, PendencyReason, PortfolioSnapshot, SnapshotPendency,
    SnapshotSource, SnapshotStatus,
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
