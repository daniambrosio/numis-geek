"""Spec 70 — Transactions: model invariants, services and API.

Covers: exclusive source FK (CHECK), fingerprint on every write, fx
always resolved (PTAX walkback / STATEMENT), card tx landing in the right
invoice (lazy OPEN creation, drifted close_date), installments, the
single pay_invoice path, transfers between own accounts, delete cascade
rules, summary cut at today, filters, workspace isolation, and the
spec 68 hooks (party merge re-point, tag in use).
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
from numis_geek.models.category import Category, CategoryKind
from numis_geek.models.credit_card import CreditCardAccount, Invoice, InvoiceStatus
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.party import Party
from numis_geek.models.ptax_rate import PTAXRate
from numis_geek.models.tag import Tag
from numis_geek.models.transaction import FxSource, Transaction, TransactionSourceType
from numis_geek.models.user import UserRole
from numis_geek.services import transactions as svc
from numis_geek.services.auth import AuthService
from numis_geek.services.user import UserService
from numis_geek.services.workspace import WorkspaceService

TEST_ENGINE = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
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


def _account(db, ws_id, fi_id, name, account_type=AccountType.checking, currency=Currency.BRL):
    a = Account(
        id=str(uuid.uuid4()), workspace_id=ws_id, financial_institution_id=fi_id,
        name=name, account_type=account_type, currency=currency, is_active=True,
    )
    db.add(a)
    return a


@pytest.fixture(scope="module")
def seed():
    db = TestSession()
    ws = WorkspaceService(db).create("TX WS")
    ws2 = WorkspaceService(db).create("TX WS 2")
    UserService(db).create(ws.id, "tx_admin@test.com", "adminpass", UserRole.admin)
    UserService(db).create(ws.id, "tx_member@test.com", "memberpass", UserRole.member)
    UserService(db).create(ws2.id, "tx_admin2@test.com", "adminpass", UserRole.admin)
    now = datetime.now(timezone.utc)
    fi = FinancialInstitution(
        id=str(uuid.uuid4()), long_name="Banco TX", short_name="BTX", logo_slug="btx",
        is_active=True, created_at=now, updated_at=now,
    )
    db.add(fi)
    db.flush()
    # PTAX every day for the last ~400 days and the next ~800 (parcelas futuras)
    start = TODAY - timedelta(days=400)
    for i in range(1200):
        db.add(PTAXRate(id=str(uuid.uuid4()), date=start + timedelta(days=i), rate=PTAX, fetched_at=now))
    itau = _account(db, ws.id, fi.id, "Conta Corrente Itaú")
    wise = _account(db, ws.id, fi.id, "Conta Corrente Wise")
    nomad = _account(db, ws.id, fi.id, "Conta Corrente Nomad", currency=Currency.USD)
    invest = _account(db, ws.id, fi.id, "Conta Investimento", account_type=AccountType.investment)
    other_ws_acc = _account(db, ws2.id, fi.id, "Conta WS2")
    card = CreditCardAccount(
        id=str(uuid.uuid4()), workspace_id=ws.id, financial_institution_id=fi.id,
        name="BTX Visa", currency=Currency.BRL, credit_limit=Decimal("10000"),
        close_day=5, due_day=15, is_active=True,
    )
    db.add(card)
    root = Category(id=str(uuid.uuid4()), workspace_id=ws.id, name="Alimentação", color="#ff0000")
    db.add(root)
    db.flush()
    sub = Category(id=str(uuid.uuid4()), workspace_id=ws.id, name="Mercado", parent_id=root.id, kind=CategoryKind.EXPENSE)
    db.add(sub)
    db.commit()
    ids = {
        "ws_id": ws.id, "ws2_id": ws2.id, "fi_id": fi.id, "itau": itau.id, "wise": wise.id,
        "nomad": nomad.id, "invest": invest.id, "other_ws_acc": other_ws_acc.id,
        "card": card.id, "root": root.id, "sub": sub.id,
    }
    ids["admin_token"] = AuthService(db).login("tx_admin@test.com", "adminpass")
    ids["member_token"] = AuthService(db).login("tx_member@test.com", "memberpass")
    ids["admin2_token"] = AuthService(db).login("tx_admin2@test.com", "adminpass")
    db.close()
    return ids


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def d(days_ago: int) -> str:
    return (TODAY - timedelta(days=days_ago)).isoformat()


def post_tx(client, seed, token=None, **body):
    payload = {"source_type": "CHECKING", "checking_account_id": seed["itau"],
               "event_date": d(10), "description": "Padaria", "amount": "-25.50"}
    payload.update(body)
    return client.post("/api/transactions", json=payload, headers=auth(token or seed["admin_token"]))


# ── pure helpers ──────────────────────────────────────────────────────────────

def test_fingerprint_uses_normalized_description():
    a = svc.compute_fingerprint(TransactionSourceType.CHECKING, "acc", date(2026, 10, 1), Decimal("-10"), Currency.BRL, "PAO ACUCAR 0042 SP")
    b = svc.compute_fingerprint(TransactionSourceType.CHECKING, "acc", date(2026, 10, 1), Decimal("-10.00"), Currency.BRL, "pao acucar")
    c = svc.compute_fingerprint(TransactionSourceType.CHECKING, "acc", date(2026, 10, 2), Decimal("-10"), Currency.BRL, "pao acucar")
    assert a == b
    assert a != c
    assert len(a) == 40


def test_convert_amounts_both_currencies():
    assert svc.convert_amounts(Decimal("-100"), Currency.BRL, Decimal("5")) == (Decimal("-100.00"), Decimal("-20.00"))
    assert svc.convert_amounts(Decimal("20"), Currency.USD, Decimal("5")) == (Decimal("100.00"), Decimal("20.00"))


@pytest.mark.parametrize("total,n", [(Decimal("100"), 3), (Decimal("-100"), 3), (Decimal("-1200"), 12), (Decimal("0.05"), 4)])
def test_split_installments_sums_exactly(total, n):
    parts = svc.split_installments(total, n)
    assert len(parts) == n
    assert sum(parts) == total
    assert len(set(parts[1:])) <= 1


def test_split_installments_first_absorbs_remainder():
    assert svc.split_installments(Decimal("-100"), 3) == [Decimal("-33.34"), Decimal("-33.33"), Decimal("-33.33")]


def test_theoretical_close_and_due_dates():
    card = CreditCardAccount(close_day=5, due_day=15)
    assert svc.theoretical_close_date(card, date(2026, 10, 3)) == date(2026, 10, 5)
    assert svc.theoretical_close_date(card, date(2026, 10, 5)) == date(2026, 10, 5)
    assert svc.theoretical_close_date(card, date(2026, 10, 6)) == date(2026, 11, 5)
    assert svc.theoretical_close_date(card, date(2026, 12, 20)) == date(2027, 1, 5)
    assert svc.theoretical_due_date(card, date(2026, 10, 5)) == date(2026, 10, 15)
    late = CreditCardAccount(close_day=25, due_day=5)
    assert svc.theoretical_due_date(late, date(2026, 10, 25)) == date(2026, 11, 5)


def test_add_months_clamps_day():
    assert svc.add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert svc.add_months(date(2026, 11, 15), 3) == date(2027, 2, 15)


# ── model invariant ───────────────────────────────────────────────────────────

def test_check_constraint_exactly_one_source(seed):
    db = TestSession()
    try:
        tx = Transaction(
            id=str(uuid.uuid4()), workspace_id=seed["ws_id"], source_type=TransactionSourceType.CHECKING,
            checking_account_id=seed["itau"], credit_card_account_id=seed["card"],
            event_date=TODAY, description="x", amount=Decimal("-1"), currency=Currency.BRL,
            fx_rate=PTAX, fx_source=FxSource.PTAX, amount_brl=Decimal("-1"), amount_usd=Decimal("-0.2"),
            fingerprint="f" * 40,
        )
        db.add(tx)
        with pytest.raises(IntegrityError):
            db.flush()
    finally:
        db.rollback()
        db.close()


# ── checking tx ───────────────────────────────────────────────────────────────

def test_create_checking_tx_resolves_fx_and_fingerprint(client, seed):
    r = post_tx(client, seed, category_id=seed["sub"])
    assert r.status_code == 201, r.text
    [tx] = r.json()
    assert tx["fx_rate"] == 5.0
    assert tx["fx_source"] == "PTAX"
    assert tx["amount_brl"] == -25.5
    assert tx["amount_usd"] == -5.1
    assert tx["account_name"] == "Conta Corrente Itaú"
    assert tx["fi_logo_slug"] == "btx"
    assert tx["category_name"] == "Mercado"
    assert tx["category_parent_name"] == "Alimentação"
    assert tx["category_color"] == "#ff0000"   # herdada da raiz
    db = TestSession()
    row = db.get(Transaction, tx["id"])
    assert row.fingerprint == svc.compute_fingerprint(
        TransactionSourceType.CHECKING, seed["itau"], row.event_date, Decimal("-25.50"), Currency.BRL, "Padaria",
    )
    db.close()


def test_member_can_create(client, seed):
    r = post_tx(client, seed, token=seed["member_token"], description="Farmácia", amount="-40")
    assert r.status_code == 201


def test_statement_fx_rate_wins(client, seed):
    r = post_tx(client, seed, checking_account_id=seed["nomad"], amount="-10", fx_rate="5.40", description="Starbucks NY")
    assert r.status_code == 201
    [tx] = r.json()
    assert tx["currency"] == "USD"
    assert tx["fx_source"] == "STATEMENT"
    assert tx["amount_brl"] == -54.0
    assert tx["amount_usd"] == -10.0


def test_no_ptax_in_window_is_422(client, seed):
    r = post_tx(client, seed, event_date="2001-01-10")
    assert r.status_code == 422
    assert "PTAX" in r.json()["detail"]


@pytest.mark.parametrize("override,msg", [
    ({"checking_account_id": "invest"}, "checking"),
    ({"checking_account_id": "other_ws_acc"}, "não encontrada"),
    ({"category_id": "root"}, "subcategoria"),
    ({"amount": "0"}, "zero"),
    ({"description": "  "}, "Descrição"),
    ({"installments": 3}, "Parcelamento"),
])
def test_checking_validation_422(client, seed, override, msg):
    body = {k: seed.get(v, v) if isinstance(v, str) else v for k, v in override.items()}
    r = post_tx(client, seed, **body)
    assert r.status_code == 422
    assert msg in r.json()["detail"]


# ── card tx / invoices ────────────────────────────────────────────────────────

def _invoices(db, card_id):
    return db.query(Invoice).filter(Invoice.credit_card_account_id == card_id).order_by(Invoice.close_date).all()


def test_card_tx_creates_open_invoice_lazily(client, seed):
    ev = date(TODAY.year, TODAY.month, 1) + timedelta(days=60)   # futuro, data estável
    ev = ev.replace(day=10)
    r = client.post("/api/transactions", json={
        "source_type": "CREDIT_CARD", "credit_card_account_id": seed["card"],
        "event_date": ev.isoformat(), "description": "Livraria", "amount": "-120",
    }, headers=auth(seed["admin_token"]))
    assert r.status_code == 201, r.text
    [tx] = r.json()
    db = TestSession()
    inv = db.get(Invoice, tx["invoice_id"])
    assert inv.status == InvoiceStatus.OPEN
    assert inv.close_date == svc.add_months(ev, 1, 5)
    assert inv.due_date == svc.add_months(ev, 1, 15)
    db.close()
    # second purchase in the same period reuses the invoice
    r2 = client.post("/api/transactions", json={
        "source_type": "CREDIT_CARD", "credit_card_account_id": seed["card"],
        "event_date": (ev + timedelta(days=5)).isoformat(), "description": "Cinema", "amount": "-30",
    }, headers=auth(seed["admin_token"]))
    assert r2.json()[0]["invoice_id"] == tx["invoice_id"]
    seed["future_invoice"] = tx["invoice_id"]


def test_purchase_after_drifted_close_goes_to_next_invoice(seed):
    """close_day=5 mas a fatura real fechou dia 3: compra no dia 4 é da próxima."""
    db = TestSession()
    card = db.get(CreditCardAccount, seed["card"])
    early = Invoice(
        id=str(uuid.uuid4()), workspace_id=seed["ws_id"], credit_card_account_id=card.id,
        close_date=date(2031, 3, 3), due_date=date(2031, 3, 15), currency=Currency.BRL,
        status=InvoiceStatus.OPEN,
    )
    db.add(early)
    db.flush()
    assert svc.resolve_invoice(db, card, date(2031, 3, 2)).id == early.id
    nxt = svc.resolve_invoice(db, card, date(2031, 3, 4))
    assert nxt.id != early.id
    assert nxt.close_date == date(2031, 4, 5)
    db.rollback()
    db.close()


def test_card_tx_shows_in_open_invoice_total(client, seed):
    cards = client.get("/api/credit-cards", headers=auth(seed["admin_token"])).json()
    card = next(c for c in cards if c["id"] == seed["card"])
    assert card["open_invoice_total"] == 150.0
    assert card["limit_used_pct"] == pytest.approx(0.015)


def test_installments_one_per_invoice(client, seed):
    ev = date(2032, 1, 10)
    r = client.post("/api/transactions", json={
        "source_type": "CREDIT_CARD", "credit_card_account_id": seed["card"],
        "event_date": ev.isoformat(), "description": "Notebook", "amount": "-1000",
        "installments": 3,
    }, headers=auth(seed["admin_token"]))
    assert r.status_code == 201, r.text
    rows = r.json()
    assert [t["installment_number"] for t in rows] == [1, 2, 3]
    assert {t["installment_total"] for t in rows} == {3}
    assert [t["amount"] for t in rows] == [-333.34, -333.33, -333.33]
    assert rows[0]["parent_transaction_id"] is None
    assert {t["parent_transaction_id"] for t in rows[1:]} == {rows[0]["id"]}
    assert len({t["invoice_id"] for t in rows}) == 3
    assert [t["event_date"] for t in rows] == ["2032-01-10", "2032-02-10", "2032-03-10"]
    seed["installment_parent"] = rows[0]["id"]


def test_installments_from_given_invoice(client, seed):
    db = TestSession()
    inv = Invoice(
        id=str(uuid.uuid4()), workspace_id=seed["ws_id"], credit_card_account_id=seed["card"],
        close_date=date(2033, 6, 6), due_date=date(2033, 6, 15), currency=Currency.BRL, status=InvoiceStatus.OPEN,
    )
    db.add(inv)
    db.commit()
    inv_id = inv.id
    db.close()
    r = client.post("/api/transactions", json={
        "source_type": "CREDIT_CARD", "credit_card_account_id": seed["card"], "invoice_id": inv_id,
        "event_date": "2033-05-20", "description": "Geladeira", "amount": "-600", "installments": 2,
    }, headers=auth(seed["admin_token"]))
    assert r.status_code == 201, r.text
    rows = r.json()
    assert rows[0]["invoice_id"] == inv_id
    db = TestSession()
    second = db.get(Invoice, rows[1]["invoice_id"])
    assert second.close_date == date(2033, 7, 5)
    db.close()


def test_card_tx_with_invoice_of_other_card_is_422(client, seed):
    db = TestSession()
    other = CreditCardAccount(
        id=str(uuid.uuid4()), workspace_id=seed["ws_id"], financial_institution_id=seed["fi_id"],
        name="Outro", currency=Currency.BRL, close_day=10, due_day=20, is_active=True,
    )
    db.add(other)
    db.flush()
    inv = Invoice(
        id=str(uuid.uuid4()), workspace_id=seed["ws_id"], credit_card_account_id=other.id,
        close_date=date(2034, 1, 10), due_date=date(2034, 1, 20), currency=Currency.BRL, status=InvoiceStatus.OPEN,
    )
    db.add(inv)
    db.commit()
    inv_id = inv.id
    db.close()
    r = client.post("/api/transactions", json={
        "source_type": "CREDIT_CARD", "credit_card_account_id": seed["card"], "invoice_id": inv_id,
        "event_date": "2034-01-05", "description": "X", "amount": "-1",
    }, headers=auth(seed["admin_token"]))
    assert r.status_code == 422


def test_card_tx_rejects_checking_fk(client, seed):
    r = client.post("/api/transactions", json={
        "source_type": "CREDIT_CARD", "credit_card_account_id": seed["card"], "checking_account_id": seed["itau"],
        "event_date": d(1), "description": "X", "amount": "-1",
    }, headers=auth(seed["admin_token"]))
    assert r.status_code == 422


# ── close / pay invoice ───────────────────────────────────────────────────────

def test_close_without_total_freezes_tx_sum(client, seed):
    r = client.post(f"/api/invoices/{seed['future_invoice']}/close", json={}, headers=auth(seed["admin_token"]))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "CLOSED"
    assert r.json()["total_amount"] == 150.0


def test_pay_invoice_is_atomic_and_single_path(client, seed):
    inv_id = seed["future_invoice"]
    r = client.post(f"/api/invoices/{inv_id}/pay", json={
        "checking_account_id": seed["itau"], "paid_on": d(0),
    }, headers=auth(seed["admin_token"]))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "PAID"
    assert r.json()["paid_at"] == d(0)
    db = TestSession()
    inv = db.get(Invoice, inv_id)
    pay_tx = db.get(Transaction, inv.paid_by_transaction_id)
    assert pay_tx.paid_invoice_id == inv_id
    assert pay_tx.amount == Decimal("-150.00")
    assert pay_tx.checking_account_id == seed["itau"]
    assert pay_tx.fingerprint
    seed["pay_tx"] = pay_tx.id
    db.close()
    again = client.post(f"/api/invoices/{inv_id}/pay", json={
        "checking_account_id": seed["itau"], "paid_on": d(0),
    }, headers=auth(seed["admin_token"]))
    assert again.status_code == 409


def test_paid_invoice_is_frozen_for_card_tx(client, seed):
    db = TestSession()
    inv = db.get(Invoice, seed["future_invoice"])
    ev = inv.close_date - timedelta(days=2)
    card_tx = db.query(Transaction).filter(Transaction.invoice_id == inv.id).first()
    card_tx_id = card_tx.id
    db.close()
    r = client.post("/api/transactions", json={
        "source_type": "CREDIT_CARD", "credit_card_account_id": seed["card"],
        "event_date": ev.isoformat(), "description": "Atrasada", "amount": "-5",
    }, headers=auth(seed["admin_token"]))
    assert r.status_code == 409
    r2 = client.patch(f"/api/transactions/{card_tx_id}", json={"description": "y"}, headers=auth(seed["admin_token"]))
    assert r2.status_code == 409


def test_payment_amount_is_not_editable(client, seed):
    r = client.patch(f"/api/transactions/{seed['pay_tx']}", json={"amount": "-1"}, headers=auth(seed["admin_token"]))
    assert r.status_code == 409


def test_deleting_payment_reopens_invoice_as_closed(client, seed):
    r = client.delete(f"/api/transactions/{seed['pay_tx']}", headers=auth(seed["admin_token"]))
    assert r.status_code == 204
    db = TestSession()
    inv = db.get(Invoice, seed["future_invoice"])
    assert inv.status == InvoiceStatus.CLOSED
    assert inv.paid_at is None
    assert inv.paid_by_transaction_id is None
    db.close()


def test_pay_open_invoice_without_total_or_tx_is_422(client, seed):
    db = TestSession()
    inv = Invoice(
        id=str(uuid.uuid4()), workspace_id=seed["ws_id"], credit_card_account_id=seed["card"],
        close_date=date(2035, 1, 5), due_date=date(2035, 1, 15), currency=Currency.BRL, status=InvoiceStatus.CLOSED,
    )
    db.add(inv)
    db.commit()
    inv_id = inv.id
    db.close()
    r = client.post(f"/api/invoices/{inv_id}/pay", json={"checking_account_id": seed["itau"], "paid_on": d(0)},
                    headers=auth(seed["admin_token"]))
    assert r.status_code == 422
    r2 = client.post(f"/api/invoices/{inv_id}/pay", json={"checking_account_id": seed["nomad"], "paid_on": d(0), "amount": "-3"},
                     headers=auth(seed["admin_token"]))
    assert r2.status_code == 422


# ── transfers ─────────────────────────────────────────────────────────────────

def test_transfer_same_currency(client, seed):
    r = client.post("/api/transactions/transfer", json={
        "from_account_id": seed["itau"], "to_account_id": seed["wise"],
        "event_date": d(5), "amount_out": "1000",
    }, headers=auth(seed["admin_token"]))
    assert r.status_code == 201, r.text
    out, inn = r.json()
    assert out["amount"] == -1000.0 and out["checking_account_id"] == seed["itau"]
    assert inn["amount"] == 1000.0 and inn["checking_account_id"] == seed["wise"]
    assert out["transfer_group_id"] == inn["transfer_group_id"] is not None
    seed["transfer_leg"] = out["id"]
    seed["transfer_other"] = inn["id"]


def test_transfer_cross_currency_uses_implied_rate(client, seed):
    r = client.post("/api/transactions/transfer", json={
        "from_account_id": seed["itau"], "to_account_id": seed["nomad"],
        "event_date": d(5), "amount_out": "5279.79", "amount_in": "1000",
    }, headers=auth(seed["admin_token"]))
    assert r.status_code == 201, r.text
    out, inn = r.json()
    assert out["currency"] == "BRL" and inn["currency"] == "USD"
    assert out["fx_source"] == inn["fx_source"] == "STATEMENT"
    assert out["fx_rate"] == pytest.approx(5.27979)
    assert inn["amount_brl"] == pytest.approx(5279.79)
    assert out["amount_usd"] == pytest.approx(-1000.0)


@pytest.mark.parametrize("body,msg", [
    ({"to_account_id": "itau"}, "mesma conta"),
    ({"to_account_id": "nomad"}, "Moedas diferentes"),
    ({"amount_out": "-5"}, "positivo"),
    ({"amount_in": "999"}, "Mesma moeda"),
    ({"to_account_id": "invest"}, "checking"),
])
def test_transfer_validation(client, seed, body, msg):
    payload = {"from_account_id": seed["itau"], "to_account_id": seed["wise"], "event_date": d(5), "amount_out": "10"}
    payload.update({k: seed.get(v, v) for k, v in body.items()})
    r = client.post("/api/transactions/transfer", json=payload, headers=auth(seed["admin_token"]))
    assert r.status_code == 422
    assert msg in r.json()["detail"]


def test_transfer_edit_propagates_and_amount_is_locked(client, seed):
    r = client.patch(f"/api/transactions/{seed['transfer_leg']}", json={"description": "Reserva", "event_date": d(4)},
                     headers=auth(seed["admin_token"]))
    assert r.status_code == 200, r.text
    assert len(r.json()) == 2
    other = client.get(f"/api/transactions/{seed['transfer_other']}", headers=auth(seed["admin_token"])).json()
    assert other["description"] == "Reserva"
    assert other["event_date"] == d(4)
    r2 = client.patch(f"/api/transactions/{seed['transfer_leg']}", json={"amount": "-5"}, headers=auth(seed["admin_token"]))
    assert r2.status_code == 409


def test_deleting_one_leg_deletes_the_pair(client, seed):
    r = client.delete(f"/api/transactions/{seed['transfer_leg']}", headers=auth(seed["admin_token"]))
    assert r.status_code == 204
    assert client.get(f"/api/transactions/{seed['transfer_other']}", headers=auth(seed["admin_token"])).status_code == 404


# ── update / delete ───────────────────────────────────────────────────────────

def test_patch_recomputes_amounts_and_fingerprint(client, seed):
    [tx] = post_tx(client, seed, description="Uber", amount="-20").json()
    r = client.patch(f"/api/transactions/{tx['id']}", json={"amount": "-30", "description": "Uber trip"},
                     headers=auth(seed["admin_token"]))
    assert r.status_code == 200
    [after] = r.json()
    assert after["amount_brl"] == -30.0
    assert after["amount_usd"] == -6.0
    db = TestSession()
    row = db.get(Transaction, tx["id"])
    assert row.fingerprint == svc.compute_fingerprint(
        TransactionSourceType.CHECKING, seed["itau"], row.event_date, Decimal("-30"), Currency.BRL, "Uber trip",
    )
    db.close()


def test_patch_card_date_moves_invoice(client, seed):
    [tx] = client.post("/api/transactions", json={
        "source_type": "CREDIT_CARD", "credit_card_account_id": seed["card"],
        "event_date": "2036-03-01", "description": "Feira", "amount": "-10",
    }, headers=auth(seed["admin_token"])).json()
    r = client.patch(f"/api/transactions/{tx['id']}", json={"event_date": "2036-03-20"}, headers=auth(seed["admin_token"]))
    [after] = r.json()
    assert after["invoice_id"] != tx["invoice_id"]
    db = TestSession()
    assert db.get(Invoice, after["invoice_id"]).close_date == date(2036, 4, 5)
    db.close()


def test_patch_rejects_structural_fields(client, seed):
    [tx] = post_tx(client, seed).json()
    r = client.patch(f"/api/transactions/{tx['id']}", json={"checking_account_id": seed["wise"]},
                     headers=auth(seed["admin_token"]))
    # campo fora do schema é ignorado pelo pydantic → nada muda
    assert r.status_code == 200
    assert r.json()[0]["checking_account_id"] == seed["itau"]


def test_delete_installment_parent_requires_cascade(client, seed):
    parent = seed["installment_parent"]
    r = client.delete(f"/api/transactions/{parent}", headers=auth(seed["admin_token"]))
    assert r.status_code == 409
    assert "cascata" in r.json()["detail"]
    r2 = client.delete(f"/api/transactions/{parent}?cascade=true", headers=auth(seed["admin_token"]))
    assert r2.status_code == 204
    db = TestSession()
    assert db.query(Transaction).filter(Transaction.parent_transaction_id == parent).count() == 0
    db.close()


# ── tags / party hooks ────────────────────────────────────────────────────────

def test_tags_roundtrip_and_tag_in_use_blocks_delete(client, seed):
    db = TestSession()
    tag = Tag(id=str(uuid.uuid4()), workspace_id=seed["ws_id"], name="viagem")
    db.add(tag)
    db.commit()
    tag_id = tag.id
    db.close()
    [tx] = post_tx(client, seed, description="Hotel", tag_ids=[tag_id]).json()
    assert tx["tags"] == [{"id": tag_id, "name": "viagem"}]
    listed = client.get(f"/api/transactions?tag_id={tag_id}", headers=auth(seed["admin_token"])).json()
    assert [t["id"] for t in listed["items"]] == [tx["id"]]
    r = client.delete(f"/api/tags/{tag_id}", headers=auth(seed["admin_token"]))
    assert r.status_code == 409
    client.patch(f"/api/transactions/{tx['id']}", json={"tag_ids": []}, headers=auth(seed["admin_token"]))
    assert client.delete(f"/api/tags/{tag_id}", headers=auth(seed["admin_token"])).status_code == 204


def test_unknown_tag_is_422(client, seed):
    r = post_tx(client, seed, tag_ids=["nope"])
    assert r.status_code == 422


def test_party_merge_repoints_transactions(client, seed):
    db = TestSession()
    a = Party(id=str(uuid.uuid4()), workspace_id=seed["ws_id"], name="Pão de Açúcar")
    b = Party(id=str(uuid.uuid4()), workspace_id=seed["ws_id"], name="PAO ACUCAR")
    db.add_all([a, b])
    db.commit()
    a_id, b_id = a.id, b.id
    db.close()
    [tx] = post_tx(client, seed, description="Mercado", party_id=b_id).json()
    r = client.post(f"/api/parties/{a_id}/merge", json={"source_party_id": b_id}, headers=auth(seed["admin_token"]))
    assert r.status_code == 200, r.text
    got = client.get(f"/api/transactions/{tx['id']}", headers=auth(seed["admin_token"])).json()
    assert got["party_id"] == a_id
    assert got["party_name"] == "Pão de Açúcar"


# ── list / summary / isolation ────────────────────────────────────────────────

def test_list_filters(client, seed):
    h = auth(seed["admin_token"])
    r = client.get("/api/transactions?search=padaria", headers=h).json()
    assert r["total"] >= 1 and all("Padaria" in t["description"] for t in r["items"])
    r = client.get(f"/api/transactions?card_id={seed['card']}", headers=h).json()
    assert r["items"] and all(t["source_type"] == "CREDIT_CARD" for t in r["items"])
    r = client.get(f"/api/transactions?category_id={seed['sub']}", headers=h).json()
    assert r["items"] and all(t["category_id"] == seed["sub"] for t in r["items"])
    r = client.get(f"/api/transactions?invoice_id={seed['future_invoice']}", headers=h).json()
    assert r["total"] == 2
    dates = [t["event_date"] for t in client.get("/api/transactions", headers=h).json()["items"]]
    assert dates == sorted(dates, reverse=True)


def test_summary_is_gross_flow_cut_at_today(client, seed):
    db = TestSession()
    acc = _account(db, seed["ws_id"], seed["fi_id"], "Conta Summary")
    db.commit()
    acc_id = acc.id
    db.close()
    h = auth(seed["admin_token"])
    post_tx(client, seed, checking_account_id=acc_id, amount="1000", description="Salário")
    post_tx(client, seed, checking_account_id=acc_id, amount="-300", description="Aluguel")
    r = client.post("/api/transactions", json={
        "source_type": "CHECKING", "checking_account_id": acc_id,
        "event_date": (TODAY + timedelta(days=30)).isoformat(), "description": "Futuro", "amount": "-999",
    }, headers=h)
    assert r.status_code == 201
    s = client.get(f"/api/transactions/summary?account_id={acc_id}", headers=h).json()
    assert s["inflows"] == {"brl": 1000.0, "usd": 200.0}
    assert s["outflows"] == {"brl": -300.0, "usd": -60.0}
    assert s["net"] == {"brl": 700.0, "usd": 140.0}
    assert s["count"] == 2
    assert s["unreconciled_count"] == 2


def test_other_workspace_isolation(client, seed):
    [tx] = post_tx(client, seed, description="Privado").json()
    h2 = auth(seed["admin2_token"])
    assert client.get(f"/api/transactions/{tx['id']}", headers=h2).status_code == 404
    assert client.patch(f"/api/transactions/{tx['id']}", json={"notes": "x"}, headers=h2).status_code == 404
    assert client.delete(f"/api/transactions/{tx['id']}", headers=h2).status_code == 404
    assert client.get("/api/transactions", headers=h2).json()["total"] == 0


def test_writes_are_audited(client, seed):
    from numis_geek.models.audit_log import AuditLog
    [tx] = post_tx(client, seed, description="Auditada").json()
    db = TestSession()
    logs = db.query(AuditLog).filter(AuditLog.resource_id == tx["id"]).all()
    assert any(lg.action == "transaction.created" for lg in logs)
    db.close()


def test_attachment_source_type_transaction_is_wired():
    from numis_geek.api.routes.attachments import _SOURCE_MODEL
    from numis_geek.models.attachment import AttachmentSourceType
    assert _SOURCE_MODEL[AttachmentSourceType.TRANSACTION] is Transaction
