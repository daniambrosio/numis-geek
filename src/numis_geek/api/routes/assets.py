import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from numis_geek.api.deps import get_current_user, get_db
from numis_geek.models.account import Account, AccountType, Currency
from numis_geek.models.asset import (
    Asset,
    AssetClass,
    FixedIncomeAsset,
    FixedIncomeIndexer,
    PhysicalAsset,
)
from numis_geek.models.external import ExternalSource
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.asset_movement import (
    ASSET_MOVEMENT_TYPE_LABELS,
    AssetMovement,
    AssetMovementType,
)
from numis_geek.models.portfolio_snapshot import (
    PortfolioSnapshot,
    PortfolioSnapshotItem,
    SnapshotStatus,
)
from numis_geek.models.user import User, UserRole
from numis_geek.models.workspace import Workspace
from numis_geek.services.audit import AuditService
from numis_geek.services.auth import UserContext
from numis_geek.services.positions import compute_position
from numis_geek.services.price_freshness import freshness_tier

router = APIRouter(prefix="/assets", tags=["assets"])


# ── Class groupings ──────────────────────────────────────────────────────────

TICKER_REQUIRED_CLASSES = {
    AssetClass.STOCK,
    AssetClass.ETF,
    AssetClass.REIT,
    AssetClass.CRYPTO,
}
TICKER_FORBIDDEN_CLASSES = {
    AssetClass.FIXED_INCOME,
    AssetClass.REAL_ESTATE,
    AssetClass.VEHICLE,
}
# FUND: ticker optional


# ── Schemas ──────────────────────────────────────────────────────────────────

class FixedIncomeDetails(BaseModel):
    issuer: str = Field(min_length=1, max_length=255)
    issue_date: date | None = None
    maturity_date: date
    indexer: FixedIncomeIndexer
    rate: Decimal
    face_value: Decimal | None = None


class PhysicalDetails(BaseModel):
    # real-estate fields
    address: str | None = Field(default=None, max_length=500)
    city: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=50)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    area_m2: Decimal | None = None
    registration_number: str | None = Field(default=None, max_length=100)
    # vehicle fields
    make: str | None = Field(default=None, max_length=100)
    model: str | None = Field(default=None, max_length=100)
    year: int | None = None
    license_plate: str | None = Field(default=None, max_length=20)
    chassis: str | None = Field(default=None, max_length=50)


class AssetRequest(BaseModel):
    asset_class: AssetClass
    account_id: str
    country: str = Field(min_length=2, max_length=2)
    name: str = Field(min_length=1, max_length=255)
    currency: Currency
    ticker: str | None = Field(default=None, max_length=20)
    cnpj: str | None = Field(default=None, max_length=18)
    current_price: Decimal | None = None
    notes: str | None = None
    external_id: str | None = Field(default=None, max_length=255)
    external_source: ExternalSource | None = None
    workspace_id: str | None = None  # only honored when caller is sysadmin
    details: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate(self) -> "AssetRequest":
        cls = self.asset_class

        # Ticker rules
        if cls in TICKER_REQUIRED_CLASSES and not (self.ticker and self.ticker.strip()):
            raise ValueError(f"ticker is required for asset_class {cls.value}")
        if cls in TICKER_FORBIDDEN_CLASSES and self.ticker:
            raise ValueError(f"ticker must be omitted for asset_class {cls.value}")

        # CNPJ only for FUND
        if self.cnpj and cls != AssetClass.FUND:
            raise ValueError("cnpj is allowed only for asset_class FUND")

        # Details presence vs class
        needs_details = cls in (AssetClass.FIXED_INCOME, AssetClass.REAL_ESTATE, AssetClass.VEHICLE)
        if needs_details and not self.details:
            raise ValueError(f"details is required for asset_class {cls.value}")
        if not needs_details and self.details:
            raise ValueError(f"details must be omitted for asset_class {cls.value}")

        # Validate the details payload itself
        if cls == AssetClass.FIXED_INCOME:
            FixedIncomeDetails(**self.details or {})
        elif cls in (AssetClass.REAL_ESTATE, AssetClass.VEHICLE):
            PhysicalDetails(**self.details or {})
            d = self.details or {}
            if cls == AssetClass.REAL_ESTATE:
                missing = [f for f in ("address", "city", "state", "country") if not d.get(f)]
                if missing:
                    raise ValueError(f"REAL_ESTATE requires fields: {', '.join(missing)}")
            else:  # VEHICLE
                missing = [f for f in ("make", "model", "year") if not d.get(f)]
                if missing:
                    raise ValueError(f"VEHICLE requires fields: {', '.join(missing)}")

        return self


class FixedIncomeOut(BaseModel):
    issuer: str
    issue_date: str | None
    maturity_date: str
    indexer: str
    rate: float
    face_value: float | None


class PhysicalOut(BaseModel):
    address: str | None
    city: str | None
    state: str | None
    country: str | None
    area_m2: float | None
    registration_number: str | None
    make: str | None
    model: str | None
    year: int | None
    license_plate: str | None
    chassis: str | None


class AssetOut(BaseModel):
    id: str
    workspace_id: str
    workspace_name: str | None = None
    account_id: str
    account_name: str
    financial_institution_id: str
    financial_institution_name: str
    asset_class: str
    country: str
    name: str
    ticker: str | None
    cnpj: str | None
    currency: str
    current_price: float | None = None
    price_updated_at: str | None = None
    price_source: str | None = None
    price_tier: str = "UNKNOWN"
    notes: str | None
    external_id: str | None = None
    external_source: str | None = None
    is_active: bool
    # Option-specific fields (None for non-OPTION assets). See Spec 17.
    underlying_id: str | None = None
    option_type: str | None = None
    strike_price: float | None = None
    expiration_date: str | None = None
    contract_size: int | None = None
    created_at: str
    updated_at: str
    details: dict[str, Any] | None = None

    @classmethod
    def from_orm(
        cls,
        asset: Asset,
        fi_name: str,
        account_name: str,
        fi_id: str,
        workspace_name: str | None = None,
    ) -> "AssetOut":
        details: dict[str, Any] | None = None
        if asset.asset_class == AssetClass.FIXED_INCOME and asset.fixed_income:
            fi_row = asset.fixed_income
            details = FixedIncomeOut(
                issuer=fi_row.issuer,
                issue_date=fi_row.issue_date.isoformat() if fi_row.issue_date else None,
                maturity_date=fi_row.maturity_date.isoformat(),
                indexer=fi_row.indexer.value,
                rate=float(fi_row.rate),
                face_value=float(fi_row.face_value) if fi_row.face_value is not None else None,
            ).model_dump()
        elif asset.asset_class in (AssetClass.REAL_ESTATE, AssetClass.VEHICLE) and asset.physical:
            p = asset.physical
            details = PhysicalOut(
                address=p.address,
                city=p.city,
                state=p.state,
                country=p.country,
                area_m2=float(p.area_m2) if p.area_m2 is not None else None,
                registration_number=p.registration_number,
                make=p.make,
                model=p.model,
                year=p.year,
                license_plate=p.license_plate,
                chassis=p.chassis,
            ).model_dump()
        return cls(
            id=asset.id,
            workspace_id=asset.workspace_id,
            workspace_name=workspace_name,
            account_id=asset.account_id,
            account_name=account_name,
            financial_institution_id=fi_id,
            financial_institution_name=fi_name,
            asset_class=asset.asset_class.value,
            country=asset.country,
            name=asset.name,
            ticker=asset.ticker,
            cnpj=asset.cnpj,
            currency=asset.currency.value,
            current_price=float(asset.current_price) if asset.current_price is not None else None,
            price_updated_at=asset.price_updated_at.isoformat() if asset.price_updated_at else None,
            price_source=asset.price_source.value if asset.price_source else None,
            price_tier=freshness_tier(asset.price_updated_at, asset.price_source).value,
            notes=asset.notes,
            external_id=asset.external_id,
            external_source=asset.external_source.value if asset.external_source else None,
            is_active=asset.is_active,
            underlying_id=asset.underlying_id,
            option_type=asset.option_type.value if asset.option_type else None,
            strike_price=float(asset.strike_price) if asset.strike_price is not None else None,
            expiration_date=asset.expiration_date.isoformat() if asset.expiration_date else None,
            contract_size=asset.contract_size,
            created_at=asset.created_at.isoformat(),
            updated_at=asset.updated_at.isoformat(),
            details=details,
        )


# ── Helpers ──────────────────────────────────────────────────────────────────

def _get_or_404(db: Session, asset_id: str) -> Asset:
    asset = db.get(Asset, asset_id)
    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found.")
    return asset


def _check_workspace_access(asset: Asset, current_user: UserContext) -> None:
    if current_user.role == UserRole.sysadmin:
        return
    if asset.workspace_id != current_user.workspace_id:
        # Reveal nothing about cross-workspace assets — return 404 like accounts/users.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found.")


def _resolve_workspace_id(body: AssetRequest, current_user: UserContext, db: Session) -> str:
    if current_user.role == UserRole.sysadmin:
        if not body.workspace_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="workspace_id is required when creating assets as sysadmin.",
            )
        if not db.get(Workspace, body.workspace_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.")
        return body.workspace_id
    if not current_user.workspace_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No workspace bound to user.")
    return current_user.workspace_id


def _check_unique(
    db: Session,
    *,
    workspace_id: str,
    ticker: str | None,
    account_id: str,
    exclude_id: str | None = None,
) -> None:
    if not ticker:
        return
    q = db.query(Asset).filter(
        Asset.workspace_id == workspace_id,
        Asset.ticker == ticker,
        Asset.account_id == account_id,
    )
    if exclude_id:
        q = q.filter(Asset.id != exclude_id)
    if q.first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"An asset with ticker {ticker} already exists at this account.",
        )


def _apply_details(asset: Asset, body: AssetRequest, db: Session) -> None:
    """Create / update / clear the specialized row to match the asset class."""
    # Clear out any stale specialized rows for the (possibly) new class.
    if asset.fixed_income and body.asset_class != AssetClass.FIXED_INCOME:
        db.delete(asset.fixed_income)
        asset.fixed_income = None
    if asset.physical and body.asset_class not in (AssetClass.REAL_ESTATE, AssetClass.VEHICLE):
        db.delete(asset.physical)
        asset.physical = None

    if body.asset_class == AssetClass.FIXED_INCOME:
        details = FixedIncomeDetails(**(body.details or {}))
        if asset.fixed_income:
            row = asset.fixed_income
            row.issuer = details.issuer
            row.issue_date = details.issue_date
            row.maturity_date = details.maturity_date
            row.indexer = details.indexer
            row.rate = details.rate
            row.face_value = details.face_value
        else:
            asset.fixed_income = FixedIncomeAsset(
                issuer=details.issuer,
                issue_date=details.issue_date,
                maturity_date=details.maturity_date,
                indexer=details.indexer,
                rate=details.rate,
                face_value=details.face_value,
            )
    elif body.asset_class in (AssetClass.REAL_ESTATE, AssetClass.VEHICLE):
        details = PhysicalDetails(**(body.details or {}))
        if asset.physical:
            row = asset.physical
            row.address = details.address
            row.city = details.city
            row.state = details.state
            row.country = details.country
            row.area_m2 = details.area_m2
            row.registration_number = details.registration_number
            row.make = details.make
            row.model = details.model
            row.year = details.year
            row.license_plate = details.license_plate
            row.chassis = details.chassis
        else:
            asset.physical = PhysicalAsset(
                address=details.address,
                city=details.city,
                state=details.state,
                country=details.country,
                area_m2=details.area_m2,
                registration_number=details.registration_number,
                make=details.make,
                model=details.model,
                year=details.year,
                license_plate=details.license_plate,
                chassis=details.chassis,
            )


def _audit(
    db: Session,
    current_user: UserContext,
    action: str,
    asset: Asset,
) -> None:
    actor = db.get(User, current_user.user_id)
    AuditService(db).log(
        user_email=actor.email if actor else current_user.user_id,
        action=action,
        workspace_id=asset.workspace_id,
        user_id=current_user.user_id,
        resource_type="asset",
        resource_id=asset.id,
        details={"name": asset.name, "asset_class": asset.asset_class.value},
    )


# ── Routes ───────────────────────────────────────────────────────────────────

@router.get("", response_model=list[AssetOut])
def list_assets(
    workspace_id: str | None = Query(default=None),
    asset_class: AssetClass | None = Query(default=None),
    include_inactive: bool = Query(default=False),
    search: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    q = db.query(Asset)
    if not include_inactive:
        q = q.filter(Asset.is_active == True)  # noqa: E712

    if current_user.role == UserRole.sysadmin:
        if workspace_id:
            q = q.filter(Asset.workspace_id == workspace_id)
    else:
        q = q.filter(Asset.workspace_id == current_user.workspace_id)

    if asset_class:
        q = q.filter(Asset.asset_class == asset_class)

    if search:
        like = f"%{search}%"
        q = q.filter(
            or_(
                Asset.name.ilike(like),
                Asset.ticker.ilike(like),
                Asset.cnpj.ilike(like),
            )
        )

    assets = q.order_by(func.lower(Asset.name)).all()
    # Hydrate account → FI map for AssetOut
    account_ids = {a.account_id for a in assets}
    account_map = {
        ac.id: ac
        for ac in db.query(Account).filter(Account.id.in_(account_ids)).all()
    } if account_ids else {}
    fi_ids = {ac.financial_institution_id for ac in account_map.values()}
    fi_map = {
        fi.id: fi.short_name
        for fi in db.query(FinancialInstitution).filter(FinancialInstitution.id.in_(fi_ids)).all()
    } if fi_ids else {}

    ws_map: dict[str, str] = {}
    if current_user.role == UserRole.sysadmin:
        ws_ids = {a.workspace_id for a in assets}
        if ws_ids:
            ws_map = {
                w.id: w.name
                for w in db.query(Workspace).filter(Workspace.id.in_(ws_ids)).all()
            }

    out = []
    for a in assets:
        ac = account_map.get(a.account_id)
        fi_id = ac.financial_institution_id if ac else ""
        out.append(AssetOut.from_orm(
            a,
            fi_map.get(fi_id, fi_id),
            account_name=ac.name if ac else a.account_id,
            fi_id=fi_id,
            workspace_name=ws_map.get(a.workspace_id),
        ))
    return out


@router.get("/{asset_id}", response_model=AssetOut)
def get_asset(
    asset_id: str,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    asset = _get_or_404(db, asset_id)
    _check_workspace_access(asset, current_user)
    account = db.get(Account, asset.account_id)
    fi_id = account.financial_institution_id if account else ""
    fi = db.get(FinancialInstitution, fi_id) if fi_id else None
    fi_name = fi.short_name if fi else fi_id
    ws_name: str | None = None
    if current_user.role == UserRole.sysadmin:
        ws = db.get(Workspace, asset.workspace_id)
        ws_name = ws.name if ws else None
    return AssetOut.from_orm(
        asset, fi_name,
        account_name=account.name if account else asset.account_id,
        fi_id=fi_id,
        workspace_name=ws_name,
    )


def _resolve_account(db: Session, account_id: str, workspace_id: str) -> Account:
    account = db.get(Account, account_id)
    if not account or not account.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found.")
    if account.workspace_id != workspace_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Account belongs to a different workspace.",
        )
    if account.account_type != AccountType.investment:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Asset must be linked to an investment account.",
        )
    return account


@router.post("", response_model=AssetOut, status_code=status.HTTP_201_CREATED)
def create_asset(
    body: AssetRequest,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    workspace_id = _resolve_workspace_id(body, current_user, db)
    account = _resolve_account(db, body.account_id, workspace_id)
    fi = db.get(FinancialInstitution, account.financial_institution_id)
    if not fi or not fi.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Financial institution not found.")

    _check_unique(
        db,
        workspace_id=workspace_id,
        ticker=body.ticker,
        account_id=body.account_id,
    )

    now = datetime.now(timezone.utc)
    asset = Asset(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        account_id=account.id,
        asset_class=body.asset_class,
        country=body.country.upper(),
        name=body.name,
        ticker=body.ticker,
        cnpj=body.cnpj,
        currency=body.currency,
        current_price=body.current_price,
        price_updated_at=now if body.current_price is not None else None,
        notes=body.notes,
        external_id=body.external_id,
        external_source=body.external_source,
        is_active=True,
        created_at=now,
        updated_at=now,
        created_by=current_user.user_id,
        updated_by=current_user.user_id,
    )
    _apply_details(asset, body, db)
    db.add(asset)
    db.flush()
    _audit(db, current_user, "asset.created", asset)

    ws_name: str | None = None
    if current_user.role == UserRole.sysadmin:
        ws = db.get(Workspace, asset.workspace_id)
        ws_name = ws.name if ws else None
    return AssetOut.from_orm(
        asset, fi.short_name,
        account_name=account.name, fi_id=fi.id,
        workspace_name=ws_name,
    )


@router.put("/{asset_id}", response_model=AssetOut)
def update_asset(
    asset_id: str,
    body: AssetRequest,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    asset = _get_or_404(db, asset_id)
    _check_workspace_access(asset, current_user)

    account = _resolve_account(db, body.account_id, asset.workspace_id)
    fi = db.get(FinancialInstitution, account.financial_institution_id)
    if not fi or not fi.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Financial institution not found.")

    _check_unique(
        db,
        workspace_id=asset.workspace_id,
        ticker=body.ticker,
        account_id=body.account_id,
        exclude_id=asset.id,
    )

    asset.account_id = account.id
    asset.asset_class = body.asset_class
    asset.country = body.country.upper()
    asset.name = body.name
    asset.ticker = body.ticker
    asset.cnpj = body.cnpj
    asset.currency = body.currency
    if body.current_price is not None and asset.current_price != body.current_price:
        asset.current_price = body.current_price
        asset.price_updated_at = datetime.now(timezone.utc)
    elif body.current_price is None and asset.current_price is not None:
        asset.current_price = None
        asset.price_updated_at = None
    asset.notes = body.notes
    asset.external_id = body.external_id
    asset.external_source = body.external_source
    asset.updated_at = datetime.now(timezone.utc)
    asset.updated_by = current_user.user_id
    _apply_details(asset, body, db)
    db.flush()
    _audit(db, current_user, "asset.updated", asset)

    ws_name: str | None = None
    if current_user.role == UserRole.sysadmin:
        ws = db.get(Workspace, asset.workspace_id)
        ws_name = ws.name if ws else None
    return AssetOut.from_orm(
        asset, fi.short_name,
        account_name=account.name, fi_id=fi.id,
        workspace_name=ws_name,
    )


class PositionOut(BaseModel):
    asset_id: str
    quantity_held: float
    average_cost: float
    average_cost_brl: float
    total_invested_brl: float
    total_received_brl: float
    currency: str
    current_price: float | None = None
    current_value: float | None = None
    current_value_brl: float | None = None
    variation: float | None = None
    rentabilidade: float | None = None


class AssetMovementLite(BaseModel):
    id: str
    workspace_id: str
    asset_id: str
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


class AssetMovementsPage(BaseModel):
    items: list[AssetMovementLite]
    total: int
    page: int
    page_size: int


class PriceRefreshOut(BaseModel):
    asset_id: str
    ticker: str | None
    country: str | None
    status: str
    provider: str | None
    price_source: str | None
    old_price: float | None
    new_price: float | None
    error: str | None


@router.post("/{asset_id}/refresh-price", response_model=PriceRefreshOut)
def refresh_asset_price(
    asset_id: str,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    from numis_geek.models.asset import PriceSource
    from numis_geek.services.price_update import refresh_one
    asset = _get_or_404(db, asset_id)
    _check_workspace_access(asset, current_user)
    if asset.price_source == PriceSource.MANUAL or asset.price_source is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Asset has MANUAL price source. Use the manual edit endpoint.",
        )
    actor = db.get(User, current_user.user_id)
    email = actor.email if actor else current_user.user_id
    r = refresh_one(db, asset, user_email=email)
    return PriceRefreshOut(
        asset_id=r.asset_id,
        ticker=r.ticker,
        country=r.country,
        status=r.status,
        provider=r.provider,
        price_source=r.source,
        old_price=float(r.old_price) if r.old_price is not None else None,
        new_price=float(r.new_price) if r.new_price is not None else None,
        error=r.error,
    )


class ManualPriceRequest(BaseModel):
    price: Decimal = Field(..., ge=0)
    note: str | None = None


class ManualPriceOut(BaseModel):
    price: float
    price_updated_at: str
    price_source: str


@router.patch("/{asset_id}/price", response_model=ManualPriceOut)
def update_asset_price_manual(
    asset_id: str,
    body: ManualPriceRequest,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    """Spec 28 — manual price edit. Always allowed (Spec 49 follow-up):

    Previously rejected with 422 when asset.price_source was automated.
    That blocked legitimate manual overrides — e.g. user fixing a wrong
    LLM-imported value before refreshing. Now any asset accepts a manual
    PATCH; the next automated refresh (cron or button) overwrites it,
    same as before. Audit log captures the prior `price_source` so a
    reviewer can spot when manual overrides happened on automated assets.
    """
    asset = _get_or_404(db, asset_id)
    _check_workspace_access(asset, current_user)

    old_price = asset.current_price
    old_source = asset.price_source.value if asset.price_source else None
    asset.current_price = body.price
    asset.price_updated_at = datetime.now(timezone.utc)
    db.flush()

    actor = db.get(User, current_user.user_id)
    email = actor.email if actor else current_user.user_id
    details: dict[str, Any] = {
        "ticker": asset.ticker,
        "name": asset.name,
        "old_price": str(old_price) if old_price is not None else None,
        "new_price": str(body.price),
        "price_source": old_source,
    }
    if body.note:
        details["note"] = body.note
    AuditService(db).log(
        user_email=email,
        action="price.update.manual",
        workspace_id=asset.workspace_id,
        user_id=current_user.user_id,
        resource_type="asset",
        resource_id=asset.id,
        details=details,
    )

    return ManualPriceOut(
        price=float(body.price),
        price_updated_at=asset.price_updated_at.isoformat(),
        price_source="MANUAL",
    )


class BulkRefreshSummaryOut(BaseModel):
    total: int
    ok: int
    skipped: int
    failed: int
    results: list[PriceRefreshOut]


@router.post(
    "/refresh-prices/bulk",
    response_model=BulkRefreshSummaryOut,
    deprecated=True,
    summary="Deprecated — use POST /prices/refresh (Spec 23).",
)
def refresh_prices_bulk(
    response: Response,
    only_country: str | None = Query(None),
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    from numis_geek.services.price_update import refresh_bulk
    workspace_id = None if current_user.role == UserRole.sysadmin else current_user.workspace_id
    actor = db.get(User, current_user.user_id)
    email = actor.email if actor else current_user.user_id
    summary = refresh_bulk(
        db, workspace_id=workspace_id, only_country=only_country, user_email=email,
    )
    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = "2026-12-31"
    response.headers["Link"] = '</prices/refresh>; rel="successor-version"'
    return BulkRefreshSummaryOut(
        total=summary.total, ok=summary.ok, skipped=summary.skipped, failed=summary.failed,
        results=[
            PriceRefreshOut(
                asset_id=r.asset_id, ticker=r.ticker, country=r.country,
                status=r.status, provider=r.provider, price_source=r.source,
                old_price=float(r.old_price) if r.old_price is not None else None,
                new_price=float(r.new_price) if r.new_price is not None else None,
                error=r.error,
            )
            for r in summary.results
        ],
    )


@router.get("/{asset_id}/position", response_model=PositionOut)
def get_asset_position(
    asset_id: str,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    asset = _get_or_404(db, asset_id)
    _check_workspace_access(asset, current_user)
    pos = compute_position(db, asset_id)

    def _f(k: str) -> float | None:
        v = pos.get(k)
        return float(v) if v is not None else None

    return PositionOut(
        asset_id=asset_id,
        quantity_held=float(pos["quantity_held"]),
        average_cost=float(pos["average_cost"]),
        average_cost_brl=float(pos["average_cost_brl"]),
        total_invested_brl=float(pos["total_invested_brl"]),
        total_received_brl=float(pos["total_received_brl"]),
        currency=pos["currency"],
        current_price=_f("current_price"),
        current_value=_f("current_value"),
        current_value_brl=_f("current_value_brl"),
        variation=_f("variation"),
        rentabilidade=_f("rentabilidade"),
    )


# ── Spec 46 — Asset price history (derived from snapshots V1) ───────────────


class AssetPriceHistoryPoint(BaseModel):
    date: str            # YYYY-MM-DD
    unit_price: str      # Decimal as str (consistent with SnapshotItemOut)


class AssetPriceHistoryOut(BaseModel):
    asset_id: str
    currency: str        # 'BRL' | 'USD'
    period: str          # echo da query
    points: list[AssetPriceHistoryPoint]


_PERIOD_DAYS: dict[str, int | None] = {
    "6m":  180,
    "12m": 365,
    "24m": 730,
    "all": None,
}


@router.get("/{asset_id}/price-history", response_model=AssetPriceHistoryOut)
def asset_price_history(
    asset_id: str,
    period: Literal["6m", "12m", "24m", "all"] = "24m",
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    """Spec 46 V1 — historical unit prices derived from PortfolioSnapshotItem.

    Each `PortfolioSnapshotItem.unit_price` is a real fechamento price for
    a given `PortfolioSnapshot.period_end_date`. We join + filter +
    sort to assemble the series in native currency. Returns up to
    ~30 points (one per snapshot in window). When the asset has fewer
    than 2 points (newly bought, no snapshot yet), returns an empty
    `points` list and the frontend hides the chart.
    """
    asset = _get_or_404(db, asset_id)
    _check_workspace_access(asset, current_user)

    days = _PERIOD_DAYS[period]
    q = (
        db.query(PortfolioSnapshot.period_end_date, PortfolioSnapshotItem.unit_price)
        .join(
            PortfolioSnapshotItem,
            PortfolioSnapshotItem.snapshot_id == PortfolioSnapshot.id,
        )
        .filter(
            PortfolioSnapshot.workspace_id == asset.workspace_id,
            PortfolioSnapshotItem.asset_id == asset_id,
            PortfolioSnapshotItem.unit_price.isnot(None),
        )
    )
    if days is not None:
        cutoff = date.today() - timedelta(days=days)
        q = q.filter(PortfolioSnapshot.period_end_date >= cutoff)
    rows = q.order_by(PortfolioSnapshot.period_end_date.asc()).all()

    return AssetPriceHistoryOut(
        asset_id=asset_id,
        currency=asset.currency.value,
        period=period,
        points=[
            AssetPriceHistoryPoint(date=d.isoformat(), unit_price=str(p))
            for (d, p) in rows
        ],
    )


# ── Spec 50 — Asset snapshot history (closings table + chart) ──────────────


class AssetSnapshotHistoryItem(BaseModel):
    period_end_date: str          # YYYY-MM-DD
    quantity: str
    unit_price: str | None
    market_value_native: str | None
    market_value_brl: str | None
    market_value_usd: str | None
    total_invested_brl: str | None
    fx_rate_usd_brl: str | None   # PTAX cravado no snapshot


class AssetSnapshotHistoryOut(BaseModel):
    asset_id: str
    currency: str
    items: list[AssetSnapshotHistoryItem]   # cronológica desc


@router.get(
    "/{asset_id}/snapshot-history", response_model=AssetSnapshotHistoryOut,
)
def asset_snapshot_history(
    asset_id: str,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    """Spec 50 — historical closings for this asset.

    Returns a row per CLOSED snapshot in the workspace where this asset
    has an item. IN_REVIEW snapshots are excluded — they contain
    unvalidated data and shouldn't pollute the asset's history."""
    asset = _get_or_404(db, asset_id)
    _check_workspace_access(asset, current_user)

    rows = (
        db.query(
            PortfolioSnapshot.period_end_date,
            PortfolioSnapshot.fx_rate_usd_brl,
            PortfolioSnapshotItem.quantity,
            PortfolioSnapshotItem.unit_price,
            PortfolioSnapshotItem.market_value_native,
            PortfolioSnapshotItem.market_value_brl,
            PortfolioSnapshotItem.market_value_usd,
            PortfolioSnapshotItem.total_invested_brl,
        )
        .join(
            PortfolioSnapshotItem,
            PortfolioSnapshotItem.snapshot_id == PortfolioSnapshot.id,
        )
        .filter(
            PortfolioSnapshot.workspace_id == asset.workspace_id,
            PortfolioSnapshot.status == SnapshotStatus.CLOSED,
            PortfolioSnapshotItem.asset_id == asset_id,
        )
        .order_by(PortfolioSnapshot.period_end_date.desc())
        .all()
    )

    def _opt(x: object) -> str | None:
        return None if x is None else str(x)

    return AssetSnapshotHistoryOut(
        asset_id=asset_id,
        currency=asset.currency.value,
        items=[
            AssetSnapshotHistoryItem(
                period_end_date=ped.isoformat(),
                quantity=str(qty),
                unit_price=_opt(up),
                market_value_native=_opt(mvn),
                market_value_brl=_opt(mvb),
                market_value_usd=_opt(mvu),
                total_invested_brl=_opt(tib),
                fx_rate_usd_brl=_opt(fx),
            )
            for (ped, fx, qty, up, mvn, mvb, mvu, tib) in rows
        ],
    )


@router.get("/{asset_id}/asset-movements", response_model=AssetMovementsPage)
def list_asset_movements(
    asset_id: str,
    include_inactive: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    asset = _get_or_404(db, asset_id)
    _check_workspace_access(asset, current_user)
    q = db.query(AssetMovement).filter(AssetMovement.asset_id == asset_id)
    if not include_inactive:
        q = q.filter(AssetMovement.is_active == True)  # noqa: E712
    total = q.count()
    rows = (
        q.order_by(AssetMovement.event_date.desc(), AssetMovement.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    items = [
        AssetMovementLite(
            id=m.id,
            workspace_id=m.workspace_id,
            asset_id=m.asset_id,
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
            is_active=m.is_active,
            created_at=m.created_at.isoformat(),
            updated_at=m.updated_at.isoformat(),
        )
        for m in rows
    ]
    return AssetMovementsPage(items=items, total=total, page=page, page_size=page_size)


@router.put("/{asset_id}/deactivate", response_model=AssetOut)
def deactivate_asset(
    asset_id: str,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    asset = _get_or_404(db, asset_id)
    _check_workspace_access(asset, current_user)
    asset.is_active = False
    asset.updated_at = datetime.now(timezone.utc)
    asset.updated_by = current_user.user_id
    db.flush()
    _audit(db, current_user, "asset.deactivated", asset)

    account = db.get(Account, asset.account_id)
    fi_id = account.financial_institution_id if account else ""
    fi = db.get(FinancialInstitution, fi_id) if fi_id else None
    fi_name = fi.short_name if fi else fi_id
    ws_name: str | None = None
    if current_user.role == UserRole.sysadmin:
        ws = db.get(Workspace, asset.workspace_id)
        ws_name = ws.name if ws else None
    return AssetOut.from_orm(
        asset, fi_name,
        account_name=account.name if account else asset.account_id,
        fi_id=fi_id,
        workspace_name=ws_name,
    )
