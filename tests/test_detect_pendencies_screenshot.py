"""Spec 35 — testes de detect_pendencies pra ativos capturados via
snapshot manual/screenshot vs. via fonte automatizada (BRAPI/FINNHUB).

NOTA: o pedido original mencionava `SnapshotSource.SCREENSHOT`, mas o enum
`SnapshotSource` só tem MANUAL/NOTION_BACKFILL/AUTOMATED. A discriminação
real de pendency happens em `Asset.price_source`, não no SnapshotSource;
esses testes cobrem essa discriminação usando snapshots MANUAL (que é o
container natural pro fluxo "usuário subiu screenshot").
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from numis_geek.db.base import Base
import numis_geek.models  # noqa: F401
from numis_geek.models.account import Account, AccountType, Currency
from numis_geek.models.asset import Asset, AssetClass, PriceSource
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.portfolio_snapshot import (
    PendencyAction,
    PendencyReason,
    PortfolioSnapshot,
    SnapshotSource,
    SnapshotStatus,
)
from numis_geek.services.snapshot import detect_pendencies
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


@pytest.fixture
def db():
    s = TestSession()
    yield s
    s.rollback()
    s.close()


# ── Builders ────────────────────────────────────────────────────────────────


def _mk_ws(db, name: str) -> str:
    ws = WorkspaceService(db).create(name)
    db.flush()
    return ws.id


def _mk_fi(db, short_name: str) -> FinancialInstitution:
    now = datetime.now(timezone.utc)
    fi = FinancialInstitution(
        id=str(uuid.uuid4()),
        long_name=short_name,
        short_name=short_name,
        logo_slug=short_name.lower(),
        country="US" if short_name.lower() == "avenue" else "BR",
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(fi)
    db.flush()
    return fi


def _mk_account(db, ws_id: str, fi_id: str, name: str = "Inv") -> Account:
    now = datetime.now(timezone.utc)
    acc = Account(
        id=str(uuid.uuid4()),
        workspace_id=ws_id,
        financial_institution_id=fi_id,
        name=name,
        account_type=AccountType.investment,
        currency=Currency.BRL,
        opening_balance=Decimal("0"),
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(acc)
    db.flush()
    return acc


def _mk_asset(
    db, ws_id: str, acc_id: str, *,
    price_source: PriceSource | None,
    ticker: str | None = "TICK",
    price_updated_at: datetime | None = None,
    asset_class=AssetClass.STOCK,
    currency=Currency.BRL,
) -> Asset:
    now = datetime.now(timezone.utc)
    a = Asset(
        id=str(uuid.uuid4()),
        workspace_id=ws_id,
        account_id=acc_id,
        asset_class=asset_class,
        country="BR",
        name=ticker or "Ativo Genérico",
        ticker=ticker,
        currency=currency,
        current_price=Decimal("100"),
        price_updated_at=price_updated_at,
        price_source=price_source,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(a)
    db.flush()
    return a


def _mk_snapshot(
    db, ws_id: str, source: SnapshotSource = SnapshotSource.MANUAL,
) -> PortfolioSnapshot:
    """Cria um snapshot MANUAL (proxy pro fluxo 'screenshot')."""
    now = datetime.now(timezone.utc)
    snap = PortfolioSnapshot(
        id=str(uuid.uuid4()),
        workspace_id=ws_id,
        period_end_date=date.today(),
        fx_rate_usd_brl=Decimal("5.00"),
        total_value_brl=Decimal("0"),
        total_value_usd=Decimal("0"),
        total_invested_brl=Decimal("0"),
        total_received_brl=Decimal("0"),
        source=source,
        status=SnapshotStatus.IN_REVIEW,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(snap)
    db.flush()
    return snap


# ── Manual price source (screenshot / upload fluxo) ─────────────────────────


def test_manual_source_generic_asset_emits_manual_source_pendency(db):
    """MANUAL sem heurística Avenue → MANUAL_SOURCE + EDIT_PRICE."""
    ws = _mk_ws(db, "manual-generic-ws")
    fi = _mk_fi(db, "XP")
    acc = _mk_account(db, ws, fi.id)
    asset = _mk_asset(db, ws, acc.id, price_source=PriceSource.MANUAL, ticker="XPML11")

    det = detect_pendencies(db, asset, period_end=date.today())
    assert det is not None
    reason, action, detail = det
    assert reason == PendencyReason.MANUAL_SOURCE
    assert action == PendencyAction.EDIT_PRICE
    assert "manual" in detail.lower()


def test_manual_source_avenue_generic_emits_upload_required(db):
    """MANUAL + ticker=NULL + FI 'Avenue' → UPLOAD_REQUIRED + UPLOAD_FILE.
    Análogo ao "screenshot obrigatório" — o único caminho pra resolver a
    pendency é subir o extrato/screenshot."""
    ws = _mk_ws(db, "avenue-ws")
    fi = _mk_fi(db, "Avenue")
    acc = _mk_account(db, ws, fi.id)
    asset = _mk_asset(
        db, ws, acc.id, price_source=PriceSource.MANUAL, ticker=None,
    )

    det = detect_pendencies(db, asset, period_end=date.today())
    assert det is not None
    reason, action, _ = det
    assert reason == PendencyReason.UPLOAD_REQUIRED
    assert action == PendencyAction.UPLOAD_FILE


def test_null_price_source_no_pendency(db):
    """Ativo sem price_source (ex: cash) → nenhuma pendency."""
    ws = _mk_ws(db, "null-src-ws")
    fi = _mk_fi(db, "XP")
    acc = _mk_account(db, ws, fi.id)
    asset = _mk_asset(db, ws, acc.id, price_source=None, ticker="CASHBRL")

    assert detect_pendencies(db, asset, period_end=date.today()) is None


# ── Automated sources — comportamento distinto ──────────────────────────────


def test_brapi_fresh_price_no_pendency(db):
    """BRAPI com preço FRESH (<24h) → sem pendency."""
    ws = _mk_ws(db, "brapi-fresh-ws")
    fi = _mk_fi(db, "XP")
    acc = _mk_account(db, ws, fi.id)
    now = datetime.now(timezone.utc)
    asset = _mk_asset(
        db, ws, acc.id, price_source=PriceSource.BRAPI,
        ticker="PETR4", price_updated_at=now - timedelta(hours=2),
    )
    assert detect_pendencies(db, asset, period_end=date.today(), now=now) is None


def test_finnhub_never_refreshed_emits_api_failed(db):
    """FINNHUB + price_updated_at=NULL → API_FAILED + RETRY_API."""
    ws = _mk_ws(db, "finn-fail-ws")
    fi = _mk_fi(db, "Avenue")
    acc = _mk_account(db, ws, fi.id)
    asset = _mk_asset(
        db, ws, acc.id, price_source=PriceSource.FINNHUB,
        ticker="AAPL", price_updated_at=None,
    )
    det = detect_pendencies(db, asset, period_end=date.today())
    assert det is not None
    reason, action, detail = det
    assert reason == PendencyReason.API_FAILED
    assert action == PendencyAction.RETRY_API
    assert "FINNHUB" in detail


def test_brapi_old_price_emits_stale(db):
    """BRAPI com preço > 7d → STALE_PRICE + RETRY_API."""
    ws = _mk_ws(db, "brapi-stale-ws")
    fi = _mk_fi(db, "XP")
    acc = _mk_account(db, ws, fi.id)
    now = datetime.now(timezone.utc)
    asset = _mk_asset(
        db, ws, acc.id, price_source=PriceSource.BRAPI,
        ticker="ITUB4", price_updated_at=now - timedelta(days=10),
    )
    det = detect_pendencies(db, asset, period_end=date.today(), now=now)
    assert det is not None
    reason, action, _ = det
    assert reason == PendencyReason.STALE_PRICE
    assert action == PendencyAction.RETRY_API


def test_manual_vs_automated_differ_for_same_snapshot(db):
    """Sanity contrast: um ativo MANUAL sob snapshot MANUAL gera pendency,
    o mesmo snapshot com ativo BRAPI fresh NÃO gera. Prova que a decisão
    é por asset.price_source (não pelo SnapshotSource)."""
    ws = _mk_ws(db, "contrast-ws")
    fi = _mk_fi(db, "XP")
    acc = _mk_account(db, ws, fi.id)
    now = datetime.now(timezone.utc)

    manual_asset = _mk_asset(
        db, ws, acc.id, price_source=PriceSource.MANUAL, ticker="IMOVEL",
    )
    automated_asset = _mk_asset(
        db, ws, acc.id, price_source=PriceSource.BRAPI, ticker="PETR4",
        price_updated_at=now - timedelta(hours=1),
    )

    snap = _mk_snapshot(db, ws, source=SnapshotSource.MANUAL)
    # A pendency shape retornada seria persistida com esses IDs:
    det_manual = detect_pendencies(db, manual_asset, period_end=snap.period_end_date, now=now)
    det_auto = detect_pendencies(db, automated_asset, period_end=snap.period_end_date, now=now)

    # Manual gera; automated fresh não.
    assert det_manual is not None
    assert det_auto is None

    # Cheque shape: os campos que o caller vai persistir num
    # SnapshotPendency (kind=reason, asset_id, snapshot_id).
    reason, action, detail = det_manual
    assert reason in {PendencyReason.MANUAL_SOURCE, PendencyReason.UPLOAD_REQUIRED}
    assert isinstance(action, PendencyAction)
    assert isinstance(detail, str) and detail  # non-empty
    # Caller monta o payload persistido com esses IDs:
    payload_ok = {
        "reason": reason.value,
        "asset_id": manual_asset.id,
        "snapshot_id": snap.id,
    }
    assert payload_ok["asset_id"] == manual_asset.id
    assert payload_ok["snapshot_id"] == snap.id
