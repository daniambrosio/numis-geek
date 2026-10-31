"""Spec 70 fase 3 (= fase 2 da spec 80) — saldo derivado da conta corrente.

Cobre: saldo derivado com/sem abertura e na fronteira de data, conferência
mês a mês, fechamento aberto puxando o derivado (create, sync e refresh
depois de mexer no ledger) com CLOSED intocado, trava de AssetMovement em
ativo vinculado, PATCH da abertura com validação e o vínculo com as
invariantes da spec 80.
"""
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

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
    PendencyAction, PendencyReason, PortfolioSnapshot, PortfolioSnapshotItem,
    SnapshotPendency, SnapshotSource, SnapshotStatus,
)
from numis_geek.models.ptax_rate import PTAXRate
from numis_geek.models.user import UserRole
from numis_geek.services import account_balance
from numis_geek.services.auth import AuthService
from numis_geek.services.snapshot import create_snapshot, sync_snapshot_items
from numis_geek.services.user import UserService
from numis_geek.services.workspace import WorkspaceService

TEST_ENGINE = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(bind=TEST_ENGINE, autoflush=False, autocommit=False)

PTAX = Decimal("5.00000000")
OPEN_DATE = date(2026, 8, 31)


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


def _account(db, ws_id, fi_id, name, *, account_type=AccountType.checking, currency=Currency.BRL,
             opening=None, opening_date=None, from_ledger=True):
    a = Account(
        id=str(uuid.uuid4()), workspace_id=ws_id, financial_institution_id=fi_id, name=name,
        account_type=account_type, currency=currency, is_active=True,
        opening_balance=opening, opening_balance_date=opening_date,
        balance_from_ledger=from_ledger,
    )
    db.add(a)
    return a


def _asset(db, ws_id, account_id, name, *, asset_class=AssetClass.CASH, currency=Currency.BRL, linked=None):
    a = Asset(
        id=str(uuid.uuid4()), workspace_id=ws_id, account_id=account_id, asset_class=asset_class,
        country="BR", name=name, currency=currency, is_active=True, linked_account_id=linked,
    )
    db.add(a)
    return a


@pytest.fixture(scope="module")
def seed():
    db = TestSession()
    ws = WorkspaceService(db).create("BAL WS")
    ws2 = WorkspaceService(db).create("BAL WS 2")
    UserService(db).create(ws.id, "bal_admin@numis-tests.dev", "adminpass", UserRole.admin)
    UserService(db).create(ws.id, "bal_member@numis-tests.dev", "memberpass", UserRole.member)
    UserService(db).create(ws2.id, "bal_admin2@numis-tests.dev", "adminpass", UserRole.admin)
    now = datetime.now(timezone.utc)
    fi = FinancialInstitution(
        id=str(uuid.uuid4()), long_name="Banco Saldo S.A.", short_name="BSD", logo_slug="bsd",
        is_active=True, created_at=now, updated_at=now,
    )
    db.add(fi)
    db.flush()
    start = date(2026, 1, 1)
    for i in range(800):
        db.add(PTAXRate(id=str(uuid.uuid4()), date=start + timedelta(days=i), rate=PTAX, fetched_at=now))
    itau = _account(db, ws.id, fi.id, "Conta Corrente Itaú", opening=Decimal("1000"), opening_date=OPEN_DATE)
    nomad = _account(db, ws.id, fi.id, "Conta Corrente Nomad", currency=Currency.USD,
                     opening=Decimal("200"), opening_date=OPEN_DATE)
    spare = _account(db, ws.id, fi.id, "Conta Corrente Sem Vínculo")
    invest = _account(db, ws.id, fi.id, "Conta Investimento", account_type=AccountType.investment)
    other_ws_acc = _account(db, ws2.id, fi.id, "Conta WS2")
    db.flush()
    cash_itau = _asset(db, ws.id, invest.id, "Saldo em Conta (Itaú)", linked=itau.id)
    cash_nomad = _asset(db, ws.id, invest.id, "Saldo em Conta Nomad", currency=Currency.USD, linked=nomad.id)
    cash_free = _asset(db, ws.id, invest.id, "Saldo em Conta (XP)")
    stock = _asset(db, ws.id, invest.id, "PETR4", asset_class=AssetClass.STOCK)
    db.commit()
    ids = {
        "ws_id": ws.id, "ws2_id": ws2.id, "fi_id": fi.id, "itau": itau.id, "nomad": nomad.id,
        "spare": spare.id, "invest": invest.id, "other_ws_acc": other_ws_acc.id,
        "cash_itau": cash_itau.id, "cash_nomad": cash_nomad.id, "cash_free": cash_free.id,
        "stock": stock.id,
    }
    ids["admin_token"] = AuthService(db).login("bal_admin@numis-tests.dev", "adminpass")
    ids["member_token"] = AuthService(db).login("bal_member@numis-tests.dev", "memberpass")
    ids["admin2_token"] = AuthService(db).login("bal_admin2@numis-tests.dev", "adminpass")
    db.close()
    return ids


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def tx(client, seed, account_key, event_date, amount, description="Mov"):
    r = client.post("/api/transactions", json={
        "source_type": "CHECKING", "checking_account_id": seed[account_key],
        "event_date": event_date, "description": description, "amount": amount,
    }, headers=auth(seed["admin_token"]))
    assert r.status_code == 201, r.text
    return r.json()[0]


# ── saldo derivado ────────────────────────────────────────────────────────────

def test_derived_balance_boundaries(client, seed):
    tx(client, seed, "itau", "2026-08-31", "-999", "No dia da abertura — já está no saldo de abertura")
    tx(client, seed, "itau", "2026-09-01", "500", "Salário")
    tx(client, seed, "itau", "2026-09-30", "-200", "Aluguel")
    tx(client, seed, "itau", "2026-10-01", "-100", "Mercado")
    db = TestSession()
    acc = db.get(Account, seed["itau"])
    assert account_balance.derived_balance(db, acc, date(2026, 8, 31)) == Decimal("1000.00")
    assert account_balance.derived_balance(db, acc, date(2026, 9, 1)) == Decimal("1500.00")
    assert account_balance.derived_balance(db, acc, date(2026, 9, 30)) == Decimal("1300.00")
    assert account_balance.derived_balance(db, acc, date(2026, 10, 1)) == Decimal("1200.00")
    db.close()


def test_derived_balance_without_opening_sums_everything(client, seed):
    tx(client, seed, "spare", "2026-01-10", "300")
    tx(client, seed, "spare", "2026-02-10", "-50")
    db = TestSession()
    acc = db.get(Account, seed["spare"])
    assert account_balance.derived_balance(db, acc, date(2026, 12, 31)) == Decimal("250.00")
    assert account_balance.derived_balance(db, acc, date(2026, 1, 31)) == Decimal("300.00")
    assert account_balance.derived_balance(db, acc, date(2026, 1, 9)) == Decimal("0.00")
    assert not account_balance.derives_on(acc, date(2026, 12, 31))  # sem data de abertura → segue digitado
    db.close()


def test_item_values_brl_and_usd():
    assert account_balance.item_values(Decimal("100"), Currency.BRL, Decimal("5")) == (
        Decimal("100"), Decimal("100"), Decimal("100"), Decimal("20.00"))
    assert account_balance.item_values(Decimal("100"), Currency.USD, Decimal("5")) == (
        Decimal("100"), Decimal("100"), Decimal("500.00"), Decimal("100"))


# ── fechamento ────────────────────────────────────────────────────────────────

def _item(db, snap_id, asset_id):
    return db.query(PortfolioSnapshotItem).filter(
        PortfolioSnapshotItem.snapshot_id == snap_id, PortfolioSnapshotItem.asset_id == asset_id,
    ).first()


def _assert_header_matches_items(db, snap):
    items = db.query(PortfolioSnapshotItem).filter(PortfolioSnapshotItem.snapshot_id == snap.id).all()
    assert snap.total_value_brl == sum((i.market_value_brl or Decimal("0") for i in items), Decimal("0"))
    assert snap.total_value_usd == sum((i.market_value_usd or Decimal("0") for i in items), Decimal("0"))


def test_create_snapshot_pulls_derived_for_linked_cash(seed):
    db = TestSession()
    res = create_snapshot(
        db, workspace_id=seed["ws_id"], period_end=date(2026, 9, 30),
        source=SnapshotSource.MANUAL, initial_status=SnapshotStatus.IN_REVIEW,
    )
    item = _item(db, res.snapshot_id, seed["cash_itau"])
    assert item.quantity == Decimal("1")
    assert item.unit_price == Decimal("1300.00")
    assert item.market_value_native == Decimal("1300.00")
    assert item.market_value_brl == Decimal("1300.00")
    assert item.market_value_usd == Decimal("260.00")
    nomad = _item(db, res.snapshot_id, seed["cash_nomad"])
    assert nomad.market_value_native == Decimal("200.00")
    assert nomad.market_value_brl == Decimal("1000.00")
    # vinculado com derivado não gera pendência; CASH digitado continua gerando
    pens = db.query(SnapshotPendency).filter(SnapshotPendency.snapshot_id == res.snapshot_id).all()
    assert seed["cash_itau"] not in {p.asset_id for p in pens}
    assert seed["cash_free"] in {p.asset_id for p in pens}
    _assert_header_matches_items(db, db.get(PortfolioSnapshot, res.snapshot_id))
    db.commit()
    seed["sep_snap"] = res.snapshot_id
    db.close()


def test_before_opening_date_stays_typed(seed):
    db = TestSession()
    res = create_snapshot(
        db, workspace_id=seed["ws_id"], period_end=date(2026, 7, 31),
        source=SnapshotSource.MANUAL, initial_status=SnapshotStatus.IN_REVIEW,
    )
    item = _item(db, res.snapshot_id, seed["cash_itau"])
    assert item.market_value_native in (None, Decimal("0"))
    pens = db.query(SnapshotPendency).filter(SnapshotPendency.snapshot_id == res.snapshot_id).all()
    assert seed["cash_itau"] in {p.asset_id for p in pens}
    db.rollback()
    db.close()


def test_ledger_change_refreshes_open_snapshot(client, seed):
    tx(client, seed, "itau", "2026-09-15", "-50", "Farmácia")
    db = TestSession()
    snap = db.get(PortfolioSnapshot, seed["sep_snap"])
    item = _item(db, snap.id, seed["cash_itau"])
    assert item.market_value_native == Decimal("1250.00")
    assert item.market_value_usd == Decimal("250.00")
    _assert_header_matches_items(db, snap)
    db.close()


def test_closed_snapshot_is_never_overwritten(client, seed):
    db = TestSession()
    snap = db.get(PortfolioSnapshot, seed["sep_snap"])
    item = _item(db, snap.id, seed["cash_itau"])
    # simula o valor digitado antigo e fecha
    item.unit_price = item.market_value_native = item.market_value_brl = Decimal("900.00")
    item.market_value_usd = Decimal("180.00")
    db.query(SnapshotPendency).filter(SnapshotPendency.snapshot_id == snap.id).update(
        {"resolved_at": datetime.now(timezone.utc)})
    snap.status = SnapshotStatus.CLOSED
    db.commit()
    db.close()
    tx(client, seed, "itau", "2026-09-20", "-10", "Café")
    db = TestSession()
    item = _item(db, seed["sep_snap"], seed["cash_itau"])
    assert item.market_value_native == Decimal("900.00")
    assert account_balance.refresh_linked_cash_items(db, db.get(PortfolioSnapshot, seed["sep_snap"])) == 0
    db.close()


def test_balance_check_shows_typed_vs_derived(client, seed):
    r = client.get(f"/api/accounts/{seed['itau']}/balance-check", headers=auth(seed["member_token"]))
    assert r.status_code == 200, r.text
    rows = r.json()
    sep = next(x for x in rows if x["period_end_date"] == "2026-09-30")
    assert sep["status"] == "CLOSED"
    assert sep["typed"] == 900.0
    assert sep["derived"] == 1240.0
    assert sep["difference"] == 340.0
    # fechamento anterior à abertura não entra
    assert all(x["period_end_date"] >= "2026-08-31" for x in rows)


def test_balance_check_empty_without_link(client, seed):
    r = client.get(f"/api/accounts/{seed['spare']}/balance-check", headers=auth(seed["admin_token"]))
    assert r.json() == []


def test_sync_reapplies_derived_and_resolves_manual_pendency(client, seed):
    db = TestSession()
    res = create_snapshot(
        db, workspace_id=seed["ws_id"], period_end=date(2026, 10, 31),
        source=SnapshotSource.MANUAL, initial_status=SnapshotStatus.IN_REVIEW,
    )
    snap = db.get(PortfolioSnapshot, res.snapshot_id)
    item = _item(db, snap.id, seed["cash_itau"])
    # estado "sujo": valor digitado + pendência manual aberta
    item.unit_price = item.market_value_native = item.market_value_brl = Decimal("1.00")
    db.add(SnapshotPendency(
        id=str(uuid.uuid4()), snapshot_id=snap.id, asset_id=seed["cash_itau"],
        reason=PendencyReason.MANUAL_SOURCE, action_type=PendencyAction.EDIT_PRICE,
        detail="manual", created_at=datetime.now(timezone.utc),
    ))
    db.commit()
    out = sync_snapshot_items(db, snapshot_id=snap.id, user_id=None)
    db.commit()
    item = _item(db, snap.id, seed["cash_itau"])
    assert item.market_value_native == Decimal("1140.00")   # 1240 − 100 de outubro
    open_pens = db.query(SnapshotPendency).filter(
        SnapshotPendency.snapshot_id == snap.id, SnapshotPendency.asset_id == seed["cash_itau"],
        SnapshotPendency.resolved_at.is_(None),
    ).count()
    assert open_pens == 0
    _assert_header_matches_items(db, db.get(PortfolioSnapshot, snap.id))
    assert out["items_added"] == 0
    snap_obj = db.get(PortfolioSnapshot, snap.id)
    snap_obj.is_active = False  # tira do caminho dos próximos testes
    db.commit()
    db.close()


# ── detalhe / abertura / vínculo ─────────────────────────────────────────────

def test_account_detail(client, seed):
    r = client.get(f"/api/accounts/{seed['itau']}", headers=auth(seed["member_token"]))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["name"] == "Conta Corrente Itaú"
    assert d["fi_long_name"] == "Banco Saldo S.A."
    assert d["linked_asset"] == {"id": seed["cash_itau"], "name": "Saldo em Conta (Itaú)"}
    assert d["opening_balance_date"] == "2026-08-31"
    assert len(d["balance_series"]) == 6
    assert d["balance"] is not None
    assert set(d["month"]) == {"inflows", "outflows", "net"}


def test_usd_account_detail_has_brl_equivalent(client, seed):
    d = client.get(f"/api/accounts/{seed['nomad']}", headers=auth(seed["admin_token"])).json()
    assert d["currency"] == "USD"
    assert d["balance_brl"] == pytest.approx(d["balance"] * 5)


def test_account_detail_other_workspace_404(client, seed):
    r = client.get(f"/api/accounts/{seed['itau']}", headers=auth(seed["admin2_token"]))
    assert r.status_code == 404


def test_investment_account_detail_has_no_balance(client, seed):
    d = client.get(f"/api/accounts/{seed['invest']}", headers=auth(seed["admin_token"])).json()
    assert d["balance"] is None
    assert d["month"] is None


def test_opening_balance_patch_validation_and_audit(client, seed):
    h = auth(seed["admin_token"])
    r = client.patch(f"/api/accounts/{seed['nomad']}/opening-balance", json={"opening_balance": "50"}, headers=h)
    assert r.status_code == 422
    r = client.patch(f"/api/accounts/{seed['nomad']}/opening-balance",
                     json={"opening_balance": "50", "opening_balance_date": "2025-12-31"}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["opening_balance"] == 50.0
    assert r.json()["opening_balance_date"] == "2025-12-31"
    r = client.patch(f"/api/accounts/{seed['invest']}/opening-balance",
                     json={"opening_balance": "1", "opening_balance_date": "2025-12-31"}, headers=h)
    assert r.status_code == 422
    r = client.patch(f"/api/accounts/{seed['nomad']}/opening-balance",
                     json={"opening_balance": "1", "opening_balance_date": "2025-12-31"},
                     headers=auth(seed["member_token"]))
    assert r.status_code == 403
    from numis_geek.models.audit_log import AuditLog
    db = TestSession()
    assert db.query(AuditLog).filter(
        AuditLog.action == "account.opening_balance_updated", AuditLog.resource_id == seed["nomad"],
    ).count() == 1
    db.close()


def test_link_invariants(client, seed):
    h = auth(seed["admin_token"])
    # não-CASH
    r = client.put(f"/api/accounts/{seed['spare']}/linked-asset", json={"asset_id": seed["stock"]}, headers=h)
    assert r.status_code == 422
    # CASH que já espelha outra conta
    r = client.put(f"/api/accounts/{seed['spare']}/linked-asset", json={"asset_id": seed["cash_itau"]}, headers=h)
    assert r.status_code == 422
    # conta de investimento não espelha
    r = client.put(f"/api/accounts/{seed['invest']}/linked-asset", json={"asset_id": seed["cash_free"]}, headers=h)
    assert r.status_code == 422
    # outro workspace
    r = client.put(f"/api/accounts/{seed['spare']}/linked-asset", json={"asset_id": seed["cash_free"]},
                   headers=auth(seed["admin2_token"]))
    assert r.status_code == 404
    # member não vincula
    r = client.put(f"/api/accounts/{seed['spare']}/linked-asset", json={"asset_id": seed["cash_free"]},
                   headers=auth(seed["member_token"]))
    assert r.status_code == 403
    # ok + desvincular
    r = client.put(f"/api/accounts/{seed['spare']}/linked-asset", json={"asset_id": seed["cash_free"]}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["linked_asset"]["id"] == seed["cash_free"]
    r = client.put(f"/api/accounts/{seed['spare']}/linked-asset", json={"asset_id": None}, headers=h)
    assert r.status_code == 200
    assert r.json()["linked_asset"] is None


# ── trava de lançamento ───────────────────────────────────────────────────────

def test_asset_movement_on_linked_cash_is_blocked(client, seed):
    r = client.post("/api/asset-movements", json={
        "asset_id": seed["cash_itau"], "type": "BUY", "event_date": "2026-09-10",
        "quantity": "1", "unit_price": "100", "gross_amount": "100", "currency": "BRL",
    }, headers=auth(seed["admin_token"]))
    assert r.status_code == 422
    assert "Movimentações" in r.json()["detail"]
    # ativo CASH sem vínculo continua aceitando
    r = client.post("/api/asset-movements", json={
        "asset_id": seed["cash_free"], "type": "BUY", "event_date": "2026-09-10",
        "quantity": "1", "unit_price": "100", "gross_amount": "100", "currency": "BRL",
    }, headers=auth(seed["admin_token"]))
    assert r.status_code == 201, r.text


# ── interruptor "saldo vem das movimentações" ─────────────────────────────────

def _off_account(seed):
    """Conta corrente com abertura e vínculo, mas interruptor desligado."""
    db = TestSession()
    acc = _account(db, seed["ws_id"], seed["fi_id"], f"Conta Off {uuid.uuid4().hex[:6]}",
                   opening=Decimal("500"), opening_date=date(2026, 8, 31), from_ledger=False)
    cash = _asset(db, seed["ws_id"], seed["invest"], f"Saldo em Conta Off {uuid.uuid4().hex[:6]}", linked=acc.id)
    db.commit()
    ids = acc.id, cash.id
    db.close()
    return ids


def test_toggle_off_keeps_typed_snapshot_and_movements(client, seed):
    acc_id, cash_id = _off_account(seed)
    db = TestSession()
    assert not account_balance.derives_on(db.get(Account, acc_id), date(2026, 10, 31))
    res = create_snapshot(
        db, workspace_id=seed["ws_id"], period_end=date(2026, 10, 31),
        source=SnapshotSource.MANUAL, initial_status=SnapshotStatus.IN_REVIEW,
    )
    item = _item(db, res.snapshot_id, cash_id)
    assert item is None or item.market_value_native in (None, Decimal("0"))
    pens = db.query(SnapshotPendency).filter(SnapshotPendency.snapshot_id == res.snapshot_id).all()
    assert cash_id in {p.asset_id for p in pens}
    db.rollback()
    db.close()
    # conferência funciona mesmo desligado
    r = client.get(f"/api/accounts/{acc_id}", headers=auth(seed["admin_token"]))
    assert r.status_code == 200
    assert r.json()["balance_from_ledger"] is False
    # lançamento no CASH vinculado segue aceito enquanto desligado
    r = client.post("/api/asset-movements", json={
        "asset_id": cash_id, "type": "BUY", "event_date": "2026-09-10",
        "quantity": "1", "unit_price": "100", "gross_amount": "100", "currency": "BRL",
    }, headers=auth(seed["admin_token"]))
    assert r.status_code == 201, r.text


def test_balance_source_patch(client, seed):
    acc_id, cash_id = _off_account(seed)
    h = auth(seed["admin_token"])
    url = f"/api/accounts/{acc_id}/balance-source"
    assert client.patch(url, json={"balance_from_ledger": True}, headers=auth(seed["member_token"])).status_code == 403
    assert client.patch(f"/api/accounts/{seed['invest']}/balance-source",
                        json={"balance_from_ledger": True}, headers=h).status_code == 422
    assert client.patch(f"/api/accounts/{seed['spare']}/balance-source",
                        json={"balance_from_ledger": True}, headers=h).status_code == 422  # sem abertura
    r = client.patch(url, json={"balance_from_ledger": True}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["balance_from_ledger"] is True
    # ligado → CASH vinculado passa a recusar lançamento
    r = client.post("/api/asset-movements", json={
        "asset_id": cash_id, "type": "BUY", "event_date": "2026-09-11",
        "quantity": "1", "unit_price": "100", "gross_amount": "100", "currency": "BRL",
    }, headers=h)
    assert r.status_code == 422
    r = client.patch(url, json={"balance_from_ledger": False}, headers=h)
    assert r.json()["balance_from_ledger"] is False
    from numis_geek.models.audit_log import AuditLog
    db = TestSession()
    assert db.query(AuditLog).filter(
        AuditLog.action == "account.balance_source_updated", AuditLog.resource_id == acc_id,
    ).count() == 2
    db.close()
