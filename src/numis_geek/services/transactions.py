"""Spec 70 — Transaction services.

Every write path for `transaction` goes through here so the invariants
hold no matter who calls (API today, statement import in spec 71):

- `fingerprint` computed on every write (dedup base for spec 71);
- `fx_rate` always resolved (STATEMENT when the caller has the document's
  rate, PTAX walkback otherwise) and `amount_brl` / `amount_usd` persisted;
- card tx always land in an invoice (resolved/created lazily by period);
- `pay_invoice` is the ONLY way an invoice becomes PAID;
- transfers between own accounts are always a pair sharing
  `transfer_group_id`.

Services raise `TransactionError` (→ 422) and `TransactionConflict`
(→ 409); routes translate. They flush but never commit.
"""
from __future__ import annotations

import calendar
import hashlib
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, InvalidOperation

from sqlalchemy.orm import Session

from numis_geek.models.account import Account, AccountType, Currency
from numis_geek.models.category import Category
from numis_geek.models.credit_card import CreditCardAccount, Invoice, InvoiceStatus
from numis_geek.models.party import Party
from numis_geek.models.tag import Tag
from numis_geek.models.transaction import (
    FxSource, Transaction, TransactionSourceType, transaction_tag,
)
from numis_geek.services.fx import FxRateNotFound, fx_rate_on
from numis_geek.services.normalize import normalize_description

CENT = Decimal("0.01")
# close_date real pode divergir do close_day teórico (fim de semana/feriado).
INVOICE_CLOSE_TOLERANCE_DAYS = 7


class TransactionError(Exception):
    """Invalid input — maps to 422."""


class TransactionConflict(Exception):
    """State conflict (e.g. paid invoice) — maps to 409."""


def to_cents(value, what: str = "Valor") -> Decimal:
    """Quantize to cents BEFORE any zero/sign check (0.004 is zero), and turn
    absurd magnitudes into a 422 instead of InvalidOperation (500)."""
    try:
        q = Decimal(value).quantize(CENT, ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        raise TransactionError(f"{what} inválido.")
    if abs(q) >= Decimal("1e14"):
        raise TransactionError(f"{what} fora do limite.")
    return q


# ── pure helpers ──────────────────────────────────────────────────────────────

def compute_fingerprint(
    source_type: TransactionSourceType,
    source_id: str,
    event_date: date,
    amount: Decimal,
    currency: Currency,
    description: str,
    *,
    original_amount: Decimal | None = None,
    original_currency: Currency | str | None = None,
) -> str:
    """sha1(source_type + source FK + event_date + amount + currency +
    normalize_description). Shared with the spec 71 dedup — never fork.

    A line converted from another currency (spec 71) hashes its ORIGINAL
    amount/currency, so a later PTAX correction or an edit of the converted
    value keeps the key stable."""
    if original_amount is not None and original_currency is not None:
        amount, currency = original_amount, original_currency
    raw = "|".join([
        source_type.value,
        source_id,
        event_date.isoformat(),
        str(Decimal(amount).quantize(CENT)),
        getattr(currency, "value", currency),   # original_currency é String(3) (spec 84)
        normalize_description(description),
    ])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def convert_amounts(amount: Decimal, currency: Currency, fx_rate: Decimal) -> tuple[Decimal, Decimal]:
    """(amount_brl, amount_usd) for a native `amount`; fx_rate is BRL per USD."""
    if currency == Currency.BRL:
        brl = Decimal(amount)
        usd = brl / fx_rate if fx_rate else Decimal("0")
    else:
        usd = Decimal(amount)
        brl = usd * fx_rate
    return brl.quantize(CENT, ROUND_HALF_UP), usd.quantize(CENT, ROUND_HALF_UP)


def add_months(d: date, months: int, day: int | None = None) -> date:
    """`d` shifted by `months`, day clamped to the month's length."""
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    target_day = day if day is not None else d.day
    return date(y, m, min(target_day, calendar.monthrange(y, m)[1]))


def theoretical_close_date(card: CreditCardAccount, event_date: date) -> date:
    """Next `close_day` on/after `event_date` — the invoice a purchase falls in."""
    this_month = add_months(event_date, 0, card.close_day)
    return this_month if event_date <= this_month else add_months(event_date, 1, card.close_day)


def theoretical_due_date(card: CreditCardAccount, close_date: date) -> date:
    """First `due_day` after `close_date`."""
    this_month = add_months(close_date, 0, card.due_day)
    return this_month if this_month > close_date else add_months(close_date, 1, card.due_day)


def split_installments(total: Decimal, n: int) -> list[Decimal]:
    """`total` in `n` parcels of equal cents; the 1st absorbs the remainder
    (card issuers round the same way)."""
    total = Decimal(total).quantize(CENT)
    base = (total / n).quantize(CENT, rounding=ROUND_DOWN)  # toward zero, both signs
    parts = [base] * n
    parts[0] = total - base * (n - 1)
    return parts


# ── resolution / validation ───────────────────────────────────────────────────

def resolve_fx(
    db: Session, event_date: date, statement_rate: Decimal | None,
) -> tuple[Decimal, FxSource]:
    if statement_rate is not None:
        if statement_rate <= 0:
            raise TransactionError("fx_rate must be positive.")
        return Decimal(statement_rate), FxSource.STATEMENT
    # Parcela futura de cartão: a PTAX da data ainda não existe — usa a
    # mais recente (hoje, com walkback). Recomputável quando a data chegar.
    try:
        return fx_rate_on(db, min(event_date, date.today())), FxSource.PTAX
    except FxRateNotFound:
        raise TransactionError(
            f"Sem PTAX até 10 dias antes de {event_date.isoformat()} — informe a cotação (fx_rate)."
        )


def get_checking_account(db: Session, workspace_id: str, account_id: str) -> Account:
    acc = db.get(Account, account_id)
    if not acc or acc.workspace_id != workspace_id:
        raise TransactionError("Conta não encontrada.")
    if acc.account_type != AccountType.checking:
        raise TransactionError("Movimentação de conta só em conta corrente (account_type=checking).")
    if not acc.is_active:
        raise TransactionError("Conta inativa.")
    return acc


def get_card(db: Session, workspace_id: str, card_id: str) -> CreditCardAccount:
    card = db.get(CreditCardAccount, card_id)
    if not card or card.workspace_id != workspace_id:
        raise TransactionError("Cartão não encontrado.")
    if not card.is_active:
        raise TransactionError("Cartão inativo.")
    return card


def validate_category(db: Session, workspace_id: str, category_id: str | None) -> None:
    if category_id is None:
        return
    c = db.get(Category, category_id)
    if not c or c.workspace_id != workspace_id:
        raise TransactionError("Categoria não encontrada.")
    if c.parent_id is None:
        raise TransactionError("Escolha uma subcategoria — a raiz é só agrupador.")
    if not c.is_active:
        raise TransactionError("Categoria inativa.")


def validate_party(db: Session, workspace_id: str, party_id: str | None) -> None:
    if party_id is None:
        return
    p = db.get(Party, party_id)
    if not p or p.workspace_id != workspace_id:
        raise TransactionError("Fornecedor/cliente não encontrado.")
    if not p.is_active:
        raise TransactionError("Fornecedor/cliente inativo.")


def resolve_tags(db: Session, workspace_id: str, tag_ids: list[str] | None) -> list[str]:
    if not tag_ids:
        return []
    ids = list(dict.fromkeys(tag_ids))
    found = db.query(Tag.id).filter(Tag.workspace_id == workspace_id, Tag.id.in_(ids)).all()
    if len(found) != len(ids):
        raise TransactionError("Tag não encontrada.")
    return ids


def set_tags(db: Session, tx_id: str, tag_ids: list[str]) -> None:
    db.execute(transaction_tag.delete().where(transaction_tag.c.transaction_id == tx_id))
    if tag_ids:
        db.execute(transaction_tag.insert(), [{"transaction_id": tx_id, "tag_id": t} for t in tag_ids])


def find_invoice_near(
    db: Session, card: CreditCardAccount, target: date, *, exclude: set[str] | frozenset[str] = frozenset(),
) -> Invoice | None:
    """Existing invoice closing near `target` (real close_date may drift a few
    days from the theoretical `close_day`) — lookup only."""
    tol = timedelta(days=INVOICE_CLOSE_TOLERANCE_DAYS)
    candidates = [
        i for i in db.query(Invoice).filter(
            Invoice.credit_card_account_id == card.id,
            Invoice.close_date >= target - tol,
            Invoice.close_date <= target + tol,
        ).all()
        if i.id not in exclude
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda i: abs((i.close_date - target).days))


def invoice_for_close(
    db: Session, card: CreditCardAccount, target: date, *, user_id: str | None = None,
    exclude: set[str] | frozenset[str] = frozenset(),
) -> Invoice:
    """Invoice closing near `target`, created OPEN (at `target`) if missing."""
    found = find_invoice_near(db, card, target, exclude=exclude)
    if found is not None:
        return found
    now = datetime.now(timezone.utc)
    inv = Invoice(
        id=str(uuid.uuid4()),
        workspace_id=card.workspace_id,
        credit_card_account_id=card.id,
        close_date=target,
        due_date=theoretical_due_date(card, target),
        currency=card.currency,
        status=InvoiceStatus.OPEN,
        created_at=now,
        updated_at=now,
        created_by=user_id,
        updated_by=user_id,
    )
    db.add(inv)
    db.flush()
    return inv


def cycle_of(card: CreditCardAccount, close_date: date) -> date:
    """Theoretical close (a `close_day` date) of the cycle a real
    `close_date` belongs to — the nearest one."""
    options = [add_months(close_date, k, card.close_day) for k in (-1, 0, 1)]
    return min(options, key=lambda t: abs((t - close_date).days))


def resolve_invoice(
    db: Session, card: CreditCardAccount, event_date: date, *, user_id: str | None = None,
) -> Invoice:
    """Invoice whose period — (previous close_date, close_date] — contains
    `event_date`, created OPEN if missing. Real close_dates drift from the
    theoretical `close_day` both ways:
    - the previous cycle closed LATER than theoretical → a purchase on/before
      that real close still belongs to it;
    - this cycle closed EARLIER → a purchase after it belongs to the next."""
    target = theoretical_close_date(card, event_date)
    prev = find_invoice_near(db, card, add_months(target, -1, card.close_day))
    if prev is not None and prev.close_date >= event_date:
        return prev
    inv = invoice_for_close(db, card, target, user_id=user_id)
    if inv.close_date < event_date:
        inv = invoice_for_close(db, card, add_months(target, 1, card.close_day), user_id=user_id)
    return inv


def _ensure_invoice_writable(inv: Invoice) -> None:
    if inv.status == InvoiceStatus.PAID:
        raise TransactionConflict("Fatura já paga — não aceita lançamentos novos nem alterações.")


# ── write paths ───────────────────────────────────────────────────────────────

@dataclass
class TxInput:
    source_type: TransactionSourceType
    event_date: date
    description: str
    amount: Decimal
    checking_account_id: str | None = None
    credit_card_account_id: str | None = None
    invoice_id: str | None = None
    fx_rate: Decimal | None = None
    category_id: str | None = None
    party_id: str | None = None
    tag_ids: list[str] | None = None
    notes: str | None = None
    is_reconciled: bool = False
    # spec 71 — linha convertida de outra moeda (valor/moeda do documento)
    original_amount: Decimal | None = None
    original_currency: Currency | None = None


def _fill(
    db: Session, tx: Transaction, *, currency: Currency, statement_rate: Decimal | None,
) -> None:
    """Derive fx + converted amounts + fingerprint from the tx's own fields."""
    rate, source = resolve_fx(db, tx.event_date, statement_rate)
    tx.currency = currency
    tx.fx_rate = rate
    tx.fx_source = source
    tx.amount_brl, tx.amount_usd = convert_amounts(tx.amount, currency, rate)
    source_id = {
        TransactionSourceType.CHECKING: tx.checking_account_id,
        TransactionSourceType.CREDIT_CARD: tx.credit_card_account_id,
        # Spec 83 — a fonte é o movimento do ativo (1 tx por movimento).
        TransactionSourceType.ASSET: tx.asset_movement_id,
    }[tx.source_type]
    # Spec 71: a k-ésima linha idêntica de um extrato ("2 cafés de R$ 5")
    # guarda o sufixo ":k" — preservado em toda reescrita.
    suffix = ""
    if tx.fingerprint and ":" in tx.fingerprint:
        suffix = ":" + tx.fingerprint.split(":", 1)[1]
    tx.fingerprint = compute_fingerprint(
        tx.source_type, source_id, tx.event_date, tx.amount, currency, tx.description,
        original_amount=tx.original_amount, original_currency=tx.original_currency,
    ) + suffix


def _new_tx(workspace_id: str, user_id: str | None, **fields) -> Transaction:
    now = datetime.now(timezone.utc)
    return Transaction(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        is_reconciled=False,
        created_at=now,
        updated_at=now,
        created_by=user_id,
        updated_by=user_id,
        **fields,
    )


def _validate_common(db: Session, workspace_id: str, data: TxInput) -> None:
    if not data.description or not data.description.strip():
        raise TransactionError("Descrição obrigatória.")
    if data.event_date is None:
        raise TransactionError("Data obrigatória.")
    data.amount = to_cents(data.amount)
    if data.amount == 0:
        raise TransactionError("Valor não pode ser zero.")
    validate_category(db, workspace_id, data.category_id)
    validate_party(db, workspace_id, data.party_id)


def create_transaction(
    db: Session, workspace_id: str, data: TxInput, *, user_id: str | None = None,
    installments: int = 1,
) -> list[Transaction]:
    """Create one tx — or `installments` card tx (one per month/invoice,
    children pointing to the 1st). Returns all created rows."""
    if data.source_type == TransactionSourceType.ASSET:
        # O par movimento + tx nasce junto em services/asset_payments.
        raise TransactionError("Pagamento com ativo: use /transactions/asset-payment.")
    _validate_common(db, workspace_id, data)
    tag_ids = resolve_tags(db, workspace_id, data.tag_ids)

    if data.source_type == TransactionSourceType.CHECKING:
        if data.credit_card_account_id or data.invoice_id:
            raise TransactionError("Movimentação de conta não leva cartão/fatura.")
        if not data.checking_account_id:
            raise TransactionError("Informe a conta corrente.")
        if installments != 1:
            raise TransactionError("Parcelamento só existe em lançamento de cartão.")
        acc = get_checking_account(db, workspace_id, data.checking_account_id)
        tx = _new_tx(
            workspace_id, user_id,
            source_type=data.source_type, checking_account_id=acc.id,
            event_date=data.event_date, description=data.description.strip(),
            amount=Decimal(data.amount), category_id=data.category_id,
            party_id=data.party_id, notes=data.notes,
            original_amount=data.original_amount, original_currency=data.original_currency,
        )
        tx.is_reconciled = data.is_reconciled
        _fill(db, tx, currency=acc.currency, statement_rate=data.fx_rate)
        db.add(tx)
        db.flush()
        set_tags(db, tx.id, tag_ids)
        return [tx]

    # CREDIT_CARD
    if data.checking_account_id:
        raise TransactionError("Lançamento de cartão não leva conta corrente.")
    if not data.credit_card_account_id:
        raise TransactionError("Informe o cartão.")
    if not 1 <= installments <= 48:
        raise TransactionError("Parcelas entre 1 e 48.")
    card = get_card(db, workspace_id, data.credit_card_account_id)

    first_invoice: Invoice | None = None
    if data.invoice_id:
        first_invoice = db.get(Invoice, data.invoice_id)
        if not first_invoice or first_invoice.credit_card_account_id != card.id:
            raise TransactionError("Fatura não pertence a este cartão.")

    parts = split_installments(data.amount, installments)
    if any(p == 0 for p in parts):
        raise TransactionError(
            f"Valor pequeno demais para {installments} parcelas — cada parcela precisa de ao menos 1 centavo."
        )
    created: list[Transaction] = []
    used: set[str] = set()
    anchor: date | None = None
    for k, part in enumerate(parts):
        ev = add_months(data.event_date, k)
        if k == 0:
            inv = first_invoice if first_invoice is not None else resolve_invoice(
                db, card, data.event_date, user_id=user_id,
            )
            # Parcela k cai k ciclos depois do ciclo TEÓRICO da 1ª — nunca
            # re-resolvida pela data deslocada (close_day >= 29 clampado em
            # fevereiro dobrava/pulava fatura; fatura X fechada cedo fazia a
            # parcela 2 cair nela de novo).
            anchor = cycle_of(card, inv.close_date)
        else:
            inv = invoice_for_close(
                db, card, add_months(anchor, k, card.close_day), user_id=user_id, exclude=used,
            )
        used.add(inv.id)
        _ensure_invoice_writable(inv)
        tx = _new_tx(
            workspace_id, user_id,
            source_type=data.source_type, credit_card_account_id=card.id,
            invoice_id=inv.id, event_date=ev, description=data.description.strip(),
            amount=part, category_id=data.category_id, party_id=data.party_id,
            notes=data.notes,
            original_amount=data.original_amount, original_currency=data.original_currency,
            installment_number=(k + 1) if installments > 1 else None,
            installment_total=installments if installments > 1 else None,
            parent_transaction_id=created[0].id if created else None,
        )
        tx.is_reconciled = data.is_reconciled
        _fill(db, tx, currency=card.currency, statement_rate=data.fx_rate)
        db.add(tx)
        db.flush()
        set_tags(db, tx.id, tag_ids)
        created.append(tx)
    return created


EDITABLE_FIELDS = (
    "event_date", "description", "amount", "fx_rate", "category_id", "party_id",
    "notes", "tag_ids", "is_reconciled",
    # Spec 83 — só em tx ASSET: quantidade do ativo que saiu/entrou.
    "asset_quantity",
)


def update_transaction(
    db: Session, tx: Transaction, changes: dict, *, user_id: str | None = None,
    reverted_occurrences: list | None = None,
) -> list[Transaction]:
    """Apply a partial update. Returns every row touched (a transfer edit
    also moves the other leg's date/description). A conta a pagar/receber
    (spec 72) settled by `tx` whose direction no longer matches the new
    sign goes back to PENDING — appended to `reverted_occurrences`."""
    unknown = set(changes) - set(EDITABLE_FIELDS)
    if unknown:
        raise TransactionError(f"Campos não editáveis: {', '.join(sorted(unknown))}.")
    for f in ("event_date", "description", "amount", "is_reconciled"):
        if f in changes and changes[f] is None:
            raise TransactionError(f"{f} não pode ser nulo.")
    if "amount" in changes:
        changes = {**changes, "amount": to_cents(changes["amount"])}
    is_asset = tx.source_type == TransactionSourceType.ASSET
    changes = dict(changes)  # não muta o dict do caller (audit usa o original)
    asset_quantity = changes.pop("asset_quantity", None)
    if asset_quantity is not None and not is_asset:
        raise TransactionError("Quantidade do ativo só existe em pagamento com ativo.")
    if is_asset:
        if "fx_rate" in changes and changes["fx_rate"] is not None:
            raise TransactionError("Pagamento com ativo usa a PTAX do dia — sem cotação manual.")
        changes.pop("fx_rate", None)
        if "amount" in changes and changes["amount"] != 0 and (changes["amount"] > 0) != (tx.amount > 0):
            raise TransactionConflict(
                "Pagamento com ativo não troca de direção (despesa ↔ receita) — exclua e recrie."
            )
    old_date = tx.event_date
    date_changed = "event_date" in changes and changes["event_date"] != old_date
    if tx.invoice_id:
        _ensure_invoice_writable(db.get(Invoice, tx.invoice_id))
    if tx.paid_invoice_id and "amount" in changes:
        raise TransactionConflict("Valor do pagamento de fatura não muda — exclua e pague de novo.")
    if tx.transfer_group_id and ("amount" in changes or "fx_rate" in changes):
        raise TransactionConflict("Valor de transferência não muda por perna — exclua e recrie a transferência.")

    if "description" in changes and not (changes["description"] or "").strip():
        raise TransactionError("Descrição obrigatória.")
    if "amount" in changes and changes["amount"] == 0:
        raise TransactionError("Valor não pode ser zero.")
    # Só valida quando MUDA: tx antiga apontando pra categoria/party já
    # desativada continua editável nos outros campos (spec 68).
    if "category_id" in changes and changes["category_id"] != tx.category_id:
        validate_category(db, tx.workspace_id, changes["category_id"])
    if "party_id" in changes and changes["party_id"] != tx.party_id:
        validate_party(db, tx.workspace_id, changes["party_id"])
    tag_ids = resolve_tags(db, tx.workspace_id, changes["tag_ids"]) if "tag_ids" in changes else None

    for f in ("event_date", "category_id", "party_id", "notes", "is_reconciled"):
        if f in changes:
            setattr(tx, f, changes[f])
    if "description" in changes:
        tx.description = changes["description"].strip()
    if "amount" in changes:
        tx.amount = Decimal(changes["amount"])
        # Spec 72 (audit 2026-10-31): sign flip un-settles the occurrence.
        from numis_geek.services.scheduled_transactions import unlink_on_sign_change
        reverted = unlink_on_sign_change(db, tx)
        if reverted_occurrences is not None:
            reverted_occurrences.extend(reverted)

    # Re-roteia só quando a data MUDOU de fato: o composer manda event_date
    # sempre, e uma fatura escolhida à mão no create não pode ser desfeita
    # por uma edição de descrição.
    if tx.source_type == TransactionSourceType.CREDIT_CARD and date_changed:
        card = db.get(CreditCardAccount, tx.credit_card_account_id)
        inv = resolve_invoice(db, card, tx.event_date, user_id=user_id)
        _ensure_invoice_writable(inv)
        tx.invoice_id = inv.id
    if tx.paid_invoice_id and date_changed:
        paid = db.get(Invoice, tx.paid_invoice_id)
        if paid is not None and paid.paid_by_transaction_id == tx.id:
            paid.paid_at = tx.event_date
            paid.updated_at = datetime.now(timezone.utc)
            paid.updated_by = user_id

    # re-derive fx: keep a STATEMENT rate unless the caller sends a new one
    statement_rate = changes.get("fx_rate")
    if statement_rate is None and tx.fx_source == FxSource.STATEMENT and "fx_rate" not in changes:
        statement_rate = tx.fx_rate
    _fill(db, tx, currency=tx.currency, statement_rate=statement_rate)
    tx.updated_at = datetime.now(timezone.utc)
    tx.updated_by = user_id
    if tag_ids is not None:
        set_tags(db, tx.id, tag_ids)
    if is_asset:
        from numis_geek.services.asset_payments import sync_movement_from_tx
        sync_movement_from_tx(
            db, tx, quantity=asset_quantity, amount_changed="amount" in changes, user_id=user_id,
        )

    touched = [tx]
    if tx.transfer_group_id and ({"event_date", "description"} & set(changes)):
        for other in transfer_legs(db, tx.transfer_group_id):
            if other.id == tx.id:
                continue
            other.event_date = tx.event_date
            other.description = tx.description
            # Perna PTAX re-deriva na nova data; só STATEMENT (cotação do
            # documento / implícita do câmbio) mantém a taxa.
            _fill(
                db, other, currency=other.currency,
                statement_rate=other.fx_rate if other.fx_source == FxSource.STATEMENT else None,
            )
            other.updated_at = tx.updated_at
            other.updated_by = user_id
            touched.append(other)
    db.flush()
    return touched


def transfer_legs(db: Session, group_id: str) -> list[Transaction]:
    return db.query(Transaction).filter(Transaction.transfer_group_id == group_id).all()


def installment_children(db: Session, parent_id: str) -> list[Transaction]:
    return db.query(Transaction).filter(Transaction.parent_transaction_id == parent_id).all()


def delete_transaction(
    db: Session, tx: Transaction, *, cascade: bool = False, reverted_occurrences: list | None = None,
    deactivated_movements: list | None = None, user_id: str | None = None,
) -> list[Transaction]:
    """Delete `tx` (and its transfer pair / installment children when
    `cascade`). Undoes an invoice payment, and puts every conta a
    pagar/receber (spec 72) it settled back to PENDING — appended to
    `reverted_occurrences` when given. Returns the deleted rows."""
    rows = [tx]
    if tx.transfer_group_id:
        rows = transfer_legs(db, tx.transfer_group_id)
    elif tx.parent_transaction_id is None:
        children = installment_children(db, tx.id)
        if children and not cascade:
            raise TransactionConflict(
                f"Parcelamento com {len(children)} parcelas seguintes — confirme a exclusão em cascata."
            )
        rows = [tx, *children]

    for r in rows:
        if r.invoice_id:
            _ensure_invoice_writable(db.get(Invoice, r.invoice_id))

    for r in rows:
        if r.paid_invoice_id:
            inv = db.get(Invoice, r.paid_invoice_id)
            if inv and inv.paid_by_transaction_id == r.id:
                inv.status = InvoiceStatus.CLOSED
                inv.paid_at = None
                inv.paid_by_transaction_id = None
                inv.updated_at = datetime.now(timezone.utc)
    # Spec 72 — occurrences settled by these tx go back to PENDING (before
    # the delete, so the FK never dangles).
    from numis_geek.services.scheduled_transactions import unlink_transaction
    for r in rows:
        reverted = unlink_transaction(db, r.id)
        if reverted_occurrences is not None:
            reverted_occurrences.extend(reverted)
    # Spec 83 — apagar o pagamento com ativo desativa o lançamento do ativo.
    from numis_geek.services.asset_payments import deactivate_movement_of
    for r in rows:
        if r.source_type == TransactionSourceType.ASSET:
            m = deactivate_movement_of(db, r, user_id=user_id)
            if m is not None and deactivated_movements is not None:
                deactivated_movements.append(m)
    db.flush()
    # children before the parent (self-FK)
    for r in sorted(rows, key=lambda x: x.parent_transaction_id is None):
        set_tags(db, r.id, [])
        db.delete(r)
    db.flush()
    return rows


def create_transfer(
    db: Session,
    workspace_id: str,
    *,
    from_account_id: str,
    to_account_id: str,
    event_date: date,
    amount_out: Decimal,
    amount_in: Decimal | None = None,
    description: str = "Transferência entre contas",
    category_id: str | None = None,
    notes: str | None = None,
    user_id: str | None = None,
) -> list[Transaction]:
    """Two CHECKING legs sharing `transfer_group_id`: −amount_out on the
    source, +amount_in on the destination. Different currencies require
    `amount_in`; the implied rate becomes the fx of both legs (STATEMENT)."""
    if from_account_id == to_account_id:
        raise TransactionError("Origem e destino são a mesma conta.")
    if event_date is None:
        raise TransactionError("Data obrigatória.")
    amount_out = to_cents(amount_out)
    if amount_out <= 0:
        raise TransactionError("Valor da transferência deve ser positivo.")
    if amount_in is not None:
        amount_in = to_cents(amount_in)
    src = get_checking_account(db, workspace_id, from_account_id)
    dst = get_checking_account(db, workspace_id, to_account_id)
    validate_category(db, workspace_id, category_id)
    description = (description or "").strip() or "Transferência entre contas"

    if src.currency == dst.currency:
        if amount_in is not None and amount_in != amount_out:
            raise TransactionError("Mesma moeda: valor de entrada deve ser igual ao de saída.")
        amount_in = amount_out
        statement_rate = None
    else:
        if amount_in is None or amount_in <= 0:
            raise TransactionError("Moedas diferentes: informe o valor que entrou no destino.")
        brl, usd = (amount_out, amount_in) if src.currency == Currency.BRL else (amount_in, amount_out)
        statement_rate = (brl / usd).quantize(Decimal("0.00000001"))

    group = str(uuid.uuid4())
    legs = []
    for acc, amt in ((src, -amount_out), (dst, amount_in)):
        tx = _new_tx(
            workspace_id, user_id,
            source_type=TransactionSourceType.CHECKING, checking_account_id=acc.id,
            event_date=event_date, description=description, amount=amt,
            category_id=category_id, notes=notes, transfer_group_id=group,
        )
        _fill(db, tx, currency=acc.currency, statement_rate=statement_rate)
        db.add(tx)
        legs.append(tx)
    db.flush()
    return legs


def pay_invoice(
    db: Session,
    invoice: Invoice,
    *,
    checking_account_id: str,
    paid_on: date,
    amount: Decimal | None = None,
    fx_rate: Decimal | None = None,
    category_id: str | None = None,
    user_id: str | None = None,
) -> Transaction:
    """The ONLY path that pays an invoice (UI button and spec 71 import).

    Creates the cash tx (negative, `paid_invoice_id` set — a transfer, never
    an expense) and flips the invoice to PAID with the mirror FK. `amount`
    is in the checking account's currency; defaults to the invoice total
    when the currencies match."""
    if invoice.status == InvoiceStatus.PAID:
        raise TransactionConflict("Fatura já paga.")
    # Pagar fatura OPEN congelava um total implícito que o "desfazer" não
    # sabia desfazer (voltava a CLOSED com total parcial). Fecha antes.
    if invoice.status != InvoiceStatus.CLOSED:
        raise TransactionConflict("Feche a fatura antes de pagar.")
    acc = get_checking_account(db, invoice.workspace_id, checking_account_id)
    validate_category(db, invoice.workspace_id, category_id)
    if amount is None:
        if invoice.total_amount is None:
            raise TransactionError("Fatura sem total — informe o valor pago.")
        if acc.currency != invoice.currency:
            raise TransactionError("Conta em outra moeda — informe o valor debitado na conta.")
        # Fatura fechada continua aceitando tx (import da spec 71): se a soma
        # mudou depois do fechamento, o total congelado não é mais confiável.
        has_tx = db.query(Transaction.id).filter(Transaction.invoice_id == invoice.id).first() is not None
        if has_tx and invoice_open_total(db, invoice) != Decimal(invoice.total_amount).quantize(CENT):
            raise TransactionError("Total da fatura difere da soma dos lançamentos — informe o valor")
        amount = invoice.total_amount
    amount = to_cents(amount)
    if amount <= 0:
        raise TransactionError("Valor pago deve ser positivo.")
    card = db.get(CreditCardAccount, invoice.credit_card_account_id)
    tx = _new_tx(
        invoice.workspace_id, user_id,
        source_type=TransactionSourceType.CHECKING, checking_account_id=acc.id,
        event_date=paid_on,
        description=f"Pagamento fatura {card.name if card else ''} {invoice.close_date.strftime('%m/%Y')}".strip(),
        amount=-amount, category_id=category_id, paid_invoice_id=invoice.id,
    )
    _fill(db, tx, currency=acc.currency, statement_rate=fx_rate)
    db.add(tx)
    db.flush()
    invoice.status = InvoiceStatus.PAID
    invoice.paid_at = paid_on
    invoice.paid_by_transaction_id = tx.id
    invoice.updated_at = datetime.now(timezone.utc)
    invoice.updated_by = user_id
    db.flush()
    return tx


def link_invoice_payment(
    db: Session, invoice: Invoice, tx: Transaction, *, user_id: str | None = None,
) -> Transaction:
    """Spec 71 — the other half of `pay_invoice`: the payment debit is
    ALREADY in the ledger (statement imported before the card invoice), so
    instead of creating a second debit, mark that tx as the payment.

    Same effects as pay_invoice (tx.paid_invoice_id + invoice PAID with the
    mirror FK, paid_at = tx date). An invoice payment is a transfer, not an
    expense: the tx loses the category/party it got as a plain line."""
    if invoice.status == InvoiceStatus.PAID:
        raise TransactionConflict("Fatura já paga.")
    if invoice.status != InvoiceStatus.CLOSED:
        raise TransactionConflict("Feche a fatura antes de pagar.")
    if tx.workspace_id != invoice.workspace_id:
        raise TransactionError("Movimentação não encontrada.")
    if tx.source_type != TransactionSourceType.CHECKING or tx.amount >= 0:
        raise TransactionError("Pagamento de fatura é um débito de conta corrente.")
    if tx.paid_invoice_id is not None:
        raise TransactionConflict("Essa movimentação já paga outra fatura.")
    if tx.transfer_group_id is not None:
        raise TransactionConflict("Transferência entre contas não pode ser pagamento de fatura.")
    if tx.currency != invoice.currency:
        raise TransactionError("Débito em outra moeda — pague a fatura informando o valor debitado.")
    now = datetime.now(timezone.utc)
    tx.paid_invoice_id = invoice.id
    tx.category_id = None
    tx.party_id = None
    tx.updated_at = now
    tx.updated_by = user_id
    db.flush()
    invoice.status = InvoiceStatus.PAID
    invoice.paid_at = tx.event_date
    invoice.paid_by_transaction_id = tx.id
    invoice.updated_at = now
    invoice.updated_by = user_id
    db.flush()
    return tx


def invoice_open_total(db: Session, invoice: Invoice) -> Decimal:
    """Positive invoice value from its tx: purchases (negative) minus
    refunds/credits (positive)."""
    rows = db.query(Transaction.amount).filter(Transaction.invoice_id == invoice.id).all()
    total = -sum((Decimal(a) for (a,) in rows), Decimal("0"))
    return total.quantize(CENT)
