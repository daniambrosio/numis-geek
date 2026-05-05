import enum
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Index, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from numis_geek.db.base import Base
from numis_geek.models.account import Currency  # noqa: F401 — reused enum
from numis_geek.models.external import ExternalSource


class LancamentoType(str, enum.Enum):
    COMPRA = "COMPRA"
    VENDA = "VENDA"
    DIVIDENDO = "DIVIDENDO"
    JUROS = "JUROS"
    JCP = "JCP"
    COME_COTAS = "COME_COTAS"
    BONIFICACAO = "BONIFICACAO"
    SUBSCRICAO = "SUBSCRICAO"
    RESGATE_TOTAL = "RESGATE_TOTAL"


# Display names (PT) for UI use; kept on the backend so any layer (audit, exports,
# notifications) can render the same label without re-implementing the dictionary.
LANCAMENTO_TYPE_LABELS: dict[LancamentoType, str] = {
    LancamentoType.COMPRA: "Compra",
    LancamentoType.VENDA: "Venda",
    LancamentoType.DIVIDENDO: "Dividendo",
    LancamentoType.JUROS: "Juros / Cupom",
    LancamentoType.JCP: "JCP",
    LancamentoType.COME_COTAS: "Come-cotas",
    LancamentoType.BONIFICACAO: "Bonificação",
    LancamentoType.SUBSCRICAO: "Subscrição",
    LancamentoType.RESGATE_TOTAL: "Resgate Total",
}


class Lancamento(Base):
    __tablename__ = "lancamento"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id: Mapped[str] = mapped_column(String(36), ForeignKey("workspace.id"), nullable=False)
    asset_id: Mapped[str] = mapped_column(String(36), ForeignKey("asset.id"), nullable=False)
    type: Mapped[LancamentoType] = mapped_column(Enum(LancamentoType), nullable=False)

    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    settlement_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)

    gross_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    fee: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    tax: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    net_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)

    currency: Mapped[Currency] = mapped_column(Enum(Currency), nullable=False)
    fx_rate: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False, default=Decimal("1.0"))

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    external_source: Mapped[ExternalSource | None] = mapped_column(
        Enum(ExternalSource), nullable=True
    )
    nota_negociacao_number: Mapped[str | None] = mapped_column(String(50), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    __table_args__ = (
        Index("ix_lancamento_workspace_event_date", "workspace_id", "event_date"),
        Index("ix_lancamento_asset_event_date", "asset_id", "event_date"),
        Index("ix_lancamento_workspace_type_event_date", "workspace_id", "type", "event_date"),
        Index(
            "ix_lancamento_external",
            "external_source",
            "external_id",
            sqlite_where=text("external_id IS NOT NULL"),
            postgresql_where=text("external_id IS NOT NULL"),
        ),
    )
