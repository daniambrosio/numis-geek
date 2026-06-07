"""Spec 38 — extraction service tests.

These tests inject a fake LLM client via `set_llm_client` so they never
call the Anthropic API. End-to-end coverage:

- Job creation + LLM call + parse → status EXTRACTED with the JSON we
  programmed the fake to return.
- `confirm_extraction` applies a SCREENSHOT_PRICE payload to the linked
  Asset's `current_price` and resolves the pendency.
- `confirm_extraction` for BROKER_POSITION updates multiple Assets and
  skips unknown tickers.
- `reject_extraction` flips status to REJECTED without applying anything.
"""
from __future__ import annotations

import json
import shutil
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import bcrypt
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from numis_geek.db.base import Base
import numis_geek.models  # noqa: F401
from numis_geek.models.account import Account, AccountType, Currency
from numis_geek.models.asset import Asset, AssetClass
from numis_geek.models.attachment import Attachment, AttachmentKind, AttachmentSourceType
from numis_geek.models.extraction_job import (
    ExtractionJob, ExtractionSourceHint, ExtractionStatus,
)
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
    target = tmp_path_factory.mktemp("extraction_atts")
    original = attachment_storage.ROOT
    attachment_storage.ROOT = target
    yield target
    attachment_storage.ROOT = original
    shutil.rmtree(target, ignore_errors=True)


@pytest.fixture
def db():
    session = TestSession()
    yield session
    session.rollback()
    session.close()


@pytest.fixture(scope="module")
def seed():
    db = TestSession()
    ws = WorkspaceService(db).create("ExtractionWS")

    now = datetime.now(timezone.utc)
    user = User(
        id=str(uuid.uuid4()),
        workspace_id=ws.id,
        email="ex@test.com",
        name="Ex",
        password_hash=bcrypt.hashpw(b"x", bcrypt.gensalt()).decode(),
        role=UserRole.admin,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    fi = FinancialInstitution(
        id=str(uuid.uuid4()), long_name="FI", short_name="FI", country="BR",
        is_active=True, created_at=now, updated_at=now,
    )
    acc = Account(
        id=str(uuid.uuid4()), workspace_id=ws.id,
        financial_institution_id=fi.id, name="Conta", account_type=AccountType.investment,
        currency=Currency.BRL, opening_balance=Decimal("0"),
        is_active=True, created_at=now, updated_at=now,
    )
    petr = Asset(
        id=str(uuid.uuid4()), workspace_id=ws.id, account_id=acc.id,
        asset_class=AssetClass.STOCK, country="BR", name="Petrobras",
        ticker="PETR4", currency=Currency.BRL, current_price=Decimal("30.00"),
        is_active=True, created_at=now, updated_at=now,
    )
    itub = Asset(
        id=str(uuid.uuid4()), workspace_id=ws.id, account_id=acc.id,
        asset_class=AssetClass.STOCK, country="BR", name="Itaú",
        ticker="ITUB4", currency=Currency.BRL, current_price=Decimal("35.00"),
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

    db.add_all([user, fi, acc, petr, itub, snap])
    db.commit()

    pen = SnapshotPendency(
        id=str(uuid.uuid4()), snapshot_id=snap.id, asset_id=petr.id,
        reason=PendencyReason.UPLOAD_REQUIRED,
        action_type=PendencyAction.UPLOAD_FILE,
        detail="manual upload required",
        created_at=now,
    )
    db.add(pen)
    db.commit()

    out = {
        "ws_id": ws.id, "user_id": user.id, "snap_id": snap.id,
        "pen_id": pen.id, "petr_id": petr.id, "itub_id": itub.id,
    }
    db.close()
    return out


def _make_attachment(ws_id: str, *, kind=AttachmentKind.IMAGE) -> str:
    """Create a tiny on-disk attachment so extraction has something to read."""
    db = TestSession()
    fake_png = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
        "0000000a49444154789c6300010000000500010d0a2db40000000049454e44ae426082"
    )
    saved = attachment_storage.save_bytes(ws_id, fake_png, "image/png")
    att = Attachment(
        id=str(uuid.uuid4()), workspace_id=ws_id,
        source_type=AttachmentSourceType.ASSET, source_id=ws_id,
        kind=kind, filename="screenshot.png", mime_type="image/png",
        size_bytes=saved.size_bytes, storage_key=saved.storage_key,
        uploaded_at=datetime.now(timezone.utc), is_active=True,
    )
    db.add(att)
    db.commit()
    att_id = att.id
    db.close()
    return att_id


class FakeLLM:
    """Mock LLMClient that returns the canned JSON for the next call."""
    def __init__(self, payload: dict[str, Any] | str):
        self.payload = payload
        self.calls: list[dict[str, Any]] = []

    def call(self, *, system, user_text, image_bytes=None, image_mime=None,
             image_parts=None, model="claude-sonnet-4-5", max_tokens=4096):
        self.calls.append({
            "system": system, "user_text": user_text,
            "image_mime": image_mime, "model": model,
        })
        text = self.payload if isinstance(self.payload, str) else json.dumps(self.payload)
        return LLMCall(text=text, input_tokens=120, output_tokens=80, model=model)


@pytest.fixture(autouse=True)
def reset_llm():
    yield
    set_llm_client(None)


# ── tests ────────────────────────────────────────────────────────────────────

def test_create_and_run_screenshot_price_returns_extracted(db, seed):
    fake = FakeLLM({
        "ticker": "PETR4",
        "price": 38.45,
        "currency": "BRL",
        "as_of_timestamp": "2026-04-30T17:55:00",
        "source_app": "B3 app",
        "confidence": 0.95,
    })
    set_llm_client(fake)
    att_id = _make_attachment(seed["ws_id"])

    job = extraction_service.create_and_run(
        db,
        workspace_id=seed["ws_id"],
        attachment_id=att_id,
        source_hint=ExtractionSourceHint.SCREENSHOT_PRICE,
        pendency_id=seed["pen_id"],
        user_id=seed["user_id"],
        user_email="ex@test.com",
    )

    assert job.status == ExtractionStatus.EXTRACTED
    assert job.extracted_json["price"] == 38.45
    assert job.input_tokens == 120
    assert job.output_tokens == 80
    assert job.cost_usd is not None and job.cost_usd > 0
    assert job.confidence == Decimal("0.95")
    assert len(fake.calls) == 1


def test_confirm_screenshot_price_updates_asset_and_resolves_pendency(db, seed):
    fake = FakeLLM({
        "ticker": "PETR4", "price": 41.00, "currency": "BRL",
        "as_of_timestamp": "2026-04-30T17:55:00",
        "source_app": "broker", "confidence": 0.93,
    })
    set_llm_client(fake)
    att_id = _make_attachment(seed["ws_id"])

    job = extraction_service.create_and_run(
        db,
        workspace_id=seed["ws_id"],
        attachment_id=att_id,
        source_hint=ExtractionSourceHint.SCREENSHOT_PRICE,
        pendency_id=seed["pen_id"],
        user_id=seed["user_id"],
        user_email="ex@test.com",
    )
    db.commit()

    result = extraction_service.confirm_extraction(
        db,
        job_id=job.id,
        user_id=seed["user_id"],
        user_email="ex@test.com",
    )
    db.commit()

    assert result.applied_count == 1
    petr = db.get(Asset, seed["petr_id"])
    assert petr.current_price == Decimal("41.00")
    pen = db.get(SnapshotPendency, seed["pen_id"])
    assert pen.resolved_at is not None
    job_after = db.get(ExtractionJob, job.id)
    assert job_after.status == ExtractionStatus.CONFIRMED


def test_confirm_broker_position_updates_multiple_and_skips_unknown(db, seed):
    fake = FakeLLM({
        "as_of_date": "2026-04-30",
        "broker_name": "XP",
        "positions": [
            {"ticker_raw": "PETR4", "ticker_normalized": "PETR4",
             "quantity": 100, "unit_price": 42.10, "currency": "BRL",
             "market_value": 4210.0, "confidence": 0.98, "notes": None},
            {"ticker_raw": "ITUB4", "ticker_normalized": "ITUB4",
             "quantity": 200, "unit_price": 36.50, "currency": "BRL",
             "market_value": 7300.0, "confidence": 0.97, "notes": None},
            {"ticker_raw": "ZZZZ9", "ticker_normalized": "ZZZZ9",
             "quantity": 1, "unit_price": 1.0, "currency": "BRL",
             "market_value": 1.0, "confidence": 0.6, "notes": "desconhecido"},
        ],
        "summary_total_brl": 11511.0,
        "summary_total_usd": None,
    })
    set_llm_client(fake)
    att_id = _make_attachment(seed["ws_id"])

    job = extraction_service.create_and_run(
        db,
        workspace_id=seed["ws_id"],
        attachment_id=att_id,
        source_hint=ExtractionSourceHint.BROKER_POSITION,
        user_id=seed["user_id"], user_email="ex@test.com",
    )
    db.commit()

    result = extraction_service.confirm_extraction(
        db, job_id=job.id, user_id=seed["user_id"], user_email="ex@test.com",
    )
    db.commit()

    assert result.applied_count == 2
    assert result.skipped_count == 1
    assert any("ZZZZ9" in e for e in result.errors)
    petr = db.get(Asset, seed["petr_id"])
    itub = db.get(Asset, seed["itub_id"])
    assert petr.current_price == Decimal("42.10")
    assert itub.current_price == Decimal("36.50")


def test_reject_extraction_marks_rejected_without_applying(db, seed):
    fake = FakeLLM({
        "ticker": "PETR4", "price": 999.99, "currency": "BRL",
        "as_of_timestamp": None, "source_app": None, "confidence": 0.2,
    })
    set_llm_client(fake)
    att_id = _make_attachment(seed["ws_id"])

    job = extraction_service.create_and_run(
        db,
        workspace_id=seed["ws_id"],
        attachment_id=att_id,
        source_hint=ExtractionSourceHint.SCREENSHOT_PRICE,
        user_id=seed["user_id"], user_email="ex@test.com",
    )
    db.commit()

    before_price = db.get(Asset, seed["petr_id"]).current_price

    rejected = extraction_service.reject_extraction(
        db, job_id=job.id, user_id=seed["user_id"], user_email="ex@test.com",
        reason="confidence muito baixa",
    )
    db.commit()

    assert rejected.status == ExtractionStatus.REJECTED
    assert rejected.error_message == "confidence muito baixa"
    after_price = db.get(Asset, seed["petr_id"]).current_price
    assert after_price == before_price  # apply NOT called


def test_run_extraction_marks_failed_on_invalid_json(db, seed):
    fake = FakeLLM("definitely not json at all")
    set_llm_client(fake)
    att_id = _make_attachment(seed["ws_id"])

    job = extraction_service.create_and_run(
        db,
        workspace_id=seed["ws_id"],
        attachment_id=att_id,
        source_hint=ExtractionSourceHint.SCREENSHOT_PRICE,
        user_id=seed["user_id"], user_email="ex@test.com",
    )

    assert job.status == ExtractionStatus.FAILED
    assert job.error_message is not None
    assert "Parse" in job.error_message or "no JSON" in job.error_message


def test_parse_json_block_handles_fenced_json():
    from numis_geek.integrations.llm import parse_json_block
    # The LLM often wraps JSON in ```json fences with a prose preamble.
    raw = 'Sure, here is the JSON:\n```json\n{"a": 1, "nested": {"b": 2}}\n```'
    assert parse_json_block(raw) == {"a": 1, "nested": {"b": 2}}


def test_parse_json_block_ignores_trailing_prose_after_fence():
    """Real Avenue regression — LLM emitted a fenced JSON followed by
    a markdown note. Old parser failed with 'Extra data at char N'.
    Brace-aware tokenizer must stop at the first balanced `{...}`."""
    from numis_geek.integrations.llm import parse_json_block

    raw = (
        '```json\n'
        '{"positions": [], "summary_total_usd": 727.33}\n'
        '```\n\n'
        '**Observação importante**: este extrato contém apenas transações.'
    )
    assert parse_json_block(raw) == {
        "positions": [], "summary_total_usd": 727.33,
    }


def test_parse_json_block_ignores_braces_inside_strings():
    """Brace counting must respect string literals — `{` inside a value
    should not increment depth."""
    from numis_geek.integrations.llm import parse_json_block

    raw = '{"notes": "value with {braces} inside", "k": 1}'
    assert parse_json_block(raw) == {
        "notes": "value with {braces} inside", "k": 1,
    }


def test_parse_json_block_handles_escaped_quotes():
    """Escaped quotes must not flip the in_string state prematurely."""
    from numis_geek.integrations.llm import parse_json_block

    raw = r'{"q": "he said \"hi\" with {brace}", "k": 2}'
    assert parse_json_block(raw) == {
        "q": 'he said "hi" with {brace}', "k": 2,
    }


def test_parse_json_block_no_json_object_raises():
    from numis_geek.integrations.llm import parse_json_block

    with pytest.raises(ValueError, match="no JSON object"):
        parse_json_block("just prose, no JSON here")


def test_split_image_returns_original_when_within_bounds():
    pytest.importorskip("PIL")
    from io import BytesIO
    from PIL import Image
    from numis_geek.services.extraction import _split_image_for_anthropic
    buf = BytesIO()
    Image.new("RGB", (1200, 1500), color="white").save(buf, format="PNG")
    parts = _split_image_for_anthropic(buf.getvalue(), "image/png")
    assert len(parts) == 1
    # In-bounds → pass through unchanged (same bytes object).
    assert parts[0][0] == buf.getvalue()
    assert parts[0][1] == "image/png"


def test_xlsx_payload_is_converted_to_csv_text():
    """Spec 19 hotfix — XLSX uploads precisam virar texto CSV-like antes
    de ir pro LLM (Claude não decoda zip XLSX nativamente)."""
    pytest.importorskip("openpyxl")
    from io import BytesIO
    from openpyxl import Workbook
    from numis_geek.services.extraction import _xlsx_to_csv_text

    wb = Workbook()
    ws = wb.active
    ws.title = "Posicao"
    ws.append(["Ticker", "Qtde", "Preço"])
    ws.append(["PETR4", 100, 38.50])
    ws.append(["ITUB4", 200, 32.10])
    buf = BytesIO()
    wb.save(buf)

    text = _xlsx_to_csv_text(buf.getvalue())
    assert text is not None
    assert "Sheet: Posicao" in text
    assert "PETR4,100,38.5" in text
    assert "ITUB4,200,32.1" in text


def test_split_image_tiles_when_taller_than_8000px():
    pytest.importorskip("PIL")
    from io import BytesIO
    from PIL import Image
    from numis_geek.services.extraction import _split_image_for_anthropic
    # 1290×10000 mimics a stitched broker screenshot.
    buf = BytesIO()
    Image.new("RGB", (1290, 10000), color="white").save(buf, format="PNG")
    parts = _split_image_for_anthropic(buf.getvalue(), "image/png")
    # Needs 2 vertical tiles (8000 + 2000).
    assert len(parts) == 2
    # Each tile decodes back within the 8000 hard limit.
    for blob, mime in parts:
        assert mime == "image/jpeg"
        img = Image.open(BytesIO(blob))
        assert max(img.size) <= 8000
