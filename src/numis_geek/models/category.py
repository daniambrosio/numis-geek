"""Spec 68 — Category.

Single level of nesting (parent -> children). Decisão 2026-08-09 (v2):
`kind` lives ONLY on subcategories — the root category is a pure
thematic grouper (kind NULL). A transaction always references a
SUBcategory, and it's the sub's kind that drives the expense-average
math in spec 74 (TRANSFER never counts as expense or income).
Color lives on the root; subs inherit it at creation.
"""
import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from numis_geek.db.base import Base


class CategoryKind(str, enum.Enum):
    EXPENSE = "EXPENSE"
    INCOME = "INCOME"
    TRANSFER = "TRANSFER"


class Category(Base):
    __tablename__ = "category"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id: Mapped[str] = mapped_column(String(36), ForeignKey("workspace.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(60), nullable=False)
    parent_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("category.id"), nullable=True)
    # NULL on roots (grouper); NOT NULL on subs (service-enforced).
    kind: Mapped[CategoryKind | None] = mapped_column(Enum(CategoryKind), nullable=True)
    color: Mapped[str | None] = mapped_column(String(7), nullable=True)
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
        # Uniqueness is per (workspace, parent): homonymous subcategories
        # under different parents are legal (spec 73 relies on this).
        Index("ux_category_ws_parent_name", "workspace_id", "parent_id", "name", unique=True),
    )
