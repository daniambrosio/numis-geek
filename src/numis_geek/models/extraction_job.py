"""Spec 38 — ExtractionJob.

One row per LLM extraction attempt. Stores the raw extracted JSON, model
metadata, cost, and lifecycle timestamps so admins can audit usage. The
applied payload (after user review) is stored separately in `user_edits`
when the user edited the LLM output before confirming.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    DateTime, Enum, ForeignKey, Index, Integer, JSON, Numeric, String, Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from numis_geek.db.base import Base


class ExtractionStatus(str, enum.Enum):
    PENDING = "PENDING"        # created, awaiting worker / sync call
    RUNNING = "RUNNING"        # LLM call in flight
    EXTRACTED = "EXTRACTED"    # JSON ready, awaiting user review
    CONFIRMED = "CONFIRMED"    # user applied; data written
    REJECTED = "REJECTED"      # user discarded
    FAILED = "FAILED"          # LLM error / parse error / timeout


class ExtractionSourceHint(str, enum.Enum):
    BROKER_POSITION = "BROKER_POSITION"
    BROKER_INCOME = "BROKER_INCOME"
    B3_TRADE_NOTE = "B3_TRADE_NOTE"
    FGTS_BALANCE = "FGTS_BALANCE"
    SCREENSHOT_PRICE = "SCREENSHOT_PRICE"
    GENERIC = "GENERIC"


class ExtractionJob(Base):
    __tablename__ = "extraction_job"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4()),
    )
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspace.id"), nullable=False,
    )

    # What triggered the job (at least one set).
    snapshot_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("portfolio_snapshot.id"), nullable=True,
    )
    pendency_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("snapshot_pendency.id"), nullable=True,
    )
    asset_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("asset.id"), nullable=True,
    )

    # The uploaded file (Spec 19 Attachment).
    attachment_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("attachment.id"), nullable=False,
    )

    source_hint: Mapped[ExtractionSourceHint] = mapped_column(
        Enum(ExtractionSourceHint), nullable=False,
        default=ExtractionSourceHint.GENERIC,
    )
    status: Mapped[ExtractionStatus] = mapped_column(
        Enum(ExtractionStatus), nullable=False,
        default=ExtractionStatus.PENDING,
    )

    # LLM call metadata.
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)

    # Extracted payload (shape varies by source_hint — see services/extraction_templates).
    extracted_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)
    detected_hint: Mapped[ExtractionSourceHint | None] = mapped_column(
        Enum(ExtractionSourceHint), nullable=True,
    )

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Lifecycle.
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc),
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    confirmed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    # Final applied payload (== extracted_json XOR user edits at confirm time).
    user_edits: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        Index("ix_extraction_workspace_status", "workspace_id", "status"),
        Index("ix_extraction_pendency", "pendency_id"),
    )
