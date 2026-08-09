"""Spec 68 — Tag.

Free-form labels for ad-hoc transaction analysis ("viagem-japao-2026").
Stored lowercase-normalized, unique per workspace. The transaction_tag
join table arrives with the transaction model (spec 70).
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from numis_geek.db.base import Base


class Tag(Base):
    __tablename__ = "tag"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id: Mapped[str] = mapped_column(String(36), ForeignKey("workspace.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    __table_args__ = (
        Index("ux_tag_ws_name", "workspace_id", "name", unique=True),
    )
