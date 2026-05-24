"""Spec 24 — tests for the cron job logic.

We don't try to wait for the actual 18:00 trigger; we call the underlying
function directly (`run_daily_price_refresh`) and assert the side effects.
The trigger setup itself is exercised via a startup smoke test that
toggles DISABLE_SCHEDULER.
"""
import importlib
import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from numis_geek.db.base import Base
import numis_geek.models  # noqa: F401
from numis_geek.integrations.brapi import BrapiQuote
from numis_geek.models.account import Account, AccountType, Currency
from numis_geek.models.asset import Asset, AssetClass, PriceSource
from numis_geek.models.audit_log import AuditLog
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.integration_credential import (
    CredentialTestResult,
    IntegrationCredential,
    IntegrationProvider,
)
from numis_geek.models.workspace import Workspace


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
def session():
    s = TestSession()
    yield s
    s.rollback()
    s.close()


def _seed(db):
    now = datetime.now(timezone.utc)
    ws = Workspace(id=str(uuid.uuid4()), name="Cron WS")
    fi = FinancialInstitution(
        id=str(uuid.uuid4()), long_name="XP", short_name="XP", logo_slug="xp",
        is_active=True, created_at=now, updated_at=now,
    )
    acc = Account(
        id=str(uuid.uuid4()), workspace_id=ws.id, financial_institution_id=fi.id,
        name="X", account_type=AccountType.investment, currency=Currency.BRL,
        is_active=True, created_at=now, updated_at=now,
    )
    asset_br = Asset(
        id=str(uuid.uuid4()), workspace_id=ws.id, account_id=acc.id,
        asset_class=AssetClass.STOCK, country="BR", name="PETR4", ticker="PETR4",
        currency=Currency.BRL, price_source=PriceSource.BRAPI,
        is_active=True, created_at=now, updated_at=now,
    )
    db.add_all([
        ws, fi, acc, asset_br,
        IntegrationCredential(
            id=str(uuid.uuid4()), workspace_id=None,
            provider=IntegrationProvider.BRAPI, key_name="API_TOKEN",
            secret_value="brapi-token", is_active=True,
            last_test_result=CredentialTestResult.UNTESTED,
            created_at=now, updated_at=now,
        ),
    ])
    db.commit()
    return ws.id, asset_br.id


def test_run_daily_price_refresh_audits_as_cron(session):
    ws_id, asset_id = _seed(session)

    from numis_geek import scheduler

    with patch(
        "numis_geek.services.price_update.brapi_quote",
        return_value=BrapiQuote(ticker="PETR4", price=Decimal("40.10")),
    ), patch(
        "numis_geek.scheduler.SessionLocal", lambda: TestSession(),
    ):
        scheduler.run_daily_price_refresh()

    # Audit should be present with the cron action.
    cron_log = (
        session.query(AuditLog)
        .filter(AuditLog.action == "price.refresh.cron",
                AuditLog.resource_id == asset_id)
        .first()
    )
    assert cron_log is not None
    assert cron_log.user_email == "system@cron"

    # Asset got the new price persisted.
    session.expire_all()
    asset = session.get(Asset, asset_id)
    assert asset.current_price == Decimal("40.10")


def test_run_daily_swallows_workspace_exception(session):
    """If one workspace blows up, the cron should log and move on, not crash."""
    ws_id_a, _ = _seed(session)
    # Seed a second workspace too.
    now = datetime.now(timezone.utc)
    ws_b = Workspace(id=str(uuid.uuid4()), name="Cron WS B")
    session.add(ws_b)
    session.commit()

    from numis_geek import scheduler

    call_count = {"n": 0}

    def flaky_refresh(db, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("boom")
        # Return a no-op summary on the second call.
        from numis_geek.services.price_update import _summarize
        return _summarize([])

    with patch(
        "numis_geek.scheduler.refresh_all_automated",
        side_effect=flaky_refresh,
    ), patch(
        "numis_geek.scheduler.SessionLocal", lambda: TestSession(),
    ):
        # Should NOT raise.
        scheduler.run_daily_price_refresh()

    assert call_count["n"] >= 2  # both workspaces were attempted


def test_disable_scheduler_env_skips_start(monkeypatch):
    """When DISABLE_SCHEDULER is truthy, start_scheduler is a no-op."""
    from numis_geek import scheduler

    monkeypatch.setenv("DISABLE_SCHEDULER", "true")
    app = MagicMock()
    app.state = MagicMock()
    result = scheduler.start_scheduler(app)
    assert result is None


def test_scheduler_starts_when_flag_unset(monkeypatch):
    from numis_geek import scheduler

    monkeypatch.delenv("DISABLE_SCHEDULER", raising=False)
    app = MagicMock()
    app.state = MagicMock()
    sched = scheduler.start_scheduler(app)
    assert sched is not None
    try:
        job = sched.get_job(scheduler.CRON_JOB_ID)
        assert job is not None
        assert job.next_run_time is not None
    finally:
        scheduler.stop_scheduler(app)
