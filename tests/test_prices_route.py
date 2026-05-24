"""Spec 23 — tests for /prices/refresh + 422 gate on /assets/{id}/refresh-price."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch

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
from numis_geek.integrations.brapi import BrapiQuote
from numis_geek.integrations.coinbase import CoinbaseQuote
from numis_geek.integrations.finnhub import FinnhubQuote
from numis_geek.models.account import Account, AccountType, Currency
from numis_geek.models.asset import Asset, AssetClass, PriceSource
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.integration_credential import (
    CredentialTestResult,
    IntegrationCredential,
    IntegrationProvider,
)
from numis_geek.models.user import User, UserRole
from numis_geek.models.workspace import Workspace
from numis_geek.services.auth import AuthService


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
    now = datetime.now(timezone.utc)

    ws = Workspace(id=str(uuid.uuid4()), name="Prices WS")
    fi = FinancialInstitution(
        id=str(uuid.uuid4()), long_name="XP", short_name="XP", logo_slug="xp",
        is_active=True, created_at=now, updated_at=now,
    )
    acc = Account(
        id=str(uuid.uuid4()), workspace_id=ws.id, financial_institution_id=fi.id,
        name="X", account_type=AccountType.investment, currency=Currency.BRL,
        is_active=True, created_at=now, updated_at=now,
    )
    member = User(
        id=str(uuid.uuid4()), workspace_id=ws.id,
        email="prices_member@test.com", name="M",
        password_hash=bcrypt.hashpw(b"memberpass", bcrypt.gensalt()).decode(),
        role=UserRole.member, is_active=True, created_at=now, updated_at=now,
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
    asset_btc = Asset(
        id=str(uuid.uuid4()), workspace_id=ws.id, account_id=acc.id,
        asset_class=AssetClass.CRYPTO, country="US", name="Bitcoin", ticker="BTC",
        currency=Currency.USD, price_source=PriceSource.COINBASE,
        is_active=True, created_at=now, updated_at=now,
    )
    asset_manual = Asset(
        id=str(uuid.uuid4()), workspace_id=ws.id, account_id=acc.id,
        asset_class=AssetClass.REAL_ESTATE, country="BR", name="Casa", ticker=None,
        currency=Currency.BRL, price_source=PriceSource.MANUAL,
        is_active=True, created_at=now, updated_at=now,
    )

    asset_br_id = asset_br.id
    asset_us_id = asset_us.id
    asset_btc_id = asset_btc.id
    asset_manual_id = asset_manual.id

    db.add_all([ws, fi, acc, member, asset_br, asset_us, asset_btc, asset_manual])
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
    db.commit()

    tok = AuthService(db).login("prices_member@test.com", "memberpass")
    db.close()

    return {
        "tok": tok,
        "asset_br_id": asset_br_id,
        "asset_us_id": asset_us_id,
        "asset_btc_id": asset_btc_id,
        "asset_manual_id": asset_manual_id,
    }


def auth(tok):
    return {"Authorization": f"Bearer {tok}"}


# ── /prices/refresh ──────────────────────────────────────────────────────────


def test_refresh_no_body_runs_all_automated(client, seed):
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
        r = client.post("/prices/refresh", headers=auth(seed["tok"]), json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] == 3   # br + us + btc
    assert body["failed"] == 0
    assert "ran_at" in body


def test_refresh_filtered_by_source(client, seed):
    with patch(
        "numis_geek.services.price_update.brapi_quote",
        return_value=BrapiQuote(ticker="PETR4", price=Decimal("38.5")),
    ):
        r = client.post(
            "/prices/refresh", headers=auth(seed["tok"]),
            json={"source": "BRAPI"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] == 1
    assert body["failed"] == 0


def test_refresh_by_asset_ids_skips_manual(client, seed):
    with patch(
        "numis_geek.services.price_update.brapi_quote",
        return_value=BrapiQuote(ticker="PETR4", price=Decimal("38.5")),
    ):
        r = client.post(
            "/prices/refresh", headers=auth(seed["tok"]),
            json={"asset_ids": [seed["asset_br_id"], seed["asset_manual_id"]]},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] == 1
    assert body["skipped"] == 1


# ── /assets/{id}/refresh-price ──────────────────────────────────────────────


def test_single_refresh_returns_price_source(client, seed):
    with patch(
        "numis_geek.services.price_update.brapi_quote",
        return_value=BrapiQuote(ticker="PETR4", price=Decimal("39.99")),
    ):
        r = client.post(
            f"/assets/{seed['asset_br_id']}/refresh-price",
            headers=auth(seed["tok"]),
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["price_source"] == "BRAPI"
    assert body["new_price"] == 39.99


def test_single_refresh_422_on_manual(client, seed):
    r = client.post(
        f"/assets/{seed['asset_manual_id']}/refresh-price",
        headers=auth(seed["tok"]),
    )
    assert r.status_code == 422
    assert "MANUAL" in r.json()["detail"]


# ── deprecated bulk ─────────────────────────────────────────────────────────


def test_legacy_bulk_endpoint_still_works_with_deprecation_headers(client, seed):
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
        r = client.post("/assets/refresh-prices/bulk", headers=auth(seed["tok"]))
    assert r.status_code == 200
    assert r.headers.get("Deprecation") == "true"
    assert r.headers.get("Sunset") == "2026-12-31"
    assert "/prices/refresh" in (r.headers.get("Link") or "")
