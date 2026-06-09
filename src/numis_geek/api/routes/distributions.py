import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from numis_geek.api.deps import get_current_user, get_db
from numis_geek.models.account import Account, Currency
from numis_geek.models.asset import Asset, AssetClass
from numis_geek.models.asset_movement import AssetMovement, AssetMovementType
from numis_geek.models.distribution import (
    DISTRIBUTION_TYPE_LABELS,
    Distribution,
    DistributionType,
)
from numis_geek.models.external import ExternalSource
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.user import User, UserRole
from numis_geek.models.workspace import Workspace
from numis_geek.services.audit import AuditService
from numis_geek.services.fx import resolve_fx_rate
from numis_geek.services.auth import UserContext
from numis_geek.services.proventos import (
    aggregate_proventos,
    Breakdown,
    Currency as ChartCurrency,
    Period,
)
from numis_geek.utils.audit_diff import diff as audit_diff, snapshot as audit_snapshot

# Fields tracked in the audit diff on update (Spec 37).
_TRACKED_FIELDS = [
    "financial_institution_id", "asset_id", "type", "event_date",
    "gross_amount", "tax", "net_amount", "currency", "fx_rate", "notes",
]

router = APIRouter(prefix="/distributions", tags=["distributions"])


# ── Chart schemas (Spec 30) ─────────────────────────────────────────────────


class ChartSegmentOut(BaseModel):
    key: str
    label: str
    color: str
    value: float | None = None


class ChartRowOut(BaseModel):
    ym: str
    total: float
    segments: list[ChartSegmentOut]


class ChartTotalsOut(BaseModel):
    sum: float
    monthly_avg: float
    max: float


class ChartDataOut(BaseModel):
    rows: list[ChartRowOut]
    legend: list[ChartSegmentOut]
    totals: ChartTotalsOut
    currency: str


# ── Schemas ──────────────────────────────────────────────────────────────────

class DistributionRequest(BaseModel):
    financial_institution_id: str
    asset_id: str | None = None
    type: DistributionType
    event_date: date
    gross_amount: Decimal
    tax: Decimal | None = None
    net_amount: Decimal | None = None
    currency: Currency | None = None
    fx_rate: Decimal | None = None
    notes: str | None = None
    external_id: str | None = Field(default=None, max_length=255)
    external_source: ExternalSource | None = None
    workspace_id: str | None = None  # sysadmin only

    @model_validator(mode="after")
    def _validate(self) -> "DistributionRequest":
        if self.event_date > date.today():
            raise ValueError("event_date cannot be in the future.")
        if self.gross_amount <= 0:
            raise ValueError("gross_amount must be > 0.")
        if self.tax is not None and self.tax < 0:
            raise ValueError("tax cannot be negative.")
        if self.fx_rate is not None and self.fx_rate <= 0:
            raise ValueError("fx_rate must be > 0.")
        return self


class DistributionOut(BaseModel):
    id: str
    workspace_id: str
    financial_institution_id: str
    financial_institution_name: str
    asset_id: str | None
    asset_name: str | None
    asset_ticker: str | None
    type: str
    type_label: str
    event_date: str
    gross_amount: float
    tax: float | None
    net_amount: float
    currency: str
    fx_rate: float
    notes: str | None
    external_id: str | None = None
    external_source: str | None = None
    is_active: bool
    created_at: str
    updated_at: str

    @classmethod
    def from_orm(
        cls,
        d: Distribution,
        *,
        fi_name: str,
        asset_name: str | None,
        asset_ticker: str | None,
    ) -> "DistributionOut":
        return cls(
            id=d.id,
            workspace_id=d.workspace_id,
            financial_institution_id=d.financial_institution_id,
            financial_institution_name=fi_name,
            asset_id=d.asset_id,
            asset_name=asset_name,
            asset_ticker=asset_ticker,
            type=d.type.value,
            type_label=DISTRIBUTION_TYPE_LABELS[d.type],
            event_date=d.event_date.isoformat(),
            gross_amount=float(d.gross_amount),
            tax=float(d.tax) if d.tax is not None else None,
            net_amount=float(d.net_amount),
            currency=d.currency.value,
            fx_rate=float(d.fx_rate),
            notes=d.notes,
            external_id=d.external_id,
            external_source=d.external_source.value if d.external_source else None,
            is_active=d.is_active,
            created_at=d.created_at.isoformat(),
            updated_at=d.updated_at.isoformat(),
        )


class SyntheticPremiumOut(BaseModel):
    """OPTION_PREMIUM sintético derivado de AssetMovement SELL_OPEN/
    BUY_TO_CLOSE em assets OPTION. Não persistido — computado on the fly.
    Shape paralelo ao DistributionOut pra facilitar agregação na UI, mas
    em campo separado pra não confundir com Distribution real."""
    id: str            # 'synthetic:<movement_id>'
    movement_id: str
    workspace_id: str
    financial_institution_id: str | None
    financial_institution_name: str | None
    asset_id: str | None         # underlying do option (não o option em si)
    underlying_ticker: str | None
    option_asset_id: str
    option_ticker: str | None
    type: str          # sempre 'OPTION_PREMIUM'
    type_label: str    # 'Prêmio sintético'
    side: str          # SELL_OPEN ou BUY_TO_CLOSE
    event_date: str
    gross_amount: float
    net_amount: float
    currency: str
    fx_rate: float


class DistributionListPage(BaseModel):
    items: list[DistributionOut]
    synthetic_premiums: list[SyntheticPremiumOut] = []
    total: int
    page: int
    page_size: int


# ── Helpers ──────────────────────────────────────────────────────────────────

def _get_or_404(db: Session, did: str) -> Distribution:
    d = db.get(Distribution, did)
    if not d:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Distribution not found.")
    return d


def _check_workspace_access(d: Distribution, current_user: UserContext) -> None:
    if current_user.role == UserRole.sysadmin:
        return
    if d.workspace_id != current_user.workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Distribution not found.")


def _resolve_workspace_id(body: DistributionRequest, current_user: UserContext, db: Session) -> str:
    if current_user.role == UserRole.sysadmin:
        if not body.workspace_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="workspace_id is required when creating distributions as sysadmin.",
            )
        if not db.get(Workspace, body.workspace_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.")
        return body.workspace_id
    if not current_user.workspace_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No workspace bound to user.")
    return current_user.workspace_id


def _resolve_fi(db: Session, fi_id: str) -> FinancialInstitution:
    fi = db.get(FinancialInstitution, fi_id)
    if not fi:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Financial institution not found.")
    return fi


def _resolve_asset(
    db: Session,
    asset_id: str | None,
    workspace_id: str,
    current_user: UserContext,
) -> Asset | None:
    if asset_id is None:
        return None
    asset = db.get(Asset, asset_id)
    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found.")
    if current_user.role != UserRole.sysadmin and asset.workspace_id != workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found.")
    if current_user.role == UserRole.sysadmin and asset.workspace_id != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Asset belongs to a different workspace.",
        )
    return asset


def _compute_net(body: DistributionRequest) -> Decimal:
    if body.net_amount is not None:
        return body.net_amount
    return body.gross_amount - (body.tax or Decimal("0"))


def _audit(
    db: Session,
    current_user: UserContext,
    action: str,
    d: Distribution,
    *,
    diff: dict | None = None,
) -> None:
    actor = db.get(User, current_user.user_id)
    details: dict = {
        "asset_id": d.asset_id,
        "type": d.type.value,
        "event_date": d.event_date.isoformat(),
    }
    if diff is not None:
        details["diff"] = diff
    AuditService(db).log(
        user_email=actor.email if actor else current_user.user_id,
        action=action,
        workspace_id=d.workspace_id,
        user_id=current_user.user_id,
        resource_type="distribution",
        resource_id=d.id,
        details=details,
    )


def _hydrate(
    db: Session, rows: list[Distribution],
) -> tuple[dict[str, FinancialInstitution], dict[str, Asset]]:
    fi_ids = {d.financial_institution_id for d in rows}
    asset_ids = {d.asset_id for d in rows if d.asset_id}
    fis = (
        {f.id: f for f in db.query(FinancialInstitution).filter(FinancialInstitution.id.in_(fi_ids)).all()}
        if fi_ids
        else {}
    )
    assets = (
        {a.id: a for a in db.query(Asset).filter(Asset.id.in_(asset_ids)).all()}
        if asset_ids
        else {}
    )
    return fis, assets


def _build_synthetic_premiums(
    db: Session,
    *,
    workspace_id: str | None,
    asset_id: str | None,
    financial_institution_id: str | None,
    from_: date | None,
    to: date | None,
) -> list[SyntheticPremiumOut]:
    """Deriva OPTION_PREMIUM sintético dos AssetMovement SELL_OPEN/
    BUY_TO_CLOSE em assets OPTION. Mesma regra do
    services/proventos.py:list_proventos — só que devolve no shape
    consumido pela KPI do snapshot."""
    q = (
        db.query(AssetMovement, Asset)
        .join(Asset, Asset.id == AssetMovement.asset_id)
        .filter(
            Asset.asset_class == AssetClass.OPTION,
            AssetMovement.type.in_([
                AssetMovementType.SELL_OPEN,
                AssetMovementType.BUY_TO_CLOSE,
            ]),
            AssetMovement.is_active.is_(True),
        )
    )
    if workspace_id:
        q = q.filter(AssetMovement.workspace_id == workspace_id)
    if asset_id:
        # asset_id filtra pelo underlying (mesma convenção do list_proventos).
        q = q.filter(Asset.underlying_id == asset_id)
    if from_:
        q = q.filter(AssetMovement.event_date >= from_)
    if to:
        q = q.filter(AssetMovement.event_date <= to)

    rows = q.all()
    if not rows:
        return []

    # Resolve FI via Asset.account_id + filtra se foi pedido.
    fi_cache: dict[str, FinancialInstitution | None] = {}
    underlying_cache: dict[str, Asset | None] = {}
    out: list[SyntheticPremiumOut] = []
    for m, opt in rows:
        acc = db.get(Account, opt.account_id) if opt.account_id else None
        fi_id = acc.financial_institution_id if acc else None
        if financial_institution_id and fi_id != financial_institution_id:
            continue
        if fi_id and fi_id not in fi_cache:
            fi_cache[fi_id] = db.get(FinancialInstitution, fi_id)
        fi = fi_cache.get(fi_id) if fi_id else None
        if opt.underlying_id and opt.underlying_id not in underlying_cache:
            underlying_cache[opt.underlying_id] = db.get(Asset, opt.underlying_id)
        underlying = underlying_cache.get(opt.underlying_id) if opt.underlying_id else None
        # AssetMovement.fx_rate armazena PTAX do dia mesmo pra movements BRL
        # (convenção [[multicurrency_fx_rate_design]]). Distribution/aggregator
        # esperam fx_rate como MULTIPLICADOR pra BRL: 1.0 quando nativo já é
        # BRL, PTAX quando nativo é USD. Sem essa normalização, a KPI multi-
        # plicava 90 BRL × 4.988 = R$ 449 — inflando ~5x. Espelha o pattern
        # do services/proventos.py:273 (eff_fx = 1 if BRL else fx_rate).
        eff_fx = float(m.fx_rate) if m.currency.value == "USD" else 1.0
        out.append(SyntheticPremiumOut(
            id=f"synthetic:{m.id}",
            movement_id=m.id,
            workspace_id=m.workspace_id,
            financial_institution_id=fi_id,
            financial_institution_name=fi.short_name if fi else None,
            asset_id=opt.underlying_id,
            underlying_ticker=underlying.ticker if underlying else None,
            option_asset_id=opt.id,
            option_ticker=opt.ticker,
            type="OPTION_PREMIUM",
            type_label="Prêmio sintético",
            side=m.type.value,
            event_date=m.event_date.isoformat(),
            gross_amount=float(m.net_amount),  # mesma convenção do services/proventos
            net_amount=float(m.net_amount),
            currency=m.currency.value,
            fx_rate=eff_fx,
        ))
    return out


# ── Routes ───────────────────────────────────────────────────────────────────

@router.get("", response_model=DistributionListPage)
def list_distributions(
    asset_id: str | None = Query(default=None),
    financial_institution_id: str | None = Query(default=None),
    type: DistributionType | None = Query(default=None),
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = Query(default=None),
    include_inactive: bool = Query(default=False),
    include_synthetic: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    workspace_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    q = db.query(Distribution)
    if not include_inactive:
        q = q.filter(Distribution.is_active == True)  # noqa: E712

    if current_user.role == UserRole.sysadmin:
        if workspace_id:
            q = q.filter(Distribution.workspace_id == workspace_id)
    else:
        q = q.filter(Distribution.workspace_id == current_user.workspace_id)

    if asset_id:
        q = q.filter(Distribution.asset_id == asset_id)
    if financial_institution_id:
        q = q.filter(Distribution.financial_institution_id == financial_institution_id)
    if type:
        q = q.filter(Distribution.type == type)
    if from_:
        q = q.filter(Distribution.event_date >= from_)
    if to:
        q = q.filter(Distribution.event_date <= to)

    total = q.count()
    rows = (
        q.order_by(Distribution.event_date.desc(), Distribution.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    fis, assets = _hydrate(db, rows)
    items = [
        DistributionOut.from_orm(
            d,
            fi_name=fis[d.financial_institution_id].short_name if d.financial_institution_id in fis else d.financial_institution_id,
            asset_name=assets[d.asset_id].name if d.asset_id and d.asset_id in assets else None,
            asset_ticker=assets[d.asset_id].ticker if d.asset_id and d.asset_id in assets else None,
        )
        for d in rows
    ]
    synthetic_premiums: list[SyntheticPremiumOut] = []
    if include_synthetic:
        ws_filter = current_user.workspace_id
        if current_user.role == UserRole.sysadmin:
            ws_filter = workspace_id  # None ⇒ cross-workspace pra sysadmin
        synthetic_premiums = _build_synthetic_premiums(
            db,
            workspace_id=ws_filter,
            asset_id=asset_id,
            financial_institution_id=financial_institution_id,
            from_=from_,
            to=to,
        )

    return DistributionListPage(
        items=items, synthetic_premiums=synthetic_premiums,
        total=total, page=page, page_size=page_size,
    )


@router.get("/chart", response_model=ChartDataOut)
def get_distributions_chart(
    period: Period = Query(default="12m"),
    breakdown: Breakdown = Query(default="klass"),
    currency: ChartCurrency = Query(default="BRL"),
    include_synthetic: bool = Query(default=True),
    workspace_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    """Spec 30 — monthly proventos chart data for /distributions and /dashboard.

    Aggregates real distributions + synthetic OPTION_PREMIUM rows into
    monthly buckets by the chosen breakdown dimension, in BRL or USD.
    """
    if current_user.role == UserRole.sysadmin:
        if workspace_id and not db.get(Workspace, workspace_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found."
            )
        ws = workspace_id  # None = cross-workspace
    else:
        if not current_user.workspace_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No workspace bound to user.",
            )
        if workspace_id and workspace_id != current_user.workspace_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cross-workspace not allowed.",
            )
        ws = current_user.workspace_id

    data = aggregate_proventos(
        db, ws,
        period=period,
        breakdown=breakdown,
        currency=currency,
        include_synthetic=include_synthetic,
    )

    return ChartDataOut(
        rows=[
            ChartRowOut(
                ym=r.ym,
                total=float(r.total),
                segments=[
                    ChartSegmentOut(
                        key=s.key, label=s.label, color=s.color,
                        value=float(s.value) if s.value is not None else None,
                    )
                    for s in r.segments
                ],
            )
            for r in data.rows
        ],
        legend=[
            ChartSegmentOut(key=s.key, label=s.label, color=s.color, value=None)
            for s in data.legend
        ],
        totals=ChartTotalsOut(
            sum=float(data.totals.sum),
            monthly_avg=float(data.totals.monthly_avg),
            max=float(data.totals.max),
        ),
        currency=data.currency,
    )


@router.get("/{did}", response_model=DistributionOut)
def get_distribution(
    did: str,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    d = _get_or_404(db, did)
    _check_workspace_access(d, current_user)
    fi = db.get(FinancialInstitution, d.financial_institution_id)
    asset = db.get(Asset, d.asset_id) if d.asset_id else None
    return DistributionOut.from_orm(
        d,
        fi_name=fi.short_name if fi else d.financial_institution_id,
        asset_name=asset.name if asset else None,
        asset_ticker=asset.ticker if asset else None,
    )


@router.post("", response_model=DistributionOut, status_code=status.HTTP_201_CREATED)
def create_distribution(
    body: DistributionRequest,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    workspace_id = _resolve_workspace_id(body, current_user, db)
    fi = _resolve_fi(db, body.financial_institution_id)
    asset = _resolve_asset(db, body.asset_id, workspace_id, current_user)

    currency = body.currency or (asset.currency if asset else Currency.BRL)
    if asset and currency != asset.currency:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Distribution currency must match asset's ({asset.currency.value}).",
        )
    fx_rate = resolve_fx_rate(db, body.event_date, client_value=body.fx_rate)
    net = _compute_net(body)

    now = datetime.now(timezone.utc)
    d = Distribution(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        financial_institution_id=fi.id,
        asset_id=asset.id if asset else None,
        type=body.type,
        event_date=body.event_date,
        gross_amount=body.gross_amount,
        tax=body.tax,
        net_amount=net,
        currency=currency,
        fx_rate=fx_rate,
        notes=body.notes,
        external_id=body.external_id,
        external_source=body.external_source,
        is_active=True,
        created_at=now,
        updated_at=now,
        created_by=current_user.user_id,
        updated_by=current_user.user_id,
    )
    db.add(d)
    db.flush()
    _audit(db, current_user, "distribution.created", d)

    return DistributionOut.from_orm(
        d,
        fi_name=fi.short_name,
        asset_name=asset.name if asset else None,
        asset_ticker=asset.ticker if asset else None,
    )


@router.put("/{did}", response_model=DistributionOut)
def update_distribution(
    did: str,
    body: DistributionRequest,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    d = _get_or_404(db, did)
    _check_workspace_access(d, current_user)

    workspace_id = d.workspace_id
    fi = _resolve_fi(db, body.financial_institution_id)
    asset = _resolve_asset(db, body.asset_id, workspace_id, current_user)

    currency = body.currency or (asset.currency if asset else Currency.BRL)
    if asset and currency != asset.currency:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Distribution currency must match asset's ({asset.currency.value}).",
        )
    fx_rate = resolve_fx_rate(db, body.event_date, client_value=body.fx_rate)
    net = _compute_net(body)

    before = audit_snapshot(d, _TRACKED_FIELDS)
    d.financial_institution_id = fi.id
    d.asset_id = asset.id if asset else None
    d.type = body.type
    d.event_date = body.event_date
    d.gross_amount = body.gross_amount
    d.tax = body.tax
    d.net_amount = net
    d.currency = currency
    d.fx_rate = fx_rate
    d.notes = body.notes
    d.external_id = body.external_id
    d.external_source = body.external_source
    d.updated_at = datetime.now(timezone.utc)
    d.updated_by = current_user.user_id
    db.flush()
    after = audit_snapshot(d, _TRACKED_FIELDS)
    _audit(db, current_user, "distribution.updated", d, diff=audit_diff(before, after))

    return DistributionOut.from_orm(
        d,
        fi_name=fi.short_name,
        asset_name=asset.name if asset else None,
        asset_ticker=asset.ticker if asset else None,
    )


@router.put("/{did}/deactivate", response_model=DistributionOut)
def deactivate_distribution(
    did: str,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    d = _get_or_404(db, did)
    _check_workspace_access(d, current_user)
    d.is_active = False
    d.updated_at = datetime.now(timezone.utc)
    d.updated_by = current_user.user_id
    db.flush()
    _audit(db, current_user, "distribution.deactivated", d)

    fi = db.get(FinancialInstitution, d.financial_institution_id)
    asset = db.get(Asset, d.asset_id) if d.asset_id else None
    return DistributionOut.from_orm(
        d,
        fi_name=fi.short_name if fi else d.financial_institution_id,
        asset_name=asset.name if asset else None,
        asset_ticker=asset.ticker if asset else None,
    )
