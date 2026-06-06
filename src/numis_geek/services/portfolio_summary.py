"""Portfolio summary — aggregates the latest snapshot into donuts /
custodians / top-holdings / 12m history. See Spec 20.

Source: PortfolioSnapshot + PortfolioSnapshotItem (28 rows backfilled
from Notion). When current_price-driven live mode becomes reliable, the
service may switch to live positions; until then snapshot wins.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from numis_geek.models.account import Account
from numis_geek.models.asset import Asset, AssetClass
from numis_geek.models.distribution import Distribution, DistributionType
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.portfolio_snapshot import (
    PortfolioSnapshot,
    PortfolioSnapshotItem,
)


@dataclass
class ClassBreakdown:
    asset_class: str
    value_brl: Decimal
    pct: float


@dataclass
class CountryBreakdown:
    country: str
    value_brl: Decimal
    pct: float


@dataclass
class CustodianBreakdown:
    fi_id: str
    fi_short: str
    fi_logo_slug: str | None
    value_brl: Decimal
    pct: float
    asset_count: int


@dataclass
class HoldingOut:
    asset_id: str
    ticker: str | None
    name: str
    asset_class: str
    country: str
    fi_short: str
    fi_logo_slug: str | None
    value_brl: Decimal
    pct: float


@dataclass
class HistoryPoint:
    period_end: str  # ISO date
    total_brl: Decimal
    by_class: dict[str, Decimal] = field(default_factory=dict)


@dataclass
class PortfolioSummary:
    as_of: str | None  # ISO date of latest snapshot; None if no data
    source: str  # "snapshot" | "live" | "empty"
    ptax_rate: Decimal | None
    total_value_brl: Decimal
    total_value_usd: Decimal
    total_invested_brl: Decimal
    total_received_brl: Decimal  # all-time, derived from Distribution table
    received_by_type: dict[str, Decimal] = field(default_factory=dict)
        # All-time net BRL grouped by DistributionType — DIVIDEND, INTEREST,
        # JCP, SECURITIES_LENDING. Same source as total_received_brl.
    by_class: list[ClassBreakdown] = field(default_factory=list)
    by_country: list[CountryBreakdown] = field(default_factory=list)
    by_custodian: list[CustodianBreakdown] = field(default_factory=list)
    top_holdings: list[HoldingOut] = field(default_factory=list)
    history: list[HistoryPoint] = field(default_factory=list)


def _empty(source: str = "empty") -> PortfolioSummary:
    return PortfolioSummary(
        as_of=None,
        source=source,
        ptax_rate=None,
        total_value_brl=Decimal("0"),
        total_value_usd=Decimal("0"),
        total_invested_brl=Decimal("0"),
        total_received_brl=Decimal("0"),
        received_by_type={},
        by_class=[],
        by_country=[],
        by_custodian=[],
        top_holdings=[],
        history=[],
    )


def _pct(value: Decimal, total: Decimal) -> float:
    if total <= 0:
        return 0.0
    return float(value / total)


def _history(db: Session, workspace_id: str, limit: int = 12) -> list[HistoryPoint]:
    """Last `limit` snapshots ordered ASC with per-class breakdown."""
    snaps = (
        db.query(PortfolioSnapshot)
        .filter(
            PortfolioSnapshot.workspace_id == workspace_id,
            PortfolioSnapshot.is_active == True,  # noqa: E712
        )
        .order_by(PortfolioSnapshot.period_end_date.desc())
        .limit(limit)
        .all()
    )
    snaps.reverse()  # back to ASC for charts

    if not snaps:
        return []

    snap_ids = [s.id for s in snaps]
    rows = (
        db.query(
            PortfolioSnapshotItem.snapshot_id,
            Asset.asset_class,
            PortfolioSnapshotItem.market_value_brl,
        )
        .join(Asset, PortfolioSnapshotItem.asset_id == Asset.id)
        .filter(PortfolioSnapshotItem.snapshot_id.in_(snap_ids))
        .all()
    )

    by_snap: dict[str, dict[str, Decimal]] = {sid: {} for sid in snap_ids}
    for snap_id, cls, value in rows:
        if value is None:
            continue
        key = cls.value if hasattr(cls, "value") else str(cls)
        bucket = by_snap[snap_id]
        bucket[key] = bucket.get(key, Decimal("0")) + value

    return [
        HistoryPoint(
            period_end=s.period_end_date.isoformat(),
            total_brl=s.total_value_brl,
            by_class=by_snap.get(s.id, {}),
        )
        for s in snaps
    ]


def _net_amount_brl_expr():
    """SQL expression: BRL distributions use net_amount as-is; USD ones
    multiply by fx_rate (PTAX). Spec 56."""
    return case(
        (Distribution.currency == "USD", Distribution.net_amount * Distribution.fx_rate),
        else_=Distribution.net_amount,
    )


def _total_received_brl(db: Session, workspace_id: str) -> Decimal:
    """All-time sum of Distribution net_amount (BRL-equiv) for the workspace.
    Includes distributions whose underlying asset is now inactive — they
    still happened historically. Excludes deactivated distribution rows."""
    total = (
        db.query(func.sum(_net_amount_brl_expr()))
        .filter(
            Distribution.workspace_id == workspace_id,
            Distribution.is_active == True,  # noqa: E712
        )
        .scalar()
    )
    return Decimal(total) if total is not None else Decimal("0")


def _received_by_type(db: Session, workspace_id: str) -> dict[str, Decimal]:
    """Same scope as _total_received_brl but grouped by DistributionType.
    Always returns every type key (zero when no rows) so the UI doesn't
    need to defend against missing entries."""
    rows = (
        db.query(
            Distribution.type,
            func.sum(_net_amount_brl_expr()),
        )
        .filter(
            Distribution.workspace_id == workspace_id,
            Distribution.is_active == True,  # noqa: E712
        )
        .group_by(Distribution.type)
        .all()
    )
    out: dict[str, Decimal] = {t.value: Decimal("0") for t in DistributionType}
    for type_val, total in rows:
        key = type_val.value if hasattr(type_val, "value") else str(type_val)
        out[key] = Decimal(total) if total is not None else Decimal("0")
    return out


def compute_portfolio_summary(
    db: Session, workspace_id: str
) -> PortfolioSummary:
    """Aggregate the latest snapshot for `workspace_id`. Returns empty
    structure when no snapshot exists."""
    latest = (
        db.query(PortfolioSnapshot)
        .filter(
            PortfolioSnapshot.workspace_id == workspace_id,
            PortfolioSnapshot.is_active == True,  # noqa: E712
        )
        .order_by(PortfolioSnapshot.period_end_date.desc())
        .first()
    )
    if not latest:
        empty = _empty()
        # Even with no snapshot, total_received_brl and the per-type
        # breakdown can be reported from Distribution rows directly.
        empty.total_received_brl = _total_received_brl(db, workspace_id)
        empty.received_by_type = _received_by_type(db, workspace_id)
        return empty

    # Pull items + joined asset/account/fi for the latest snapshot.
    rows = (
        db.query(
            PortfolioSnapshotItem,
            Asset,
            Account,
            FinancialInstitution,
        )
        .join(Asset, PortfolioSnapshotItem.asset_id == Asset.id)
        .join(Account, Asset.account_id == Account.id)
        .join(
            FinancialInstitution,
            Account.financial_institution_id == FinancialInstitution.id,
        )
        .filter(PortfolioSnapshotItem.snapshot_id == latest.id)
        .all()
    )

    total_brl = sum(
        (r[0].market_value_brl or Decimal("0") for r in rows), Decimal("0")
    )

    # Aggregations.
    by_class: dict[str, Decimal] = {}
    by_country: dict[str, Decimal] = {}
    by_cust_value: dict[str, Decimal] = {}
    by_cust_meta: dict[str, FinancialInstitution] = {}
    by_cust_count: dict[str, int] = {}

    for item, asset, account, fi in rows:
        v = item.market_value_brl or Decimal("0")
        cls = asset.asset_class.value
        by_class[cls] = by_class.get(cls, Decimal("0")) + v
        by_country[asset.country] = by_country.get(asset.country, Decimal("0")) + v
        by_cust_value[fi.id] = by_cust_value.get(fi.id, Decimal("0")) + v
        by_cust_meta[fi.id] = fi
        by_cust_count[fi.id] = by_cust_count.get(fi.id, 0) + 1

    class_breakdowns = sorted(
        [
            ClassBreakdown(
                asset_class=k, value_brl=v, pct=_pct(v, total_brl)
            )
            for k, v in by_class.items()
        ],
        key=lambda x: x.value_brl,
        reverse=True,
    )

    country_breakdowns = sorted(
        [
            CountryBreakdown(country=k, value_brl=v, pct=_pct(v, total_brl))
            for k, v in by_country.items()
        ],
        key=lambda x: x.value_brl,
        reverse=True,
    )

    custodian_breakdowns = sorted(
        [
            CustodianBreakdown(
                fi_id=fi_id,
                fi_short=by_cust_meta[fi_id].short_name,
                fi_logo_slug=by_cust_meta[fi_id].logo_slug,
                value_brl=v,
                pct=_pct(v, total_brl),
                asset_count=by_cust_count[fi_id],
            )
            for fi_id, v in by_cust_value.items()
        ],
        key=lambda x: x.value_brl,
        reverse=True,
    )

    # Top 10 holdings.
    holdings = sorted(rows, key=lambda r: r[0].market_value_brl or 0, reverse=True)[:10]
    top_holdings = [
        HoldingOut(
            asset_id=asset.id,
            ticker=asset.ticker,
            name=asset.name,
            asset_class=asset.asset_class.value,
            country=asset.country,
            fi_short=fi.short_name,
            fi_logo_slug=fi.logo_slug,
            value_brl=item.market_value_brl or Decimal("0"),
            pct=_pct(item.market_value_brl or Decimal("0"), total_brl),
        )
        for item, asset, account, fi in holdings
    ]

    return PortfolioSummary(
        as_of=latest.period_end_date.isoformat(),
        source="snapshot",
        ptax_rate=latest.fx_rate_usd_brl,
        total_value_brl=latest.total_value_brl,
        total_value_usd=latest.total_value_usd,
        total_invested_brl=latest.total_invested_brl,
        total_received_brl=_total_received_brl(db, workspace_id),
        received_by_type=_received_by_type(db, workspace_id),
        by_class=class_breakdowns,
        by_country=country_breakdowns,
        by_custodian=custodian_breakdowns,
        top_holdings=top_holdings,
        history=_history(db, workspace_id, limit=12),
    )
