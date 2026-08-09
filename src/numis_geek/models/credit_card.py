"""Spec 69 — CreditCardAccount + Invoice.

Credit cards are a separate entity (NOT Account.account_type) — decisão
da entrevista 2026-08-09, seguindo o protótipo v2: campos próprios
(limite, dias de fechamento/vencimento, bandeira) não contaminam a
tabela account. FK direto pra FinancialInstitution.

Invoice é o agrupador mensal das transações de cartão (spec 70).
Ciclo: OPEN (lazy-created) → CLOSED (congela total) → PAID (spec 70,
serviço pay_invoice). `total_amount` é SEMPRE positivo (valor da
fatura); enquanto OPEN é derivado da soma |tx|.
"""
import enum
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Boolean, Date, DateTime, Enum, ForeignKey, Index, Integer, Numeric,
    String, Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from numis_geek.db.base import Base
from numis_geek.models.account import Currency


class InvoiceStatus(str, enum.Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    PAID = "PAID"


class CreditCardAccount(Base):
    __tablename__ = "credit_card_account"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id: Mapped[str] = mapped_column(String(36), ForeignKey("workspace.id"), nullable=False)
    financial_institution_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("financial_institution.id"), nullable=False,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    brand: Mapped[str | None] = mapped_column(String(30), nullable=True)
    last4: Mapped[str | None] = mapped_column(String(4), nullable=True)
    currency: Mapped[Currency] = mapped_column(Enum(Currency), nullable=False)
    credit_limit: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    close_day: Mapped[int] = mapped_column(Integer, nullable=False)   # 1–28
    due_day: Mapped[int] = mapped_column(Integer, nullable=False)     # 1–28
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    __table_args__ = (
        Index("ix_credit_card_workspace", "workspace_id"),
    )


class Invoice(Base):
    __tablename__ = "invoice"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id: Mapped[str] = mapped_column(String(36), ForeignKey("workspace.id"), nullable=False)
    credit_card_account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("credit_card_account.id"), nullable=False,
    )
    close_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    # Sempre positivo. NULL enquanto OPEN (derivado da soma |tx|);
    # congelado no fechamento ou vindo do PDF (spec 71).
    total_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    # IOF consolidado da fatura — fonte do KPI "IOF · cartão" (spec 71 preenche).
    iof_total: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    currency: Mapped[Currency] = mapped_column(Enum(Currency), nullable=False)
    status: Mapped[InvoiceStatus] = mapped_column(
        Enum(InvoiceStatus), nullable=False, default=InvoiceStatus.OPEN,
    )
    paid_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    # paid_by_transaction_id chega na spec 70 (batch_alter) — espelho
    # denormalizado do pagamento; lado autoritativo é transaction.paid_invoice_id.
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    __table_args__ = (
        Index("ux_invoice_card_close", "credit_card_account_id", "close_date", unique=True),
        Index("ix_invoice_workspace_status", "workspace_id", "status"),
    )
