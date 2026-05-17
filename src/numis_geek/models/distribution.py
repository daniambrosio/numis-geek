import enum
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Index, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from numis_geek.db.base import Base
from numis_geek.models.account import Currency  # noqa: F401 — reused enum
from numis_geek.models.external import ExternalSource


class DistributionType(str, enum.Enum):
    DIVIDEND = "DIVIDEND"
    INTEREST = "INTEREST"
    JCP = "JCP"
    SECURITIES_LENDING = "SECURITIES_LENDING"


DISTRIBUTION_TYPE_LABELS: dict[DistributionType, str] = {
    DistributionType.DIVIDEND: "Dividendo",
    DistributionType.INTEREST: "Juros / Cupom",
    DistributionType.JCP: "JCP",
    DistributionType.SECURITIES_LENDING: "Aluguel",
}


class Distribution(Base):
    """Income-receiving event: dividend, interest, JCP, securities lending.

    `asset_id` is nullable — Avenue's generic "rendimento de aluguel" arrives
    without a specific ticker. `financial_institution_id` is always known and
    the FI Hub uses it to aggregate FI-level distribution feed.
    """
    __tablename__ = "distribution"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id: Mapped[str] = mapped_column(String(36), ForeignKey("workspace.id"), nullable=False)
    financial_institution_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("financial_institution.id"), nullable=False
    )
    asset_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("asset.id"), nullable=True
    )
    type: Mapped[DistributionType] = mapped_column(Enum(DistributionType), nullable=False)

    event_date: Mapped[date] = mapped_column(Date, nullable=False)

    gross_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
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

    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    __table_args__ = (
        Index("ix_distribution_workspace_event_date", "workspace_id", "event_date"),
        Index("ix_distribution_fi_event_date", "financial_institution_id", "event_date"),
        Index("ix_distribution_asset_event_date", "asset_id", "event_date"),
        Index(
            "ix_distribution_external",
            "external_source",
            "external_id",
            sqlite_where=text("external_id IS NOT NULL"),
            postgresql_where=text("external_id IS NOT NULL"),
        ),
    )
