"""Spec 62 — SUSPICIOUS_DELTA HTTP routes.

Cobre GET /snapshots/{id}/mom-deltas, POST /snapshots/{id}/recheck-deltas
e POST /snapshots/pendencies/{pid}/confirm-delta, além de autorização
cross-workspace.
"""
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
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.portfolio_snapshot import (
    PendencyReason,
    PortfolioSnapshot,
    PortfolioSnapshotItem,
    SnapshotPendency,
    SnapshotSource,
    SnapshotStatus,
)
from numis_geek.models.user import User, UserRole
from numis_geek.services.auth import AuthService
from numis_geek.services.snapshot import detect_suspicious_deltas
from numis_geek.services.user import UserService
from numis_geek.services.workspace import WorkspaceService


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


def _mk_ws_with_asset(db, ws_name: str) -> dict:
    now = datetime.now(timezone.utc)
    ws = WorkspaceService(db).create(ws_name)
    fi = FinancialInstitution(
        id=str(uuid.uuid4()), long_name="XP", short_name="XP",
        logo_slug="xp", is_active=True, created_at=now, updated_at=now,
    )
    db.add(fi)
    acc = Account(
        id=str(uuid.uuid4()), workspace_id=ws.id,
        financial_institution_id=fi.id, name="XP Inv",
        account_type=AccountType.investment, currency=Currency.BRL,
        is_active=True, created_at=now, updated_at=now,
    )
    db.add(acc)
    # Asset FUND (threshold 15% — fácil de disparar).
    asset = Asset(
        id=str(uuid.uuid4()), workspace_id=ws.id, account_id=acc.id,
        asset_class=AssetClass.FUND, country="BR",
        name=f"Fundo {ws_name}", ticker=None,
        currency=Currency.BRL, current_price=Decimal("100000"),
        is_active=True, created_at=now, updated_at=now,
    )
    db.add(asset)
    db.flush()
    return {"ws_id": ws.id, "asset_id": asset.id, "now": now}


def _make_snap(db, ws_id: str, period_end: date, asset_id: str, mv_native: Decimal,
                *, status=SnapshotStatus.CLOSED) -> PortfolioSnapshot:
    now = datetime.now(timezone.utc)
    snap = PortfolioSnapshot(
        id=str(uuid.uuid4()), workspace_id=ws_id,
        period_end_date=period_end, fx_rate_usd_brl=Decimal("5.00"),
        total_value_brl=mv_native, total_value_usd=Decimal("0"),
        total_invested_brl=Decimal("0"), total_received_brl=Decimal("0"),
        source=SnapshotSource.MANUAL, status=status,
        closed_at=now if status == SnapshotStatus.CLOSED else None,
        closed_by="seed" if status == SnapshotStatus.CLOSED else None,
        is_active=True, created_at=now, updated_at=now,
    )
    db.add(snap)
    db.add(PortfolioSnapshotItem(
        id=str(uuid.uuid4()), snapshot_id=snap.id, asset_id=asset_id,
        quantity=Decimal("1"), unit_price=mv_native,
        market_value_native=mv_native, market_value_brl=mv_native,
        market_value_usd=mv_native / Decimal("5"),
        total_invested_brl=mv_native, created_at=now, updated_at=now,
    ))
    return snap


@pytest.fixture(scope="module")
def seed():
    """Dois workspaces, cada um com 1 asset FUND e 2 snapshots consecutivos.

    WS A: 50k (abr) → 100k (mai, IN_REVIEW) → 100% de delta > 15% FUND.
    WS B: 50k (abr) → 100k (mai) — mesma coisa, pra teste cross-workspace.
    """
    db = TestSession()
    ws_a = _mk_ws_with_asset(db, "SD WS A")
    ws_b = _mk_ws_with_asset(db, "SD WS B")

    # WS A snapshots (abr CLOSED, mai IN_REVIEW pra detect ter espaço)
    prev_a = _make_snap(
        db, ws_a["ws_id"], date(2026, 4, 30), ws_a["asset_id"],
        Decimal("50000"), status=SnapshotStatus.CLOSED,
    )
    cur_a = _make_snap(
        db, ws_a["ws_id"], date(2026, 5, 31), ws_a["asset_id"],
        Decimal("100000"), status=SnapshotStatus.IN_REVIEW,
    )

    # WS B snapshots
    prev_b = _make_snap(
        db, ws_b["ws_id"], date(2026, 4, 30), ws_b["asset_id"],
        Decimal("50000"), status=SnapshotStatus.CLOSED,
    )
    cur_b = _make_snap(
        db, ws_b["ws_id"], date(2026, 5, 31), ws_b["asset_id"],
        Decimal("100000"), status=SnapshotStatus.IN_REVIEW,
    )

    # Users: admin A, member A, admin B, sysadmin puro.
    UserService(db).create(
        ws_a["ws_id"], "sd_admin_a@test.com", "pw", UserRole.admin,
    )
    UserService(db).create(
        ws_a["ws_id"], "sd_member_a@test.com", "pw", UserRole.member,
    )
    UserService(db).create(
        ws_b["ws_id"], "sd_admin_b@test.com", "pw", UserRole.admin,
    )
    now = datetime.now(timezone.utc)
    sys_u = User(
        id=str(uuid.uuid4()), workspace_id=None,
        email="sd_sys@test.internal", name="Sys",
        password_hash=bcrypt.hashpw(b"pw", bcrypt.gensalt()).decode(),
        role=UserRole.sysadmin, is_active=True,
        created_at=now, updated_at=now,
    )
    db.add(sys_u)
    db.commit()

    # Detecta SUSPICIOUS_DELTA no snapshot atual do WS A pra ter uma
    # pendency já plantada.
    pids_a = detect_suspicious_deltas(db, cur_a.id)
    assert len(pids_a) == 1, "seed inválida: detect_suspicious_deltas não flagou"
    db.commit()

    out = {
        "ws_a_id": ws_a["ws_id"],
        "ws_b_id": ws_b["ws_id"],
        "asset_a_id": ws_a["asset_id"],
        "asset_b_id": ws_b["asset_id"],
        "prev_a_id": prev_a.id,
        "cur_a_id": cur_a.id,
        "prev_b_id": prev_b.id,
        "cur_b_id": cur_b.id,
        "pendency_a_id": pids_a[0],
        "admin_a": AuthService(db).login("sd_admin_a@test.com", "pw"),
        "member_a": AuthService(db).login("sd_member_a@test.com", "pw"),
        "admin_b": AuthService(db).login("sd_admin_b@test.com", "pw"),
        "sysadmin": AuthService(db).login("sd_sys@test.internal", "pw"),
    }
    db.close()
    return out


def _h(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


# ── GET /snapshots/{id}/mom-deltas ──────────────────────────────────────────


def test_mom_deltas_returns_row_for_suspicious_asset(client, seed):
    r = client.get(
        f"/api/snapshots/{seed['cur_a_id']}/mom-deltas",
        headers=_h(seed["admin_a"]),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["snapshot_id"] == seed["cur_a_id"]
    assert body["previous_snapshot_id"] == seed["prev_a_id"]
    assert body["previous_period_end"] == "2026-04-30"
    assert len(body["rows"]) == 1
    row = body["rows"][0]
    assert row["asset_id"] == seed["asset_a_id"]
    assert row["previous_mv_native"] is not None
    assert row["current_mv_native"] is not None
    assert Decimal(row["previous_mv_native"]) == Decimal("50000")
    assert Decimal(row["current_mv_native"]) == Decimal("100000")
    assert Decimal(row["delta_native"]) == Decimal("50000")
    assert row["pendency_id"] == seed["pendency_a_id"]
    assert row["pendency_resolved"] is False


def test_mom_deltas_member_allowed(client, seed):
    r = client.get(
        f"/api/snapshots/{seed['cur_a_id']}/mom-deltas",
        headers=_h(seed["member_a"]),
    )
    assert r.status_code == 200, r.text


def test_mom_deltas_cross_workspace_returns_404(client, seed):
    """admin_b tenta ler snapshot do ws A → 404."""
    r = client.get(
        f"/api/snapshots/{seed['cur_a_id']}/mom-deltas",
        headers=_h(seed["admin_b"]),
    )
    assert r.status_code == 404


def test_mom_deltas_requires_auth(client, seed):
    r = client.get(f"/api/snapshots/{seed['cur_a_id']}/mom-deltas")
    assert r.status_code in (401, 403)  # HTTPBearer bloqueia sem header


# ── POST /snapshots/{id}/recheck-deltas ─────────────────────────────────────


def test_recheck_deltas_returns_empty_when_already_detected(client, seed):
    """detect_suspicious_deltas é idempotente — items com pendency existente
    são skipados. Chamar recheck após seed retorna lista vazia."""
    r = client.post(
        f"/api/snapshots/{seed['cur_a_id']}/recheck-deltas",
        headers=_h(seed["admin_a"]),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body, list)
    assert body == []


def test_recheck_deltas_creates_new_pendency_on_fresh_snapshot(client, seed):
    """Cria um snapshot NOVO (jun/26) via ORM sem pendencies, recheck deve
    detectar e criar 1."""
    db = TestSession()
    try:
        cur_b = db.get(PortfolioSnapshot, seed["cur_b_id"])
        # Fecha WS B (mai/26) pra virar previous CLOSED do jun/26.
        cur_b.status = SnapshotStatus.CLOSED
        cur_b.closed_at = datetime.now(timezone.utc)
        cur_b.closed_by = "seed"
        db.add(cur_b)

        new_snap = _make_snap(
            db, seed["ws_b_id"], date(2026, 6, 30), seed["asset_b_id"],
            Decimal("300000"),  # 100k → 300k = 200% delta
            status=SnapshotStatus.IN_REVIEW,
        )
        db.commit()
        new_snap_id = new_snap.id
    finally:
        db.close()

    r = client.post(
        f"/api/snapshots/{new_snap_id}/recheck-deltas",
        headers=_h(seed["admin_b"]),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body) == 1
    assert body[0]["reason"] == PendencyReason.SUSPICIOUS_DELTA.value
    assert body[0]["asset_id"] == seed["asset_b_id"]


def test_recheck_deltas_cross_workspace_returns_404(client, seed):
    r = client.post(
        f"/api/snapshots/{seed['cur_a_id']}/recheck-deltas",
        headers=_h(seed["admin_b"]),
    )
    assert r.status_code == 404


def test_recheck_deltas_sysadmin_pure_needs_workspace_id(client, seed):
    """Sysadmin puro (workspace_id=None) precisa passar ?workspace_id=X
    via _workspace_id dep — endpoint atual não expõe o query, então
    resulta em 400 na primeira chamada de _workspace_id."""
    r = client.post(
        f"/api/snapshots/{seed['cur_a_id']}/recheck-deltas",
        headers=_h(seed["sysadmin"]),
    )
    # _workspace_id levanta HTTPException(400) pra sysadmin puro sem ws.
    assert r.status_code == 400, r.text


# ── POST /snapshots/pendencies/{pid}/confirm-delta ──────────────────────────


def test_confirm_delta_marks_pendency_resolved(client, seed):
    """admin_a confirma a pendency SUSPICIOUS_DELTA plantada na seed."""
    r = client.post(
        f"/api/snapshots/pendencies/{seed['pendency_a_id']}/confirm-delta",
        json={"note": "cotas valorizaram — checado com extrato"},
        headers=_h(seed["admin_a"]),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == seed["pendency_a_id"]
    assert body["reason"] == PendencyReason.SUSPICIOUS_DELTA.value
    assert body["resolved_at"] is not None
    assert body["resolution_note"] == "cotas valorizaram — checado com extrato"


def test_confirm_delta_cross_workspace_returns_404(client, seed):
    """admin_b não pode confirmar pendency do ws A → 404."""
    r = client.post(
        f"/api/snapshots/pendencies/{seed['pendency_a_id']}/confirm-delta",
        json={"note": "hax"},
        headers=_h(seed["admin_b"]),
    )
    assert r.status_code == 404


def test_confirm_delta_unknown_pendency_returns_404(client, seed):
    r = client.post(
        f"/api/snapshots/pendencies/{uuid.uuid4()}/confirm-delta",
        json={"note": "x"},
        headers=_h(seed["admin_a"]),
    )
    assert r.status_code == 404


def test_confirm_delta_wrong_reason_returns_400(client, seed):
    """Pendency HISTORICAL_PRICE_REQUIRED não pode ser confirmada via
    confirm-delta — serviço rejeita com ValueError('not SUSPICIOUS_DELTA'),
    rota traduz pra 400."""
    from numis_geek.models.portfolio_snapshot import (
        PendencyAction,
        SnapshotPendency,
    )
    db = TestSession()
    try:
        # Novo asset no ws A pra respeitar UNIQUE(snapshot_id, asset_id) —
        # o asset_a_id já tem pendency SUSPICIOUS_DELTA no cur_a_id.
        now = datetime.now(timezone.utc)
        acc_id = db.query(Asset).filter(
            Asset.id == seed["asset_a_id"]
        ).one().account_id
        other_asset = Asset(
            id=str(uuid.uuid4()), workspace_id=seed["ws_a_id"],
            account_id=acc_id,
            asset_class=AssetClass.FUND, country="BR",
            name="Fundo secundário", ticker=None,
            currency=Currency.BRL,
            is_active=True, created_at=now, updated_at=now,
        )
        db.add(other_asset)
        db.flush()

        pen = SnapshotPendency(
            id=str(uuid.uuid4()),
            snapshot_id=seed["cur_a_id"],
            asset_id=other_asset.id,
            reason=PendencyReason.HISTORICAL_PRICE_REQUIRED,
            action_type=PendencyAction.EDIT_PRICE,
            detail=None,
            created_at=now,
        )
        db.add(pen)
        db.commit()
        wrong_pid = pen.id
    finally:
        db.close()

    r = client.post(
        f"/api/snapshots/pendencies/{wrong_pid}/confirm-delta",
        json={"note": "x"},
        headers=_h(seed["admin_a"]),
    )
    assert r.status_code == 400, r.text
    assert "SUSPICIOUS_DELTA" in r.json()["detail"]
