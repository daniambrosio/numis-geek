import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import Date, DateTime, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from numis_geek.db.base import Base


class PTAXRate(Base):
    """Daily USD/BRL PTAX rate from BCB SGS.

    PTAX is a single rate fixed by BCB by averaging interbank trades on the
    business day. We use series 10813 (PTAX venda) — the canonical reference
    used for IRPF calculations on USD-denominated income.

    System-wide table — no workspace_id. One row per business day; weekend
    and holiday gaps are not filled. The FX service walks back to the
    previous business day's rate.
    """
    __tablename__ = "ptax_rate"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    date: Mapped[date] = mapped_column(Date, nullable=False, unique=True, index=True)
    rate: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="BCB_SGS")
    fetched_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
