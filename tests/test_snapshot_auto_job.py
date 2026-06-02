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


def test_cron_skips_when_user_has_in_review_snapshot(db):
    """Spec 35 hotfix CRÍTICO — o cron NUNCA pode destruir um snapshot
    que o usuário está revisando. Antes (force_reopen=True), a cascade
    deletava items + pendências resolvidas + dataset do user. Agora skip."""
    from numis_geek.models.portfolio_snapshot import (
        SnapshotSource, SnapshotStatus, PortfolioSnapshot,
        SnapshotPendency, PendencyReason, PendencyAction,
    )
    import uuid as _uuid

    ws_id = _seed_workspace(db, "Protect WS")
    # Sembrar um snapshot IN_REVIEW manualmente (simula user em fluxo).
    snap = PortfolioSnapshot(
        id=str(_uuid.uuid4()), workspace_id=ws_id,
        period_end_date=date(2026, 4, 30),
        total_value_brl=Decimal("100000"), total_value_usd=Decimal("19000"),
        total_invested_brl=Decimal("90000"), total_received_brl=Decimal("0"),
        source=SnapshotSource.AUTOMATED, status=SnapshotStatus.IN_REVIEW,
        notion_sync_status="PENDING", auto_run_at=datetime.now(timezone.utc),
    )
    db.add(snap)
    db.flush()
    # Mark "resolved" pendency state so we can verify it wasn't destroyed.
    initial_snapshot_id = snap.id
    db.commit()

    with patch("numis_geek.jobs.snapshot_auto.refresh_all_automated") as r:
        from numis_geek.services.price_update import RefreshSummary
        r.return_value = RefreshSummary(
            ok=0, failed=0, skipped=0, errors=[],
            ran_at=datetime.now(timezone.utc), results=[],
        )
        results = run_monthly_snapshot(db, target_ym="2026-04")

    # The cron SKIPS the protected workspace specifically (other
    # workspaces in the DB may exist from earlier tests in this
    # module-scoped suite, so filter on our ws_id).
    mine = [r for r in results if r.workspace_id == ws_id]
    assert len(mine) == 1
    assert mine[0].status == "skipped"
    # Snapshot ID preserved (not cascade-deleted + re-created).
    surviving = (
        db.query(PortfolioSnapshot)
        .filter(PortfolioSnapshot.workspace_id == ws_id)
        .all()
    )
    assert len(surviving) == 1
    assert surviving[0].id == initial_snapshot_id


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
