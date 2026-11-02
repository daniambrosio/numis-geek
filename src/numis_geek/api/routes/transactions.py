"""Spec 70 — Transactions (Movimentações) API.

Thin layer over `services/transactions.py`: workspace scoping, request
parsing, hydration of display names and audit. Any workspace user
writes (same rule as asset movements); sysadmin passes `workspace_id`.
"""
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from numis_geek.api.deps import get_current_user, get_db
from numis_geek.api.fields import BoundedDate, Money, Rate
from numis_geek.models.account import Account
from numis_geek.models.asset import Asset
from numis_geek.models.asset_movement import AssetMovement
from numis_geek.models.attachment import Attachment
from numis_geek.models.extraction_job import ExtractionJob
from numis_geek.models.category import Category
from numis_geek.models.credit_card import CreditCardAccount
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.party import Party
from numis_geek.models.tag import Tag
from numis_geek.models.transaction import Transaction, TransactionSourceType, transaction_tag
from numis_geek.models.user import User, UserRole
from numis_geek.services import account_balance
from numis_geek.services import asset_payments
from numis_geek.services import transactions as svc
from numis_geek.services.bank_import import is_projected
from numis_geek.services.audit import AuditService
from numis_geek.services.auth import UserContext

router = APIRouter(prefix="/transactions", tags=["transactions"])


# ── schemas ───────────────────────────────────────────────────────────────────

class TagRef(BaseModel):
    id: str
    name: str


class TransactionOut(BaseModel):
    id: str
    workspace_id: str
    source_type: str
    checking_account_id: str | None
    account_name: str | None
    credit_card_account_id: str | None
    card_name: str | None
    financial_institution_name: str | None
    fi_logo_slug: str | None
    invoice_id: str | None
    event_date: str
    description: str
    amount: float
    currency: str
    fx_rate: float
    fx_source: str
    amount_brl: float
    amount_usd: float
    category_id: str | None
    category_name: str | None
    category_parent_name: str | None
    category_color: str | None
    category_kind: str | None
    party_id: str | None
    party_name: str | None
    tags: list[TagRef]
    installment_number: int | None
    installment_total: int | None
    parent_transaction_id: str | None
    paid_invoice_id: str | None
    transfer_group_id: str | None
    # Spec 83 — pago/recebido com ativo.
    asset_movement_id: str | None = None
    asset_id: str | None = None
    asset_name: str | None = None
    asset_ticker: str | None = None
    asset_quantity: float | None = None
    is_reconciled: bool
    # Spec 71 — rastreabilidade arquivo → transação.
    extraction_job_id: str | None = None
    source_attachment_id: str | None = None
    source_attachment_filename: str | None = None
    # Spec 71 — valor/moeda originais de linha convertida pela PTAX
    original_amount: float | None = None
    original_currency: str | None = None
    # Spec 71 — parcela futura gerada pelo import de fatura, ainda não confirmada
    is_projected: bool = False
    notes: str | None
    created_at: str
    updated_at: str


class TransactionListOut(BaseModel):
    items: list[TransactionOut]
    total: int
    page: int
    page_size: int


class MoneyPair(BaseModel):
    brl: float
    usd: float


class TransactionSummaryOut(BaseModel):
    inflows: MoneyPair
    outflows: MoneyPair
    net: MoneyPair
    unreconciled_count: int
    count: int


class TransactionCreateRequest(BaseModel):
    source_type: TransactionSourceType
    checking_account_id: str | None = None
    credit_card_account_id: str | None = None
    invoice_id: str | None = None
    event_date: BoundedDate
    description: str
    amount: Money
    fx_rate: Rate | None = None
    category_id: str | None = None
    party_id: str | None = None
    tag_ids: list[str] | None = None
    notes: str | None = None
    installments: int = 1


class TransactionUpdateRequest(BaseModel):
    event_date: BoundedDate | None = None
    description: str | None = None
    amount: Money | None = None
    fx_rate: Rate | None = None
    category_id: str | None = None
    party_id: str | None = None
    tag_ids: list[str] | None = None
    notes: str | None = None
    is_reconciled: bool | None = None
    # Spec 83 — só em tx ASSET.
    asset_quantity: Decimal | None = None


class AssetPaymentRequest(BaseModel):
    """Spec 83 — despesa paga com ativo (EXPENSE → SELL) ou receita recebida
    em ativo (INCOME → BUY). `amount` positivo, na moeda do ativo."""
    direction: str
    asset_id: str
    event_date: BoundedDate
    quantity: Decimal | None = None
    amount: Money
    description: str
    category_id: str | None = None
    party_id: str | None = None
    tag_ids: list[str] | None = None
    notes: str | None = None


class TransferRequest(BaseModel):
    from_account_id: str
    to_account_id: str
    event_date: BoundedDate
    amount_out: Money
    amount_in: Money | None = None
    description: str = "Transferência entre contas"
    category_id: str | None = None
    notes: str | None = None


# ── helpers ───────────────────────────────────────────────────────────────────

def _resolve_ws(current_user: UserContext, workspace_id: str | None) -> str:
    if current_user.role == UserRole.sysadmin:
        target = workspace_id or current_user.workspace_id
        if not target:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="workspace_id required for sysadmin.")
        return target
    return current_user.workspace_id


def _get_or_404(db: Session, tx_id: str, current_user: UserContext) -> Transaction:
    tx = db.get(Transaction, tx_id)
    if not tx or (current_user.role != UserRole.sysadmin and tx.workspace_id != current_user.workspace_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Transaction not found.")
    return tx


def _translate(exc: Exception) -> HTTPException:
    if isinstance(exc, svc.TransactionConflict):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


def _audit(db: Session, current_user: UserContext, action: str, rows: list[Transaction], extra: dict | None = None) -> None:
    actor = db.get(User, current_user.user_id)
    first = rows[0]
    details = {
        "description": first.description,
        "event_date": first.event_date.isoformat(),
        "amount": str(first.amount),
        "currency": first.currency.value,
        "source_type": first.source_type.value,
        "count": len(rows),
        "ids": [r.id for r in rows],
    }
    if extra:
        details.update(extra)
    AuditService(db).log(
        user_email=actor.email if actor else current_user.user_id,
        action=action,
        resource_type="transaction",
        resource_id=first.id,
        details=details,
        workspace_id=first.workspace_id,
    )


def _audit_payment_reverted(
    db: Session, current_user: UserContext, occurrences: list, ws_id: str, reason: str, tx_id: str,
) -> None:
    """Spec 72: one audit per conta a pagar/receber put back to PENDING
    because the tx that settled it was deleted or flipped sign."""
    if not occurrences:
        return
    actor = db.get(User, current_user.user_id)
    for occ in occurrences:
        AuditService(db).log(
            user_email=actor.email if actor else current_user.user_id,
            action="scheduled_transaction.payment_reverted",
            resource_type="scheduled_transaction",
            resource_id=occ.id,
            details={
                "description": occ.description, "due_date": occ.due_date.isoformat(),
                "reason": reason, "transaction_id": tx_id,
            },
            workspace_id=ws_id,
        )


def _audit_invoice(db: Session, current_user: UserContext, action: str, invoice_id: str, ws_id: str, details: dict) -> None:
    actor = db.get(User, current_user.user_id)
    AuditService(db).log(
        user_email=actor.email if actor else current_user.user_id,
        action=action,
        resource_type="invoice",
        resource_id=invoice_id,
        details=details,
        workspace_id=ws_id,
    )


def hydrate(db: Session, rows: list[Transaction]) -> list[TransactionOut]:
    """Batch-load display names for a page of tx."""
    if not rows:
        return []
    mov_ids = {r.asset_movement_id for r in rows if r.asset_movement_id}
    movs = {m.id: m for m in db.query(AssetMovement).filter(AssetMovement.id.in_(mov_ids)).all()} if mov_ids else {}
    asset_ids = {m.asset_id for m in movs.values()}
    assets = {a.id: a for a in db.query(Asset).filter(Asset.id.in_(asset_ids)).all()} if asset_ids else {}
    acc_ids = {r.checking_account_id for r in rows if r.checking_account_id}
    asset_acc_ids = {a.account_id for a in assets.values()}
    card_ids = {r.credit_card_account_id for r in rows if r.credit_card_account_id}
    accounts = {
        a.id: a for a in db.query(Account).filter(Account.id.in_(acc_ids | asset_acc_ids)).all()
    } if (acc_ids or asset_acc_ids) else {}
    cards = {c.id: c for c in db.query(CreditCardAccount).filter(CreditCardAccount.id.in_(card_ids)).all()} if card_ids else {}
    fi_ids = {a.financial_institution_id for a in accounts.values()} | {c.financial_institution_id for c in cards.values()}
    fis = {f.id: f for f in db.query(FinancialInstitution).filter(FinancialInstitution.id.in_(fi_ids)).all()} if fi_ids else {}
    cat_ids = {r.category_id for r in rows if r.category_id}
    cats = {c.id: c for c in db.query(Category).filter(Category.id.in_(cat_ids)).all()} if cat_ids else {}
    parent_ids = {c.parent_id for c in cats.values() if c.parent_id}
    parents = {c.id: c for c in db.query(Category).filter(Category.id.in_(parent_ids)).all()} if parent_ids else {}
    party_ids = {r.party_id for r in rows if r.party_id}
    parties = {p.id: p for p in db.query(Party).filter(Party.id.in_(party_ids)).all()} if party_ids else {}
    tag_rows = db.query(transaction_tag.c.transaction_id, Tag.id, Tag.name).join(
        Tag, Tag.id == transaction_tag.c.tag_id,
    ).filter(transaction_tag.c.transaction_id.in_([r.id for r in rows])).all()
    tags: dict[str, list[TagRef]] = {}
    for tx_id, tag_id, tag_name in tag_rows:
        tags.setdefault(tx_id, []).append(TagRef(id=tag_id, name=tag_name))
    job_ids = {r.extraction_job_id for r in rows if r.extraction_job_id}
    sources: dict[str, tuple[str, str]] = {}
    if job_ids:
        for job_id, att_id, filename in db.query(
            ExtractionJob.id, Attachment.id, Attachment.filename,
        ).join(Attachment, Attachment.id == ExtractionJob.attachment_id).filter(
            ExtractionJob.id.in_(job_ids), Attachment.is_active == True,  # noqa: E712
        ).all():
            sources[job_id] = (att_id, filename)

    out = []
    for r in rows:
        acc = accounts.get(r.checking_account_id) if r.checking_account_id else None
        card = cards.get(r.credit_card_account_id) if r.credit_card_account_id else None
        mov = movs.get(r.asset_movement_id) if r.asset_movement_id else None
        asset = assets.get(mov.asset_id) if mov else None
        asset_acc = accounts.get(asset.account_id) if asset else None
        holder = acc or card or asset_acc
        fi = fis.get(holder.financial_institution_id) if holder else None
        cat = cats.get(r.category_id) if r.category_id else None
        parent = parents.get(cat.parent_id) if cat and cat.parent_id else None
        party = parties.get(r.party_id) if r.party_id else None
        out.append(TransactionOut(
            id=r.id,
            workspace_id=r.workspace_id,
            source_type=r.source_type.value,
            checking_account_id=r.checking_account_id,
            account_name=acc.name if acc else None,
            credit_card_account_id=r.credit_card_account_id,
            card_name=card.name if card else None,
            financial_institution_name=fi.short_name if fi else None,
            fi_logo_slug=fi.logo_slug if fi else None,
            invoice_id=r.invoice_id,
            event_date=r.event_date.isoformat(),
            description=r.description,
            amount=float(r.amount),
            currency=r.currency.value,
            fx_rate=float(r.fx_rate),
            fx_source=r.fx_source.value,
            amount_brl=float(r.amount_brl),
            amount_usd=float(r.amount_usd),
            category_id=r.category_id,
            category_name=cat.name if cat else None,
            category_parent_name=parent.name if parent else None,
            category_color=(cat.color or (parent.color if parent else None)) if cat else None,
            category_kind=cat.kind.value if cat and cat.kind else None,
            party_id=r.party_id,
            party_name=party.name if party else None,
            tags=sorted(tags.get(r.id, []), key=lambda t: t.name),
            installment_number=r.installment_number,
            installment_total=r.installment_total,
            parent_transaction_id=r.parent_transaction_id,
            paid_invoice_id=r.paid_invoice_id,
            transfer_group_id=r.transfer_group_id,
            asset_movement_id=r.asset_movement_id,
            asset_id=asset.id if asset else None,
            asset_name=asset.name if asset else None,
            asset_ticker=asset.ticker if asset else None,
            asset_quantity=float(mov.quantity) if mov and mov.quantity is not None else None,
            is_reconciled=r.is_reconciled,
            extraction_job_id=r.extraction_job_id,
            source_attachment_id=sources[r.extraction_job_id][0] if r.extraction_job_id in sources else None,
            source_attachment_filename=sources[r.extraction_job_id][1] if r.extraction_job_id in sources else None,
            original_amount=float(r.original_amount) if r.original_amount is not None else None,
            original_currency=r.original_currency.value if r.original_currency else None,
            is_projected=is_projected(r),
            notes=r.notes,
            created_at=r.created_at.isoformat(),
            updated_at=r.updated_at.isoformat(),
        ))
    return out


def _filtered(
    db: Session,
    ws: str,
    *,
    date_from: date | None,
    date_to: date | None,
    account_ids: list[str] | None,
    card_ids: list[str] | None,
    category_ids: list[str] | None,
    party_id: str | None,
    tag_id: str | None,
    search: str | None,
    reconciled: bool | None,
    invoice_id: str | None = None,
    extraction_job_id: str | None = None,
    include_assets: bool = False,
):
    q = db.query(Transaction).filter(Transaction.workspace_id == ws)
    if date_from:
        q = q.filter(Transaction.event_date >= date_from)
    if date_to:
        q = q.filter(Transaction.event_date <= date_to)
    if account_ids or card_ids or include_assets:
        conds = []
        if account_ids:
            conds.append(Transaction.checking_account_id.in_(account_ids))
        if card_ids:
            conds.append(Transaction.credit_card_account_id.in_(card_ids))
        if include_assets:
            conds.append(Transaction.source_type == TransactionSourceType.ASSET)
        q = q.filter(or_(*conds))
    if category_ids:
        q = q.filter(Transaction.category_id.in_(category_ids))
    if party_id:
        q = q.filter(Transaction.party_id == party_id)
    if tag_id:
        q = q.filter(Transaction.id.in_(
            db.query(transaction_tag.c.transaction_id).filter(transaction_tag.c.tag_id == tag_id)
        ))
    if search:
        like = f"%{search.strip()}%"
        q = q.filter(or_(Transaction.description.ilike(like), Transaction.notes.ilike(like)))
    if reconciled is not None:
        q = q.filter(Transaction.is_reconciled == reconciled)
    if invoice_id:
        q = q.filter(Transaction.invoice_id == invoice_id)
    if extraction_job_id:
        q = q.filter(Transaction.extraction_job_id == extraction_job_id)
    return q


# ── routes ────────────────────────────────────────────────────────────────────

@router.get("", response_model=TransactionListOut)
def list_transactions(
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    account_id: list[str] | None = Query(default=None),
    card_id: list[str] | None = Query(default=None),
    asset_source: bool = Query(default=False),
    category_id: list[str] | None = Query(default=None),
    party_id: str | None = Query(default=None),
    tag_id: str | None = Query(default=None),
    invoice_id: str | None = Query(default=None),
    extraction_job_id: str | None = Query(default=None),
    search: str | None = Query(default=None),
    reconciled: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
    workspace_id: str | None = Query(default=None),
    db: Session = Depends(get_db, scope="function"),
    current_user: UserContext = Depends(get_current_user),
):
    ws = _resolve_ws(current_user, workspace_id)
    q = _filtered(
        db, ws, date_from=date_from, date_to=date_to, account_ids=account_id, card_ids=card_id,
        category_ids=category_id, party_id=party_id, tag_id=tag_id, search=search,
        reconciled=reconciled, invoice_id=invoice_id, extraction_job_id=extraction_job_id,
        include_assets=asset_source,
    )
    total = q.count()
    rows = (
        q.order_by(Transaction.event_date.desc(), Transaction.created_at.desc(), Transaction.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return TransactionListOut(items=hydrate(db, rows), total=total, page=page, page_size=page_size)


@router.get("/summary", response_model=TransactionSummaryOut)
def summary(
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    account_id: list[str] | None = Query(default=None),
    card_id: list[str] | None = Query(default=None),
    asset_source: bool = Query(default=False),
    category_id: list[str] | None = Query(default=None),
    party_id: str | None = Query(default=None),
    search: str | None = Query(default=None),
    workspace_id: str | None = Query(default=None),
    db: Session = Depends(get_db, scope="function"),
    current_user: UserContext = Depends(get_current_user),
):
    """Fluxo BRUTO do período (inclui transferências e pagamentos de fatura —
    o /expenses/summary da spec 74 aplica as exclusões). Sempre corta em
    `event_date <= hoje`: parcelas futuras de cartão não entram."""
    ws = _resolve_ws(current_user, workspace_id)
    today = date.today()
    q = _filtered(
        db, ws, date_from=date_from, date_to=min(date_to, today) if date_to else today,
        account_ids=account_id, card_ids=card_id, category_ids=category_id,
        party_id=party_id, tag_id=None, search=search, reconciled=None,
        include_assets=asset_source,
    )
    sub = q.with_entities(
        Transaction.amount_brl, Transaction.amount_usd, Transaction.is_reconciled,
    ).subquery()
    zero = Decimal("0")
    row = db.query(
        func.coalesce(func.sum(sub.c.amount_brl).filter(sub.c.amount_brl > 0), zero),
        func.coalesce(func.sum(sub.c.amount_usd).filter(sub.c.amount_brl > 0), zero),
        func.coalesce(func.sum(sub.c.amount_brl).filter(sub.c.amount_brl < 0), zero),
        func.coalesce(func.sum(sub.c.amount_usd).filter(sub.c.amount_brl < 0), zero),
        func.count().filter(sub.c.is_reconciled == False),  # noqa: E712
        func.count(),
    ).one()
    in_brl, in_usd, out_brl, out_usd, unrec, count = row
    return TransactionSummaryOut(
        inflows=MoneyPair(brl=float(in_brl), usd=float(in_usd)),
        outflows=MoneyPair(brl=float(out_brl), usd=float(out_usd)),
        net=MoneyPair(brl=float(in_brl) + float(out_brl), usd=float(in_usd) + float(out_usd)),
        unreconciled_count=unrec,
        count=count,
    )


@router.get("/{tx_id}", response_model=TransactionOut)
def get_transaction(
    tx_id: str,
    db: Session = Depends(get_db, scope="function"),
    current_user: UserContext = Depends(get_current_user),
):
    return hydrate(db, [_get_or_404(db, tx_id, current_user)])[0]


@router.post("", response_model=list[TransactionOut], status_code=status.HTTP_201_CREATED)
def create_transaction(
    body: TransactionCreateRequest,
    workspace_id: str | None = Query(default=None),
    db: Session = Depends(get_db, scope="function"),
    current_user: UserContext = Depends(get_current_user),
):
    """Returns a list: 1 row, or N rows for an installment purchase."""
    ws = _resolve_ws(current_user, workspace_id)
    data = svc.TxInput(**body.model_dump(exclude={"installments"}))
    try:
        rows = svc.create_transaction(db, ws, data, user_id=current_user.user_id, installments=body.installments)
    except (svc.TransactionError, svc.TransactionConflict) as exc:
        raise _translate(exc)
    _audit(db, current_user, "transaction.created", rows)
    account_balance.refresh_open_snapshots(db, ws)
    return hydrate(db, rows)


@router.post("/transfer", response_model=list[TransactionOut], status_code=status.HTTP_201_CREATED)
def create_transfer(
    body: TransferRequest,
    workspace_id: str | None = Query(default=None),
    db: Session = Depends(get_db, scope="function"),
    current_user: UserContext = Depends(get_current_user),
):
    ws = _resolve_ws(current_user, workspace_id)
    try:
        legs = svc.create_transfer(db, ws, user_id=current_user.user_id, **body.model_dump())
    except (svc.TransactionError, svc.TransactionConflict) as exc:
        raise _translate(exc)
    _audit(db, current_user, "transaction.transfer_created", legs, {"transfer_group_id": legs[0].transfer_group_id})
    account_balance.refresh_open_snapshots(db, ws)
    return hydrate(db, legs)


def _audit_movement(db: Session, current_user: UserContext, action: str, m: AssetMovement, tx_id: str | None) -> None:
    """Spec 83 — audit do lado investimento do par (mesmo shape do
    routes/asset_movements._audit, + o id da tx vinculada)."""
    actor = db.get(User, current_user.user_id)
    asset = db.get(Asset, m.asset_id)
    AuditService(db).log(
        user_email=actor.email if actor else current_user.user_id,
        action=action,
        workspace_id=m.workspace_id,
        user_id=current_user.user_id,
        resource_type="asset_movement",
        resource_id=m.id,
        details={
            "asset_id": m.asset_id,
            "asset_name": asset.name if asset else None,
            "asset_ticker": asset.ticker if asset else None,
            "type": m.type.value,
            "event_date": m.event_date.isoformat(),
            "quantity": str(m.quantity) if m.quantity is not None else None,
            "gross_amount": str(m.gross_amount) if m.gross_amount is not None else None,
            "linked_transaction_id": tx_id,
        },
    )


@router.post("/asset-payment", response_model=TransactionOut, status_code=status.HTTP_201_CREATED)
def create_asset_payment(
    body: AssetPaymentRequest,
    workspace_id: str | None = Query(default=None),
    db: Session = Depends(get_db, scope="function"),
    current_user: UserContext = Depends(get_current_user),
):
    """Spec 83 — cria o par lançamento do ativo (SELL/BUY) + movimentação
    (source_type=ASSET) numa transação só."""
    ws = _resolve_ws(current_user, workspace_id)
    try:
        m, tx = asset_payments.create_asset_payment(
            db, ws, user_id=current_user.user_id, **body.model_dump(),
        )
    except (svc.TransactionError, svc.TransactionConflict) as exc:
        raise _translate(exc)
    _audit(db, current_user, "transaction.created", [tx], {"asset_movement_id": m.id})
    _audit_movement(db, current_user, "asset_movement.created", m, tx.id)
    return hydrate(db, [tx])[0]


@router.patch("/{tx_id}", response_model=list[TransactionOut])
def update_transaction(
    tx_id: str,
    body: TransactionUpdateRequest,
    db: Session = Depends(get_db, scope="function"),
    current_user: UserContext = Depends(get_current_user),
):
    """Partial update; returns every row touched (both legs of a transfer)."""
    tx = _get_or_404(db, tx_id, current_user)
    changes = body.model_dump(exclude_unset=True)
    before = {k: str(getattr(tx, k, None)) for k in changes if k != "tag_ids"}
    old_date = tx.event_date
    reverted: list = []
    try:
        rows = svc.update_transaction(
            db, tx, changes, user_id=current_user.user_id, reverted_occurrences=reverted,
        )
    except (svc.TransactionError, svc.TransactionConflict) as exc:
        raise _translate(exc)
    _audit(db, current_user, "transaction.updated", rows, {
        "before": before, "after": {k: str(v) for k, v in changes.items()},
    })
    if tx.asset_movement_id and tx.source_type == TransactionSourceType.ASSET:
        mov = db.get(AssetMovement, tx.asset_movement_id)
        if mov is not None:
            _audit_movement(db, current_user, "asset_movement.updated", mov, tx.id)
    _audit_payment_reverted(db, current_user, reverted, tx.workspace_id, "transaction sign changed", tx.id)
    if tx.paid_invoice_id and tx.event_date != old_date:
        _audit_invoice(db, current_user, "invoice.payment_date_updated", tx.paid_invoice_id, tx.workspace_id, {
            "transaction_id": tx.id, "before": old_date.isoformat(), "after": tx.event_date.isoformat(),
        })
    account_balance.refresh_open_snapshots(db, tx.workspace_id)
    return hydrate(db, rows)


@router.delete("/{tx_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_transaction(
    tx_id: str,
    cascade: bool = Query(default=False),
    db: Session = Depends(get_db, scope="function"),
    current_user: UserContext = Depends(get_current_user),
):
    tx = _get_or_404(db, tx_id, current_user)
    ws = tx.workspace_id
    reverted: list = []
    deactivated: list = []
    try:
        rows = svc.delete_transaction(
            db, tx, cascade=cascade, reverted_occurrences=reverted,
            deactivated_movements=deactivated, user_id=current_user.user_id,
        )
    except (svc.TransactionError, svc.TransactionConflict) as exc:
        raise _translate(exc)
    _audit(db, current_user, "transaction.deleted", rows)
    for m in deactivated:
        _audit_movement(db, current_user, "asset_movement.deactivated", m, tx_id)
    _audit_payment_reverted(db, current_user, reverted, ws, "transaction deleted", tx_id)
    for r in rows:
        if r.paid_invoice_id:
            _audit_invoice(db, current_user, "invoice.payment_reverted", r.paid_invoice_id, ws, {
                "transaction_id": r.id, "amount": str(-r.amount), "paid_on": r.event_date.isoformat(),
            })
    account_balance.refresh_open_snapshots(db, ws)

