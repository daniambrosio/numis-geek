import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from numis_geek.api.deps import get_current_user, get_db
from numis_geek.models.account import Currency
from numis_geek.models.asset import Asset, AssetClass
from numis_geek.models.external import ExternalSource
from numis_geek.models.lancamento import LANCAMENTO_TYPE_LABELS, Lancamento, LancamentoType
from numis_geek.models.user import User, UserRole
from numis_geek.models.workspace import Workspace
from numis_geek.services.audit import AuditService
from numis_geek.services.auth import UserContext

router = APIRouter(prefix="/lancamentos", tags=["lancamentos"])


# ── Type-driven validation tables ────────────────────────────────────────────

# Asset classes that are NOT cotado (no qty/unit_price; just a monetary value).
NON_COTADO_CLASSES = {
    AssetClass.FIXED_INCOME,
    AssetClass.FGTS,
    AssetClass.PRIVATE_PENSION,
    AssetClass.CASH,
}

# Types that follow "qty + unit_price" math (cotado) OR may use gross_amount-only
# (non-cotado relaxation). RESGATE_TOTAL behaves identically to VENDA.
COTADO_OR_VALUE_TYPES = {
    LancamentoType.COMPRA,
    LancamentoType.VENDA,
    LancamentoType.SUBSCRICAO,
    LancamentoType.RESGATE_TOTAL,
}

# Types where quantity is allowed (and required for BONIFICACAO).
QUANTITY_ALLOWED = COTADO_OR_VALUE_TYPES | {LancamentoType.BONIFICACAO}

# unit_price allowed (BONIFICACAO forbids it; income types forbid it).
UNIT_PRICE_ALLOWED = COTADO_OR_VALUE_TYPES
UNIT_PRICE_FORBIDDEN = {LancamentoType.BONIFICACAO}

# gross_amount required (must be > 0 and provided) for income types.
INCOME_TYPES = {
    LancamentoType.DIVIDENDO,
    LancamentoType.JUROS,
    LancamentoType.JCP,
    LancamentoType.COME_COTAS,
}
GROSS_REQUIRED = INCOME_TYPES  # COME_COTAS uses gross/tax, no qty
GROSS_POSITIVE_TYPES = {LancamentoType.DIVIDENDO, LancamentoType.JUROS, LancamentoType.JCP, LancamentoType.COME_COTAS}

# tax required only for COME_COTAS.
TAX_REQUIRED = {LancamentoType.COME_COTAS}
# fee/tax forbidden for BONIFICACAO (free shares — no cash, no tax).
FEE_TAX_FORBIDDEN = {LancamentoType.BONIFICACAO}


# ── Schemas ──────────────────────────────────────────────────────────────────

class LancamentoRequest(BaseModel):
    asset_id: str
    type: LancamentoType
    event_date: date
    settlement_date: date | None = None
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    gross_amount: Decimal | None = None
    fee: Decimal | None = None
    tax: Decimal | None = None
    net_amount: Decimal | None = None
    currency: Currency | None = None
    fx_rate: Decimal | None = None
    notes: str | None = None
    external_id: str | None = Field(default=None, max_length=255)
    external_source: ExternalSource | None = None
    nota_negociacao_number: str | None = Field(default=None, max_length=50)
    workspace_id: str | None = None  # only honored when caller is sysadmin

    @model_validator(mode="after")
    def _validate(self) -> "LancamentoRequest":
        t = self.type

        if self.event_date > date.today():
            raise ValueError("event_date cannot be in the future.")

        # Quantity rules
        # BONIFICACAO requires quantity (free shares: count is the whole story).
        if t == LancamentoType.BONIFICACAO:
            if self.quantity is None or self.quantity <= 0:
                raise ValueError(f"quantity is required and must be > 0 for type {t.value}.")
        elif t in COTADO_OR_VALUE_TYPES:
            # COMPRA/VENDA/SUBSCRICAO/RESGATE_TOTAL: must have either
            # (quantity AND unit_price) OR gross_amount. We can't see the
            # asset_class here, so just enforce "at least one route to a
            # gross". Value-positivity is checked at route level after asset
            # resolution.
            has_qty_price = self.quantity is not None and self.unit_price is not None
            has_gross = self.gross_amount is not None
            if not has_qty_price and not has_gross:
                raise ValueError(
                    f"type {t.value} requires either (quantity AND unit_price) "
                    f"or gross_amount."
                )
            if self.quantity is not None and self.quantity <= 0:
                raise ValueError(f"quantity must be > 0 for type {t.value}.")
            if self.unit_price is not None and self.unit_price <= 0:
                raise ValueError(f"unit_price must be > 0 for type {t.value}.")
        else:
            # COME_COTAS / income types — quantity must be null per spec.
            if self.quantity is not None:
                raise ValueError(f"quantity must be omitted for type {t.value}.")

        # Unit price rules
        if t in UNIT_PRICE_FORBIDDEN and self.unit_price is not None:
            raise ValueError(f"unit_price must be omitted for type {t.value}.")
        if t not in UNIT_PRICE_ALLOWED and t not in UNIT_PRICE_FORBIDDEN and self.unit_price is not None:
            # income/come-cotas: unit_price not used
            raise ValueError(f"unit_price must be omitted for type {t.value}.")

        # Gross rules
        if t in GROSS_REQUIRED:
            if self.gross_amount is None:
                raise ValueError(f"gross_amount is required for type {t.value}.")
        if t in GROSS_POSITIVE_TYPES and self.gross_amount is not None and self.gross_amount <= 0:
            raise ValueError(f"gross_amount must be > 0 for type {t.value} (use VENDA for negative cash).")

        # Tax rules
        if t in TAX_REQUIRED and (self.tax is None or self.tax <= 0):
            raise ValueError(f"tax is required and must be > 0 for type {t.value}.")
        if t in FEE_TAX_FORBIDDEN:
            if self.fee is not None:
                raise ValueError(f"fee must be omitted for type {t.value}.")
            if self.tax is not None:
                raise ValueError(f"tax must be omitted for type {t.value}.")

        # fx_rate basic sanity
        if self.fx_rate is not None and self.fx_rate <= 0:
            raise ValueError("fx_rate must be > 0.")

        return self


class LancamentoOut(BaseModel):
    id: str
    workspace_id: str
    asset_id: str
    asset_name: str
    asset_ticker: str | None
    type: str
    type_label: str
    event_date: str
    settlement_date: str | None
    quantity: float | None
    unit_price: float | None
    gross_amount: float | None
    fee: float | None
    tax: float | None
    net_amount: float
    currency: str
    fx_rate: float
    notes: str | None
    external_id: str | None = None
    external_source: str | None = None
    nota_negociacao_number: str | None = None
    is_active: bool
    created_at: str
    updated_at: str

    @classmethod
    def from_orm(cls, l: Lancamento, asset_name: str, asset_ticker: str | None) -> "LancamentoOut":
        return cls(
            id=l.id,
            workspace_id=l.workspace_id,
            asset_id=l.asset_id,
            asset_name=asset_name,
            asset_ticker=asset_ticker,
            type=l.type.value,
            type_label=LANCAMENTO_TYPE_LABELS[l.type],
            event_date=l.event_date.isoformat(),
            settlement_date=l.settlement_date.isoformat() if l.settlement_date else None,
            quantity=float(l.quantity) if l.quantity is not None else None,
            unit_price=float(l.unit_price) if l.unit_price is not None else None,
            gross_amount=float(l.gross_amount) if l.gross_amount is not None else None,
            fee=float(l.fee) if l.fee is not None else None,
            tax=float(l.tax) if l.tax is not None else None,
            net_amount=float(l.net_amount),
            currency=l.currency.value,
            fx_rate=float(l.fx_rate),
            notes=l.notes,
            external_id=l.external_id,
            external_source=l.external_source.value if l.external_source else None,
            nota_negociacao_number=l.nota_negociacao_number,
            is_active=l.is_active,
            created_at=l.created_at.isoformat(),
            updated_at=l.updated_at.isoformat(),
        )


class LancamentoListPage(BaseModel):
    items: list[LancamentoOut]
    total: int
    page: int
    page_size: int


# ── Helpers ──────────────────────────────────────────────────────────────────

def _get_or_404(db: Session, lan_id: str) -> Lancamento:
    l = db.get(Lancamento, lan_id)
    if not l:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lançamento not found.")
    return l


def _check_workspace_access(l: Lancamento, current_user: UserContext) -> None:
    if current_user.role == UserRole.sysadmin:
        return
    if l.workspace_id != current_user.workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lançamento not found.")


def _resolve_workspace_id(body: LancamentoRequest, current_user: UserContext, db: Session) -> str:
    if current_user.role == UserRole.sysadmin:
        if not body.workspace_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="workspace_id is required when creating lançamentos as sysadmin.",
            )
        if not db.get(Workspace, body.workspace_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.")
        return body.workspace_id
    if not current_user.workspace_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No workspace bound to user.")
    return current_user.workspace_id


def _resolve_asset(db: Session, asset_id: str, workspace_id: str, current_user: UserContext) -> Asset:
    # Inactive assets are intentionally allowed: importers backfill historical entries
    # against deactivated assets, and the UI surfaces an explicit confirmation step.
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


def _compute_net_amount(body: LancamentoRequest, gross: Decimal) -> Decimal:
    """Server-computed net per type (per spec)."""
    fee = body.fee or Decimal("0")
    tax = body.tax or Decimal("0")
    t = body.type
    if t == LancamentoType.COMPRA:
        return gross + fee + tax  # cost basis
    if t in (LancamentoType.VENDA, LancamentoType.RESGATE_TOTAL):
        return gross - fee - tax  # proceeds
    if t in INCOME_TYPES and t != LancamentoType.COME_COTAS:
        return gross - fee - tax
    if t == LancamentoType.COME_COTAS:
        return -tax
    if t == LancamentoType.BONIFICACAO:
        return Decimal("0")
    if t == LancamentoType.SUBSCRICAO:
        return gross + fee + tax  # acts as a small COMPRA
    return gross


def _resolve_gross(body: LancamentoRequest) -> Decimal:
    """Compute or accept the gross_amount per type."""
    if body.gross_amount is not None:
        return body.gross_amount
    t = body.type
    if t in COTADO_OR_VALUE_TYPES:
        # qty * unit_price (when both present); else 0 (caller validated already).
        if body.quantity is not None and body.unit_price is not None:
            return body.quantity * body.unit_price
        return Decimal("0")
    if t == LancamentoType.BONIFICACAO:
        return Decimal("0")
    # Income types fall through but the validator already requires gross_amount.
    raise HTTPException(status_code=400, detail=f"Cannot compute gross_amount for type {t.value}.")


def _audit(db: Session, current_user: UserContext, action: str, l: Lancamento) -> None:
    actor = db.get(User, current_user.user_id)
    AuditService(db).log(
        user_email=actor.email if actor else current_user.user_id,
        action=action,
        workspace_id=l.workspace_id,
        user_id=current_user.user_id,
        resource_type="lancamento",
        resource_id=l.id,
        details={
            "asset_id": l.asset_id,
            "type": l.type.value,
            "event_date": l.event_date.isoformat(),
        },
    )


def _hydrate_assets(db: Session, lans: list[Lancamento]) -> dict[str, Asset]:
    asset_ids = {l.asset_id for l in lans}
    if not asset_ids:
        return {}
    rows = db.query(Asset).filter(Asset.id.in_(asset_ids)).all()
    return {a.id: a for a in rows}


# ── Routes ───────────────────────────────────────────────────────────────────

@router.get("", response_model=LancamentoListPage)
def list_lancamentos(
    asset_id: str | None = Query(default=None),
    type: LancamentoType | None = Query(default=None),
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = Query(default=None),
    include_inactive: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    workspace_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    q = db.query(Lancamento)
    if not include_inactive:
        q = q.filter(Lancamento.is_active == True)  # noqa: E712

    if current_user.role == UserRole.sysadmin:
        if workspace_id:
            q = q.filter(Lancamento.workspace_id == workspace_id)
    else:
        q = q.filter(Lancamento.workspace_id == current_user.workspace_id)

    if asset_id:
        q = q.filter(Lancamento.asset_id == asset_id)
    if type:
        q = q.filter(Lancamento.type == type)
    if from_:
        q = q.filter(Lancamento.event_date >= from_)
    if to:
        q = q.filter(Lancamento.event_date <= to)

    total = q.count()
    rows = (
        q.order_by(Lancamento.event_date.desc(), Lancamento.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    assets = _hydrate_assets(db, rows)
    items = [
        LancamentoOut.from_orm(
            l,
            asset_name=assets[l.asset_id].name if l.asset_id in assets else l.asset_id,
            asset_ticker=assets[l.asset_id].ticker if l.asset_id in assets else None,
        )
        for l in rows
    ]
    return LancamentoListPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/{lan_id}", response_model=LancamentoOut)
def get_lancamento(
    lan_id: str,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    l = _get_or_404(db, lan_id)
    _check_workspace_access(l, current_user)
    asset = db.get(Asset, l.asset_id)
    return LancamentoOut.from_orm(
        l,
        asset_name=asset.name if asset else l.asset_id,
        asset_ticker=asset.ticker if asset else None,
    )


def _validate_against_asset_class(body: LancamentoRequest, asset: Asset) -> None:
    """Asset-class-aware validation that the Pydantic validator can't do.

    Specifically: cotado assets (stocks/FIIs/ETFs/etc) must have
    `(quantity AND unit_price)` for COMPRA/VENDA/SUBSCRICAO/RESGATE_TOTAL —
    gross_amount-only is reserved for non-cotado classes (FIXED_INCOME / FGTS /
    PRIVATE_PENSION / CASH).
    """
    t = body.type
    if t not in COTADO_OR_VALUE_TYPES:
        return
    has_qty_price = body.quantity is not None and body.unit_price is not None
    has_gross = body.gross_amount is not None
    is_non_cotado = asset.asset_class in NON_COTADO_CLASSES
    if not is_non_cotado and not has_qty_price:
        # Cotado assets must have qty AND unit_price; gross_amount alone is
        # not enough. (gross can override the math, but it's not a substitute
        # for missing qty/price.)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"type {t.value} on a cotado asset ({asset.asset_class.value}) "
                f"requires both quantity and unit_price."
            ),
        )
    if is_non_cotado and not has_qty_price and not has_gross:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"type {t.value} on a non-cotado asset requires gross_amount "
                f"(or quantity + unit_price)."
            ),
        )


@router.post("", response_model=LancamentoOut, status_code=status.HTTP_201_CREATED)
def create_lancamento(
    body: LancamentoRequest,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    workspace_id = _resolve_workspace_id(body, current_user, db)
    asset = _resolve_asset(db, body.asset_id, workspace_id, current_user)
    _validate_against_asset_class(body, asset)

    currency = body.currency or asset.currency
    if body.type in INCOME_TYPES and currency != asset.currency:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Income lançamentos must use the asset's currency ({asset.currency.value}).",
        )
    fx_rate = body.fx_rate if body.fx_rate is not None else Decimal("1.0")
    gross = _resolve_gross(body)

    # Persist computed gross_amount when not provided so the row is self-explanatory.
    persisted_gross: Decimal | None
    if body.gross_amount is not None:
        persisted_gross = body.gross_amount
    elif body.type in COTADO_OR_VALUE_TYPES:
        persisted_gross = gross
    elif body.type == LancamentoType.BONIFICACAO:
        persisted_gross = Decimal("0")
    else:
        persisted_gross = gross

    net = body.net_amount if body.net_amount is not None else _compute_net_amount(body, gross)

    now = datetime.now(timezone.utc)
    l = Lancamento(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        asset_id=asset.id,
        type=body.type,
        event_date=body.event_date,
        settlement_date=body.settlement_date,
        quantity=body.quantity,
        unit_price=body.unit_price,
        gross_amount=persisted_gross,
        fee=body.fee,
        tax=body.tax,
        net_amount=net,
        currency=currency,
        fx_rate=fx_rate,
        notes=body.notes,
        external_id=body.external_id,
        external_source=body.external_source,
        nota_negociacao_number=body.nota_negociacao_number,
        is_active=True,
        created_at=now,
        updated_at=now,
        created_by=current_user.user_id,
        updated_by=current_user.user_id,
    )
    db.add(l)
    db.flush()
    _audit(db, current_user, "lancamento.created", l)

    return LancamentoOut.from_orm(l, asset_name=asset.name, asset_ticker=asset.ticker)


@router.put("/{lan_id}", response_model=LancamentoOut)
def update_lancamento(
    lan_id: str,
    body: LancamentoRequest,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    l = _get_or_404(db, lan_id)
    _check_workspace_access(l, current_user)

    # workspace_id is immutable on update; honor sysadmin scope but don't move the row.
    workspace_id = l.workspace_id
    asset = _resolve_asset(db, body.asset_id, workspace_id, current_user)
    _validate_against_asset_class(body, asset)

    currency = body.currency or asset.currency
    if body.type in INCOME_TYPES and currency != asset.currency:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Income lançamentos must use the asset's currency ({asset.currency.value}).",
        )
    fx_rate = body.fx_rate if body.fx_rate is not None else Decimal("1.0")
    gross = _resolve_gross(body)

    persisted_gross: Decimal | None
    if body.gross_amount is not None:
        persisted_gross = body.gross_amount
    elif body.type in COTADO_OR_VALUE_TYPES:
        persisted_gross = gross
    elif body.type == LancamentoType.BONIFICACAO:
        persisted_gross = Decimal("0")
    else:
        persisted_gross = gross

    net = body.net_amount if body.net_amount is not None else _compute_net_amount(body, gross)

    l.asset_id = asset.id
    l.type = body.type
    l.event_date = body.event_date
    l.settlement_date = body.settlement_date
    l.quantity = body.quantity
    l.unit_price = body.unit_price
    l.gross_amount = persisted_gross
    l.fee = body.fee
    l.tax = body.tax
    l.net_amount = net
    l.currency = currency
    l.fx_rate = fx_rate
    l.notes = body.notes
    l.external_id = body.external_id
    l.external_source = body.external_source
    l.nota_negociacao_number = body.nota_negociacao_number
    l.updated_at = datetime.now(timezone.utc)
    l.updated_by = current_user.user_id
    db.flush()
    _audit(db, current_user, "lancamento.updated", l)

    return LancamentoOut.from_orm(l, asset_name=asset.name, asset_ticker=asset.ticker)


@router.put("/{lan_id}/deactivate", response_model=LancamentoOut)
def deactivate_lancamento(
    lan_id: str,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    l = _get_or_404(db, lan_id)
    _check_workspace_access(l, current_user)
    l.is_active = False
    l.updated_at = datetime.now(timezone.utc)
    l.updated_by = current_user.user_id
    db.flush()
    _audit(db, current_user, "lancamento.deactivated", l)

    asset = db.get(Asset, l.asset_id)
    return LancamentoOut.from_orm(
        l,
        asset_name=asset.name if asset else l.asset_id,
        asset_ticker=asset.ticker if asset else None,
    )
