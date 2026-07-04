"""Portfolio aggregations — Spec 20.

Single endpoint returns hero/donuts/custodians/top-holdings/12m history
for the current workspace (or for any workspace when sysadmin passes
?workspace_id=).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from numis_geek.api.deps import get_current_user, get_db
from numis_geek.models.user import UserRole
from numis_geek.services.auth import UserContext
from numis_geek.services.portfolio_summary import compute_portfolio_summary

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


# ── schemas ───────────────────────────────────────────────────────────────────

class ClassBreakdownOut(BaseModel):
    asset_class: str
    value_brl: float
    pct: float


class CountryBreakdownOut(BaseModel):
    country: str
    value_brl: float
    pct: float


class CustodianBreakdownOut(BaseModel):
    fi_id: str
    fi_short: str
    fi_logo_slug: str | None
    value_brl: float
    pct: float
    asset_count: int


class HoldingOut(BaseModel):
    asset_id: str
    ticker: str | None
    name: str
    asset_class: str
    country: str
    fi_short: str
    fi_logo_slug: str | None
    value_brl: float
    pct: float


class HistoryPointOut(BaseModel):
    period_end: str
    total_brl: float
    by_class: dict[str, float]


class PortfolioOut(BaseModel):
    as_of: str | None
    source: str  # "snapshot" | "live" | "empty"
    ptax_rate: float | None
    total_value_brl: float
    total_value_usd: float
    total_invested_brl: float
    total_received_brl: float
    received_by_type: dict[str, float]
    by_class: list[ClassBreakdownOut]
    by_country: list[CountryBreakdownOut]
    by_custodian: list[CustodianBreakdownOut]
    top_holdings: list[HoldingOut]
    history: list[HistoryPointOut]


# ── route ─────────────────────────────────────────────────────────────────────

@router.get("", response_model=PortfolioOut)
def get_portfolio(
    workspace_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    # Sysadmin híbrido (workspace_id no user): cai no dele por default;
    # ?workspace_id= sobrescreve pra ver outro. Sysadmin puro: precisa
    # do query param, senão 400.
    if current_user.role == UserRole.sysadmin:
        target_ws = workspace_id or current_user.workspace_id
        if target_ws is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="sysadmin must pass workspace_id.",
            )
    else:
        target_ws = current_user.workspace_id
        if workspace_id and workspace_id != target_ws:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cross-workspace access denied.",
            )

    summary = compute_portfolio_summary(db, target_ws)

    return PortfolioOut(
        as_of=summary.as_of,
        source=summary.source,
        ptax_rate=float(summary.ptax_rate) if summary.ptax_rate is not None else None,
        total_value_brl=float(summary.total_value_brl),
        total_value_usd=float(summary.total_value_usd),
        total_invested_brl=float(summary.total_invested_brl),
        total_received_brl=float(summary.total_received_brl),
        received_by_type={k: float(v) for k, v in summary.received_by_type.items()},
        by_class=[
            ClassBreakdownOut(
                asset_class=c.asset_class,
                value_brl=float(c.value_brl),
                pct=c.pct,
            )
            for c in summary.by_class
        ],
        by_country=[
            CountryBreakdownOut(
                country=c.country,
                value_brl=float(c.value_brl),
                pct=c.pct,
            )
            for c in summary.by_country
        ],
        by_custodian=[
            CustodianBreakdownOut(
                fi_id=c.fi_id,
                fi_short=c.fi_short,
                fi_logo_slug=c.fi_logo_slug,
                value_brl=float(c.value_brl),
                pct=c.pct,
                asset_count=c.asset_count,
            )
            for c in summary.by_custodian
        ],
        top_holdings=[
            HoldingOut(
                asset_id=h.asset_id,
                ticker=h.ticker,
                name=h.name,
                asset_class=h.asset_class,
                country=h.country,
                fi_short=h.fi_short,
                fi_logo_slug=h.fi_logo_slug,
                value_brl=float(h.value_brl),
                pct=h.pct,
            )
            for h in summary.top_holdings
        ],
        history=[
            HistoryPointOut(
                period_end=p.period_end,
                total_brl=float(p.total_brl),
                by_class={k: float(v) for k, v in p.by_class.items()},
            )
            for p in summary.history
        ],
    )
