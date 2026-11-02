"""Spec 72 — Contas a Pagar e a Receber (services).

Every write on `recurrence_rule` / `scheduled_transaction` goes through here
so the invariants hold for every caller (API today, statement import in
spec 71, daily job):

- `amount` always positive — `direction` gives the sign;
- every occurrence keeps its ORIGINAL slot (`slot_date`); postponing moves
  only `due_date`. Materialization is idempotent and dedupes by slot: a
  rule's slots up to `today + 90 days` exist exactly once
  (UNIQUE(rule, slot_date)); MONTHLY/INSTALLMENT also never put a second
  occurrence in a year-month the rule already holds (YEARLY: per year), and
  INSTALLMENT never repeats a parcela number. The `materialized_through`
  watermark keeps a canceled/deleted slot from coming back;
- editing a rule only touches occurrences still PENDING whose slot AND due
  date are both >= today: they're dropped and re-materialized from the new
  rule. Overdue (by slot or by due date), paid and canceled ones are history
  and never change — and since they keep holding their slot, the rebuild
  never duplicates them (audit 2026-10-31);
- `settle_occurrence(occ, tx)` is the single path that marks an occurrence
  PAID with a real transaction — the manual "Marcar pago" and the import
  matcher (spec 71) both call it. `undo_payment` is the way back.

Raises `ScheduleError` (→ 422) and `ScheduleConflict` (→ 409); routes
translate. Flushes, never commits.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from numis_geek.models.account import Account, AccountType, Currency
from numis_geek.models.credit_card import Invoice, InvoiceStatus
from numis_geek.models.ptax_rate import PTAXRate
from numis_geek.models.scheduled_transaction import (
    RecurrenceFrequency, RecurrenceRule, ScheduledDirection, ScheduledStatus,
    ScheduledTransaction,
)
from numis_geek.models.transaction import Transaction
from numis_geek.services.fx import FxRateNotFound, fx_rate_on
from numis_geek.services.transactions import (
    TransactionError, add_months, to_cents, validate_category, validate_party,
)

HORIZON_DAYS = 90
# Safety net: a MONTHLY rule over 90 days yields ~3 slots; a rule back-dated
# by decades must not spin forever. When a run hits the cap the watermark
# stops at the last generated slot, so the next run carries on from there.
MAX_SLOTS_PER_RUN = 1200
# A rule can't start more than this many months back (audit 2026-10-31):
# past slots are born overdue, and decades of them are a typo.
MAX_START_MONTHS_BACK = 24


class ScheduleError(Exception):
    """Invalid input — maps to 422."""


class ScheduleConflict(Exception):
    """State conflict (e.g. paying a canceled occurrence) — maps to 409."""


def horizon(today: date | None = None) -> date:
    return (today or date.today()) + timedelta(days=HORIZON_DAYS)


def is_overdue(occ: ScheduledTransaction, today: date | None = None) -> bool:
    """'Em atraso' is derived, never stored."""
    return occ.status == ScheduledStatus.PENDING and occ.due_date < (today or date.today())


def display_status(occ: ScheduledTransaction, today: date | None = None) -> str:
    return "OVERDUE" if is_overdue(occ, today) else occ.status.value


def signed_amount(direction: ScheduledDirection, amount: Decimal) -> Decimal:
    """Ledger sign of an occurrence: payable is an outflow."""
    return -amount if direction == ScheduledDirection.PAYABLE else amount


# ── validation ────────────────────────────────────────────────────────────────

def positive_amount(value) -> Decimal:
    try:
        q = to_cents(value)
    except TransactionError as exc:
        raise ScheduleError(str(exc))
    if q <= 0:
        raise ScheduleError("Valor deve ser positivo — a direção (a pagar / a receber) dá o sinal.")
    return q


def _validate_refs(db: Session, workspace_id: str, *, category_id, party_id) -> None:
    try:
        validate_category(db, workspace_id, category_id)
        validate_party(db, workspace_id, party_id)
    except TransactionError as exc:
        raise ScheduleError(str(exc))


def resolve_account_currency(
    db: Session, workspace_id: str, account_id: str | None, currency: Currency | None,
    *, require_active: bool = True,
) -> Currency:
    """Expected account must be a checking account of the workspace; the
    occurrence's currency defaults to (and must match) the account's.

    `require_active` only when the account is being SET (create, or the
    value changed): a rule/occurrence that already points to an account
    deactivated later stays editable and pausable (audit 2026-10-31)."""
    if account_id is None:
        return currency or Currency.BRL
    acc = db.get(Account, account_id)
    if not acc or acc.workspace_id != workspace_id:
        raise ScheduleError("Conta não encontrada.")
    if acc.account_type != AccountType.checking:
        raise ScheduleError("Conta prevista deve ser conta corrente.")
    if require_active and not acc.is_active:
        raise ScheduleError("Conta inativa.")
    if currency is not None and currency != acc.currency:
        raise ScheduleError(f"Moeda difere da conta ({acc.currency.value}).")
    return acc.currency


def _clean_description(desc: str | None) -> str:
    d = (desc or "").strip()
    if not d:
        raise ScheduleError("Descrição é obrigatória.")
    if len(d) > 255:
        raise ScheduleError("Descrição longa demais (máx. 255).")
    return d


def validate_rule_shape(rule: RecurrenceRule) -> None:
    """Frequency-specific fields: month only for YEARLY, installment_* only
    for INSTALLMENT; day_of_month 1–28 (every month has it)."""
    if not 1 <= (rule.day_of_month or 0) <= 28:
        raise ScheduleError("Dia do vencimento deve ser entre 1 e 28.")
    if rule.frequency == RecurrenceFrequency.YEARLY:
        if not 1 <= (rule.month or 0) <= 12:
            raise ScheduleError("Recorrência anual exige o mês (1–12).")
    elif rule.month is not None:
        raise ScheduleError("Mês só se aplica à recorrência anual.")
    if rule.frequency == RecurrenceFrequency.INSTALLMENT:
        if not rule.installment_total or rule.installment_total < 1 or rule.installment_total > 1200:
            raise ScheduleError("Parcelamento exige o número de parcelas (1–1200).")
        paid = rule.installment_paid or 0
        if not 0 <= paid < rule.installment_total:
            raise ScheduleError("Parcelas já pagas deve ser entre 0 e o total − 1.")
    elif rule.installment_total is not None or rule.installment_paid:
        raise ScheduleError("Parcelas só se aplicam ao parcelamento.")
    if rule.end_date is not None and rule.end_date < rule.start_date:
        raise ScheduleError("Fim deve ser igual ou posterior ao início.")


def validate_start_date(start: date, today: date | None = None) -> None:
    """Checked on create and whenever `start_date` changes — an existing
    rule that started long ago stays editable."""
    floor = add_months(today or date.today(), -MAX_START_MONTHS_BACK)
    if start < floor:
        raise ScheduleError(
            f"Início não pode ser anterior a {MAX_START_MONTHS_BACK} meses atrás "
            f"({floor.strftime('%d/%m/%Y')})."
        )


# ── slot generation (pure) ────────────────────────────────────────────────────

def _first_slot(rule: RecurrenceRule) -> date:
    if rule.frequency == RecurrenceFrequency.YEARLY:
        d = date(rule.start_date.year, rule.month, rule.day_of_month)
        return d if d >= rule.start_date else date(d.year + 1, rule.month, rule.day_of_month)
    first = add_months(rule.start_date, 0, rule.day_of_month)
    return first if first >= rule.start_date else add_months(rule.start_date, 1, rule.day_of_month)


def slot_dates(
    rule: RecurrenceRule, until: date, *, after: date | None = None, limit: int | None = None,
) -> tuple[list[date], bool]:
    """Slot dates of `rule` (first on/after `start_date`, then every month /
    year) in (`after`, min(until, end_date)]. Dates <= `after` are walked
    but don't count toward `limit` (default MAX_SLOTS_PER_RUN). Returns
    (dates, truncated) — truncated when the limit cut the list short.

    No installment bound here: the parcela count is enforced by the
    materializer, which hands out the free parcela numbers in order."""
    cap = MAX_SLOTS_PER_RUN if limit is None else limit
    last = min(until, rule.end_date) if rule.end_date else until
    first = _first_slot(rule)
    out: list[date] = []
    i = 0
    while True:
        if rule.frequency == RecurrenceFrequency.YEARLY:
            d = date(first.year + i, rule.month, rule.day_of_month)
        else:
            d = add_months(first, i, rule.day_of_month)
        if d > last:
            return out, False
        i += 1
        if after is not None and d <= after:
            continue
        if len(out) >= cap:
            return out, True
        out.append(d)


def rule_slots(rule: RecurrenceRule, until: date) -> list[tuple[date, int | None]]:
    """Every (slot_date, installment_number) of a FRESH `rule` (no
    occurrence yet) from `start_date` up to `until` (inclusive), respecting
    `end_date` and the installment count.

    INSTALLMENT: the 1st slot on/after `start_date` is parcela
    `installment_paid + 1` (parcelas already paid before the rule existed
    are skipped), one per month until parcela `installment_total`."""
    dates, _ = slot_dates(rule, until)
    if rule.frequency != RecurrenceFrequency.INSTALLMENT:
        return [(d, None) for d in dates]
    paid = rule.installment_paid or 0
    return [(d, paid + i + 1) for i, d in enumerate(dates) if paid + i + 1 <= rule.installment_total]


def slot_period(rule: RecurrenceRule, d: date) -> tuple[int, ...]:
    """Dedupe key: one occurrence per year-month (YEARLY: per year)."""
    if rule.frequency == RecurrenceFrequency.YEARLY:
        return (d.year,)
    return (d.year, d.month)


# ── materialization ───────────────────────────────────────────────────────────

def _occurrence_from_rule(rule: RecurrenceRule, slot: date, k: int | None, user_id: str | None) -> ScheduledTransaction:
    return ScheduledTransaction(
        workspace_id=rule.workspace_id,
        direction=rule.direction,
        recurrence_rule_id=rule.id,
        description=rule.description,
        party_id=rule.party_id,
        category_id=rule.category_id,
        amount=rule.amount,
        currency=rule.currency,
        due_date=slot,
        slot_date=slot,
        installment_number=k,
        installment_total=rule.installment_total if k is not None else None,
        expected_account_id=rule.expected_account_id,
        status=ScheduledStatus.PENDING,
        created_by=user_id,
        updated_by=user_id,
    )


def free_installment_numbers(rule: RecurrenceRule, held: set[int]) -> list[int]:
    """Parcela numbers still to be generated, ascending: (paid, total] minus
    the numbers some existing occurrence already holds."""
    if rule.frequency != RecurrenceFrequency.INSTALLMENT or not rule.installment_total:
        return []
    return [k for k in range((rule.installment_paid or 0) + 1, rule.installment_total + 1) if k not in held]


def materialize_rule(
    db: Session, rule: RecurrenceRule, *, today: date | None = None, user_id: str | None = None,
) -> list[ScheduledTransaction]:
    """Ensure every slot of an active rule in (`materialized_through`,
    today + 90d] exists. Dedupes by ORIGINAL slot (never by the current
    due_date, which a postpone may have moved): a slot is skipped when its
    slot_date — or, MONTHLY/INSTALLMENT, its year-month; YEARLY, its year —
    is already held by an occurrence of the rule. INSTALLMENT hands out the
    free parcela numbers in order (numbering continues from the first one
    nobody holds) and stops when they run out. If the per-run cap is hit,
    the watermark stops at the last generated slot."""
    if not rule.is_active:
        return []
    until = horizon(today)
    floor = rule.materialized_through
    existing = db.query(
        ScheduledTransaction.slot_date, ScheduledTransaction.installment_number,
    ).filter(ScheduledTransaction.recurrence_rule_id == rule.id).all()
    taken_slots = {d for d, _ in existing}
    taken_periods = {slot_period(rule, d) for d, _ in existing}
    is_inst = rule.frequency == RecurrenceFrequency.INSTALLMENT
    free_k = free_installment_numbers(rule, {k for _, k in existing if k is not None})

    dates, truncated = slot_dates(rule, until, after=floor)
    created: list[ScheduledTransaction] = []
    for slot in dates:
        if is_inst and not free_k:
            break
        if slot in taken_slots or slot_period(rule, slot) in taken_periods:
            continue
        k = free_k.pop(0) if is_inst else None
        occ = _occurrence_from_rule(rule, slot, k, user_id)
        db.add(occ)
        created.append(occ)
        taken_slots.add(slot)
        taken_periods.add(slot_period(rule, slot))
    watermark = dates[-1] if truncated else until
    if rule.materialized_through is None or rule.materialized_through < watermark:
        rule.materialized_through = watermark
    db.flush()
    return created


def is_dropped_on_edit(occ: ScheduledTransaction, today: date) -> bool:
    """What a rule edit/pause deletes: PENDING whose slot AND due date are
    both today or later. A postponed overdue occurrence (old slot) and one
    moved to an already-past date survive, holding their slot."""
    return (
        occ.status == ScheduledStatus.PENDING
        and occ.slot_date >= today
        and occ.due_date >= today
    )


def drop_future_pending(db: Session, rule: RecurrenceRule, today: date | None = None) -> int:
    """Delete the rule's future PENDING occurrences (`is_dropped_on_edit`) —
    the only ones a rule edit may touch. Overdue/paid/canceled stay."""
    t = today or date.today()
    rows = db.query(ScheduledTransaction).filter(
        ScheduledTransaction.recurrence_rule_id == rule.id,
        ScheduledTransaction.status == ScheduledStatus.PENDING,
        ScheduledTransaction.slot_date >= t,
        ScheduledTransaction.due_date >= t,
    ).all()
    for r in rows:
        db.delete(r)
    db.flush()
    return len(rows)


def rematerialize_rule(
    db: Session, rule: RecurrenceRule, *, today: date | None = None, user_id: str | None = None,
) -> tuple[int, list[ScheduledTransaction]]:
    """After a rule edit: drop future PENDING and rebuild them from today."""
    t = today or date.today()
    dropped = drop_future_pending(db, rule, t)
    rule.materialized_through = t - timedelta(days=1)
    return dropped, materialize_rule(db, rule, today=t, user_id=user_id)


def materialize_workspace(
    db: Session, workspace_id: str, *, today: date | None = None, user_id: str | None = None,
) -> dict[str, int]:
    """Daily job body for one workspace: {rule_id: created_count} (only >0)."""
    out: dict[str, int] = {}
    rules = db.query(RecurrenceRule).filter(
        RecurrenceRule.workspace_id == workspace_id, RecurrenceRule.is_active.is_(True),
    ).all()
    for rule in rules:
        created = materialize_rule(db, rule, today=today, user_id=user_id)
        if created:
            out[rule.id] = len(created)
    return out


# ── rules CRUD ────────────────────────────────────────────────────────────────

RULE_FIELDS = (
    "direction", "description", "party_id", "category_id", "amount", "currency",
    "frequency", "day_of_month", "month", "installment_total", "installment_paid",
    "expected_account_id", "start_date", "end_date", "is_active", "notes",
)


@dataclass
class RuleInput:
    direction: ScheduledDirection
    description: str
    amount: Decimal
    frequency: RecurrenceFrequency
    day_of_month: int
    start_date: date
    currency: Currency | None = None
    party_id: str | None = None
    category_id: str | None = None
    month: int | None = None
    installment_total: int | None = None
    installment_paid: int | None = None
    expected_account_id: str | None = None
    end_date: date | None = None
    is_active: bool = True
    notes: str | None = None


def _normalize_rule(db: Session, rule: RecurrenceRule, *, account_changed: bool = True) -> None:
    rule.description = _clean_description(rule.description)
    rule.amount = positive_amount(rule.amount)
    rule.currency = resolve_account_currency(
        db, rule.workspace_id, rule.expected_account_id, rule.currency, require_active=account_changed,
    )
    if rule.frequency == RecurrenceFrequency.INSTALLMENT and rule.installment_paid is None:
        rule.installment_paid = 0
    validate_rule_shape(rule)


def create_rule(
    db: Session, workspace_id: str, data: RuleInput, *, user_id: str | None = None,
    today: date | None = None,
) -> tuple[RecurrenceRule, list[ScheduledTransaction]]:
    _validate_refs(db, workspace_id, category_id=data.category_id, party_id=data.party_id)
    if data.start_date is not None:
        validate_start_date(data.start_date, today)
    rule = RecurrenceRule(workspace_id=workspace_id, created_by=user_id, updated_by=user_id)
    for f in RULE_FIELDS:
        setattr(rule, f, getattr(data, f))
    _normalize_rule(db, rule)
    db.add(rule)
    db.flush()
    return rule, materialize_rule(db, rule, today=today, user_id=user_id)


def update_rule(
    db: Session, rule: RecurrenceRule, changes: dict, *, user_id: str | None = None,
    today: date | None = None,
) -> tuple[int, list[ScheduledTransaction]]:
    """Partial update. Any change re-materializes the FUTURE PENDING
    occurrences (dropped + rebuilt, see `is_dropped_on_edit`); everything
    else is untouched. Refs (account / category / party) and the start
    date are only validated when they CHANGE, so a rule pointing to
    something deactivated later can still be edited, paused, reactivated."""
    t = today or date.today()
    for f in ("direction", "description", "amount", "frequency", "day_of_month", "start_date", "is_active"):
        if f in changes and changes[f] is None:
            raise ScheduleError(f"{f} não pode ser nulo.")
    if "start_date" in changes and changes["start_date"] != rule.start_date:
        validate_start_date(changes["start_date"], t)
    account_changed = (
        "expected_account_id" in changes and changes["expected_account_id"] != rule.expected_account_id
    )
    if "category_id" in changes and changes["category_id"] != rule.category_id:
        _validate_refs(db, rule.workspace_id, category_id=changes["category_id"], party_id=None)
    if "party_id" in changes and changes["party_id"] != rule.party_id:
        _validate_refs(db, rule.workspace_id, category_id=None, party_id=changes["party_id"])
    if "expected_account_id" in changes and "currency" not in changes and changes["expected_account_id"]:
        # trocar a conta arrasta a moeda junto
        rule.currency = None
    for f in RULE_FIELDS:
        if f in changes:
            setattr(rule, f, changes[f])
    if rule.frequency != RecurrenceFrequency.YEARLY and "frequency" in changes and "month" not in changes:
        rule.month = None
    if rule.frequency != RecurrenceFrequency.INSTALLMENT and "frequency" in changes:
        if "installment_total" not in changes:
            rule.installment_total = None
        if "installment_paid" not in changes:
            rule.installment_paid = None
    _normalize_rule(db, rule, account_changed=account_changed)
    rule.updated_by = user_id
    db.flush()
    if not rule.is_active:
        dropped = drop_future_pending(db, rule, t)
        rule.materialized_through = t - timedelta(days=1)
        return dropped, []
    return rematerialize_rule(db, rule, today=t, user_id=user_id)


def delete_rule(db: Session, rule: RecurrenceRule) -> tuple[int, int]:
    """Hard-delete the rule: its PENDING occurrences go with it (overdue
    included); PAID/CANCELED stay as history, detached (rule_id NULL).
    Returns (deleted_pending, detached)."""
    rows = db.query(ScheduledTransaction).filter(ScheduledTransaction.recurrence_rule_id == rule.id).all()
    deleted = detached = 0
    for r in rows:
        if r.status == ScheduledStatus.PENDING:
            db.delete(r)
            deleted += 1
        else:
            r.recurrence_rule_id = None
            detached += 1
    db.flush()
    db.delete(rule)
    db.flush()
    return deleted, detached


# ── occurrences ───────────────────────────────────────────────────────────────

OCC_EDITABLE = ("description", "party_id", "category_id", "amount", "currency", "expected_account_id", "notes")


@dataclass
class OccurrenceInput:
    direction: ScheduledDirection
    description: str
    amount: Decimal
    due_date: date
    currency: Currency | None = None
    party_id: str | None = None
    category_id: str | None = None
    expected_account_id: str | None = None
    notes: str | None = None


def create_one_off(
    db: Session, workspace_id: str, data: OccurrenceInput, *, user_id: str | None = None,
) -> ScheduledTransaction:
    _validate_refs(db, workspace_id, category_id=data.category_id, party_id=data.party_id)
    occ = ScheduledTransaction(
        workspace_id=workspace_id,
        direction=data.direction,
        recurrence_rule_id=None,
        description=_clean_description(data.description),
        party_id=data.party_id,
        category_id=data.category_id,
        amount=positive_amount(data.amount),
        currency=resolve_account_currency(db, workspace_id, data.expected_account_id, data.currency),
        due_date=data.due_date,
        slot_date=data.due_date,
        expected_account_id=data.expected_account_id,
        status=ScheduledStatus.PENDING,
        notes=data.notes,
        created_by=user_id,
        updated_by=user_id,
    )
    db.add(occ)
    db.flush()
    return occ


def _require_pending(occ: ScheduledTransaction, what: str) -> None:
    if occ.status != ScheduledStatus.PENDING:
        label = "paga" if occ.status == ScheduledStatus.PAID else "cancelada"
        raise ScheduleConflict(f"Conta já {label} — não dá pra {what}.")


def update_occurrence(
    db: Session, occ: ScheduledTransaction, changes: dict, *, user_id: str | None = None,
) -> ScheduledTransaction:
    """Per-occurrence edit (amount may diverge from the rule). Only PENDING;
    due_date changes go through `postpone`."""
    _require_pending(occ, "editar")
    for f in ("description", "amount"):
        if f in changes and changes[f] is None:
            raise ScheduleError(f"{f} não pode ser nulo.")
    if "category_id" in changes and changes["category_id"] != occ.category_id:
        _validate_refs(db, occ.workspace_id, category_id=changes["category_id"], party_id=None)
    if "party_id" in changes and changes["party_id"] != occ.party_id:
        _validate_refs(db, occ.workspace_id, category_id=None, party_id=changes["party_id"])
    account_changed = (
        "expected_account_id" in changes and changes["expected_account_id"] != occ.expected_account_id
    )
    if "expected_account_id" in changes and "currency" not in changes and changes["expected_account_id"]:
        occ.currency = None
    for f in OCC_EDITABLE:
        if f in changes:
            setattr(occ, f, changes[f])
    occ.description = _clean_description(occ.description)
    occ.amount = positive_amount(occ.amount)
    occ.currency = resolve_account_currency(
        db, occ.workspace_id, occ.expected_account_id, occ.currency, require_active=account_changed,
    )
    occ.updated_by = user_id
    db.flush()
    return occ


def _link_conflict(db: Session, tx: Transaction, occ: ScheduledTransaction) -> ScheduledTransaction | None:
    return db.query(ScheduledTransaction).filter(
        ScheduledTransaction.paid_by_transaction_id == tx.id,
        ScheduledTransaction.id != occ.id,
    ).first()


def validate_settling_tx(db: Session, occ: ScheduledTransaction, tx: Transaction) -> None:
    """Tx that settles an occurrence: same workspace, sign matching the
    direction, and not already settling another occurrence."""
    if tx.workspace_id != occ.workspace_id:
        raise ScheduleError("Movimentação não encontrada.")
    if occ.direction == ScheduledDirection.PAYABLE and tx.amount >= 0:
        raise ScheduleError("Conta a pagar só quita com uma saída (valor negativo).")
    if occ.direction == ScheduledDirection.RECEIVABLE and tx.amount <= 0:
        raise ScheduleError("Conta a receber só quita com uma entrada (valor positivo).")
    other = _link_conflict(db, tx, occ)
    if other:
        raise ScheduleConflict(
            f"Movimentação já quita outra conta: {other.description} · vence {other.due_date.strftime('%d/%m/%Y')}."
        )


def _tx_writable(db: Session, tx: Transaction) -> bool:
    """A card tx inside a PAID invoice is frozen (same lock as
    `transactions._ensure_invoice_writable`)."""
    if not tx.invoice_id:
        return True
    inv = db.get(Invoice, tx.invoice_id)
    return inv is None or inv.status != InvoiceStatus.PAID


def _ref_active(db: Session, workspace_id: str, *, category_id=None, party_id=None) -> bool:
    try:
        _validate_refs(db, workspace_id, category_id=category_id, party_id=party_id)
    except ScheduleError:
        return False
    return True


def settle_occurrence(
    db: Session, occ: ScheduledTransaction, tx: Transaction, *,
    paid_at: date | None = None, user_id: str | None = None, inherited: dict | None = None,
) -> ScheduledTransaction:
    """THE path that marks an occurrence PAID by a real transaction —
    manual "Marcar pago" with a link and the spec 71 import matcher both
    call this. Sets PAID + paid_at (default: tx date) +
    paid_by_transaction_id.

    The tx inherits the occurrence's category/party when its own is empty —
    only if that category/party is still active and the tx is writable (not
    in a PAID invoice). What was inherited goes into `inherited` (when
    given) as {field: value}, so the caller can audit it."""
    _require_pending(occ, "quitar")
    validate_settling_tx(db, occ, tx)
    occ.status = ScheduledStatus.PAID
    occ.paid_at = paid_at or tx.event_date
    occ.paid_by_transaction_id = tx.id
    occ.updated_by = user_id
    got: dict = {}
    if _tx_writable(db, tx):
        if (tx.category_id is None and occ.category_id is not None
                and _ref_active(db, tx.workspace_id, category_id=occ.category_id)):
            tx.category_id = occ.category_id
            got["category_id"] = occ.category_id
        if (tx.party_id is None and occ.party_id is not None
                and _ref_active(db, tx.workspace_id, party_id=occ.party_id)):
            tx.party_id = occ.party_id
            got["party_id"] = occ.party_id
    if got:
        tx.updated_at = datetime.now(timezone.utc)
        tx.updated_by = user_id
    if inherited is not None:
        inherited.update(got)
    db.flush()
    return occ


def remember_rule_alias(db: Session, occ: ScheduledTransaction, alias: str | None) -> None:
    """Spec 71 (2026-11-02) — the statement import settled `occ` with a bank
    line: remember that text (normalized, no trailing dates — or the Pix
    counterparty) on the occurrence's rule so the next statement scores it
    strongly. One-offs have no rule → nothing to learn."""
    if not alias or not occ.recurrence_rule_id:
        return
    from numis_geek.models.scheduled_transaction import RecurrenceRuleAlias
    row = db.query(RecurrenceRuleAlias).filter(
        RecurrenceRuleAlias.recurrence_rule_id == occ.recurrence_rule_id,
        RecurrenceRuleAlias.alias_normalized == alias,
    ).first()
    if row is None:
        db.add(RecurrenceRuleAlias(workspace_id=occ.workspace_id, recurrence_rule_id=occ.recurrence_rule_id,
                                   alias_normalized=alias[:255], hits=1))
    else:
        row.hits += 1
        row.last_seen_at = datetime.now(timezone.utc)
    db.flush()


def learns_amount(db: Session, occ: ScheduledTransaction) -> bool:
    """Ocorrência de regra MONTHLY/YEARLY: o valor pago no extrato vira o
    valor previsto da regra. Parcelamento (INSTALLMENT) e avulsa, não."""
    if not occ.recurrence_rule_id:
        return False
    rule = db.get(RecurrenceRule, occ.recurrence_rule_id)
    return rule is not None and rule.frequency in (RecurrenceFrequency.MONTHLY, RecurrenceFrequency.YEARLY)


def learn_amount_from_payment(
    db: Session, occ: ScheduledTransaction, tx: Transaction, *, user_id: str | None = None,
) -> dict | None:
    """Spec 71 (user, 2026-11-02: "o valor certo o sistema vai ter que
    identificar a partir dos extratos"). Called by the statement import
    right after `settle_occurrence` — NEVER by the manual "Marcar pago".

    When the paid |tx.amount| differs from the occurrence amount, the rule
    learns it (`rule.amount = paid`) and so do its later PENDING occurrences
    — only those still holding the old rule amount, so a value the user
    edited by hand on one occurrence is never overwritten. Returns the
    change ({rule_id, old_amount, new_amount, occurrence_ids}) or None."""
    if not learns_amount(db, occ):
        return None
    paid = to_cents(abs(Decimal(tx.amount)))
    if paid <= 0 or paid == to_cents(occ.amount):
        return None
    rule = db.get(RecurrenceRule, occ.recurrence_rule_id)
    old = to_cents(rule.amount)
    rule.amount = paid
    rule.updated_by = user_id
    later = db.query(ScheduledTransaction).filter(
        ScheduledTransaction.recurrence_rule_id == rule.id,
        ScheduledTransaction.status == ScheduledStatus.PENDING,
        ScheduledTransaction.due_date > occ.due_date,
        ScheduledTransaction.id != occ.id,
    ).all()
    touched = []
    for o in later:
        if to_cents(o.amount) == old:
            o.amount = paid
            o.updated_by = user_id
            touched.append(o.id)
    db.flush()
    return {
        "rule_id": rule.id, "description": rule.description, "old_amount": str(old),
        "new_amount": str(paid), "occurrence_ids": touched, "settled_occurrence_id": occ.id,
        "transaction_id": tx.id,
    }


def mark_paid(
    db: Session, occ: ScheduledTransaction, *, paid_at: date, transaction_id: str | None = None,
    user_id: str | None = None, inherited: dict | None = None,
) -> ScheduledTransaction:
    """Manual fallback. With a tx → `settle_occurrence`; without → PAID
    with no link (the UI warns that nothing ties it to the ledger)."""
    if transaction_id:
        tx = db.get(Transaction, transaction_id)
        if not tx:
            raise ScheduleError("Movimentação não encontrada.")
        return settle_occurrence(db, occ, tx, paid_at=paid_at, user_id=user_id, inherited=inherited)
    _require_pending(occ, "marcar como paga")
    occ.status = ScheduledStatus.PAID
    occ.paid_at = paid_at
    occ.paid_by_transaction_id = None
    occ.updated_by = user_id
    db.flush()
    return occ


def postpone(
    db: Session, occ: ScheduledTransaction, new_due: date, *, user_id: str | None = None,
) -> ScheduledTransaction:
    """Moves only `due_date` — `slot_date` stays, so the occurrence keeps
    holding its original slot. Landing on another slot's date is fine: the
    two occurrences stay distinct and the materializer still creates the
    other slot (audit 2026-10-31)."""
    _require_pending(occ, "adiar")
    if new_due == occ.due_date:
        raise ScheduleError("Escolha uma data diferente do vencimento atual.")
    occ.due_date = new_due
    occ.updated_by = user_id
    db.flush()
    return occ


def cancel(db: Session, occ: ScheduledTransaction, *, user_id: str | None = None) -> ScheduledTransaction:
    _require_pending(occ, "cancelar")
    occ.status = ScheduledStatus.CANCELED
    occ.updated_by = user_id
    db.flush()
    return occ


def delete_one_off(db: Session, occ: ScheduledTransaction) -> None:
    """Only one-offs are deletable — a rule occurrence is canceled instead
    (deleting it would be undone by the next rule edit)."""
    if occ.recurrence_rule_id:
        raise ScheduleConflict("Ocorrência de recorrência — use Cancelar (ou edite a recorrência).")
    db.delete(occ)
    db.flush()


def undo_payment(db: Session, occ: ScheduledTransaction, *, user_id: str | None = None) -> dict:
    """"Desfazer pagamento": PAID → PENDING, clearing paid_at and the tx
    link. Returns what was cleared (for the audit). A category/party the tx
    inherited on payment stays on the tx."""
    if occ.status != ScheduledStatus.PAID:
        raise ScheduleConflict("Só dá pra desfazer o pagamento de uma conta paga.")
    before = {
        "paid_at": occ.paid_at.isoformat() if occ.paid_at else None,
        "paid_by_transaction_id": occ.paid_by_transaction_id,
    }
    occ.status = ScheduledStatus.PENDING
    occ.paid_at = None
    occ.paid_by_transaction_id = None
    occ.updated_by = user_id
    db.flush()
    return before


def unlink_on_sign_change(db: Session, tx: Transaction) -> list[ScheduledTransaction]:
    """Hook for transaction edit: an occurrence settled by `tx` whose sign
    no longer matches its direction goes back to PENDING, link cleared. An
    amount-only change (same sign) keeps it PAID."""
    rows = db.query(ScheduledTransaction).filter(ScheduledTransaction.paid_by_transaction_id == tx.id).all()
    out = []
    for r in rows:
        ok = tx.amount < 0 if r.direction == ScheduledDirection.PAYABLE else tx.amount > 0
        if not ok:
            r.status = ScheduledStatus.PENDING
            r.paid_at = None
            r.paid_by_transaction_id = None
            out.append(r)
    if out:
        db.flush()
    return out


def unlink_transaction(db: Session, tx_id: str) -> list[ScheduledTransaction]:
    """Hook for transaction delete: occurrences it settled go back to
    PENDING (same idea as an invoice payment being undone)."""
    rows = db.query(ScheduledTransaction).filter(ScheduledTransaction.paid_by_transaction_id == tx_id).all()
    for r in rows:
        r.status = ScheduledStatus.PENDING
        r.paid_at = None
        r.paid_by_transaction_id = None
    if rows:
        db.flush()
    return rows


def candidate_transactions(
    db: Session, occ: ScheduledTransaction, *, window_days: int = 45, limit: int = 50,
) -> list[Transaction]:
    """Tx that could settle `occ` by hand: same workspace, sign matching
    the direction, event_date within ±window of due_date, not settling any
    other occurrence. Closest date first, then closest |amount|."""
    q = db.query(Transaction).filter(
        Transaction.workspace_id == occ.workspace_id,
        Transaction.event_date >= occ.due_date - timedelta(days=window_days),
        Transaction.event_date <= occ.due_date + timedelta(days=window_days),
        Transaction.amount < 0 if occ.direction == ScheduledDirection.PAYABLE else Transaction.amount > 0,
        ~Transaction.id.in_(
            db.query(ScheduledTransaction.paid_by_transaction_id).filter(
                ScheduledTransaction.paid_by_transaction_id.isnot(None),
                ScheduledTransaction.id != occ.id,
            )
        ),
    )
    rows = q.all()
    rows.sort(key=lambda t: (abs((t.event_date - occ.due_date).days), abs(abs(t.amount) - occ.amount)))
    return rows[:limit]


# ── forecast ──────────────────────────────────────────────────────────────────

def latest_fx(db: Session, today: date | None = None) -> Decimal | None:
    """BRL per USD for converting future flows: today's PTAX (walkback),
    else the most recent one on file, else None."""
    t = today or date.today()
    try:
        return fx_rate_on(db, t)
    except FxRateNotFound:
        rate = db.query(PTAXRate.rate).order_by(PTAXRate.date.desc()).first()
        return Decimal(rate[0]) if rate else None


def to_pair(amount: Decimal, currency: Currency, fx: Decimal | None) -> tuple[Decimal, Decimal]:
    """(brl, usd) of a native amount; without fx the other side is 0."""
    if currency == Currency.BRL:
        return amount, (amount / fx if fx else Decimal("0"))
    return (amount * fx if fx else Decimal("0")), amount


def month_start(d: date) -> date:
    return d.replace(day=1)


def forecast(
    db: Session, workspace_id: str, *, months: int = 3, today: date | None = None,
) -> dict:
    """PENDING flow aggregated by due month, from the current month on
    (`months` buckets): a pagar, a receber, líquido (BRL/USD at the latest
    PTAX) + breakdown by expected account (native currency). `overdue`
    totals every PENDING with due_date < today, any month."""
    t = today or date.today()
    start = month_start(t)
    end = add_months(start, months, 1)  # exclusive
    fx = latest_fx(db, t)
    rows = db.query(ScheduledTransaction).filter(
        ScheduledTransaction.workspace_id == workspace_id,
        ScheduledTransaction.status == ScheduledStatus.PENDING,
        ScheduledTransaction.due_date < end,
    ).all()
    acc_ids = {r.expected_account_id for r in rows if r.expected_account_id}
    accounts = {a.id: a for a in db.query(Account).filter(Account.id.in_(acc_ids)).all()} if acc_ids else {}
    invoices = card_invoices_due(db, workspace_id, start, end, rows)

    zero = Decimal("0")
    buckets: dict[str, dict] = {}
    for i in range(months):
        ym = add_months(start, i, 1).strftime("%Y-%m")
        buckets[ym] = {
            "month": ym, "count": 0,
            "payable": [zero, zero], "receivable": [zero, zero],
            "by_account": {},
        }
    overdue = {"count": 0, "payable": [zero, zero], "receivable": [zero, zero]}

    for r in rows:
        brl, usd = to_pair(Decimal(r.amount), r.currency, fx)
        side = "payable" if r.direction == ScheduledDirection.PAYABLE else "receivable"
        if r.due_date < t:
            overdue["count"] += 1
            overdue[side][0] += brl
            overdue[side][1] += usd
        if r.due_date < start:
            continue
        b = buckets[r.due_date.strftime("%Y-%m")]
        b["count"] += 1
        b[side][0] += brl
        b[side][1] += usd
        if r.expected_account_id and r.expected_account_id in accounts:
            acc = accounts[r.expected_account_id]
            a = b["by_account"].setdefault(acc.id, {
                "account_id": acc.id, "account_name": acc.name, "currency": acc.currency.value,
                "payable": zero, "receivable": zero,
            })
            a[side] += Decimal(r.amount)

    # Spec 72 (2026-11-02) — fatura de cartão ainda não paga entra como
    # "a pagar" no vencimento (o pagamento real, quando vier, é tx — fatura
    # PAID sai daqui).
    for inv in invoices:
        brl, usd = to_pair(inv["_amount"], inv["_currency"], fx)
        due = inv["_due"]
        if due < t:
            overdue["count"] += 1
            overdue["payable"][0] += brl
            overdue["payable"][1] += usd
        b = buckets[due.strftime("%Y-%m")]
        b["count"] += 1
        b["payable"][0] += brl
        b["payable"][1] += usd

    def pair(v):
        return {"brl": float(round(v[0], 2)), "usd": float(round(v[1], 2))}

    out_months = []
    for b in buckets.values():
        net = [b["receivable"][0] - b["payable"][0], b["receivable"][1] - b["payable"][1]]
        out_months.append({
            "month": b["month"],
            "count": b["count"],
            "payable": pair(b["payable"]),
            "receivable": pair(b["receivable"]),
            "net": pair(net),
            "by_account": [
                {
                    **{k: v for k, v in a.items() if k not in ("payable", "receivable")},
                    "payable": float(a["payable"]),
                    "receivable": float(a["receivable"]),
                    "net": float(a["receivable"] - a["payable"]),
                }
                for a in sorted(b["by_account"].values(), key=lambda x: x["account_name"])
            ],
        })
    return {
        "months": out_months,
        "overdue": {
            "count": overdue["count"],
            "payable": pair(overdue["payable"]),
            "receivable": pair(overdue["receivable"]),
        },
        "fx_rate": float(fx) if fx is not None else None,
        "card_invoices": [{k: v for k, v in inv.items() if not k.startswith("_")} for inv in invoices],
    }


def _represents_invoice(occ: ScheduledTransaction, card_name: str, due: date) -> bool:
    """Conta a pagar que já É a fatura deste cartão (ex.: regra "Fatura Cartão
    X" do Notion — não importadas de propósito, mas se existir não conta
    em dobro): descrição com "FATURA" e um nome do cartão, vencendo perto."""
    from numis_geek.services.normalize import normalize_description
    if abs((occ.due_date - due).days) > 7:
        return False
    desc = normalize_description(occ.description)
    words = [w for w in normalize_description(card_name).split() if len(w) >= 4]
    return "FATURA" in desc and any(w in desc for w in words)


def card_invoices_due(
    db: Session, workspace_id: str, start: date, end: date, occurrences: list[ScheduledTransaction],
) -> list[dict]:
    """Faturas não pagas vencendo em [start, end): valor = total_amount se
    FECHADA, senão a soma das tx conhecidas (inclui parcelas previstas)."""
    from numis_geek.models.credit_card import CreditCardAccount
    from numis_geek.services.transactions import invoice_open_total
    invs = db.query(Invoice).filter(
        Invoice.workspace_id == workspace_id,
        Invoice.status != InvoiceStatus.PAID,
        Invoice.due_date >= start,
        Invoice.due_date < end,
    ).order_by(Invoice.due_date).all()
    cards = {c.id: c for c in db.query(CreditCardAccount).filter(
        CreditCardAccount.id.in_({i.credit_card_account_id for i in invs})).all()} if invs else {}
    out = []
    for inv in invs:
        card = cards.get(inv.credit_card_account_id)
        if card is None:
            continue
        if inv.status == InvoiceStatus.CLOSED and inv.total_amount is not None:
            amount = Decimal(inv.total_amount)
        else:
            amount = invoice_open_total(db, inv)
        if amount <= 0:
            continue
        if any(_represents_invoice(o, card.name, inv.due_date) for o in occurrences):
            continue
        out.append({
            "invoice_id": inv.id, "card_id": card.id, "card_name": card.name,
            "due_date": inv.due_date.isoformat(), "close_date": inv.close_date.isoformat(),
            "status": inv.status.value, "amount": float(amount), "currency": inv.currency.value,
            "label": f"Fatura {card.name} · vence {inv.due_date.strftime('%d/%m')}",
            "_amount": amount, "_currency": inv.currency, "_due": inv.due_date,
        })
    return out
