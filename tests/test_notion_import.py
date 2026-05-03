"""Tests for the Notion → Asset importer (scripts/import_notion_assets.py)."""
from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import bcrypt
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from numis_geek.db.base import Base
import numis_geek.models  # noqa: F401 — registers all models on Base.metadata
from numis_geek.models.asset import Asset, AssetClass
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.user import User, UserRole
from numis_geek.models.workspace import Workspace

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import import_notion_assets as importer  # noqa: E402

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "notion_export_sample.json"
WORKSPACE_NAME = "Família Ambrosio"

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


@pytest.fixture(scope="module")
def seed():
    """Seed the workspace, sysadmin user, and the IFs needed by the fixture."""
    db = TestSession()
    now = datetime.now(timezone.utc)

    ws_id = str(uuid.uuid4())
    sysadmin_id = str(uuid.uuid4())

    ws = Workspace(id=ws_id, name=WORKSPACE_NAME)
    db.add(ws)

    sysadmin = User(
        id=sysadmin_id,
        workspace_id=None,
        email=importer.SYSADMIN_EMAIL,
        name="System Admin",
        password_hash=bcrypt.hashpw(b"x", bcrypt.gensalt()).decode(),
        role=UserRole.sysadmin,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(sysadmin)

    fi_specs = [
        ("XP Investimentos", "XP", "xp"),
        ("Avenue Securities", "Avenue", "avenue"),
        ("BTG Pactual", "BTG", "btg"),
        ("Coinbase", "Coinbase", "coinbase"),
        ("Bradesco", "Bradesco", "bradesco"),
        ("Itaú Unibanco", "Itaú", "itau"),
        ("Particular (sem instituição)", "Particular", "particular"),
    ]
    fi_ids: dict[str, str] = {}
    for long_name, short_name, slug in fi_specs:
        fi_id = str(uuid.uuid4())
        fi = FinancialInstitution(
            id=fi_id,
            long_name=long_name,
            short_name=short_name,
            logo_slug=slug,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        db.add(fi)
        fi_ids[short_name] = fi_id

    db.commit()
    db.close()
    return {"ws_id": ws_id, "sysadmin_id": sysadmin_id, "fi_ids": fi_ids}


def _patched_session_local(monkeypatch):
    """Make the importer use our in-memory test session."""
    monkeypatch.setattr(importer, "SessionLocal", TestSession)


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_dry_run_creates_nothing(seed, monkeypatch):
    _patched_session_local(monkeypatch)
    summary = importer.import_from_json(FIXTURE_PATH, apply=False, workspace_name=WORKSPACE_NAME)
    assert summary.total == 15
    assert summary.would_create == 15
    assert summary.would_update == 0

    db = TestSession()
    try:
        assert db.query(Asset).filter(Asset.workspace_id == seed["ws_id"]).count() == 0
    finally:
        db.close()


def test_apply_inserts_all_rows(seed, monkeypatch):
    _patched_session_local(monkeypatch)
    summary = importer.import_from_json(FIXTURE_PATH, apply=True, workspace_name=WORKSPACE_NAME)
    assert summary.total == 15
    assert summary.would_create == 15
    assert summary.would_update == 0
    # row-15 references "Banco Inexistente" → must fall back to Particular
    assert len(summary.fallback_to_particular) == 1
    assert summary.fallback_to_particular[0][1] == "Banco Inexistente"

    db = TestSession()
    try:
        rows = db.query(Asset).filter(Asset.workspace_id == seed["ws_id"]).all()
        assert len(rows) == 15

        # By class
        classes = {a.asset_class for a in rows}
        assert AssetClass.PRIVATE_PENSION in classes
        assert AssetClass.FGTS in classes
        assert AssetClass.CASH in classes
        assert AssetClass.STOCK_BR in classes
        assert AssetClass.REAL_ESTATE in classes

        # All rows have created_by/updated_by = sysadmin
        for r in rows:
            assert r.created_by == seed["sysadmin_id"]
            assert r.updated_by == seed["sysadmin_id"]
    finally:
        db.close()


def test_fi_mapping_matches_short_name(seed, monkeypatch):
    _patched_session_local(monkeypatch)
    db = TestSession()
    try:
        petr = db.query(Asset).filter(
            Asset.workspace_id == seed["ws_id"],
            Asset.ticker == "PETR4",
        ).first()
        assert petr is not None
        assert petr.financial_institution_id == seed["fi_ids"]["XP"]

        cash = db.query(Asset).filter(
            Asset.workspace_id == seed["ws_id"],
            Asset.asset_class == AssetClass.CASH,
            Asset.name == "Float Avenue",
        ).first()
        assert cash is not None
        assert cash.financial_institution_id == seed["fi_ids"]["Avenue"]
    finally:
        db.close()


def test_fallback_to_particular_for_unknown_if(seed, monkeypatch):
    _patched_session_local(monkeypatch)
    db = TestSession()
    try:
        wege = db.query(Asset).filter(
            Asset.workspace_id == seed["ws_id"],
            Asset.ticker == "WEGE3",
        ).first()
        assert wege is not None
        # Unknown "Banco Inexistente" must have fallen back to Particular
        assert wege.financial_institution_id == seed["fi_ids"]["Particular"]
    finally:
        db.close()


def test_currency_set_correctly(seed, monkeypatch):
    _patched_session_local(monkeypatch)
    db = TestSession()
    try:
        aapl = db.query(Asset).filter(
            Asset.workspace_id == seed["ws_id"],
            Asset.ticker == "AAPL",
        ).first()
        assert aapl is not None
        assert aapl.currency.value == "USD"

        petr = db.query(Asset).filter(
            Asset.workspace_id == seed["ws_id"],
            Asset.ticker == "PETR4",
        ).first()
        assert petr.currency.value == "BRL"
    finally:
        db.close()


def test_zeroed_position_imported_as_inactive(seed, monkeypatch):
    _patched_session_local(monkeypatch)
    db = TestSession()
    try:
        btc = db.query(Asset).filter(
            Asset.workspace_id == seed["ws_id"],
            Asset.ticker == "BTC",
        ).first()
        assert btc is not None
        assert btc.is_active is False
    finally:
        db.close()


def test_tickerless_rows_have_null_ticker(seed, monkeypatch):
    _patched_session_local(monkeypatch)
    db = TestSession()
    try:
        # FGTS / PRIVATE_PENSION / CASH / REAL_ESTATE / VEHICLE / FIXED_INCOME
        # are tickerless in the fixture; verify ticker is NULL.
        for name in (
            "FGTS Itaú",
            "Bradesco Vida e Previdência VGBL",
            "Float Avenue",
            "Apto Pinheiros",
            "Toyota Corolla 2022",
            "CDB BTG 110% CDI 2028",
            "Fundo XP Global",
        ):
            row = db.query(Asset).filter(
                Asset.workspace_id == seed["ws_id"],
                Asset.name == name,
            ).first()
            assert row is not None, f"missing {name}"
            assert row.ticker is None, f"{name} should have null ticker"
    finally:
        db.close()


def test_idempotent_second_run_no_duplicates(seed, monkeypatch):
    _patched_session_local(monkeypatch)
    summary = importer.import_from_json(FIXTURE_PATH, apply=True, workspace_name=WORKSPACE_NAME)
    assert summary.would_create == 0
    assert summary.would_update == 15

    db = TestSession()
    try:
        # Still 15 — no duplicates
        rows = db.query(Asset).filter(Asset.workspace_id == seed["ws_id"]).all()
        assert len(rows) == 15
    finally:
        db.close()


def test_idempotent_run_preserves_inactive(seed, monkeypatch):
    _patched_session_local(monkeypatch)
    importer.import_from_json(FIXTURE_PATH, apply=True, workspace_name=WORKSPACE_NAME)
    db = TestSession()
    try:
        btc = db.query(Asset).filter(
            Asset.workspace_id == seed["ws_id"],
            Asset.ticker == "BTC",
        ).first()
        assert btc is not None
        assert btc.is_active is False
    finally:
        db.close()


def test_notion_url_recorded_in_notes(seed, monkeypatch):
    _patched_session_local(monkeypatch)
    db = TestSession()
    try:
        petr = db.query(Asset).filter(
            Asset.workspace_id == seed["ws_id"],
            Asset.ticker == "PETR4",
        ).first()
        assert petr is not None
        assert petr.notes is not None
        assert "https://www.notion.so/row1" in petr.notes
    finally:
        db.close()
