"""Spec 61c — POST /portfolio/optimize (Markowitz)."""
from datetime import date as date_cls
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from numis_geek.api.deps import get_current_user, get_db
from numis_geek.models.user import UserRole
from numis_geek.models.workspace import Workspace
from numis_geek.services.auth import UserContext
from numis_geek.services.markowitz import (
    MarkowitzError, MarkowitzInput, MarkowitzResult,
    get_class_targets_from_db, optimize_portfolio,
)

router = APIRouter(prefix="/portfolio", tags=["markowitz"])


class OptimizeRequest(BaseModel):
    workspace_id: str | None = None
    class_targets: dict[str, Decimal] | None = None
    asset_cap: Decimal = Field(default=Decimal("0.15"), ge=0, le=1)
    country_caps: dict[str, Decimal] = Field(
        default_factory=lambda: {"BR": Decimal("0.70")}
    )
    min_months: int = Field(default=12, ge=2, le=120)
    ledoit_wolf_alpha: float = Field(default=0.05, ge=0.0, le=1.0)


class FrontierPointOut(BaseModel):
    ret: float
    vol: float


class OptimalOut(BaseModel):
    asset_id: str
    ticker: str | None
    name: str
    asset_class: str
    country: str
    weight: float
    current_weight: float
    delta: float
    target_value_brl: float
    current_value_brl: float
    trade_action: str
    trade_value_brl: float


class ExcludedOut(BaseModel):
    asset_id: str
    ticker: str | None
    name: str
    asset_class: str
    reason: str
    current_value_brl: float


class OptimizeOut(BaseModel):
    as_of: date_cls | None
    n_assets: int
    n_excluded: int
    total_value_brl: float
    expected_return: float
    volatility: float
    frontier: list[FrontierPointOut]
    optimal: list[OptimalOut]
    excluded: list[ExcludedOut]
    binding_constraints: list[str]
    warnings: list[str]

    @classmethod
    def from_result(cls, r: MarkowitzResult) -> "OptimizeOut":
        return cls(
            as_of=r.as_of,
            n_assets=r.n_assets,
            n_excluded=r.n_excluded,
            total_value_brl=r.total_value_brl,
            expected_return=r.expected_return,
            volatility=r.volatility,
            frontier=[FrontierPointOut(ret=p.ret, vol=p.vol) for p in r.frontier],
            optimal=[
                OptimalOut(
                    asset_id=o.asset_id, ticker=o.ticker, name=o.name,
                    asset_class=o.asset_class, country=o.country,
                    weight=o.weight, current_weight=o.current_weight,
                    delta=o.delta, target_value_brl=o.target_value_brl,
                    current_value_brl=o.current_value_brl,
                    trade_action=o.trade_action, trade_value_brl=o.trade_value_brl,
                ) for o in r.optimal
            ],
            excluded=[
                ExcludedOut(
                    asset_id=e.asset_id, ticker=e.ticker, name=e.name,
                    asset_class=e.asset_class, reason=e.reason,
                    current_value_brl=e.current_value_brl,
                ) for e in r.excluded
            ],
            binding_constraints=r.binding_constraints,
            warnings=r.warnings,
        )


def _resolve_workspace(
    db: Session, workspace_id: str | None, current_user: UserContext,
) -> str:
    if current_user.role == UserRole.sysadmin:
        ws_id = workspace_id or current_user.workspace_id
        if not ws_id:
            raise HTTPException(400, "sysadmin must specify workspace_id")
        ws = db.get(Workspace, ws_id)
        if not ws:
            raise HTTPException(404, "Workspace not found")
        return ws.id
    if workspace_id and workspace_id != current_user.workspace_id:
        raise HTTPException(403, "Cross-workspace access denied")
    if not current_user.workspace_id:
        raise HTTPException(400, "User has no workspace")
    return current_user.workspace_id


@router.post("/optimize", response_model=OptimizeOut)
def optimize(
    body: OptimizeRequest,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    ws_id = _resolve_workspace(db, body.workspace_id, current_user)
    # Default class_targets from target_allocation table if not provided.
    class_targets = body.class_targets
    if class_targets is None:
        loaded = get_class_targets_from_db(db, ws_id)
        if not loaded:
            raise HTTPException(
                400,
                "Sem target_allocation cadastrada (configure em "
                "/admin/target-allocation antes de otimizar).",
            )
        class_targets = {k: Decimal(str(v)) for k, v in loaded.items()}

    inp = MarkowitzInput(
        workspace_id=ws_id,
        class_targets=class_targets,
        asset_cap=body.asset_cap,
        country_caps=body.country_caps,
        min_months=body.min_months,
        ledoit_wolf_alpha=body.ledoit_wolf_alpha,
    )
    try:
        result = optimize_portfolio(db, inp)
    except MarkowitzError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e),
        )
    return OptimizeOut.from_result(result)
