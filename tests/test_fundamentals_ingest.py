"""Spec 61b — Fundamentals ingestion tests.

Mocks brapi.fetch_fundamentals / finnhub.fetch_basic_financials /
yfinance.fetch_fundamentals — no network calls. Verifies provider
dispatch by class+country and per-asset failure isolation.
"""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest

from numis_geek.integrations.brapi import BrapiFundamentals
from numis_geek.integrations.finnhub import FinnhubFundamentals
from numis_geek.integrations.yfinance import YFinanceFundamentals
from numis_geek.models.account import Account, AccountType, Currency
from numis_geek.models.asset import Asset, AssetClass
from numis_geek.models.asset_fundamentals import (
    AssetFundamentals, FundamentalsSource,
)
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.integration_credential import (
    IntegrationCredential, IntegrationProvider,
)
from numis_geek.models.workspace import Workspace
from numis_geek.services.fundamentals_ingest import (
    refresh_asset_fundamentals, refresh_workspace_fundamentals,
)


def _setup(db, *, asset_class=AssetClass.STOCK, country="BR",
           currency=Currency.BRL, ticker="TICK"):
    ws = Workspace(name=f"WS-fi-{uuid.uuid4().hex[:6]}")
    db.add(ws); db.flush()
    fi = FinancialInstitution(
        id=str(uuid.uuid4()), long_name="FI", short_name="FI",
        logo_slug=None, is_active=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(fi); db.flush()
    acc = Account(
        id=str(uuid.uuid4()), workspace_id=ws.id,
        financial_institution_id=fi.id, name="Acc",
        account_type=AccountType.investment, currency=currency,
        opening_balance=Decimal("0"), is_active=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(acc); db.flush()
    asset = Asset(
        id=str(uuid.uuid4()), workspace_id=ws.id, account_id=acc.id,
        asset_class=asset_class, country=country, name="A",
        ticker=ticker, currency=currency,
        is_active=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(asset); db.flush()
    return ws, asset


def _add_cred(db, provider, value="tok123"):
    cred = IntegrationCredential(
        workspace_id=None, provider=provider, key_name="default",
        secret_value=value, is_active=True,
    )
    db.add(cred); db.flush()


# ── Provider dispatch ────────────────────────────────────────────────────────


def test_br_stock_routes_to_brapi(db):
    ws, asset = _setup(db, country="BR", asset_class=AssetClass.STOCK)
    _add_cred(db, IntegrationProvider.BRAPI)
    fake = BrapiFundamentals(
        ticker="TICK", snapshot_date=date.today(),
        pe=Decimal("12"), eps=Decimal("5"),
    )
    with patch("numis_geek.services.fundamentals_ingest.brapi.fetch_fundamentals",
               return_value=fake):
        row = refresh_asset_fundamentals(db, asset)
    assert row is not None
    assert row.source == FundamentalsSource.BRAPI
    assert row.pe == Decimal("12")


def test_us_stock_routes_to_finnhub(db):
    ws, asset = _setup(db, country="US", asset_class=AssetClass.STOCK,
                       currency=Currency.USD)
    _add_cred(db, IntegrationProvider.FINNHUB)
    fake = FinnhubFundamentals(
        symbol="TICK", snapshot_date=date.today(),
        pe=Decimal("20"), eps=Decimal("3"), roe=Decimal("0.15"),
    )
    with patch("numis_geek.services.fundamentals_ingest.finnhub.fetch_basic_financials",
               return_value=fake):
        row = refresh_asset_fundamentals(db, asset)
    assert row is not None
    assert row.source == FundamentalsSource.FINNHUB
    assert row.roe == Decimal("0.15")


def test_us_etf_routes_to_yfinance(db):
    ws, asset = _setup(db, country="US", asset_class=AssetClass.ETF,
                       currency=Currency.USD)
    fake = YFinanceFundamentals(
        symbol="TICK", snapshot_date=date.today(),
        expense_ratio=Decimal("0.003"), aum=Decimal("1000000000"),
    )
    with patch("numis_geek.services.fundamentals_ingest.yfin.is_available",
               return_value=True), \
         patch("numis_geek.services.fundamentals_ingest.yfin.fetch_fundamentals",
               return_value=fake):
        row = refresh_asset_fundamentals(db, asset)
    assert row is not None
    assert row.source == FundamentalsSource.YFINANCE
    assert row.expense_ratio == Decimal("0.003")


def test_brapi_skipped_when_no_credential(db):
    ws, asset = _setup(db, country="BR")
    # No credential added.
    row = refresh_asset_fundamentals(db, asset)
    assert row is None


def test_finnhub_skipped_when_no_credential(db):
    ws, asset = _setup(db, country="US", currency=Currency.USD)
    row = refresh_asset_fundamentals(db, asset)
    assert row is None


def test_fixed_income_always_skipped(db):
    ws, asset = _setup(db, asset_class=AssetClass.FIXED_INCOME)
    _add_cred(db, IntegrationProvider.BRAPI)
    row = refresh_asset_fundamentals(db, asset)
    assert row is None


@pytest.mark.parametrize("klass", [
    AssetClass.CRYPTO, AssetClass.REAL_ESTATE, AssetClass.VEHICLE,
    AssetClass.FGTS, AssetClass.CASH, AssetClass.PRIVATE_PENSION,
    AssetClass.OPTION, AssetClass.FUND,
])
def test_unsupported_classes_skipped(db, klass):
    ws, asset = _setup(db, asset_class=klass)
    _add_cred(db, IntegrationProvider.BRAPI)
    row = refresh_asset_fundamentals(db, asset)
    assert row is None


def test_asset_without_ticker_skipped(db):
    ws, asset = _setup(db, ticker=None)
    _add_cred(db, IntegrationProvider.BRAPI)
    row = refresh_asset_fundamentals(db, asset)
    assert row is None


# ── Upsert behavior ──────────────────────────────────────────────────────────


def test_same_day_refresh_updates_in_place(db):
    ws, asset = _setup(db, country="BR")
    _add_cred(db, IntegrationProvider.BRAPI)
    fake1 = BrapiFundamentals(ticker="TICK", snapshot_date=date.today(), pe=Decimal("10"))
    fake2 = BrapiFundamentals(ticker="TICK", snapshot_date=date.today(), pe=Decimal("11"))
    with patch("numis_geek.services.fundamentals_ingest.brapi.fetch_fundamentals",
               return_value=fake1):
        refresh_asset_fundamentals(db, asset)
    with patch("numis_geek.services.fundamentals_ingest.brapi.fetch_fundamentals",
               return_value=fake2):
        refresh_asset_fundamentals(db, asset)
    rows = db.query(AssetFundamentals).filter_by(asset_id=asset.id).all()
    assert len(rows) == 1
    assert rows[0].pe == Decimal("11")


# ── Workspace orchestrator: error isolation ──────────────────────────────────


def test_workspace_refresh_continues_after_per_asset_failure(db):
    ws, asset_a = _setup(db, country="BR", ticker="A")
    asset_b = Asset(
        id=str(uuid.uuid4()), workspace_id=ws.id,
        account_id=asset_a.account_id,
        asset_class=AssetClass.STOCK, country="BR", name="B",
        ticker="B", currency=Currency.BRL, is_active=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(asset_b); db.flush()
    _add_cred(db, IntegrationProvider.BRAPI)

    def flaky(ticker, token):
        if ticker == "A":
            raise RuntimeError("provider down for A")
        return BrapiFundamentals(ticker=ticker, snapshot_date=date.today(), pe=Decimal("8"))

    with patch("numis_geek.services.fundamentals_ingest.brapi.fetch_fundamentals",
               side_effect=flaky):
        summary = refresh_workspace_fundamentals(db, ws.id)
    assert summary.failed == 1
    assert summary.ok == 1
