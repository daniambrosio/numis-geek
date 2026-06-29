from datetime import date as date_cls
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from numis_geek.api.deps import get_current_user, get_db
from numis_geek.models.asset import Asset
from numis_geek.models.asset_fundamentals import AssetFundamentals
from numis_geek.models.user import UserRole
from numis_geek.services.audit import AuditService
from numis_geek.services.auth import UserContext
from numis_geek.services.fundamentals_ingest import refresh_asset_fundamentals
from numis_geek.services.valuation import (
    ValuationMetric, ValuationResult, value_asset,
)

router = APIRouter(prefix="/assets", tags=["valuation"])


class MetricOut(BaseModel):
    name: str
    value: Decimal | None
    unit: str
    interpretation: str


class ValuationOut(BaseModel):
    asset_id: str
    asset_class: str
    currency: str
    verdict: str
    verdict_reason: str
    metrics: list[MetricOut]
    disqualifying: list[str]
    fundamentals_as_of: date_cls | None
    fundamentals_source: str | None
    is_stale: bool

    @classmethod
    def from_result(cls, r: ValuationResult) -> "ValuationOut":
        return cls(
            asset_id=r.asset_id,
            asset_class=r.asset_class,
            currency=r.currency,
            verdict=r.verdict,
            verdict_reason=r.verdict_reason,
            metrics=[
                MetricOut(
                    name=m.name, value=m.value, unit=m.unit,
                    interpretation=m.interpretation,
                ) for m in r.metrics
            ],
            disqualifying=r.disqualifying,
            fundamentals_as_of=r.fundamentals_as_of,
            fundamentals_source=r.fundamentals_source,
            is_stale=r.is_stale,
        )


class FundamentalsOut(BaseModel):
    asset_id: str
    snapshot_date: date_cls
    source: str
    pe: Decimal | None
    pb: Decimal | None
    eps: Decimal | None
    bvps: Decimal | None
    roe: Decimal | None
    dividend_yield_12m: Decimal | None
    dps_12m: Decimal | None
    p_vp: Decimal | None
    p_ffo: Decimal | None
    payout_ratio: Decimal | None
    earnings_growth_5y: Decimal | None
    debt_ebitda: Decimal | None
    net_margin: Decimal | None
    ebitda_margin: Decimal | None
    vacancy: Decimal | None
    distribution_coverage: Decimal | None
    expense_ratio: Decimal | None
    aum: Decimal | None
    ytm: Decimal | None
    duration: Decimal | None

    @classmethod
    def from_orm(cls, f: AssetFundamentals) -> "FundamentalsOut":
        return cls(
            asset_id=f.asset_id,
            snapshot_date=f.snapshot_date,
            source=f.source.value,
            pe=f.pe, pb=f.pb, eps=f.eps, bvps=f.bvps, roe=f.roe,
            dividend_yield_12m=f.dividend_yield_12m,
            dps_12m=f.dps_12m, p_vp=f.p_vp, p_ffo=f.p_ffo,
            payout_ratio=f.payout_ratio,
            earnings_growth_5y=f.earnings_growth_5y,
            debt_ebitda=f.debt_ebitda,
            net_margin=f.net_margin, ebitda_margin=f.ebitda_margin,
            vacancy=f.vacancy,
            distribution_coverage=f.distribution_coverage,
            expense_ratio=f.expense_ratio, aum=f.aum,
            ytm=f.ytm, duration=f.duration,
        )


def _get_asset_or_404(
    db: Session, asset_id: str, current_user: UserContext,
) -> Asset:
    asset = db.get(Asset, asset_id)
    if not asset:
        raise HTTPException(404, "Asset not found")
    if (
        current_user.role != UserRole.sysadmin
        and asset.workspace_id != current_user.workspace_id
    ):
        raise HTTPException(403, "Workspace access denied")
    return asset


@router.get("/{asset_id}/valuation", response_model=ValuationOut)
def get_valuation(
    asset_id: str,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    asset = _get_asset_or_404(db, asset_id, current_user)
    return ValuationOut.from_result(value_asset(db, asset))


@router.get("/{asset_id}/fundamentals", response_model=FundamentalsOut | None)
def get_fundamentals(
    asset_id: str,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    asset = _get_asset_or_404(db, asset_id, current_user)
    fund = (
        db.query(AssetFundamentals)
        .filter(AssetFundamentals.asset_id == asset.id)
        .order_by(AssetFundamentals.snapshot_date.desc())
        .first()
    )
    if not fund:
        return None
    return FundamentalsOut.from_orm(fund)


@router.post("/{asset_id}/fundamentals/refresh", response_model=FundamentalsOut | None)
def refresh_fundamentals(
    asset_id: str,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    if current_user.role not in (UserRole.admin, UserRole.sysadmin):
        raise HTTPException(403, "Admin only")
    asset = _get_asset_or_404(db, asset_id, current_user)
    try:
        row = refresh_asset_fundamentals(db, asset, force=True)
    except Exception as e:
        raise HTTPException(502, f"Provider error: {e}")
    AuditService(db).log(
        user_email=current_user.user_id,
        action="fundamentals.refresh",
        workspace_id=asset.workspace_id,
        user_id=current_user.user_id,
        resource_type="asset",
        resource_id=asset.id,
        details={"source": row.source.value if row else None},
    )
    return FundamentalsOut.from_orm(row) if row else None
