"""Spec 70 — Transaction (Movimentação).

Single ledger table for the Numis side, discriminated by `source_type`:
CHECKING tx live in a checking `account`, CREDIT_CARD tx live in a
`credit_card_account` + its `invoice`. Exactly one of the two source FKs
is set (CHECK constraint + service validation).

`amount` is SIGNED (expense negative, income positive — prototype
convention). `fx_rate` is the canonical USD/BRL of the event date (PTAX
walkback, or the document's own rate when `fx_source=STATEMENT`), and
`amount_brl` / `amount_usd` are PERSISTED on write — deliberately unlike
the investments side, because a STATEMENT rate can't be recomputed from
the PTAX table.

Structural links:
- installments: N tx (one per invoice/month), children point to the 1st
  via `parent_transaction_id`;
- invoice payment: cash tx with `paid_invoice_id` (authoritative side;
  `invoice.paid_by_transaction_id` is a mirror kept by `pay_invoice`);
- transfer between own accounts: two CHECKING legs sharing
  `transfer_group_id`.

`fingerprint` is computed on EVERY write (manual or imported) — the
statement import (spec 71) dedups against it. Not unique.
"""
import enum
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Boolean, CheckConstraint, Column, Date, DateTime, Enum, ForeignKey, Index,
    Integer, Numeric, String, Table, Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from numis_geek.db.base import Base
from numis_geek.models.account import Currency


class TransactionSourceType(str, enum.Enum):
    CHECKING = "CHECKING"
    CREDIT_CARD = "CREDIT_CARD"


class FxSource(str, enum.Enum):
    STATEMENT = "STATEMENT"
    PTAX = "PTAX"


transaction_tag = Table(
    "transaction_tag",
    Base.metadata,
    Column("transaction_id", String(36), ForeignKey("transaction.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", String(36), ForeignKey("tag.id", ondelete="CASCADE"), primary_key=True),
    Index("ix_transaction_tag_tag", "tag_id"),
)


class Transaction(Base):
    __tablename__ = "transaction"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id: Mapped[str] = mapped_column(String(36), ForeignKey("workspace.id"), nullable=False)
    source_type: Mapped[TransactionSourceType] = mapped_column(Enum(TransactionSourceType), nullable=False)
    checking_account_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("account.id"), nullable=True)
    credit_card_account_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("credit_card_account.id"), nullable=True,
    )
    invoice_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("invoice.id"), nullable=True)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    currency: Mapped[Currency] = mapped_column(Enum(Currency), nullable=False)
    fx_rate: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    fx_source: Mapped[FxSource] = mapped_column(Enum(FxSource), nullable=False, default=FxSource.PTAX)
    amount_brl: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    amount_usd: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    category_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("category.id"), nullable=True)
    party_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("party.id"), nullable=True)
    installment_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    installment_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parent_transaction_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("transaction.id"), nullable=True,
    )
    paid_invoice_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("invoice.id"), nullable=True)
    transfer_group_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # sha1 hex (40) + sufixo ":k" da k-ésima linha idêntica no mesmo arquivo (spec 71).
    fingerprint: Mapped[str] = mapped_column(String(48), nullable=False)
    is_reconciled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Spec 71 — import (extraction_job) que criou ou conciliou esta tx.
    # NULL = manual nunca conciliada. Re-conciliação não sobrescreve.
    extraction_job_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("extraction_job.id"), nullable=True,
    )
    # Spec 71 (2026-11-02) — linha do extrato em outra moeda convertida pela
    # PTAX (Wise: US$ numa conta BRL): valor e moeda ORIGINAIS. A chave de
    # dedup (fingerprint) usa estes quando presentes, então editar a tx não
    # quebra o casamento com o re-import.
    original_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    original_currency: Mapped[Currency | None] = mapped_column(Enum(Currency), nullable=True)
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
        CheckConstraint(
            "(checking_account_id IS NOT NULL AND credit_card_account_id IS NULL)"
            " OR (checking_account_id IS NULL AND credit_card_account_id IS NOT NULL)",
            name="ck_transaction_one_source",
        ),
        Index("ix_transaction_ws_date", "workspace_id", "event_date"),
        Index("ix_transaction_invoice", "invoice_id"),
        Index("ix_transaction_category", "category_id"),
        Index("ix_transaction_party", "party_id"),
        Index("ix_transaction_ws_fingerprint", "workspace_id", "fingerprint"),
        Index("ix_transaction_checking", "checking_account_id", "event_date"),
        Index("ix_transaction_transfer_group", "transfer_group_id"),
        Index("ix_transaction_extraction_job", "extraction_job_id"),
    )
