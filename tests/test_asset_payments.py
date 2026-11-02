"""Spec 83 — Pagar e receber com ativos.

Covers: CHECK de exatamente uma fonte (3 FKs), par atômico movimento + tx
pelos dois lados (Movimentações e Lançamentos), edição de um lado
refletindo no outro, remoção vinculada, relatórios contando a despesa
(summary / filtro de origem), SELL reduzindo custo proporcionalmente,
receita em ativo com custo = valor informado, isolamento de workspace e
o caminho genérico de create recusando ASSET.
"""
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
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
from numis_geek.models.category import Category, CategoryKind
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.party import Party
from numis_geek.models.ptax_rate import PTAXRate
from numis_geek.models.transaction import FxSource, Transaction, TransactionSourceType
from numis_geek.models.user import UserRole
from numis_geek.services.auth import AuthService
from numis_geek.services.positions import compute_position
from numis_geek.services.user import UserService
from numis_geek.services.workspace import WorkspaceService

TEST_ENGINE = create_engine(
    "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
)
TestSession = sessionmaker(bind=TEST_ENGINE, autoflush=False, autocommit=False)
PTAX = Decimal("5.00000000")
TODAY = date.today()


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


def _asset(db, ws_id, acc_id, name, ticker, cls=AssetClass.CRYPTO, ccy=Currency.BRL, price=None, linked=None):
    a = Asset(
        id=str(uuid.uuid4()), workspace_id=ws_id, account_id=acc_id, asset_class=cls, country="BR",
        name=name, ticker=ticker, currency=ccy, current_price=price, is_active=True,
        linked_account_id=linked,
    )
    db.add(a)
    return a


@pytest.fixture(scope="module")
def seed():
    db = TestSession()
    ws = WorkspaceService(db).create("AP WS")
    ws2 = WorkspaceService(db).create("AP WS 2")
    UserService(db).create(ws.id, "ap_admin@test.com", "adminpass", UserRole.admin)
    UserService(db).create(ws2.id, "ap_admin2@test.com", "adminpass", UserRole.admin)
    now = datetime.now(timezone.utc)
    fi = FinancialInstitution(
        id=str(uuid.uuid4()), long_name="Coinbase", short_name="COINBASE", logo_slug="coinbase",
        is_active=True, created_at=now, updated_at=now,
    )
    db.add(fi)
    db.flush()
    start = TODAY - timedelta(days=400)
    for i in range(500):
        db.add(PTAXRate(id=str(uuid.uuid4()), date=start + timedelta(days=i), rate=PTAX, fetched_at=now))
    invest = Account(
        id=str(uuid.uuid4()), workspace_id=ws.id, financial_institution_id=fi.id, name="Coinbase",
        account_type=AccountType.investment, currency=Currency.BRL, is_active=True,
    )
    checking = Account(
        id=str(uuid.uuid4()), workspace_id=ws.id, financial_institution_id=fi.id, name="Conta Itaú",
        account_type=AccountType.checking, currency=Currency.BRL, is_active=True, balance_from_ledger=True,
    )
    db.add_all([invest, checking])
    db.flush()
    usdc = _asset(db, ws.id, invest.id, "Cripto Stablecoin de Dólar", "USDC", price=Decimal("5.40"))
    btc = _asset(db, ws.id, invest.id, "Bitcoin", "BTC", price=Decimal("600000"))
    fund = _asset(db, ws.id, invest.id, "Fundo X", None, cls=AssetClass.FUND)
    mirror = _asset(db, ws.id, invest.id, "Saldo Itaú", None, cls=AssetClass.CASH, linked=checking.id)
    root = Category(id=str(uuid.uuid4()), workspace_id=ws.id, name="Assinaturas", color="#00f")
    db.add(root)
    db.flush()
    sub = Category(id=str(uuid.uuid4()), workspace_id=ws.id, name="Serviços digitais", parent_id=root.id, kind=CategoryKind.EXPENSE)
    party = Party(id=str(uuid.uuid4()), workspace_id=ws.id, name="Coinbase", is_active=True)
    db.add_all([sub, party])
    db.flush()
    # 100 USDC comprados a R$ 5,00 → custo R$ 500.
    db.add(AssetMovement(
        id=str(uuid.uuid4()), workspace_id=ws.id, asset_id=usdc.id, type=AssetMovementType.BUY,
        event_date=TODAY - timedelta(days=200), quantity=Decimal("100"), unit_price=Decimal("5"),
        gross_amount=Decimal("500"), net_amount=Decimal("500"), currency=Currency.BRL, fx_rate=PTAX,
        is_active=True, created_at=now, updated_at=now,
    ))
    db.commit()
    ids = {
        "ws": ws.id, "invest": invest.id, "usdc": usdc.id, "btc": btc.id, "fund": fund.id,
        "mirror": mirror.id, "sub": sub.id, "root": root.id, "party": party.id,
        "token": AuthService(db).login("ap_admin@test.com", "adminpass"),
        "token2": AuthService(db).login("ap_admin2@test.com", "adminpass"),
    }
    db.close()
    return ids


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def d(days_ago: int) -> str:
    return (TODAY - timedelta(days=days_ago)).isoformat()


def pay(client, seed, token=None, **body):
    payload = {
        "direction": "EXPENSE", "asset_id": seed["usdc"], "event_date": d(30),
        "quantity": "10", "amount": "54.00", "description": "Coinbase One",
        "category_id": seed["sub"], "party_id": seed["party"],
    }
    payload.update(body)
    return client.post("/api/transactions/asset-payment", json=payload, headers=auth(token or seed["token"]))


def _movement(mid) -> AssetMovement:
    db = TestSession()
    try:
        return db.get(AssetMovement, mid)
    finally:
        db.close()


# ── model invariant ───────────────────────────────────────────────────────────

def test_check_rejects_asset_movement_plus_checking(seed):
    db = TestSession()
    try:
        m = db.query(AssetMovement).filter(AssetMovement.asset_id == seed["usdc"]).first()
        acc = db.query(Account).filter(Account.account_type == AccountType.checking).first()
        base = dict(
            workspace_id=seed["ws"], source_type=TransactionSourceType.ASSET, event_date=TODAY,
            description="x", amount=Decimal("-1"), currency=Currency.BRL, fx_rate=PTAX,
            fx_source=FxSource.PTAX, amount_brl=Decimal("-1"), amount_usd=Decimal("-0.2"), fingerprint="f" * 40,
        )
        db.add(Transaction(id=str(uuid.uuid4()), asset_movement_id=m.id, checking_account_id=acc.id, **base))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()
        db.add(Transaction(id=str(uuid.uuid4()), **base))  # nenhuma fonte
        with pytest.raises(IntegrityError):
            db.flush()
    finally:
        db.rollback()
        db.close()


def test_generic_create_refuses_asset(client, seed):
    r = client.post("/api/transactions", json={
        "source_type": "ASSET", "event_date": d(1), "description": "x", "amount": "-1",
    }, headers=auth(seed["token"]))
    assert r.status_code == 422
    assert "asset-payment" in r.json()["detail"]


# ── Movimentações → Pago com ativo ────────────────────────────────────────────

def test_expense_paid_with_asset_creates_pair(client, seed):
    r = pay(client, seed)
    assert r.status_code == 201, r.text
    tx = r.json()
    assert tx["source_type"] == "ASSET"
    assert tx["amount"] == -54.0
    assert tx["currency"] == "BRL"
    assert tx["fx_source"] == "PTAX"
    assert tx["asset_ticker"] == "USDC"
    assert tx["asset_quantity"] == 10.0
    assert tx["financial_institution_name"] == "COINBASE"
    assert tx["category_id"] == seed["sub"] and tx["party_id"] == seed["party"]
    assert tx["checking_account_id"] is None and tx["credit_card_account_id"] is None
    assert tx["is_reconciled"] is True  # sem extrato pra conciliar
    m = _movement(tx["asset_movement_id"])
    assert m.type == AssetMovementType.SELL
    assert m.quantity == Decimal("10") and m.gross_amount == Decimal("54.00") and m.net_amount == Decimal("54.00")
    assert m.unit_price == Decimal("5.40")
    assert m.event_date.isoformat() == d(30)
    db = TestSession()
    try:
        actions = {a.action for a in db.query(AuditLog).filter(AuditLog.resource_id.in_([tx["id"], m.id])).all()}
    finally:
        db.close()
    assert {"transaction.created", "asset_movement.created"} <= actions


def test_sell_reduces_cost_proportionally(client, seed):
    # Depois do teste anterior: 100 USDC a R$ 5 → pagou 10 → custo cai 10%.
    db = TestSession()
    try:
        pos = compute_position(db, seed["usdc"])
    finally:
        db.close()
    assert pos["quantity_held"] == Decimal("90")
    assert pos["total_invested_brl"].quantize(Decimal("0.01")) == Decimal("450.00")


def test_income_received_in_asset_is_buy_with_given_cost(client, seed):
    r = pay(client, seed, direction="INCOME", asset_id=seed["btc"], quantity="0.0001",
            amount="60.00", description="Cashback em BTC", category_id=None, party_id=None)
    assert r.status_code == 201, r.text
    tx = r.json()
    assert tx["amount"] == 60.0
    m = _movement(tx["asset_movement_id"])
    assert m.type == AssetMovementType.BUY
    db = TestSession()
    try:
        pos = compute_position(db, seed["btc"])
    finally:
        db.close()
    assert pos["quantity_held"] == Decimal("0.0001")
    assert pos["total_invested_brl"].quantize(Decimal("0.01")) == Decimal("60.00")


def test_value_mode_asset_forces_quantity_one(client, seed):
    r = pay(client, seed, asset_id=seed["fund"], quantity=None, amount="100", description="Pagou com fundo")
    assert r.status_code == 201, r.text
    m = _movement(r.json()["asset_movement_id"])
    assert m.quantity == Decimal("1") and m.unit_price == Decimal("100")


@pytest.mark.parametrize("override,status,msg", [
    ({"direction": "SIDEWAYS"}, 422, "Direção"),
    ({"amount": "0"}, 422, None),
    ({"quantity": None}, 422, "quantidade"),
    ({"quantity": "-1"}, 422, "Quantidade"),
    ({"description": "  "}, 422, "Descrição"),
    ({"category_id": "nope"}, 422, "Categoria"),
])
def test_asset_payment_validation(client, seed, override, status, msg):
    r = pay(client, seed, **override)
    assert r.status_code == status, r.text
    if msg:
        assert msg in r.json()["detail"]


def test_mirror_cash_asset_is_refused(client, seed):
    r = pay(client, seed, asset_id=seed["mirror"], quantity=None)
    assert r.status_code == 422
    assert "conta corrente" in r.json()["detail"]


def test_other_workspace_asset_is_not_found(client, seed):
    r = pay(client, seed, token=seed["token2"])
    assert r.status_code == 422
    assert "Ativo não encontrado" in r.json()["detail"]


# ── edição vinculada ──────────────────────────────────────────────────────────

def test_editing_tx_updates_movement(client, seed):
    tx = pay(client, seed, description="Editável").json()
    r = client.patch(f"/api/transactions/{tx['id']}", json={
        "amount": "-81.00", "event_date": d(20), "asset_quantity": "15",
    }, headers=auth(seed["token"]))
    assert r.status_code == 200, r.text
    assert r.json()[0]["asset_quantity"] == 15.0
    m = _movement(tx["asset_movement_id"])
    assert m.gross_amount == Decimal("81.00") and m.net_amount == Decimal("81.00")
    assert m.quantity == Decimal("15") and m.unit_price == Decimal("5.40")
    assert m.event_date.isoformat() == d(20)


def test_tx_cannot_flip_direction(client, seed):
    tx = pay(client, seed, description="Sem flip").json()
    r = client.patch(f"/api/transactions/{tx['id']}", json={"amount": "10"}, headers=auth(seed["token"]))
    assert r.status_code == 409


def test_asset_quantity_only_on_asset_tx(client, seed):
    db = TestSession()
    try:
        acc = db.query(Account).filter(Account.account_type == AccountType.checking).first().id
    finally:
        db.close()
    tx = client.post("/api/transactions", json={
        "source_type": "CHECKING", "checking_account_id": acc, "event_date": d(3),
        "description": "Padaria", "amount": "-10",
    }, headers=auth(seed["token"])).json()[0]
    r = client.patch(f"/api/transactions/{tx['id']}", json={"asset_quantity": "1"}, headers=auth(seed["token"]))
    assert r.status_code == 422


def test_editing_movement_updates_tx(client, seed):
    tx = pay(client, seed, description="Pelo lado do ativo").json()
    mid = tx["asset_movement_id"]
    r = client.put(f"/api/asset-movements/{mid}", json={
        "asset_id": seed["usdc"], "type": "SELL", "event_date": d(25),
        "quantity": "20", "unit_price": "5.5",
    }, headers=auth(seed["token"]))
    assert r.status_code == 200, r.text
    assert r.json()["linked_transaction_id"] == tx["id"]
    t = client.get(f"/api/transactions/{tx['id']}", headers=auth(seed["token"])).json()
    assert t["amount"] == -110.0
    assert t["event_date"] == d(25)
    assert t["asset_quantity"] == 20.0


def test_linked_movement_cannot_change_type_or_asset(client, seed):
    tx = pay(client, seed, description="Travado").json()
    mid = tx["asset_movement_id"]
    for body in ({"asset_id": seed["usdc"], "type": "BUY"}, {"asset_id": seed["btc"], "type": "SELL"}):
        r = client.put(f"/api/asset-movements/{mid}", json={
            **body, "event_date": d(30), "quantity": "10", "unit_price": "5.4",
        }, headers=auth(seed["token"]))
        assert r.status_code == 409, r.text


# ── Lançamentos → "Foi uma despesa / receita" ─────────────────────────────────

def test_movement_composer_creates_linked_expense(client, seed):
    r = client.post("/api/asset-movements", json={
        "asset_id": seed["usdc"], "type": "SELL", "event_date": d(15),
        "quantity": "5", "unit_price": "5.40",
        "linked_transaction": {"description": "Domínio .com", "category_id": seed["sub"], "party_id": seed["party"]},
    }, headers=auth(seed["token"]))
    assert r.status_code == 201, r.text
    m = r.json()
    assert m["linked_transaction_description"] == "Domínio .com"
    assert m["linked_transaction_category_name"] == "Serviços digitais"
    assert m["linked_transaction_amount"] == -27.0
    listed = client.get(f"/api/asset-movements?asset_id={seed['usdc']}", headers=auth(seed["token"])).json()["items"]
    assert any(i["id"] == m["id"] and i["linked_transaction_id"] for i in listed)


def test_linking_existing_movement_via_update(client, seed):
    """Backfill: SELL já lançado na reconciliação ganha a despesa depois."""
    r = client.post("/api/asset-movements", json={
        "asset_id": seed["usdc"], "type": "SELL", "event_date": d(40),
        "quantity": "47.537572", "gross_amount": "239.98", "unit_price": "5.04821744",
        "notes": "Coinbase One Subscription pago com USDC",
    }, headers=auth(seed["token"]))
    mid = r.json()["id"]
    assert r.json()["linked_transaction_id"] is None
    body = {
        "asset_id": seed["usdc"], "type": "SELL", "event_date": d(40),
        "quantity": "47.537572", "gross_amount": "239.98", "unit_price": "5.04821744",
        "notes": "Coinbase One Subscription pago com USDC",
        "linked_transaction": {"description": "Coinbase One", "category_id": seed["sub"], "party_id": seed["party"]},
    }
    r = client.put(f"/api/asset-movements/{mid}", json=body, headers=auth(seed["token"]))
    assert r.status_code == 200, r.text
    assert r.json()["linked_transaction_amount"] == -239.98
    again = client.put(f"/api/asset-movements/{mid}", json=body, headers=auth(seed["token"]))
    assert again.status_code == 409


def test_bonus_cannot_be_linked(client, seed):
    r = client.post("/api/asset-movements", json={
        "asset_id": seed["usdc"], "type": "BONUS", "event_date": d(5), "quantity": "1",
        "linked_transaction": {"description": "x"},
    }, headers=auth(seed["token"]))
    assert r.status_code == 422


# ── remoção vinculada ─────────────────────────────────────────────────────────

def test_deleting_tx_deactivates_movement(client, seed):
    tx = pay(client, seed, description="Apagar pela tx").json()
    r = client.delete(f"/api/transactions/{tx['id']}", headers=auth(seed["token"]))
    assert r.status_code == 204
    assert _movement(tx["asset_movement_id"]).is_active is False


def test_deactivating_movement_deletes_tx(client, seed):
    tx = pay(client, seed, description="Apagar pelo lançamento").json()
    r = client.put(f"/api/asset-movements/{tx['asset_movement_id']}/deactivate", headers=auth(seed["token"]))
    assert r.status_code == 200, r.text
    assert client.get(f"/api/transactions/{tx['id']}", headers=auth(seed["token"])).status_code == 404


# ── relatórios ────────────────────────────────────────────────────────────────

def test_summary_and_source_filter_count_asset_expense(client, seed):
    h = auth(seed["token"])
    pay(client, seed, description="Relatório", amount="12.34", event_date=d(2))
    s = client.get(f"/api/transactions/summary?from={d(2)}&to={d(2)}", headers=h).json()
    assert s["outflows"]["brl"] == -12.34
    only_assets = client.get(f"/api/transactions?from={d(2)}&to={d(2)}&asset_source=true", headers=h).json()
    assert [i["description"] for i in only_assets["items"]] == ["Relatório"]
    by_cat = client.get(f"/api/transactions?category_id={seed['sub']}&from={d(2)}", headers=h).json()
    assert any(i["description"] == "Relatório" for i in by_cat["items"])


# ── regressões do audit adversarial (2026-11-02) ──────────────────────────────

def _sell_with_fee_linked(client, seed, description):
    r = client.post("/api/asset-movements", json={
        "asset_id": seed["usdc"], "type": "SELL", "event_date": d(12),
        "quantity": "10", "unit_price": "5.40", "fee": "1.50",
        "linked_transaction": {"description": description},
    }, headers=auth(seed["token"]))
    assert r.status_code == 201, r.text
    return r.json()


def test_tx_edit_without_amount_keeps_fee_and_unit_price(client, seed):
    m = _sell_with_fee_linked(client, seed, "Com taxa")
    for body in ({"is_reconciled": False}, {"description": "Com taxa (renomeada)"}):
        r = client.patch(f"/api/transactions/{m['linked_transaction_id']}", json=body, headers=auth(seed["token"]))
        assert r.status_code == 200, r.text
    mov = _movement(m["id"])
    assert mov.fee == Decimal("1.50")
    assert mov.net_amount == Decimal("52.50")
    assert mov.unit_price == Decimal("5.40")


def test_tx_amount_edit_keeps_fee_in_net(client, seed):
    m = _sell_with_fee_linked(client, seed, "Taxa no net")
    r = client.patch(f"/api/transactions/{m['linked_transaction_id']}", json={"amount": "-60.00"}, headers=auth(seed["token"]))
    assert r.status_code == 200, r.text
    mov = _movement(m["id"])
    assert mov.gross_amount == Decimal("60.00")
    assert mov.fee == Decimal("1.50")
    assert mov.net_amount == Decimal("58.50")
    assert mov.unit_price == Decimal("6.00")


def test_asset_page_movements_carry_the_link(client, seed):
    tx = pay(client, seed, description="Na página do ativo").json()
    items = client.get(f"/api/assets/{seed['usdc']}/asset-movements?page_size=200", headers=auth(seed["token"])).json()["items"]
    row = next(i for i in items if i["id"] == tx["asset_movement_id"])
    assert row["linked_transaction_id"] == tx["id"]
    assert row["linked_transaction_description"] == "Na página do ativo"


def test_option_asset_is_refused(client, seed):
    db = TestSession()
    try:
        opt = _asset(db, seed["ws"], seed["invest"], "PETRX40", "PETRX40", cls=AssetClass.OPTION)
        db.commit()
        opt_id = opt.id
    finally:
        db.close()
    r = pay(client, seed, asset_id=opt_id)
    assert r.status_code == 422
    assert "Opção" in r.json()["detail"]


def test_unit_price_rounding_to_zero_is_refused(client, seed):
    r = pay(client, seed, quantity="123456789", amount="0.01")
    assert r.status_code == 422
    assert "preço unitário" in r.json()["detail"]


def test_check_ties_source_type_to_fk(seed):
    db = TestSession()
    try:
        m = db.query(AssetMovement).filter(AssetMovement.asset_id == seed["usdc"]).first()
        db.add(Transaction(
            id=str(uuid.uuid4()), workspace_id=seed["ws"], source_type=TransactionSourceType.CHECKING,
            asset_movement_id=m.id, event_date=TODAY, description="x", amount=Decimal("-1"),
            currency=Currency.BRL, fx_rate=PTAX, fx_source=FxSource.PTAX, amount_brl=Decimal("-1"),
            amount_usd=Decimal("-0.2"), fingerprint="f" * 40,
        ))
        with pytest.raises(IntegrityError):
            db.flush()
    finally:
        db.rollback()
        db.close()


def test_deactivating_movement_reverts_settled_payable_with_audit(client, seed):
    h = auth(seed["token"])
    tx = pay(client, seed, description="Coinbase One mensal").json()
    occ = client.post("/api/scheduled-transactions", json={
        "direction": "PAYABLE", "description": "Coinbase One", "amount": "54.00", "due_date": d(30),
    }, headers=h)
    assert occ.status_code == 201, occ.text
    occ_id = occ.json()["id"]
    paid = client.post(f"/api/scheduled-transactions/{occ_id}/pay", json={"paid_at": d(30), "transaction_id": tx["id"]}, headers=h)
    assert paid.status_code == 200, paid.text
    r = client.put(f"/api/asset-movements/{tx['asset_movement_id']}/deactivate", headers=h)
    assert r.status_code == 200, r.text
    db = TestSession()
    try:
        actions = [a.action for a in db.query(AuditLog).filter(AuditLog.resource_id == occ_id).all()]
    finally:
        db.close()
    assert "scheduled_transaction.payment_reverted" in actions
