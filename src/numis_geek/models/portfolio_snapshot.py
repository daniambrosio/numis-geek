"""Monthly portfolio snapshot — frozen photo of positions at period_end.

PortfolioSnapshot is the header (one row per workspace × period_end);
PortfolioSnapshotItem is the detail (one row per active asset at that
date). Stores raw quantity and market value in both native currency and
BRL/USD.

Workflow:
- User runs snapshot create --period-end YYYY-MM-DD on the 1st of the
  next month → captures fotografia of current_price and PTAX at that
  date. Stores totals.
- Historical backfill: snapshot backfill-from-notion reads Notion DB IG
  Lote Apuracao + DB IG Apuracao, creates snapshots, validates against
  rollups, generates a divergencias_<ts>.csv report.
"""
import enum
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Boolean, Date, DateTime, Enum, ForeignKey, Index, Numeric, String, Text,
    UniqueConstraint, text,
)
from sqlalchemy.orm import Mapped, mapped_column

from numis_geek.db.base import Base
from numis_geek.models.external import ExternalSource
from numis_geek.models.notion_sync import NotionSyncStatus


class SnapshotSource(str, enum.Enum):
    MANUAL = "MANUAL"
    NOTION_BACKFILL = "NOTION_BACKFILL"
    AUTOMATED = "AUTOMATED"


class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshot"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id: Mapped[str] = mapped_column(String(36), ForeignKey("workspace.id"), nullable=False)

    period_end_date: Mapped[date] = mapped_column(Date, nullable=False)
    fx_rate_usd_brl: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)

    total_value_brl: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    total_value_usd: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    total_invested_brl: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    total_received_brl: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))

    source: Mapped[SnapshotSource] = mapped_column(Enum(SnapshotSource), nullable=False, default=SnapshotSource.MANUAL)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    external_source: Mapped[ExternalSource | None] = mapped_column(
        Enum(ExternalSource), nullable=True
    )
    notion_last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notion_remote_last_edited_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notion_sync_status: Mapped[NotionSyncStatus] = mapped_column(
        Enum(NotionSyncStatus), nullable=False, default=NotionSyncStatus.PENDING
    )
    notion_sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    __table_args__ = (
        UniqueConstraint("workspace_id", "period_end_date", name="ux_snapshot_ws_period"),
        Index("ix_snapshot_workspace_period", "workspace_id", "period_end_date"),
        Index(
            "ix_snapshot_external",
            "external_source",
            "external_id",
            sqlite_where=text("external_id IS NOT NULL"),
            postgresql_where=text("external_id IS NOT NULL"),
        ),
    )


class PortfolioSnapshotItem(Base):
    __tablename__ = "portfolio_snapshot_item"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    snapshot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("portfolio_snapshot.id"), nullable=False
    )
    asset_id: Mapped[str] = mapped_column(String(36), ForeignKey("asset.id"), nullable=False)

    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    market_value_native: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    market_value_brl: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    market_value_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)

    average_cost_brl: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    total_invested_brl: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    external_source: Mapped[ExternalSource | None] = mapped_column(
        Enum(ExternalSource), nullable=True
    )
    notion_last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notion_remote_last_edited_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notion_sync_status: Mapped[NotionSyncStatus] = mapped_column(
        Enum(NotionSyncStatus), nullable=False, default=NotionSyncStatus.PENDING
    )
    notion_sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_snapshot_item_snapshot", "snapshot_id"),
        Index("ix_snapshot_item_asset", "asset_id"),
        Index(
            "ix_snapshot_item_external",
            "external_source",
            "external_id",
            sqlite_where=text("external_id IS NOT NULL"),
            postgresql_where=text("external_id IS NOT NULL"),
        ),
    )
