"""Spec 35 — tests for the monthly auto-snapshot job."""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from numis_geek.db.base import Base
import numis_geek.models  # noqa: F401
from numis_geek.models.audit_log import AuditLog
from numis_geek.models.portfolio_snapshot import (
    PortfolioSnapshot,
    SnapshotSource,
    SnapshotStatus,
)
from numis_geek.models.workspace import Workspace
from numis_geek.jobs.snapshot_auto import run_monthly_snapshot


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


def _seed_workspace(db, name: str) -> str:
    ws = Workspace(id=str(uuid.uuid4()), name=name)
    db.add(ws)
    db.flush()
    return ws.id


def test_run_monthly_snapshot_creates_for_each_workspace(db):
    ws_a = _seed_workspace(db, "WS A")
    ws_b = _seed_workspace(db, "WS B")
    db.commit()

    # Stub refresh_all_automated so we don't try real adapters.
    with patch(
        "numis_geek.jobs.snapshot_auto.refresh_all_automated"
    ) as refresh_mock:
        # Empty summary OK.
        from numis_geek.services.price_update import RefreshSummary
        refresh_mock.return_value = RefreshSummary(
            ok=0, failed=0, skipped=0, errors=[],
            ran_at=datetime.now(timezone.utc), results=[],
        )
        results = run_monthly_snapshot(db, target_ym="2026-04")

    statuses = sorted(r.status for r in results)
    assert statuses == ["created", "created"]
    snaps = db.query(PortfolioSnapshot).filter(
        PortfolioSnapshot.workspace_id.in_([ws_a, ws_b])
    ).all()
    assert len(snaps) == 2
    for s in snaps:
        assert s.source == SnapshotSource.AUTOMATED
        # No assets seeded, so no pendencies → CLOSED
        assert s.status == SnapshotStatus.CLOSED
        assert s.period_end_date == date(2026, 4, 30)
        assert s.auto_run_at is not None


def test_run_monthly_snapshot_is_idempotent(db):
    """Second invocation skips workspaces whose target period already
    has a CLOSED snapshot."""
    ws_id = _seed_workspace(db, "Idem WS")
    db.commit()

    with patch("numis_geek.jobs.snapshot_auto.refresh_all_automated") as r:
        from numis_geek.services.price_update import RefreshSummary
        r.return_value = RefreshSummary(
            ok=0, failed=0, skipped=0, errors=[],
            ran_at=datetime.now(timezone.utc), results=[],
        )
        first = run_monthly_snapshot(db, target_ym="2026-04")
        second = run_monthly_snapshot(db, target_ym="2026-04")

    assert first[0].status == "created"
    assert second[0].status == "skipped"
    # Still only 1 snapshot in DB.
    n = db.query(PortfolioSnapshot).filter(
        PortfolioSnapshot.workspace_id == ws_id
    ).count()
    assert n == 1


def test_run_monthly_snapshot_emits_audit(db):
    ws_id = _seed_workspace(db, "Audit WS")
    db.commit()
    with patch("numis_geek.jobs.snapshot_auto.refresh_all_automated") as r:
        from numis_geek.services.price_update import RefreshSummary
        r.return_value = RefreshSummary(
            ok=0, failed=0, skipped=0, errors=[],
            ran_at=datetime.now(timezone.utc), results=[],
        )
        run_monthly_snapshot(db, target_ym="2026-04")

    audits = db.query(AuditLog).filter(
        AuditLog.action == "snapshot.auto_create",
        AuditLog.workspace_id == ws_id,
    ).all()
    assert len(audits) == 1
