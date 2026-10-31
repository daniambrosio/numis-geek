"""Spec 72 — Contas a Pagar e a Receber.

Covers: slot generation per frequency (monthly / yearly / installment
"parcela k/N"), 90-day materialization, idempotency (service, workspace and
the daily APScheduler job), the watermark (a postponed occurrence never
comes back), rule edit touching only FUTURE PENDING, pause, rule delete,
overdue derived status, positive-amount convention, every manual action
(pay with/without tx, postpone, cancel, delete one-off), tx delete reverting
the payment, forecast, workspace isolation and permissions.
"""
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

import bcrypt
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
from numis_geek.models.audit_log import AuditLog
from numis_geek.models.category import Category, CategoryKind
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.party import Party
from numis_geek.models.ptax_rate import PTAXRate
from numis_geek.models.scheduled_transaction import (
    RecurrenceFrequency, RecurrenceRule, ScheduledDirection, ScheduledStatus,
    ScheduledTransaction,
)
from numis_geek.models.user import User, UserRole
from numis_geek.services import scheduled_transactions as svc
from numis_geek.services.auth import AuthService
from numis_geek.services.user import UserService
from numis_geek.services.workspace import WorkspaceService

TEST_ENGINE = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(bind=TEST_ENGINE, autoflush=False, autocommit=False)

TODAY = date.today()
PTAX = Decimal("5.00000000")


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


def _account(db, ws_id, fi_id, name, currency=Currency.BRL, account_type=AccountType.checking):
    a = Account(
        id=str(uuid.uuid4()), workspace_id=ws_id, financial_institution_id=fi_id,
        name=name, account_type=account_type, currency=currency, is_active=True,
    )
    db.add(a)
    return a


@pytest.fixture(scope="module")
def seed():
    db = TestSession()
    ws = WorkspaceService(db).create("AP WS")
    ws2 = WorkspaceService(db).create("AP WS 2")
    UserService(db).create(ws.id, "ap_admin@test.com", "adminpass", UserRole.admin)
    UserService(db).create(ws.id, "ap_member@test.com", "memberpass", UserRole.member)
    UserService(db).create(ws2.id, "ap_admin2@test.com", "adminpass", UserRole.admin)
    now = datetime.now(timezone.utc)
    db.add(User(
        id=str(uuid.uuid4()), workspace_id=None, email="ap_sys@test.internal", name="Sys",
        password_hash=bcrypt.hashpw(b"syspass", bcrypt.gensalt()).decode(),
        role=UserRole.sysadmin, is_active=True, created_at=now, updated_at=now,
    ))
    fi = FinancialInstitution(
        id=str(uuid.uuid4()), long_name="Banco AP", short_name="BAP", logo_slug="bap",
        is_active=True, created_at=now, updated_at=now,
    )
    db.add(fi)
    db.flush()
    start = TODAY - timedelta(days=200)
    for i in range(400):
        db.add(PTAXRate(id=str(uuid.uuid4()), date=start + timedelta(days=i), rate=PTAX, fetched_at=now))
    itau = _account(db, ws.id, fi.id, "Conta Corrente Itaú")
    nomad = _account(db, ws.id, fi.id, "Conta Corrente Nomad", currency=Currency.USD)
    invest = _account(db, ws.id, fi.id, "Conta Investimento", account_type=AccountType.investment)
    root = Category(id=str(uuid.uuid4()), workspace_id=ws.id, name="Moradia", color="#ff0000")
    db.add(root)
    db.flush()
    sub = Category(id=str(uuid.uuid4()), workspace_id=ws.id, name="Aluguel", parent_id=root.id, kind=CategoryKind.EXPENSE)
    party = Party(id=str(uuid.uuid4()), workspace_id=ws.id, name="Imobiliária X")
    party2 = Party(id=str(uuid.uuid4()), workspace_id=ws.id, name="Imob X (dup)")
    db.add_all([sub, party, party2])
    db.commit()
    ids = {
        "ws_id": ws.id, "ws2_id": ws2.id, "fi_id": fi.id, "itau": itau.id, "nomad": nomad.id,
        "invest": invest.id, "root": root.id, "sub": sub.id, "party": party.id, "party2": party2.id,
    }
    ids["admin_token"] = AuthService(db).login("ap_admin@test.com", "adminpass")
    ids["member_token"] = AuthService(db).login("ap_member@test.com", "memberpass")
    ids["admin2_token"] = AuthService(db).login("ap_admin2@test.com", "adminpass")
    ids["sys_token"] = AuthService(db).login("ap_sys@test.internal", "syspass")
    db.close()
    return ids


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def _rule(**kw) -> RecurrenceRule:
    base = dict(
        id=str(uuid.uuid4()), workspace_id="ws", direction=ScheduledDirection.PAYABLE,
        description="Aluguel", amount=Decimal("2500"), currency=Currency.BRL,
        frequency=RecurrenceFrequency.MONTHLY, day_of_month=5, start_date=date(2026, 1, 1),
        is_active=True,
    )
    base.update(kw)
    return RecurrenceRule(**base)


def _new_rule(db, ws_id, today, **kw):
    data = dict(
        direction=ScheduledDirection.PAYABLE, description="Aluguel", amount=Decimal("2500"),
        frequency=RecurrenceFrequency.MONTHLY, day_of_month=5, start_date=today,
    )
    data.update(kw)
    return svc.create_rule(db, ws_id, svc.RuleInput(**data), today=today)


def _occs(db, rule_id):
    return db.query(ScheduledTransaction).filter(
        ScheduledTransaction.recurrence_rule_id == rule_id,
    ).order_by(ScheduledTransaction.due_date).all()


def _tx(client, seed, amount, *, days_ago=1, desc="Pagamento aluguel"):
    r = client.post("/api/transactions", json={
        "source_type": "CHECKING", "checking_account_id": seed["itau"],
        "event_date": (TODAY - timedelta(days=days_ago)).isoformat(),
        "description": desc, "amount": str(amount),
    }, headers=auth(seed["admin_token"]))
    assert r.status_code == 201, r.text
    return r.json()[0]


def _one_off(client, seed, token=None, **body):
    payload = {"direction": "PAYABLE", "description": "IPVA", "amount": "1200.00",
               "due_date": (TODAY + timedelta(days=10)).isoformat()}
    payload.update(body)
    return client.post("/api/scheduled-transactions", json=payload, headers=auth(token or seed["admin_token"]))


# ── slot generation (pure) ────────────────────────────────────────────────────

def test_monthly_slots_from_start_date_until_horizon():
    rule = _rule(start_date=date(2026, 1, 10), day_of_month=5)
    slots = svc.rule_slots(rule, date(2026, 5, 4))
    # dia 5 de jan já passou do início → 1º vencimento é 05/02
    assert [d for d, _ in slots] == [date(2026, 2, 5), date(2026, 3, 5), date(2026, 4, 5)]
    assert all(k is None for _, k in slots)


def test_monthly_respects_end_date():
    rule = _rule(start_date=date(2026, 1, 1), end_date=date(2026, 3, 4))
    assert [d for d, _ in svc.rule_slots(rule, date(2026, 12, 31))] == [date(2026, 1, 5), date(2026, 2, 5)]


def test_yearly_slots():
    rule = _rule(frequency=RecurrenceFrequency.YEARLY, month=3, day_of_month=15, start_date=date(2026, 4, 1))
    assert [d for d, _ in svc.rule_slots(rule, date(2028, 12, 31))] == [date(2027, 3, 15), date(2028, 3, 15)]


def test_installment_slots_numbered_and_bounded():
    rule = _rule(frequency=RecurrenceFrequency.INSTALLMENT, installment_total=180, installment_paid=36,
                 start_date=date(2026, 11, 1), day_of_month=10)
    slots = svc.rule_slots(rule, date(2027, 1, 31))
    assert slots == [(date(2026, 11, 10), 37), (date(2026, 12, 10), 38), (date(2027, 1, 10), 39)]
    short = _rule(frequency=RecurrenceFrequency.INSTALLMENT, installment_total=2, installment_paid=0,
                  start_date=date(2026, 1, 1), day_of_month=10)
    assert [k for _, k in svc.rule_slots(short, date(2030, 1, 1))] == [1, 2]


# ── materialization ───────────────────────────────────────────────────────────

def test_materializes_90_days_ahead_pending_and_positive(seed):
    db = TestSession()
    today = date(2026, 10, 31)
    rule, created = _new_rule(db, seed["ws_id"], today, description="Mat 90d", day_of_month=5)
    # 05/11, 05/12, 05/01 ≤ 29/01/2027 (= hoje + 90)
    assert [o.due_date for o in created] == [date(2026, 11, 5), date(2026, 12, 5), date(2027, 1, 5)]
    assert svc.horizon(today) == date(2027, 1, 29)
    assert all(o.status == ScheduledStatus.PENDING and o.amount > 0 for o in created)
    assert all(o.description == "Mat 90d" and o.direction == ScheduledDirection.PAYABLE for o in created)
    assert rule.materialized_through == date(2027, 1, 29)
    db.rollback(); db.close()


def test_materialization_is_idempotent(seed):
    db = TestSession()
    today = date(2026, 10, 31)
    rule, created = _new_rule(db, seed["ws_id"], today, description="Idem")
    assert len(created) == 3
    assert svc.materialize_rule(db, rule, today=today) == []
    rule.materialized_through = None  # even without the watermark the UNIQUE slot holds
    assert svc.materialize_rule(db, rule, today=today) == []
    assert len(_occs(db, rule.id)) == 3
    # next month the window moves forward: exactly one new slot
    later = svc.materialize_rule(db, rule, today=date(2026, 11, 30))
    assert [o.due_date for o in later] == [date(2027, 2, 5)]
    db.rollback(); db.close()


def test_unique_rule_due_date_constraint(seed):
    db = TestSession()
    rule, created = _new_rule(db, seed["ws_id"], date(2026, 10, 31), description="Unique")
    dup = ScheduledTransaction(
        workspace_id=seed["ws_id"], direction=ScheduledDirection.PAYABLE, recurrence_rule_id=rule.id,
        description="dup", amount=Decimal("1"), currency=Currency.BRL, due_date=created[0].due_date,
    )
    db.add(dup)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback(); db.close()


def test_postponed_occurrence_is_not_recreated(seed):
    db = TestSession()
    today = date(2026, 10, 31)
    rule, created = _new_rule(db, seed["ws_id"], today, description="Adiado")
    svc.postpone(db, created[0], date(2026, 11, 20))
    assert svc.materialize_rule(db, rule, today=date(2026, 11, 1)) == []
    assert [o.due_date for o in _occs(db, rule.id)] == [date(2026, 11, 20), date(2026, 12, 5), date(2027, 1, 5)]
    db.rollback(); db.close()


def test_installment_materialization_labels(seed):
    db = TestSession()
    rule, created = _new_rule(
        db, seed["ws_id"], date(2026, 10, 31), description="Financiamento",
        frequency=RecurrenceFrequency.INSTALLMENT, installment_total=180, installment_paid=36, day_of_month=10,
    )
    assert [(o.installment_number, o.installment_total) for o in created] == [(37, 180), (38, 180), (39, 180)]
    db.rollback(); db.close()


def test_daily_job_is_idempotent_and_audited(seed):
    from numis_geek import scheduler
    db = TestSession()
    rule, _ = _new_rule(db, seed["ws_id"], TODAY, description="Job rule")
    # simulate a rule whose window was never pushed (created before the job ran)
    for o in _occs(db, rule.id):
        db.delete(o)
    rule.materialized_through = None
    db.commit()
    rule_id = rule.id
    db.close()

    with patch("numis_geek.scheduler.SessionLocal", lambda: TestSession()):
        scheduler.run_daily_scheduled_materialization()
        db = TestSession()
        n1 = len(_occs(db, rule_id))
        db.close()
        scheduler.run_daily_scheduled_materialization()

    db = TestSession()
    assert n1 >= 2
    assert len(_occs(db, rule_id)) == n1
    audits = db.query(AuditLog).filter(
        AuditLog.action == "scheduled_transaction.materialized", AuditLog.resource_id == rule_id,
    ).all()
    assert len(audits) == 1 and audits[0].user_email == "system@cron"
    db.query(ScheduledTransaction).filter(ScheduledTransaction.recurrence_rule_id == rule_id).delete()
    db.query(RecurrenceRule).filter(RecurrenceRule.id == rule_id).delete()
    db.commit(); db.close()


def test_scheduler_registers_materialization_job(monkeypatch):
    from numis_geek import scheduler

    class FakeApp:
        class state:
            pass

    monkeypatch.setenv("DISABLE_SCHEDULER", "false")
    with patch.object(scheduler.BackgroundScheduler, "start"), \
         patch.object(scheduler.BackgroundScheduler, "get_job") as get_job:
        get_job.return_value.next_run_time = None
        sched = scheduler.start_scheduler(FakeApp)
    job_ids = [j.id for j in sched.get_jobs()]
    assert scheduler.SCHEDULED_TX_JOB_ID in job_ids


# ── rule edit / pause / delete ────────────────────────────────────────────────

def test_rule_edit_only_touches_future_pending(seed):
    db = TestSession()
    today = date(2026, 10, 31)
    # started 3 months ago → 3 overdue occurrences (Aug, Sep, Oct)
    rule, created = _new_rule(db, seed["ws_id"], today, description="Edit", start_date=date(2026, 8, 1))
    by_date = {o.due_date: o for o in created}
    overdue = by_date[date(2026, 8, 5)]
    paid_past = by_date[date(2026, 9, 5)]
    svc.mark_paid(db, paid_past, paid_at=date(2026, 9, 5))
    paid_early = by_date[date(2026, 12, 5)]
    svc.mark_paid(db, paid_early, paid_at=date(2026, 10, 30))
    canceled = by_date[date(2027, 1, 5)]
    svc.cancel(db, canceled)

    dropped, rebuilt = svc.update_rule(db, rule, {"amount": Decimal("2800"), "description": "Aluguel novo"}, today=today)
    assert dropped == 1  # only 05/11 was future PENDING
    assert [o.due_date for o in rebuilt] == [date(2026, 11, 5)]
    assert rebuilt[0].amount == Decimal("2800") and rebuilt[0].description == "Aluguel novo"
    # history untouched
    assert overdue.amount == Decimal("2500") and overdue.status == ScheduledStatus.PENDING
    assert paid_past.amount == Decimal("2500") and paid_past.status == ScheduledStatus.PAID
    assert paid_early.amount == Decimal("2500") and paid_early.status == ScheduledStatus.PAID
    assert canceled.status == ScheduledStatus.CANCELED and canceled.description == "Edit"
    db.rollback(); db.close()


def test_rule_edit_reschedules_future_pending(seed):
    db = TestSession()
    today = date(2026, 10, 31)
    rule, _ = _new_rule(db, seed["ws_id"], today, description="Dia muda")
    svc.update_rule(db, rule, {"day_of_month": 20}, today=today)
    assert [o.due_date for o in _occs(db, rule.id)] == [date(2026, 11, 20), date(2026, 12, 20), date(2027, 1, 20)]
    db.rollback(); db.close()


def test_pause_drops_future_pending_and_job_skips(seed):
    db = TestSession()
    today = date(2026, 10, 31)
    rule, _ = _new_rule(db, seed["ws_id"], today, description="Pausa")
    dropped, created = svc.update_rule(db, rule, {"is_active": False}, today=today)
    assert dropped == 3 and created == []
    assert svc.materialize_rule(db, rule, today=today) == []
    _, created = svc.update_rule(db, rule, {"is_active": True}, today=today)
    assert len(created) == 3
    db.rollback(); db.close()


def test_rule_shape_validation(seed):
    db = TestSession()
    today = date(2026, 10, 31)
    with pytest.raises(svc.ScheduleError, match="anual exige o mês"):
        _new_rule(db, seed["ws_id"], today, frequency=RecurrenceFrequency.YEARLY)
    with pytest.raises(svc.ScheduleError, match="Mês só se aplica"):
        _new_rule(db, seed["ws_id"], today, month=3)
    with pytest.raises(svc.ScheduleError, match="número de parcelas"):
        _new_rule(db, seed["ws_id"], today, frequency=RecurrenceFrequency.INSTALLMENT)
    with pytest.raises(svc.ScheduleError, match="Parcelas só se aplicam"):
        _new_rule(db, seed["ws_id"], today, installment_total=3)
    with pytest.raises(svc.ScheduleError, match="Fim deve ser"):
        _new_rule(db, seed["ws_id"], today, end_date=today - timedelta(days=1))
    db.rollback(); db.close()


# ── overdue / status ──────────────────────────────────────────────────────────

def test_overdue_is_derived():
    occ = ScheduledTransaction(status=ScheduledStatus.PENDING, due_date=date(2026, 10, 30))
    assert svc.is_overdue(occ, date(2026, 10, 31))
    assert svc.display_status(occ, date(2026, 10, 31)) == "OVERDUE"
    assert not svc.is_overdue(occ, date(2026, 10, 30))  # vence hoje ≠ atraso
    occ.status = ScheduledStatus.PAID
    assert not svc.is_overdue(occ, date(2026, 10, 31))
    assert svc.display_status(occ, date(2026, 10, 31)) == "PAID"


def test_overdue_in_api_and_filter(client, seed):
    r = _one_off(client, seed, description="Boleto vencido", due_date=(TODAY - timedelta(days=3)).isoformat())
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "PENDING" and body["display_status"] == "OVERDUE" and body["is_overdue"] is True
    lst = client.get("/api/scheduled-transactions?overdue=true", headers=auth(seed["admin_token"])).json()
    assert body["id"] in [o["id"] for o in lst]
    assert all(o["is_overdue"] for o in lst)
    client.post(f"/api/scheduled-transactions/{body['id']}/cancel", headers=auth(seed["admin_token"]))


# ── positive-amount convention ────────────────────────────────────────────────

@pytest.mark.parametrize("amount", ["-100.00", "0", "0.004"])
def test_amount_must_be_positive(client, seed, amount):
    r = _one_off(client, seed, amount=amount)
    assert r.status_code == 422
    r = client.post("/api/recurrence-rules", json={
        "direction": "RECEIVABLE", "description": "Salário", "amount": amount, "frequency": "MONTHLY",
        "day_of_month": 10, "start_date": TODAY.isoformat(),
    }, headers=auth(seed["admin_token"]))
    assert r.status_code == 422


def test_direction_gives_the_sign(client, seed):
    pay = _one_off(client, seed, description="Sinal pagar").json()
    rec = _one_off(client, seed, direction="RECEIVABLE", description="Sinal receber").json()
    assert pay["amount"] == 1200 and pay["signed_amount"] == -1200
    assert rec["amount"] == 1200 and rec["signed_amount"] == 1200
    for o in (pay, rec):
        client.delete(f"/api/scheduled-transactions/{o['id']}", headers=auth(seed["admin_token"]))


def test_currency_follows_expected_account(client, seed):
    r = _one_off(client, seed, description="USD bill", expected_account_id=seed["nomad"])
    assert r.status_code == 201 and r.json()["currency"] == "USD"
    assert r.json()["expected_account_name"] == "Conta Corrente Nomad"
    client.delete(f"/api/scheduled-transactions/{r.json()['id']}", headers=auth(seed["admin_token"]))
    assert _one_off(client, seed, expected_account_id=seed["nomad"], currency="BRL").status_code == 422
    assert _one_off(client, seed, expected_account_id=seed["invest"]).status_code == 422


# ── manual actions ────────────────────────────────────────────────────────────

def test_rule_crud_via_api_materializes(client, seed):
    h = auth(seed["admin_token"])
    r = client.post("/api/recurrence-rules", json={
        "direction": "PAYABLE", "description": "Condomínio", "amount": "900.00", "frequency": "MONTHLY",
        "day_of_month": 10, "start_date": TODAY.isoformat(), "category_id": seed["sub"],
        "party_id": seed["party"], "expected_account_id": seed["itau"],
    }, headers=h)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["created_count"] >= 2
    rule = body["rule"]
    assert rule["next_due_date"] and rule["pending_count"] == body["created_count"]
    assert rule["category_name"] == "Aluguel" and rule["category_color"] == "#ff0000"
    occs = client.get(f"/api/scheduled-transactions?recurrence_rule_id={rule['id']}", headers=h).json()
    assert len(occs) == body["created_count"]
    assert all(o["frequency"] == "MONTHLY" and o["party_name"] == "Imobiliária X" for o in occs)

    r = client.patch(f"/api/recurrence-rules/{rule['id']}", json={"amount": "950.00"}, headers=h)
    assert r.status_code == 200, r.text
    occs = client.get(f"/api/scheduled-transactions?recurrence_rule_id={rule['id']}", headers=h).json()
    assert all(o["amount"] == 950 for o in occs if o["due_date"] >= TODAY.isoformat())

    assert client.delete(f"/api/recurrence-rules/{rule['id']}", headers=h).status_code == 204
    assert client.get(f"/api/recurrence-rules/{rule['id']}", headers=h).status_code == 404
    db = TestSession()
    actions = {a.action for a in db.query(AuditLog).filter(AuditLog.resource_id == rule["id"]).all()}
    assert {"recurrence_rule.created", "recurrence_rule.updated", "recurrence_rule.deleted"} <= actions
    db.close()


def test_delete_rule_keeps_history_detached(seed):
    db = TestSession()
    today = date(2026, 10, 31)
    rule, created = _new_rule(db, seed["ws_id"], today, description="Del", start_date=date(2026, 9, 1))
    svc.mark_paid(db, created[0], paid_at=date(2026, 9, 5))
    paid_id = created[0].id
    deleted, detached = svc.delete_rule(db, rule)
    assert detached == 1 and deleted == len(created) - 1
    kept = db.get(ScheduledTransaction, paid_id)
    assert kept.recurrence_rule_id is None and kept.status == ScheduledStatus.PAID
    db.rollback(); db.close()


def test_mark_paid_without_tx(client, seed):
    occ = _one_off(client, seed, description="Pago sem link").json()
    r = client.post(f"/api/scheduled-transactions/{occ['id']}/pay", json={"paid_at": TODAY.isoformat()},
                    headers=auth(seed["admin_token"]))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "PAID" and r.json()["paid_at"] == TODAY.isoformat()
    assert r.json()["paid_by_transaction_id"] is None
    # already paid → 409 on every action
    for action, body in (("pay", {"paid_at": TODAY.isoformat()}), ("postpone", {"due_date": TODAY.isoformat()}), ("cancel", None)):
        r = client.post(f"/api/scheduled-transactions/{occ['id']}/{action}", json=body, headers=auth(seed["admin_token"]))
        assert r.status_code == 409, action


def test_mark_paid_with_tx_links_and_inherits(client, seed):
    occ = _one_off(client, seed, description="Aluguel out", category_id=seed["sub"], party_id=seed["party"]).json()
    tx = _tx(client, seed, "-1200.00")
    income = _tx(client, seed, "500.00", desc="Entrada qualquer")

    cands = client.get(f"/api/scheduled-transactions/{occ['id']}/candidate-transactions", headers=auth(seed["admin_token"])).json()
    cand_ids = [c["id"] for c in cands]
    assert tx["id"] in cand_ids and income["id"] not in cand_ids

    # wrong sign → 422
    r = client.post(f"/api/scheduled-transactions/{occ['id']}/pay",
                    json={"paid_at": TODAY.isoformat(), "transaction_id": income["id"]}, headers=auth(seed["admin_token"]))
    assert r.status_code == 422
    r = client.post(f"/api/scheduled-transactions/{occ['id']}/pay",
                    json={"paid_at": TODAY.isoformat(), "transaction_id": tx["id"]}, headers=auth(seed["admin_token"]))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "PAID" and r.json()["paid_by_transaction_id"] == tx["id"]
    t = client.get(f"/api/transactions/{tx['id']}", headers=auth(seed["admin_token"])).json()
    assert t["category_id"] == seed["sub"] and t["party_id"] == seed["party"]

    # the same tx can't settle a second occurrence
    other = _one_off(client, seed, description="Outra").json()
    r = client.post(f"/api/scheduled-transactions/{other['id']}/pay",
                    json={"paid_at": TODAY.isoformat(), "transaction_id": tx["id"]}, headers=auth(seed["admin_token"]))
    assert r.status_code == 409
    cands = client.get(f"/api/scheduled-transactions/{other['id']}/candidate-transactions", headers=auth(seed["admin_token"])).json()
    assert tx["id"] not in [c["id"] for c in cands]

    # deleting the tx puts the occurrence back to PENDING (audited)
    assert client.delete(f"/api/transactions/{tx['id']}", headers=auth(seed["admin_token"])).status_code == 204
    back = client.get(f"/api/scheduled-transactions/{occ['id']}", headers=auth(seed["admin_token"])).json()
    assert back["status"] == "PENDING" and back["paid_by_transaction_id"] is None and back["paid_at"] is None
    db = TestSession()
    assert db.query(AuditLog).filter(
        AuditLog.action == "scheduled_transaction.payment_reverted", AuditLog.resource_id == occ["id"],
    ).count() == 1
    db.close()


def test_settle_occurrence_is_the_import_entry_point(client, seed):
    """spec 71 calls settle_occurrence(occ, tx) directly — paid_at defaults to the tx date."""
    occ_id = _one_off(client, seed, direction="RECEIVABLE", description="Salário import").json()["id"]
    tx_id = _tx(client, seed, "1200.00", days_ago=2, desc="SALARIO")["id"]
    db = TestSession()
    from numis_geek.models.transaction import Transaction
    occ = db.get(ScheduledTransaction, occ_id)
    tx = db.get(Transaction, tx_id)
    svc.settle_occurrence(db, occ, tx)
    assert occ.status == ScheduledStatus.PAID and occ.paid_at == tx.event_date
    assert occ.paid_by_transaction_id == tx.id
    db.rollback(); db.close()


def test_postpone_and_cancel(client, seed):
    h = auth(seed["admin_token"])
    occ = _one_off(client, seed, description="Adiar").json()
    new_due = (TODAY + timedelta(days=40)).isoformat()
    r = client.post(f"/api/scheduled-transactions/{occ['id']}/postpone", json={"due_date": new_due}, headers=h)
    assert r.status_code == 200 and r.json()["due_date"] == new_due
    r = client.post(f"/api/scheduled-transactions/{occ['id']}/postpone", json={"due_date": new_due}, headers=h)
    assert r.status_code == 422  # same date
    r = client.post(f"/api/scheduled-transactions/{occ['id']}/cancel", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "CANCELED" and r.json()["display_status"] == "CANCELED"
    db = TestSession()
    actions = [a.action for a in db.query(AuditLog).filter(AuditLog.resource_id == occ["id"]).all()]
    assert {"scheduled_transaction.created", "scheduled_transaction.postponed", "scheduled_transaction.canceled"} <= set(actions)
    db.close()


def test_postpone_clash_with_same_rule(seed):
    db = TestSession()
    rule, created = _new_rule(db, seed["ws_id"], date(2026, 10, 31), description="Clash")
    with pytest.raises(svc.ScheduleConflict):
        svc.postpone(db, created[0], created[1].due_date)
    db.rollback(); db.close()


def test_edit_occurrence_and_delete_rules(client, seed):
    h = auth(seed["admin_token"])
    occ = _one_off(client, seed, description="Editar").json()
    r = client.patch(f"/api/scheduled-transactions/{occ['id']}", json={"amount": "1300.50", "notes": "reajuste"}, headers=h)
    assert r.status_code == 200 and r.json()["amount"] == 1300.5
    assert client.patch(f"/api/scheduled-transactions/{occ['id']}", json={"amount": "-5"}, headers=h).status_code == 422
    assert client.delete(f"/api/scheduled-transactions/{occ['id']}", headers=h).status_code == 204

    db = TestSession()
    rule, created = _new_rule(db, seed["ws_id"], TODAY, description="Não exclui")
    db.commit()
    occ_id, rule_id = created[0].id, rule.id
    db.close()
    assert client.delete(f"/api/scheduled-transactions/{occ_id}", headers=h).status_code == 409
    assert client.delete(f"/api/recurrence-rules/{rule_id}", headers=h).status_code == 204


# ── forecast ──────────────────────────────────────────────────────────────────

def test_forecast_buckets_overdue_and_accounts(seed):
    db = TestSession()
    ws = WorkspaceService(db).create("Forecast WS")
    db.flush()
    acc = _account(db, ws.id, seed["fi_id"], "CC Forecast")
    usd_acc = _account(db, ws.id, seed["fi_id"], "CC USD", currency=Currency.USD)
    db.flush()
    today = date(2026, 10, 15)

    def one(direction, amount, due, account=None, currency=None):
        return svc.create_one_off(db, ws.id, svc.OccurrenceInput(
            direction=direction, description="x", amount=Decimal(amount), due_date=due,
            expected_account_id=account, currency=currency,
        ))

    P, R = ScheduledDirection.PAYABLE, ScheduledDirection.RECEIVABLE
    one(P, "100", date(2026, 9, 20))                       # overdue, previous month
    one(P, "200", date(2026, 10, 10), acc.id)              # overdue, this month
    one(R, "1000", date(2026, 10, 20), acc.id)
    one(P, "50", date(2026, 11, 5), usd_acc.id)            # USD → BRL 250
    one(R, "300", date(2026, 12, 1))
    one(R, "999", date(2027, 1, 1))                        # outside months=3
    paid = one(P, "777", date(2026, 10, 25))
    svc.mark_paid(db, paid, paid_at=today)

    f = svc.forecast(db, ws.id, months=3, today=today)
    assert [m["month"] for m in f["months"]] == ["2026-10", "2026-11", "2026-12"]
    oct_, nov, dec = f["months"]
    assert oct_["payable"]["brl"] == 200 and oct_["receivable"]["brl"] == 1000 and oct_["net"]["brl"] == 800
    assert oct_["by_account"] == [{
        "account_id": acc.id, "account_name": "CC Forecast", "currency": "BRL",
        "payable": 200.0, "receivable": 1000.0, "net": 800.0,
    }]
    assert nov["payable"]["brl"] == 250 and nov["payable"]["usd"] == 50
    assert nov["by_account"][0]["currency"] == "USD" and nov["by_account"][0]["payable"] == 50
    assert dec["receivable"]["brl"] == 300 and dec["by_account"] == []
    assert f["overdue"]["count"] == 2 and f["overdue"]["payable"]["brl"] == 300
    assert f["fx_rate"] == 5.0
    db.rollback(); db.close()


def test_forecast_endpoint(client, seed):
    r = client.get("/api/scheduled-transactions/forecast?months=3", headers=auth(seed["member_token"]))
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["months"]) == 3 and body["months"][0]["month"] == TODAY.strftime("%Y-%m")
    assert set(body["overdue"]) == {"count", "payable", "receivable"}
    assert client.get("/api/scheduled-transactions/forecast?months=0", headers=auth(seed["member_token"])).status_code == 422


# ── workspace isolation & permissions ─────────────────────────────────────────

def test_workspace_isolation(client, seed):
    occ = _one_off(client, seed, description="Só WS1").json()
    h2 = auth(seed["admin2_token"])
    assert client.get(f"/api/scheduled-transactions/{occ['id']}", headers=h2).status_code == 404
    assert client.post(f"/api/scheduled-transactions/{occ['id']}/cancel", headers=h2).status_code == 404
    assert client.post(f"/api/scheduled-transactions/{occ['id']}/pay", json={"paid_at": TODAY.isoformat()}, headers=h2).status_code == 404
    assert occ["id"] not in [o["id"] for o in client.get("/api/scheduled-transactions", headers=h2).json()]
    # cross-workspace references are rejected
    assert _one_off(client, seed, token=seed["admin2_token"], expected_account_id=seed["itau"]).status_code == 422
    assert _one_off(client, seed, token=seed["admin2_token"], category_id=seed["sub"]).status_code == 422
    # a ws2 tx can't settle a ws1 occurrence (sysadmin crossing workspaces)
    db = TestSession()
    other_acc = _account(db, seed["ws2_id"], seed["fi_id"], "CC WS2")
    db.commit(); other_id = other_acc.id; db.close()
    tx2 = client.post("/api/transactions", json={
        "source_type": "CHECKING", "checking_account_id": other_id, "event_date": TODAY.isoformat(),
        "description": "ws2 tx", "amount": "-1200",
    }, headers=h2).json()[0]
    r = client.post(f"/api/scheduled-transactions/{occ['id']}/pay",
                    json={"paid_at": TODAY.isoformat(), "transaction_id": tx2["id"]}, headers=auth(seed["sys_token"]))
    assert r.status_code == 422


def test_member_reads_but_cannot_write(client, seed):
    hm = auth(seed["member_token"])
    occ = _one_off(client, seed, description="Member vê").json()
    assert client.get("/api/scheduled-transactions", headers=hm).status_code == 200
    assert client.get("/api/recurrence-rules", headers=hm).status_code == 200
    assert client.get(f"/api/scheduled-transactions/{occ['id']}", headers=hm).status_code == 200
    assert _one_off(client, seed, token=seed["member_token"]).status_code == 403
    assert client.post("/api/recurrence-rules", json={
        "direction": "PAYABLE", "description": "x", "amount": "1", "frequency": "MONTHLY",
        "day_of_month": 1, "start_date": TODAY.isoformat(),
    }, headers=hm).status_code == 403
    for action, body in (("pay", {"paid_at": TODAY.isoformat()}), ("postpone", {"due_date": TODAY.isoformat()}), ("cancel", None)):
        assert client.post(f"/api/scheduled-transactions/{occ['id']}/{action}", json=body, headers=hm).status_code == 403
    assert client.patch(f"/api/scheduled-transactions/{occ['id']}", json={"notes": "x"}, headers=hm).status_code == 403
    assert client.delete(f"/api/scheduled-transactions/{occ['id']}", headers=hm).status_code == 403


def test_sysadmin_writes_with_workspace_id(client, seed):
    hs = auth(seed["sys_token"])
    # pure sysadmin (no workspace) must say which one
    assert _one_off(client, seed, token=seed["sys_token"]).status_code == 400
    r = client.post(f"/api/scheduled-transactions?workspace_id={seed['ws_id']}", json={
        "direction": "RECEIVABLE", "description": "Sys cria", "amount": "10",
        "due_date": TODAY.isoformat(),
    }, headers=hs)
    assert r.status_code == 201 and r.json()["workspace_id"] == seed["ws_id"]
    # sysadmin acts on any workspace's occurrence
    assert client.post(f"/api/scheduled-transactions/{r.json()['id']}/cancel", headers=hs).status_code == 200


def test_party_merge_repoints_rules_and_occurrences(client, seed):
    h = auth(seed["admin_token"])
    occ = _one_off(client, seed, description="Merge", party_id=seed["party2"]).json()
    rule = client.post("/api/recurrence-rules", json={
        "direction": "PAYABLE", "description": "Merge rule", "amount": "10", "frequency": "MONTHLY",
        "day_of_month": 3, "start_date": TODAY.isoformat(), "party_id": seed["party2"],
    }, headers=h).json()["rule"]
    r = client.post(f"/api/parties/{seed['party']}/merge", json={"source_party_id": seed["party2"]}, headers=h)
    assert r.status_code == 200, r.text
    assert client.get(f"/api/scheduled-transactions/{occ['id']}", headers=h).json()["party_id"] == seed["party"]
    assert client.get(f"/api/recurrence-rules/{rule['id']}", headers=h).json()["party_id"] == seed["party"]
