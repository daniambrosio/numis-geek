"""Spec 71 — Import de extrato e fatura com detecção de duplicatas.

Covers: dedup layer 1 (file hash: re-upload refused / interrupted review
resumed), layer 2 (fingerprint: already-reconciled → skip, manual
never-reconciled → Conciliar + linked, k-th identical line → ":k"), layer 3
(period overlap warning), invoice payment via `pay_invoice` (statement debit
and the "Pagamento recebido" line on the next card invoice — never a card
tx), statement debit after a payment created from the card side (dedup by
payment tx), installments converging with the composer (event_date =
original + (X−1) months), installment parent link, AP/AR settlement via
`settle_occurrence`, new party + alias, atomic apply, and traceability
job ↔ tx in both directions. The LLM is always faked.
"""
import json
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
from numis_geek.integrations.llm import LLMCall, set_llm_client
from numis_geek.models.account import Account, AccountType, Currency
from numis_geek.models.category import Category, CategoryKind
from numis_geek.models.credit_card import CreditCardAccount, Invoice, InvoiceStatus
from numis_geek.models.extraction_job import ExtractionJob, ExtractionSourceHint, ExtractionStatus
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.party import Party, PartyAlias
from numis_geek.models.ptax_rate import PTAXRate
from numis_geek.models.scheduled_transaction import (
    ScheduledDirection, ScheduledStatus, ScheduledTransaction,
)
from numis_geek.models.transaction import Transaction, TransactionSourceType
from numis_geek.models.user import UserRole
from numis_geek.services import attachment_storage
from numis_geek.services import scheduled_transactions as sched_svc
from numis_geek.services import transactions as tx_svc
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
BASE = date(2026, 3, 1)


@pytest.fixture(scope="module", autouse=True)
def setup_db(tmp_path_factory):
    Base.metadata.create_all(TEST_ENGINE)
    original = attachment_storage.ROOT
    attachment_storage.ROOT = tmp_path_factory.mktemp("bank_import_atts")
    yield
    attachment_storage.ROOT = original
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


@pytest.fixture(autouse=True)
def reset_llm():
    yield
    set_llm_client(None)


@pytest.fixture(scope="module")
def seed():
    db = TestSession()
    ws = WorkspaceService(db).create("BI WS")
    ws2 = WorkspaceService(db).create("BI WS 2")
    UserService(db).create(ws.id, "bi_admin@test.com", "adminpass", UserRole.admin)
    UserService(db).create(ws2.id, "bi_other@test.com", "adminpass", UserRole.admin)
    now = datetime.now(timezone.utc)
    fi = FinancialInstitution(
        id=str(uuid.uuid4()), long_name="Banco BI", short_name="BBI", logo_slug="bbi",
        is_active=True, created_at=now, updated_at=now,
    )
    db.add(fi)
    start = BASE - timedelta(days=200)
    for i in range(800):
        db.add(PTAXRate(id=str(uuid.uuid4()), date=start + timedelta(days=i), rate=PTAX, fetched_at=now))
    root = Category(id=str(uuid.uuid4()), workspace_id=ws.id, name="Moradia", color="#00ff00")
    db.add(root)
    db.flush()
    sub = Category(id=str(uuid.uuid4()), workspace_id=ws.id, name="Aluguel", parent_id=root.id, kind=CategoryKind.EXPENSE)
    db.add(sub)
    db.commit()
    ids = {"ws": ws.id, "ws2": ws2.id, "fi": fi.id, "sub": sub.id}
    ids["token"] = AuthService(db).login("bi_admin@test.com", "adminpass")
    ids["token2"] = AuthService(db).login("bi_other@test.com", "adminpass")
    db.close()
    return ids


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def new_account(seed, name="Conta", currency=Currency.BRL) -> str:
    db = TestSession()
    a = Account(
        id=str(uuid.uuid4()), workspace_id=seed["ws"], financial_institution_id=seed["fi"],
        name=f"{name} {uuid.uuid4().hex[:4]}", account_type=AccountType.checking,
        currency=currency, is_active=True,
    )
    db.add(a)
    aid = a.id
    db.commit()
    db.close()
    return aid


def new_card(seed) -> str:
    db = TestSession()
    c = CreditCardAccount(
        id=str(uuid.uuid4()), workspace_id=seed["ws"], financial_institution_id=seed["fi"],
        name=f"Cartão {uuid.uuid4().hex[:4]}", currency=Currency.BRL, credit_limit=Decimal("20000"),
        close_day=5, due_day=15, is_active=True,
    )
    db.add(c)
    cid = c.id
    db.commit()
    db.close()
    return cid


class FakeLLM:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def call(self, *, system, user_text, image_bytes=None, image_mime=None,
             image_parts=None, model="claude-sonnet-4-5", max_tokens=4096):
        self.calls += 1
        return LLMCall(text=json.dumps(self.payload), input_tokens=100, output_tokens=50, model=model)


def line(d: date, desc: str, amount, **kw) -> dict:
    return {"event_date": d.isoformat(), "description": desc, "amount": float(amount), "currency": "BRL", **kw}


def statement(lines, start=None, end=None) -> dict:
    out = {"transactions": lines}
    if start and end:
        out["period"] = {"start": start.isoformat(), "end": end.isoformat()}
    return out


def upload(client, seed, path: str, payload: dict, *, content: bytes | None = None,
           filename="extrato.csv", mime="text/csv"):
    fake = FakeLLM(payload)
    set_llm_client(fake)
    body = content if content is not None else (uuid.uuid4().hex + json.dumps(payload)).encode()
    r = client.post(f"/api{path}", files={"file": (filename, body, mime)}, headers=auth(seed["token"]))
    return r, fake


def import_statement(client, seed, account_id, payload, **kw):
    r, _ = upload(client, seed, f"/accounts/{account_id}/statement-imports", payload, **kw)
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "EXTRACTED", r.json()
    return r.json()


def import_invoice(client, seed, card_id, payload, **kw):
    r, _ = upload(client, seed, f"/credit-cards/{card_id}/invoice-imports", payload,
                  filename="fatura.pdf", mime="application/pdf", **kw)
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "EXTRACTED", r.json()
    return r.json()


def preview(client, seed, job_id) -> dict:
    r = client.post(f"/api/extractions/{job_id}/preview", json={}, headers=auth(seed["token"]))
    assert r.status_code == 200, r.text
    return r.json()["bank_import"]


def confirm(client, seed, job_id, decisions=None, expect=200):
    r = client.post(f"/api/extractions/{job_id}/confirm", json={"bank_decisions": decisions},
                    headers=auth(seed["token"]))
    assert r.status_code == expect, r.text
    return r.json()


def txs_of(db, account_id=None, card_id=None):
    q = db.query(Transaction)
    if account_id:
        q = q.filter(Transaction.checking_account_id == account_id)
    if card_id:
        q = q.filter(Transaction.credit_card_account_id == card_id)
    return q.order_by(Transaction.event_date, Transaction.created_at).all()


# ── layer 1 ──────────────────────────────────────────────────────────────────

def test_reupload_same_file_refused_and_interrupted_review_resumes(client, seed):
    acc = new_account(seed)
    payload = statement([line(BASE, "PADARIA", -12)])
    content = b"same-bytes-" + uuid.uuid4().hex.encode()
    job = import_statement(client, seed, acc, payload, content=content)

    # same file again before apply: resumes the pending review (no new LLM call)
    r, fake = upload(client, seed, f"/accounts/{acc}/statement-imports", payload, content=content)
    assert r.status_code == 200 and r.json()["resumed"] is True and r.json()["id"] == job["id"]
    assert fake.calls == 0

    confirm(client, seed, job["id"])
    r, fake = upload(client, seed, f"/accounts/{acc}/statement-imports", payload, content=content)
    assert r.status_code == 409
    assert "já importado" in r.json()["detail"] and job["attachment_id"] in r.json()["detail"]
    assert fake.calls == 0

    # same bytes to another account: refused too, pointing at the original
    other = new_account(seed)
    r, _ = upload(client, seed, f"/accounts/{other}/statement-imports", payload, content=content)
    assert r.status_code == 409


def test_failed_extraction_retry_reuses_attachment(client, seed):
    acc = new_account(seed)
    content = b"broken-" + uuid.uuid4().hex.encode()
    set_llm_client(FakeLLM({"nope": True}))  # missing `transactions` → validation fails
    r = client.post(f"/api/accounts/{acc}/statement-imports",
                    files={"file": ("x.csv", content, "text/csv")}, headers=auth(seed["token"]))
    assert r.status_code == 201 and r.json()["status"] == "FAILED"
    first_att = r.json()["attachment_id"]
    r, _ = upload(client, seed, f"/accounts/{acc}/statement-imports",
                  statement([line(BASE, "X", -1)]), content=content)
    assert r.status_code == 201 and r.json()["status"] == "EXTRACTED"
    assert r.json()["attachment_id"] == first_att


def test_content_hash_on_generic_upload(client, seed):
    acc = new_account(seed)
    r = client.post("/api/attachments", data={"source_type": "account", "source_id": acc},
                    files={"file": ("a.csv", b"abc", "text/csv")}, headers=auth(seed["token"]))
    assert r.status_code == 201, r.text
    db = TestSession()
    from numis_geek.models.attachment import Attachment
    att = db.get(Attachment, r.json()["id"])
    assert att.content_hash == attachment_storage.content_hash(b"abc")
    db.close()


def test_ofx_upload_without_mime_is_accepted(client, seed):
    acc = new_account(seed)
    r, _ = upload(client, seed, f"/accounts/{acc}/statement-imports", statement([line(BASE, "TED", -5)]),
                  content=b"OFXHEADER:100\n<OFX>" + uuid.uuid4().hex.encode(),
                  filename="extrato.ofx", mime="application/octet-stream")
    assert r.status_code == 201 and r.json()["status"] == "EXTRACTED"


def test_other_workspace_cannot_import_into_account(client, seed):
    acc = new_account(seed)
    r = client.post(f"/api/accounts/{acc}/statement-imports",
                    files={"file": ("a.csv", b"zz", "text/csv")}, headers=auth(seed["token2"]))
    assert r.status_code == 404


# ── layer 2 ──────────────────────────────────────────────────────────────────

def test_already_imported_line_defaults_to_skip_and_overlap_is_reported(client, seed):
    acc = new_account(seed)
    d1, d2 = BASE + timedelta(days=2), BASE + timedelta(days=20)
    job1 = import_statement(client, seed, acc, statement(
        [line(d1, "MERCADO X", -100)], start=BASE, end=BASE + timedelta(days=14)))
    confirm(client, seed, job1["id"])

    job2 = import_statement(client, seed, acc, statement(
        [line(d1, "MERCADO X", -100), line(d2, "FARMACIA", -30)],
        start=BASE + timedelta(days=1), end=BASE + timedelta(days=30)))
    p = preview(client, seed, job2["id"])
    dup, new = p["rows"]
    assert dup["bucket"] == "duplicate" and dup["default_action"] == "skip"
    assert dup["duplicate"]["reason"] == "fingerprint"
    assert new["bucket"] == "new"
    assert len(p["overlaps"]) == 1
    ov = p["overlaps"][0]
    assert ov["job_id"] == job1["id"] and ov["duplicate_count"] == 1
    assert ov["start"] == BASE.isoformat()

    res = confirm(client, seed, job2["id"])
    assert res["bank_import"]["created"] == 1 and res["bank_import"]["skipped"] == 1
    db = TestSession()
    assert len(txs_of(db, account_id=acc)) == 2
    db.close()


def test_manual_unreconciled_tx_is_reconciled_and_linked_not_skipped(client, seed):
    acc = new_account(seed)
    d = BASE + timedelta(days=3)
    db = TestSession()
    manual = tx_svc.create_transaction(db, seed["ws"], tx_svc.TxInput(
        source_type=TransactionSourceType.CHECKING, checking_account_id=acc,
        event_date=d, description="Conta de luz", amount=Decimal("-210.55"),
    ))[0]
    manual_id = manual.id
    db.commit()
    db.close()

    job = import_statement(client, seed, acc, statement([line(d, "CONTA DE LUZ", -210.55)]))
    row = preview(client, seed, job["id"])["rows"][0]
    assert row["bucket"] == "duplicate"
    assert row["default_action"] == "reconcile"
    assert row["duplicate"]["transaction_id"] == manual_id
    res = confirm(client, seed, job["id"])
    assert res["bank_import"]["reconciled"] == 1 and res["bank_import"]["created"] == 0

    db = TestSession()
    tx = db.get(Transaction, manual_id)
    assert tx.is_reconciled is True and tx.extraction_job_id == job["id"]
    assert len(txs_of(db, account_id=acc)) == 1
    db.close()


def test_identical_lines_same_day_promoted_with_suffix(client, seed):
    acc = new_account(seed)
    d = BASE + timedelta(days=4)
    lines = [line(d, "CAFE DA ESQUINA", -5), line(d, "CAFE DA ESQUINA", -5)]
    job = import_statement(client, seed, acc, statement(lines))
    rows = preview(client, seed, job["id"])["rows"]
    # 2026-11-02: identical lines in the SAME file are distinct movements
    assert [r["bucket"] for r in rows] == ["new", "new"]
    assert [r["default_action"] for r in rows] == ["import", "import"]
    assert rows[1]["fingerprint"] == rows[0]["fingerprint"] + ":2"
    confirm(client, seed, job["id"])

    db = TestSession()
    txs = txs_of(db, account_id=acc)
    assert len(txs) == 2
    fps = sorted(t.fingerprint for t in txs)
    assert fps[1] == fps[0] + ":2"
    db.close()

    # overlapping file with the same 2 coffees → both fall as duplicates (skip)
    job2 = import_statement(client, seed, acc, statement(lines))
    rows = preview(client, seed, job2["id"])["rows"]
    assert [r["bucket"] for r in rows] == ["duplicate", "duplicate"]
    assert [r["default_action"] for r in rows] == ["skip", "skip"]
    assert all(r["duplicate"]["transaction_id"] for r in rows)


def test_fingerprint_suffix_survives_edit(client, seed):
    acc = new_account(seed)
    db = TestSession()
    tx = tx_svc.create_transaction(db, seed["ws"], tx_svc.TxInput(
        source_type=TransactionSourceType.CHECKING, checking_account_id=acc,
        event_date=BASE, description="Cafe", amount=Decimal("-5"),
    ))[0]
    tx.fingerprint = tx.fingerprint + ":2"
    tx_svc.update_transaction(db, tx, {"notes": "x"})
    assert tx.fingerprint.endswith(":2")
    db.rollback()
    db.close()


# ── invoice payment ──────────────────────────────────────────────────────────

def _closed_invoice(card_id, close, due, total) -> str:
    db = TestSession()
    card = db.get(CreditCardAccount, card_id)
    inv = Invoice(
        id=str(uuid.uuid4()), workspace_id=card.workspace_id, credit_card_account_id=card.id,
        close_date=close, due_date=due, total_amount=Decimal(total), currency=Currency.BRL,
        status=InvoiceStatus.CLOSED,
    )
    db.add(inv)
    iid = inv.id
    db.commit()
    db.close()
    return iid


def test_statement_debit_pays_closed_invoice_via_pay_invoice(client, seed):
    acc = new_account(seed)
    card = new_card(seed)
    inv_id = _closed_invoice(card, BASE + timedelta(days=4), BASE + timedelta(days=14), "1500.00")
    paid_on = BASE + timedelta(days=13)
    # ±1%: 1508 is within 15.00 of 1500
    job = import_statement(client, seed, acc, statement([line(paid_on, "PAG FATURA CARTAO", -1508)]))
    row = preview(client, seed, job["id"])["rows"][0]
    assert row["bucket"] == "invoice_payment" and row["default_action"] == "pay"
    assert row["invoice_payment"]["invoice_id"] == inv_id
    confirm(client, seed, job["id"])

    db = TestSession()
    inv = db.get(Invoice, inv_id)
    assert inv.status == InvoiceStatus.PAID and inv.paid_at == paid_on
    tx = db.get(Transaction, inv.paid_by_transaction_id)
    assert tx.paid_invoice_id == inv_id and tx.amount == Decimal("-1508.00")
    assert tx.is_reconciled and tx.extraction_job_id == job["id"]
    db.close()


def test_statement_debit_outside_tolerance_is_not_invoice_payment(client, seed):
    acc = new_account(seed)
    card = new_card(seed)
    _closed_invoice(card, BASE + timedelta(days=4), BASE + timedelta(days=14), "1500.00")
    job = import_statement(client, seed, acc, statement([
        line(BASE + timedelta(days=13), "PAG FATURA", -1530),   # 2% off
        line(BASE + timedelta(days=40), "PAG FATURA", -1500),   # after due+10
    ]))
    rows = preview(client, seed, job["id"])["rows"]
    assert [r["bucket"] for r in rows] == ["new", "new"]


def test_card_invoice_import_payment_line_never_becomes_card_tx(client, seed):
    acc = new_account(seed)
    card = new_card(seed)
    prev_id = _closed_invoice(card, date(2026, 2, 5), date(2026, 2, 15), "800.00")
    original = date(2026, 1, 10)
    job = import_invoice(client, seed, card, {
        "period": {"start": "2026-02-06", "end": "2026-03-05"},
        "invoice": {"close_date": "2026-03-05", "due_date": "2026-03-15", "total": 1290.4, "iof_total": 3.5},
        "transactions": [
            line(date(2026, 2, 10), "PAGAMENTO RECEBIDO", 800, is_invoice_payment=True),
            line(date(2026, 2, 20), "RESTAURANTE", -190.4),
            line(original, "NOTEBOOK", -1000, installment="3/10"),
            line(date(2026, 2, 25), "SPOTIFY", -96.5, fx={"usd_amount": 19.3, "rate": 5.0}),
            line(date(2026, 2, 25), "IOF COMPRA EXTERIOR", -3.5),
        ],
    })
    p = preview(client, seed, job["id"])
    pay, rest, nb, spot, iof = p["rows"]
    assert pay["bucket"] == "invoice_payment" and pay["invoice_payment"]["invoice_id"] == prev_id
    assert pay["invoice_payment"]["kind"] == "card_payment_line"
    assert "import" not in pay["actions"] and "import_anyway" not in pay["actions"]
    # no previous payment → no default account → must be chosen in review
    assert pay["default_action"] == "skip" and pay["warning"]
    assert nb["event_date"] == "2026-03-10" and nb["original_date"] == "2026-01-10"
    assert nb["installment_number"] == 3 and nb["installment_total"] == 10
    assert p["invoice"]["close_date"] == "2026-03-05" and p["invoice"]["existing_invoice_id"] is None

    confirm(client, seed, job["id"], {"r0": {"action": "pay", "payment_account_id": acc}})
    db = TestSession()
    all_card = txs_of(db, card_id=card)
    projected = [t for t in all_card if (t.notes or "").startswith("parcela prevista")]
    card_txs = [t for t in all_card if t not in projected]
    assert len(card_txs) == 4
    assert sorted(t.installment_number for t in projected) == list(range(4, 11))   # NOTEBOOK 3/10 → 4..10
    assert all(t.amount < 0 for t in card_txs)  # the +800 never became a card tx
    doc_inv = db.query(Invoice).filter(Invoice.credit_card_account_id == card,
                                       Invoice.close_date == date(2026, 3, 5)).one()
    assert doc_inv.status == InvoiceStatus.CLOSED
    assert doc_inv.total_amount == Decimal("1290.40") and doc_inv.iof_total == Decimal("3.50")
    assert doc_inv.due_date == date(2026, 3, 15)
    assert {t.invoice_id for t in card_txs} == {doc_inv.id}
    spot_tx = next(t for t in card_txs if t.description == "SPOTIFY")
    assert spot_tx.fx_rate == Decimal("5.0") and spot_tx.fx_source.value == "STATEMENT"
    prev = db.get(Invoice, prev_id)
    assert prev.status == InvoiceStatus.PAID
    pay_tx = db.get(Transaction, prev.paid_by_transaction_id)
    assert pay_tx.checking_account_id == acc and pay_tx.amount == Decimal("-800.00")
    assert pay_tx.is_reconciled and pay_tx.extraction_job_id == job["id"]
    pay_tx_id = pay_tx.id
    db.close()

    # the checking statement arrives later: the debit falls on layer 2
    job2 = import_statement(client, seed, acc, statement([line(date(2026, 2, 10), "PGTO CARTAO NU", -800)]))
    row = preview(client, seed, job2["id"])["rows"][0]
    assert row["bucket"] == "duplicate" and row["duplicate"]["reason"] == "invoice_payment_tx"
    assert row["duplicate"]["transaction_id"] == pay_tx_id and row["default_action"] == "skip"

    # next invoice: default payment account is the last one used for this card
    job3 = import_invoice(client, seed, card, {
        "invoice": {"close_date": "2026-04-05", "due_date": "2026-04-15", "total": 10},
        "transactions": [line(date(2026, 3, 14), "PAGAMENTO RECEBIDO", 1290.4, is_invoice_payment=True),
                         line(date(2026, 3, 20), "PADARIA", -10)],
    })
    pay = preview(client, seed, job3["id"])["rows"][0]
    assert pay["invoice_payment"]["invoice_id"] == doc_inv.id
    assert pay["invoice_payment"]["payment_account_id"] == acc and pay["default_action"] == "pay"


def test_payment_line_reconciles_payment_of_already_paid_invoice(client, seed):
    acc = new_account(seed)
    card = new_card(seed)
    prev_id = _closed_invoice(card, date(2026, 2, 5), date(2026, 2, 15), "500.00")
    db = TestSession()
    tx = tx_svc.pay_invoice(db, db.get(Invoice, prev_id), checking_account_id=acc, paid_on=date(2026, 2, 14))
    pay_id = tx.id
    db.commit()
    db.close()

    job = import_invoice(client, seed, card, {
        "invoice": {"close_date": "2026-03-05", "due_date": "2026-03-15", "total": 20},
        "transactions": [line(date(2026, 2, 15), "Pagamento efetuado", 500),   # heuristic, no flag
                         line(date(2026, 2, 20), "LANCHE", -20)],
    })
    row = preview(client, seed, job["id"])["rows"][0]
    assert row["bucket"] == "invoice_payment" and row["default_action"] == "reconcile"
    confirm(client, seed, job["id"])
    db = TestSession()
    tx = db.get(Transaction, pay_id)
    assert tx.is_reconciled and tx.extraction_job_id == job["id"]
    assert len(txs_of(db, card_id=card)) == 1
    db.close()


# ── installments ─────────────────────────────────────────────────────────────

def test_installment_converges_with_composer(client, seed):
    card = new_card(seed)
    original = date(2026, 1, 10)
    db = TestSession()
    created = tx_svc.create_transaction(db, seed["ws"], tx_svc.TxInput(
        source_type=TransactionSourceType.CREDIT_CARD, credit_card_account_id=card,
        event_date=original, description="NOTEBOOK DELL", amount=Decimal("-1200.03"),
    ), installments=12)
    third = created[2]
    third_id, third_fp, third_inv = third.id, third.fingerprint, third.invoice_id
    first_id = created[0].id
    close = db.get(Invoice, third_inv).close_date
    db.commit()
    db.close()

    job = import_invoice(client, seed, card, {
        "invoice": {"close_date": close.isoformat(), "due_date": (close + timedelta(days=10)).isoformat(), "total": 100},
        "transactions": [line(original, "NOTEBOOK DELL", -100, installment="03/12"),
                         line(original, "NOTEBOOK DELL", -100.03, installment="1/12")],
    })
    rows = preview(client, seed, job["id"])["rows"]
    r3, r1 = rows
    assert r3["fingerprint"] == third_fp           # same rule as the composer
    assert r3["bucket"] == "duplicate" and r3["duplicate"]["transaction_id"] == third_id
    assert r3["default_action"] == "reconcile"
    # 1/12 is 100.03 on the composer too: also converges
    assert r1["bucket"] == "duplicate" and r1["duplicate"]["transaction_id"] == first_id
    confirm(client, seed, job["id"])
    db = TestSession()
    assert db.query(Transaction).filter(Transaction.credit_card_account_id == card).count() == 12
    assert db.get(Transaction, third_id).is_reconciled
    db.close()


def test_installment_within_cents_matches_even_if_fingerprint_differs(client, seed):
    card = new_card(seed)
    original = date(2026, 1, 12)
    db = TestSession()
    created = tx_svc.create_transaction(db, seed["ws"], tx_svc.TxInput(
        source_type=TransactionSourceType.CREDIT_CARD, credit_card_account_id=card,
        event_date=original, description="GELADEIRA", amount=Decimal("-1000"),
    ), installments=3)
    second_id = created[1].id
    db.commit()
    db.close()
    job = import_invoice(client, seed, card, {
        "invoice": {"close_date": "2026-03-05", "due_date": "2026-03-15", "total": 333.36},
        "transactions": [line(original, "GELADEIRA", -333.36, installment="2/3")],  # composer: 333.33
    })
    row = preview(client, seed, job["id"])["rows"][0]
    assert row["bucket"] == "duplicate" and row["duplicate"]["reason"] == "installment"
    assert row["duplicate"]["transaction_id"] == second_id


def test_imported_installment_links_parent_by_purchase(client, seed):
    card = new_card(seed)
    original = date(2026, 1, 20)
    job1 = import_invoice(client, seed, card, {
        "invoice": {"close_date": "2026-02-05", "due_date": "2026-02-15", "total": 150},
        "transactions": [line(original, "TV SAMSUNG", -150, installment="1/3")],
    })
    confirm(client, seed, job1["id"])
    job2 = import_invoice(client, seed, card, {
        "invoice": {"close_date": "2026-03-05", "due_date": "2026-03-15", "total": 150},
        "transactions": [line(original, "TV SAMSUNG", -150, installment="2/3")],
    })
    row = preview(client, seed, job2["id"])["rows"][0]
    # 2026-11-02: 1/3 generated 2/3 and 3/3 as projected → 2/3 now confirms it
    assert row["bucket"] == "duplicate" and row["default_action"] == "reconcile"
    confirm(client, seed, job2["id"])
    db = TestSession()
    txs = txs_of(db, card_id=card)
    assert len(txs) == 3
    first = next(t for t in txs if t.installment_number == 1)
    second = next(t for t in txs if t.installment_number == 2)
    assert second.parent_transaction_id == first.id
    assert second.event_date == date(2026, 2, 20)
    assert second.is_reconciled and second.extraction_job_id == job2["id"] and second.notes is None
    db.close()


# ── AP/AR settlement ─────────────────────────────────────────────────────────

def test_scheduled_occurrence_settled_by_import(client, seed):
    acc = new_account(seed)
    due = BASE + timedelta(days=9)
    db = TestSession()
    near = sched_svc.create_one_off(db, seed["ws"], sched_svc.OccurrenceInput(
        direction=ScheduledDirection.PAYABLE, description="Aluguel", amount=Decimal("3000"),
        due_date=due, currency=Currency.BRL, category_id=seed["sub"],
    ))
    far = sched_svc.create_one_off(db, seed["ws"], sched_svc.OccurrenceInput(
        direction=ScheduledDirection.PAYABLE, description="Aluguel", amount=Decimal("3000"),
        due_date=due + timedelta(days=4), currency=Currency.BRL,
    ))
    near_id, far_id = near.id, far.id
    db.commit()
    db.close()

    job = import_statement(client, seed, acc, statement([
        line(due + timedelta(days=1), "TED ALUGUEL APTO", -3090),   # +3%
    ]))
    row = preview(client, seed, job["id"])["rows"][0]
    # 2026-11-02 scored matcher: two "Aluguel" 3 days apart are too close to
    # call → stays Importar, candidates shown best first (closest date).
    assert row["bucket"] == "new" and row["default_action"] == "import" and "settle" in row["actions"]
    assert row["scheduled"]["occurrence_id"] == near_id
    assert [c["occurrence_id"] for c in row["scheduled"]["candidates"]] == [near_id, far_id]
    confirm(client, seed, job["id"], {"r0": {"action": "settle"}})

    db = TestSession()
    occ = db.get(ScheduledTransaction, near_id)
    assert occ.status == ScheduledStatus.PAID
    tx = db.get(Transaction, occ.paid_by_transaction_id)
    assert tx.extraction_job_id == job["id"] and tx.is_reconciled
    assert tx.category_id == seed["sub"]                       # inherited from the occurrence
    assert db.get(ScheduledTransaction, far_id).status == ScheduledStatus.PENDING
    db.close()


def test_scheduled_user_can_pick_another_candidate(client, seed):
    acc = new_account(seed)
    due = BASE + timedelta(days=50)
    db = TestSession()
    a = sched_svc.create_one_off(db, seed["ws"], sched_svc.OccurrenceInput(
        direction=ScheduledDirection.PAYABLE, description="Condominio", amount=Decimal("900"),
        due_date=due, currency=Currency.BRL))
    b = sched_svc.create_one_off(db, seed["ws"], sched_svc.OccurrenceInput(
        direction=ScheduledDirection.PAYABLE, description="Condominio", amount=Decimal("900"),
        due_date=due + timedelta(days=3), currency=Currency.BRL))
    a_id, b_id = a.id, b.id
    db.commit()
    db.close()
    job = import_statement(client, seed, acc, statement([line(due, "CONDOMINIO ED", -900)]))
    confirm(client, seed, job["id"], {"r0": {"action": "settle", "occurrence_id": b_id}})
    db = TestSession()
    assert db.get(ScheduledTransaction, b_id).status == ScheduledStatus.PAID
    assert db.get(ScheduledTransaction, a_id).status == ScheduledStatus.PENDING
    db.close()


# ── parties ──────────────────────────────────────────────────────────────────

def test_new_party_created_with_alias_and_reused(client, seed):
    acc = new_account(seed)
    job = import_statement(client, seed, acc, statement([line(BASE + timedelta(days=60), "UBER *TRIP 1234", -23.4)]))
    row = preview(client, seed, job["id"])["rows"][0]
    assert row["party"]["mode"] == "new" and row["party"]["new_party_name"] == "UBER *TRIP 1234"
    assert row["party"]["alias"] == "UBER TRIP"
    confirm(client, seed, job["id"])
    db = TestSession()
    alias = db.query(PartyAlias).filter(PartyAlias.workspace_id == seed["ws"],
                                        PartyAlias.alias_normalized == "UBER TRIP").one()
    party = db.get(Party, alias.party_id)
    tx = txs_of(db, account_id=acc)[0]
    assert tx.party_id == party.id
    db.close()

    job2 = import_statement(client, seed, acc, statement([line(BASE + timedelta(days=61), "UBER *TRIP 999", -18)]))
    row = preview(client, seed, job2["id"])["rows"][0]
    assert row["party"]["mode"] == "existing" and row["party"]["party_id"] == party.id


def test_inline_category_and_party_overrides(client, seed):
    acc = new_account(seed)
    job = import_statement(client, seed, acc, statement([line(BASE + timedelta(days=70), "XPTO LTDA", -50)]))
    confirm(client, seed, job["id"], {"r0": {"action": "import", "category_id": seed["sub"], "no_party": True}})
    db = TestSession()
    tx = txs_of(db, account_id=acc)[0]
    assert tx.category_id == seed["sub"] and tx.party_id is None
    assert db.query(PartyAlias).filter(PartyAlias.alias_normalized == "XPTO LTDA").count() == 0
    db.close()


# ── atomicity + traceability ─────────────────────────────────────────────────

def test_apply_is_atomic_on_invalid_decision(client, seed):
    acc = new_account(seed)
    job = import_statement(client, seed, acc, statement([
        line(BASE + timedelta(days=80), "A", -1), line(BASE + timedelta(days=80), "B", -2),
    ]))
    confirm(client, seed, job["id"], {"r1": {"action": "pay"}}, expect=400)
    db = TestSession()
    assert txs_of(db, account_id=acc) == []
    assert db.get(ExtractionJob, job["id"]).status == ExtractionStatus.EXTRACTED
    assert db.query(PartyAlias).filter(PartyAlias.alias_normalized == "A").count() == 0
    db.close()


def test_traceability_job_to_tx_and_tx_to_file(client, seed):
    acc = new_account(seed)
    job = import_statement(client, seed, acc, statement([
        line(BASE + timedelta(days=90), "LOJA 1", -10), line(BASE + timedelta(days=91), "LOJA 2", -20),
    ], start=BASE + timedelta(days=90), end=BASE + timedelta(days=95)))
    confirm(client, seed, job["id"])

    # job → tx
    r = client.get(f"/api/transactions?extraction_job_id={job['id']}", headers=auth(seed["token"]))
    assert r.status_code == 200 and r.json()["total"] == 2
    # tx → job → file
    tx = r.json()["items"][0]
    assert tx["extraction_job_id"] == job["id"]
    assert tx["source_attachment_id"] == job["attachment_id"]
    assert tx["source_attachment_filename"] == "extrato.csv"
    # history on the account
    hist = client.get(f"/api/accounts/{acc}/statement-imports", headers=auth(seed["token"])).json()
    h = next(x for x in hist if x["id"] == job["id"])
    assert h["status"] == "CONFIRMED" and h["transaction_count"] == 2
    assert h["statement_period_start"] == (BASE + timedelta(days=90)).isoformat()
    # the imported file can't be deleted out from under the tx
    r = client.delete(f"/api/attachments/{job['attachment_id']}", headers=auth(seed["token"]))
    assert r.status_code == 409


def test_manual_tx_never_reconciled_has_no_job(client, seed):
    acc = new_account(seed)
    db = TestSession()
    tx = tx_svc.create_transaction(db, seed["ws"], tx_svc.TxInput(
        source_type=TransactionSourceType.CHECKING, checking_account_id=acc,
        event_date=BASE, description="Manual", amount=Decimal("-1"),
    ))[0]
    assert tx.extraction_job_id is None
    db.rollback()
    db.close()


def test_card_import_into_paid_invoice_only_reconciles(client, seed):
    acc = new_account(seed)
    card = new_card(seed)
    inv_id = _closed_invoice(card, date(2026, 5, 5), date(2026, 5, 15), "40.00")
    db = TestSession()
    tx_svc.pay_invoice(db, db.get(Invoice, inv_id), checking_account_id=acc, paid_on=date(2026, 5, 14))
    db.commit()
    db.close()
    job = import_invoice(client, seed, card, {
        "invoice": {"close_date": "2026-05-05", "due_date": "2026-05-15", "total": 40},
        "transactions": [line(date(2026, 4, 20), "LIVRARIA", -40)],
    })
    p = preview(client, seed, job["id"])
    assert p["invoice"]["blocked"] is True
    assert p["rows"][0]["actions"] == ["skip"]
    confirm(client, seed, job["id"], {"r0": {"action": "import"}}, expect=400)


# ══ audit adversarial 2026-10-31 — regressões ═══════════════════════════════

def _party_with_alias(seed, name, alias, active=True) -> str:
    db = TestSession()
    p = Party(id=str(uuid.uuid4()), workspace_id=seed["ws"], name=name, is_active=active)
    db.add(p)
    db.flush()
    db.add(PartyAlias(id=str(uuid.uuid4()), workspace_id=seed["ws"], party_id=p.id, alias_normalized=alias))
    pid = p.id
    db.commit()
    db.close()
    return pid


# A (#1, 8, 12, 16) — alias of an inactive party
def test_alias_of_inactive_party_previews_and_applies_as_no_party(client, seed):
    acc = new_account(seed)
    _party_with_alias(seed, "Netflix antigo", "NETFLIX COM BR", active=False)
    job = import_statement(client, seed, acc, statement([line(BASE + timedelta(days=100), "NETFLIX COM BR", -39.9)]))
    row = preview(client, seed, job["id"])["rows"][0]
    assert row["party"]["mode"] == "none" and "inativo" in row["warning"]
    confirm(client, seed, job["id"])  # defaults never 400
    db = TestSession()
    tx = txs_of(db, account_id=acc)[0]
    assert tx.party_id is None
    db.close()


# A (#15) — new_party_name honored even when the alias belongs to another party
def test_new_party_name_creates_that_party_without_stealing_alias(client, seed):
    acc = new_account(seed)
    other = _party_with_alias(seed, "Uber", "UBER EATS PEDIDO")
    job = import_statement(client, seed, acc, statement([
        line(BASE + timedelta(days=101), "UBER EATS PEDIDO", -50),
        line(BASE + timedelta(days=102), "UBER EATS PEDIDO", -60),
    ]))
    confirm(client, seed, job["id"], {"r0": {"action": "import", "new_party_name": "Uber Eats"},
                                       "r1": {"action": "import", "new_party_name": "Outro Nome"}})
    db = TestSession()
    t0, t1 = txs_of(db, account_id=acc)
    assert db.get(Party, t0.party_id).name == "Uber Eats"
    assert db.get(Party, t1.party_id).name == "Outro Nome"
    # 2026-11-02 party memory: the user's explicit choice re-points the text
    # (last explicit choice in the file wins)
    alias = db.query(PartyAlias).filter(PartyAlias.alias_normalized == "UBER EATS PEDIDO").one()
    assert alias.party_id == t1.party_id != other
    db.close()


# B (#3) — payment line never attaches to an invoice older than the previous cycle
def test_payment_line_without_previous_cycle_is_skip(client, seed):
    card = new_card(seed)
    _closed_invoice(card, date(2026, 8, 5), date(2026, 8, 15), "2300.00")   # Aug; Sep missing
    job = import_invoice(client, seed, card, {
        "invoice": {"close_date": "2026-10-05", "due_date": "2026-10-15", "total": 10},
        "transactions": [line(date(2026, 9, 14), "PAGAMENTO RECEBIDO", 2300, is_invoice_payment=True),
                         line(date(2026, 9, 20), "PADARIA", -10)],
    })
    row = preview(client, seed, job["id"])["rows"][0]
    assert row["actions"] == ["skip"] and "ciclo anterior" in row["warning"]


# B (#6) — partial / multiple payment lines: skip, never N-1
def test_multiple_and_partial_payment_lines_skip(client, seed):
    acc = new_account(seed)
    card = new_card(seed)
    n_minus_1 = _closed_invoice(card, date(2026, 7, 5), date(2026, 7, 15), "500.00")
    n = _closed_invoice(card, date(2026, 8, 5), date(2026, 8, 15), "1500.00")
    db = TestSession()
    tx_svc.pay_invoice(db, db.get(Invoice, n_minus_1), checking_account_id=acc, paid_on=date(2026, 7, 14))
    db.commit()
    db.close()
    job = import_invoice(client, seed, card, {
        "invoice": {"close_date": "2026-09-05", "due_date": "2026-09-15", "total": 10},
        "transactions": [line(date(2026, 8, 10), "PAGAMENTO RECEBIDO", 1000, is_invoice_payment=True),
                         line(date(2026, 8, 12), "PAGAMENTO RECEBIDO", 500, is_invoice_payment=True),
                         line(date(2026, 8, 20), "LANCHE", -10)],
    })
    r0, r1, _ = preview(client, seed, job["id"])["rows"]
    assert r0["invoice_payment"]["invoice_id"] == n and r0["actions"] == ["skip"] and "parcial" in r0["warning"]
    assert r1["invoice_payment"]["invoice_id"] == n and r1["actions"] == ["skip"] and "múltiplo" in r1["warning"]
    confirm(client, seed, job["id"])
    db = TestSession()
    assert db.get(Invoice, n).status == InvoiceStatus.CLOSED
    pay = db.get(Transaction, db.get(Invoice, n_minus_1).paid_by_transaction_id)
    assert pay.extraction_job_id is None and not pay.is_reconciled
    db.close()


# C (#2) — statement imported before the invoice: link, never a 2nd debit
def test_statement_first_then_invoice_links_existing_debit(client, seed):
    acc = new_account(seed)
    card = new_card(seed)
    db = TestSession()
    card_row = db.get(CreditCardAccount, card)
    n = Invoice(id=str(uuid.uuid4()), workspace_id=seed["ws"], credit_card_account_id=card,
                close_date=date(2026, 6, 5), due_date=date(2026, 6, 15), currency=Currency.BRL,
                status=InvoiceStatus.OPEN)
    db.add(n)
    n_id = n.id
    db.commit()
    db.close()
    job = import_statement(client, seed, acc, statement([line(date(2026, 6, 14), "PGTO CARTAO NU", -1500)]))
    row = preview(client, seed, job["id"])["rows"][0]
    assert row["bucket"] == "new" and row["party"]["mode"] == "none" and "fatura" in row["warning"]
    confirm(client, seed, job["id"], {"r0": {"action": "import", "category_id": seed["sub"]}})

    db = TestSession()
    inv = db.get(Invoice, n_id)
    inv.status, inv.total_amount = InvoiceStatus.CLOSED, Decimal("1500.00")
    debit_id = txs_of(db, account_id=acc)[0].id
    db.commit()
    db.close()
    job2 = import_invoice(client, seed, card, {
        "invoice": {"close_date": "2026-07-05", "due_date": "2026-07-15", "total": 30},
        "transactions": [line(date(2026, 6, 14), "PAGAMENTO RECEBIDO", 1500, is_invoice_payment=True),
                         line(date(2026, 6, 20), "MERCADO", -30)],
    })
    row = preview(client, seed, job2["id"])["rows"][0]
    assert row["default_action"] == "link" and row["invoice_payment"]["existing_debit"]["transaction_id"] == debit_id
    confirm(client, seed, job2["id"])
    db = TestSession()
    assert len(txs_of(db, account_id=acc)) == 1          # no second debit
    inv = db.get(Invoice, n_id)
    assert inv.status == InvoiceStatus.PAID and inv.paid_by_transaction_id == debit_id
    debit = db.get(Transaction, debit_id)
    assert debit.paid_invoice_id == n_id and debit.category_id is None and debit.party_id is None
    db.close()
    _ = card_row


def test_link_invoice_payment_service_guards(client, seed):
    acc = new_account(seed)
    card = new_card(seed)
    inv_id = _closed_invoice(card, date(2026, 5, 5), date(2026, 5, 15), "10.00")
    db = TestSession()
    credit = tx_svc.create_transaction(db, seed["ws"], tx_svc.TxInput(
        source_type=TransactionSourceType.CHECKING, checking_account_id=acc,
        event_date=date(2026, 5, 10), description="Estorno", amount=Decimal("10"),
    ))[0]
    with pytest.raises(tx_svc.TransactionError):
        tx_svc.link_invoice_payment(db, db.get(Invoice, inv_id), credit)
    db.rollback()
    db.close()


# D (#4, 9) — card payment from an account in another currency is refused
def test_pay_card_from_other_currency_account_refused(client, seed):
    brl = new_account(seed)
    usd = new_account(seed, "Nomad", currency=Currency.USD)
    card = new_card(seed)
    prev = _closed_invoice(card, date(2026, 4, 5), date(2026, 4, 15), "700.00")
    db = TestSession()   # last payment of this card came from the USD account (manual)
    old = _closed_invoice(card, date(2026, 3, 5), date(2026, 3, 15), "100.00")
    tx_svc.pay_invoice(db, db.get(Invoice, old), checking_account_id=usd, paid_on=date(2026, 3, 14), amount=Decimal("20"))
    db.commit()
    db.close()
    job = import_invoice(client, seed, card, {
        "invoice": {"close_date": "2026-05-05", "due_date": "2026-05-15", "total": 5},
        "transactions": [line(date(2026, 4, 14), "PAGAMENTO RECEBIDO", 700, is_invoice_payment=True),
                         line(date(2026, 4, 20), "CAFE", -5)],
    })
    row = preview(client, seed, job["id"])["rows"][0]
    assert row["invoice_payment"]["invoice_id"] == prev
    assert row["invoice_payment"]["payment_account_id"] is None    # USD default ignored
    r = confirm(client, seed, job["id"], {"r0": {"action": "pay", "payment_account_id": usd}}, expect=400)
    assert "USD" in r["detail"]
    confirm(client, seed, job["id"], {"r0": {"action": "pay", "payment_account_id": brl}})


# D (#19) — line in another currency never stored with the same number
def test_line_in_other_currency_is_converted_with_ptax(client, seed):
    # 2026-11-02 (CSV da Wise): linha USD numa conta BRL importa convertida
    # pela PTAX do dia; só moeda sem cotação fica não importável.
    acc = new_account(seed)
    d = BASE + timedelta(days=110)
    job = import_statement(client, seed, acc, statement([
        {**line(d, "AMAZON US", -25), "currency": "USD"},
        line(d, "PADARIA", -8),
        {**line(d, "LOJA EUROPA", -10), "currency": "EUR"},
    ]))
    r0, r1, r2 = preview(client, seed, job["id"])["rows"]
    assert r0["bucket"] == "new" and r0["default_action"] == "import"
    assert r0["amount"] == "-125.00" and r0["currency"] == "BRL"
    assert r0["original"] == {"amount": "-25.00", "currency": "USD", "rate": "5.00000000",
                              "rate_date": d.isoformat(), "rate_source": "PTAX", "merchant": None, "cross": None}
    assert r1["bucket"] == "new" and "original" not in r1 or r1["original"] is None
    assert r2["bucket"] == "blocked" and r2["actions"] == ["skip"] and "EUR" in r2["warning"]
    confirm(client, seed, job["id"])
    db = TestSession()
    amazon = next(t for t in txs_of(db, account_id=acc) if t.description == "AMAZON US")
    assert amazon.amount == Decimal("-125.00") and amazon.amount_usd == Decimal("-25.00")
    assert amazon.fx_source.value == "PTAX" and amazon.fx_rate == PTAX
    assert amazon.notes == f"US$ 25,00 × PTAX 5,0000 ({d.strftime('%d/%m')})"
    expected_fp = tx_svc.compute_fingerprint(TransactionSourceType.CHECKING, acc, d, Decimal("-25"),
                                             Currency.USD, "AMAZON US")
    assert amazon.fingerprint == expected_fp            # dedup key = ORIGINAL amount/currency
    db.close()


def test_converted_line_dedups_even_after_ptax_correction(client, seed):
    acc = new_account(seed)
    d = BASE + timedelta(days=111)
    lines = [{**line(d, "STRIPE PAYOUT", 40), "currency": "USD"}]
    confirm(client, seed, import_statement(client, seed, acc, statement(lines))["id"])
    db = TestSession()
    rate = db.query(PTAXRate).filter(PTAXRate.date == d).one()
    rate.rate = Decimal("5.12345678")                    # BCB corrected the PTAX
    db.commit()
    db.close()
    try:
        row = preview(client, seed, import_statement(client, seed, acc, statement(lines))["id"])["rows"][0]
        assert row["bucket"] == "duplicate" and row["duplicate"]["reason"] == "fingerprint"
    finally:
        db = TestSession()
        db.query(PTAXRate).filter(PTAXRate.date == d).one().rate = PTAX
        db.commit()
        db.close()


def test_brl_line_on_usd_account_divides(client, seed):
    nomad = new_account(seed, "Nomad", currency=Currency.USD)
    d = BASE + timedelta(days=112)
    job = import_statement(client, seed, nomad, statement([{**line(d, "PIX RECEBIDO", 500), "currency": "BRL"}]))
    row = preview(client, seed, job["id"])["rows"][0]
    assert row["amount"] == "100.00" and row["currency"] == "USD" and row["original"]["currency"] == "BRL"
    confirm(client, seed, job["id"])
    db = TestSession()
    tx = txs_of(db, account_id=nomad)[0]
    assert tx.amount == Decimal("100.00") and tx.amount_brl == Decimal("500.00")
    assert tx.notes.startswith("R$ 500,00 ÷ PTAX 5,0000")
    db.close()


def test_convert_line_stale_ptax_and_no_ptax(db):
    from numis_geek.services.bank_import import _convert_line
    db.add(PTAXRate(id=str(uuid.uuid4()), date=date(2025, 1, 2), rate=Decimal("6.1"),
                    fetched_at=datetime.now(timezone.utc)))
    db.flush()
    fresh = _convert_line(db, date(2025, 1, 5), Decimal("-10"), "USD", "BRL", None)
    assert fresh["converted"] == Decimal("-61.00") and fresh["rate_source"] == "PTAX" and not fresh["warning"]
    stale = _convert_line(db, date(2025, 2, 10), Decimal("-10"), "USD", "BRL", None)
    assert stale["rate_source"] == "PTAX_STALE" and stale["warning"] and stale["rate_date"] == date(2025, 1, 2)
    assert _convert_line(db, date(2024, 12, 1), Decimal("-10"), "USD", "BRL", None) is None
    doc = _convert_line(db, date(2025, 2, 10), Decimal("-10"), "USD", "BRL", Decimal("5.5"))
    assert doc["converted"] == Decimal("-55.00") and doc["rate_source"] == "STATEMENT"


# ── possível duplicata entre arquivos (CSV × PDF da Wise) ───────────────────

def test_possible_duplicate_across_imports_with_different_texts(client, seed):
    acc = new_account(seed)
    csv = import_statement(client, seed, acc, statement([
        line(date(2026, 3, 9), "TRANSFER-2243921860", -1517.33),
        line(date(2026, 3, 10), "CARD-1182 STARBUCKS", -23.9),
    ]))
    confirm(client, seed, csv["id"])
    pdf = import_statement(client, seed, acc, statement([
        line(date(2026, 3, 10), "Transfer to Joao Silva", -1517.33),   # +1 day, other text
        line(date(2026, 3, 13), "Card transaction Starbucks", -23.9),   # +3 days → not flagged
        line(date(2026, 3, 10), "Transfer to Joao Silva", -1517.32),    # off by a cent → not flagged
        line(date(2026, 3, 10), "Received money from Ana", 1517.33),    # other sign
    ]))
    r0, r1, r2, r3 = preview(client, seed, pdf["id"])["rows"]
    assert r0["bucket"] == "duplicate" and r0["duplicate"]["reason"] == "possible_duplicate"
    assert r0["default_action"] == "skip" and "import_anyway" in r0["actions"]
    assert r0["duplicate"]["description"] == "TRANSFER-2243921860"
    assert r0["duplicate"]["event_date"] == "2026-03-09"
    assert [r["bucket"] for r in (r1, r2, r3)] == ["new", "new", "new"]
    confirm(client, seed, pdf["id"], {"r0": {"action": "import_anyway"}})
    db = TestSession()
    assert len(txs_of(db, account_id=acc)) == 6
    db.close()


def test_possible_duplicate_never_against_manual_or_same_file(client, seed):
    acc = new_account(seed)
    db = TestSession()
    tx_svc.create_transaction(db, seed["ws"], tx_svc.TxInput(
        source_type=TransactionSourceType.CHECKING, checking_account_id=acc, event_date=date(2026, 4, 1),
        description="Aluguel garagem", amount=Decimal("-300"),
    ))
    db.commit()
    db.close()
    job = import_statement(client, seed, acc, statement([
        line(date(2026, 4, 2), "DDA GARAGEM", -300),                  # manual nearby → not "possível"
        line(date(2026, 4, 5), "PIX ANA", -80),
        line(date(2026, 4, 5), "PIX BETO", -80),                       # same amount, same file → both import
    ]))
    rows = preview(client, seed, job["id"])["rows"]
    assert [r["bucket"] for r in rows] == ["new", "new", "new"]


def test_possible_duplicate_compares_original_amount_on_fx_rows(client, seed):
    acc = new_account(seed)
    d = date(2026, 4, 20)
    confirm(client, seed, import_statement(client, seed, acc, statement([
        {**line(d, "CARD-99 AWS", -12.34), "currency": "USD"}]))["id"])
    row = preview(client, seed, import_statement(client, seed, acc, statement([
        {**line(d + timedelta(days=1), "Card transaction AWS EMEA", -12.34), "currency": "USD"}]))["id"])["rows"][0]
    assert row["bucket"] == "duplicate" and row["duplicate"]["reason"] == "possible_duplicate"


# E (#5) — a second confirm (stale session / second tab) never applies again
def test_concurrent_confirm_applies_once(client, seed):
    from numis_geek.services import extraction as extraction_service
    acc = new_account(seed)
    job = import_statement(client, seed, acc, statement([line(BASE + timedelta(days=120), "LOJA X", -10)]))
    stale = TestSession()
    stale_job = stale.get(ExtractionJob, job["id"])  # keep a ref: identity map is weak
    assert stale_job.status == ExtractionStatus.EXTRACTED
    confirm(client, seed, job["id"])
    with pytest.raises(extraction_service.ExtractionConflict):
        extraction_service.confirm_extraction(stale, job_id=job["id"], user_id=None)
    stale.rollback()
    stale.close()
    db = TestSession()
    assert len(txs_of(db, account_id=acc)) == 1
    db.close()
    r = client.post(f"/api/extractions/{job['id']}/confirm", json={}, headers=auth(seed["token"]))
    assert r.status_code == 400   # status check: no longer EXTRACTED


# F (#7, 13, 21) — settling inherits the occurrence's party; no junk party
def test_settle_by_description_inherits_occurrence_party(client, seed):
    acc = new_account(seed)
    landlord = _party_with_alias(seed, "Imobiliária Z", "IMOBILIARIA Z LTDA")
    due = BASE + timedelta(days=130)
    db = TestSession()
    occ = sched_svc.create_one_off(db, seed["ws"], sched_svc.OccurrenceInput(
        direction=ScheduledDirection.PAYABLE, description="Aluguel Apto", amount=Decimal("3000"),
        due_date=due, currency=Currency.BRL, party_id=landlord))
    occ_id = occ.id
    db.commit()
    db.close()
    job = import_statement(client, seed, acc, statement([line(due, "TED ALUGUEL APTO MAIO", -3000)]))
    row = preview(client, seed, job["id"])["rows"][0]
    assert row["bucket"] == "scheduled"
    assert row["party"]["mode"] == "none" and row["party"]["from_occurrence"] is True
    assert row["scheduled"]["candidates"][0]["party_name"] == "Imobiliária Z"
    confirm(client, seed, job["id"])
    db = TestSession()
    tx = db.get(Transaction, db.get(ScheduledTransaction, occ_id).paid_by_transaction_id)
    assert tx.party_id == landlord
    assert db.query(PartyAlias).filter(PartyAlias.alias_normalized == "TED ALUGUEL APTO MAIO").count() == 0
    db.close()


# G (#10) — FX keeps precision and matches usd_amount
def test_fx_rate_precision_from_usd_amount(client, seed):
    card = new_card(seed)
    job = import_invoice(client, seed, card, {
        "invoice": {"close_date": "2026-09-05", "due_date": "2026-09-15", "total": 545.67},
        "transactions": [line(date(2026, 8, 20), "GITHUB", -545.67, fx={"usd_amount": 100.0, "rate": 5.4567})],
    })
    confirm(client, seed, job["id"])
    db = TestSession()
    tx = txs_of(db, card_id=card)[0]
    assert tx.fx_rate == Decimal("5.45670000") and tx.amount_usd == Decimal("-100.00")
    db.close()


# H (#11) — credit balance invoice is not an amount owed
def test_negative_invoice_total_stored_as_zero(client, seed):
    acc = new_account(seed)
    card = new_card(seed)
    job = import_invoice(client, seed, card, {
        "invoice": {"close_date": "2026-10-05", "due_date": "2026-10-15", "total": -200},
        "transactions": [line(date(2026, 9, 20), "ESTORNO LOJA", 250), line(date(2026, 9, 21), "CAFE", -50)],
    })
    p = preview(client, seed, job["id"])
    assert p["invoice"]["total_amount"] == "0.00" and any("credor" in w for w in p["warnings"])
    confirm(client, seed, job["id"])
    db = TestSession()
    inv = db.query(Invoice).filter(Invoice.credit_card_account_id == card).one()
    assert inv.total_amount == Decimal("0.00")
    db.close()
    job2 = import_statement(client, seed, acc, statement([line(date(2026, 10, 10), "DEBITO QUALQUER", -200)]))
    assert preview(client, seed, job2["id"])["rows"][0]["bucket"] == "new"


# I (#14) — best match across lines, not file order
def test_occurrence_assignment_is_global_best_match(client, seed):
    acc = new_account(seed)
    due = BASE + timedelta(days=140)
    db = TestSession()
    occ = sched_svc.create_one_off(db, seed["ws"], sched_svc.OccurrenceInput(
        direction=ScheduledDirection.PAYABLE, description="Escola", amount=Decimal("3000"),
        due_date=due, currency=Currency.BRL))
    occ_id = occ.id
    db.commit()
    db.close()
    job = import_statement(client, seed, acc, statement([
        line(due - timedelta(days=4), "TED ESCOLA", -2950),
        line(due, "TED ESCOLA", -3000),
    ]))
    r0, r1 = preview(client, seed, job["id"])["rows"]
    assert r1["bucket"] == "scheduled" and r1["scheduled"]["occurrence_id"] == occ_id
    assert r0["bucket"] == "new" and "settle" in r0["actions"]
    assert [c["occurrence_id"] for c in r0["scheduled"]["candidates"]] == [occ_id]
    confirm(client, seed, job["id"])
    db = TestSession()
    tx = db.get(Transaction, db.get(ScheduledTransaction, occ_id).paid_by_transaction_id)
    assert tx.amount == Decimal("-3000.00")
    db.close()


# J (#17) — discarded on the wrong account → importable on the right one
def test_file_discarded_on_wrong_account_can_go_to_right_one(client, seed):
    a, b = new_account(seed), new_account(seed)
    content = b"wrong-account-" + uuid.uuid4().hex.encode()
    payload = statement([line(BASE, "X", -1)])
    job = import_statement(client, seed, a, payload, content=content)
    r = client.post(f"/api/extractions/{job['id']}/reject", json={}, headers=auth(seed["token"]))
    assert r.status_code == 200
    r, _ = upload(client, seed, f"/accounts/{b}/statement-imports", payload, content=content)
    assert r.status_code == 201 and r.json()["status"] == "EXTRACTED"
    assert r.json()["attachment_id"] != job["attachment_id"]


# K (#18) — a confirmed import can't be rejected
def test_reject_confirmed_import_is_409(client, seed):
    acc = new_account(seed)
    job = import_statement(client, seed, acc, statement([line(BASE + timedelta(days=150), "Y", -1)]))
    confirm(client, seed, job["id"])
    r = client.post(f"/api/extractions/{job['id']}/reject", json={}, headers=auth(seed["token"]))
    assert r.status_code == 409
    assert client.delete(f"/api/attachments/{job['attachment_id']}", headers=auth(seed["token"])).status_code == 409


# L (#20) — card invoice period is the cycle, not the oldest installment date
def test_card_invoice_period_is_the_cycle(client, seed):
    card = new_card(seed)
    job = import_invoice(client, seed, card, {
        "invoice": {"close_date": "2026-03-05", "due_date": "2026-03-15", "total": 110},
        "transactions": [line(date(2026, 1, 10), "NOTEBOOK", -100, installment="3/10"),
                         line(date(2026, 2, 20), "CAFE", -10)],
    })
    assert job["statement_period_start"] == "2026-02-06" and job["statement_period_end"] == "2026-03-05"


# ══ party por tipo de linha (decisão do user 2026-11-02) ════════════════════

def _party_of(db, tx_id):
    tx = db.get(Transaction, tx_id)
    return db.get(Party, tx.party_id) if tx.party_id else None


def test_iof_has_no_hardcoded_party_and_learns_the_users_choice(client, seed):
    # 2026-11-02: "pode apagar essa regra fixa" — nada de "Receita Federal".
    card = new_card(seed)
    job = import_invoice(client, seed, card, {
        "invoice": {"close_date": "2026-09-05", "due_date": "2026-09-15", "total": 13.5},
        "transactions": [
            line(date(2026, 8, 20), "IOF COMPRA EXTERIOR TESTE D", -3.5, line_kind="IOF"),
            line(date(2026, 8, 21), "IOF S/ COMPRA EXTERIOR 0042", -10),          # fallback, no line_kind
        ],
    })
    rows = preview(client, seed, job["id"])["rows"]
    assert all(r["party"]["mode"] == "none" and r["party"]["source"] == "iof" for r in rows)
    assert all(not r["warning"] for r in rows)                                  # no nagging
    gov = _party_with_alias(seed, "Governo", "GOVERNO ALIAS IOF TESTE")
    confirm(client, seed, job["id"], {"r0": {"action": "import", "party_id": gov}, "r1": {"action": "import"}})
    db = TestSession()
    assert db.query(Party).filter(Party.workspace_id == seed["ws"], Party.name == "Receita Federal").count() == 0
    db.close()
    acc = new_account(seed)
    job2 = import_statement(client, seed, acc, statement([line(date(2026, 9, 2), "IOF ADIC CHEQUE ESPECIAL", -1.2)]))
    row = preview(client, seed, job2["id"])["rows"][0]
    assert row["party"]["mode"] == "existing" and row["party"]["party_id"] == gov


def test_bank_fees_go_to_the_account_institution(client, seed):
    acc = new_account(seed)
    job = import_statement(client, seed, acc, statement([
        line(BASE + timedelta(days=160), "TARIFA PACOTE SERVICOS", -45, line_kind="BANK_FEE"),
        line(BASE + timedelta(days=161), "CESTA DE SERVICOS 11/2026", -30),     # fallback
        line(BASE + timedelta(days=162), "JUROS CHEQUE ESPECIAL", -12.3),       # fallback
    ]))
    rows = preview(client, seed, job["id"])["rows"]
    assert {r["party"]["new_party_name"] for r in rows} == {"BBI"}
    assert all(r["party"]["source"] == "bank_fee" for r in rows)
    confirm(client, seed, job["id"])
    card = new_card(seed)   # same FI → same party
    job2 = import_invoice(client, seed, card, {
        "invoice": {"close_date": "2026-09-05", "due_date": "2026-09-15", "total": 39},
        "transactions": [line(date(2026, 8, 20), "ANUIDADE DIFERENCIADA 03/12", -39)],
    })
    row = preview(client, seed, job2["id"])["rows"][0]
    assert row["party"]["mode"] == "existing" and row["party"]["party_name"] == "BBI"
    db = TestSession()
    assert db.query(Party).filter(Party.workspace_id == seed["ws"], Party.name == "BBI").count() == 1
    db.close()


def test_pix_uses_counterparty_never_raw_text(client, seed):
    acc = new_account(seed)
    job = import_statement(client, seed, acc, statement([
        line(BASE + timedelta(days=170), "PIX TRANSF JOAO S 12/03", -150, line_kind="PIX", counterparty="João da Silva"),
        line(BASE + timedelta(days=171), "PIX RECEBIDO MARIA 13/03", 80, counterparty="Maria Souza ME"),
        line(BASE + timedelta(days=172), "PIX TRANSF 9981", -20),              # no counterparty
        line(BASE + timedelta(days=173), "TED 033 0001 ACME", -900, line_kind="TED", counterparty="ACME LTDA"),
    ]))
    r0, r1, r2, r3 = preview(client, seed, job["id"])["rows"]
    assert r0["party"]["new_party_name"] == "João da Silva" and r0["party"]["alias"] == "JOÃO DA SILVA"
    assert r1["party"]["new_party_name"] == "Maria Souza ME"
    assert r2["party"]["mode"] == "none" and "Pix sem recebedor" in r2["warning"]
    assert r3["party"]["new_party_name"] == "ACME LTDA"
    confirm(client, seed, job["id"])
    db = TestSession()
    t0, t1, t2, t3 = txs_of(db, account_id=acc)
    assert _party_of(db, t0.id).name == "João da Silva"
    assert _party_of(db, t1.id).name == "Maria Souza ME"
    assert t2.party_id is None
    assert db.query(PartyAlias).filter(PartyAlias.alias_normalized.like("PIX%")).count() == 0
    db.close()
    # same counterparty in another Pix → reused
    job2 = import_statement(client, seed, acc, statement([
        line(BASE + timedelta(days=180), "PIX TRANSF JOAO S 01/04", -150, counterparty="JOÃO DA SILVA"),
    ]))
    row = preview(client, seed, job2["id"])["rows"][0]
    assert row["party"]["mode"] == "existing" and row["party"]["party_name"] == "João da Silva"


def test_description_alias_still_wins_and_review_can_override(client, seed):
    acc = new_account(seed)
    mine = _party_with_alias(seed, "Minha Diarista", "PIX TRANSF ANA DIARISTA")
    job = import_statement(client, seed, acc, statement([
        line(BASE + timedelta(days=190), "PIX TRANSF ANA DIARISTA", -200, line_kind="PIX", counterparty="Ana Paula"),
        line(BASE + timedelta(days=191), "IOF COMPRA", -1, line_kind="IOF"),
    ]))
    r0, _ = preview(client, seed, job["id"])["rows"]
    assert r0["party"]["mode"] == "existing" and r0["party"]["party_id"] == mine
    confirm(client, seed, job["id"], {"r1": {"action": "import", "party_id": mine}})
    db = TestSession()
    t0, t1 = txs_of(db, account_id=acc)
    assert t0.party_id == mine and t1.party_id == mine
    db.close()


def test_line_kind_fallbacks():
    from numis_geek.services.bank_import import line_kind_of
    assert line_kind_of("IOF S/ COMPRA EXTERIOR", Decimal("-1"), None) == "IOF"
    assert line_kind_of("PIX ENVIADO FULANO", Decimal("-1"), None) == "PIX"
    assert line_kind_of("TARIFA BANCARIA", Decimal("-1"), None) == "BANK_FEE"
    assert line_kind_of("JUROS S/ CAPITAL PROPRIO", Decimal("10"), None) is None   # income, not a fee
    assert line_kind_of("ALUGUEL MORADIA", Decimal("-1"), None) is None
    assert line_kind_of("QUALQUER", Decimal("-1"), "bank_fee") == "BANK_FEE"
    assert line_kind_of("QUALQUER", Decimal("-1"), "nonsense") is None


# ══ contas a pagar/receber aprendem o valor do extrato (user 2026-11-02) ════

def _rule(seed, desc, amount, frequency, **kw):
    from numis_geek.models.scheduled_transaction import RecurrenceFrequency, RecurrenceRule
    db = TestSession()
    rule, occs = sched_svc.create_rule(db, seed["ws"], sched_svc.RuleInput(
        direction=ScheduledDirection.PAYABLE, description=desc, amount=Decimal(amount),
        frequency=RecurrenceFrequency[frequency], day_of_month=5, start_date=date(2026, 3, 5),
        currency=Currency.BRL, **kw,
    ))
    by_due = {o.due_date: o.id for o in occs}
    rid = rule.id
    db.commit()
    db.close()
    return rid, by_due


def test_import_settling_monthly_rule_learns_the_paid_amount(client, seed):
    from numis_geek.models.scheduled_transaction import RecurrenceRule
    acc = new_account(seed)
    rid, occ = _rule(seed, "Internet Vivo Fibra", "300", "MONTHLY")
    apr, may, jun, jul = (occ[date(2026, m, 5)] for m in (4, 5, 6, 7))
    mar = occ[date(2026, 3, 5)]
    db = TestSession()
    db.get(ScheduledTransaction, jun).amount = Decimal("280")   # edited by hand
    db.commit()
    db.close()

    job = import_statement(client, seed, acc, statement([line(date(2026, 4, 5), "DEB AUT INTERNET VIVO FIBRA", -312.4)]))
    row = preview(client, seed, job["id"])["rows"][0]
    assert row["bucket"] == "scheduled" and row["scheduled"]["occurrence_id"] == apr
    assert row["scheduled"]["candidates"][0]["learns_amount"] is True
    res = confirm(client, seed, job["id"])
    assert res["bank_import"]["amounts_learned"] == 1

    db = TestSession()
    assert db.get(RecurrenceRule, rid).amount == Decimal("312.40")
    assert db.get(ScheduledTransaction, apr).status == ScheduledStatus.PAID
    assert db.get(ScheduledTransaction, apr).amount == Decimal("300.00")      # settled one keeps its forecast
    assert db.get(ScheduledTransaction, mar).amount == Decimal("300.00")      # earlier: untouched
    assert db.get(ScheduledTransaction, may).amount == Decimal("312.40")
    assert db.get(ScheduledTransaction, jul).amount == Decimal("312.40")
    assert db.get(ScheduledTransaction, jun).amount == Decimal("280.00")      # hand edit preserved
    from numis_geek.models.audit_log import AuditLog
    log = db.query(AuditLog).filter(AuditLog.action == "recurrence_rule.amount_learned",
                                    AuditLog.resource_id == rid).one()
    details = json.loads(log.details) if isinstance(log.details, str) else log.details
    assert details["old_amount"] == "300.00" and details["new_amount"] == "312.40"
    assert may in details["occurrence_ids"] and jun not in details["occurrence_ids"]
    db.close()


def test_same_amount_learns_nothing(client, seed):
    from numis_geek.models.scheduled_transaction import RecurrenceRule
    acc = new_account(seed)
    rid, occ = _rule(seed, "Academia Smart", "120", "MONTHLY")
    job = import_statement(client, seed, acc, statement([line(date(2026, 4, 5), "ACADEMIA SMART FIT", -120)]))
    assert confirm(client, seed, job["id"])["bank_import"]["amounts_learned"] == 0
    db = TestSession()
    assert db.get(RecurrenceRule, rid).amount == Decimal("120.00")
    db.close()


def test_installment_rule_never_learns(client, seed):
    from numis_geek.models.scheduled_transaction import RecurrenceRule
    acc = new_account(seed)
    rid, occ = _rule(seed, "Parcela Sofa Tok", "500", "INSTALLMENT", installment_total=10)
    job = import_statement(client, seed, acc, statement([line(date(2026, 4, 5), "PARCELA SOFA TOK STOK", -510)]))
    row = preview(client, seed, job["id"])["rows"][0]
    assert row["bucket"] == "scheduled" and row["scheduled"]["candidates"][0]["learns_amount"] is False
    confirm(client, seed, job["id"])
    db = TestSession()
    assert db.get(RecurrenceRule, rid).amount == Decimal("500.00")
    assert db.get(ScheduledTransaction, occ[date(2026, 5, 5)]).amount == Decimal("500.00")
    db.close()


def test_manual_mark_paid_does_not_learn(client, seed):
    from numis_geek.models.scheduled_transaction import RecurrenceRule
    acc = new_account(seed)
    rid, occ = _rule(seed, "Plano Celular", "90", "MONTHLY")
    db = TestSession()
    tx = tx_svc.create_transaction(db, seed["ws"], tx_svc.TxInput(
        source_type=TransactionSourceType.CHECKING, checking_account_id=acc,
        event_date=date(2026, 4, 5), description="Celular", amount=Decimal("-95"),
    ))[0]
    sched_svc.mark_paid(db, db.get(ScheduledTransaction, occ[date(2026, 4, 5)]), paid_at=date(2026, 4, 5),
                        transaction_id=tx.id)
    db.commit()
    assert db.get(RecurrenceRule, rid).amount == Decimal("90.00")
    assert db.get(ScheduledTransaction, occ[date(2026, 5, 5)]).amount == Decimal("90.00")
    db.close()
    r = client.post(f"/api/scheduled-transactions/{occ[date(2026, 6, 5)]}/pay",
                    json={"paid_at": "2026-06-05"}, headers=auth(seed["token"]))
    assert r.status_code == 200, r.text
    db = TestSession()
    assert db.get(RecurrenceRule, rid).amount == Decimal("90.00")
    db.close()


def test_one_off_occurrence_never_learns(client, seed):
    acc = new_account(seed)
    due = BASE + timedelta(days=200)
    db = TestSession()
    o = sched_svc.create_one_off(db, seed["ws"], sched_svc.OccurrenceInput(
        direction=ScheduledDirection.PAYABLE, description="IPVA Unico", amount=Decimal("1000"),
        due_date=due, currency=Currency.BRL))
    oid = o.id
    db.commit()
    db.close()
    job = import_statement(client, seed, acc, statement([line(due, "IPVA UNICO SP", -1020)]))
    assert confirm(client, seed, job["id"])["bank_import"]["amounts_learned"] == 0
    db = TestSession()
    assert db.get(ScheduledTransaction, oid).amount == Decimal("1000.00")
    db.close()


# ── Itaú .xls + lançamentos futuros (2026-11-02, primeiro import real) ──────

def test_future_dated_lines_are_dropped_with_warning(client, seed):
    acc = new_account(seed)
    past, future = date.today() - timedelta(days=3), date.today() + timedelta(days=20)
    job = import_statement(client, seed, acc, statement(
        [line(past, "MERCADO X", -100), line(future, "DDA PAG TIT", -3384.75)]))
    p = preview(client, seed, job["id"])
    assert [r["description"] for r in p["rows"]] == ["MERCADO X"]
    assert any("lançamento futuro" in w for w in p["warnings"])


def test_xls_reader_and_mojibake_fix():
    from numis_geek.services.extraction import _fix_mojibake
    assert _fix_mojibake("SALDO TOTAL DISPONÃ\x8dVEL DIA") == "SALDO TOTAL DISPONÍVEL DIA"
    assert _fix_mojibake("Lançamentos") == "Lançamentos"


def test_unreadable_spreadsheet_raises_clear_error(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from numis_geek.services import extraction as ex
    f = tmp_path / "x.xls"
    f.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1garbage")
    monkeypatch.setattr(ex.attachment_storage, "absolute_path_for", lambda a: str(f))
    att = SimpleNamespace(kind=None, mime_type="application/vnd.ms-excel")
    with pytest.raises(ex.ExtractionError, match="planilha"):
        ex._read_attachment_payload(att)


def test_long_statement_is_extracted_in_chunks_and_merged(client, seed):
    from numis_geek.services.extraction import STATEMENT_CHUNK_LINES

    class ChunkLLM:
        def __init__(self):
            self.calls = 0

        def call(self, *, system, user_text, image_bytes=None, image_mime=None,
                 image_parts=None, model="claude-sonnet-4-5", max_tokens=4096):
            from numis_geek.services.bank_classifier import SYSTEM1_MODEL
            if model == SYSTEM1_MODEL:   # System 1 pass (categorias) — não é extração
                return LLMCall(text='{"lines": []}', input_tokens=1, output_tokens=1, model=model)
            self.calls += 1
            rows = [l for l in user_text.splitlines() if l[:2].isdigit()]
            txs = [line(date(2026, 3, int(r.split("/")[0])), r.split(",")[1], r.split(",")[2]) for r in rows]
            body = {"transactions": txs, "period": {"start": "2026-03-01", "end": "2026-03-28"},
                    "institution_name": "Itaú", "confidence": 0.9}
            return LLMCall(text=json.dumps(body), input_tokens=10, output_tokens=5, model=model)

    acc = new_account(seed)
    n = STATEMENT_CHUNK_LINES * 2 + 5
    csv_text = "Banco X\nConta: 123\ndata,lançamento,valor\n" + "\n".join(
        f"{(i % 28) + 1:02d}/03/2026,LOJA {i},-{i + 1}" for i in range(n))
    fake = ChunkLLM()
    set_llm_client(fake)
    r = client.post(f"/api/accounts/{acc}/statement-imports",
                    files={"file": ("longo.csv", csv_text.encode(), "text/csv")}, headers=auth(seed["token"]))
    assert r.status_code == 201, r.text
    assert fake.calls == 3
    p = preview(client, seed, r.json()["id"])
    assert len(p["rows"]) == n


def test_chunk_that_skipped_lines_is_asked_again():
    from numis_geek.services.extraction import _call_chunked, _expected_movements
    from numis_geek.services.extraction_templates import BANK_STATEMENT

    chunk = "Banco\ndata,desc,valor\n01/03/2026,A,-1\n02/03/2026,B,-2\n02/03/2026,SALDO TOTAL,,9\n03/03/2026,C,-3\nlançamentos futuros\n09/03/2026,D,-4"
    assert _expected_movements(chunk) == 3

    class Flaky:
        calls = 0

        def call(self, *, system, user_text, model, **kw):
            Flaky.calls += 1
            n = 2 if Flaky.calls == 1 else 3
            txs = [line(date(2026, 3, i + 1), f"L{i}", -1) for i in range(n)]
            return LLMCall(text=json.dumps({"transactions": txs}), input_tokens=1, output_tokens=1, model=model)

    call, obj = _call_chunked(Flaky(), BANK_STATEMENT, [chunk, chunk.replace("Banco", "Banco 2")])
    assert len(obj["transactions"]) >= 5 and Flaky.calls >= 3



# ══ 1º import real (2026-11-02) ═════════════════════════════════════════════

def test_four_identical_indemnities_in_one_file_all_import(client, seed):
    acc = new_account(seed)
    d = date(2026, 9, 18)
    lines = [line(d, "LATAM AIRLINES INDENIZ", 3395.41) for _ in range(4)] + [line(d, "PIX MARIA N", -50)] * 2
    job = import_statement(client, seed, acc, statement(lines))
    rows = preview(client, seed, job["id"])["rows"]
    assert all(r["bucket"] == "new" and r["default_action"] == "import" for r in rows)
    confirm(client, seed, job["id"])
    db = TestSession()
    txs = txs_of(db, account_id=acc)
    assert len(txs) == 6
    latam = sorted(t.fingerprint for t in txs if t.description.startswith("LATAM"))
    base = latam[0]
    assert latam == [base, base + ":2", base + ":3", base + ":4"]
    db.close()
    # only what is already in the DB counts as duplicate: same file again (other bytes) → 6 dups
    job2 = import_statement(client, seed, acc, statement(lines))
    rows = preview(client, seed, job2["id"])["rows"]
    assert all(r["bucket"] == "duplicate" for r in rows)
    # a file with 5 identical lines: 4 match, the 5th is new
    job3 = import_statement(client, seed, acc, statement([line(d, "LATAM AIRLINES INDENIZ", 3395.41) for _ in range(5)]))
    rows = preview(client, seed, job3["id"])["rows"]
    assert [r["bucket"] for r in rows] == ["duplicate"] * 4 + ["new"]


# ── System 1 (categoria por LLM rápido) ─────────────────────────────────────

class RoutedLLM:
    """Extraction calls get `payload`; System 1 calls get `s1` (or raise)."""

    def __init__(self, payload, s1=None, s1_error=None):
        self.payload, self.s1, self.s1_error = payload, s1, s1_error
        self.s1_calls: list[str] = []

    def call(self, *, system, user_text, image_bytes=None, image_mime=None,
             image_parts=None, model="claude-sonnet-4-5", max_tokens=4096):
        from numis_geek.services.bank_classifier import SYSTEM1_MODEL
        if model == SYSTEM1_MODEL:
            self.s1_calls.append(user_text)
            if self.s1_error:
                raise RuntimeError(self.s1_error)
            body = self.s1(user_text) if callable(self.s1) else self.s1
            return LLMCall(text=json.dumps(body or {"lines": []}), input_tokens=1_000_000,
                           output_tokens=100_000, model=model)
        return LLMCall(text=json.dumps(self.payload), input_tokens=100, output_tokens=50, model=model)


def import_with(client, seed, account_id, payload, s1=None, s1_error=None):
    fake = RoutedLLM(payload, s1, s1_error)
    set_llm_client(fake)
    r = client.post(f"/api/accounts/{account_id}/statement-imports",
                    files={"file": ("e.csv", (uuid.uuid4().hex + json.dumps(payload)).encode(), "text/csv")},
                    headers=auth(seed["token"]))
    assert r.status_code == 201 and r.json()["status"] == "EXTRACTED", r.text
    return r.json(), fake


def test_system1_suggests_category_by_confidence_and_persists(client, seed):
    acc = new_account(seed)
    lines = [line(date(2026, 9, 1), "PADARIA DO ZE", -12), line(date(2026, 9, 2), "LOJA QUALQUER", -30),
             line(date(2026, 9, 3), "OUTRA", -5)]
    s1 = {"lines": [
        {"i": 0, "category_id": seed["sub"], "confidence": 0.92, "reason": "igual ao histórico"},
        {"i": 1, "category_id": seed["sub"], "confidence": 0.4, "reason": "palpite"},
        {"i": 2, "category_id": "nao-existe", "confidence": 0.99, "reason": "inventada"},
    ]}
    job, fake = import_with(client, seed, acc, statement(lines), s1)
    assert len(fake.s1_calls) == 1                       # ran at extraction time
    r0, r1, r2 = preview(client, seed, job["id"])["rows"]
    assert len(fake.s1_calls) == 1                       # persisted: preview doesn't re-run
    assert r0["category_id"] == seed["sub"] and r0["category_suggestion"]["applied"] is True
    assert r0["category_suggestion"]["reason"] == "igual ao histórico"
    assert r1["category_id"] is None and r1["category_suggestion"]["applied"] is False
    assert r2["category_id"] is None and "category_suggestion" not in r2   # ids outside the list ignored
    db = TestSession()
    j = db.get(ExtractionJob, job["id"])
    from numis_geek.services.bank_classifier import SYSTEM1_VERSION
    assert j.classification_json["version"] == SYSTEM1_VERSION
    assert j.cost_usd >= Decimal("0.15")                 # 1M in × $0.10 + 100k out × $0.50 added
    db.close()
    confirm(client, seed, job["id"], {"r2": {"action": "import", "category_id": None}})
    db = TestSession()
    t0, t1, t2 = txs_of(db, account_id=acc)
    assert t0.category_id == seed["sub"] and t1.category_id is None and t2.category_id is None
    db.close()


def test_system1_explicit_no_category_beats_suggestion(client, seed):
    acc = new_account(seed)
    job, _ = import_with(client, seed, acc, statement([line(date(2026, 9, 4), "X", -1)]),
                         {"lines": [{"i": 0, "category_id": seed["sub"], "confidence": 0.95, "reason": "r"}]})
    confirm(client, seed, job["id"], {"r0": {"action": "import", "category_id": None}})
    db = TestSession()
    assert txs_of(db, account_id=acc)[0].category_id is None
    db.close()


def test_system1_runs_lazily_on_already_extracted_job(client, seed):
    acc = new_account(seed)
    job, fake = import_with(client, seed, acc, statement([line(date(2026, 9, 5), "MERCADO ABC", -80)]), {"lines": []})
    db = TestSession()
    j = db.get(ExtractionJob, job["id"])
    j.classification_json = None          # job extracted before System 1 existed (prod 5d6dd50f)
    db.commit()
    db.close()
    fake.s1 = {"lines": [{"i": 0, "category_id": seed["sub"], "confidence": 0.8, "reason": "mercado"}]}
    row = preview(client, seed, job["id"])["rows"][0]
    assert row["category_id"] == seed["sub"] and len(fake.s1_calls) == 2
    preview(client, seed, job["id"])
    assert len(fake.s1_calls) == 2


def test_system1_input_has_categories_history_and_occurrences(client, seed):
    acc = new_account(seed)
    db = TestSession()
    past = tx_svc.create_transaction(db, seed["ws"], tx_svc.TxInput(
        source_type=TransactionSourceType.CHECKING, checking_account_id=acc, event_date=date(2026, 8, 18),
        description="ACOUGUE BOI GORDO 18/08", amount=Decimal("-77"), category_id=seed["sub"],
    ))[0]
    _ = past.id
    db.commit()
    db.close()
    rid, occ = _rule_day(seed, "Condominio Edificio", "900", 15)
    job, fake = import_with(client, seed, acc, statement([line(date(2026, 9, 18), "ACOUGUE BOI GORDO 18/09", -81)]))
    payload = json.loads(fake.s1_calls[0].split("\n\n", 1)[1])
    assert {"id": seed["sub"], "path": "Moradia › Aluguel", "kind": "EXPENSE"} in payload["CATEGORIAS"]
    hist = payload["LINHAS"][0]["historico"]
    assert hist and hist[0]["description"] == "ACOUGUE BOI GORDO 18/08" and hist[0]["category"] == "Moradia › Aluguel"
    assert any(o["description"] == "Condominio Edificio" for o in payload["CONTAS_A_PAGAR_RECEBER"])


def test_system1_failure_never_blocks_the_import(client, seed):
    acc = new_account(seed)
    job, _ = import_with(client, seed, acc, statement([line(date(2026, 9, 6), "Y", -2)]), s1_error="boom")
    row = preview(client, seed, job["id"])["rows"][0]
    assert row["bucket"] == "new" and row["category_id"] is None
    db = TestSession()
    assert "boom" in db.get(ExtractionJob, job["id"]).classification_json["errors"][0]
    db.close()
    confirm(client, seed, job["id"])


# ── matcher pontuado de contas a pagar/receber ──────────────────────────────

def _rule_day(seed, desc, amount, day, **kw):
    from numis_geek.models.scheduled_transaction import RecurrenceFrequency
    db = TestSession()
    rule, occs = sched_svc.create_rule(db, seed["ws"], sched_svc.RuleInput(
        direction=ScheduledDirection.PAYABLE, description=desc, amount=Decimal(amount),
        frequency=RecurrenceFrequency.MONTHLY, day_of_month=day, start_date=date(2026, 3, day),
        currency=Currency.BRL, **kw,
    ))
    by_due = {o.due_date: o.id for o in occs}
    rid = rule.id
    db.commit()
    db.close()
    return rid, by_due


def test_notion_rule_without_party_is_candidate_not_default(client, seed):
    acc = new_account(seed)
    rid, occ = _rule_day(seed, "Condomínio Notion", "1234.56", 5)
    sat = occ[date(2026, 9, 5)]                                   # Saturday
    job = import_statement(client, seed, acc, statement([line(date(2026, 9, 8), "DDA PAG TIT", -1234.56)]))
    row = preview(client, seed, job["id"])["rows"][0]
    assert row["bucket"] == "new" and row["default_action"] == "import"   # generic text → user picks
    cand = row["scheduled"]["candidates"][0]
    assert cand["occurrence_id"] == sat and "próximo dia útil" in cand["signals"]
    assert "tipo de lançamento" in cand["signals"]
    # user picks it → the rule learns the bank text
    confirm(client, seed, job["id"], {"r0": {"action": "settle"}})
    from numis_geek.models.scheduled_transaction import RecurrenceRuleAlias
    db = TestSession()
    assert db.query(RecurrenceRuleAlias).filter(RecurrenceRuleAlias.recurrence_rule_id == rid).one().alias_normalized == "DDA PAG TIT"
    db.close()
    # next month: amount floated 8%, paid a day late → learned alias makes it confident
    job2 = import_statement(client, seed, acc, statement([line(date(2026, 10, 6), "DDA PAG TIT", -1333.32)]))
    row = preview(client, seed, job2["id"])["rows"][0]
    assert row["bucket"] == "scheduled" and row["default_action"] == "settle"
    assert row["scheduled"]["occurrence_id"] == occ[date(2026, 10, 5)]
    assert "já quitou esta conta antes" in row["scheduled"]["candidates"][0]["signals"]


def test_scheduled_hard_constraints(client, seed):
    acc = new_account(seed)
    other_acc = new_account(seed)
    _rule_day(seed, "Escola Piaget", "2000", 10)
    _rule_day(seed, "Clube Pinheiros", "2000", 10, expected_account_id=other_acc)
    job = import_statement(client, seed, acc, statement([
        line(date(2026, 9, 10), "MENSALIDADE ESCOLA PIAGET", -2500),   # +25% → still candidate
        line(date(2026, 10, 10), "MENSALIDADE ESCOLA PIAGET", -2700),  # +35% → out
        line(date(2026, 8, 10), "ESCOLA PIAGET", 2000),                # wrong direction
        line(date(2026, 7, 23), "ESCOLA PIAGET", -2000),               # 13 days late → out
    ]))
    r0, r1, r2, r3 = preview(client, seed, job["id"])["rows"]
    piaget = [c for c in r0["scheduled"]["candidates"] if c["description"] == "Escola Piaget"]
    assert piaget and piaget[0]["occurrence_id"] == r0["scheduled"]["occurrence_id"]
    assert all(c["description"] != "Escola Piaget" for c in (r1.get("scheduled") or {}).get("candidates", []))
    assert "scheduled" not in r2 and "scheduled" not in r3 or all(
        c["description"] != "Escola Piaget" for c in r3["scheduled"]["candidates"])
    # expected_account elsewhere is penalised: Clube never outranks
    assert r0["scheduled"]["candidates"][0]["description"] == "Escola Piaget"


def test_system1_occurrence_signal_makes_match_confident(client, seed):
    acc = new_account(seed)
    rid, occ = _rule_day(seed, "Diarista Fixa", "480", 15)
    target = occ[date(2026, 9, 15)]
    job, _ = import_with(client, seed, acc, statement([line(date(2026, 9, 15), "PIX TRANSF 88812", -480)]),
                         lambda text: {"lines": [{"i": 0, "category_id": None, "confidence": 0.3,
                                                  "occurrence_id": target, "reason": "valor e data da diarista"}]})
    row = preview(client, seed, job["id"])["rows"][0]
    assert row["bucket"] == "scheduled" and row["scheduled"]["occurrence_id"] == target
    assert "sugerida pela IA" in row["scheduled"]["candidates"][0]["signals"]


# ── memória de fornecedor + chave de grupo ──────────────────────────────────

def test_party_choice_is_remembered_without_trailing_dates(client, seed):
    from numis_geek.services.bank_import import alias_key
    assert alias_key("PIX MARIA N 18/09") == "PIX MARIA N"
    assert alias_key("PIX MARIA N 18/09/2026 SP") == "PIX MARIA N"
    acc = new_account(seed)
    diarista = _party_with_alias(seed, "Maria (diarista)", "MARIA DIARISTA ALIAS")
    job = import_statement(client, seed, acc, statement([
        line(date(2026, 9, 18), "PIX MARIA N 18/09", -150, line_kind="PIX"),
        line(date(2026, 9, 25), "PIX MARIA N 25/09", -150, line_kind="PIX"),
    ]))
    r0, r1 = preview(client, seed, job["id"])["rows"]
    assert r0["group_key"] == r1["group_key"] == "PIX MARIA N"
    assert r0["party"]["mode"] == "none"                            # Pix sem recebedor
    confirm(client, seed, job["id"], {"r0": {"action": "import", "party_id": diarista},
                                       "r1": {"action": "import", "party_id": diarista}})
    job2 = import_statement(client, seed, acc, statement([line(date(2026, 10, 2), "PIX MARIA N 02/10", -150, line_kind="PIX")]))
    row = preview(client, seed, job2["id"])["rows"][0]
    assert row["party"]["mode"] == "existing" and row["party"]["party_id"] == diarista


def test_temperature_only_for_models_that_accept_it():
    from numis_geek.integrations.llm import accepts_temperature
    assert accepts_temperature("claude-sonnet-4-5")
    assert not accepts_temperature("claude-haiku-5-5")
    assert not accepts_temperature("claude-sonnet-5-5")



def _fake_anthropic(fail_on_temperature: bool):
    from types import SimpleNamespace
    seen = []

    def create(**kw):
        seen.append(kw)
        if fail_on_temperature and "temperature" in kw:
            raise RuntimeError("Error code: 400 - `temperature` is deprecated for this model.")
        return SimpleNamespace(content=[SimpleNamespace(type="text", text="{}")],
                               usage=SimpleNamespace(input_tokens=1, output_tokens=1), model=kw["model"])

    return SimpleNamespace(messages=SimpleNamespace(create=create)), seen


def test_client_sends_temperature_zero_to_sonnet_4_5_and_retries_without_on_400():
    from numis_geek.integrations.llm import AnthropicClient
    c = AnthropicClient.__new__(AnthropicClient)
    c._sdk, seen = _fake_anthropic(fail_on_temperature=False)
    c.call(system="s", user_text="u", model="claude-sonnet-4-5")
    assert seen[0]["temperature"] == 0

    c._sdk, seen = _fake_anthropic(fail_on_temperature=True)
    c.call(system="s", user_text="u", model="claude-sonnet-4-5")
    assert "temperature" in seen[0] and "temperature" not in seen[1]

    c._sdk, seen = _fake_anthropic(fail_on_temperature=False)
    c.call(system="s", user_text="u", model="claude-haiku-5-5-20260101")
    assert len(seen) == 1 and "temperature" not in seen[0]


def test_first_real_import_exact_school_bills_settle_and_junk_is_not_a_candidate(client, seed):
    """Itaú ago–out/26: duas escolas por DDA no mesmo dia com valor exato
    marcam pago sozinhas; PIX de R$ 500 não vira candidata de uma conta de
    R$ 628 (o ±30% linear antigo sugeria)."""
    acc = new_account(seed)
    _, lara = _rule_day(seed, "Escola Lara", "6210.90", 5, expected_account_id=acc)
    _, caio = _rule_day(seed, "Escola Caio", "5646.55", 5, expected_account_id=acc)
    _rule_day(seed, "Alimentação Escola", "628.13", 1, expected_account_id=acc)
    job = import_statement(client, seed, acc, statement([
        line(date(2026, 10, 5), "DDA PAG TIT", -6210.90, line_kind="BOLETO"),
        line(date(2026, 10, 5), "DDA PAG TIT", -5646.55, line_kind="BOLETO"),
        line(date(2026, 10, 2), "PIX TRANSF MARIA N02/10", -500, line_kind="PIX", counterparty="MARIA N"),
    ]))
    r_lara, r_caio, r_maria = preview(client, seed, job["id"])["rows"]
    assert r_lara["default_action"] == "settle" and r_lara["scheduled"]["occurrence_id"] == lara[date(2026, 10, 5)]
    assert r_caio["default_action"] == "settle" and r_caio["scheduled"]["occurrence_id"] == caio[date(2026, 10, 5)]
    assert not r_maria.get("scheduled")


def test_rule_payment_method_from_notion_blocks_wrong_kind(client, seed):
    """AXSECURITY (boleto, 248,89) não quita o Piscineiro (Pix, 250)."""
    acc = new_account(seed)
    _, pisc = _rule_day(seed, "Piscineiro", "250", 10, expected_account_id=acc,
                        notes="[notion:x] Meio de pagamento no Notion: PIX")
    job = import_statement(client, seed, acc, statement([
        line(date(2026, 10, 13), "PAG BOLETO AXSECURITY ALARME", -248.89, line_kind="BOLETO"),
        line(date(2026, 10, 13), "PIX TRANSF GEAN LI10/10", -250, line_kind="PIX", counterparty="GEAN LI"),
    ]))
    boleto, pix = preview(client, seed, job["id"])["rows"]
    assert not boleto.get("scheduled")
    assert pix["scheduled"]["occurrence_id"] == pisc[date(2026, 10, 10)]
    assert "meio de pagamento" in pix["scheduled"]["candidates"][0]["signals"]


# ── exemplos do Notion (category_example) no System 1 ───────────────────────

def _notion_example(seed, key, category_id, count, direction="out", lo=200, hi=500):
    from numis_geek.models.category_example import CategoryExample
    db = TestSession()
    db.add(CategoryExample(id=str(uuid.uuid4()), workspace_id=seed["ws"], alias_key=key, sample_description=key,
                           direction=direction, category_id=category_id, count=count, avg_amount=Decimal(lo + hi) / 2,
                           min_amount=Decimal(lo), max_amount=Decimal(hi), source="notion"))
    db.commit()
    db.close()


def _other_sub(seed, name):
    db = TestSession()
    root = db.query(Category).filter(Category.workspace_id == seed["ws"], Category.parent_id.is_(None)).first()
    c = Category(id=str(uuid.uuid4()), workspace_id=seed["ws"], name=name, parent_id=root.id, kind=CategoryKind.EXPENSE)
    db.add(c)
    cid = c.id
    db.commit()
    db.close()
    return cid


def test_notion_examples_reach_the_llm_and_dominant_category_shortcut(client, seed):
    acc = new_account(seed)
    other = _other_sub(seed, f"Faxina {uuid.uuid4().hex[:3]}")
    _notion_example(seed, "PIX TRANSF GEAN LI", seed["sub"], 18)
    _notion_example(seed, "PIX TRANSF GEAN LI", other, 2)
    _notion_example(seed, "PIX TRANSF GEAN LI", seed["sub"], 50, direction="in")   # other direction: ignored
    job, fake = import_with(client, seed, acc, statement([
        line(date(2026, 9, 10), "PIX TRANSF GEAN LI10/06", -420, line_kind="PIX"),
    ]), {"lines": [{"i": 0, "category_id": None, "confidence": 0.2, "reason": "genérico"}]})
    sent = json.loads(fake.s1_calls[0].split("\n\n", 1)[1])["LINHAS"][0]["historico_notion"]
    assert sent[0] == {"fonte": "Notion", "category": "Moradia › Aluguel", "count": 18,
                       "faixa": "200.00–500.00", "media": "350.00"}
    assert len(sent) == 2
    row = preview(client, seed, job["id"])["rows"][0]
    sug = row["category_suggestion"]
    assert row["category_id"] == seed["sub"] and sug["applied"] is True
    assert sug["reason"] == "igual a 18 lançamentos do Notion em Moradia › Aluguel"
    # examples are never transactions
    db = TestSession()
    assert txs_of(db, account_id=acc) == []
    db.close()


def test_no_shortcut_when_not_dominant(client, seed):
    acc = new_account(seed)
    other = _other_sub(seed, f"Feira {uuid.uuid4().hex[:3]}")
    _notion_example(seed, "PIX TRANSF ZEZE", seed["sub"], 6)
    _notion_example(seed, "PIX TRANSF ZEZE", other, 4)            # 60% < 80%
    job, _ = import_with(client, seed, acc, statement([line(date(2026, 9, 11), "PIX TRANSF ZEZE", -100)]))
    assert preview(client, seed, job["id"])["rows"][0]["category_id"] is None


def test_confirmed_numis_history_beats_notion(client, seed):
    acc = new_account(seed)
    newer = _other_sub(seed, f"Pet {uuid.uuid4().hex[:3]}")
    _notion_example(seed, "PIX TRANSF BIDU", seed["sub"], 20)
    db = TestSession()
    tx_svc.create_transaction(db, seed["ws"], tx_svc.TxInput(
        source_type=TransactionSourceType.CHECKING, checking_account_id=acc, event_date=date(2026, 8, 20),
        description="PIX TRANSF BIDU 20/08", amount=Decimal("-90"), category_id=newer,
    ))
    db.commit()
    db.close()
    job, fake = import_with(client, seed, acc, statement([line(date(2026, 9, 20), "PIX TRANSF BIDU 20/09", -95)]))
    row = preview(client, seed, job["id"])["rows"][0]
    assert row["category_id"] is None                             # no Notion shortcut against newer history
    linha = json.loads(fake.s1_calls[0].split("\n\n", 1)[1])["LINHAS"][0]
    assert linha["historico"] and linha["historico_notion"]          # both reach the LLM


def test_older_system1_version_is_reclassified_on_preview(client, seed):
    from numis_geek.services.bank_classifier import SYSTEM1_VERSION
    acc = new_account(seed)
    job, fake = import_with(client, seed, acc, statement([line(date(2026, 9, 12), "QUALQUER COISA", -10)]))
    db = TestSession()
    j = db.get(ExtractionJob, job["id"])
    j.classification_json = {"version": "system1-v1", "lines": {}, "errors": []}   # cached by the old code
    db.commit()
    db.close()
    fake.s1 = {"lines": [{"i": 0, "category_id": seed["sub"], "confidence": 0.9, "reason": "nova versão"}]}
    row = preview(client, seed, job["id"])["rows"][0]
    assert len(fake.s1_calls) == 2 and row["category_id"] == seed["sub"]
    db = TestSession()
    cj = db.get(ExtractionJob, job["id"]).classification_json
    assert cj["version"] == SYSTEM1_VERSION and cj["previous_version"] == "system1-v1"
    db.close()
    preview(client, seed, job["id"])
    assert len(fake.s1_calls) == 2                                 # current version: cached
    confirm(client, seed, job["id"])                               # apply never re-runs System 1
    assert len(fake.s1_calls) == 2


def test_alias_key_strips_glued_itau_dates():
    from numis_geek.services.bank_import import alias_key
    assert alias_key("PIX TRANSF GEAN LI10/06") == "PIX TRANSF GEAN LI"
    assert alias_key("PIX TRANSF MARIA N13/12") == "PIX TRANSF MARIA N"
    assert alias_key("PIX TRANSF MARIA N 13/12") == "PIX TRANSF MARIA N"
    assert alias_key("PARCELA 3/10") == "PARCELA"


def test_itau_invoice_without_close_date_and_payment_already_in_statement(client, seed):
    """The One out/26: o .xlsx só traz o vencimento (o modelo repete como
    fechamento) e o débito do pagamento já veio do extrato da conta. O import
    usa o close_day do cartão e vincula o débito existente — fatura PAID sem
    segundo débito."""
    acc = new_account(seed)
    card = new_card(seed)                       # close 5, due 15
    st = import_statement(client, seed, acc, statement([line(date(2026, 3, 15), "CARTAO ITAU THE ONE", -4321.87)]))
    confirm(client, seed, st["id"])
    job = import_invoice(client, seed, card, {
        "invoice": {"close_date": "2026-03-15", "due_date": "2026-03-15", "total": 4321.87},
        "transactions": [line(date(2026, 2, 20), "RESTAURANTE", -3321.87), line(date(2026, 3, 1), "MERCADO", -1000)],
    })
    p = preview(client, seed, job["id"])
    assert p["invoice"]["close_date"] == "2026-03-05"
    assert p["invoice"]["existing_payment"]["event_date"] == "2026-03-15"
    res = confirm(client, seed, job["id"])
    db = TestSession()
    inv = db.query(Invoice).filter(Invoice.credit_card_account_id == card).one()
    assert inv.status == InvoiceStatus.PAID
    debits = txs_of(db, account_id=acc)
    assert len(debits) == 1 and debits[0].paid_invoice_id == inv.id
    db.close()
    assert res["bank_import"]["paid_invoices"] >= 1 or res["bank_import"].get("paid_invoices") is not None


def test_iof_uses_party_user_chose_before_and_truncated_alias_matches(client, seed):
    """The One: user escolheu "Governo" pro "IOF COMPRA INTERNACIONA"; no
    Latam a descrição vem "IOF COMPRA INTERNACIONAL" — tem que vir Governo,
    não "nova: Receita Federal"."""
    card = new_card(seed)
    db = TestSession()
    gov = Party(id=str(uuid.uuid4()), workspace_id=seed["ws"], name="Governo", is_active=True)
    db.add(gov); db.flush()
    db.add(PartyAlias(id=str(uuid.uuid4()), workspace_id=seed["ws"], party_id=gov.id, alias_normalized="IOF COMPRA INTERNACIONA"))
    gid = gov.id
    db.commit(); db.close()
    job = import_invoice(client, seed, card, {
        "invoice": {"close_date": "2026-03-05", "due_date": "2026-03-15", "total": 3.98},
        "transactions": [line(date(2026, 3, 1), "IOF COMPRA INTERNACIONAL", -3.98, line_kind="IOF")],
    })
    row = preview(client, seed, job["id"])["rows"][0]
    assert row["party"]["mode"] == "existing" and row["party"]["party_id"] == gid


def test_bank_fee_choice_is_learned_per_institution(client, seed):
    acc = new_account(seed)
    mine = _party_with_alias(seed, "Itaú Unibanco (tarifas)", "ITAU TARIFAS ALIAS TESTE")
    job = import_statement(client, seed, acc, statement([line(BASE + timedelta(days=240), "TARIFA AVULSA XYZ", -9, line_kind="BANK_FEE")]))
    row = preview(client, seed, job["id"])["rows"][0]
    assert row["party"]["source"] == "bank_fee" and row["party"]["mode"] in ("new", "existing")   # institution = suggestion
    confirm(client, seed, job["id"], {"r0": {"action": "import", "party_id": mine}})
    job2 = import_statement(client, seed, acc, statement([line(BASE + timedelta(days=241), "CESTA SERVICOS QWERTY", -30)]))
    row = preview(client, seed, job2["id"])["rows"][0]
    assert row["party"]["mode"] == "existing" and row["party"]["party_id"] == mine


# ── A: parcelas futuras geradas pelo import da fatura ───────────────────────

def _inv_payload(close, lines_):
    due = (date.fromisoformat(close) + timedelta(days=10)).isoformat()
    return {"invoice": {"close_date": close, "due_date": due, "total": 1}, "transactions": lines_}


def _card_txs(card):
    db = TestSession()
    rows = [(t.installment_number, t.is_reconciled, t.extraction_job_id, t.notes, t.invoice_id, t.event_date,
             t.party_id, t.category_id, t.parent_transaction_id, t.id)
            for t in txs_of(db, card_id=card)]
    db.close()
    return rows


def test_import_generates_future_installments_and_real_invoice_confirms(client, seed):
    card = new_card(seed)
    original = date(2026, 1, 10)
    job = import_invoice(client, seed, card, _inv_payload("2026-03-05", [
        line(original, "SOFA ETNA", -400, installment="3/6")]))
    row = preview(client, seed, job["id"])["rows"][0]
    assert row["future_installments"] == {"from": 4, "to": 6, "existing": 0}
    confirm(client, seed, job["id"], {"r0": {"action": "import", "category_id": seed["sub"]}})
    rows = _card_txs(card)
    assert sorted(r[0] for r in rows) == [3, 4, 5, 6]                  # 1 and 2 never created
    by_k = {r[0]: r for r in rows}
    for k in (4, 5, 6):
        n, rec, jid, notes, inv_id, ev, party, cat, parent, _ = by_k[k]
        assert not rec and jid is None and notes.startswith("parcela prevista (gerada pelo import da fatura 03/2026)")
        assert ev == tx_svc.add_months(original, k - 1) and cat == seed["sub"] and party == by_k[3][6]
        assert parent == by_k[3][9]
    assert len({by_k[k][4] for k in (3, 4, 5, 6)}) == 4                # each in its own invoice
    db = TestSession()
    inv4 = db.get(Invoice, by_k[4][4])
    assert inv4.close_date == date(2026, 4, 5)
    db.close()
    # Movimentações shows "prevista"
    r = client.get(f"/api/transactions?card_id={card}", headers=auth(seed["token"])).json()["items"]
    assert {t["installment_number"]: t["is_projected"] for t in r} == {3: False, 4: True, 5: True, 6: True}

    # the invoice where 4/6 actually appears reconciles the projected one
    job2 = import_invoice(client, seed, card, _inv_payload("2026-04-05", [
        line(original, "SOFA ETNA", -400, installment="4/6")]))
    row = preview(client, seed, job2["id"])["rows"][0]
    assert row["bucket"] == "duplicate" and row["duplicate"]["transaction_id"] == by_k[4][9]
    assert row["default_action"] == "reconcile"
    assert row["future_installments"] == {"from": 5, "to": 6, "existing": 2}
    confirm(client, seed, job2["id"])
    rows = _card_txs(card)
    assert sorted(r[0] for r in rows) == [3, 4, 5, 6]                  # nothing duplicated
    four = next(r for r in rows if r[0] == 4)
    assert four[1] and four[2] == job2["id"] and four[3] is None        # confirmed, marker gone


def test_out_of_order_invoices_never_duplicate_installments(client, seed):
    card = new_card(seed)
    original = date(2026, 1, 15)
    j5 = import_invoice(client, seed, card, _inv_payload("2026-06-05", [
        line(original, "NOTEBOOK ACER", -250, installment="5/12")]))
    confirm(client, seed, j5["id"])
    assert sorted(r[0] for r in _card_txs(card)) == list(range(5, 13))  # 5 + 6..12 projected
    j3 = import_invoice(client, seed, card, _inv_payload("2026-04-05", [
        line(original, "NOTEBOOK ACER", -250, installment="3/12")]))
    row = preview(client, seed, j3["id"])["rows"][0]
    assert row["bucket"] == "new"
    assert row["future_installments"] == {"from": 4, "to": 12, "existing": 8}
    confirm(client, seed, j3["id"])
    ks = sorted(r[0] for r in _card_txs(card))
    assert ks == list(range(3, 13))                                     # 3 new, 4 generated, 5..12 untouched
    four = next(r for r in _card_txs(card) if r[0] == 4)
    db = TestSession()
    assert db.get(Invoice, four[4]).close_date == date(2026, 5, 5)
    db.close()


# ── C: valor/moeda originais da linha convertida ────────────────────────────

def test_edited_converted_tx_still_dedups_on_reimport(client, seed):
    acc = new_account(seed)
    d = BASE + timedelta(days=113)
    lines_ = [{**line(d, "CARD-77 GITHUB", -10), "currency": "USD"}]
    confirm(client, seed, import_statement(client, seed, acc, statement(lines_))["id"])
    db = TestSession()
    tx = txs_of(db, account_id=acc)[0]
    assert tx.original_amount == Decimal("-10.00") and tx.original_currency == Currency.USD
    tx_id = tx.id
    db.close()
    r = client.patch(f"/api/transactions/{tx_id}", json={"amount": -51.37, "notes": "ajustei o valor"},
                     headers=auth(seed["token"]))
    assert r.status_code == 200, r.text
    assert r.json()[0]["original_amount"] == -10.0 and r.json()[0]["original_currency"] == "USD"
    row = preview(client, seed, import_statement(client, seed, acc, statement(lines_))["id"])["rows"][0]
    assert row["bucket"] == "duplicate" and row["duplicate"]["reason"] == "fingerprint"
    assert row["duplicate"]["transaction_id"] == tx_id


def test_compute_fingerprint_prefers_original_kwargs():
    a = tx_svc.compute_fingerprint(TransactionSourceType.CHECKING, "acc", BASE, Decimal("-50"), Currency.BRL, "X",
                                   original_amount=Decimal("-10"), original_currency=Currency.USD)
    b = tx_svc.compute_fingerprint(TransactionSourceType.CHECKING, "acc", BASE, Decimal("-10"), Currency.USD, "X")
    c = tx_svc.compute_fingerprint(TransactionSourceType.CHECKING, "acc", BASE, Decimal("-50"), Currency.BRL, "X")
    assert a == b != c


# ── E: descrição genérica nunca cria fornecedor ─────────────────────────────

def test_generic_bank_descriptions_suggest_no_party(client, seed):
    from numis_geek.services.bank_import import _merchant_of
    for generic in ("DDA PAG TIT", "REND PAGO APLIC AUT MAIS", "INT PAG TIT BANCO 237", "TED D INT 341 0001",
                    "SALDO DO DIA", "PIX TRANSF 18/09", "RESGATE CDB 12345"):
        assert _merchant_of(generic) is None, generic
    assert _merchant_of("PAG BOLETO AXSECURITY ALARMES") == "AXSECURITY ALARMES"
    assert _merchant_of("UBER *TRIP 1234") == "UBER *TRIP 1234"
    acc = new_account(seed)
    job = import_statement(client, seed, acc, statement([
        line(date(2026, 10, 20), "DDA PAG TIT", -321.12),
        line(date(2026, 10, 20), "REND PAGO APLIC AUT MAIS", 1.23),
        line(date(2026, 10, 21), "PAG BOLETO AXSECURITY ALARMES", -89.9),
    ]))
    r0, r1, r2 = preview(client, seed, job["id"])["rows"]
    assert r0["party"]["mode"] == "none" and r0["party"]["source"] == "generic"
    assert r1["party"]["mode"] == "none"
    assert r2["party"]["mode"] == "new" and r2["party"]["new_party_name"] == "AXSECURITY ALARMES"
    confirm(client, seed, job["id"])
    db = TestSession()
    t0, t1, t2 = txs_of(db, account_id=acc)
    assert t0.party_id is None and t1.party_id is None and db.get(Party, t2.party_id).name == "AXSECURITY ALARMES"
    assert db.query(PartyAlias).filter(PartyAlias.alias_normalized == "DDA PAG TIT").count() == 0
    db.close()



# ══ spec 84 — Wise (conta multimoeda, uma conta só em reais) ═══════════════

WISE_PAGES = [
    "Transactions\r\n"
    "19 October\r\n"
    "Refund Globalblue.com + 6.12 BRL\r\n"
    "Hotel Aqua\r\n2 EUR\r\n2.25 USD\r\n"
    "Search Filters (2) Export\r\nHome Cards Recipients Payments\r\nEarn R$250 when you invite\r\n"
    "11/2/26, 12:02 PM Wise - Home\r\n"
    "https://wise.com/all-transactions?from=2023-01-01&to=2026-11-02 1/2\r\n",
    "Bar Alfa\r\n91.25 EUR\r\n103.02 USD\r\n"          # page break: still 19 October
    "14 October\r\n"
    "To EUR\r\nMoved\r\n178.69 EUR\r\n200 USD\r\n"
    "Torrons Beta 25 EUR\r\n"
    "Ristorante Gama\r\n98.06 EUR\r\nEUR, USD\r\n"
    "TFL - Transport\r\nCard checked\r\n0 GBP\r\n"
    "2 October\r\n"
    "Assets fee 0.37 USD\r\n"
    "Cashback + 2.50 BRL\r\n"
    "PESSOA TESTE SOBRENOME+ 3,000 BRL\r\n"
    "To USD Jar 1,000 USD Home Cards Recipients Payments\r\n"
    "19 October 2025\r\n"
    "To USD\r\nMoved\r\n4.54 USD\r\n4,365 CLP\r\n"
    "Parrilla Delta 12,000 CLP\r\n"
    "Casa Epsilon\r\n236,100 ARS\r\n160.70 USD\r\n"
    "1 July 2024\r\n"
    "Fulano Recebedor\r\nSent\r\n660,000 CLP\r\n3,994.19 BRL\r\n"
    "Mercado Zeta 152.84 UYU\r\n"
    "11/2/26, 12:02 PM Wise - Home\r\n",
]


def test_wise_parser_kinds_jars_and_years():
    from numis_geek.services.extraction_parsers.wise_statement import parse_text
    out = parse_text(WISE_PAGES)
    tx = out["transactions"]
    by = {t["description"]: t for t in tx}
    assert len(tx) == 15 and "TFL - Transport" not in by           # card check (0) dropped
    assert any("sem movimento" in w for w in out["parse_warnings"])
    assert by["Refund Globalblue.com"]["line_kind"] == "REFUND" and by["Refund Globalblue.com"]["jar_amount"] == 6.12
    assert by["Hotel Aqua"]["event_date"] == "2026-10-19"
    bar = by["Bar Alfa"]                                              # header from previous page
    assert (bar["event_date"], bar["jar_amount"], bar["jar_currency"], bar["merchant_amount"], bar["merchant_currency"]) \
        == ("2026-10-19", -103.02, "USD", -91.25, "EUR")
    conv = [t for t in tx if t["line_kind"] == "CONVERSION"]
    assert len(conv) == 3
    assert (conv[0]["jar_amount"], conv[0]["jar_currency"], conv[0]["merchant_amount"]) == (-200.0, "USD", 178.69)
    assert by["Torrons Beta"]["jar_amount"] == -25.0 and by["Torrons Beta"]["merchant_currency"] is None
    assert by["Ristorante Gama"]["multi_jar"] == "EUR, USD"
    assert by["Assets fee"]["line_kind"] == "FEE" and by["Cashback"]["line_kind"] == "CASHBACK"
    dep = by["PESSOA TESTE SOBRENOME"]
    assert dep["line_kind"] == "DEPOSIT" and dep["jar_amount"] == 3000.0 and dep["counterparty"] == "PESSOA TESTE SOBRENOME"
    assert by["Parrilla Delta"]["event_date"] == "2025-10-19" and by["Parrilla Delta"]["jar_amount"] == -12000.0
    assert by["Casa Epsilon"]["merchant_amount"] == -236100.0
    sent = by["Fulano Recebedor"]
    assert (sent["line_kind"], sent["event_date"], sent["jar_amount"], sent["jar_currency"]) == ("SENT", "2024-07-01", -3994.19, "BRL")
    assert out["period"] == {"start": "2024-07-01", "end": "2026-10-19"}
    dates = [t["event_date"] for t in tx]
    assert dates == sorted(dates, reverse=True)                       # newest → oldest, years in order


def _wise_account(seed) -> str:
    db = TestSession()
    now = datetime.now(timezone.utc)
    fi = db.query(FinancialInstitution).filter(FinancialInstitution.short_name == "Wise").first()
    if fi is None:
        fi = FinancialInstitution(id=str(uuid.uuid4()), long_name="Wise Payments", short_name="Wise",
                                  logo_slug="wise", is_active=True, created_at=now, updated_at=now)
        db.add(fi)
        db.flush()
    a = Account(id=str(uuid.uuid4()), workspace_id=seed["ws"], financial_institution_id=fi.id,
                name=f"Conta Corrente Wise {uuid.uuid4().hex[:4]}", account_type=AccountType.checking,
                currency=Currency.BRL, is_active=True)
    db.add(a)
    aid = a.id
    db.commit()
    db.close()
    return aid


@pytest.fixture
def bcb_rates(monkeypatch):
    """EUR/GBP no BCB a 6,00/7,00; demais moedas sem cotação."""
    from numis_geek.integrations import bcb
    calls = []

    def fake(cur, start, end):
        calls.append(cur)
        rate = {"EUR": Decimal("6.00"), "GBP": Decimal("7.00")}.get(cur)
        if rate is None:
            return []
        out, d = [], start
        while d <= end:
            out.append(bcb.PTAXRow(date=d, rate=rate))
            d += timedelta(days=1)
        return out
    monkeypatch.setattr(bcb, "fetch_currency_ptax_range", fake)
    return calls


def _wise_import(client, seed, acc, pages=None):
    from numis_geek.services.extraction_parsers.wise_statement import parse_text
    payload = parse_text(pages or WISE_PAGES)
    return import_statement(client, seed, acc, payload)


def test_wise_classify_buckets_rates_and_notes(client, seed, bcb_rates):
    db = TestSession()   # PTAX table starts in 2025 here; one old rate → nearest-earlier fallback for 2024 lines
    if not db.query(PTAXRate).filter(PTAXRate.date == date(2024, 6, 28)).first():
        db.add(PTAXRate(id=str(uuid.uuid4()), date=date(2024, 6, 28), rate=PTAX, fetched_at=datetime.now(timezone.utc)))
        db.commit()
    db.close()
    acc = _wise_account(seed)
    job = _wise_import(client, seed, acc)
    p = preview(client, seed, job["id"])
    by = {r["description"]: r for r in p["rows"]}
    # conversions between jars never become transactions
    internal = [r for r in p["rows"] if r["bucket"] == "internal"]
    assert len(internal) == 3 and all(r["actions"] == ["skip"] for r in internal)
    # USD jar → PTAX (5.0); EUR merchant in the note
    bar = by["Bar Alfa"]
    assert bar["amount"] == "-515.10" and bar["original"]["currency"] == "USD"
    assert bar["original"]["merchant"] == {"amount": "-91.25", "currency": "EUR"}
    # EUR jar → BCB EUR (6,00)
    tor = by["Torrons Beta"]
    assert tor["amount"] == "-150.00" and tor["original"]["rate_source"] == "BCB"
    # CLP jar: no BCB → crossed via the document's CLP/USD (4.54/4365) × PTAX 5
    par = by["Parrilla Delta"]
    assert par["original"]["rate_source"] == "CROSS"
    assert par["amount"] == str((Decimal("-12000") * (Decimal("4.54") / Decimal("4365")) * 5).quantize(Decimal("0.01")))
    # UYU with no rate anywhere → stays importable, unconverted, warned
    uyu = by["Mercado Zeta"]
    assert uyu["bucket"] == "new" and uyu["original"]["rate_source"] == "NONE" and "Sem cotação" in uyu["warning"]
    # multi-jar warning, BRL "Sent" with CLP note, refund party, cashback no party, fee
    assert "mais de um saldo" in by["Ristorante Gama"]["warning"]
    sent = by["Fulano Recebedor"]
    assert sent["amount"] == "-3994.19" and sent["original"] is None and sent["note"] == "660.000 CLP (destino)"
    assert sent["party"]["new_party_name"] == "Fulano Recebedor"
    assert by["Refund Globalblue.com"]["party"]["new_party_name"] == "Globalblue.com"
    assert by["Cashback"]["party"]["mode"] == "none"
    assert by["Assets fee"]["line_kind"] == "BANK_FEE"
    # BCB fetched once per currency, cached on the job
    db = TestSession()
    cache = db.get(ExtractionJob, job["id"]).extracted_json["_fx_rates"]
    db.close()
    assert set(cache) >= {"EUR", "CLP", "UYU"} and cache["EUR"]["rates"]

    n_calls = len(bcb_rates)
    preview(client, seed, job["id"])
    assert len(bcb_rates) == n_calls                                   # cached
    confirm(client, seed, job["id"])
    assert len(bcb_rates) == n_calls                                   # apply never fetches
    db = TestSession()
    txs = {t.description: t for t in txs_of(db, account_id=acc)}
    assert "To EUR" not in txs and "To USD" not in txs and len(txs) == 12
    t = txs["Torrons Beta"]
    assert t.amount == Decimal("-150.00") and t.original_amount == Decimal("-25.00") and t.original_currency == "EUR"
    assert t.notes == "25 EUR × BCB 6,0000 (14/10)"
    assert txs["Bar Alfa"].notes == "91,25 EUR (comerciante) · US$ 103,02 × PTAX 5,0000 (19/10)"
    assert txs["Fulano Recebedor"].notes == "660.000 CLP (destino)" and txs["Fulano Recebedor"].original_amount is None
    expected = tx_svc.compute_fingerprint(TransactionSourceType.CHECKING, acc, date(2026, 10, 14), Decimal("-150"),
                                          Currency.BRL, "Torrons Beta", original_amount=Decimal("-25"),
                                          original_currency="EUR")
    assert t.fingerprint == expected
    db.close()
    # re-import of the same lines: everything is a duplicate (or internal)
    p2 = preview(client, seed, _wise_import(client, seed, acc)["id"])
    assert {r["bucket"] for r in p2["rows"]} == {"duplicate", "internal"}


def test_wise_own_pix_is_transfer(client, seed, bcb_rates):
    from numis_geek.models.user import User
    db = TestSession()
    u = db.query(User).filter(User.email == "bi_admin@test.com").one()
    u.name = "Pessoa Teste Sobrenome"
    root = db.query(Category).filter(Category.workspace_id == seed["ws"], Category.parent_id.is_(None)).first()
    tr = Category(id=str(uuid.uuid4()), workspace_id=seed["ws"], name="Entre contas", parent_id=root.id,
                  kind=CategoryKind.TRANSFER)
    db.add(tr)
    tr_id = tr.id
    db.commit()
    db.close()
    acc = _wise_account(seed)
    row = next(r for r in preview(client, seed, _wise_import(client, seed, acc)["id"])["rows"]
               if r["description"] == "PESSOA TESTE SOBRENOME")
    assert row["party"]["mode"] == "none" and row["party"]["source"] == "own_transfer"
    assert row["category_id"] == tr_id


def test_wise_pdf_goes_through_deterministic_parser(client, seed, monkeypatch, bcb_rates):
    from numis_geek.services.extraction_parsers import wise_statement
    monkeypatch.setattr(wise_statement, "pdf_pages_text", lambda blob: WISE_PAGES)
    acc = _wise_account(seed)
    fake = FakeLLM({"lines": []})
    set_llm_client(fake)
    r = client.post(f"/api/accounts/{acc}/statement-imports",
                    files={"file": ("wise.pdf", b"%PDF-1.4 " + uuid.uuid4().hex.encode(), "application/pdf")},
                    headers=auth(seed["token"]))
    assert r.status_code == 201 and r.json()["status"] == "EXTRACTED", r.text
    db = TestSession()
    j = db.get(ExtractionJob, r.json()["id"])
    assert j.prompt_version == "deterministic:parse_wise_statement_pdf"
    assert len(j.extracted_json["transactions"]) == 15
    assert (j.statement_period_start, j.statement_period_end) == (date(2024, 7, 1), date(2026, 10, 19))
    db.close()
    # non-text PDF falls back to the LLM
    def no_text(blob):
        raise wise_statement.NotApplicable("sem texto")
    monkeypatch.setattr(wise_statement, "parse_wise_statement_pdf", no_text)
    from numis_geek.services import extraction_parsers
    monkeypatch.setitem(extraction_parsers._BY_KEY,
                        ("wise", ExtractionSourceHint.BANK_STATEMENT, "application/pdf"), no_text)
    set_llm_client(FakeLLM(statement([line(date(2026, 10, 1), "LOJA", -1)])))
    r = client.post(f"/api/accounts/{acc}/statement-imports",
                    files={"file": ("w2.pdf", b"%PDF-1.4 " + uuid.uuid4().hex.encode(), "application/pdf")},
                    headers=auth(seed["token"]))
    assert r.status_code == 201 and r.json()["status"] == "EXTRACTED"
    db = TestSession()
    assert db.get(ExtractionJob, r.json()["id"]).prompt_version == "bank-statement-wise-v1"
    db.close()


def test_non_wise_usd_line_keeps_ptax_path(client, seed):
    acc = new_account(seed)
    d = BASE + timedelta(days=114)
    row = preview(client, seed, import_statement(client, seed, acc, statement([
        {**line(d, "AWS", -10), "currency": "USD"}]))["id"])["rows"][0]
    assert row["original"]["rate_source"] == "PTAX" and row["amount"] == "-50.00"


def test_olinda_client_parses_and_unknown_currency(monkeypatch):
    from numis_geek.integrations import bcb

    class Resp:
        def __init__(self, status, body):
            self.status_code, self._b = status, body

        def raise_for_status(self):
            pass

        def json(self):
            return self._b

    class Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, params=None, timeout=None):
            if params["@moeda"] == "'CLP'":
                return Resp(400, {})
            return Resp(200, {"value": [
                {"cotacaoVenda": 6.1234, "dataHoraCotacao": "2026-10-14 13:05:00.000", "tipoBoletim": "Abertura"},
                {"cotacaoVenda": 6.2, "dataHoraCotacao": "2026-10-14 13:10:00.000", "tipoBoletim": "Fechamento"},
            ]})
    monkeypatch.setattr(bcb.httpx, "Client", Client)
    rows = bcb.fetch_currency_ptax_range("eur", date(2026, 10, 1), date(2026, 10, 15))
    assert rows == [bcb.PTAXRow(date=date(2026, 10, 14), rate=Decimal("6.2"))]
    assert bcb.fetch_currency_ptax_range("CLP", date(2026, 10, 1), date(2026, 10, 15)) == []


def test_convert_jar_prefers_closest_document_rate(db):
    from numis_geek.services import multicurrency as mc
    db.add(PTAXRate(id=str(uuid.uuid4()), date=date(2025, 7, 10), rate=Decimal("5.5"),
                    fetched_at=datetime.now(timezone.utc)))
    db.flush()
    payload = {"transactions": [
        {"event_date": "2025-07-10", "jar_amount": -1000, "jar_currency": "BRL", "merchant_amount": 7085.86,
         "merchant_currency": "UYU", "line_kind": "CONVERSION"},
        {"event_date": "2025-10-19", "jar_amount": -152.84, "jar_currency": "UYU", "merchant_amount": 3.80,
         "merchant_currency": "USD", "line_kind": "CONVERSION"},
    ]}
    implied = mc.implied_usd_rates(payload)
    implied.update({("BRL", c): v for c, v in mc.implied_brl_rates(payload).items()})
    out = mc.convert_jar(db, date(2025, 7, 12), Decimal("-708.59"), "UYU", "BRL", {}, implied)
    assert out["rate_source"] == "CROSS" and out["cross"]["implied_date"] == "2025-07-10"
    assert out["converted"] == Decimal("-100.00")                 # BRL leg, 2 days away, beats USD leg (3 months)
    assert mc.convert_jar(db, date(2025, 7, 12), Decimal("-1"), "ARS", "BRL", {}, implied)["rate_source"] == "NONE"


def test_wise_page_break_conversion_and_footer_inside_line():
    """PDF real: "To EUR 916.79 EUR" no fim da página e "Moved 6,000 BRL" no
    topo da seguinte virava gasto de −6.000; o rodapé da página caía no meio
    da linha ("Holiday Inn Home Cards Recipients Payments 94,380 CLP")."""
    from numis_geek.services.extraction_parsers.wise_statement import parse_text
    footer = "Home Cards Recipients Payments\n11/2/26, 12:02 PM Wise - Home\nhttps://wise.com/all-transactions?from=2023-01-01&to=2026-11-02 21/35"
    pages = [
        "Transactions\n12 September 2025\nTo EUR 916.79 EUR Home Cards Recipients Payments\n" + footer,
        "Moved 6,000 BRL\nDANIEL RODRIGUES AMBROSIO + 6,000 BRL\n7 July 2024\n"
        "Holiday Inn Home Cards Recipients Payments 94,380 CLP\n" + footer,
    ]
    tx = parse_text(pages)["transactions"]
    descs = [t["description"] for t in tx]
    assert "Moved" not in descs and all("Home Cards" not in d for d in descs)
    conv = next(t for t in tx if t["description"] == "To EUR")
    assert conv["line_kind"] == "CONVERSION" and conv["jar_currency"] == "BRL" and conv["jar_amount"] == -6000.0
    hotel = next(t for t in tx if t["description"] == "Holiday Inn")
    assert hotel["jar_amount"] == -94380.0 and hotel["jar_currency"] == "CLP"


def test_own_name_falls_back_to_email_when_profile_has_no_name(seed):
    """Prod: user sem nome no perfil — o Pix "DANIEL RODRIGUES AMBROSIO" pra
    Wise vinha como 'nova: DANIEL…' em vez de transferência própria."""
    from numis_geek.models.user import User
    from numis_geek.services.bank_import import _is_own_name, _own_names
    db = TestSession()
    u = db.query(User).filter(User.email == "bi_admin@test.com").one()
    old_name, old_email = u.name, u.email
    u.name, u.email = None, "daniel.ambrosio@example.com"
    db.flush()
    own = _own_names(db, seed["ws"])
    assert _is_own_name("DANIEL RODRIGUES AMBROSIO", own)
    assert not _is_own_name("MARIA N", own)
    db.rollback()
    db.close()
