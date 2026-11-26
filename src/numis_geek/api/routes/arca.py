"""Spec 85 — ARCA: resumo, simulador de aporte e classificação dos ativos."""
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from numis_geek.api.deps import get_current_user, get_db
from numis_geek.api.routes.target_allocation import _resolve_workspace
from numis_geek.models.arca import ArcaCategory, ArcaSubcategory
from numis_geek.models.asset import Asset
from numis_geek.services.arca import (
    ArcaClassificationError,
    ArcaPlanError,
    arca_summary,
    contribution_plan,
    set_classification,
)
from numis_geek.services.auth import UserContext

router = APIRouter(prefix="/workspaces", tags=["arca"])


# ── Schemas ──


class ArcaAssetOut(BaseModel):
    asset_id: str
    ticker: str | None
    name: str
    asset_class: str
    country: str
    category: str | None
    subcategory: str | None
    derived_category: str | None
    derived_subcategory: str | None
    source: str
    value_brl: Decimal
    income_12m_brl: Decimal
    derived_note: str = ""


class ArcaSubOut(BaseModel):
    key: str
    role: str
    value_brl: Decimal
    pct_of_letter: float
    pct_of_total: float
    target_pct_of_letter: Decimal | None
    target_pct_of_total: Decimal | None
    gap_brl: Decimal | None
    income_12m_brl: Decimal
    yield_12m: float | None


class ArcaLetterOut(BaseModel):
    key: str
    value_brl: Decimal
    current_pct: float
    target_pct: Decimal | None
    min_pct: Decimal
    max_pct: Decimal
    gap_brl: Decimal | None
    status: str
    income_12m_brl: Decimal
    yield_12m: float | None
    income_share: float
    income_forward_brl: Decimal
    unclassified_sub_value_brl: Decimal
    subcategories: list[ArcaSubOut]


class ArcaSummaryOut(BaseModel):
    as_of: str | None
    total_brl: Decimal
    out_of_scope_brl: Decimal
    unmapped_brl: Decimal
    unmapped_count: int
    income_12m_total_brl: Decimal
    attack_pct: float
    defense_pct: float
    unknown_role_pct: float
    targets_configured: bool
    letters: list[ArcaLetterOut]
    assets: list[ArcaAssetOut]


class PlanRequest(BaseModel):
    amount_brl: Decimal = Field(gt=0)


class PlanSubOut(BaseModel):
    key: str
    amount_brl: Decimal


class PlanLetterOut(BaseModel):
    key: str
    current_brl: Decimal
    amount_brl: Decimal
    after_brl: Decimal
    after_pct: float
    target_pct: Decimal
    sell_suggestion_brl: Decimal
    subcategories: list[PlanSubOut]


class PlanOut(BaseModel):
    amount_brl: Decimal
    total_after_brl: Decimal
    letters: list[PlanLetterOut]


class ClassificationItem(BaseModel):
    asset_id: str
    category: ArcaCategory | None = None
    subcategory: ArcaSubcategory | None = None


class ClassificationRequest(BaseModel):
    items: list[ClassificationItem] = Field(min_length=1, max_length=500)


# ── Routes ──


@router.get("/{workspace_id}/arca/summary", response_model=ArcaSummaryOut)
def get_arca_summary(
    workspace_id: str,
    db: Session = Depends(get_db, scope="function"),
    current_user: UserContext = Depends(get_current_user),
):
    ws_id = _resolve_workspace(db, workspace_id, current_user)
    s = arca_summary(db, ws_id)
    return ArcaSummaryOut.model_validate(s, from_attributes=True)


@router.post("/{workspace_id}/arca/contribution-plan", response_model=PlanOut)
def post_contribution_plan(
    workspace_id: str,
    body: PlanRequest,
    db: Session = Depends(get_db, scope="function"),
    current_user: UserContext = Depends(get_current_user),
):
    ws_id = _resolve_workspace(db, workspace_id, current_user)
    try:
        plan = contribution_plan(db, ws_id, body.amount_brl)
    except ArcaPlanError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return PlanOut.model_validate(plan, from_attributes=True)


@router.put("/{workspace_id}/arca/classification", response_model=ArcaSummaryOut)
def put_classification(
    workspace_id: str,
    body: ClassificationRequest,
    db: Session = Depends(get_db, scope="function"),
    current_user: UserContext = Depends(get_current_user),
):
    """Grava o override ARCA de um ou mais ativos (category/subcategory
    nulos = volta para a regra automática). Mesma permissão de editar ativo:
    qualquer usuário do workspace; sysadmin em qualquer um."""
    ws_id = _resolve_workspace(db, workspace_id, current_user)
    for item in body.items:
        asset = db.get(Asset, item.asset_id)
        if not asset or asset.workspace_id != ws_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found.")
        try:
            set_classification(
                db,
                asset,
                item.category.value if item.category else None,
                item.subcategory.value if item.subcategory else None,
                user_email=current_user.user_id,
                user_id=current_user.user_id,
            )
        except ArcaClassificationError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{asset.name}: {exc}",
            )
    return ArcaSummaryOut.model_validate(arca_summary(db, ws_id), from_attributes=True)
