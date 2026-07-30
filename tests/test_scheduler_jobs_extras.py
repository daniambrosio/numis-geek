"""Extras coverage for scheduler entrypoints not exercised by
test_scheduler.py (which covers run_daily_price_refresh).

Covers:
- run_daily_backup             → wraps services.backup.create_backup + rotate_backups
- run_daily_fundamentals_refresh → iterates workspaces + swallows per-ws errors
- run_option_auto_settle        → wraps services.option_lifecycle.auto_settle_expired_options

Same pattern as test_scheduler.py: call the underlying function directly,
patch the module-level names imported by scheduler.py, and assert the
side effects on mocks (no live network / no live SQLite backup).
"""
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from numis_geek.db.base import Base
import numis_geek.models  # noqa: F401
from numis_geek.models.workspace import Workspace
from numis_geek.services.backup import BackupResult, RotationResult
from numis_geek.services.fundamentals_ingest import IngestionSummary


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


def _mk_ws(db, name: str) -> Workspace:
    ws = Workspace(id=str(uuid.uuid4()), name=name)
    db.add(ws)
    db.commit()
    return ws


# ---------- run_daily_backup ----------

def test_run_daily_backup_calls_create_and_rotate():
    from numis_geek import scheduler

    fake_result = BackupResult(
        path=Path("data/backups/numis_geek-20260101-070000.db"),
        size_bytes=1024 * 1024,
        duration_ms=42,
        pages_copied=10,
    )
    fake_rot = RotationResult(
        kept=[Path("a.db"), Path("b.db")],
        deleted=[Path("c.db")],
    )
    with patch(
        "numis_geek.scheduler.create_backup", return_value=fake_result,
    ) as mock_cb, patch(
        "numis_geek.scheduler.rotate_backups", return_value=fake_rot,
    ) as mock_rot:
        scheduler.run_daily_backup()

    mock_cb.assert_called_once()
    # Positional args: (DATABASE_URL, BACKUP_DIR)
    args, _ = mock_cb.call_args
    assert args[1] == scheduler.BACKUP_DIR
    mock_rot.assert_called_once_with(scheduler.BACKUP_DIR)


def test_run_daily_backup_swallows_create_error():
    from numis_geek import scheduler

    with patch(
        "numis_geek.scheduler.create_backup",
        side_effect=RuntimeError("disk full"),
    ), patch(
        "numis_geek.scheduler.rotate_backups",
    ) as mock_rot:
        # Must NOT raise — cron jobs never propagate errors.
        scheduler.run_daily_backup()

    # rotate should NOT run when create blew up (it's sequential).
    mock_rot.assert_not_called()


# ---------- run_daily_fundamentals_refresh ----------

def test_run_daily_fundamentals_iterates_all_workspaces(session):
    ws_a = _mk_ws(session, "ws-a-fund")
    ws_b = _mk_ws(session, "ws-b-fund")

    from numis_geek import scheduler

    seen: list[str] = []

    def fake_refresh(db, ws_id):
        seen.append(ws_id)
        return IngestionSummary(ok=1, failed=0, skipped=0)

    with patch(
        "numis_geek.scheduler.SessionLocal", lambda: TestSession(),
    ), patch(
        "numis_geek.scheduler.refresh_workspace_fundamentals",
        side_effect=fake_refresh,
    ):
        scheduler.run_daily_fundamentals_refresh()

    # Both this-test workspaces must be visited (other-test rows may leak
    # into shared in-memory DB, hence subset check).
    assert set(seen) >= {ws_a.id, ws_b.id}


def test_run_daily_fundamentals_swallows_per_workspace_error(session):
    """A single workspace exploding must NOT abort the whole run — the
    scheduler wraps refresh_workspace_fundamentals in try/except so a bad
    workspace is logged and the rest still get processed."""
    ws_a = _mk_ws(session, "ws-a-explode")
    ws_b = _mk_ws(session, "ws-b-safe")

    from numis_geek import scheduler

    calls: list[str] = []

    def flaky(db, ws_id):
        calls.append(ws_id)
        # Fail on the first call only; second and beyond succeed.
        if len(calls) == 1:
            raise RuntimeError("brapi down")
        return IngestionSummary(ok=2, failed=0, skipped=0)

    with patch(
        "numis_geek.scheduler.SessionLocal", lambda: TestSession(),
    ), patch(
        "numis_geek.scheduler.refresh_workspace_fundamentals",
        side_effect=flaky,
    ):
        # Must NOT raise even though the first workspace blew up.
        scheduler.run_daily_fundamentals_refresh()

    # If the swallow works, both workspaces were attempted (>= 2).
    assert len(calls) >= 2
    assert set(calls) >= {ws_a.id, ws_b.id}


# ---------- run_option_auto_settle ----------

def test_run_option_auto_settle_empty_results(session):
    """No expired options → early return, but service still called once."""
    from numis_geek import scheduler

    with patch(
        "numis_geek.scheduler.SessionLocal", lambda: TestSession(),
    ), patch(
        "numis_geek.scheduler.auto_settle_expired_options",
        return_value=[],
    ) as mock_svc:
        scheduler.run_option_auto_settle()

    mock_svc.assert_called_once()
    _, kwargs = mock_svc.call_args
    assert kwargs.get("created_by") == scheduler.CRON_USER_EMAIL


def test_run_option_auto_settle_summarises_mixed_results(session):
    from numis_geek import scheduler
    from numis_geek.services.option_lifecycle import AutoSettleResult

    results = [
        AutoSettleResult(
            option_id="o1", ticker="PETRA100", decision="expired",
            underlying_ticker="PETR4", underlying_price=None,
            price_source=None, price_effective_date=None,
            strike_price=None, option_type=None, reason="ATM",
        ),
        AutoSettleResult(
            option_id="o2", ticker="PETRA110", decision="exercised",
            underlying_ticker="PETR4", underlying_price=None,
            price_source=None, price_effective_date=None,
            strike_price=None, option_type=None, reason="ITM",
        ),
        AutoSettleResult(
            option_id="o3", ticker="VALEP50", decision="skipped",
            underlying_ticker="VALE3", underlying_price=None,
            price_source=None, price_effective_date=None,
            strike_price=None, option_type=None, reason="no price",
        ),
    ]

    with patch(
        "numis_geek.scheduler.SessionLocal", lambda: TestSession(),
    ), patch(
        "numis_geek.scheduler.auto_settle_expired_options",
        return_value=results,
    ):
        # Just ensuring the log-summary branch runs without exploding.
        scheduler.run_option_auto_settle()


def test_run_option_auto_settle_swallows_service_error(session):
    from numis_geek import scheduler

    with patch(
        "numis_geek.scheduler.SessionLocal", lambda: TestSession(),
    ), patch(
        "numis_geek.scheduler.auto_settle_expired_options",
        side_effect=RuntimeError("db down"),
    ):
        # Cron must never propagate; error is logged and swallowed.
        scheduler.run_option_auto_settle()
