"""Spec 69 — CreditCardAccount CRUD + Invoice list/create/close."""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from numis_geek.api.deps import get_current_user, get_db
from numis_geek.models.account import Currency
from numis_geek.models.credit_card import CreditCardAccount, Invoice, InvoiceStatus
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.user import User, UserRole
from numis_geek.services.audit import AuditService
from numis_geek.services.auth import UserContext

router = APIRouter(prefix="/credit-cards", tags=["credit-cards"])
invoice_router = APIRouter(prefix="/invoices", tags=["invoices"])


# ── schemas ───────────────────────────────────────────────────────────────────

class CreditCardOut(BaseModel):
    id: str
    workspace_id: str
    financial_institution_id: str
    financial_institution_name: str
    fi_logo_slug: str | None
    name: str
    brand: str | None
    last4: str | None
    currency: str
    credit_limit: float | None
    close_day: int
    due_day: int
    is_active: bool
    # Derivados — 0/None até a spec 70 (soma das tx da invoice OPEN).
    open_invoice_total: float
    limit_used_pct: float | None
    created_at: str

    @classmethod
    def from_orm(cls, c: CreditCardAccount, fi: FinancialInstitution | None, open_total: Decimal) -> "CreditCardOut":
        limit_pct = (
            float(open_total) / float(c.credit_limit)
            if c.credit_limit and float(c.credit_limit) > 0 else None
        )
        return cls(
            id=c.id,
            workspace_id=c.workspace_id,
            financial_institution_id=c.financial_institution_id,
            financial_institution_name=fi.short_name if fi else c.financial_institution_id,
            fi_logo_slug=fi.logo_slug if fi else None,
            name=c.name,
            brand=c.brand,
            last4=c.last4,
            currency=c.currency.value,
            credit_limit=float(c.credit_limit) if c.credit_limit is not None else None,
            close_day=c.close_day,
            due_day=c.due_day,
            is_active=c.is_active,
            open_invoice_total=float(open_total),
            limit_used_pct=limit_pct,
            created_at=c.created_at.isoformat(),
        )


class CreditCardRequest(BaseModel):
    name: str
    financial_institution_id: str
    currency: Currency
    brand: str | None = None
    last4: str | None = None
    credit_limit: Decimal | None = None
    close_day: int
    due_day: int

    @field_validator("close_day", "due_day")
    @classmethod
    def _day_range(cls, v: int) -> int:
        if not 1 <= v <= 28:
            raise ValueError("day must be between 1 and 28")
        return v


class InvoiceOut(BaseModel):
    id: str
    workspace_id: str
    credit_card_account_id: str
    credit_card_name: str
    close_date: str
    due_date: str
    total_amount: float | None
    iof_total: float | None
    currency: str
    status: str
    paid_at: str | None
    notes: str | None

    @classmethod
    def from_orm(cls, inv: Invoice, card_name: str) -> "InvoiceOut":
        return cls(
            id=inv.id,
            workspace_id=inv.workspace_id,
            credit_card_account_id=inv.credit_card_account_id,
            credit_card_name=card_name,
            close_date=inv.close_date.isoformat(),
            due_date=inv.due_date.isoformat(),
            total_amount=float(inv.total_amount) if inv.total_amount is not None else None,
            iof_total=float(inv.iof_total) if inv.iof_total is not None else None,
            currency=inv.currency.value,
            status=inv.status.value,
            paid_at=inv.paid_at.isoformat() if inv.paid_at else None,
            notes=inv.notes,
        )


class InvoiceCreateRequest(BaseModel):
    close_date: date
    due_date: date
    total_amount: Decimal | None = None

    @field_validator("total_amount")
    @classmethod
    def _positive(cls, v: Decimal | None) -> Decimal | None:
        if v is not None and v < 0:
            raise ValueError("total_amount is always positive (valor da fatura)")
        return v


class InvoiceCloseRequest(BaseModel):
    total_amount: Decimal | None = None  # opcional: congela valor informado

    @field_validator("total_amount")
    @classmethod
    def _positive(cls, v: Decimal | None) -> Decimal | None:
        if v is not None and v < 0:
            raise ValueError("total_amount is always positive (valor da fatura)")
        return v


# ── helpers ───────────────────────────────────────────────────────────────────

def _require_admin(current_user: UserContext) -> None:
    if current_user.role not in (UserRole.admin, UserRole.sysadmin):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only.")


def _resolve_ws(current_user: UserContext, workspace_id: str | None) -> str:
    if current_user.role == UserRole.sysadmin:
        target = workspace_id or current_user.workspace_id
        if not target:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="workspace_id required for sysadmin.")
        return target
    return current_user.workspace_id


def _get_card_or_404(db: Session, card_id: str, current_user: UserContext) -> CreditCardAccount:
    c = db.get(CreditCardAccount, card_id)
    if not c:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credit card not found.")
    if current_user.role != UserRole.sysadmin and c.workspace_id != current_user.workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credit card not found.")
    return c


def _get_invoice_or_404(db: Session, invoice_id: str, current_user: UserContext) -> Invoice:
    inv = db.get(Invoice, invoice_id)
    if not inv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found.")
    if current_user.role != UserRole.sysadmin and inv.workspace_id != current_user.workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found.")
    return inv


def _open_total(db: Session, card: CreditCardAccount) -> Decimal:
    """Soma |tx| da invoice OPEN — chega com a spec 70. Por ora, o
    total congelado da OPEN se existir (criada manual/import), senão 0."""
    inv = db.query(Invoice).filter(
        Invoice.credit_card_account_id == card.id,
        Invoice.status == InvoiceStatus.OPEN,
    ).order_by(Invoice.close_date.desc()).first()
    return inv.total_amount if inv and inv.total_amount is not None else Decimal("0")


def _audit(db: Session, current_user: UserContext, action: str, resource_type: str, resource_id: str, ws_id: str, details: dict) -> None:
    actor = db.get(User, current_user.user_id)
    AuditService(db).log(
        user_email=actor.email if actor else current_user.user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details,
        workspace_id=ws_id,
    )


# ── credit card routes ────────────────────────────────────────────────────────

@router.get("", response_model=list[CreditCardOut])
def list_credit_cards(
    workspace_id: str | None = Query(default=None),
    include_inactive: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    ws = _resolve_ws(current_user, workspace_id)
    q = db.query(CreditCardAccount).filter(CreditCardAccount.workspace_id == ws)
    if not include_inactive:
        q = q.filter(CreditCardAccount.is_active == True)  # noqa: E712
    cards = q.order_by(CreditCardAccount.name).all()
    fi_map = {
        fi.id: fi
        for fi in db.query(FinancialInstitution).filter(
            FinancialInstitution.id.in_({c.financial_institution_id for c in cards})
        ).all()
    }
    return [
        CreditCardOut.from_orm(c, fi_map.get(c.financial_institution_id), _open_total(db, c))
        for c in cards
    ]


@router.post("", response_model=CreditCardOut, status_code=status.HTTP_201_CREATED)
def create_credit_card(
    body: CreditCardRequest,
    workspace_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    _require_admin(current_user)
    ws = _resolve_ws(current_user, workspace_id)
    fi = db.get(FinancialInstitution, body.financial_institution_id)
    if not fi or not fi.is_active:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unknown financial institution.")
    now = datetime.now(timezone.utc)
    c = CreditCardAccount(
        id=str(uuid.uuid4()),
        workspace_id=ws,
        financial_institution_id=body.financial_institution_id,
        name=body.name,
        brand=body.brand,
        last4=body.last4,
        currency=body.currency,
        credit_limit=body.credit_limit,
        close_day=body.close_day,
        due_day=body.due_day,
        is_active=True,
        created_at=now,
        updated_at=now,
        created_by=current_user.user_id,
        updated_by=current_user.user_id,
    )
    db.add(c)
    db.flush()
    _audit(db, current_user, "credit_card.created", "credit_card_account", c.id, ws, {"name": c.name})
    return CreditCardOut.from_orm(c, fi, Decimal("0"))


@router.put("/{card_id}", response_model=CreditCardOut)
def update_credit_card(
    card_id: str,
    body: CreditCardRequest,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    _require_admin(current_user)
    c = _get_card_or_404(db, card_id, current_user)
    c.name = body.name
    c.financial_institution_id = body.financial_institution_id
    c.currency = body.currency
    c.brand = body.brand
    c.last4 = body.last4
    c.credit_limit = body.credit_limit
    c.close_day = body.close_day
    c.due_day = body.due_day
    c.updated_at = datetime.now(timezone.utc)
    c.updated_by = current_user.user_id
    db.flush()
    fi = db.get(FinancialInstitution, c.financial_institution_id)
    _audit(db, current_user, "credit_card.updated", "credit_card_account", c.id, c.workspace_id, {"name": c.name})
    return CreditCardOut.from_orm(c, fi, _open_total(db, c))


@router.put("/{card_id}/deactivate", response_model=CreditCardOut)
def deactivate_credit_card(
    card_id: str,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    _require_admin(current_user)
    c = _get_card_or_404(db, card_id, current_user)
    open_inv = db.query(Invoice).filter(
        Invoice.credit_card_account_id == c.id,
        Invoice.status.in_([InvoiceStatus.OPEN, InvoiceStatus.CLOSED]),
    ).first()
    if open_inv:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot deactivate: card has open or unpaid invoices.",
        )
    c.is_active = False
    c.updated_at = datetime.now(timezone.utc)
    c.updated_by = current_user.user_id
    db.flush()
    fi = db.get(FinancialInstitution, c.financial_institution_id)
    _audit(db, current_user, "credit_card.deactivated", "credit_card_account", c.id, c.workspace_id, {"name": c.name})
    return CreditCardOut.from_orm(c, fi, Decimal("0"))


@router.get("/{card_id}/invoices", response_model=list[InvoiceOut])
def list_card_invoices(
    card_id: str,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    c = _get_card_or_404(db, card_id, current_user)
    invoices = db.query(Invoice).filter(
        Invoice.credit_card_account_id == c.id,
    ).order_by(Invoice.close_date.desc()).all()
    return [InvoiceOut.from_orm(inv, c.name) for inv in invoices]


@router.post("/{card_id}/invoices", response_model=InvoiceOut, status_code=status.HTTP_201_CREATED)
def create_invoice(
    card_id: str,
    body: InvoiceCreateRequest,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    _require_admin(current_user)
    c = _get_card_or_404(db, card_id, current_user)
    if body.due_date < body.close_date:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="due_date must be on/after close_date.")
    dup = db.query(Invoice).filter(
        Invoice.credit_card_account_id == c.id,
        Invoice.close_date == body.close_date,
    ).first()
    if dup:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Invoice with this close_date already exists.")
    now = datetime.now(timezone.utc)
    inv = Invoice(
        id=str(uuid.uuid4()),
        workspace_id=c.workspace_id,
        credit_card_account_id=c.id,
        close_date=body.close_date,
        due_date=body.due_date,
        total_amount=body.total_amount,
        currency=c.currency,
        status=InvoiceStatus.OPEN,
        created_at=now,
        updated_at=now,
        created_by=current_user.user_id,
        updated_by=current_user.user_id,
    )
    db.add(inv)
    db.flush()
    _audit(db, current_user, "invoice.created", "invoice", inv.id, c.workspace_id, {"card": c.name, "close_date": inv.close_date.isoformat()})
    return InvoiceOut.from_orm(inv, c.name)


# ── invoice routes ────────────────────────────────────────────────────────────

@invoice_router.get("", response_model=list[InvoiceOut])
def list_invoices(
    workspace_id: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    card_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    ws = _resolve_ws(current_user, workspace_id)
    q = db.query(Invoice).filter(Invoice.workspace_id == ws)
    if status_filter:
        try:
            q = q.filter(Invoice.status == InvoiceStatus(status_filter))
        except ValueError:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid status.")
    if card_id:
        q = q.filter(Invoice.credit_card_account_id == card_id)
    invoices = q.order_by(Invoice.close_date.desc()).all()
    card_names = {
        c.id: c.name
        for c in db.query(CreditCardAccount).filter(
            CreditCardAccount.id.in_({i.credit_card_account_id for i in invoices})
        ).all()
    }
    return [InvoiceOut.from_orm(i, card_names.get(i.credit_card_account_id, "—")) for i in invoices]


@invoice_router.post("/{invoice_id}/close", response_model=InvoiceOut)
def close_invoice(
    invoice_id: str,
    body: InvoiceCloseRequest,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    _require_admin(current_user)
    inv = _get_invoice_or_404(db, invoice_id, current_user)
    if inv.status != InvoiceStatus.OPEN:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only OPEN invoices can be closed.")
    if body.total_amount is not None:
        inv.total_amount = body.total_amount
    # Spec 70: quando as tx existirem, fechar sem total explícito congela
    # a soma |tx| do período. Por ora exige total (ou já preenchido).
    if inv.total_amount is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="total_amount required to close (transaction-derived totals arrive with spec 70).",
        )
    inv.status = InvoiceStatus.CLOSED
    inv.updated_at = datetime.now(timezone.utc)
    inv.updated_by = current_user.user_id
    db.flush()
    card = db.get(CreditCardAccount, inv.credit_card_account_id)
    _audit(db, current_user, "invoice.closed", "invoice", inv.id, inv.workspace_id, {"total": float(inv.total_amount)})
    return InvoiceOut.from_orm(inv, card.name if card else "—")
