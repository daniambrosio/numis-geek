import enum
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Index, Integer, Numeric, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from numis_geek.db.base import Base
from numis_geek.models.account import Currency  # noqa: F401 — reused enum
from numis_geek.models.external import ExternalSource


class AssetClass(str, enum.Enum):
    STOCK = "STOCK"
    REIT = "REIT"
    ETF = "ETF"
    FIXED_INCOME = "FIXED_INCOME"
    FUND = "FUND"
    CRYPTO = "CRYPTO"
    REAL_ESTATE = "REAL_ESTATE"
    VEHICLE = "VEHICLE"
    CASH = "CASH"
    FGTS = "FGTS"
    PRIVATE_PENSION = "PRIVATE_PENSION"


class FixedIncomeIndexer(str, enum.Enum):
    CDI = "CDI"
    IPCA = "IPCA"
    SELIC = "SELIC"
    PREFIXED = "PREFIXED"
    USD = "USD"


class Asset(Base):
    __tablename__ = "asset"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id: Mapped[str] = mapped_column(String(36), ForeignKey("workspace.id"), nullable=False)
    financial_institution_id: Mapped[str] = mapped_column(String(36), ForeignKey("financial_institution.id"), nullable=False)
    asset_class: Mapped[AssetClass] = mapped_column(Enum(AssetClass), nullable=False)
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    ticker: Mapped[str | None] = mapped_column(String(20), nullable=True)
    cnpj: Mapped[str | None] = mapped_column(String(18), nullable=True)
    currency: Mapped[Currency] = mapped_column(Enum(Currency), nullable=False)
    current_price: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True)
    price_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
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
        Index(
            "ix_asset_external",
            "external_source",
            "external_id",
            sqlite_where=text("external_id IS NOT NULL"),
            postgresql_where=text("external_id IS NOT NULL"),
        ),
    )

    fixed_income: Mapped["FixedIncomeAsset | None"] = relationship(
        "FixedIncomeAsset",
        back_populates="asset",
        uselist=False,
        cascade="all, delete-orphan",
    )
    physical: Mapped["PhysicalAsset | None"] = relationship(
        "PhysicalAsset",
        back_populates="asset",
        uselist=False,
        cascade="all, delete-orphan",
    )


class FixedIncomeAsset(Base):
    __tablename__ = "fixed_income_asset"

    asset_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("asset.id", ondelete="CASCADE"),
        primary_key=True,
    )
    issuer: Mapped[str] = mapped_column(String(255), nullable=False)
    issue_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    maturity_date: Mapped[date] = mapped_column(Date, nullable=False)
    indexer: Mapped[FixedIncomeIndexer] = mapped_column(Enum(FixedIncomeIndexer), nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    face_value: Mapped[Decimal | None] = mapped_column(Numeric(15, 2), nullable=True)

    asset: Mapped["Asset"] = relationship("Asset", back_populates="fixed_income")


class PhysicalAsset(Base):
    __tablename__ = "physical_asset"

    asset_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("asset.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # Real-estate fields
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    state: Mapped[str | None] = mapped_column(String(50), nullable=True)
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    area_m2: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    registration_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Vehicle fields
    make: Mapped[str | None] = mapped_column(String(100), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    license_plate: Mapped[str | None] = mapped_column(String(20), nullable=True)
    chassis: Mapped[str | None] = mapped_column(String(50), nullable=True)

    asset: Mapped["Asset"] = relationship("Asset", back_populates="physical")
