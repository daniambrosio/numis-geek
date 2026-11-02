"""Spec 70 — Transaction (Movimentação).

Single ledger table for the Numis side, discriminated by `source_type`:
CHECKING tx live in a checking `account`, CREDIT_CARD tx live in a
`credit_card_account` + its `invoice`, ASSET tx (spec 83) are paid/received
with an asset and point to the `asset_movement` that moved it. Exactly one
of the three source FKs is set (CHECK constraint + service validation).

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
    Integer, Numeric, String, Table, Text, text,
)
from sqlalchemy.orm import Mapped, mapped_column

from numis_geek.db.base import Base
from numis_geek.models.account import Currency


class TransactionSourceType(str, enum.Enum):
    CHECKING = "CHECKING"
    CREDIT_CARD = "CREDIT_CARD"
    # Spec 83 — paga/recebida com o próprio ativo (USDC, BTC…): a fonte é o
    # `asset_movement` (SELL = despesa, BUY = receita) em `asset_movement_id`.
    ASSET = "ASSET"


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


# A fonte bate com source_type. CHECKING aceita asset_movement_id opcional:
# é a tx de caixa de resgate/aplicação ligada ao investimento (spec 82).
ONE_SOURCE_SQL = (
    "(source_type = 'CHECKING' AND checking_account_id IS NOT NULL AND credit_card_account_id IS NULL)"
    " OR (source_type = 'CREDIT_CARD' AND credit_card_account_id IS NOT NULL"
    " AND checking_account_id IS NULL AND asset_movement_id IS NULL)"
    " OR (source_type = 'ASSET' AND asset_movement_id IS NOT NULL"
    " AND checking_account_id IS NULL AND credit_card_account_id IS NULL)"
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
    # Spec 83/82 — movimento de ativo ligado a esta tx (lado autoritativo do
    # vínculo; um movimento tem no máximo UMA tx). Na 83 é a fonte da tx
    # (source_type=ASSET); a 82 reaproveita pra tx de caixa de resgate/aplicação.
    asset_movement_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("asset_movement.id", ondelete="RESTRICT"), nullable=True,
    )
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
    original_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)  # spec 84: EUR, GBP, CLP…
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
        # Exatamente uma fonte, coerente com source_type: conta corrente,
        # cartão ou (spec 83) ativo.
        CheckConstraint(
            ONE_SOURCE_SQL,
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
        Index(
            "uq_transaction_asset_movement", "asset_movement_id", unique=True,
            sqlite_where=text("asset_movement_id IS NOT NULL"),
            postgresql_where=text("asset_movement_id IS NOT NULL"),
        ),
    )
