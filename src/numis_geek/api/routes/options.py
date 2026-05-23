"""Spec 17 — Options API routes."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from numis_geek.api.deps import get_current_user, get_db
from numis_geek.models.account import Account, Currency
from numis_geek.models.asset import Asset, AssetClass, OptionType
from numis_geek.models.asset_movement import AssetMovement, AssetMovementType
from numis_geek.models.user import UserRole
from numis_geek.models.workspace import Workspace
from numis_geek.services.auth import UserContext
from numis_geek.services.option_lifecycle import (
    OptionLifecycleError,
    compute_open_options,
    exercise_option,
    expire_option,
    parse_br_option_ticker,
)

router = APIRouter(prefix="/options", tags=["options"])


# ── Schemas ──────────────────────────────────────────────────────────────────


class OptionCreateRequest(BaseModel):
    ticker: str = Field(min_length=4, max_length=12)
    name: str | None = None
    underlying_id: str
    account_id: str
    option_type: OptionType
    strike_price: Decimal
    expiration_date: date
    contract_size: int = 100
    # First movement to open the position
    movement_type: Literal["SELL_OPEN", "BUY_TO_OPEN"] = "SELL_OPEN"
    movement_date: date
    quantity: Decimal
    price_per_share: Decimal
    fee: Decimal = Decimal("0")
    tax: Decimal = Decimal("0")
    notes: str | None = None
    workspace_id: str | None = None  # sysadmin only

    @model_validator(mode="after")
    def _validate(self) -> "OptionCreateRequest":
        if self.strike_price <= 0:
            raise ValueError("strike_price must be > 0")
        if self.quantity <= 0:
            raise ValueError("quantity must be > 0")
        if self.price_per_share < 0:
            raise ValueError("price_per_share must be >= 0")
        return self


class OptionOut(BaseModel):
    id: str
    ticker: str
    name: str
    underlying_id: str
    underlying_ticker: str | None
    option_type: str
    strike_price: float
    expiration_date: str
    contract_size: int
    currency: str
    is_active: bool
    account_id: str
    workspace_id: str

    @classmethod
    def from_orm(cls, a: Asset, underlying: Asset | None) -> "OptionOut":
        return cls(
            id=a.id,
            ticker=a.ticker or "",
            name=a.name,
            underlying_id=a.underlying_id,
            underlying_ticker=underlying.ticker if underlying else None,
            option_type=a.option_type.value if a.option_type else "",
            strike_price=float(a.strike_price) if a.strike_price else 0.0,
            expiration_date=a.expiration_date.isoformat() if a.expiration_date else "",
            contract_size=a.contract_size or 100,
            currency=a.currency.value,
            is_active=a.is_active,
            account_id=a.account_id,
            workspace_id=a.workspace_id,
        )


class ParseResult(BaseModel):
    prefix: str
    month: int
    option_type: str
    strike_digits: str
    strike_suggested: float
    adjustment_suffix: str | None


class OpenOptionOut(BaseModel):
    option_id: str
    ticker: str
    name: str
    option_type: str
    strike: float
    expiration_date: str
    days_to_expiration: int
    contract_size: int
    qty: float
    is_short: bool
    premium_received: float
    premium_per_share: float
    current_price: float | None
    mark_to_market: float | None
    close_now_pnl: float | None
    effective_price: float | None
    verdict: str


class ExerciseRequest(BaseModel):
    exercise_date: date


class ExpireRequest(BaseModel):
    expiration_date: date | None = None


class CloseRequest(BaseModel):
    close_date: date
    quantity: Decimal
    price_per_share: Decimal
    movement_type: Literal["BUY_TO_CLOSE", "SELL_TO_CLOSE"] = "BUY_TO_CLOSE"
    fee: Decimal = Decimal("0")
    notes: str | None = None


# ── Helpers ──────────────────────────────────────────────────────────────────


def _resolve_workspace_id(body, current_user: UserContext, db: Session) -> str:
    if current_user.role == UserRole.sysadmin:
        ws_id = getattr(body, "workspace_id", None)
        if not ws_id:
            raise HTTPException(400, "workspace_id is required for sysadmin")
        if not db.get(Workspace, ws_id):
            raise HTTPException(404, "Workspace not found")
        return ws_id
    if not current_user.workspace_id:
        raise HTTPException(400, "No workspace bound to user")
    return current_user.workspace_id


def _get_option_or_404(db: Session, oid: str, current_user: UserContext) -> Asset:
    opt = db.get(Asset, oid)
    if not opt or opt.asset_class != AssetClass.OPTION:
        raise HTTPException(404, "Option not found")
    if current_user.role != UserRole.sysadmin and opt.workspace_id != current_user.workspace_id:
        raise HTTPException(404, "Option not found")
    return opt


# ── Routes ───────────────────────────────────────────────────────────────────


@router.get("/parse", response_model=ParseResult | None)
def parse_ticker(
    ticker: str = Query(...),
    underlying_price: float | None = Query(default=None),
):
    parsed = parse_br_option_ticker(
        ticker,
        Decimal(str(underlying_price)) if underlying_price is not None else None,
    )
    if not parsed:
        raise HTTPException(400, f"Cannot parse ticker {ticker!r}")
    return ParseResult(
        prefix=parsed.prefix,
        month=parsed.month,
        option_type=parsed.option_type.value,
        strike_digits=parsed.strike_digits,
        strike_suggested=float(parsed.strike_suggested),
        adjustment_suffix=parsed.adjustment_suffix,
    )


@router.post("", response_model=OptionOut, status_code=status.HTTP_201_CREATED)
def create_option(
    body: OptionCreateRequest,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    workspace_id = _resolve_workspace_id(body, current_user, db)
    underlying = db.get(Asset, body.underlying_id)
    if not underlying:
        raise HTTPException(404, "Underlying asset not found")
    account = db.get(Account, body.account_id)
    if not account:
        raise HTTPException(404, "Account not found")

    now = datetime.now(timezone.utc)
    option = Asset(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        account_id=account.id,
        asset_class=AssetClass.OPTION,
        country=underlying.country,
        name=body.name or f"{body.option_type.value} {underlying.ticker or underlying.name} · strike R$ {body.strike_price} · vence {body.expiration_date.isoformat()}",
        ticker=body.ticker.upper(),
        currency=underlying.currency,
        is_active=True,
        underlying_id=underlying.id,
        option_type=body.option_type,
        strike_price=body.strike_price,
        expiration_date=body.expiration_date,
        contract_size=body.contract_size,
        created_at=now,
        updated_at=now,
        created_by=current_user.user_id,
        updated_by=current_user.user_id,
    )
    db.add(option)
    db.flush()

    # First movement to open the position
    mtype = (AssetMovementType.SELL_OPEN
             if body.movement_type == "SELL_OPEN"
             else AssetMovementType.BUY_TO_OPEN)
    gross = body.quantity * body.price_per_share
    # SELL_OPEN: cash IN (premium received); BUY_TO_OPEN: cash OUT
    if mtype == AssetMovementType.SELL_OPEN:
        net = gross - (body.fee or Decimal("0")) - (body.tax or Decimal("0"))
    else:
        net = -(gross + (body.fee or Decimal("0")) + (body.tax or Decimal("0")))

    db.add(AssetMovement(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        asset_id=option.id,
        type=mtype,
        event_date=body.movement_date,
        quantity=body.quantity,
        unit_price=body.price_per_share,
        gross_amount=gross,
        fee=body.fee,
        tax=body.tax,
        net_amount=net,
        currency=underlying.currency,
        fx_rate=Decimal("1"),
        notes=body.notes,
        is_active=True,
        created_at=now,
        updated_at=now,
        created_by=current_user.user_id,
        updated_by=current_user.user_id,
    ))
    db.flush()
    return OptionOut.from_orm(option, underlying)


@router.get("/{oid}", response_model=OptionOut)
def get_option(
    oid: str,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    opt = _get_option_or_404(db, oid, current_user)
    underlying = db.get(Asset, opt.underlying_id) if opt.underlying_id else None
    return OptionOut.from_orm(opt, underlying)


@router.get("/by-underlying/{underlying_id}", response_model=list[OpenOptionOut])
def list_open_for_underlying(
    underlying_id: str,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    underlying = db.get(Asset, underlying_id)
    if not underlying:
        raise HTTPException(404, "Asset not found")
    if current_user.role != UserRole.sysadmin and underlying.workspace_id != current_user.workspace_id:
        raise HTTPException(404, "Asset not found")
    rows = compute_open_options(db, underlying_id)
    return [
        OpenOptionOut(
            option_id=r.option_id,
            ticker=r.ticker,
            name=r.name,
            option_type=r.option_type.value,
            strike=float(r.strike),
            expiration_date=r.expiration_date.isoformat(),
            days_to_expiration=r.days_to_expiration,
            contract_size=r.contract_size,
            qty=float(r.qty),
            is_short=r.is_short,
            premium_received=float(r.premium_received),
            premium_per_share=float(r.premium_per_share),
            current_price=float(r.current_price) if r.current_price is not None else None,
            mark_to_market=float(r.mark_to_market) if r.mark_to_market is not None else None,
            close_now_pnl=float(r.close_now_pnl) if r.close_now_pnl is not None else None,
            effective_price=float(r.effective_price) if r.effective_price is not None else None,
            verdict=r.verdict,
        )
        for r in rows
    ]


@router.post("/{oid}/exercise", response_model=OptionOut)
def exercise(
    oid: str,
    body: ExerciseRequest,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    opt = _get_option_or_404(db, oid, current_user)
    try:
        exercise_option(db, oid, body.exercise_date, created_by=current_user.user_id)
    except OptionLifecycleError as e:
        raise HTTPException(400, str(e))
    underlying = db.get(Asset, opt.underlying_id) if opt.underlying_id else None
    return OptionOut.from_orm(opt, underlying)


@router.post("/{oid}/expire", response_model=OptionOut)
def expire(
    oid: str,
    body: ExpireRequest,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    opt = _get_option_or_404(db, oid, current_user)
    try:
        expire_option(db, oid, body.expiration_date, created_by=current_user.user_id)
    except OptionLifecycleError as e:
        raise HTTPException(400, str(e))
    underlying = db.get(Asset, opt.underlying_id) if opt.underlying_id else None
    return OptionOut.from_orm(opt, underlying)


@router.post("/{oid}/close", response_model=OptionOut)
def close_manual(
    oid: str,
    body: CloseRequest,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    opt = _get_option_or_404(db, oid, current_user)
    if not opt.is_active:
        raise HTTPException(400, "Option is already closed.")
    mtype = (AssetMovementType.BUY_TO_CLOSE
             if body.movement_type == "BUY_TO_CLOSE"
             else AssetMovementType.SELL_TO_CLOSE)
    gross = body.quantity * body.price_per_share
    net = -(gross + body.fee) if mtype == AssetMovementType.BUY_TO_CLOSE else (gross - body.fee)
    now = datetime.now(timezone.utc)
    db.add(AssetMovement(
        id=str(uuid.uuid4()),
        workspace_id=opt.workspace_id,
        asset_id=opt.id,
        type=mtype,
        event_date=body.close_date,
        quantity=body.quantity,
        unit_price=body.price_per_share,
        gross_amount=gross,
        fee=body.fee,
        tax=Decimal("0"),
        net_amount=net,
        currency=opt.currency,
        fx_rate=Decimal("1"),
        notes=body.notes,
        is_active=True,
        created_at=now,
        updated_at=now,
        created_by=current_user.user_id,
        updated_by=current_user.user_id,
    ))
    db.flush()
    underlying = db.get(Asset, opt.underlying_id) if opt.underlying_id else None
    return OptionOut.from_orm(opt, underlying)
