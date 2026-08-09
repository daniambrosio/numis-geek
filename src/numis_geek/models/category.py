"""Spec 68 — Category.

Expense/income/transfer categorization with a single level of nesting
(parent -> children). `kind` drives the expense-average math in spec 74:
TRANSFER rows never count as expense or income. Subcategories inherit
kind/color from the parent (enforced at the service layer, stored
denormalized for query simplicity).
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
    kind: Mapped[CategoryKind] = mapped_column(Enum(CategoryKind), nullable=False)
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
