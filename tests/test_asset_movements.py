import uuid
from datetime import date, datetime, timedelta, timezone

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
from numis_geek.models.asset import Asset, AssetClass
from numis_geek.models.account import Account, AccountType, Currency
from numis_geek.models.audit_log import AuditLog
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.user import User, UserRole
from numis_geek.services.auth import AuthService
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


@pytest.fixture(scope="module")
def seed():
    db = TestSession()
    ws_a = WorkspaceService(db).create("Lan WS A")
    ws_b = WorkspaceService(db).create("Lan WS B")

    admin_a = UserService(db).create(ws_a.id, "lan_admin_a@test.com", "adminpass", UserRole.admin)
    member_a = UserService(db).create(ws_a.id, "lan_member_a@test.com", "memberpass", UserRole.member)
    admin_b = UserService(db).create(ws_b.id, "lan_admin_b@test.com", "adminpass", UserRole.admin)

    now = datetime.now(timezone.utc)
    sysadmin = User(
        id=str(uuid.uuid4()),
        workspace_id=None,
        email="lan_sysadmin@test.internal",
        name="SysAdmin",
        password_hash=bcrypt.hashpw(b"syspass", bcrypt.gensalt()).decode(),
        role=UserRole.sysadmin,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(sysadmin)

    fi = FinancialInstitution(
        id=str(uuid.uuid4()),
        long_name="XP Investimentos",
        short_name="XP",
        logo_slug="xp",
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(fi)

    # Spec 10: every asset needs an investment account per workspace
    account_a = Account(
        id=str(uuid.uuid4()), workspace_id=ws_a.id, financial_institution_id=fi.id,
        name="XP Inv A", account_type=AccountType.investment, currency=Currency.BRL,
        is_active=True, created_at=now, updated_at=now,
    )
    account_b = Account(
        id=str(uuid.uuid4()), workspace_id=ws_b.id, financial_institution_id=fi.id,
        name="XP Inv B", account_type=AccountType.investment, currency=Currency.BRL,
        is_active=True, created_at=now, updated_at=now,
    )
    db.add_all([account_a, account_b])
    db.flush()

    # One asset per workspace.
    asset_a = Asset(
        id=str(uuid.uuid4()),
        workspace_id=ws_a.id,
        account_id=account_a.id,
        asset_class=AssetClass.STOCK,
        country="BR",
        name="Petrobras PN",
        ticker="PETR4",
        currency=Currency.BRL,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    asset_a_us = Asset(
        id=str(uuid.uuid4()),
        workspace_id=ws_a.id,
        account_id=account_a.id,
        asset_class=AssetClass.STOCK,
        country="BR",
        name="Apple",
        ticker="AAPL",
        currency=Currency.USD,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    asset_b = Asset(
        id=str(uuid.uuid4()),
        workspace_id=ws_b.id,
        account_id=account_b.id,
        asset_class=AssetClass.STOCK,
        country="BR",
        name="Itaú PN",
        ticker="ITUB4",
        currency=Currency.BRL,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add_all([asset_a, asset_a_us, asset_b])
    db.commit()

    db.refresh(ws_a); db.refresh(ws_b); db.refresh(fi)
    db.refresh(asset_a); db.refresh(asset_a_us); db.refresh(asset_b)

    # Capture all primary keys BEFORE closing the session — once closed,
    # accessing attributes on a detached instance triggers a lazy refresh.
    out = {
        "ws_a": ws_a.id,
        "ws_b": ws_b.id,
        "fi_id": fi.id,
        "asset_a": asset_a.id,
        "asset_a_us": asset_a_us.id,
        "asset_b": asset_b.id,
    }

    out["admin_token_a"] = AuthService(db).login("lan_admin_a@test.com", "adminpass")
    out["member_token_a"] = AuthService(db).login("lan_member_a@test.com", "memberpass")
    out["admin_token_b"] = AuthService(db).login("lan_admin_b@test.com", "adminpass")
    out["sysadmin_token"] = AuthService(db).login("lan_sysadmin@test.internal", "syspass")
    db.close()
    return out


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def _today_iso():
    return date.today().isoformat()


# ── Tests: list / empty ──────────────────────────────────────────────────────

def test_list_lancamentos_empty(client, seed):
    r = client.get("/asset-movements", headers=auth(seed["admin_token_a"]))
    assert r.status_code == 200
    body = r.json()
    assert body["items"] == []
    assert body["total"] == 0


# ── Tests: create per type ──────────────────────────────────────────────────

def test_create_compra(client, seed):
    r = client.post("/asset-movements", json={
        "asset_id": seed["asset_a"],
        "type": "BUY",
        "event_date": _today_iso(),
        "quantity": 100,
        "unit_price": 30.50,
        "fee": 1.50,
        "tax": 0.50,
    }, headers=auth(seed["admin_token_a"]))
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["type"] == 'BUY'
    assert data["type_label"] == "Compra"
    assert data["quantity"] == 100.0
    assert data["unit_price"] == 30.5
    # gross = 100 * 30.5 = 3050; net = gross + fee + tax = 3050 + 1.5 + 0.5 = 3052.0
    assert data["gross_amount"] == 3050.0
    assert data["net_amount"] == 3052.0
    assert data["currency"] == "BRL"  # defaulted from asset
    assert data["fx_rate"] == 1.0


def test_create_venda(client, seed):
    r = client.post("/asset-movements", json={
        "asset_id": seed["asset_a"],
        "type": "SELL",
        "event_date": _today_iso(),
        "quantity": 50,
        "unit_price": 32.00,
        "fee": 2.00,
        "tax": 1.00,
    }, headers=auth(seed["admin_token_a"]))
    assert r.status_code == 201, r.text
    data = r.json()
    # gross = 50 * 32 = 1600; net = gross - fee - tax = 1600 - 2 - 1 = 1597
    assert data["gross_amount"] == 1600.0
    assert data["net_amount"] == 1597.0


def test_create_bonificacao(client, seed):
    r = client.post("/asset-movements", json={
        "asset_id": seed["asset_a"],
        "type": "BONUS",
        "event_date": _today_iso(),
        "quantity": 10,
    }, headers=auth(seed["admin_token_a"]))
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["quantity"] == 10.0
    assert data["unit_price"] is None
    assert data["gross_amount"] == 0.0
    assert data["net_amount"] == 0.0


def test_create_come_cotas(client, seed):
    r = client.post("/asset-movements", json={
        "asset_id": seed["asset_a"],
        "type": "COME_COTAS",
        "event_date": _today_iso(),
        "gross_amount": 10.00,
        "tax": 7.50,
    }, headers=auth(seed["admin_token_a"]))
    assert r.status_code == 201, r.text
    data = r.json()
    # net = -tax
    assert data["net_amount"] == -7.5


# ── Tests: validation rules ────────────────────────────────────────────────

def test_compra_requires_quantity(client, seed):
    r = client.post("/asset-movements", json={
        "asset_id": seed["asset_a"],
        "type": "BUY",
        "event_date": _today_iso(),
        "unit_price": 30.0,
    }, headers=auth(seed["admin_token_a"]))
    assert r.status_code == 422


def test_compra_requires_unit_price(client, seed):
    r = client.post("/asset-movements", json={
        "asset_id": seed["asset_a"],
        "type": "BUY",
        "event_date": _today_iso(),
        "quantity": 100,
    }, headers=auth(seed["admin_token_a"]))
    assert r.status_code == 422


def test_bonificacao_forbids_unit_price(client, seed):
    r = client.post("/asset-movements", json={
        "asset_id": seed["asset_a"],
        "type": "BONUS",
        "event_date": _today_iso(),
        "quantity": 10,
        "unit_price": 5.0,
    }, headers=auth(seed["admin_token_a"]))
    assert r.status_code == 422


def test_event_date_no_future(client, seed):
    future = (date.today() + timedelta(days=1)).isoformat()
    r = client.post("/asset-movements", json={
        "asset_id": seed["asset_a"],
        "type": "BUY",
        "event_date": future,
        "quantity": 1,
        "unit_price": 1.0,
    }, headers=auth(seed["admin_token_a"]))
    assert r.status_code == 422


def test_come_cotas_requires_tax(client, seed):
    r = client.post("/asset-movements", json={
        "asset_id": seed["asset_a"],
        "type": "COME_COTAS",
        "event_date": _today_iso(),
        "gross_amount": 5.0,
    }, headers=auth(seed["admin_token_a"]))
    assert r.status_code == 422


def test_compra_quantity_must_be_positive(client, seed):
    r = client.post("/asset-movements", json={
        "asset_id": seed["asset_a"],
        "type": "BUY",
        "event_date": _today_iso(),
        "quantity": 0,
        "unit_price": 10.0,
    }, headers=auth(seed["admin_token_a"]))
    assert r.status_code == 422


def test_member_cannot_read_other_workspace_lancamento(client, seed):
    r_create = client.post("/asset-movements", json={
        "asset_id": seed["asset_b"],
        "type": "BUY",
        "event_date": _today_iso(),
        "quantity": 5,
        "unit_price": 10.0,
    }, headers=auth(seed["admin_token_b"]))
    assert r_create.status_code == 201, r_create.text
    lan_id_b = r_create.json()["id"]

    r = client.get(f"/asset-movements/{lan_id_b}", headers=auth(seed["member_token_a"]))
    assert r.status_code == 404

    # And listing in WS A doesn't show it
    r2 = client.get("/asset-movements", headers=auth(seed["member_token_a"]))
    assert r2.status_code == 200
    assert lan_id_b not in [l["id"] for l in r2.json()["items"]]


def test_cross_workspace_asset_rejected(client, seed):
    # admin_a tries to create a lançamento for an asset in WS B
    r = client.post("/asset-movements", json={
        "asset_id": seed["asset_b"],
        "type": "BUY",
        "event_date": _today_iso(),
        "quantity": 1,
        "unit_price": 1.0,
    }, headers=auth(seed["admin_token_a"]))
    assert r.status_code == 404


# ── Tests: sysadmin cross-workspace ────────────────────────────────────────

def test_sysadmin_lists_across_workspaces(client, seed):
    r = client.get("/asset-movements", headers=auth(seed["sysadmin_token"]))
    assert r.status_code == 200
    items = r.json()["items"]
    workspace_ids = {l["workspace_id"] for l in items}
    assert seed["ws_a"] in workspace_ids
    assert seed["ws_b"] in workspace_ids


def test_sysadmin_create_requires_workspace(client, seed):
    r = client.post("/asset-movements", json={
        "asset_id": seed["asset_a"],
        "type": "BUY",
        "event_date": _today_iso(),
        "quantity": 1,
        "unit_price": 1.0,
    }, headers=auth(seed["sysadmin_token"]))
    assert r.status_code == 400


def test_sysadmin_creates_in_target_workspace(client, seed):
    r = client.post("/asset-movements", json={
        "asset_id": seed["asset_b"],
        "type": "BUY",
        "event_date": _today_iso(),
        "quantity": 7,
        "unit_price": 12.0,
        "workspace_id": seed["ws_b"],
    }, headers=auth(seed["sysadmin_token"]))
    assert r.status_code == 201, r.text
    assert r.json()["workspace_id"] == seed["ws_b"]


# ── Tests: filters ─────────────────────────────────────────────────────────

def test_filter_by_asset(client, seed):
    r = client.get(
        f"/asset-movements?asset_id={seed['asset_a']}",
        headers=auth(seed["admin_token_a"]),
    )
    assert r.status_code == 200
    items = r.json()["items"]
    assert all(l["asset_id"] == seed["asset_a"] for l in items)
    assert len(items) >= 1


def test_filter_by_type(client, seed):
    r = client.get(
        "/asset-movements?type=BUY",
        headers=auth(seed["admin_token_a"]),
    )
    assert r.status_code == 200
    items = r.json()["items"]
    assert all(l["type"] == "BUY" for l in items)


def test_pagination_max_200(client, seed):
    r = client.get("/asset-movements?page_size=500", headers=auth(seed["admin_token_a"]))
    assert r.status_code == 422  # ge/le validation


# ── Tests: update / deactivate ─────────────────────────────────────────────

def test_update_lancamento(client, seed):
    r = client.post("/asset-movements", json={
        "asset_id": seed["asset_a"],
        "type": "BUY",
        "event_date": _today_iso(),
        "quantity": 10,
        "unit_price": 20.0,
    }, headers=auth(seed["admin_token_a"]))
    lan_id = r.json()["id"]

    r2 = client.put(f"/asset-movements/{lan_id}", json={
        "asset_id": seed["asset_a"],
        "type": "BUY",
        "event_date": _today_iso(),
        "quantity": 15,
        "unit_price": 21.0,
        "notes": "edited",
    }, headers=auth(seed["admin_token_a"]))
    assert r2.status_code == 200
    body = r2.json()
    assert body["quantity"] == 15.0
    assert body["unit_price"] == 21.0
    assert body["notes"] == "edited"
    assert body["gross_amount"] == 15 * 21.0


def test_deactivate_lancamento(client, seed):
    r = client.post("/asset-movements", json={
        "asset_id": seed["asset_a"],
        "type": "BUY",
        "event_date": _today_iso(),
        "quantity": 1,
        "unit_price": 1.0,
    }, headers=auth(seed["admin_token_a"]))
    lan_id = r.json()["id"]

    r2 = client.put(f"/asset-movements/{lan_id}/deactivate", headers=auth(seed["admin_token_a"]))
    assert r2.status_code == 200
    assert r2.json()["is_active"] is False

    r3 = client.get("/asset-movements", headers=auth(seed["admin_token_a"]))
    assert lan_id not in [l["id"] for l in r3.json()["items"]]

    r4 = client.get("/asset-movements?include_inactive=true", headers=auth(seed["admin_token_a"]))
    assert lan_id in [l["id"] for l in r4.json()["items"]]


# ── Tests: audit log ───────────────────────────────────────────────────────

def test_audit_log_created_for_lancamento_mutations(client, seed):
    r = client.post("/asset-movements", json={
        "asset_id": seed["asset_a"],
        "type": "BUY",
        "event_date": _today_iso(),
        "quantity": 1,
        "unit_price": 1.0,
    }, headers=auth(seed["admin_token_a"]))
    lan_id = r.json()["id"]

    client.put(f"/asset-movements/{lan_id}", json={
        "asset_id": seed["asset_a"],
        "type": "BUY",
        "event_date": _today_iso(),
        "quantity": 2,
        "unit_price": 1.0,
    }, headers=auth(seed["admin_token_a"]))
    client.put(f"/asset-movements/{lan_id}/deactivate", headers=auth(seed["admin_token_a"]))

    db = TestSession()
    try:
        actions = [
            row.action for row in
            db.query(AuditLog).filter(AuditLog.resource_id == lan_id).all()
        ]
    finally:
        db.close()
    assert "asset_movement.created" in actions
    assert "asset_movement.updated" in actions
    assert "asset_movement.deactivated" in actions


# ── Tests: USD currency / fx_rate ──────────────────────────────────────────

def test_usd_asset_defaults_currency_usd(client, seed):
    r = client.post("/asset-movements", json={
        "asset_id": seed["asset_a_us"],
        "type": "BUY",
        "event_date": _today_iso(),
        "quantity": 5,
        "unit_price": 200.0,
        "fx_rate": 5.5,
    }, headers=auth(seed["admin_token_a"]))
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["currency"] == "USD"
    assert data["fx_rate"] == 5.5


# ── Tests: inactive asset is now allowed (with FE warning safety net) ──────

def test_can_create_lancamento_against_inactive_asset(client, seed):
    """Importers backfill historical entries against deactivated assets;
    the API does not reject this path. The UI shows a confirmation."""
    # Deactivate asset_a directly via DB.
    db = TestSession()
    try:
        asset = db.get(Asset, seed["asset_a"])
        asset.is_active = False
        db.commit()
    finally:
        db.close()

    r = client.post("/asset-movements", json={
        "asset_id": seed["asset_a"],
        "type": "BUY",
        "event_date": _today_iso(),
        "quantity": 1,
        "unit_price": 25.0,
    }, headers=auth(seed["admin_token_a"]))
    assert r.status_code == 201, r.text

    # Reactivate so other tests aren't affected.
    db = TestSession()
    try:
        asset = db.get(Asset, seed["asset_a"])
        asset.is_active = True
        db.commit()
    finally:
        db.close()


# ── Tests: income types must use the asset's currency ─────────────────────

def test_bonificacao_default_gross_is_zero(client, seed):
    r = client.post("/asset-movements", json={
        "asset_id": seed["asset_a"],
        "type": "BONUS",
        "event_date": _today_iso(),
        "quantity": 5,
    }, headers=auth(seed["admin_token_a"]))
    assert r.status_code == 201, r.text
    assert r.json()["gross_amount"] == 0.0


def test_bonificacao_accepts_override_gross_amount(client, seed):
    r = client.post("/asset-movements", json={
        "asset_id": seed["asset_a"],
        "type": "BONUS",
        "event_date": _today_iso(),
        "quantity": 5,
        "gross_amount": 150.0,  # FMV declared by company (5 shares × R$30 nominal)
    }, headers=auth(seed["admin_token_a"]))
    assert r.status_code == 201, r.text
    assert r.json()["gross_amount"] == 150.0


# ── Tests: RESGATE_TOTAL (Spec 07c) ───────────────────────────────────────────

def test_create_resgate_total(client, seed):
    """RESGATE_TOTAL is the 9th lançamento type; validation matches VENDA."""
    r = client.post("/asset-movements", json={
        "asset_id": seed["asset_a"],
        "type": "FULL_REDEMPTION",
        "event_date": _today_iso(),
        "quantity": 100,
        "unit_price": 25.00,
        "fee": 1.00,
        "tax": 0.50,
    }, headers=auth(seed["admin_token_a"]))
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["type"] == 'FULL_REDEMPTION'
    assert data["type_label"] == "Resgate Total"
    # Same math as VENDA: gross = qty * price = 2500; net = gross - fee - tax = 2498.5
    assert data["gross_amount"] == 2500.0
    assert data["net_amount"] == 2498.5


def test_resgate_total_persists_external_fields(client, seed):
    r = client.post("/asset-movements", json={
        "asset_id": seed["asset_a"],
        "type": "FULL_REDEMPTION",
        "event_date": _today_iso(),
        "quantity": 50,
        "unit_price": 10.00,
        "external_id": "https://www.notion.so/some-row",
        "external_source": "NOTION",
        "nota_negociacao_number": "12345",
    }, headers=auth(seed["admin_token_a"]))
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["external_id"] == "https://www.notion.so/some-row"
    assert data["external_source"] == "NOTION"
    assert data["nota_negociacao_number"] == "12345"


# ── Tests: Non-cotado relaxation (CDB) ────────────────────────────────────────

@pytest.fixture(scope="module")
def cdb_asset(seed):
    db = TestSession()
    fi = db.query(FinancialInstitution).first()
    account = db.query(Account).first()
    now = datetime.now(timezone.utc)
    cdb = Asset(
        id=str(uuid.uuid4()),
        workspace_id=seed["ws_a"],
        account_id=account.id,
        asset_class=AssetClass.FIXED_INCOME,
        country="BR",
        name="CDB BTG 110% CDI 2028",
        ticker=None,
        currency=Currency.BRL,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(cdb)
    db.commit()
    cdb_id = cdb.id
    db.close()
    return cdb_id


def test_compra_cdb_with_gross_only_succeeds(client, seed, cdb_asset):
    """A CDB COMPRA with only gross_amount (no qty/unit_price) is valid."""
    r = client.post("/asset-movements", json={
        "asset_id": cdb_asset,
        "type": "BUY",
        "event_date": _today_iso(),
        "gross_amount": 5000.00,
    }, headers=auth(seed["admin_token_a"]))
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["quantity"] is None
    assert data["unit_price"] is None
    assert data["gross_amount"] == 5000.0
    # net = gross + fee + tax = 5000 (none provided → 0)
    assert data["net_amount"] == 5000.0


def test_compra_with_neither_qty_nor_gross_rejected(client, seed):
    """A COMPRA with neither (qty+price) nor gross_amount must 422."""
    r = client.post("/asset-movements", json={
        "asset_id": seed["asset_a"],
        "type": "BUY",
        "event_date": _today_iso(),
        # no quantity, no unit_price, no gross_amount
    }, headers=auth(seed["admin_token_a"]))
    assert r.status_code == 422


def test_compra_cotado_with_gross_only_accepted(client, seed):
    """A cotado COMPRA may use gross_amount-only.

    Real-world data has cases like Brazilian Funds tracked as 'Não Cotado'
    even though our enum classifies them as cotado, plus dust crypto
    transfers without per-unit prices. The Pydantic-level check (qty+price
    OR gross) is the only gate.
    """
    r = client.post("/asset-movements", json={
        "asset_id": seed["asset_a"],  # STOCK_BR
        "type": "BUY",
        "event_date": _today_iso(),
        "gross_amount": 1000.00,
        # no qty, no unit_price
    }, headers=auth(seed["admin_token_a"]))
    assert r.status_code == 201, r.text
    assert r.json()["gross_amount"] == 1000.0
    assert r.json()["quantity"] is None
    assert r.json()["unit_price"] is None
