"""Matrix de authorization + edge cases pros routes de items de snapshot.

Cobre PATCH, DELETE, POST /items, POST /sync-items:
- Happy path (owner)
- Cross-workspace (member/admin de outro ws) → 404 (route usa
  `snap.workspace_id != ws_id` pra info-hiding; retorna 404, não 403)
- Sysadmin híbrido (workspace = ws do snapshot) → aceito
- PATCH quantity=3 em asset FUND (value-mode) → clamp automático pra 1
  (memory value_mode_qty_1_invariant)
"""
from __future__ import annotations

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
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.portfolio_snapshot import (
    PortfolioSnapshotItem, SnapshotStatus,
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
    """2 workspaces + 1 stock (cotado) + 1 fund (value-mode) com posição,
    snapshot IN_REVIEW pronto pra edição."""
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
    fund = Asset(
        id=str(uuid.uuid4()), workspace_id=ws_own.id, account_id=acc.id,
        asset_class=AssetClass.FUND, country="BR",
        name="Fundo X", ticker=None, currency=Currency.BRL,
        current_price=Decimal("1000"), price_source=None,
        is_active=True, created_at=now, updated_at=now,
    )
    db.add_all([ws_own, ws_other, fi, acc, ptax, stock, fund]); db.flush()
    for asset_id, qty, up in [(stock.id, "100", "30"), (fund.id, "1", "1000")]:
        db.add(AssetMovement(
            id=str(uuid.uuid4()), workspace_id=ws_own.id, asset_id=asset_id,
            type=AssetMovementType.BUY, event_date=date(2026, 1, 10),
            quantity=Decimal(qty), unit_price=Decimal(up),
            gross_amount=Decimal(qty) * Decimal(up),
            net_amount=Decimal(qty) * Decimal(up),
            currency=Currency.BRL, fx_rate=Decimal("1"),
            is_active=True, created_at=now, updated_at=now,
        ))
    db.flush()

    tag = uuid.uuid4().hex[:6]
    _mk_user(db, ws_own.id, UserRole.admin, f"admin_own_{tag}@t.com")
    _mk_user(db, ws_own.id, UserRole.member, f"member_own_{tag}@t.com")
    _mk_user(db, ws_other.id, UserRole.admin, f"admin_other_{tag}@t.com")
    _mk_user(db, ws_other.id, UserRole.member, f"member_other_{tag}@t.com")
    _mk_user(db, ws_own.id, UserRole.sysadmin, f"sys_{tag}@t.internal")
    db.flush()

    result = create_snapshot(
        db, workspace_id=ws_own.id, period_end=period,
        initial_status=SnapshotStatus.IN_REVIEW,
    )
    db.flush()
    return {
        "ws_own_id": ws_own.id,
        "snapshot_id": result.snapshot_id,
        "stock_id": stock.id, "fund_id": fund.id, "acc_id": acc.id,
        "tok_own": AuthService(db).login(f"admin_own_{tag}@t.com", "pw"),
        "tok_other_admin": AuthService(db).login(f"admin_other_{tag}@t.com", "pw"),
        "tok_other_member": AuthService(db).login(f"member_other_{tag}@t.com", "pw"),
        "tok_sys": AuthService(db).login(f"sys_{tag}@t.internal", "pw"),
    }


def _hdr(tok):
    return {"Authorization": f"Bearer {tok}"}


def _new_cash_asset(db, ws_id, acc_id, suffix):
    now = datetime.now(timezone.utc)
    a = Asset(
        id=str(uuid.uuid4()), workspace_id=ws_id, account_id=acc_id,
        asset_class=AssetClass.CASH, country="BR",
        name=f"Saldo {suffix}", ticker=None, currency=Currency.BRL,
        is_active=True, created_at=now, updated_at=now,
    )
    db.add(a); db.flush()
    return a.id


# ═════════════════════════════════════════════════════════════════════════
# PATCH /snapshots/{id}/items/{asset_id}
# ═════════════════════════════════════════════════════════════════════════


def test_patch_item_happy(db, client):
    s = _seed(db)
    r = client.patch(
        f"/api/snapshots/{s['snapshot_id']}/items/{s['stock_id']}",
        json={"price": "42.00", "value_mode": "unit"},
        headers=_hdr(s["tok_own"]),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["asset_id"] == s["stock_id"]
    # stock qty=100 × 42 = 4200
    assert Decimal(body["market_value_brl"]) == Decimal("4200")


@pytest.mark.parametrize("tok_key", ["tok_other_admin", "tok_other_member"])
def test_patch_item_cross_workspace_blocked(db, client, tok_key):
    s = _seed(db)
    r = client.patch(
        f"/api/snapshots/{s['snapshot_id']}/items/{s['stock_id']}",
        json={"price": "42.00", "value_mode": "unit"},
        headers=_hdr(s[tok_key]),
    )
    # Cross-workspace vaza como 404 (info-hiding do route).
    assert r.status_code == 404, r.text


def test_patch_item_sysadmin_accepted(db, client):
    s = _seed(db)
    r = client.patch(
        f"/api/snapshots/{s['snapshot_id']}/items/{s['stock_id']}",
        json={"price": "50.00", "value_mode": "unit"},
        headers=_hdr(s["tok_sys"]),
    )
    assert r.status_code == 200, r.text


def test_patch_value_mode_quantity_clamps_to_1(db, client):
    """Invariante value_mode_qty_1_invariant: FUND deve ficar com qty=1
    mesmo quando o user manda quantity=3."""
    s = _seed(db)
    r = client.patch(
        f"/api/snapshots/{s['snapshot_id']}/items/{s['fund_id']}",
        json={"price": "1200.00", "value_mode": "unit", "quantity": "3"},
        headers=_hdr(s["tok_own"]),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert Decimal(body["quantity"]) == Decimal("1"), (
        f"value-mode FUND deveria ter qty clampada pra 1, veio {body['quantity']}"
    )
    # Com clamp + unit mode, mv = 1 × 1200 = 1200
    assert Decimal(body["market_value_brl"]) == Decimal("1200")


# ═════════════════════════════════════════════════════════════════════════
# DELETE /snapshots/{id}/items/{asset_id}
# ═════════════════════════════════════════════════════════════════════════


def test_delete_item_happy(db, client):
    s = _seed(db)
    r = client.delete(
        f"/api/snapshots/{s['snapshot_id']}/items/{s['stock_id']}",
        headers=_hdr(s["tok_own"]),
    )
    assert r.status_code == 204, r.text
    count = db.query(PortfolioSnapshotItem).filter_by(
        snapshot_id=s["snapshot_id"], asset_id=s["stock_id"],
    ).count()
    assert count == 0


def test_delete_item_cross_workspace_blocked(db, client):
    s = _seed(db)
    r = client.delete(
        f"/api/snapshots/{s['snapshot_id']}/items/{s['stock_id']}",
        headers=_hdr(s["tok_other_admin"]),
    )
    assert r.status_code == 404, r.text


def test_delete_item_sysadmin_accepted(db, client):
    s = _seed(db)
    r = client.delete(
        f"/api/snapshots/{s['snapshot_id']}/items/{s['stock_id']}",
        headers=_hdr(s["tok_sys"]),
    )
    assert r.status_code == 204, r.text


# ═════════════════════════════════════════════════════════════════════════
# POST /snapshots/{id}/items
# ═════════════════════════════════════════════════════════════════════════


def test_post_item_happy(db, client):
    s = _seed(db)
    new_id = _new_cash_asset(db, s["ws_own_id"], s["acc_id"], "A")
    r = client.post(
        f"/api/snapshots/{s['snapshot_id']}/items",
        json={"asset_id": new_id},
        headers=_hdr(s["tok_own"]),
    )
    assert r.status_code == 201, r.text
    assert r.json()["asset_id"] == new_id


def test_post_item_cross_workspace_blocked(db, client):
    s = _seed(db)
    new_id = _new_cash_asset(db, s["ws_own_id"], s["acc_id"], "B")
    r = client.post(
        f"/api/snapshots/{s['snapshot_id']}/items",
        json={"asset_id": new_id},
        headers=_hdr(s["tok_other_member"]),
    )
    assert r.status_code == 404, r.text


def test_post_item_sysadmin_accepted(db, client):
    s = _seed(db)
    new_id = _new_cash_asset(db, s["ws_own_id"], s["acc_id"], "C")
    r = client.post(
        f"/api/snapshots/{s['snapshot_id']}/items",
        json={"asset_id": new_id},
        headers=_hdr(s["tok_sys"]),
    )
    assert r.status_code == 201, r.text


# ═════════════════════════════════════════════════════════════════════════
# POST /snapshots/{id}/sync-items
# ═════════════════════════════════════════════════════════════════════════


def test_sync_items_happy(db, client):
    s = _seed(db)
    # Cria CASH asset extra sem item pré-existente → sync deve incluí-lo.
    _new_cash_asset(db, s["ws_own_id"], s["acc_id"], "Sync")
    r = client.post(
        f"/api/snapshots/{s['snapshot_id']}/sync-items",
        headers=_hdr(s["tok_own"]),
    )
    assert r.status_code == 200, r.text
    assert r.json()["items_added"] >= 1


def test_sync_items_cross_workspace_blocked(db, client):
    s = _seed(db)
    r = client.post(
        f"/api/snapshots/{s['snapshot_id']}/sync-items",
        headers=_hdr(s["tok_other_admin"]),
    )
    assert r.status_code == 404, r.text


def test_sync_items_sysadmin_accepted(db, client):
    s = _seed(db)
    r = client.post(
        f"/api/snapshots/{s['snapshot_id']}/sync-items",
        headers=_hdr(s["tok_sys"]),
    )
    assert r.status_code == 200, r.text
