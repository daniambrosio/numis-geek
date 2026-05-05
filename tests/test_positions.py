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
from numis_geek.models.asset import Asset, AssetClass
from numis_geek.models.account import Currency
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.lancamento import Lancamento, LancamentoType
from numis_geek.models.user import User, UserRole
from numis_geek.services.auth import AuthService
from numis_geek.services.positions import compute_position
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
    ws = WorkspaceService(db).create("Pos WS")
    admin = UserService(db).create(ws.id, "pos_admin@test.com", "adminpass", UserRole.admin)

    now = datetime.now(timezone.utc)
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

    # BRL stock asset for the qty / avg-cost test
    asset_brl = Asset(
        id=str(uuid.uuid4()),
        workspace_id=ws.id,
        financial_institution_id=fi.id,
        asset_class=AssetClass.STOCK_BR,
        name="Petrobras PN",
        ticker="PETR4",
        currency=Currency.BRL,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    # USD asset for the fx_rate accumulation test
    asset_usd = Asset(
        id=str(uuid.uuid4()),
        workspace_id=ws.id,
        financial_institution_id=fi.id,
        asset_class=AssetClass.STOCK_US,
        name="Apple",
        ticker="AAPL",
        currency=Currency.USD,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add_all([asset_brl, asset_usd])
    db.commit()
    db.refresh(ws); db.refresh(fi); db.refresh(asset_brl); db.refresh(asset_usd)

    out = {
        "ws_id": ws.id,
        "fi_id": fi.id,
        "asset_brl": asset_brl.id,
        "asset_usd": asset_usd.id,
    }
    out["admin_token"] = AuthService(db).login("pos_admin@test.com", "adminpass")
    db.close()
    return out


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def _today_iso():
    return date.today().isoformat()


# ── Hand-calculated scenario: 100 COMPRA + 50 BONIFICACAO + 80 VENDA ────────

def test_position_quantity_held_with_compra_bonificacao_venda(client, seed):
    today = _today_iso()
    # 100 @ 30
    client.post("/lancamentos", json={
        "asset_id": seed["asset_brl"],
        "type": "COMPRA",
        "event_date": today,
        "quantity": 100,
        "unit_price": 30.00,
    }, headers=auth(seed["admin_token"]))
    # +50 BONIFICACAO (free shares)
    client.post("/lancamentos", json={
        "asset_id": seed["asset_brl"],
        "type": "BONIFICACAO",
        "event_date": today,
        "quantity": 50,
    }, headers=auth(seed["admin_token"]))
    # -80 VENDA @ 35
    client.post("/lancamentos", json={
        "asset_id": seed["asset_brl"],
        "type": "VENDA",
        "event_date": today,
        "quantity": 80,
        "unit_price": 35.00,
    }, headers=auth(seed["admin_token"]))

    r = client.get(f"/assets/{seed['asset_brl']}/position", headers=auth(seed["admin_token"]))
    assert r.status_code == 200, r.text
    pos = r.json()
    # 100 + 50 - 80 = 70
    assert pos["quantity_held"] == 70.0
    # Avg cost = (100 * 30) / 100 = 30 (BONIFICACAO doesn't affect basis;
    # VENDA does not reduce basis qty either in our spec — it only reduces holdings).
    assert pos["average_cost"] == 30.0
    assert pos["currency"] == "BRL"
    # BRL currency, fx_rate = 1 → avg_cost_brl == avg_cost
    assert pos["average_cost_brl"] == 30.0
    # total_invested_brl = 70 * 30 = 2100
    assert pos["total_invested_brl"] == 2100.0


# ── Weighted average cost ──────────────────────────────────────────────────

def test_weighted_average_cost(client, seed):
    # New asset to keep things isolated
    db = TestSession()
    fi = db.query(FinancialInstitution).first()
    now = datetime.now(timezone.utc)
    a = Asset(
        id=str(uuid.uuid4()),
        workspace_id=seed["ws_id"],
        financial_institution_id=fi.id,
        asset_class=AssetClass.STOCK_BR,
        name="Itaú",
        ticker="ITUB4",
        currency=Currency.BRL,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(a); db.commit(); db.refresh(a)
    asset_id = a.id
    db.close()

    today = _today_iso()
    # 100 @ 10, 100 @ 20 → weighted avg = (100*10 + 100*20) / 200 = 15
    client.post("/lancamentos", json={
        "asset_id": asset_id, "type": "COMPRA", "event_date": today,
        "quantity": 100, "unit_price": 10.0,
    }, headers=auth(seed["admin_token"]))
    client.post("/lancamentos", json={
        "asset_id": asset_id, "type": "COMPRA", "event_date": today,
        "quantity": 100, "unit_price": 20.0,
    }, headers=auth(seed["admin_token"]))

    r = client.get(f"/assets/{asset_id}/position", headers=auth(seed["admin_token"]))
    pos = r.json()
    assert pos["quantity_held"] == 200.0
    assert pos["average_cost"] == 15.0


# ── DIVIDENDO accumulation in BRL via fx_rate ──────────────────────────────

def test_dividendo_accumulation_with_fx_rate(client, seed):
    today = _today_iso()
    # USD asset: $10 dividendo at fx_rate 5.0 → 50 BRL; $20 dividendo at fx 5.5 → 110 BRL.
    # Total received BRL = 160.
    client.post("/lancamentos", json={
        "asset_id": seed["asset_usd"],
        "type": "DIVIDENDO",
        "event_date": today,
        "gross_amount": 10.00,
        "currency": "USD",
        "fx_rate": 5.0,
    }, headers=auth(seed["admin_token"]))
    client.post("/lancamentos", json={
        "asset_id": seed["asset_usd"],
        "type": "DIVIDENDO",
        "event_date": today,
        "gross_amount": 20.00,
        "currency": "USD",
        "fx_rate": 5.5,
    }, headers=auth(seed["admin_token"]))

    r = client.get(f"/assets/{seed['asset_usd']}/position", headers=auth(seed["admin_token"]))
    pos = r.json()
    assert pos["currency"] == "USD"
    # 10*5 + 20*5.5 = 50 + 110 = 160
    assert pos["total_received_brl"] == 160.0


# ── /assets/{id}/lancamentos convenience endpoint ──────────────────────────

def test_assets_lancamentos_endpoint(client, seed):
    r = client.get(
        f"/assets/{seed['asset_brl']}/lancamentos",
        headers=auth(seed["admin_token"]),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "items" in body
    assert all(l["asset_id"] == seed["asset_brl"] for l in body["items"])


# ── Direct service call for completeness ───────────────────────────────────

def test_compute_position_service_direct(seed):
    db = TestSession()
    try:
        pos = compute_position(db, seed["asset_brl"])
        assert pos["currency"] == "BRL"
        assert pos["quantity_held"] == Decimal("70")
        assert pos["average_cost"] == Decimal("30")
    finally:
        db.close()


# ── Empty asset returns zero position ──────────────────────────────────────

def test_empty_asset_position(client, seed):
    # Create a brand-new asset with no lançamentos
    db = TestSession()
    fi = db.query(FinancialInstitution).first()
    now = datetime.now(timezone.utc)
    a = Asset(
        id=str(uuid.uuid4()),
        workspace_id=seed["ws_id"],
        financial_institution_id=fi.id,
        asset_class=AssetClass.STOCK_BR,
        name="Zero Asset",
        ticker="ZERO3",
        currency=Currency.BRL,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(a); db.commit(); db.refresh(a)
    asset_id = a.id
    db.close()

    r = client.get(f"/assets/{asset_id}/position", headers=auth(seed["admin_token"]))
    assert r.status_code == 200
    pos = r.json()
    assert pos["quantity_held"] == 0.0
    assert pos["average_cost"] == 0.0
    assert pos["total_received_brl"] == 0.0


# ── PRIO3 scenario: cost-basis reset on RESGATE_TOTAL ─────────────────────────

def test_resgate_total_resets_cost_basis(client, seed):
    """COMPRA 100 @ 25 → RESGATE_TOTAL (full close) → COMPRA 50 @ 32 must
    yield avg_cost = 32 (not a weighted blend with the old 25)."""
    db = TestSession()
    fi = db.query(FinancialInstitution).first()
    now = datetime.now(timezone.utc)
    a = Asset(
        id=str(uuid.uuid4()),
        workspace_id=seed["ws_id"],
        financial_institution_id=fi.id,
        asset_class=AssetClass.STOCK_BR,
        name="PRIO Petroleo",
        ticker="PRIO3",
        currency=Currency.BRL,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(a); db.commit(); db.refresh(a)
    asset_id = a.id
    db.close()

    # Use distinct event_dates to make the chronological order unambiguous.
    client.post("/lancamentos", json={
        "asset_id": asset_id, "type": "COMPRA",
        "event_date": "2024-01-15",
        "quantity": 100, "unit_price": 25.00,
    }, headers=auth(seed["admin_token"]))
    client.post("/lancamentos", json={
        "asset_id": asset_id, "type": "RESGATE_TOTAL",
        "event_date": "2024-06-15",
        "quantity": 100, "unit_price": 28.00,
    }, headers=auth(seed["admin_token"]))
    client.post("/lancamentos", json={
        "asset_id": asset_id, "type": "COMPRA",
        "event_date": "2024-09-15",
        "quantity": 50, "unit_price": 32.00,
    }, headers=auth(seed["admin_token"]))

    r = client.get(f"/assets/{asset_id}/position", headers=auth(seed["admin_token"]))
    assert r.status_code == 200, r.text
    pos = r.json()
    # After reset, the only basis-contributing event is the second COMPRA (50 @ 32).
    assert pos["quantity_held"] == 50.0
    assert pos["average_cost"] == 32.0
    # total_invested = 50 * 32 = 1600 (no old prices contaminate it).
    assert pos["total_invested_brl"] == 1600.0


# ── BTC fractional sale: tolerance triggers reset ─────────────────────────────

def test_fractional_sale_below_tolerance_resets(client, seed):
    """Buy 0.005 BTC; sell 0.005 BTC. Floating-point residual under 1e-6 must
    trigger a position reset just as RESGATE_TOTAL would."""
    db = TestSession()
    fi = db.query(FinancialInstitution).first()
    now = datetime.now(timezone.utc)
    a = Asset(
        id=str(uuid.uuid4()),
        workspace_id=seed["ws_id"],
        financial_institution_id=fi.id,
        asset_class=AssetClass.CRYPTO,
        name="Bitcoin",
        ticker="BTC",
        currency=Currency.BRL,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(a); db.commit(); db.refresh(a)
    asset_id = a.id
    db.close()

    client.post("/lancamentos", json={
        "asset_id": asset_id, "type": "COMPRA",
        "event_date": "2024-01-10",
        "quantity": 0.005, "unit_price": 200000.00,
    }, headers=auth(seed["admin_token"]))
    # Sell exactly the same — residual will be 0 (or below 1e-6).
    client.post("/lancamentos", json={
        "asset_id": asset_id, "type": "VENDA",
        "event_date": "2024-02-10",
        "quantity": 0.005, "unit_price": 250000.00,
    }, headers=auth(seed["admin_token"]))
    # Re-buy at a different price.
    client.post("/lancamentos", json={
        "asset_id": asset_id, "type": "COMPRA",
        "event_date": "2024-03-10",
        "quantity": 0.01, "unit_price": 300000.00,
    }, headers=auth(seed["admin_token"]))

    r = client.get(f"/assets/{asset_id}/position", headers=auth(seed["admin_token"]))
    pos = r.json()
    assert abs(pos["quantity_held"] - 0.01) < 1e-6
    # PM is fresh: only the second COMPRA matters.
    assert pos["average_cost"] == 300000.0


# ── Non-cotado COMPRA accumulates basis with qty unchanged ────────────────────

def test_non_cotado_position_runs_basis_only(client, seed):
    """A CDB COMPRA with gross_amount = 5000 contributes 5000 to basis but 0 to
    quantity. running_qty = 0; running_basis_brl = 5000."""
    db = TestSession()
    fi = db.query(FinancialInstitution).first()
    now = datetime.now(timezone.utc)
    a = Asset(
        id=str(uuid.uuid4()),
        workspace_id=seed["ws_id"],
        financial_institution_id=fi.id,
        asset_class=AssetClass.FIXED_INCOME,
        name="CDB BTG 110% CDI 2028",
        ticker=None,
        currency=Currency.BRL,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(a); db.commit(); db.refresh(a)
    asset_id = a.id
    db.close()

    client.post("/lancamentos", json={
        "asset_id": asset_id, "type": "COMPRA",
        "event_date": "2024-04-01",
        "gross_amount": 5000.00,
    }, headers=auth(seed["admin_token"]))

    r = client.get(f"/assets/{asset_id}/position", headers=auth(seed["admin_token"]))
    pos = r.json()
    assert pos["quantity_held"] == 0.0
    # Cotado-style avg_cost is 0 (no qty contributing).
    assert pos["average_cost"] == 0.0
    # But the standalone basis is 5000.
    assert pos["total_invested_brl"] == 5000.0
