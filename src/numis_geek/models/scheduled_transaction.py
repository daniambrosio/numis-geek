"""Spec 72 — Contas a Pagar e a Receber.

`recurrence_rule` is the template (aluguel dia 5, salário dia 10, financiamento
em 180x); `scheduled_transaction` is a concrete future obligation/right — one
row per occurrence, materialized from a rule (daily job + on-write) or created
by hand (one-off: `recurrence_rule_id IS NULL`).

`amount` is ALWAYS POSITIVE in both tables — `direction` (PAYABLE |
RECEIVABLE) gives the sign. That's deliberately unlike `transaction.amount`
(signed); the matcher compares |amount|.

"Em atraso" is NOT a status: it's `status == PENDING and due_date < today`,
derived on read.

`slot_date` is the ORIGINAL date the rule generated for an occurrence;
postponing moves only `due_date`. `UNIQUE(recurrence_rule_id, slot_date)`
makes materialization idempotent (a NULL rule never collides, so one-offs
are free — for them slot_date == due_date at creation). Materialization and
rule edits dedupe/drop by slot, never by the current due_date (audit
2026-10-31). `materialized_through` is the rule's watermark: the last slot
date the materializer already considered.
"""
import enum
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Boolean, Date, DateTime, Enum, ForeignKey, Index, Integer, Numeric, String, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from numis_geek.db.base import Base
from numis_geek.models.account import Currency


class ScheduledDirection(str, enum.Enum):
    PAYABLE = "PAYABLE"
    RECEIVABLE = "RECEIVABLE"


class RecurrenceFrequency(str, enum.Enum):
    MONTHLY = "MONTHLY"
    YEARLY = "YEARLY"
    INSTALLMENT = "INSTALLMENT"


class ScheduledStatus(str, enum.Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    CANCELED = "CANCELED"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class RecurrenceRule(Base):
    __tablename__ = "recurrence_rule"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id: Mapped[str] = mapped_column(String(36), ForeignKey("workspace.id"), nullable=False)
    direction: Mapped[ScheduledDirection] = mapped_column(Enum(ScheduledDirection), nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    party_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("party.id"), nullable=True)
    category_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("category.id"), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[Currency] = mapped_column(Enum(Currency), nullable=False)
    frequency: Mapped[RecurrenceFrequency] = mapped_column(Enum(RecurrenceFrequency), nullable=False)
    day_of_month: Mapped[int] = mapped_column(Integer, nullable=False)
    month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    installment_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    installment_paid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expected_account_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("account.id"), nullable=True)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    materialized_through: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    __table_args__ = (
        Index("ix_recurrence_rule_ws", "workspace_id", "is_active"),
    )


class ScheduledTransaction(Base):
    __tablename__ = "scheduled_transaction"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id: Mapped[str] = mapped_column(String(36), ForeignKey("workspace.id"), nullable=False)
    direction: Mapped[ScheduledDirection] = mapped_column(Enum(ScheduledDirection), nullable=False)
    recurrence_rule_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("recurrence_rule.id"), nullable=True,
    )
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    party_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("party.id"), nullable=True)
    category_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("category.id"), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[Currency] = mapped_column(Enum(Currency), nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    # Original slot generated by the rule — postpone never changes it.
    slot_date: Mapped[date] = mapped_column(Date, nullable=False)
    installment_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    installment_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expected_account_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("account.id"), nullable=True)
    status: Mapped[ScheduledStatus] = mapped_column(
        Enum(ScheduledStatus), nullable=False, default=ScheduledStatus.PENDING,
    )
    paid_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    paid_by_transaction_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("transaction.id"), nullable=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    __table_args__ = (
        UniqueConstraint("recurrence_rule_id", "slot_date", name="uq_scheduled_rule_slot"),
        Index("ix_scheduled_ws_due", "workspace_id", "due_date"),
        Index("ix_scheduled_ws_status", "workspace_id", "status"),
        Index("ix_scheduled_paid_by_tx", "paid_by_transaction_id"),
    )
