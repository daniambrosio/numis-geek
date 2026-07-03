"""Attachment — polymorphic user-uploaded files (image/pdf/csv/other) attached
to Asset, AssetMovement, or Distribution rows.

See `docs/conceptual-model.md` §2.9 for the design rationale: notes & files
are user-authored content separate from reconciliation files (StatementFile,
TradeNote, InvoiceFile). Storage is local filesystem (V1); migrate to object
storage when moving to VPS.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, Enum, ForeignKey, Index, Integer, String,
)
from sqlalchemy.orm import Mapped, mapped_column

from numis_geek.db.base import Base


class AttachmentSourceType(str, enum.Enum):
    ASSET = "asset"
    MOVEMENT = "movement"
    DISTRIBUTION = "distribution"
    SNAPSHOT = "snapshot"
    SNAPSHOT_ITEM = "snapshot_item"


class AttachmentKind(str, enum.Enum):
    IMAGE = "image"
    PDF = "pdf"
    CSV = "csv"
    OTHER = "other"


class Attachment(Base):
    __tablename__ = "attachment"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspace.id"), nullable=False
    )
    source_type: Mapped[AttachmentSourceType] = mapped_column(
        Enum(AttachmentSourceType), nullable=False
    )
    # App-level FK — points at asset / asset_movement / distribution. We don't
    # express the FK at the DB level because it's polymorphic, but we do
    # validate the row exists in the same workspace before inserting.
    source_id: Mapped[str] = mapped_column(String(36), nullable=False)

    kind: Mapped[AttachmentKind] = mapped_column(Enum(AttachmentKind), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    # Relative path under ./data/attachments/, e.g. "{workspace_id}/{uuid}.png".
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)

    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    uploaded_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("user.id"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    __table_args__ = (
        Index("ix_attachment_source", "source_type", "source_id"),
        Index("ix_attachment_workspace", "workspace_id"),
    )
