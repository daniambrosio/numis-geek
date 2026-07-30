"""Tests para GET /drift, POST /items/{asset_id}/recompute, POST /items/{asset_id}/skip-recompute.

Spec 51 — retroactive event reconciliation. Cobertura:
- Snapshot CLOSED + AssetMovement retroativo criado após close
- POST /recompute recomputa item + grava audit action 'snapshot.item.recompute'
  com auto_reopened=True nos details (comprova que o reopen automático rolou;
  se não havia pendency aberta, snap volta a CLOSED via auto_reclose)
- POST /skip-recompute marca skipped no audit; snapshot permanece CLOSED
- GET /drift agrega entries via audit_log ('snapshot.recompute.skipped')
- Autorização: member/admin OUTRO workspace → 404; sysadmin híbrido → OK
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

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
from numis_geek.models.account import Account, AccountType, Currency
from numis_geek.models.asset import Asset, AssetClass
from numis_geek.models.asset_movement import AssetMovement, AssetMovementType
from numis_geek.models.audit_log import AuditLog
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.portfolio_snapshot import (
    PortfolioSnapshot, SnapshotStatus,
)
from numis_geek.models.ptax_rate import PTAXRate
from numis_geek.models.user import User, UserRole
from numis_geek.models.workspace import Workspace
from numis_geek.services.auth import AuthService
from numis_geek.services.snapshot import create_snapshot


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


@pytest.fixture
def client(db):
    def _gen():
        yield db
    app.dependency_overrides[get_db] = _gen
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _mk_user(db, ws_id, role, email):
    now = datetime.now(timezone.utc)
    u = User(
        id=str(uuid.uuid4()), workspace_id=ws_id, email=email, name="U",
        password_hash=bcrypt.hashpw(b"pw", bcrypt.gensalt()).decode(),
        role=role, is_active=True,
        created_at=now, updated_at=now,
    )
    db.add(u); db.flush()
    return u


def _seed(db):
    """Snapshot CLOSED com 1 stock item (BUY 100 @ 30). Depois adiciona
    AssetMovement retroativo (BUY 50) — o drift a ser reconciliado."""
    now = datetime.now(timezone.utc)
    ws_own = Workspace(id=str(uuid.uuid4()), name="own")
    ws_other = Workspace(id=str(uuid.uuid4()), name="other")
    fi = FinancialInstitution(
        id=str(uuid.uuid4()), long_name="XP", short_name="XP", country="BR",
        is_active=True, created_at=now, updated_at=now,
    )
    acc = Account(
        id=str(uuid.uuid4()), workspace_id=ws_own.id,
        financial_institution_id=fi.id, name="XP Inv",
        account_type=AccountType.investment, currency=Currency.BRL,
        is_active=True, created_at=now, updated_at=now,
    )
    period = date(2026, 3, 31)
    ptax = PTAXRate(
        id=str(uuid.uuid4()), date=period, rate=Decimal("5.00"),
        source="BCB_SGS", fetched_at=now,
    )
    stock = Asset(
        id=str(uuid.uuid4()), workspace_id=ws_own.id, account_id=acc.id,
        asset_class=AssetClass.STOCK, country="BR",
        name="Petrobras", ticker="PETR4", currency=Currency.BRL,
        current_price=Decimal("30"), price_source=None,
        is_active=True, created_at=now, updated_at=now,
    )
    db.add_all([ws_own, ws_other, fi, acc, ptax, stock]); db.flush()
    db.add(AssetMovement(
        id=str(uuid.uuid4()), workspace_id=ws_own.id, asset_id=stock.id,
        type=AssetMovementType.BUY, event_date=date(2026, 1, 10),
        quantity=Decimal("100"), unit_price=Decimal("30"),
        gross_amount=Decimal("3000"), net_amount=Decimal("3000"),
        currency=Currency.BRL, fx_rate=Decimal("1"),
        is_active=True, created_at=now, updated_at=now,
    ))
    db.flush()

    tag = uuid.uuid4().hex[:6]
    admin_own = _mk_user(db, ws_own.id, UserRole.admin, f"admin_own_{tag}@t.com")
    _mk_user(db, ws_other.id, UserRole.admin, f"admin_other_{tag}@t.com")
    _mk_user(db, ws_own.id, UserRole.sysadmin, f"sys_{tag}@t.internal")
    db.flush()

    # Snapshot CLOSED (asset com price_source=None não gera pendency,
    # então initial_status=CLOSED é honrado).
    result = create_snapshot(
        db, workspace_id=ws_own.id, period_end=period,
        initial_status=SnapshotStatus.CLOSED,
        user_id=admin_own.id,
    )
    db.flush()
    snap = db.get(PortfolioSnapshot, result.snapshot_id)
    assert snap.status == SnapshotStatus.CLOSED, "seed esperava CLOSED"

    # Movement retroativo APÓS close — event_date dentro do período
    # (impacta o snapshot). trigger_event_id no /recompute /skip
    # aceita qualquer string; é só pra audit.
    retro_id = str(uuid.uuid4())
    db.add(AssetMovement(
        id=retro_id, workspace_id=ws_own.id, asset_id=stock.id,
        type=AssetMovementType.BUY, event_date=date(2026, 1, 20),
        quantity=Decimal("50"), unit_price=Decimal("30"),
        gross_amount=Decimal("1500"), net_amount=Decimal("1500"),
        currency=Currency.BRL, fx_rate=Decimal("1"),
        is_active=True, created_at=now, updated_at=now,
    ))
    db.flush()

    return {
        "snapshot_id": result.snapshot_id,
        "stock_id": stock.id, "retro_id": retro_id,
        "tok_own": AuthService(db).login(f"admin_own_{tag}@t.com", "pw"),
        "tok_other_admin": AuthService(db).login(f"admin_other_{tag}@t.com", "pw"),
        "tok_sys": AuthService(db).login(f"sys_{tag}@t.internal", "pw"),
    }


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}"}


def _skip_body(retro_id, reason="Aceito"):
    return {"trigger_event_type": "asset_movement",
            "trigger_event_id": retro_id, "reason": reason}


def _recompute_body(retro_id):
    return {"trigger_event_type": "asset_movement",
            "trigger_event_id": retro_id}


# ═════════════════════════════════════════════════════════════════════════
# GET /snapshots/{id}/drift
# ═════════════════════════════════════════════════════════════════════════


def test_drift_empty_when_no_skip_recorded(db, client):
    s = _seed(db)
    r = client.get(
        f"/api/snapshots/{s['snapshot_id']}/drift",
        headers=_hdr(s["tok_own"]),
    )
    assert r.status_code == 200, r.text
    assert r.json() == []


def test_drift_returns_entry_after_skip(db, client):
    """Skip grava audit; drift agrega a partir do audit_log."""
    s = _seed(db)
    r_skip = client.post(
        f"/api/snapshots/{s['snapshot_id']}/items/{s['stock_id']}/skip-recompute",
        json=_skip_body(s["retro_id"], "Aporte antigo — manter"),
        headers=_hdr(s["tok_own"]),
    )
    assert r_skip.status_code == 204, r_skip.text
    r = client.get(
        f"/api/snapshots/{s['snapshot_id']}/drift",
        headers=_hdr(s["tok_own"]),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) == 1, body
    entry = body[0]
    assert entry["asset_id"] == s["stock_id"]
    assert entry["reason"] == "Aporte antigo — manter"
    assert entry["trigger_event_type"] == "asset_movement"
    assert entry["trigger_event_id"] == s["retro_id"]


def test_drift_cross_workspace_blocked(db, client):
    s = _seed(db)
    r = client.get(
        f"/api/snapshots/{s['snapshot_id']}/drift",
        headers=_hdr(s["tok_other_admin"]),
    )
    assert r.status_code == 404, r.text


def test_drift_sysadmin_accepted(db, client):
    s = _seed(db)
    r = client.get(
        f"/api/snapshots/{s['snapshot_id']}/drift",
        headers=_hdr(s["tok_sys"]),
    )
    assert r.status_code == 200, r.text


# ═════════════════════════════════════════════════════════════════════════
# POST /snapshots/{id}/items/{asset_id}/recompute
# ═════════════════════════════════════════════════════════════════════════


def test_recompute_updates_item_and_logs_audit(db, client):
    """qty=100 antes → 150 depois. Audit action='snapshot.item.recompute'
    com auto_reopened=True (comprova reopen automático do CLOSED)."""
    s = _seed(db)
    r = client.post(
        f"/api/snapshots/{s['snapshot_id']}/items/{s['stock_id']}/recompute",
        json=_recompute_body(s["retro_id"]),
        headers=_hdr(s["tok_own"]),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert Decimal(body["quantity"]) == Decimal("150"), body

    rows = (
        db.query(AuditLog)
        .filter(AuditLog.action == "snapshot.item.recompute")
        .order_by(AuditLog.created_at.desc())
        .all()
    )
    assert len(rows) >= 1, "esperava audit snapshot.item.recompute"
    details = json.loads(rows[0].details or "{}")
    assert details.get("snapshot_id") == s["snapshot_id"]
    assert details.get("asset_id") == s["stock_id"]
    assert details.get("auto_reopened") is True, (
        "reopen automático do snapshot CLOSED não foi registrado"
    )
    assert details.get("trigger_event_id") == s["retro_id"]


def test_recompute_cross_workspace_blocked(db, client):
    s = _seed(db)
    r = client.post(
        f"/api/snapshots/{s['snapshot_id']}/items/{s['stock_id']}/recompute",
        json=_recompute_body(s["retro_id"]),
        headers=_hdr(s["tok_other_admin"]),
    )
    assert r.status_code == 404, r.text


def test_recompute_sysadmin_accepted(db, client):
    s = _seed(db)
    r = client.post(
        f"/api/snapshots/{s['snapshot_id']}/items/{s['stock_id']}/recompute",
        json=_recompute_body(s["retro_id"]),
        headers=_hdr(s["tok_sys"]),
    )
    assert r.status_code == 200, r.text


# ═════════════════════════════════════════════════════════════════════════
# POST /snapshots/{id}/items/{asset_id}/skip-recompute
# ═════════════════════════════════════════════════════════════════════════


def test_skip_recompute_keeps_snapshot_closed(db, client):
    s = _seed(db)
    r = client.post(
        f"/api/snapshots/{s['snapshot_id']}/items/{s['stock_id']}/skip-recompute",
        json=_skip_body(s["retro_id"]),
        headers=_hdr(s["tok_own"]),
    )
    assert r.status_code == 204, r.text
    # apply_skip_recompute só loga; não muda status.
    snap = db.get(PortfolioSnapshot, s["snapshot_id"])
    db.refresh(snap)
    assert snap.status == SnapshotStatus.CLOSED, (
        f"skip não deve reabrir snapshot; status atual = {snap.status}"
    )


def test_skip_recompute_cross_workspace_blocked(db, client):
    s = _seed(db)
    r = client.post(
        f"/api/snapshots/{s['snapshot_id']}/items/{s['stock_id']}/skip-recompute",
        json=_skip_body(s["retro_id"]),
        headers=_hdr(s["tok_other_admin"]),
    )
    assert r.status_code == 404, r.text


def test_skip_recompute_sysadmin_accepted(db, client):
    s = _seed(db)
    r = client.post(
        f"/api/snapshots/{s['snapshot_id']}/items/{s['stock_id']}/skip-recompute",
        json=_skip_body(s["retro_id"]),
        headers=_hdr(s["tok_sys"]),
    )
    assert r.status_code == 204, r.text
