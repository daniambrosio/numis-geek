"""Spec 71 — classify + apply of a statement (BANK_STATEMENT) or card
invoice (CARD_INVOICE) extraction job.

Rides on the ExtractionJob pipeline (specs 38/48/58): the LLM output lives
in `job.extracted_json`; `_classify_bank_import` turns it into buckets
(read-only — used by both preview and apply, so the review modal shows
exactly what apply will do), and `apply_bank_import` executes the user's
decisions on top of that classification.

Buckets per line:

- **new** — becomes a transaction (`is_reconciled=true`,
  `extraction_job_id` set), party resolved by alias or auto-created;
- **duplicate** — dedup layer 2: fingerprint (or installment match, or an
  existing invoice-payment tx) already in the ledger. Default *skip* when the
  existing tx is already reconciled, *reconcile* when it is a manual tx never
  reconciled (the statement line confirms it). A k-th identical line in the
  same file (2 coffees) also lands here and can be promoted to "importar
  mesmo assim" (fingerprint persisted with suffix `:k`);
- **invoice_payment** — a checking debit matching a CLOSED unpaid invoice
  (±1%, close_date..due_date+10) or the "Pagamento recebido" line on the
  next card invoice. Applied via `transactions.pay_invoice` — never by
  writing PAID / FKs here. The card line never becomes a card tx;
- **scheduled** — settles a PENDING conta a pagar/receber (spec 72 rules:
  ±5% amount, ±5 days of due_date, party via alias or description contains
  the occurrence's; closest date wins). Applied via
  `scheduled_transactions.settle_occurrence`.

Layer 1 (file hash) is enforced at upload; layer 3 (period overlap with a
previous CONFIRMED job of the same account/card) is reported here as a
warning.
"""
from __future__ import annotations

import re
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from numis_geek.models.account import Account, Currency
from numis_geek.models.credit_card import CreditCardAccount, Invoice, InvoiceStatus
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.extraction_job import (
    ExtractionJob, ExtractionSourceHint, ExtractionStatus,
)
from numis_geek.models.party import Party, PartyAlias, PartyKind
from numis_geek.models.scheduled_transaction import (
    ScheduledDirection, ScheduledStatus, ScheduledTransaction,
)
from numis_geek.models.transaction import Transaction, TransactionSourceType
from numis_geek.services import scheduled_transactions as sched_svc
from numis_geek.services import transactions as tx_svc
from numis_geek.services.normalize import normalize_description
from numis_geek.utils.business_day import first_business_day

BANK_HINTS = (ExtractionSourceHint.BANK_STATEMENT, ExtractionSourceHint.CARD_INVOICE)

CENT = Decimal("0.01")
INSTALLMENT_AMOUNT_TOL = Decimal("0.05")     # R$ 0,05 — arredondamento do emissor
INSTALLMENT_DATE_TOL_DAYS = 3
INVOICE_PAYMENT_PCT = Decimal("0.01")        # ±1% (deliberadamente estrito)
INVOICE_PAYMENT_GRACE_DAYS = 10              # até due_date + 10
PAYMENT_TX_DATE_TOL_DAYS = 5                 # débito do extrato × tx de pagamento já criada
# Matcher pontuado de contas a pagar/receber (2026-11-02). Ver _score_scheduled.
SCHED_EARLY_DAYS = 7                         # linha até 7 dias ANTES do vencimento
SCHED_LATE_DAYS = 10                         # … e até 10 dias depois
SCHED_AMOUNT_BAND = Decimal("0.30")          # |valor| a ±30%
SCHED_MIN_SCORE = 0.40                       # abaixo disso nem aparece como candidata
SCHED_CONFIDENT = 0.70                       # "Marcar pago" default a partir daqui…
SCHED_MARGIN = 0.15                          # … e com essa folga sobre a 2ª candidata

_PAYMENT_PREFIXES = ("PAGAMENTO", "PAGTO", "PGTO", "PAG FATURA", "PAG. FATURA")


class BankImportError(Exception):
    """Invalid decisions / state — the route maps to 400."""


# ── helpers ───────────────────────────────────────────────────────────────────

def _local_day(ts: datetime | None) -> date:
    """Dia em America/Sao_Paulo de um timestamp UTC (naive = UTC)."""
    if ts is None:
        return datetime.now(ZoneInfo("America/Sao_Paulo")).date()
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(ZoneInfo("America/Sao_Paulo")).date()


def _parse_date(raw) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _money(raw) -> Decimal | None:
    try:
        return Decimal(str(raw)).quantize(CENT)
    except (InvalidOperation, TypeError, ValueError):
        return None


def _parse_installment(raw) -> tuple[int, int] | None:
    if not raw:
        return None
    try:
        a, b = str(raw).replace(" ", "").split("/", 1)
        x, y = int(a), int(b)
    except ValueError:
        return None
    if y < 2 or not 1 <= x <= y or y > 48:
        return None
    return x, y


def _looks_like_payment(desc: str, amount: Decimal) -> bool:
    norm = normalize_description(desc)
    return amount > 0 and norm.startswith(_PAYMENT_PREFIXES)


def _looks_like_card_payment_debit(desc: str) -> bool:
    """Débito do extrato com cara de pagamento de cartão ("PGTO CARTAO NU",
    "PAGAMENTO FATURA") — usado só pra avisar e não criar fornecedor."""
    norm = normalize_description(desc)
    return "FATURA" in norm or (norm.startswith(_PAYMENT_PREFIXES) and ("CARTAO" in norm or "CARTÃO" in norm))


RATE_Q = Decimal("0.00000001")  # Numeric(18, 8) de transaction.fx_rate


def _rate(raw) -> Decimal | None:
    try:
        r = Decimal(str(raw)).quantize(RATE_Q)
    except (InvalidOperation, TypeError, ValueError):
        return None
    return r if r > 0 else None


def _warn(r: dict, msg: str) -> None:
    r["warning"] = f"{r['warning']} · {msg}" if r.get("warning") else msg


def _within_pct(a: Decimal, b: Decimal, pct: Decimal) -> bool:
    return b > 0 and abs(abs(a) - b) <= b * pct


def _fp_suffix(fp: str) -> int:
    if ":" not in fp:
        return 1
    try:
        return int(fp.split(":", 1)[1])
    except ValueError:
        return 1


def _tx_brief(tx: Transaction) -> dict:
    return {
        "transaction_id": tx.id,
        "event_date": tx.event_date.isoformat(),
        "description": tx.description,
        "amount": str(tx.amount),
        "is_reconciled": tx.is_reconciled,
        "extraction_job_id": tx.extraction_job_id,
    }


def _already_linked(tx: Transaction) -> bool:
    """Conciliada por import anterior (ou marcada à mão) — default skip."""
    return tx.extraction_job_id is not None or tx.is_reconciled


@dataclass
class _Scope:
    job: ExtractionJob
    workspace_id: str
    hint: ExtractionSourceHint
    source_type: TransactionSourceType
    source_id: str
    currency: Currency
    account: Account | None = None
    card: CreditCardAccount | None = None


def _scope(db: Session, job: ExtractionJob) -> _Scope:
    if job.source_hint == ExtractionSourceHint.BANK_STATEMENT:
        acc = db.get(Account, job.checking_account_id) if job.checking_account_id else None
        if acc is None:
            raise BankImportError("Import de extrato sem conta corrente.")
        return _Scope(job, job.workspace_id, job.source_hint, TransactionSourceType.CHECKING,
                      acc.id, acc.currency, account=acc)
    if job.source_hint == ExtractionSourceHint.CARD_INVOICE:
        card = db.get(CreditCardAccount, job.credit_card_account_id) if job.credit_card_account_id else None
        if card is None:
            raise BankImportError("Import de fatura sem cartão.")
        return _Scope(job, job.workspace_id, job.source_hint, TransactionSourceType.CREDIT_CARD,
                      card.id, card.currency, card=card)
    raise BankImportError(f"Hint {job.source_hint.value} não é import de extrato/fatura.")


def statement_period(payload: dict, *, card_invoice: bool = False) -> tuple[date | None, date | None]:
    """Período declarado pelo documento; fallback min/max das linhas.

    Fatura de cartão: o período é o CICLO (fechamento anterior + 1 dia →
    fechamento). A data das linhas parceladas é a da compra original — usá-
    la no min/max abria o período meses pra trás e disparava overlap todo
    mês (audit 2026-10-31)."""
    if card_invoice:
        close = _parse_date((payload.get("invoice") or {}).get("close_date"))
        if close is not None:
            return tx_svc.add_months(close, -1) + timedelta(days=1), close
        dates = [
            d for d, t in ((_parse_date(t.get("event_date")), t) for t in payload.get("transactions") or [])
            if d and not _parse_installment(t.get("installment"))
        ]
        return (min(dates), max(dates)) if dates else (None, None)
    period = payload.get("period") or {}
    start = _parse_date(period.get("start"))
    end = _parse_date(period.get("end"))
    if start is None or end is None:
        dates = [d for d in (_parse_date(t.get("event_date")) for t in payload.get("transactions") or []) if d]
        if dates:
            start = start or min(dates)
            end = end or max(dates)
    if start and end and start > end:
        start, end = end, start
    return start, end


# ── classify ──────────────────────────────────────────────────────────────────

@dataclass
class Classification:
    rows: list[dict]
    invoice: dict | None
    overlaps: list[dict]
    warnings: list[str]
    period: tuple[date | None, date | None]
    # internals for apply
    occurrence_ids: dict[str, list[str]] = field(default_factory=dict)


def _alias_map(db: Session, workspace_id: str) -> dict[str, Party]:
    rows = db.query(PartyAlias, Party).join(Party, Party.id == PartyAlias.party_id).filter(
        PartyAlias.workspace_id == workspace_id,
    ).all()
    return {a.alias_normalized: p for a, p in rows}


# ── party by line kind (decisão do user 2026-11-02: "IOF é o governo,
# tarifas são do banco correspondente, pix tem o recebedor sempre") ────────

IOF_PARTY_NAME = "Receita Federal"
LINE_KINDS = ("PURCHASE", "IOF", "BANK_FEE", "PIX", "TED", "BOLETO", "SALARY", "OTHER")
_FEE_WORDS = ("TARIFA", "ANUIDADE", "CESTA", "ENCARGO", "JUROS", "MULTA")


_DATE_TOKEN = re.compile(r"^\d{1,2}/\d{1,2}(/\d{2,4})?$")


def alias_key(text: str) -> str:
    """Chave de memória de fornecedor/regra: `normalize_description` sem as
    datas no fim ("PIX MARIA N 18/09" → "PIX MARIA N"). Usada pra gravar e
    procurar alias aprendido; o fingerprint continua no normalize puro."""
    tokens = normalize_description(text).split()
    while tokens and _DATE_TOKEN.match(tokens[-1]):
        tokens.pop()
        tokens = normalize_description(" ".join(tokens)).split()
    return " ".join(tokens)


def line_kind_of(desc: str, amount: Decimal, emitted: str | None) -> str | None:
    """Tipo da linha: o do LLM quando válido; senão heurística na descrição."""
    k = (emitted or "").strip().upper()
    if k in LINE_KINDS:
        return k
    tokens = normalize_description(desc).replace(".", " ").replace("/", " ").split()
    if "IOF" in tokens:
        return "IOF"
    if "PIX" in tokens:
        return "PIX"
    if amount < 0 and any(t.startswith(_FEE_WORDS) for t in tokens):
        return "BANK_FEE"
    if tokens and tokens[0] in ("TED", "DOC"):
        return "TED"
    norm = " ".join(tokens)
    if amount < 0 and ("DDA" in tokens or "BOLETO" in tokens or "DEB AUT" in norm
                       or "DEBITO AUTOMATICO" in norm or "PAG TIT" in norm):
        return "BOLETO"
    if amount > 0 and any(t.startswith(("SALARIO", "PROVENTO", "FOLHA")) for t in tokens):
        return "SALARY"
    return None


def _by_alias(alias: str, name: str, aliases: dict[str, Party], source: str) -> dict:
    """Fornecedor por alias estável: ativo → existing; inativo → none + aviso;
    ausente → new (criado no apply com esse nome e alias)."""
    p = aliases.get(alias)
    if p is not None and p.is_active:
        return {"mode": "existing", "party_id": p.id, "party_name": p.name, "alias": alias, "source": source}
    if p is not None:
        return {"mode": "none", "alias": alias, "inactive_party_name": p.name, "source": source}
    return {"mode": "new", "new_party_name": name.strip()[:120], "alias": alias, "source": source,
            "kind": "SUPPLIER" if source in ("iof", "bank_fee") else None}


def _resolve_party(
    desc: str, amount: Decimal, kind: str | None, counterparty: str | None,
    aliases: dict[str, Party], fi_name: str | None,
) -> dict:
    """1. alias da descrição → fornecedor ativo ganha sempre;
    2. IOF → Receita Federal; 3. tarifa/juros do banco → a instituição da
    conta/cartão; 4. contraparte extraída (Pix/TED/boleto); 5. Pix sem
    contraparte → sem fornecedor + aviso; 6. senão, novo pela descrição."""
    alias = alias_key(desc)
    for k in dict.fromkeys((alias, normalize_description(desc))):
        p = aliases.get(k)
        if p is not None and p.is_active:
            return {"mode": "existing", "party_id": p.id, "party_name": p.name, "alias": k, "source": "alias"}
    if kind == "IOF":
        return _by_alias(normalize_description(IOF_PARTY_NAME), IOF_PARTY_NAME, aliases, "iof")
    if kind == "BANK_FEE" and fi_name:
        return _by_alias(normalize_description(fi_name), fi_name, aliases, "bank_fee")
    cp = (counterparty or "").strip()
    if cp and alias_key(cp):
        return _by_alias(alias_key(cp), cp, aliases, "counterparty")
    if kind == "PIX":
        return {"mode": "none", "alias": alias, "source": "pix_unknown",
                "warning": "Pix sem recebedor identificável — escolha o fornecedor/cliente"}
    return _party_for(desc, aliases)


def _party_for(desc: str, aliases: dict[str, Party]) -> dict:
    alias = alias_key(desc)
    p = aliases.get(alias) or aliases.get(normalize_description(desc))
    if p is not None and p.is_active:
        return {"mode": "existing", "party_id": p.id, "party_name": p.name, "alias": alias}
    if p is not None:
        # Alias de fornecedor desativado: sem fornecedor (o alias é único —
        # "criar novo" não teria como apontar pra ele). Preview e apply
        # concordam; o review deixa escolher outro.
        return {"mode": "none", "alias": alias, "inactive_party_name": p.name}
    if not alias:
        return {"mode": "none", "alias": alias}
    return {"mode": "new", "new_party_name": desc.strip()[:120], "alias": alias}


def _default_payment_account(db: Session, card: CreditCardAccount) -> str | None:
    """Última conta corrente (ativa, na moeda do cartão) usada pra pagar
    este cartão."""
    rows = db.query(Transaction.checking_account_id).join(
        Invoice, Invoice.id == Transaction.paid_invoice_id,
    ).filter(
        Invoice.credit_card_account_id == card.id,
        Transaction.checking_account_id.isnot(None),
    ).order_by(Transaction.event_date.desc(), Transaction.created_at.desc()).all()
    for (acc_id,) in rows:
        acc = db.get(Account, acc_id)
        if acc and acc.is_active and acc.currency == card.currency:
            return acc.id
    return None


def _invoice_brief(db: Session, inv: Invoice) -> dict:
    card = db.get(CreditCardAccount, inv.credit_card_account_id)
    return {
        "invoice_id": inv.id,
        "card_id": inv.credit_card_account_id,
        "card_name": card.name if card else None,
        "close_date": inv.close_date.isoformat(),
        "due_date": inv.due_date.isoformat(),
        "total_amount": str(inv.total_amount) if inv.total_amount is not None else None,
        "status": inv.status.value,
        "payment_transaction_id": inv.paid_by_transaction_id,
    }


def _doc_invoice(db: Session, sc: _Scope, payload: dict, line_dates: list[date]) -> tuple[dict | None, list[str]]:
    """CARD_INVOICE: the invoice the document is (close/due/total/iof + the
    existing row it resolves to, if any)."""
    if sc.card is None:
        return None, []
    warnings: list[str] = []
    info = payload.get("invoice") or {}
    close = _parse_date(info.get("close_date"))
    due = _parse_date(info.get("due_date"))
    if close is None:
        base = max(line_dates) if line_dates else date.today()
        close = tx_svc.theoretical_close_date(sc.card, base)
        warnings.append("Fatura sem data de fechamento no documento — usei o fechamento teórico do cartão.")
    if due is None or due < close:
        due = tx_svc.theoretical_due_date(sc.card, close)
    total = _money(info.get("total"))
    iof = _money(info.get("iof_total"))
    if total is not None and total <= 0:
        # Saldo credor (estornos > compras): nada a pagar — nunca vira valor devido.
        if total < 0:
            warnings.append(f"Fatura com saldo credor de {abs(total)} — gravada com total 0 (nada a pagar).")
        total = Decimal("0.00")
    existing = tx_svc.find_invoice_near(db, sc.card, close)
    out = {
        "close_date": close.isoformat(),
        "due_date": due.isoformat(),
        "total_amount": str(total) if total is not None else None,
        "iof_total": str(abs(iof)) if iof is not None else None,
        "existing_invoice_id": existing.id if existing else None,
        "existing_status": existing.status.value if existing else None,
        "blocked": bool(existing and existing.status == InvoiceStatus.PAID),
    }
    if out["blocked"]:
        warnings.append("Fatura já paga — lançamentos novos não entram nela (só conciliação).")
    return out, warnings


def _classify_bank_import(db: Session, job: ExtractionJob, payload: dict | None = None) -> Classification:
    """Read-only. Same input → same output; apply re-runs it."""
    payload = payload if payload is not None else (job.extracted_json or {})
    sc = _scope(db, job)
    warnings: list[str] = []
    aliases = _alias_map(db, sc.workspace_id)
    fi = db.get(FinancialInstitution, (sc.account or sc.card).financial_institution_id)
    fi_name = fi.short_name if fi else None

    # 1. parse lines
    parsed: list[dict] = []
    # Determinístico (apply re-classifica): o dia do upload, não "hoje".
    upload_day = _local_day(job.created_at)
    for i, line in enumerate(payload.get("transactions") or []):
        rid = f"r{i}"
        d = _parse_date(line.get("event_date"))
        amount = _money(line.get("amount"))
        desc = (line.get("description") or "").strip()
        if d is None or amount is None or amount == 0 or not desc:
            warnings.append(f"Linha {i + 1} ignorada (data/valor/descrição inválidos): {desc or '—'}")
            continue
        if d > upload_day:
            # Agendado ("lançamentos futuros" do Itaú): ainda não aconteceu.
            warnings.append(f"Linha {i + 1} ignorada (lançamento futuro, {d.strftime('%d/%m/%Y')}): {desc}")
            continue
        line_ccy = (line.get("currency") or sc.currency.value).upper()
        inst = _parse_installment(line.get("installment")) if sc.card else None
        eff = tx_svc.add_months(d, inst[0] - 1) if inst else d
        fx = line.get("fx") if isinstance(line.get("fx"), dict) else {}
        usd_amount = _money(fx.get("usd_amount")) if fx.get("usd_amount") is not None else None
        fx_rate = _rate(fx.get("rate")) if fx.get("rate") else None
        if sc.currency == Currency.BRL and usd_amount is not None and usd_amount != 0:
            # amount_usd tem que bater com o documento: a taxa sai de BRL/USD
            # com 8 casas, não da cotação arredondada.
            fx_rate = _rate(abs(amount) / abs(usd_amount)) or fx_rate
        is_payment = bool(sc.card) and (bool(line.get("is_invoice_payment")) or _looks_like_payment(desc, amount))
        parsed.append({
            "row_id": rid,
            "index": i,
            "event_date": eff.isoformat(),
            "original_date": d.isoformat(),
            "description": desc[:255],
            "amount": str(amount),
            "currency": sc.currency.value,
            "fx_rate": str(fx_rate) if fx_rate is not None else None,
            "usd_amount": str(usd_amount) if usd_amount is not None else None,
            "line_currency": line_ccy,
            "installment_number": inst[0] if inst else None,
            "installment_total": inst[1] if inst else None,
            "balance_after": str(_money(line.get("balance_after"))) if line.get("balance_after") is not None else None,
            "category_hint": line.get("category_hint"),
            "line_kind": line_kind_of(desc, amount, line.get("line_kind")),
            "counterparty": (line.get("counterparty") or "").strip()[:120] or None,
            "is_invoice_payment": is_payment,
            "_date": eff,
            "_amount": amount,
        })

    line_dates = [r["_date"] for r in parsed if not r["installment_number"]] or [r["_date"] for r in parsed]
    invoice_info, inv_warnings = _doc_invoice(db, sc, payload, line_dates)
    warnings.extend(inv_warnings)

    # 2. existing tx of this source, for dedup
    src_filter = (
        Transaction.checking_account_id == sc.source_id
        if sc.source_type == TransactionSourceType.CHECKING
        else Transaction.credit_card_account_id == sc.source_id
    )
    existing = db.query(Transaction).filter(Transaction.workspace_id == sc.workspace_id, src_filter).all()
    by_base: dict[str, list[Transaction]] = defaultdict(list)
    for t in existing:
        by_base[t.fingerprint.split(":", 1)[0]].append(t)
    for lst in by_base.values():
        lst.sort(key=lambda t: (_fp_suffix(t.fingerprint), t.created_at or datetime.min, t.id))
    used_tx: set[str] = set()
    used_invoices: set[str] = set()
    seen_in_file: dict[str, int] = defaultdict(int)
    default_pay_acc = _default_payment_account(db, sc.card) if sc.card else None

    occ_pool: list[ScheduledTransaction] = []
    if parsed:
        # janela: linha entre due −7 e due +10 (vencimento em feriado/fds)
        lo = min(r["_date"] for r in parsed) - timedelta(days=SCHED_LATE_DAYS)
        hi = max(r["_date"] for r in parsed) + timedelta(days=SCHED_EARLY_DAYS)
        occ_pool = db.query(ScheduledTransaction).filter(
            ScheduledTransaction.workspace_id == sc.workspace_id,
            ScheduledTransaction.status == ScheduledStatus.PENDING,
            ScheduledTransaction.due_date >= lo,
            ScheduledTransaction.due_date <= hi,
        ).all()

    rule_aliases = _rule_aliases(db, occ_pool)
    s1_lines = (job.classification_json or {}).get("lines") or {}
    active_subs = _active_subcategories(db, sc.workspace_id)

    rows: list[dict] = []
    occurrence_ids: dict[str, list[str]] = {}
    pending_sched: list[tuple[dict, list[tuple[float, ScheduledTransaction, list[str]]]]] = []
    for r in parsed:
        d, amount = r["_date"], r["_amount"]
        r["party"] = {"mode": "none"} if r["is_invoice_payment"] else _resolve_party(
            r["description"], amount, r["line_kind"], r["counterparty"], aliases, fi_name,
        )
        r["category_id"] = None
        r["warning"] = None
        r["parent_transaction_id"] = None
        r["group_key"] = alias_key(r["counterparty"]) if r["counterparty"] else alias_key(r["description"])
        _apply_system1(r, s1_lines.get(str(r["index"])), active_subs)
        if r["party"].get("warning"):
            _warn(r, r["party"].pop("warning"))
        if r["party"].get("inactive_party_name"):
            _warn(r, f"Fornecedor/cliente \"{r['party']['inactive_party_name']}\" está inativo — sem fornecedor")

        # ── linha em outra moeda: nunca grava o número na moeda da conta ───
        if r["line_currency"] != sc.currency.value:
            r["fingerprint"] = None
            r["party"] = {"mode": "none"}
            r.update(bucket="blocked", actions=["skip"], default_action="skip")
            _warn(r, f"Linha em {r['line_currency']} numa conta em {sc.currency.value} — não importável; lance à mão com o valor convertido")
            rows.append(r)
            continue

        # ── card "Pagamento recebido" — never a card tx ────────────────────
        if r["is_invoice_payment"]:
            _classify_card_payment_line(
                db, sc, r, used_invoices, default_pay_acc, invoice_info, used_tx,
            )
            rows.append(r)
            continue

        base = tx_svc.compute_fingerprint(sc.source_type, sc.source_id, d, amount, sc.currency, r["description"])
        seen_in_file[base] += 1
        k = seen_in_file[base]
        r["fingerprint"] = base if k == 1 else f"{base}:{k}"
        r["fingerprint_base"] = base
        r["occurrence_in_file"] = k

        dup: Transaction | None = None
        reason = None
        # installment convergence with the composer
        if r["installment_number"]:
            dup = _match_installment(existing, r, used_tx)
            reason = "installment" if dup else None
        if dup is None:
            dup = next((t for t in by_base.get(base, []) if t.id not in used_tx), None)
            reason = "fingerprint" if dup else None
        if dup is None and sc.account is not None and amount < 0:
            dup = _match_payment_tx(existing, r, used_tx)
            reason = "invoice_payment_tx" if dup else None

        if dup is not None:
            used_tx.add(dup.id)
            linked = _already_linked(dup)
            r.update(bucket="duplicate", duplicate={**_tx_brief(dup), "reason": reason},
                     actions=["skip", "import_anyway"] if linked else ["reconcile", "skip", "import_anyway"],
                     default_action="skip" if linked else "reconcile")
            rows.append(r)
            continue
        # k-ésima linha idêntica NO MESMO arquivo sem par no banco: é outro
        # movimento (4 indenizações LATAM de R$ 3.395,41 no mesmo dia) —
        # segue como linha normal e grava com sufixo ":k". Duplicata é só o
        # que já existe no ledger (2026-11-02, 1º import real).

        # ── checking debit paying a CLOSED invoice ─────────────────────────
        if sc.account is not None and amount < 0:
            inv = _match_invoice(db, sc, d, amount, used_invoices)
            if inv is not None:
                used_invoices.add(inv.id)
                r["party"] = {"mode": "none"}
                r.update(bucket="invoice_payment",
                         invoice_payment={**_invoice_brief(db, inv), "kind": "statement_debit",
                                          "payment_account_id": sc.account.id},
                         actions=["pay", "import", "skip"], default_action="pay")
                rows.append(r)
                continue
            if _looks_like_card_payment_debit(r["description"]):
                # Pagamento de cartão sem fatura FECHADA que bata: entra como
                # movimentação comum, mas sem fornecedor automático. Quando a
                # fatura chegar, a linha "Pagamento recebido" oferece vincular
                # este débito (não paga de novo).
                r["party"] = {"mode": "none"}
                _warn(r, "Parece pagamento de fatura, mas nenhuma fatura fechada bate — importe/feche a fatura para vincular")

        # ── settles a conta a pagar/receber: assignment global depois ──────
        cands = _score_scheduled(occ_pool, r, amount, d, sc, rule_aliases,
                                 (s1_lines.get(str(r["index"])) or {}).get("occurrence_id"))
        if cands:
            pending_sched.append((r, cands))
            rows.append(r)
            continue

        r.update(bucket="new", actions=["import", "skip"], default_action="import")
        rows.append(r)

    _assign_occurrences(db, pending_sched, occurrence_ids)

    # new card lines into a PAID invoice can't go in
    if invoice_info and invoice_info["blocked"]:
        for r in rows:
            if r["bucket"] in ("new", "scheduled") or (r["bucket"] == "duplicate" and "import_anyway" in r["actions"]):
                r["actions"] = [a for a in r["actions"] if a not in ("import", "import_anyway", "settle")] or ["skip"]
                if r["default_action"] not in r["actions"]:
                    r["default_action"] = "skip"
                r["warning"] = r["warning"] or "Fatura já paga"

    # installment parent (best-effort) for lines that will be created
    if sc.card is not None:
        for r in rows:
            if r.get("installment_number") and r["installment_number"] > 1:
                parent = _match_installment_parent(existing, r)
                r["parent_transaction_id"] = parent.id if parent else None

    period = (job.statement_period_start, job.statement_period_end)
    if period[0] is None or period[1] is None:
        period = statement_period(payload, card_invoice=sc.card is not None)
    overlaps = _overlaps(db, sc, period, rows)

    for r in rows:
        r.pop("_date", None)
        r.pop("_amount", None)
    return Classification(rows=rows, invoice=invoice_info, overlaps=overlaps, warnings=warnings,
                          period=period, occurrence_ids=occurrence_ids)


def _apply_system1(r: dict, sug: dict | None, active_subs: dict[str, str]) -> None:
    """Categoria sugerida pelo System 1: pré-seleciona com confiança alta;
    abaixo disso fica só como dica (Sem categoria)."""
    if not sug or not sug.get("category_id") or sug["category_id"] not in active_subs:
        return
    from numis_geek.services.bank_classifier import CONFIDENT
    conf = float(sug.get("confidence") or 0)
    r["category_suggestion"] = {
        "category_id": sug["category_id"], "path": active_subs[sug["category_id"]],
        "confidence": conf, "reason": sug.get("reason") or "", "applied": conf >= CONFIDENT,
    }
    if conf >= CONFIDENT:
        r["category_id"] = sug["category_id"]
        r["category_source"] = "system1"


def _active_subcategories(db: Session, workspace_id: str) -> dict[str, str]:
    from numis_geek.services.bank_classifier import category_tree
    return {c["id"]: c["path"] for c in category_tree(db, workspace_id)}


def _rule_aliases(db: Session, pool: list[ScheduledTransaction]) -> dict[str, set[str]]:
    from numis_geek.models.scheduled_transaction import RecurrenceRuleAlias
    rule_ids = {o.recurrence_rule_id for o in pool if o.recurrence_rule_id}
    if not rule_ids:
        return {}
    out: dict[str, set[str]] = defaultdict(set)
    for rid, alias in db.query(RecurrenceRuleAlias.recurrence_rule_id, RecurrenceRuleAlias.alias_normalized).filter(
        RecurrenceRuleAlias.recurrence_rule_id.in_(rule_ids),
    ).all():
        out[rid].add(alias)
    return out


def _assign_occurrences(
    db: Session, pending: list[tuple[dict, list[tuple[float, ScheduledTransaction, list[str]]]]],
    occurrence_ids: dict[str, list[str]],
) -> None:
    """Best-match global: todos os pares (linha, ocorrência) por score
    decrescente; uma linha por ocorrência. "Marcar pago" vira default só com
    score alto E folga sobre a 2ª candidata da linha; senão a linha fica
    "Importar" mostrando as candidatas (o usuário escolhe)."""
    pairs = []
    for r, cands in pending:
        d = date.fromisoformat(r["event_date"])
        for score, o, _ in cands:
            pairs.append((-score, abs((o.due_date - d).days), r["index"], r, o))
    pairs.sort(key=lambda x: (x[0], x[1], x[2]))
    assigned: dict[str, ScheduledTransaction] = {}
    used: set[str] = set()
    for _, _, _, r, o in pairs:
        if r["row_id"] in assigned or o.id in used:
            continue
        assigned[r["row_id"]] = o
        used.add(o.id)
    for r, cands in pending:
        occurrence_ids[r["row_id"]] = [o.id for _, o, _ in cands]
        best = assigned.get(r["row_id"])
        scores = {o.id: (sc_, sig) for sc_, o, sig in cands}
        chosen = best or cands[0][1]
        sched = {
            "occurrence_id": chosen.id,
            "candidates": [{**_occ_brief(db, o), "score": round(sc_, 2), "signals": sig} for sc_, o, sig in cands],
        }
        confident = False
        if best is not None:
            s_best = scores[best.id][0]
            others = [sc_ for sc_, o, _ in cands if o.id != best.id]
            confident = s_best >= SCHED_CONFIDENT and (not others or s_best - max(others) >= SCHED_MARGIN)
        if not confident:
            r.update(bucket="new", scheduled=sched, actions=["import", "settle", "skip"], default_action="import")
            continue
        # Fornecedor vem da conta a pagar/receber (spec 72: a tx herda). Sem
        # alias, nada de criar fornecedor a partir da descrição do banco.
        if r["party"]["mode"] != "existing":
            r["party"] = {"mode": "none", "alias": r["party"].get("alias"), "from_occurrence": True}
        if best.category_id and r.get("category_source") != "user":
            r["category_id"] = best.category_id   # curado pelo usuário na conta
            r["category_source"] = "occurrence"
        r.update(bucket="scheduled", scheduled=sched, actions=["settle", "import", "skip"], default_action="settle")


def _classify_card_payment_line(
    db: Session, sc: _Scope, r: dict, used_invoices: set[str], default_pay_acc: str | None,
    invoice_info: dict | None, used_tx: set[str],
) -> None:
    """"Pagamento recebido" on invoice N+1 → invoice N, the cycle right
    before the document's invoice — never an older one. The amount must
    match N (total, or its payment tx) within ±1%; a second payment line
    for the same N, a partial payment or a missing N → skip + warning.

    N PAID → reconcile its payment tx. N CLOSED → link an existing checking
    debit of that amount (statement imported first) or pay via pay_invoice."""
    r["fingerprint"] = None
    amount = Decimal(r["amount"])
    line_d = date.fromisoformat(r["original_date"])
    doc_close = date.fromisoformat(invoice_info["close_date"]) if invoice_info else line_d
    target = tx_svc.add_months(doc_close, -1)
    exclude = {invoice_info["existing_invoice_id"]} if invoice_info and invoice_info.get("existing_invoice_id") else set()
    cands = [
        i for i in db.query(Invoice).filter(
            Invoice.credit_card_account_id == sc.card.id,
            Invoice.close_date >= target - timedelta(days=12),
            Invoice.close_date <= target + timedelta(days=12),
            Invoice.close_date < doc_close,
        ).all()
        if i.id not in exclude
    ]
    prev = min(cands, key=lambda i: abs((i.close_date - target).days)) if cands else None

    def skip(msg: str, brief: dict | None = None) -> None:
        r.update(bucket="invoice_payment",
                 invoice_payment=brief or {"kind": "card_payment_line", "invoice_id": None},
                 actions=["skip"], default_action="skip")
        _warn(r, msg)

    if prev is None:
        skip("Fatura do ciclo anterior não está no sistema — importe-a antes para registrar o pagamento.")
        return
    brief = {**_invoice_brief(db, prev), "kind": "card_payment_line"}
    if prev.id in used_invoices:
        skip("Pagamento parcial/múltiplo da mesma fatura — confira manualmente.", brief)
        return
    used_invoices.add(prev.id)

    if prev.status == InvoiceStatus.PAID:
        pay_tx = db.get(Transaction, prev.paid_by_transaction_id) if prev.paid_by_transaction_id else None
        if pay_tx is None:
            skip("Fatura já paga sem movimentação de pagamento ligada.", brief)
            return
        brief["payment_transaction"] = _tx_brief(pay_tx)
        if not _within_pct(amount, abs(Decimal(pay_tx.amount)), INVOICE_PAYMENT_PCT):
            skip("Valor diferente do pagamento registrado — confira manualmente.", brief)
            return
        linked = _already_linked(pay_tx)
        r.update(bucket="invoice_payment", invoice_payment=brief,
                 actions=["skip"] if pay_tx.extraction_job_id else ["reconcile", "skip"],
                 default_action="skip" if linked else "reconcile")
        return
    if prev.status != InvoiceStatus.CLOSED:
        skip("Fatura anterior ainda aberta — feche-a para registrar o pagamento.", brief)
        return
    total = Decimal(prev.total_amount) if prev.total_amount is not None else Decimal("0")
    if not _within_pct(amount, total, INVOICE_PAYMENT_PCT):
        skip("Pagamento parcial ou valor diferente do total da fatura — confira manualmente.", brief)
        return

    # statement imported first: an unlinked debit of this payment already exists
    debit = _match_unlinked_debit(db, sc, prev, amount, line_d, used_tx)
    if debit is not None:
        used_tx.add(debit.id)
        r.update(bucket="invoice_payment", invoice_payment={**brief, "existing_debit": _tx_brief(debit),
                                                            "payment_account_id": debit.checking_account_id},
                 actions=["link", "skip"], default_action="link")
        return
    r.update(bucket="invoice_payment",
             invoice_payment={**brief, "payment_account_id": default_pay_acc},
             actions=["pay", "skip"], default_action="pay" if default_pay_acc else "skip")
    if not default_pay_acc:
        _warn(r, "Escolha a conta de onde saiu o pagamento.")


def _match_unlinked_debit(
    db: Session, sc: _Scope, inv: Invoice, amount: Decimal, d: date, used: set[str],
) -> Transaction | None:
    """Débito de conta corrente (moeda da fatura) com o valor do pagamento,
    perto da data, que ainda não paga fatura nenhuma nem é transferência."""
    rows = db.query(Transaction).join(Account, Account.id == Transaction.checking_account_id).filter(
        Transaction.workspace_id == sc.workspace_id,
        Transaction.source_type == TransactionSourceType.CHECKING,
        Account.currency == inv.currency,
        Transaction.paid_invoice_id.is_(None),
        Transaction.transfer_group_id.is_(None),
        Transaction.amount < 0,
        Transaction.event_date >= d - timedelta(days=PAYMENT_TX_DATE_TOL_DAYS),
        Transaction.event_date <= d + timedelta(days=PAYMENT_TX_DATE_TOL_DAYS),
    ).all()
    cands = [t for t in rows if t.id not in used and abs(abs(Decimal(t.amount)) - abs(amount)) <= CENT]
    cands.sort(key=lambda t: abs((t.event_date - d).days))
    return cands[0] if cands else None


def _match_installment(existing: list[Transaction], r: dict, used: set[str]) -> Transaction | None:
    norm = normalize_description(r["description"])
    amount = Decimal(r["amount"])
    d = date.fromisoformat(r["event_date"])
    cands = [
        t for t in existing
        if t.id not in used
        and t.installment_number == r["installment_number"]
        and t.installment_total == r["installment_total"]
        and normalize_description(t.description) == norm
        and abs(Decimal(t.amount) - amount) <= INSTALLMENT_AMOUNT_TOL
        and abs((t.event_date - d).days) <= INSTALLMENT_DATE_TOL_DAYS
    ]
    cands.sort(key=lambda t: (abs((t.event_date - d).days), abs(Decimal(t.amount) - amount)))
    return cands[0] if cands else None


def _match_installment_parent(existing: list[Transaction], r: dict) -> Transaction | None:
    """Parcela 1/Y da mesma compra (mesma descrição normalizada, valor
    ±R$ 0,05, data original ±3 dias); ou o parent de uma irmã já ligada."""
    norm = normalize_description(r["description"])
    amount = Decimal(r["amount"])
    original = date.fromisoformat(r["original_date"])
    y = r["installment_total"]
    for t in existing:
        if (t.installment_total != y or not t.installment_number
                or normalize_description(t.description) != norm
                or abs(Decimal(t.amount) - amount) > INSTALLMENT_AMOUNT_TOL):
            continue
        t_original = tx_svc.add_months(t.event_date, -(t.installment_number - 1))
        if abs((t_original - original).days) > INSTALLMENT_DATE_TOL_DAYS:
            continue
        if t.installment_number == 1:
            return t
        if t.parent_transaction_id:
            parent = next((p for p in existing if p.id == t.parent_transaction_id), None)
            if parent is not None:
                return parent
    return None


def _match_payment_tx(existing: list[Transaction], r: dict, used: set[str]) -> Transaction | None:
    """A checking debit for an invoice already paid via `pay_invoice` (e.g.
    created from the card's next invoice): the descriptions differ, so the
    fingerprint can't see it — match by amount + date."""
    amount = Decimal(r["amount"])
    d = date.fromisoformat(r["event_date"])
    cands = [
        t for t in existing
        if t.id not in used and t.paid_invoice_id
        and abs(Decimal(t.amount) - amount) <= CENT
        and abs((t.event_date - d).days) <= PAYMENT_TX_DATE_TOL_DAYS
    ]
    cands.sort(key=lambda t: abs((t.event_date - d).days))
    return cands[0] if cands else None


def _match_invoice(db: Session, sc: _Scope, d: date, amount: Decimal, used: set[str]) -> Invoice | None:
    value = abs(amount)
    invs = db.query(Invoice).filter(
        Invoice.workspace_id == sc.workspace_id,
        Invoice.status == InvoiceStatus.CLOSED,
        Invoice.currency == sc.currency,
        Invoice.total_amount.isnot(None),
        Invoice.total_amount > 0,
        Invoice.close_date <= d,
        Invoice.due_date >= d - timedelta(days=INVOICE_PAYMENT_GRACE_DAYS),
    ).all()
    cands = [
        i for i in invs
        if i.id not in used
        and abs(value - Decimal(i.total_amount)) <= Decimal(i.total_amount) * INVOICE_PAYMENT_PCT
    ]
    cands.sort(key=lambda i: (abs((i.due_date - d).days), abs(value - Decimal(i.total_amount))))
    return cands[0] if cands else None


def _occ_brief(db: Session, o: ScheduledTransaction) -> dict:
    party = db.get(Party, o.party_id) if o.party_id else None
    return {
        # regra MONTHLY/YEARLY: quitar com outro valor atualiza o previsto
        "learns_amount": sched_svc.learns_amount(db, o),
        "party_name": party.name if party and party.is_active else None,
        "occurrence_id": o.id,
        "description": o.description,
        "due_date": o.due_date.isoformat(),
        "amount": str(o.amount),
        "currency": o.currency.value,
        "direction": o.direction.value,
        "category_id": o.category_id,
        "party_id": o.party_id,
    }


def _score_scheduled(
    pool: list[ScheduledTransaction], r: dict, amount: Decimal, d: date, sc: "_Scope",
    rule_aliases: dict[str, set[str]], s1_occurrence_id: str | None,
) -> list[tuple[float, ScheduledTransaction, list[str]]]:
    """Matcher pontuado de contas a pagar/receber (2026-11-02: "valores
    flutuam mês a mês e datas mudam quando o vencimento cai em
    feriado/fim de semana").

    Restrições duras: sentido, moeda, linha entre due −7 e due +10 dias,
    |valor| a ±30%. Pontos: proximidade de valor (0–0,25) e de data (0–0,25,
    vencimento rolado pro próximo dia útil conta como exato), alias aprendido
    da regra (+0,5), fornecedor (+0,35), descrição contém a da conta (+0,35),
    System 1 apontou esta conta (+0,3), conta esperada (+0,1 / −0,15),
    tipo de linha compatível (+0,1). Devolve candidatas ≥ SCHED_MIN_SCORE,
    da melhor pra pior."""
    direction = ScheduledDirection.PAYABLE if amount < 0 else ScheduledDirection.RECEIVABLE
    norm = normalize_description(r["description"])
    keys = {k for k in (alias_key(r["description"]), alias_key(r.get("counterparty") or "")) if k}
    party_id = r["party"].get("party_id") if r["party"]["mode"] == "existing" else None
    kind = r.get("line_kind")
    value = abs(amount)
    out = []
    for o in pool:
        if o.direction != direction or o.currency != sc.currency:
            continue
        lag = (d - o.due_date).days            # >0: pago depois do vencimento
        if lag < -SCHED_EARLY_DAYS or lag > SCHED_LATE_DAYS:
            continue
        expected = Decimal(o.amount)
        if expected <= 0 or abs(value - expected) > expected * SCHED_AMOUNT_BAND:
            continue
        sig: list[str] = []
        rel = float(abs(value - expected) / expected)
        score = 0.25 * (1 - rel / float(SCHED_AMOUNT_BAND))
        if rel == 0:
            sig.append("valor exato")
        rolled = first_business_day(o.due_date)
        days = min(abs((d - o.due_date).days), abs((d - rolled).days))
        score += 0.25 * max(0.0, 1 - days / 10)
        if days == 0:
            sig.append("data do vencimento" if d == o.due_date else "próximo dia útil")
        if o.recurrence_rule_id and keys & rule_aliases.get(o.recurrence_rule_id, set()):
            score += 0.5
            sig.append("já quitou esta conta antes")
        if party_id and o.party_id == party_id:
            score += 0.35
            sig.append("mesmo fornecedor")
        occ_norm = normalize_description(o.description)
        if occ_norm and occ_norm in norm:
            score += 0.35
            sig.append("descrição")
        if s1_occurrence_id == o.id:
            score += 0.3
            sig.append("sugerida pela IA")
        if o.expected_account_id and sc.account is not None:
            if o.expected_account_id == sc.account.id:
                score += 0.1
                sig.append("conta esperada")
            else:
                score -= 0.15
        if (direction == ScheduledDirection.PAYABLE and kind == "BOLETO") or (
            direction == ScheduledDirection.RECEIVABLE and kind == "SALARY"
        ):
            score += 0.1
            sig.append("tipo de lançamento")
        if score >= SCHED_MIN_SCORE:
            out.append((score, o, sig))
    out.sort(key=lambda x: (-x[0], abs((x[1].due_date - d).days)))
    return out[:5]


def _overlaps(db: Session, sc: _Scope, period: tuple[date | None, date | None], rows: list[dict]) -> list[dict]:
    start, end = period
    if start is None or end is None:
        return []
    col = (ExtractionJob.checking_account_id if sc.account is not None else ExtractionJob.credit_card_account_id)
    jobs = db.query(ExtractionJob).filter(
        ExtractionJob.workspace_id == sc.workspace_id,
        col == sc.source_id,
        ExtractionJob.status == ExtractionStatus.CONFIRMED,
        ExtractionJob.id != sc.job.id,
        ExtractionJob.statement_period_start.isnot(None),
        ExtractionJob.statement_period_end.isnot(None),
        ExtractionJob.statement_period_start <= end,
        ExtractionJob.statement_period_end >= start,
    ).order_by(ExtractionJob.statement_period_start).all()
    out = []
    for j in jobs:
        lo, hi = max(start, j.statement_period_start), min(end, j.statement_period_end)
        n = sum(
            1 for r in rows
            if r["bucket"] == "duplicate" and r.get("duplicate", {}).get("transaction_id")
            and lo <= date.fromisoformat(r["event_date"]) <= hi
        )
        out.append({
            "job_id": j.id,
            "start": j.statement_period_start.isoformat(),
            "end": j.statement_period_end.isoformat(),
            "duplicate_count": n,
        })
    return out


def preview_payload(c: Classification) -> dict:
    counts: dict[str, int] = defaultdict(int)
    for r in c.rows:
        counts[r["bucket"]] += 1
    return {
        "rows": c.rows,
        "invoice": c.invoice,
        "overlaps": c.overlaps,
        "warnings": c.warnings,
        "period": {
            "start": c.period[0].isoformat() if c.period[0] else None,
            "end": c.period[1].isoformat() if c.period[1] else None,
        },
        "counts": dict(counts),
    }


# ── apply ─────────────────────────────────────────────────────────────────────

@dataclass
class ApplyOutcome:
    created: list[str] = field(default_factory=list)
    reconciled: list[str] = field(default_factory=list)
    skipped: int = 0
    paid_invoices: list[dict] = field(default_factory=list)
    settled: list[dict] = field(default_factory=list)
    new_parties: list[str] = field(default_factory=list)
    invoice_id: str | None = None
    learned: list[dict] = field(default_factory=list)
    aliases: list[dict] = field(default_factory=list)


def _resolve_doc_invoice(db: Session, sc: _Scope, info: dict, user_id: str | None) -> Invoice:
    close = date.fromisoformat(info["close_date"])
    due = date.fromisoformat(info["due_date"])
    inv = tx_svc.find_invoice_near(db, sc.card, close)
    if inv is None:
        inv = tx_svc.invoice_for_close(db, sc.card, close, user_id=user_id)
    if inv.status != InvoiceStatus.PAID:
        clash = db.query(Invoice.id).filter(
            Invoice.credit_card_account_id == sc.card.id, Invoice.close_date == close, Invoice.id != inv.id,
        ).first()
        if not clash:
            inv.close_date = close
        inv.due_date = due
        inv.updated_at = datetime.now(timezone.utc)
        inv.updated_by = user_id
        db.flush()
    return inv


def _finalize_doc_invoice(db: Session, inv: Invoice, info: dict, user_id: str | None) -> None:
    """Total/IOF do documento + CLOSED (fatura importada = fechada)."""
    if inv.status == InvoiceStatus.PAID:
        return
    if info.get("total_amount") is not None:
        inv.total_amount = Decimal(info["total_amount"])
    elif inv.total_amount is None:
        inv.total_amount = tx_svc.invoice_open_total(db, inv)
    if info.get("iof_total") is not None:
        inv.iof_total = Decimal(info["iof_total"])
    inv.status = InvoiceStatus.CLOSED
    inv.updated_at = datetime.now(timezone.utc)
    inv.updated_by = user_id
    db.flush()


def _alias_row(db: Session, workspace_id: str, key: str) -> PartyAlias | None:
    if not key:
        return None
    return db.query(PartyAlias).filter(
        PartyAlias.workspace_id == workspace_id, PartyAlias.alias_normalized == key,
    ).first()


def _get_or_create_party(
    db: Session, workspace_id: str, name: str, alias: str, amount: Decimal,
    cache: dict[str, str | None], out: ApplyOutcome, user_id: str | None,
    kind: PartyKind | None = None,
) -> str | None:
    """Fornecedor do alias (ativo) ou um novo com o alias. Alias de
    fornecedor INATIVO → None (sem fornecedor), igual ao preview."""
    key = alias or normalize_description(name)
    if key in cache:
        return cache[key]
    existing = _alias_row(db, workspace_id, key)
    if existing is not None:
        p = db.get(Party, existing.party_id)
        cache[key] = p.id if p is not None and p.is_active else None
        return cache[key]
    pid = _new_party(db, workspace_id, name, key, amount, out, user_id, kind)
    cache[key] = pid
    return pid


def _named_party(
    db: Session, workspace_id: str, name: str, alias: str, amount: Decimal,
    cache: dict[str, str | None], out: ApplyOutcome, user_id: str | None,
) -> str:
    """Decisão explícita `new_party_name`: SEMPRE um fornecedor com esse
    nome (reaproveitado se o mesmo nome já foi pedido neste import). Leva o
    alias só se ele estiver livre — nunca rouba o alias de outro."""
    key = "name:" + normalize_description(name)
    if cache.get(key):
        return cache[key]  # type: ignore[return-value]
    free = alias if alias and _alias_row(db, workspace_id, alias) is None and alias not in cache else ""
    pid = _new_party(db, workspace_id, name, free, amount, out, user_id)
    cache[key] = pid
    if free:
        cache[free] = pid
    elif alias:
        # escolha explícita do usuário: o texto passa a apontar pro novo
        _remember_party_alias(db, workspace_id, alias, pid, out)
    return pid


def _remember_party_alias(db: Session, workspace_id: str, key: str, party_id: str, out: "ApplyOutcome") -> None:
    """Memória de fornecedor (2026-11-02): o usuário escolheu/criou o
    fornecedor desta linha → alias(texto sem datas) aponta pra ele, e a
    próxima "PIX MARIA N 02/10" já vem como "Maria (diarista)". Escolha
    explícita ganha de um alias anterior (re-aponta)."""
    if not key:
        return
    row = _alias_row(db, workspace_id, key)
    if row is None:
        db.add(PartyAlias(id=str(uuid.uuid4()), workspace_id=workspace_id, party_id=party_id,
                          alias_normalized=key, created_at=datetime.now(timezone.utc)))
        out.aliases.append({"alias": key, "party_id": party_id, "previous_party_id": None})
    elif row.party_id != party_id:
        out.aliases.append({"alias": key, "party_id": party_id, "previous_party_id": row.party_id})
        row.party_id = party_id
    db.flush()


def _new_party(
    db: Session, workspace_id: str, name: str, key: str, amount: Decimal, out: ApplyOutcome, user_id: str | None,
    kind: PartyKind | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    p = Party(
        id=str(uuid.uuid4()), workspace_id=workspace_id, name=name.strip()[:120],
        kind=kind or (PartyKind.SUPPLIER if amount < 0 else PartyKind.CLIENT), is_active=True,
        created_at=now, updated_at=now, created_by=user_id, updated_by=user_id,
    )
    db.add(p)
    db.flush()
    if key:
        db.add(PartyAlias(id=str(uuid.uuid4()), workspace_id=workspace_id, party_id=p.id,
                          alias_normalized=key, created_at=now))
        db.flush()
    out.new_parties.append(p.id)
    return p.id


def _free_suffix(db: Session, workspace_id: str, base: str, start: int, taken: set[str]) -> str:
    k = max(start, 2)
    while True:
        fp = f"{base}:{k}"
        if fp not in taken and not db.query(Transaction.id).filter(
            Transaction.workspace_id == workspace_id, Transaction.fingerprint == fp,
        ).first():
            taken.add(fp)
            return fp
        k += 1


def _mark_reconciled(tx: Transaction, job: ExtractionJob, user_id: str | None) -> None:
    tx.is_reconciled = True
    if tx.extraction_job_id is None:  # re-conciliação não sobrescreve
        tx.extraction_job_id = job.id
    tx.updated_at = datetime.now(timezone.utc)
    tx.updated_by = user_id


def apply_bank_import(
    db: Session, job: ExtractionJob, decisions: dict | None, *, user_id: str | None,
) -> tuple[ApplyOutcome, Classification]:
    """Execute the classification with the user's per-row decisions.
    Raises BankImportError on any invalid decision — caller rolls back
    (apply is all-or-nothing)."""
    decisions = decisions or {}
    c = _classify_bank_import(db, job)
    sc = _scope(db, job)
    by_id = {r["row_id"]: r for r in c.rows}
    unknown = set(decisions) - set(by_id)
    if unknown:
        raise BankImportError(f"Linhas desconhecidas: {', '.join(sorted(unknown))}.")

    out = ApplyOutcome()
    doc_invoice: Invoice | None = None
    if sc.card is not None and c.invoice is not None:
        doc_invoice = _resolve_doc_invoice(db, sc, c.invoice, user_id)
        out.invoice_id = doc_invoice.id

    party_cache: dict[str, str | None] = {}
    chosen_occ: set[str] = set()
    taken_fps: set[str] = set()

    for r in c.rows:
        dec = decisions.get(r["row_id"]) or {}
        action = dec.get("action") or r["default_action"]
        if action not in r["actions"]:
            raise BankImportError(f"Ação '{action}' inválida para a linha {r['index'] + 1} ({r['description']}).")
        if action == "skip":
            out.skipped += 1
            continue

        if action == "reconcile":
            if r["bucket"] == "invoice_payment":
                tx = db.get(Transaction, r["invoice_payment"]["payment_transaction"]["transaction_id"])
            else:
                tx = db.get(Transaction, r["duplicate"]["transaction_id"])
            _mark_reconciled(tx, job, user_id)
            out.reconciled.append(tx.id)
            continue

        if action == "pay":
            ip = r["invoice_payment"]
            inv = db.get(Invoice, ip["invoice_id"])
            acc_id = dec.get("payment_account_id") or ip.get("payment_account_id")
            if not acc_id:
                raise BankImportError(f"Escolha a conta de origem do pagamento da fatura ({r['description']}).")
            if ip["kind"] == "statement_debit" and acc_id != sc.source_id:
                raise BankImportError("Débito do extrato paga a fatura a partir desta conta.")
            acc = db.get(Account, acc_id)
            if acc is None or acc.workspace_id != sc.workspace_id:
                raise BankImportError("Conta de origem do pagamento não encontrada.")
            if acc.currency != inv.currency:
                raise BankImportError(
                    f"Conta {acc.name} em {acc.currency.value} e fatura em {inv.currency.value} — pague pela "
                    "tela de faturas informando o valor debitado na conta."
                )
            try:
                tx = tx_svc.pay_invoice(
                    db, inv, checking_account_id=acc_id, paid_on=date.fromisoformat(r["event_date"]),
                    amount=abs(Decimal(r["amount"])), category_id=dec.get("category_id"), user_id=user_id,
                )
            except (tx_svc.TransactionError, tx_svc.TransactionConflict) as exc:
                raise BankImportError(f"{r['description']}: {exc}")
            _mark_reconciled(tx, job, user_id)
            out.created.append(tx.id)
            out.paid_invoices.append({"invoice_id": inv.id, "transaction_id": tx.id, "amount": str(-tx.amount),
                                      "paid_on": r["event_date"], "checking_account_id": acc_id})
            continue

        if action == "link":
            ip = r["invoice_payment"]
            inv = db.get(Invoice, ip["invoice_id"])
            debit = db.get(Transaction, ip["existing_debit"]["transaction_id"])
            try:
                tx_svc.link_invoice_payment(db, inv, debit, user_id=user_id)
            except (tx_svc.TransactionError, tx_svc.TransactionConflict) as exc:
                raise BankImportError(f"{r['description']}: {exc}")
            _mark_reconciled(debit, job, user_id)
            out.reconciled.append(debit.id)
            out.paid_invoices.append({"invoice_id": inv.id, "transaction_id": debit.id, "amount": str(-debit.amount),
                                      "paid_on": debit.event_date.isoformat(),
                                      "checking_account_id": debit.checking_account_id, "linked": True})
            continue

        # import / import_anyway / settle → create the tx
        tx = _create_from_row(db, sc, job, r, dec, doc_invoice, party_cache, out, taken_fps, user_id)
        out.created.append(tx.id)

        if action == "settle":
            occ_id = dec.get("occurrence_id") or r["scheduled"]["occurrence_id"]
            if occ_id not in c.occurrence_ids.get(r["row_id"], []):
                raise BankImportError(f"Conta a pagar/receber inválida para a linha {r['index'] + 1}.")
            if occ_id in chosen_occ:
                raise BankImportError("A mesma conta a pagar/receber foi escolhida para duas linhas.")
            chosen_occ.add(occ_id)
            occ = db.get(ScheduledTransaction, occ_id)
            inherited: dict = {}
            try:
                sched_svc.settle_occurrence(db, occ, tx, user_id=user_id, inherited=inherited)
            except (sched_svc.ScheduleError, sched_svc.ScheduleConflict) as exc:
                raise BankImportError(f"{r['description']}: {exc}")
            out.settled.append({"occurrence_id": occ.id, "transaction_id": tx.id,
                                "paid_at": occ.paid_at.isoformat(), "inherited": inherited})
            sched_svc.remember_rule_alias(db, occ, r["group_key"])
            learned = sched_svc.learn_amount_from_payment(db, occ, tx, user_id=user_id)
            if learned:
                out.learned.append(learned)

    if doc_invoice is not None:
        _finalize_doc_invoice(db, doc_invoice, c.invoice, user_id)
    db.flush()
    return out, c


def _create_from_row(
    db: Session, sc: _Scope, job: ExtractionJob, r: dict, dec: dict, doc_invoice: Invoice | None,
    party_cache: dict[str, str], out: ApplyOutcome, taken_fps: set[str], user_id: str | None,
) -> Transaction:
    amount = Decimal(r["amount"])
    # party: decision overrides the classification
    party_id: str | None = None
    if dec.get("no_party"):
        party_id = None
    elif dec.get("party_id"):
        party_id = dec["party_id"]
        _remember_party_alias(db, sc.workspace_id, r["group_key"], party_id, out)
    elif dec.get("new_party_name") and dec["new_party_name"].strip():
        name = dec["new_party_name"].strip()
        party_id = _named_party(db, sc.workspace_id, name, r["group_key"] or r["party"].get("alias") or "",
                                amount, party_cache, out, user_id)
    elif (dec.get("action") or r["default_action"]) == "settle" and r["party"]["mode"] in ("new", "none"):
        # quitar herda o fornecedor da ocorrência escolhida (settle_occurrence)
        party_id = None
    elif r["party"].get("from_occurrence"):
        # quita conta a pagar/receber: settle_occurrence herda o fornecedor
        # da ocorrência escolhida (qualquer candidata)
        party_id = None
    elif r["party"]["mode"] == "existing":
        party_id = r["party"]["party_id"]
    elif r["party"]["mode"] == "new":
        party_id = _get_or_create_party(
            db, sc.workspace_id, r["party"]["new_party_name"], r["party"]["alias"], amount, party_cache, out,
            user_id, PartyKind(r["party"]["kind"]) if r["party"].get("kind") else None,
        )

    data = tx_svc.TxInput(
        source_type=sc.source_type,
        event_date=date.fromisoformat(r["event_date"]),
        description=r["description"],
        amount=amount,
        checking_account_id=sc.source_id if sc.account is not None else None,
        credit_card_account_id=sc.source_id if sc.card is not None else None,
        invoice_id=doc_invoice.id if doc_invoice is not None else None,
        fx_rate=Decimal(r["fx_rate"]) if r.get("fx_rate") else None,
        # decisão explícita (inclusive "Sem categoria" = null) ganha da sugestão
        category_id=dec["category_id"] if "category_id" in dec else r.get("category_id"),
        party_id=party_id,
        is_reconciled=True,
    )
    try:
        tx = tx_svc.create_transaction(db, sc.workspace_id, data, user_id=user_id)[0]
    except (tx_svc.TransactionError, tx_svc.TransactionConflict) as exc:
        raise BankImportError(f"Linha {r['index'] + 1} ({r['description']}): {exc}")
    tx.extraction_job_id = job.id
    if r.get("installment_number"):
        tx.installment_number = r["installment_number"]
        tx.installment_total = r["installment_total"]
        if r.get("parent_transaction_id"):
            tx.parent_transaction_id = r["parent_transaction_id"]
    # k-ésima linha idêntica (ou promovida sobre uma duplicata): sufixo ":k"
    base = r["fingerprint_base"]
    if r["bucket"] == "duplicate" or (r.get("occurrence_in_file") or 1) >= 2 or tx.fingerprint in taken_fps:
        tx.fingerprint = _free_suffix(db, sc.workspace_id, base, r.get("occurrence_in_file") or 2, taken_fps)
    else:
        taken_fps.add(tx.fingerprint)
    db.flush()
    return tx
