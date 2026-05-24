"""Tests for spec 12 price update service."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from numis_geek.db.base import Base
import numis_geek.models  # noqa: F401
from numis_geek.integrations.brapi import BrapiError, BrapiQuote
from numis_geek.integrations.finnhub import FinnhubError, FinnhubQuote
from numis_geek.models.account import Account, AccountType, Currency
from numis_geek.models.asset import Asset, AssetClass, PriceSource
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.integration_credential import (
    CredentialTestResult,
    IntegrationCredential,
    IntegrationProvider,
)
from numis_geek.models.workspace import Workspace
from numis_geek.integrations.coinbase import CoinbaseQuote
from numis_geek.models.audit_log import AuditLog
from numis_geek.services.price_update import (
    refresh_all_automated,
    refresh_by_ids,
    refresh_by_source,
    refresh_bulk,
    refresh_one,
)


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


def _seed_world(db) -> dict:
    now = datetime.now(timezone.utc)
    ws = Workspace(id=str(uuid.uuid4()), name="PR WS")
    fi = FinancialInstitution(
        id=str(uuid.uuid4()),
        long_name="XP", short_name="XP", logo_slug="xp",
        is_active=True, created_at=now, updated_at=now,
    )
    acc = Account(
        id=str(uuid.uuid4()), workspace_id=ws.id, financial_institution_id=fi.id,
        name="X", account_type=AccountType.investment, currency=Currency.BRL,
        is_active=True, created_at=now, updated_at=now,
    )
    asset_br = Asset(
        id=str(uuid.uuid4()), workspace_id=ws.id, account_id=acc.id,
        asset_class=AssetClass.STOCK, country="BR", name="Petrobras", ticker="PETR4",
        currency=Currency.BRL, price_source=PriceSource.BRAPI,
        is_active=True, created_at=now, updated_at=now,
    )
    asset_us = Asset(
        id=str(uuid.uuid4()), workspace_id=ws.id, account_id=acc.id,
        asset_class=AssetClass.STOCK, country="US", name="Apple", ticker="AAPL",
        currency=Currency.USD, price_source=PriceSource.FINNHUB,
        is_active=True, created_at=now, updated_at=now,
    )
    db.add_all([ws, fi, acc, asset_br, asset_us])
    db.add_all([
        IntegrationCredential(
            id=str(uuid.uuid4()), workspace_id=None,
            provider=IntegrationProvider.BRAPI, key_name="API_TOKEN",
            secret_value="brapi-token", is_active=True,
            last_test_result=CredentialTestResult.UNTESTED,
            created_at=now, updated_at=now,
        ),
        IntegrationCredential(
            id=str(uuid.uuid4()), workspace_id=None,
            provider=IntegrationProvider.FINNHUB, key_name="API_TOKEN",
            secret_value="finnhub-token", is_active=True,
            last_test_result=CredentialTestResult.UNTESTED,
            created_at=now, updated_at=now,
        ),
    ])
    db.flush()
    return {"ws_id": ws.id, "asset_br": asset_br, "asset_us": asset_us}


def test_refresh_one_br_uses_brapi(db):
    world = _seed_world(db)
    with patch(
        "numis_geek.services.price_update.brapi_quote",
        return_value=BrapiQuote(ticker="PETR4", price=Decimal("38.50")),
    ):
        r = refresh_one(db, world["asset_br"])
    assert r.status == "ok"
    assert r.provider == "brapi"
    assert r.new_price == Decimal("38.50")
    assert world["asset_br"].current_price == Decimal("38.50")
    assert world["asset_br"].price_updated_at is not None


def test_refresh_one_us_uses_finnhub(db):
    world = _seed_world(db)
    with patch(
        "numis_geek.services.price_update.finnhub_quote",
        return_value=FinnhubQuote(symbol="AAPL", price=Decimal("190.25")),
    ):
        r = refresh_one(db, world["asset_us"])
    assert r.status == "ok"
    assert r.provider == "finnhub"
    assert r.new_price == Decimal("190.25")


def test_refresh_one_failed_brapi_returns_failed(db):
    world = _seed_world(db)
    with patch(
        "numis_geek.services.price_update.brapi_quote",
        side_effect=BrapiError("network"),
    ):
        r = refresh_one(db, world["asset_br"])
    assert r.status == "failed"
    assert "network" in (r.error or "")
    assert world["asset_br"].current_price is None


def test_bulk_refresh_returns_summary(db):
    world = _seed_world(db)
    with patch(
        "numis_geek.services.price_update.brapi_quote",
        return_value=BrapiQuote(ticker="PETR4", price=Decimal("38.50")),
    ), patch(
        "numis_geek.services.price_update.finnhub_quote",
        return_value=FinnhubQuote(symbol="AAPL", price=Decimal("190.25")),
    ):
        summary = refresh_bulk(db, workspace_id=world["ws_id"])
    assert summary.total == 2
    assert summary.ok == 2
    assert summary.failed == 0


def test_refresh_one_skips_when_no_credential(db):
    """Asset with country=BR but no BRAPI credential → skipped."""
    now = datetime.now(timezone.utc)
    ws = Workspace(id=str(uuid.uuid4()), name="No-cred WS")
    fi = FinancialInstitution(
        id=str(uuid.uuid4()), long_name="X", short_name="X", logo_slug="x",
        is_active=True, created_at=now, updated_at=now,
    )
    acc = Account(
        id=str(uuid.uuid4()), workspace_id=ws.id, financial_institution_id=fi.id,
        name="X", account_type=AccountType.investment, currency=Currency.BRL,
        is_active=True, created_at=now, updated_at=now,
    )
    asset = Asset(
        id=str(uuid.uuid4()), workspace_id=ws.id, account_id=acc.id,
        asset_class=AssetClass.STOCK, country="BR", name="X", ticker="XYZ4",
        currency=Currency.BRL, price_source=PriceSource.BRAPI,
        is_active=True, created_at=now, updated_at=now,
    )
    db.add_all([ws, fi, acc, asset])
    db.flush()
    r = refresh_one(db, asset)
    assert r.status == "skipped"
    assert "BRAPI credential missing" in (r.error or "")


# ── Spec 23 additions ────────────────────────────────────────────────────────


def _seed_with_crypto(db):
    """Extends _seed_world with a CRYPTO asset routed to Coinbase."""
    world = _seed_world(db)
    now = datetime.now(timezone.utc)
    asset_crypto = Asset(
        id=str(uuid.uuid4()), workspace_id=world["ws_id"], account_id=world["asset_br"].account_id,
        asset_class=AssetClass.CRYPTO, country="US", name="Bitcoin", ticker="BTC",
        currency=Currency.USD, price_source=PriceSource.COINBASE,
        is_active=True, created_at=now, updated_at=now,
    )
    asset_manual = Asset(
        id=str(uuid.uuid4()), workspace_id=world["ws_id"], account_id=world["asset_br"].account_id,
        asset_class=AssetClass.REAL_ESTATE, country="BR", name="Casa", ticker=None,
        currency=Currency.BRL, price_source=PriceSource.MANUAL,
        is_active=True, created_at=now, updated_at=now,
    )
    db.add_all([asset_crypto, asset_manual])
    db.flush()
    world["asset_crypto"] = asset_crypto
    world["asset_manual"] = asset_manual
    return world


def test_refresh_one_coinbase_for_crypto(db):
    world = _seed_with_crypto(db)
    with patch(
        "numis_geek.services.price_update.coinbase_spot",
        return_value=CoinbaseQuote(symbol="BTC", price=Decimal("67000"), currency="USD"),
    ):
        r = refresh_one(db, world["asset_crypto"])
    assert r.status == "ok"
    assert r.provider == "coinbase"
    assert r.source == "COINBASE"
    assert r.new_price == Decimal("67000")


def test_refresh_one_skips_manual(db):
    world = _seed_with_crypto(db)
    r = refresh_one(db, world["asset_manual"])
    assert r.status == "skipped"
    assert "MANUAL" in (r.error or "")


def test_refresh_by_source_filters(db):
    world = _seed_with_crypto(db)
    with patch(
        "numis_geek.services.price_update.brapi_quote",
        return_value=BrapiQuote(ticker="PETR4", price=Decimal("38.5")),
    ):
        summary = refresh_by_source(
            db, PriceSource.BRAPI, workspace_id=world["ws_id"],
        )
    # Only the BR asset (BRAPI source) should have been processed.
    assert summary.ok == 1
    assert summary.skipped == 0
    assert all(r.source == "BRAPI" for r in summary.results)


def test_refresh_by_ids_filters_and_skips_manual(db):
    world = _seed_with_crypto(db)
    ids = [world["asset_br"].id, world["asset_manual"].id]
    with patch(
        "numis_geek.services.price_update.brapi_quote",
        return_value=BrapiQuote(ticker="PETR4", price=Decimal("38.5")),
    ):
        summary = refresh_by_ids(db, ids, workspace_id=world["ws_id"])
    assert summary.ok == 1   # BR
    assert summary.skipped == 1  # MANUAL
    assert summary.failed == 0


def test_refresh_all_automated_excludes_manual(db):
    world = _seed_with_crypto(db)
    with patch(
        "numis_geek.services.price_update.brapi_quote",
        return_value=BrapiQuote(ticker="PETR4", price=Decimal("38.5")),
    ), patch(
        "numis_geek.services.price_update.finnhub_quote",
        return_value=FinnhubQuote(symbol="AAPL", price=Decimal("190")),
    ), patch(
        "numis_geek.services.price_update.coinbase_spot",
        return_value=CoinbaseQuote(symbol="BTC", price=Decimal("67000"), currency="USD"),
    ):
        summary = refresh_all_automated(db, workspace_id=world["ws_id"])
    # BR + US + Crypto = 3 ok, Manual excluded.
    assert summary.ok == 3
    assert summary.failed == 0
    assert summary.skipped == 0


def test_refresh_one_emits_audit_on_success(db):
    world = _seed_world(db)
    with patch(
        "numis_geek.services.price_update.brapi_quote",
        return_value=BrapiQuote(ticker="PETR4", price=Decimal("38.5")),
    ):
        refresh_one(db, world["asset_br"], user_email="alice@test.com")
    audit = (
        db.query(AuditLog)
        .filter(AuditLog.action == "price.refresh",
                AuditLog.resource_id == world["asset_br"].id)
        .first()
    )
    assert audit is not None
    assert audit.user_email == "alice@test.com"
    assert "PETR4" in (audit.details or "")
    assert "BRAPI" in (audit.details or "")


def test_refresh_one_no_audit_on_failure(db):
    world = _seed_world(db)
    with patch(
        "numis_geek.services.price_update.brapi_quote",
        side_effect=BrapiError("network"),
    ):
        refresh_one(db, world["asset_br"])
    audit = (
        db.query(AuditLog)
        .filter(AuditLog.action == "price.refresh",
                AuditLog.resource_id == world["asset_br"].id)
        .first()
    )
    assert audit is None


def test_coinbase_invalid_ticker_is_skipped_not_failed(db):
    """A CRYPTO asset with a name-like ticker (space/accent) should skip
    instead of failing — Coinbase would return 404 otherwise."""
    world = _seed_world(db)
    now = datetime.now(timezone.utc)
    bad = Asset(
        id=str(uuid.uuid4()), workspace_id=world["ws_id"],
        account_id=world["asset_br"].account_id,
        asset_class=AssetClass.CRYPTO, country="BR", name="Meli Dólar",
        ticker="Meli Dólar",  # invalid: has space + accent
        currency=Currency.USD, price_source=PriceSource.COINBASE,
        is_active=True, created_at=now, updated_at=now,
    )
    db.add(bad)
    db.flush()
    # Should not call coinbase_spot at all.
    with patch("numis_geek.services.price_update.coinbase_spot") as spot:
        r = refresh_one(db, bad)
    assert r.status == "skipped"
    assert "Coinbase symbol" in (r.error or "")
    spot.assert_not_called()


def test_cron_audit_action_variant(db):
    world = _seed_world(db)
    with patch(
        "numis_geek.services.price_update.brapi_quote",
        return_value=BrapiQuote(ticker="PETR4", price=Decimal("38.5")),
    ):
        refresh_one(db, world["asset_br"], audit_action="price.refresh.cron")
    cron_audit = (
        db.query(AuditLog).filter(AuditLog.action == "price.refresh.cron").first()
    )
    assert cron_audit is not None
