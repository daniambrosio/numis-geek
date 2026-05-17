"""Tests for the Notion → Lançamento importer (scripts/import_notion_lancamentos.py)."""
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
import numis_geek.models  # noqa: F401 — registers models on Base.metadata
from numis_geek.models.account import Currency
from numis_geek.models.asset import Asset, AssetClass
from numis_geek.models.external import ExternalSource
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.asset_movement import AssetMovement, AssetMovementType
from numis_geek.models.user import User, UserRole
from numis_geek.models.workspace import Workspace

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import import_notion_lancamentos as importer  # noqa: E402

FIXTURE_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "notion_lancamento_export_sample.json"
)
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
    """Create the workspace, sysadmin, FI, and three Notion-sourced assets."""
    db = TestSession()
    now = datetime.now(timezone.utc)

    ws_id = str(uuid.uuid4())
    sysadmin_id = str(uuid.uuid4())
    fi_id = str(uuid.uuid4())

    db.add(Workspace(id=ws_id, name=WORKSPACE_NAME))
    db.add(User(
        id=sysadmin_id,
        workspace_id=None,
        email=importer.SYSADMIN_EMAIL,
        name="System Admin",
        password_hash=bcrypt.hashpw(b"x", bcrypt.gensalt()).decode(),
        role=UserRole.sysadmin,
        is_active=True,
        created_at=now,
        updated_at=now,
    ))
    db.add(FinancialInstitution(
        id=fi_id,
        long_name="XP Investimentos",
        short_name="XP",
        logo_slug="xp",
        is_active=True,
        created_at=now,
        updated_at=now,
    ))

    # Three Notion-sourced assets, matching the fixture's asset_external_id values.
    asset_petr = Asset(
        id=str(uuid.uuid4()),
        workspace_id=ws_id,
        financial_institution_id=fi_id,
        asset_class=AssetClass.STOCK_BR,
        name="Petrobras PN",
        ticker="PETR4",
        currency=Currency.BRL,
        is_active=True,
        created_at=now,
        updated_at=now,
        external_id="https://www.notion.so/asset-petr4",
        external_source=ExternalSource.NOTION,
    )
    asset_fund = Asset(
        id=str(uuid.uuid4()),
        workspace_id=ws_id,
        financial_institution_id=fi_id,
        asset_class=AssetClass.FUND,
        name="Fundo Multi XP",
        ticker=None,
        currency=Currency.BRL,
        is_active=True,
        created_at=now,
        updated_at=now,
        external_id="https://www.notion.so/asset-fund1",
        external_source=ExternalSource.NOTION,
    )
    asset_cdb = Asset(
        id=str(uuid.uuid4()),
        workspace_id=ws_id,
        financial_institution_id=fi_id,
        asset_class=AssetClass.FIXED_INCOME,
        name="CDB BTG 110% CDI 2028",
        ticker=None,
        currency=Currency.BRL,
        is_active=True,
        created_at=now,
        updated_at=now,
        external_id="https://www.notion.so/asset-cdb",
        external_source=ExternalSource.NOTION,
    )
    db.add_all([asset_petr, asset_fund, asset_cdb])
    db.commit()

    out = {
        "ws_id": ws_id,
        "sysadmin_id": sysadmin_id,
        "fi_id": fi_id,
        "asset_petr": asset_petr.id,
        "asset_fund": asset_fund.id,
        "asset_cdb": asset_cdb.id,
    }
    db.close()
    return out


def _patched_session_local(monkeypatch):
    monkeypatch.setattr(importer, "SessionLocal", TestSession)


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_dry_run_creates_nothing(seed, monkeypatch):
    _patched_session_local(monkeypatch)
    summary = importer.import_from_json(
        FIXTURE_PATH, apply=False, workspace_name=WORKSPACE_NAME,
    )
    # 7 valid + 8 invalid (1 orphan + 7 hard-error rows) = 15 total
    assert summary.total == 15
    # Valid by_type counts: COMPRA(2: petr + cdb), VENDA(1), BONIFICACAO(1),
    # SUBSCRICAO(1), COME_COTAS(1), RESGATE_TOTAL(1) = 7
    assert sum(summary.by_type.values()) == 7
    db = TestSession()
    try:
        assert db.query(AssetMovement).filter(
            AssetMovement.workspace_id == seed["ws_id"]
        ).count() == 0
    finally:
        db.close()


def test_summary_groups_errors_by_code(seed, monkeypatch):
    _patched_session_local(monkeypatch)
    summary = importer.import_from_json(
        FIXTURE_PATH, apply=False, workspace_name=WORKSPACE_NAME,
    )
    grouped = summary.grouped_errors()
    # Each hard-error code appears at least once in the fixture.
    assert grouped.get("ORPHAN_ASSET", 0) >= 1
    assert grouped.get("MISSING_DATE", 0) >= 1
    assert grouped.get("FUTURE_DATE", 0) >= 1
    assert grouped.get("MISSING_ASSET", 0) >= 1
    assert grouped.get("UNKNOWN_TYPE", 0) >= 1
    assert grouped.get("COMPRA_VENDA_MISSING_VALUE", 0) >= 1
    assert grouped.get("COMECOTAS_MISSING_TAX", 0) >= 1
    assert grouped.get("BONIFICACAO_MISSING_QTY", 0) >= 1
    # Orchestrator-supplied error is preserved.
    assert grouped.get("DUPLICATE_NOTION_ID", 0) >= 1


def test_summary_warnings_passed_through(seed, monkeypatch):
    _patched_session_local(monkeypatch)
    summary = importer.import_from_json(
        FIXTURE_PATH, apply=False, workspace_name=WORKSPACE_NAME,
    )
    grouped = summary.grouped_warnings()
    # All seven orchestrator-supplied warnings should round-trip.
    for code in (
        "UNIT_PRICE_ZERO",
        "BONIFICACAO_HAS_PRICE",
        "FX_RATE_MISSING_FOR_USD",
        "FX_RATE_PRESENT_FOR_BRL",
        "BOTH_QTY_AND_AR_VALOR",
        "LARGE_FEE_RATIO",
        "DATE_BEFORE_ASSET_CREATED",
    ):
        assert grouped.get(code, 0) >= 1, f"missing warning {code}"


def test_apply_refuses_when_errors_without_force(seed, monkeypatch):
    """--apply with hard errors must roll back unless --force."""
    _patched_session_local(monkeypatch)
    summary = importer.import_from_json(
        FIXTURE_PATH, apply=True, workspace_name=WORKSPACE_NAME, force=False,
    )
    assert summary.errors  # there are errors in the fixture
    db = TestSession()
    try:
        # Nothing was committed.
        assert db.query(AssetMovement).filter(
            AssetMovement.workspace_id == seed["ws_id"]
        ).count() == 0
    finally:
        db.close()


def test_apply_with_force_inserts_valid_rows(seed, monkeypatch):
    _patched_session_local(monkeypatch)
    summary = importer.import_from_json(
        FIXTURE_PATH, apply=True, workspace_name=WORKSPACE_NAME, force=True,
    )
    # 7 valid rows succeed, 8 fail (orphan + 7 hard-error codes).
    assert summary.would_create == 7
    assert summary.would_update == 0
    db = TestSession()
    try:
        rows = db.query(AssetMovement).filter(
            AssetMovement.workspace_id == seed["ws_id"]
        ).all()
        assert len(rows) == 7
        # All carry NOTION provenance.
        for r in rows:
            assert r.external_source == ExternalSource.NOTION
            assert r.external_id and r.external_id.startswith("https://www.notion.so/")
            assert r.created_by == seed["sysadmin_id"]
        # nota_negociacao_number preserved on COMPRA / VENDA.
        compra = next(r for r in rows if r.external_id == "https://www.notion.so/lan-1")
        assert compra.nota_negociacao_number == "12345"
    finally:
        db.close()


def test_idempotent_second_run_no_duplicates(seed, monkeypatch):
    _patched_session_local(monkeypatch)
    summary = importer.import_from_json(
        FIXTURE_PATH, apply=True, workspace_name=WORKSPACE_NAME, force=True,
    )
    assert summary.would_create == 0
    assert summary.would_update == 7
    db = TestSession()
    try:
        rows = db.query(AssetMovement).filter(
            AssetMovement.workspace_id == seed["ws_id"]
        ).all()
        assert len(rows) == 7
    finally:
        db.close()


def test_resgate_total_mapped(seed, monkeypatch):
    _patched_session_local(monkeypatch)
    db = TestSession()
    try:
        rt = db.query(AssetMovement).filter(
            AssetMovement.workspace_id == seed["ws_id"],
            AssetMovement.external_id == "https://www.notion.so/lan-6",
        ).first()
        assert rt is not None
        assert rt.type == AssetMovementType.FULL_REDEMPTION
    finally:
        db.close()


def test_non_cotado_compra_persisted_with_gross_only(seed, monkeypatch):
    _patched_session_local(monkeypatch)
    db = TestSession()
    try:
        cdb_compra = db.query(AssetMovement).filter(
            AssetMovement.workspace_id == seed["ws_id"],
            AssetMovement.external_id == "https://www.notion.so/lan-7",
        ).first()
        assert cdb_compra is not None
        assert cdb_compra.quantity is None
        assert cdb_compra.unit_price is None
        assert float(cdb_compra.gross_amount) == 5000.0
    finally:
        db.close()


def test_orphan_asset_row_skipped(seed, monkeypatch):
    _patched_session_local(monkeypatch)
    db = TestSession()
    try:
        orphan = db.query(AssetMovement).filter(
            AssetMovement.workspace_id == seed["ws_id"],
            AssetMovement.external_id == "https://www.notion.so/lan-orphan",
        ).first()
        assert orphan is None
    finally:
        db.close()


def test_exit_code_2_when_unknown_type(seed, monkeypatch):
    """Exit code 2 is returned when the snapshot contains UNKNOWN_TYPE — it
    takes precedence over ORPHAN_ASSET (3) and generic hard errors (4)."""
    _patched_session_local(monkeypatch)
    rc = importer.main([
        "--from-json", str(FIXTURE_PATH),
        "--workspace", WORKSPACE_NAME,
        "--dry-run",
    ])
    assert rc == 2


def test_unknown_type_returns_exit_2_when_only_error(monkeypatch, seed):
    """A snapshot whose ONLY hard error is UNKNOWN_TYPE returns exit code 2."""
    _patched_session_local(monkeypatch)
    # Build a tiny snapshot with just an unknown-type row (and a valid asset URL).
    import json
    import tempfile

    payload = {
        "lancamentos": [
            {
                "notion_id": "https://www.notion.so/lan-x",
                "asset_external_id": "https://www.notion.so/asset-petr4",
                "type": "Tipo Desconhecido",
                "event_date": "2024-03-15",
                "quantity": 1,
                "unit_price": 1,
            },
        ],
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(payload, f)
        path = f.name
    rc = importer.main([
        "--from-json", path,
        "--workspace", WORKSPACE_NAME,
        "--dry-run",
    ])
    assert rc == 2


def test_exit_code_3_when_orphan_only(monkeypatch, seed):
    """A snapshot whose ONLY hard error is ORPHAN_ASSET returns 3."""
    _patched_session_local(monkeypatch)
    import json
    import tempfile

    payload = {
        "lancamentos": [
            {
                "notion_id": "https://www.notion.so/lan-orph-only",
                "asset_external_id": "https://www.notion.so/asset-NOPE",
                "type": "Compra",
                "event_date": "2024-03-15",
                "quantity": 1,
                "unit_price": 1,
            },
        ],
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(payload, f)
        path = f.name
    rc = importer.main([
        "--from-json", path,
        "--workspace", WORKSPACE_NAME,
        "--dry-run",
    ])
    assert rc == 3


def test_local_negative_running_qty_warning(monkeypatch, seed):
    """If the snapshot's chronological order yields negative qty, warn."""
    _patched_session_local(monkeypatch)
    import json
    import tempfile

    payload = {
        "lancamentos": [
            {
                "notion_id": "https://www.notion.so/lan-vsell",
                "asset_external_id": "https://www.notion.so/asset-petr4",
                "type": "Venda",
                "event_date": "2024-03-15",
                "quantity": 100,
                "unit_price": 30,
            },
        ],
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(payload, f)
        path = f.name

    summary = importer.import_from_json(
        path, apply=False, workspace_name=WORKSPACE_NAME,
    )
    grouped = summary.grouped_warnings()
    assert grouped.get("NEGATIVE_RUNNING_QTY", 0) >= 1
