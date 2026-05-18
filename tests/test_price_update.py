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
from numis_geek.models.asset import Asset, AssetClass
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.integration_credential import (
    CredentialTestResult,
    IntegrationCredential,
    IntegrationProvider,
)
from numis_geek.models.workspace import Workspace
from numis_geek.services.price_update import refresh_bulk, refresh_one


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
        currency=Currency.BRL, is_active=True, created_at=now, updated_at=now,
    )
    asset_us = Asset(
        id=str(uuid.uuid4()), workspace_id=ws.id, account_id=acc.id,
        asset_class=AssetClass.STOCK, country="US", name="Apple", ticker="AAPL",
        currency=Currency.USD, is_active=True, created_at=now, updated_at=now,
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
        currency=Currency.BRL, is_active=True, created_at=now, updated_at=now,
    )
    db.add_all([ws, fi, acc, asset])
    db.flush()
    r = refresh_one(db, asset)
    assert r.status == "skipped"
    assert "BRAPI credential missing" in (r.error or "")
