"""Spec 11 finalizer — tests for the daily PTAX cron job.

Mirrors `tests/test_scheduler.py` pattern: we don't wait for the 20:00
trigger; we call the underlying `run_daily_ptax_sync` directly and assert
side effects. BCB is mocked — never hit the real API in tests.
"""
from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from numis_geek.db.base import Base
import numis_geek.models  # noqa: F401
from numis_geek.models.ptax_rate import PTAXRate
from numis_geek.services.ptax_sync import PtaxSyncResult


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


def test_run_daily_ptax_sync_calls_incremental(session):
    """Wrapper calls sync_ptax in incremental mode and commits."""
    from numis_geek import scheduler

    fake_result = PtaxSyncResult(
        mode="incremental",
        fetched_count=1,
        inserted_count=1,
        updated_count=0,
        range_start=date(2026, 5, 23),
        range_end=date(2026, 5, 25),
        duration_ms=42,
    )

    captured = {}

    def fake_sync(db, *, mode):
        captured["mode"] = mode
        captured["db"] = db
        return fake_result

    with patch(
        "numis_geek.scheduler.sync_ptax", side_effect=fake_sync,
    ), patch(
        "numis_geek.scheduler.SessionLocal", lambda: TestSession(),
    ):
        # Must not raise.
        scheduler.run_daily_ptax_sync()

    assert captured["mode"] == "incremental"
    assert captured["db"] is not None


def test_run_daily_ptax_sync_swallows_exception():
    """If sync_ptax blows up, cron logs and returns — does NOT propagate."""
    from numis_geek import scheduler

    def boom(db, *, mode):
        raise RuntimeError("BCB unreachable")

    with patch(
        "numis_geek.scheduler.sync_ptax", side_effect=boom,
    ), patch(
        "numis_geek.scheduler.SessionLocal", lambda: TestSession(),
    ):
        # Must not raise — same swallow-and-log pattern as price refresh.
        scheduler.run_daily_ptax_sync()


def test_run_daily_ptax_sync_persists_rows(session):
    """End-to-end-ish: when sync_ptax actually upserts rows, they persist
    after the wrapper's commit. Uses the real sync_ptax with BCB mocked."""
    from numis_geek import scheduler
    from numis_geek.integrations.bcb import PTAXRow
    from decimal import Decimal

    fake_rows = [
        PTAXRow(date=date(2026, 5, 23), rate=Decimal("5.0150")),
        PTAXRow(date=date(2026, 5, 24), rate=Decimal("5.0211")),
    ]

    with patch(
        "numis_geek.services.ptax_sync.fetch_ptax_range",
        return_value=fake_rows,
    ), patch(
        "numis_geek.scheduler.SessionLocal", lambda: TestSession(),
    ):
        scheduler.run_daily_ptax_sync()

    # Confirm rows landed (using a fresh session, since the wrapper closes
    # its own).
    s = TestSession()
    try:
        total = s.query(func.count(PTAXRate.id)).scalar()
        assert total == 2
        latest = s.query(func.max(PTAXRate.date)).scalar()
        assert latest == date(2026, 5, 24)
    finally:
        s.close()


def test_scheduler_registers_ptax_job(monkeypatch):
    """start_scheduler wires the PTAX job alongside price + snapshot."""
    from numis_geek import scheduler

    monkeypatch.delenv("DISABLE_SCHEDULER", raising=False)
    app = MagicMock()
    app.state = MagicMock()
    sched = scheduler.start_scheduler(app)
    assert sched is not None
    try:
        job = sched.get_job(scheduler.PTAX_JOB_ID)
        assert job is not None
        assert job.next_run_time is not None
        # Confirm hour=20 minute=0 cron schedule
        trigger_repr = str(job.trigger)
        assert "hour='20'" in trigger_repr
        assert "minute='0'" in trigger_repr
    finally:
        scheduler.stop_scheduler(app)


# ── Spec 44 follow-up: startup catchup ──────────────────────────────────


def test_run_ptax_catchup_skips_when_fresh():
    """If today's PTAX (SP) already exists, the catchup must NOT call BCB."""
    from datetime import datetime
    from decimal import Decimal
    from zoneinfo import ZoneInfo
    from numis_geek import scheduler

    s = TestSession()
    try:
        # Wipe and seed with today's date (SP).
        s.query(PTAXRate).delete()
        today_sp = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
        s.add(PTAXRate(
            date=today_sp, rate=Decimal("5.0000"),
            source="BCB_SGS", fetched_at=datetime.now(),
        ))
        s.commit()
    finally:
        s.close()

    called = {"sync": False}

    def must_not_be_called(db, *, mode):
        called["sync"] = True
        raise AssertionError("sync_ptax should not be called when fresh")

    with patch(
        "numis_geek.scheduler.sync_ptax", side_effect=must_not_be_called,
    ), patch(
        "numis_geek.scheduler.SessionLocal", lambda: TestSession(),
    ):
        scheduler.run_ptax_catchup()

    assert called["sync"] is False


def test_run_ptax_catchup_syncs_when_stale():
    """When last_date < today (SP), catchup fires sync_ptax(incremental)."""
    from datetime import date, datetime
    from decimal import Decimal
    from numis_geek import scheduler

    s = TestSession()
    try:
        s.query(PTAXRate).delete()
        # Seed with a clearly old date.
        s.add(PTAXRate(
            date=date(2026, 5, 18), rate=Decimal("4.9000"),
            source="BCB_SGS", fetched_at=datetime.now(),
        ))
        s.commit()
    finally:
        s.close()

    captured = {}
    fake_result = PtaxSyncResult(
        mode="incremental",
        fetched_count=2,
        inserted_count=2,
        updated_count=0,
        range_start=date(2026, 5, 19),
        range_end=date(2026, 5, 26),
        duration_ms=12,
    )

    def fake_sync(db, *, mode):
        captured["mode"] = mode
        return fake_result

    with patch(
        "numis_geek.scheduler.sync_ptax", side_effect=fake_sync,
    ), patch(
        "numis_geek.scheduler.SessionLocal", lambda: TestSession(),
    ):
        scheduler.run_ptax_catchup()

    assert captured["mode"] == "incremental"


def test_scheduler_wires_ptax_catchup(monkeypatch):
    """start_scheduler adds the one-shot catchup job. We patch add_job so
    we can observe the wiring (the actual one-shot fires immediately and
    disappears, so a get_job lookup races and is unreliable)."""
    from numis_geek import scheduler

    monkeypatch.delenv("DISABLE_SCHEDULER", raising=False)

    captured_ids: list[str] = []
    original_add_job = None

    def spy_add_job(self, func, trigger=None, **kwargs):
        captured_ids.append(kwargs.get("id"))
        return original_add_job(self, func, trigger, **kwargs)

    from apscheduler.schedulers.background import BackgroundScheduler
    original_add_job = BackgroundScheduler.add_job
    monkeypatch.setattr(BackgroundScheduler, "add_job", spy_add_job)

    app = MagicMock()
    app.state = MagicMock()
    sched = scheduler.start_scheduler(app)
    try:
        assert scheduler.PTAX_CATCHUP_JOB_ID in captured_ids
    finally:
        scheduler.stop_scheduler(app)
