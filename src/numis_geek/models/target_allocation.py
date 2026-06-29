import enum
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from numis_geek.db.base import Base


class TargetAllocationDimension(str, enum.Enum):
    CLASS = "CLASS"
    COUNTRY = "COUNTRY"


class TargetAllocation(Base):
    """Workspace-scoped allocation targets used by Decision Support.

    Each row holds one (dimension, key) → target_pct entry.
    `dimension=CLASS` keys are AssetClass.value (STOCK, REIT, ...).
    `dimension=COUNTRY` keys are ISO-2 (BR, US, ...).
    `target_pct` is a decimal in [0, 1]. Per dimension the sum must equal 1.0
    (validated at the service layer).

    Markowitz uses CLASS entries as equality constraints and COUNTRY entries
    as caps (see spec 61c).
    """

    __tablename__ = "target_allocation"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspace.id"), nullable=False
    )
    dimension: Mapped[TargetAllocationDimension] = mapped_column(
        Enum(TargetAllocationDimension), nullable=False
    )
    key: Mapped[str] = mapped_column(String(32), nullable=False)
    target_pct: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "dimension", "key",
            name="ux_target_allocation_ws_dim_key",
        ),
    )
