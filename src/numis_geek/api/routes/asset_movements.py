import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from numis_geek.api.deps import get_current_user, get_db
from numis_geek.models.account import Currency
from numis_geek.models.asset import Asset
from numis_geek.models.asset_movement import (
    ASSET_MOVEMENT_TYPE_LABELS,
    AssetMovement,
    AssetMovementType,
)
from numis_geek.models.external import ExternalSource
from numis_geek.models.user import User, UserRole
from numis_geek.models.workspace import Workspace
from numis_geek.services.audit import AuditService
from numis_geek.services.auth import UserContext
from numis_geek.services.fx import resolve_fx_rate

router = APIRouter(prefix="/asset-movements", tags=["asset-movements"])


# ── Type-driven validation tables ────────────────────────────────────────────

# Types that follow "qty + unit_price" math (cotado) OR may use gross_amount-only.
COTADO_OR_VALUE_TYPES = {
    AssetMovementType.BUY,
    AssetMovementType.SELL,
    AssetMovementType.SUBSCRIPTION,
    AssetMovementType.FULL_REDEMPTION,
}

UNIT_PRICE_ALLOWED = COTADO_OR_VALUE_TYPES
UNIT_PRICE_FORBIDDEN = {AssetMovementType.BONUS}

GROSS_REQUIRED = {AssetMovementType.COME_COTAS}
GROSS_POSITIVE_TYPES = {AssetMovementType.COME_COTAS}

TAX_REQUIRED = {AssetMovementType.COME_COTAS}
FEE_TAX_FORBIDDEN = {AssetMovementType.BONUS}


# ── Schemas ──────────────────────────────────────────────────────────────────

class AssetMovementRequest(BaseModel):
    asset_id: str
    type: AssetMovementType
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
    def _validate(self) -> "AssetMovementRequest":
        t = self.type

        if self.event_date > date.today():
            raise ValueError("event_date cannot be in the future.")

        # Quantity rules
        if t == AssetMovementType.BONUS:
            if self.quantity is None or self.quantity <= 0:
                raise ValueError(f"quantity is required and must be > 0 for type {t.value}.")
        elif t in COTADO_OR_VALUE_TYPES:
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
            # COME_COTAS — quantity must be null
            if self.quantity is not None:
                raise ValueError(f"quantity must be omitted for type {t.value}.")

        # Unit price rules
        if t in UNIT_PRICE_FORBIDDEN and self.unit_price is not None:
            raise ValueError(f"unit_price must be omitted for type {t.value}.")
        if t not in UNIT_PRICE_ALLOWED and t not in UNIT_PRICE_FORBIDDEN and self.unit_price is not None:
            raise ValueError(f"unit_price must be omitted for type {t.value}.")

        # Gross rules
        if t in GROSS_REQUIRED and self.gross_amount is None:
            raise ValueError(f"gross_amount is required for type {t.value}.")
        if t in GROSS_POSITIVE_TYPES and self.gross_amount is not None and self.gross_amount <= 0:
            raise ValueError(f"gross_amount must be > 0 for type {t.value} (use SELL for negative cash).")

        # Tax rules
        if t in TAX_REQUIRED and (self.tax is None or self.tax <= 0):
            raise ValueError(f"tax is required and must be > 0 for type {t.value}.")
        if t in FEE_TAX_FORBIDDEN:
            if self.fee is not None:
                raise ValueError(f"fee must be omitted for type {t.value}.")
            if self.tax is not None:
                raise ValueError(f"tax must be omitted for type {t.value}.")

        if self.fx_rate is not None and self.fx_rate <= 0:
            raise ValueError("fx_rate must be > 0.")

        return self


class AssetMovementOut(BaseModel):
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
    notion_sync_status: str
    notion_sync_error: str | None = None
    notion_last_synced_at: str | None = None
    is_active: bool
    created_at: str
    updated_at: str

    @classmethod
    def from_orm(cls, m: AssetMovement, asset_name: str, asset_ticker: str | None) -> "AssetMovementOut":
        return cls(
            id=m.id,
            workspace_id=m.workspace_id,
            asset_id=m.asset_id,
            asset_name=asset_name,
            asset_ticker=asset_ticker,
            type=m.type.value,
            type_label=ASSET_MOVEMENT_TYPE_LABELS[m.type],
            event_date=m.event_date.isoformat(),
            settlement_date=m.settlement_date.isoformat() if m.settlement_date else None,
            quantity=float(m.quantity) if m.quantity is not None else None,
            unit_price=float(m.unit_price) if m.unit_price is not None else None,
            gross_amount=float(m.gross_amount) if m.gross_amount is not None else None,
            fee=float(m.fee) if m.fee is not None else None,
            tax=float(m.tax) if m.tax is not None else None,
            net_amount=float(m.net_amount),
            currency=m.currency.value,
            fx_rate=float(m.fx_rate),
            notes=m.notes,
            external_id=m.external_id,
            external_source=m.external_source.value if m.external_source else None,
            nota_negociacao_number=m.nota_negociacao_number,
            notion_sync_status=m.notion_sync_status.value,
            notion_sync_error=m.notion_sync_error,
            notion_last_synced_at=m.notion_last_synced_at.isoformat() if m.notion_last_synced_at else None,
            is_active=m.is_active,
            created_at=m.created_at.isoformat(),
            updated_at=m.updated_at.isoformat(),
        )


class AssetMovementListPage(BaseModel):
    items: list[AssetMovementOut]
    total: int
    page: int
    page_size: int


# ── Helpers ──────────────────────────────────────────────────────────────────

def _get_or_404(db: Session, mid: str) -> AssetMovement:
    m = db.get(AssetMovement, mid)
    if not m:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset movement not found.")
    return m


def _check_workspace_access(m: AssetMovement, current_user: UserContext) -> None:
    if current_user.role == UserRole.sysadmin:
        return
    if m.workspace_id != current_user.workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset movement not found.")


def _resolve_workspace_id(body: AssetMovementRequest, current_user: UserContext, db: Session) -> str:
    if current_user.role == UserRole.sysadmin:
        if not body.workspace_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="workspace_id is required when creating asset movements as sysadmin.",
            )
        if not db.get(Workspace, body.workspace_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.")
        return body.workspace_id
    if not current_user.workspace_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No workspace bound to user.")
    return current_user.workspace_id


def _resolve_asset(db: Session, asset_id: str, workspace_id: str, current_user: UserContext) -> Asset:
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


def _compute_net_amount(body: AssetMovementRequest, gross: Decimal) -> Decimal:
    """Server-computed net per type."""
    fee = body.fee or Decimal("0")
    tax = body.tax or Decimal("0")
    t = body.type
    if t == AssetMovementType.BUY:
        return gross + fee + tax
    if t in (AssetMovementType.SELL, AssetMovementType.FULL_REDEMPTION):
        return gross - fee - tax
    if t == AssetMovementType.COME_COTAS:
        return -tax
    if t == AssetMovementType.BONUS:
        return Decimal("0")
    if t == AssetMovementType.SUBSCRIPTION:
        return gross + fee + tax
    return gross


def _resolve_gross(body: AssetMovementRequest) -> Decimal:
    if body.gross_amount is not None:
        return body.gross_amount
    t = body.type
    if t in COTADO_OR_VALUE_TYPES:
        if body.quantity is not None and body.unit_price is not None:
            return body.quantity * body.unit_price
        return Decimal("0")
    if t == AssetMovementType.BONUS:
        return Decimal("0")
    raise HTTPException(status_code=400, detail=f"Cannot compute gross_amount for type {t.value}.")


def _audit(db: Session, current_user: UserContext, action: str, m: AssetMovement) -> None:
    actor = db.get(User, current_user.user_id)
    AuditService(db).log(
        user_email=actor.email if actor else current_user.user_id,
        action=action,
        workspace_id=m.workspace_id,
        user_id=current_user.user_id,
        resource_type="asset_movement",
        resource_id=m.id,
        details={
            "asset_id": m.asset_id,
            "type": m.type.value,
            "event_date": m.event_date.isoformat(),
        },
    )


def _hydrate_assets(db: Session, ms: list[AssetMovement]) -> dict[str, Asset]:
    asset_ids = {m.asset_id for m in ms}
    if not asset_ids:
        return {}
    rows = db.query(Asset).filter(Asset.id.in_(asset_ids)).all()
    return {a.id: a for a in rows}


# ── Routes ───────────────────────────────────────────────────────────────────

@router.get("", response_model=AssetMovementListPage)
def list_asset_movements(
    asset_id: str | None = Query(default=None),
    type: AssetMovementType | None = Query(default=None),
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = Query(default=None),
    include_inactive: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    workspace_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    q = db.query(AssetMovement)
    if not include_inactive:
        q = q.filter(AssetMovement.is_active == True)  # noqa: E712

    if current_user.role == UserRole.sysadmin:
        if workspace_id:
            q = q.filter(AssetMovement.workspace_id == workspace_id)
    else:
        q = q.filter(AssetMovement.workspace_id == current_user.workspace_id)

    if asset_id:
        q = q.filter(AssetMovement.asset_id == asset_id)
    if type:
        q = q.filter(AssetMovement.type == type)
    if from_:
        q = q.filter(AssetMovement.event_date >= from_)
    if to:
        q = q.filter(AssetMovement.event_date <= to)

    total = q.count()
    rows = (
        q.order_by(AssetMovement.event_date.desc(), AssetMovement.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    assets = _hydrate_assets(db, rows)
    items = [
        AssetMovementOut.from_orm(
            m,
            asset_name=assets[m.asset_id].name if m.asset_id in assets else m.asset_id,
            asset_ticker=assets[m.asset_id].ticker if m.asset_id in assets else None,
        )
        for m in rows
    ]
    return AssetMovementListPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/{mid}", response_model=AssetMovementOut)
def get_asset_movement(
    mid: str,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    m = _get_or_404(db, mid)
    _check_workspace_access(m, current_user)
    asset = db.get(Asset, m.asset_id)
    return AssetMovementOut.from_orm(
        m,
        asset_name=asset.name if asset else m.asset_id,
        asset_ticker=asset.ticker if asset else None,
    )


@router.post("", response_model=AssetMovementOut, status_code=status.HTTP_201_CREATED)
def create_asset_movement(
    body: AssetMovementRequest,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    workspace_id = _resolve_workspace_id(body, current_user, db)
    asset = _resolve_asset(db, body.asset_id, workspace_id, current_user)

    currency = body.currency or asset.currency
    fx_rate = resolve_fx_rate(db, body.event_date, client_value=body.fx_rate)
    gross = _resolve_gross(body)

    persisted_gross: Decimal | None
    if body.gross_amount is not None:
        persisted_gross = body.gross_amount
    elif body.type in COTADO_OR_VALUE_TYPES:
        persisted_gross = gross
    elif body.type == AssetMovementType.BONUS:
        persisted_gross = Decimal("0")
    else:
        persisted_gross = gross

    net = body.net_amount if body.net_amount is not None else _compute_net_amount(body, gross)

    now = datetime.now(timezone.utc)
    m = AssetMovement(
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
    db.add(m)
    db.flush()
    _audit(db, current_user, "asset_movement.created", m)

    return AssetMovementOut.from_orm(m, asset_name=asset.name, asset_ticker=asset.ticker)


@router.put("/{mid}", response_model=AssetMovementOut)
def update_asset_movement(
    mid: str,
    body: AssetMovementRequest,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    m = _get_or_404(db, mid)
    _check_workspace_access(m, current_user)

    workspace_id = m.workspace_id
    asset = _resolve_asset(db, body.asset_id, workspace_id, current_user)

    currency = body.currency or asset.currency
    fx_rate = resolve_fx_rate(db, body.event_date, client_value=body.fx_rate)
    gross = _resolve_gross(body)

    persisted_gross: Decimal | None
    if body.gross_amount is not None:
        persisted_gross = body.gross_amount
    elif body.type in COTADO_OR_VALUE_TYPES:
        persisted_gross = gross
    elif body.type == AssetMovementType.BONUS:
        persisted_gross = Decimal("0")
    else:
        persisted_gross = gross

    net = body.net_amount if body.net_amount is not None else _compute_net_amount(body, gross)

    m.asset_id = asset.id
    m.type = body.type
    m.event_date = body.event_date
    m.settlement_date = body.settlement_date
    m.quantity = body.quantity
    m.unit_price = body.unit_price
    m.gross_amount = persisted_gross
    m.fee = body.fee
    m.tax = body.tax
    m.net_amount = net
    m.currency = currency
    m.fx_rate = fx_rate
    m.notes = body.notes
    m.external_id = body.external_id
    m.external_source = body.external_source
    m.nota_negociacao_number = body.nota_negociacao_number
    m.updated_at = datetime.now(timezone.utc)
    m.updated_by = current_user.user_id
    db.flush()
    _audit(db, current_user, "asset_movement.updated", m)

    return AssetMovementOut.from_orm(m, asset_name=asset.name, asset_ticker=asset.ticker)


@router.put("/{mid}/deactivate", response_model=AssetMovementOut)
def deactivate_asset_movement(
    mid: str,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    m = _get_or_404(db, mid)
    _check_workspace_access(m, current_user)
    m.is_active = False
    m.updated_at = datetime.now(timezone.utc)
    m.updated_by = current_user.user_id
    db.flush()
    _audit(db, current_user, "asset_movement.deactivated", m)

    asset = db.get(Asset, m.asset_id)
    return AssetMovementOut.from_orm(
        m,
        asset_name=asset.name if asset else m.asset_id,
        asset_ticker=asset.ticker if asset else None,
    )
