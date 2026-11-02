"""Spec 71 (2026-11-02) — exemplos de classificação vindos do Notion.

Referência pro "System 1" (classificador de categorias do import): grupos
de lançamentos categorizados no Notion (≈1885 grupos / 5418 lançamentos
desde 2025), por texto do banco normalizado sem datas. **Não são
transações** — não aparecem em Movimentações, saldos, dashboards nem
fechamentos; só viram exemplos no prompt e atalho determinístico de
categoria dominante.
"""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from numis_geek.db.base import Base


class CategoryExample(Base):
    __tablename__ = "category_example"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id: Mapped[str] = mapped_column(String(36), ForeignKey("workspace.id"), nullable=False)
    # bank_import.alias_key do texto (sem datas no fim, inclusive coladas: "LI10/06")
    alias_key: Mapped[str] = mapped_column(String(255), nullable=False)
    sample_description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    direction: Mapped[str] = mapped_column(String(3), nullable=False)   # "out" | "in"
    category_id: Mapped[str] = mapped_column(String(36), ForeignKey("category.id"), nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    avg_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    min_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    max_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    last_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="notion")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("workspace_id", "source", "alias_key", "category_id", "direction",
                         name="uq_category_example"),
        Index("ix_category_example_ws_key", "workspace_id", "alias_key"),
    )
