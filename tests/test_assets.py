import json
import uuid
from datetime import datetime, timezone

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
    ws_a = WorkspaceService(db).create("Assets WS A")
    ws_b = WorkspaceService(db).create("Assets WS B")

    admin_a = UserService(db).create(ws_a.id, "ast_admin_a@test.com", "adminpass", UserRole.admin)
    member_a = UserService(db).create(ws_a.id, "ast_member_a@test.com", "memberpass", UserRole.member)
    admin_b = UserService(db).create(ws_b.id, "ast_admin_b@test.com", "adminpass", UserRole.admin)

    now = datetime.now(timezone.utc)
    sysadmin = User(
        id=str(uuid.uuid4()),
        workspace_id=None,
        email="ast_sysadmin@test.internal",
        name="SysAdmin",
        password_hash=bcrypt.hashpw(b"syspass", bcrypt.gensalt()).decode(),
        role=UserRole.sysadmin,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(sysadmin)

    fi_xp = FinancialInstitution(
        id=str(uuid.uuid4()),
        long_name="XP Investimentos",
        short_name="XP",
        logo_slug="xp",
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    fi_avenue = FinancialInstitution(
        id=str(uuid.uuid4()),
        long_name="Avenue Securities",
        short_name="Avenue",
        logo_slug="avenue",
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    fi_inactive = FinancialInstitution(
        id=str(uuid.uuid4()),
        long_name="Inactive Bank",
        short_name="Inactive",
        logo_slug=None,
        is_active=False,
        created_at=now,
        updated_at=now,
    )
    fi_particular = FinancialInstitution(
        id=str(uuid.uuid4()),
        long_name="Particular (sem instituição)",
        short_name="Particular",
        logo_slug="particular",
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add_all([fi_xp, fi_avenue, fi_inactive, fi_particular])
    db.commit()

    db.refresh(ws_a); db.refresh(ws_b)
    db.refresh(admin_a); db.refresh(member_a); db.refresh(admin_b); db.refresh(sysadmin)
    db.refresh(fi_xp); db.refresh(fi_avenue); db.refresh(fi_inactive); db.refresh(fi_particular)

    # Spec 10: assets need investment accounts. Create one per (workspace, FI).
    def _make_acc(ws_id, fi_id, name, currency="BRL"):
        from numis_geek.models.account import Account, AccountType, Currency
        from datetime import timezone
        a = Account(
            id=str(uuid.uuid4()),
            workspace_id=ws_id,
            financial_institution_id=fi_id,
            name=name,
            account_type=AccountType.investment,
            currency=Currency(currency),
            is_active=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(a)
        return a

    acc_xp_a = _make_acc(ws_a.id, fi_xp.id, "XP Inv A")
    acc_avenue_a = _make_acc(ws_a.id, fi_avenue.id, "Avenue Inv A", currency="USD")
    acc_particular_a = _make_acc(ws_a.id, fi_particular.id, "Patrimônio pessoal A")
    acc_xp_b = _make_acc(ws_b.id, fi_xp.id, "XP Inv B")
    db.commit()
    db.refresh(acc_xp_a); db.refresh(acc_avenue_a); db.refresh(acc_particular_a); db.refresh(acc_xp_b)

    # Capture all IDs before db.close() to avoid DetachedInstanceError.
    out = {
        "ws_a": ws_a.id, "ws_b": ws_b.id,
        "admin_a_id": admin_a.id, "member_a_id": member_a.id, "admin_b_id": admin_b.id,
        "sysadmin_id": sysadmin.id,
        "fi_xp": fi_xp.id, "fi_avenue": fi_avenue.id,
        "fi_inactive": fi_inactive.id, "fi_particular": fi_particular.id,
        "acc_xp_a": acc_xp_a.id, "acc_avenue_a": acc_avenue_a.id,
        "acc_particular_a": acc_particular_a.id, "acc_xp_b": acc_xp_b.id,
    }
    out["admin_token_a"] = AuthService(db).login("ast_admin_a@test.com", "adminpass")
    out["member_token_a"] = AuthService(db).login("ast_member_a@test.com", "memberpass")
    out["admin_token_b"] = AuthService(db).login("ast_admin_b@test.com", "adminpass")
    out["sysadmin_token"] = AuthService(db).login("ast_sysadmin@test.internal", "syspass")
    db.close()
    return out


def auth(token):
    return {"Authorization": f"Bearer {token}"}


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_list_assets_empty(client, seed):
    r = client.get("/assets", headers=auth(seed["admin_token_a"]))
    assert r.status_code == 200
    assert r.json() == []


def test_create_stock_br(client, seed):
    r = client.post("/assets", json={
        "asset_class": "STOCK", "country": "BR", "country": "BR",
        "account_id": seed["acc_xp_a"],
        "name": "Petrobras PN",
        "currency": "BRL",
        "ticker": "PETR4",
    }, headers=auth(seed["admin_token_a"]))
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["ticker"] == "PETR4"
    assert data["asset_class"] == "STOCK"
    assert data["financial_institution_name"] == "XP"
    assert data["details"] is None
    assert data["workspace_id"] == seed["ws_a"]


def test_create_member_can_create(client, seed):
    r = client.post("/assets", json={
        "asset_class": "STOCK", "country": "BR", "country": "BR",
        "account_id": seed["acc_xp_a"],
        "name": "Itaú PN",
        "currency": "BRL",
        "ticker": "ITUB4",
    }, headers=auth(seed["member_token_a"]))
    assert r.status_code == 201, r.text


def test_create_fixed_income(client, seed):
    r = client.post("/assets", json={
        "asset_class": "FIXED_INCOME", "country": "BR",
        "account_id": seed["acc_xp_a"],
        "name": "CDB BTG 110% CDI 2028",
        "currency": "BRL",
        "details": {
            "issuer": "Banco BTG Pactual",
            "issue_date": "2024-03-15",
            "maturity_date": "2028-03-15",
            "indexer": "CDI",
            "rate": 110.0,
            "face_value": 50000.00,
        },
    }, headers=auth(seed["admin_token_a"]))
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["details"]["issuer"] == "Banco BTG Pactual"
    assert data["details"]["indexer"] == "CDI"
    assert data["details"]["maturity_date"] == "2028-03-15"


def test_create_real_estate(client, seed):
    r = client.post("/assets", json={
        "asset_class": "REAL_ESTATE", "country": "BR",
        "account_id": seed["acc_particular_a"],
        "name": "Apto Pinheiros 302",
        "currency": "BRL",
        "details": {
            "address": "Rua dos Pinheiros, 100, ap 302",
            "city": "São Paulo",
            "state": "SP",
            "country": "BR",
            "area_m2": 95.5,
        },
    }, headers=auth(seed["admin_token_a"]))
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["details"]["city"] == "São Paulo"
    assert data["details"]["country"] == "BR"


def test_create_vehicle(client, seed):
    r = client.post("/assets", json={
        "asset_class": "VEHICLE", "country": "BR",
        "account_id": seed["acc_particular_a"],
        "name": "Toyota Corolla 2022",
        "currency": "BRL",
        "details": {
            "make": "Toyota",
            "model": "Corolla",
            "year": 2022,
            "license_plate": "ABC1D23",
        },
    }, headers=auth(seed["admin_token_a"]))
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["details"]["make"] == "Toyota"
    assert data["details"]["year"] == 2022


def test_fi_required(client, seed):
    r = client.post("/assets", json={
        "asset_class": "STOCK", "country": "BR", "country": "BR",
        # missing financial_institution_id
        "name": "No FI",
        "currency": "BRL",
        "ticker": "NOFI3",
    }, headers=auth(seed["admin_token_a"]))
    assert r.status_code == 422


def test_nonexistent_account_rejected(client, seed):
    """Spec 10: when account_id doesn't exist, return 404."""
    r = client.post("/assets", json={
        "asset_class": "STOCK", "country": "BR",
        "account_id": "00000000-0000-0000-0000-000000000000",
        "name": "Should Fail",
        "currency": "BRL",
        "ticker": "FAIL3",
    }, headers=auth(seed["admin_token_a"]))
    assert r.status_code == 404


def test_ticker_required_for_stock(client, seed):
    r = client.post("/assets", json={
        "asset_class": "STOCK", "country": "BR", "country": "BR",
        "account_id": seed["acc_xp_a"],
        "name": "Stock w/o ticker",
        "currency": "BRL",
    }, headers=auth(seed["admin_token_a"]))
    assert r.status_code == 422


def test_ticker_forbidden_for_real_estate(client, seed):
    r = client.post("/assets", json={
        "asset_class": "REAL_ESTATE", "country": "BR",
        "account_id": seed["acc_particular_a"],
        "name": "Casa com ticker",
        "currency": "BRL",
        "ticker": "HOUSE",
        "details": {"address": "x", "city": "y", "state": "z", "country": "BR"},
    }, headers=auth(seed["admin_token_a"]))
    assert r.status_code == 422


def test_details_required_for_fixed_income(client, seed):
    r = client.post("/assets", json={
        "asset_class": "FIXED_INCOME", "country": "BR",
        "account_id": seed["acc_xp_a"],
        "name": "CDB no details",
        "currency": "BRL",
    }, headers=auth(seed["admin_token_a"]))
    assert r.status_code == 422


def test_details_forbidden_for_stock(client, seed):
    r = client.post("/assets", json={
        "asset_class": "STOCK", "country": "BR", "country": "BR",
        "account_id": seed["acc_xp_a"],
        "name": "Stock w/ extras",
        "currency": "BRL",
        "ticker": "EXTRA3",
        "details": {"issuer": "x"},
    }, headers=auth(seed["admin_token_a"]))
    assert r.status_code == 422


def test_cnpj_only_for_fund(client, seed):
    r = client.post("/assets", json={
        "asset_class": "STOCK", "country": "BR", "country": "BR",
        "account_id": seed["acc_xp_a"],
        "name": "Stock w/ cnpj",
        "currency": "BRL",
        "ticker": "CNPJ3",
        "cnpj": "12.345.678/0001-90",
    }, headers=auth(seed["admin_token_a"]))
    assert r.status_code == 422


def test_real_estate_missing_required_field(client, seed):
    r = client.post("/assets", json={
        "asset_class": "REAL_ESTATE", "country": "BR",
        "account_id": seed["acc_particular_a"],
        "name": "Casa incompleta",
        "currency": "BRL",
        "details": {"address": "x", "city": "y"},  # missing state, country
    }, headers=auth(seed["admin_token_a"]))
    assert r.status_code == 422


def test_unique_per_workspace_ticker_fi(client, seed):
    r1 = client.post("/assets", json={
        "asset_class": "STOCK", "country": "BR", "country": "US",
        "account_id": seed["acc_avenue_a"],
        "name": "Apple",
        "currency": "USD",
        "ticker": "AAPL",
    }, headers=auth(seed["admin_token_a"]))
    assert r1.status_code == 201, r1.text

    # Same ticker, same custodian, same class → blocked.
    r2 = client.post("/assets", json={
        "asset_class": "STOCK", "country": "BR", "country": "US",
        "account_id": seed["acc_avenue_a"],
        "name": "Apple Dup",
        "currency": "USD",
        "ticker": "AAPL",
    }, headers=auth(seed["admin_token_a"]))
    assert r2.status_code == 409

    # Same ticker, same custodian, DIFFERENT class → also blocked
    # (catches class typos like registering AAPL as STOCK_BR by mistake).
    r3 = client.post("/assets", json={
        "asset_class": "STOCK", "country": "BR", "country": "BR",
        "account_id": seed["acc_avenue_a"],
        "name": "Apple as BR (typo)",
        "currency": "BRL",
        "ticker": "AAPL",
    }, headers=auth(seed["admin_token_a"]))
    assert r3.status_code == 409


def test_same_ticker_different_fi_allowed(client, seed):
    # AAPL @ Avenue already exists from previous test; create AAPL @ XP — should succeed.
    r = client.post("/assets", json={
        "asset_class": "STOCK", "country": "BR", "country": "US",
        "account_id": seed["acc_xp_a"],
        "name": "Apple via XP BDR",
        "currency": "USD",
        "ticker": "AAPL",
    }, headers=auth(seed["admin_token_a"]))
    assert r.status_code == 201, r.text


def test_member_cannot_read_other_workspace(client, seed):
    # admin_b creates an asset in workspace B
    r_create = client.post("/assets", json={
        "asset_class": "STOCK", "country": "BR",
        "account_id": seed["acc_xp_b"],
        "name": "WS B Asset",
        "currency": "BRL",
        "ticker": "WSB3",
    }, headers=auth(seed["admin_token_b"]))
    assert r_create.status_code == 201
    asset_id_b = r_create.json()["id"]

    # member of workspace A tries to read it
    r = client.get(f"/assets/{asset_id_b}", headers=auth(seed["member_token_a"]))
    assert r.status_code == 404

    # And cannot edit it
    r2 = client.put(f"/assets/{asset_id_b}", json={
        "asset_class": "STOCK", "country": "BR", "country": "BR",
        "account_id": seed["acc_xp_a"],
        "name": "Hijack",
        "currency": "BRL",
        "ticker": "WSB3",
    }, headers=auth(seed["member_token_a"]))
    assert r2.status_code == 404

    # And the member's listing shouldn't include it
    r3 = client.get("/assets", headers=auth(seed["member_token_a"]))
    ids = [a["id"] for a in r3.json()]
    assert asset_id_b not in ids


def test_sysadmin_lists_across_workspaces(client, seed):
    r = client.get("/assets", headers=auth(seed["sysadmin_token"]))
    assert r.status_code == 200
    items = r.json()
    workspace_ids_seen = {a["workspace_id"] for a in items}
    assert seed["ws_a"] in workspace_ids_seen
    assert seed["ws_b"] in workspace_ids_seen


def test_sysadmin_filter_by_workspace(client, seed):
    r = client.get(f"/assets?workspace_id={seed['ws_b']}", headers=auth(seed["sysadmin_token"]))
    assert r.status_code == 200
    items = r.json()
    assert all(a["workspace_id"] == seed["ws_b"] for a in items)
    assert len(items) >= 1


def test_sysadmin_creates_in_specified_workspace(client, seed):
    r = client.post("/assets", json={
        "asset_class": "CRYPTO", "country": "BR",
        "account_id": seed["acc_xp_b"],
        "name": "Bitcoin via Sysadmin",
        "currency": "USD",
        "ticker": "BTC",
        "workspace_id": seed["ws_b"],
    }, headers=auth(seed["sysadmin_token"]))
    assert r.status_code == 201, r.text
    assert r.json()["workspace_id"] == seed["ws_b"]


def test_sysadmin_create_requires_workspace(client, seed):
    r = client.post("/assets", json={
        "asset_class": "STOCK", "country": "BR", "country": "BR",
        "account_id": seed["acc_xp_a"],
        "name": "No WS",
        "currency": "BRL",
        "ticker": "NOWS3",
    }, headers=auth(seed["sysadmin_token"]))
    assert r.status_code == 400


def test_update_asset(client, seed):
    r = client.post("/assets", json={
        "asset_class": "REIT", "country": "BR", "country": "BR",
        "account_id": seed["acc_xp_a"],
        "name": "HGLG11 original",
        "currency": "BRL",
        "ticker": "HGLG11",
    }, headers=auth(seed["admin_token_a"]))
    asset_id = r.json()["id"]

    r2 = client.put(f"/assets/{asset_id}", json={
        "asset_class": "REIT", "country": "BR", "country": "BR",
        "account_id": seed["acc_xp_a"],
        "name": "CSHG Logística FII",
        "currency": "BRL",
        "ticker": "HGLG11",
    }, headers=auth(seed["admin_token_a"]))
    assert r2.status_code == 200
    assert r2.json()["name"] == "CSHG Logística FII"


def test_deactivate_asset(client, seed):
    r = client.post("/assets", json={
        "asset_class": "STOCK", "country": "BR", "country": "BR",
        "account_id": seed["acc_xp_a"],
        "name": "To Deactivate",
        "currency": "BRL",
        "ticker": "DEAC3",
    }, headers=auth(seed["admin_token_a"]))
    asset_id = r.json()["id"]

    r2 = client.put(f"/assets/{asset_id}/deactivate", headers=auth(seed["admin_token_a"]))
    assert r2.status_code == 200
    assert r2.json()["is_active"] is False

    # default list excludes it
    r3 = client.get("/assets", headers=auth(seed["admin_token_a"]))
    assert asset_id not in [a["id"] for a in r3.json()]

    # include_inactive=true brings it back
    r4 = client.get("/assets?include_inactive=true", headers=auth(seed["admin_token_a"]))
    assert asset_id in [a["id"] for a in r4.json()]


def test_audit_log_created_for_asset_mutations(client, seed):
    r = client.post("/assets", json={
        "asset_class": "ETF", "country": "BR",
        "account_id": seed["acc_xp_a"],
        "name": "BOVA11",
        "currency": "BRL",
        "ticker": "BOVA11",
    }, headers=auth(seed["admin_token_a"]))
    asset_id = r.json()["id"]

    client.put(f"/assets/{asset_id}", json={
        "asset_class": "ETF", "country": "BR",
        "account_id": seed["acc_xp_a"],
        "name": "BOVA11 ETF Ibovespa",
        "currency": "BRL",
        "ticker": "BOVA11",
    }, headers=auth(seed["admin_token_a"]))

    client.put(f"/assets/{asset_id}/deactivate", headers=auth(seed["admin_token_a"]))

    db = TestSession()
    try:
        actions = [
            row.action for row in
            db.query(AuditLog).filter(AuditLog.resource_id == asset_id).all()
        ]
    finally:
        db.close()
    assert "asset.created" in actions
    assert "asset.updated" in actions
    assert "asset.deactivated" in actions


def test_fi_deactivate_blocked_when_active_asset_exists(client, seed):
    # Create a fresh FI through the sysadmin endpoint
    r_fi = client.post("/financial-institutions", json={
        "long_name": "Bank Restrict",
        "short_name": "Restrict",
    }, headers=auth(seed["sysadmin_token"]))
    fi_id = r_fi.json()["id"]

    # Create an investment account at this FI in workspace A
    from numis_geek.models.account import Account, AccountType, Currency
    db = TestSession()
    acc = Account(
        id=str(uuid.uuid4()), workspace_id=seed["ws_a"],
        financial_institution_id=fi_id, name="Restrict Inv",
        account_type=AccountType.investment, currency=Currency.BRL,
        is_active=True, created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(acc); db.commit(); db.refresh(acc)
    acc_id = acc.id
    db.close()

    # Bind an asset to it
    r_asset = client.post("/assets", json={
        "asset_class": "STOCK", "country": "BR",
        "account_id": acc_id,
        "name": "Bound asset",
        "currency": "BRL",
        "ticker": "REST3",
    }, headers=auth(seed["admin_token_a"]))
    assert r_asset.status_code == 201
    asset_id = r_asset.json()["id"]

    # Deactivation must fail
    r_blocked = client.put(f"/financial-institutions/{fi_id}/deactivate", headers=auth(seed["sysadmin_token"]))
    assert r_blocked.status_code == 409

    # After deactivating the asset, FI deactivation succeeds
    client.put(f"/assets/{asset_id}/deactivate", headers=auth(seed["admin_token_a"]))
    r_ok = client.put(f"/financial-institutions/{fi_id}/deactivate", headers=auth(seed["sysadmin_token"]))
    assert r_ok.status_code == 200


# ── Spec 46 — /assets/{id}/price-history ───────────────────────────────────


def _create_test_asset(client, seed, ticker: str = "PETR4") -> str:
    """Helper: create a stock asset in ws_a so we can attach snapshot items.
    Caller passes a unique ticker per test to dodge the
    (ticker, fi, workspace) unique constraint when tests run together."""
    r = client.post("/assets", json={
        "asset_class": "STOCK", "country": "BR",
        "account_id": seed["acc_xp_a"],
        "name": f"{ticker} stock", "ticker": ticker,
        "currency": "BRL",
    }, headers=auth(seed["admin_token_a"]))
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def _seed_snapshot_with_item(ws_id: str, asset_id: str, period: str, price: str):
    """Insert one PortfolioSnapshot + one PortfolioSnapshotItem with `unit_price`.
    period is a YYYY-MM-DD string for period_end_date."""
    from datetime import date, datetime, timezone
    from decimal import Decimal
    from numis_geek.models.portfolio_snapshot import (
        PortfolioSnapshot, PortfolioSnapshotItem, SnapshotSource, SnapshotStatus,
    )
    db = TestSession()
    try:
        snap = PortfolioSnapshot(
            id=str(uuid.uuid4()),
            workspace_id=ws_id,
            period_end_date=date.fromisoformat(period),
            source=SnapshotSource.MANUAL,
            status=SnapshotStatus.CLOSED,
            total_value_brl=Decimal("0"),
            total_value_usd=Decimal("0"),
            total_invested_brl=Decimal("0"),
            total_received_brl=Decimal("0"),
            is_active=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        db.add(snap)
        db.flush()
        db.add(PortfolioSnapshotItem(
            id=str(uuid.uuid4()),
            snapshot_id=snap.id,
            asset_id=asset_id,
            quantity=Decimal("100"),
            unit_price=Decimal(price),
            created_at=datetime.now(timezone.utc),
        ))
        db.commit()
    finally:
        db.close()


def test_price_history_returns_chronological_points(client, seed):
    asset_id = _create_test_asset(client, seed, ticker="PH1")
    _seed_snapshot_with_item(seed["ws_a"], asset_id, "2026-01-31", "30.10")
    _seed_snapshot_with_item(seed["ws_a"], asset_id, "2026-03-31", "32.40")
    _seed_snapshot_with_item(seed["ws_a"], asset_id, "2026-04-30", "31.80")

    r = client.get(
        f"/assets/{asset_id}/price-history?period=all",
        headers=auth(seed["admin_token_a"]),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["asset_id"] == asset_id
    assert body["currency"] == "BRL"
    assert body["period"] == "all"
    dates = [p["date"] for p in body["points"]]
    assert dates == sorted(dates), "points must be ASC by date"
    assert dates == ["2026-01-31", "2026-03-31", "2026-04-30"]
    # unit_price round-trips as a Decimal string.
    assert body["points"][0]["unit_price"].startswith("30.10")


def test_price_history_cross_workspace_returns_404(client, seed):
    # ws_a asset, but request comes from admin_token_b (different workspace).
    asset_id = _create_test_asset(client, seed, ticker="PH2")
    _seed_snapshot_with_item(seed["ws_a"], asset_id, "2026-02-28", "31.80")

    r = client.get(
        f"/assets/{asset_id}/price-history",
        headers=auth(seed["admin_token_b"]),
    )
    assert r.status_code == 404


def test_price_history_period_6m_filters_old_snapshots(client, seed):
    """A snapshot from 3 years ago must be excluded when period=6m."""
    from datetime import date, timedelta
    asset_id = _create_test_asset(client, seed, ticker="PH3")

    today = date.today()
    far_past = (today - timedelta(days=3 * 365)).isoformat()
    recent = (today - timedelta(days=60)).isoformat()

    _seed_snapshot_with_item(seed["ws_a"], asset_id, far_past, "20.00")
    _seed_snapshot_with_item(seed["ws_a"], asset_id, recent, "31.80")

    r6 = client.get(
        f"/assets/{asset_id}/price-history?period=6m",
        headers=auth(seed["admin_token_a"]),
    )
    assert r6.status_code == 200
    dates_6m = [p["date"] for p in r6.json()["points"]]
    assert recent in dates_6m
    assert far_past not in dates_6m

    # period=all keeps both
    r_all = client.get(
        f"/assets/{asset_id}/price-history?period=all",
        headers=auth(seed["admin_token_a"]),
    )
    dates_all = [p["date"] for p in r_all.json()["points"]]
    assert far_past in dates_all
    assert recent in dates_all


def test_price_history_no_snapshots_returns_empty(client, seed):
    asset_id = _create_test_asset(client, seed, ticker="PH4")
    r = client.get(
        f"/assets/{asset_id}/price-history",
        headers=auth(seed["admin_token_a"]),
    )
    assert r.status_code == 200
    assert r.json()["points"] == []


def test_get_asset_returns_details(client, seed):
    r_create = client.post("/assets", json={
        "asset_class": "FIXED_INCOME", "country": "BR",
        "account_id": seed["acc_xp_a"],
        "name": "LCI BTG IPCA",
        "currency": "BRL",
        "details": {
            "issuer": "BTG",
            "maturity_date": "2030-01-15",
            "indexer": "IPCA",
            "rate": 6.5,
        },
    }, headers=auth(seed["admin_token_a"]))
    asset_id = r_create.json()["id"]

    r_get = client.get(f"/assets/{asset_id}", headers=auth(seed["admin_token_a"]))
    assert r_get.status_code == 200
    body = r_get.json()
    assert body["details"]["indexer"] == "IPCA"
    assert body["details"]["rate"] == 6.5
