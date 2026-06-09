"""Corporate actions: splits, groupings (reverse splits), asset conversions.

Separate from AssetMovement — these are *transformations* of existing
positions, not trades. They preserve total cost basis while modifying
quantity and per-unit price. See memory `corporate-actions-design` for
the design rationale.
"""
import enum
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Boolean, Date, DateTime, Enum, ForeignKey, Index, Numeric, String, Text, text
)
from sqlalchemy.orm import Mapped, mapped_column

from numis_geek.db.base import Base
from numis_geek.models.external import ExternalSource


class CorporateActionType(str, enum.Enum):
    SPLIT = "SPLIT"               # desdobramento: ratio > 1 (e.g. 10 means 1→10)
    GROUPING = "GROUPING"         # agrupamento/inplit: ratio < 1 (e.g. 0.1 means 10→1)
    ASSET_CONVERSION = "ASSET_CONVERSION"   # incorporação/troca de ticker


CORPORATE_ACTION_TYPE_LABELS: dict[CorporateActionType, str] = {
    CorporateActionType.SPLIT: "Desdobramento",
    CorporateActionType.GROUPING: "Agrupamento",
    CorporateActionType.ASSET_CONVERSION: "Conversão / Incorporação",
}


class CorporateAction(Base):
    __tablename__ = "corporate_action"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id: Mapped[str] = mapped_column(String(36), ForeignKey("workspace.id"), nullable=False)
    asset_id: Mapped[str] = mapped_column(String(36), ForeignKey("asset.id"), nullable=False)

    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    event_type: Mapped[CorporateActionType] = mapped_column(Enum(CorporateActionType), nullable=False)
    ratio: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)

    # Only used for ASSET_CONVERSION
    target_asset_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("asset.id"), nullable=True)
    target_ratio: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)

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
        Index("ix_corp_action_workspace_event_date", "workspace_id", "event_date"),
        Index("ix_corp_action_asset_event_date", "asset_id", "event_date"),
        Index(
            "ix_corp_action_external",
            "external_source",
            "external_id",
            sqlite_where=text("external_id IS NOT NULL"),
            postgresql_where=text("external_id IS NOT NULL"),
        ),
    )
