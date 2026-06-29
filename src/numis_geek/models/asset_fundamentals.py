import enum
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Date, DateTime, Enum, ForeignKey, Index, Numeric, String, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from numis_geek.db.base import Base


class FundamentalsSource(str, enum.Enum):
    MANUAL = "MANUAL"
    BRAPI = "BRAPI"
    FINNHUB = "FINNHUB"
    YFINANCE = "YFINANCE"


class AssetFundamentals(Base):
    """Temporal snapshot of fundamentals per asset + source.

    UNIQUE(asset_id, snapshot_date, source) — supports manual override
    coexisting with the daily cron ingestion. Valuation reads the most
    recent row per asset (regardless of source).

    Most fields are nullable — different classes populate different
    subsets. Fields named with the metric's canonical short form
    (P/E → `pe`, P/VP → `p_vp`, etc.). Percentage fields are stored as
    decimal fractions in [0, 1] (e.g. 0.0834 for 8.34%).

    `raw_payload` stores the full provider response as JSON text for
    debugging / future field extraction without a re-fetch.
    """

    __tablename__ = "asset_fundamentals"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspace.id"), nullable=False
    )
    asset_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("asset.id"), nullable=False
    )
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[FundamentalsSource] = mapped_column(
        Enum(FundamentalsSource), nullable=False
    )

    # ── Stocks ──
    pe: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    pb: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    eps: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    bvps: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    roe: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    roic: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    net_margin: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    ebitda_margin: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    debt_ebitda: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    earnings_growth_5y: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    dividend_yield_12m: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    payout_ratio: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    dps_12m: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)

    # ── REITs ──
    p_ffo: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    p_vp: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    ffo_per_share: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    affo_per_share: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    vacancy: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    distribution_coverage: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)

    # ── ETFs ──
    expense_ratio: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    tracking_error: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    aum: Mapped[Decimal | None] = mapped_column(Numeric(20, 2), nullable=True)

    # ── Fixed income ──
    ytm: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    duration: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)

    raw_payload: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint(
            "asset_id", "snapshot_date", "source",
            name="ux_fundamentals_asset_date_source",
        ),
        Index("ix_fundamentals_asset_recent", "asset_id", "snapshot_date"),
    )
