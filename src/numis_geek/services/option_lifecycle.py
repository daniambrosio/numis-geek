"""Spec 17 — Option lifecycle service.

Handles open option computation, exercise (with auto-generated BUY/SELL on
the underlying using the strike±premium/share effective price), expire
worthless, and BR ticker parsing.

Source of truth: docs/options-rationale.md
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Literal

from sqlalchemy.orm import Session

from numis_geek.models.asset import Asset, AssetClass, OptionType
from numis_geek.models.asset_movement import AssetMovement, AssetMovementType


# ── BR ticker parser ─────────────────────────────────────────────────────────
# Format: [4-letter prefix][1 letter month+type][3-4 digit strike][optional adjustment]
# Month-letter map: A-L = CALLs (Jan-Dec), M-X = PUTs (Jan-Dec).

_MONTH_CALL = {chr(ord("A") + i): i + 1 for i in range(12)}  # A=1(Jan), L=12(Dec)
_MONTH_PUT = {chr(ord("M") + i): i + 1 for i in range(12)}   # M=1(Jan), X=12(Dec)

_TICKER_RE = re.compile(r"^([A-Z]{4})([A-X])(\d{1,4})([A-Z]?)$")


@dataclass(frozen=True)
class ParsedBROptionTicker:
    prefix: str
    month: int
    option_type: OptionType
    strike_digits: str
    strike_suggested: Decimal
    adjustment_suffix: str | None


def parse_br_option_ticker(ticker: str, underlying_price: Decimal | None = None) -> ParsedBROptionTicker | None:
    """ITUBR364 → prefix=ITUB, month=6, type=PUT, strike_digits=364,
    strike_suggested=36.40, adjustment_suffix=None.

    Strike suggestion: divides digits by 10 (B3 convention). UI should
    confirm — the suggestion is best-effort; some series put the decimal
    elsewhere. If `underlying_price` is given, the suggestion is sanity-
    checked: if it's > 5× underlying, try without dividing.
    """
    m = _TICKER_RE.match(ticker.upper().strip())
    if not m:
        return None
    prefix, letter, digits, suffix = m.groups()
    if letter in _MONTH_CALL:
        opt = OptionType.CALL
        month = _MONTH_CALL[letter]
    elif letter in _MONTH_PUT:
        opt = OptionType.PUT
        month = _MONTH_PUT[letter]
    else:
        return None

    raw = Decimal(digits)
    suggested = raw / Decimal("10")
    if underlying_price is not None and underlying_price > 0:
        if suggested > underlying_price * 5:
            suggested = raw
        elif suggested < underlying_price / Decimal("100"):
            suggested = raw * Decimal("10")

    return ParsedBROptionTicker(
        prefix=prefix,
        month=month,
        option_type=opt,
        strike_digits=digits,
        strike_suggested=suggested,
        adjustment_suffix=suffix or None,
    )


# ── Open options (computed) ──────────────────────────────────────────────────


@dataclass
class OpenOptionRow:
    option_id: str
    ticker: str
    name: str
    option_type: OptionType
    strike: Decimal
    expiration_date: date
    days_to_expiration: int
    contract_size: int
    qty: Decimal
    is_short: bool
    premium_received: Decimal  # net cash from open/close movements
    premium_per_share: Decimal
    current_price: Decimal | None
    mark_to_market: Decimal | None
    close_now_pnl: Decimal | None
    effective_price: Decimal | None
    verdict: Literal["likely_exercise", "likely_worthless", "unknown"]


def compute_open_options(
    db: Session, underlying_id: str, as_of: date | None = None,
) -> list[OpenOptionRow]:
    today = as_of or date.today()
    options = (
        db.query(Asset)
        .filter(
            Asset.asset_class == AssetClass.OPTION,
            Asset.underlying_id == underlying_id,
            Asset.is_active.is_(True),
        )
        .all()
    )
    underlying = db.get(Asset, underlying_id)
    out: list[OpenOptionRow] = []
    for opt in options:
        movs = (
            db.query(AssetMovement)
            .filter(AssetMovement.asset_id == opt.id, AssetMovement.is_active.is_(True))
            .all()
        )
        qty = Decimal("0")
        premium = Decimal("0")
        is_short = False
        for m in movs:
            if m.type in (AssetMovementType.SELL_OPEN, AssetMovementType.BUY_TO_OPEN):
                qty += (m.quantity or Decimal("0"))
                premium += (m.net_amount or Decimal("0"))
                if m.type == AssetMovementType.SELL_OPEN:
                    is_short = True
            elif m.type in (AssetMovementType.SELL_TO_CLOSE, AssetMovementType.BUY_TO_CLOSE):
                qty -= (m.quantity or Decimal("0"))
                premium += (m.net_amount or Decimal("0"))
            # EXERCISED / EXPIRED zero qty handled by walking through; if
            # they exist we already filtered is_active=False on the asset.

        if qty == 0:
            continue

        days = max(0, (opt.expiration_date - today).days) if opt.expiration_date else 0
        prem_per_share = (premium / qty) if qty else Decimal("0")
        if is_short:
            # Premium recorded as positive (cash in). Per share is +.
            prem_per_share = abs(prem_per_share)

        cur = opt.current_price
        mtm = (cur * qty) if cur is not None else None
        close_now = None
        if mtm is not None:
            close_now = premium - mtm if is_short else mtm - abs(premium)

        if opt.option_type == OptionType.PUT:
            effective = (opt.strike_price - prem_per_share) if opt.strike_price else None
        else:
            effective = (opt.strike_price + prem_per_share) if opt.strike_price else None

        verdict: Literal["likely_exercise", "likely_worthless", "unknown"] = "unknown"
        if underlying and underlying.current_price is not None and opt.strike_price:
            up = underlying.current_price
            if opt.option_type == OptionType.PUT:
                verdict = "likely_exercise" if up < opt.strike_price else "likely_worthless"
            else:
                verdict = "likely_exercise" if up > opt.strike_price else "likely_worthless"

        out.append(OpenOptionRow(
            option_id=opt.id,
            ticker=opt.ticker or opt.name,
            name=opt.name,
            option_type=opt.option_type,
            strike=opt.strike_price,
            expiration_date=opt.expiration_date,
            days_to_expiration=days,
            contract_size=opt.contract_size or 100,
            qty=qty,
            is_short=is_short,
            premium_received=premium,
            premium_per_share=prem_per_share,
            current_price=cur,
            mark_to_market=mtm,
            close_now_pnl=close_now,
            effective_price=effective,
            verdict=verdict,
        ))
    return out


# ── Exercise / expire ────────────────────────────────────────────────────────


class OptionLifecycleError(RuntimeError):
    pass


def _sum_open_qty(db: Session, option_id: str) -> tuple[Decimal, bool, Decimal]:
    """Returns (qty_open, is_short, premium_per_share)."""
    movs = db.query(AssetMovement).filter(
        AssetMovement.asset_id == option_id,
        AssetMovement.is_active.is_(True),
    ).all()
    qty = Decimal("0")
    premium = Decimal("0")
    is_short = False
    for m in movs:
        if m.type in (AssetMovementType.SELL_OPEN, AssetMovementType.BUY_TO_OPEN):
            qty += (m.quantity or Decimal("0"))
            premium += (m.net_amount or Decimal("0"))
            if m.type == AssetMovementType.SELL_OPEN:
                is_short = True
        elif m.type in (AssetMovementType.SELL_TO_CLOSE, AssetMovementType.BUY_TO_CLOSE):
            qty -= (m.quantity or Decimal("0"))
            premium += (m.net_amount or Decimal("0"))
    pps = abs(premium / qty) if qty else Decimal("0")
    return qty, is_short, pps


def exercise_option(
    db: Session,
    option_id: str,
    exercise_date: date,
    created_by: str | None = None,
) -> AssetMovement:
    """Sold PUT → BUY underlying at price = strike − premium/share.
    Sold CALL → SELL underlying at price = strike + premium/share.
    Long PUT  → SELL at strike − premium/share (premium was paid, so cost is recovered).
    Long CALL → BUY at strike + premium/share.

    Creates EXERCISED movement on the option AND a BUY/SELL on the
    underlying, linked via `related_movement_id`. Marks option inactive.
    """
    opt = db.get(Asset, option_id)
    if not opt or opt.asset_class != AssetClass.OPTION:
        raise OptionLifecycleError(f"Asset {option_id} is not an OPTION.")
    if not opt.is_active:
        raise OptionLifecycleError(f"Option {opt.ticker} is already closed.")
    if not opt.strike_price or not opt.option_type or not opt.underlying_id:
        raise OptionLifecycleError("Option missing required fields (strike/type/underlying).")

    qty_open, is_short, prem_per_share = _sum_open_qty(db, option_id)
    if qty_open == 0:
        raise OptionLifecycleError("No open position to exercise.")

    # Effective price
    if opt.option_type == OptionType.PUT:
        eff_price = opt.strike_price - prem_per_share
        underlying_dir = AssetMovementType.BUY if is_short else AssetMovementType.SELL
    else:
        eff_price = opt.strike_price + prem_per_share
        underlying_dir = AssetMovementType.SELL if is_short else AssetMovementType.BUY

    now = datetime.now(timezone.utc)

    # 1. Underlying BUY/SELL
    underlying = db.get(Asset, opt.underlying_id)
    if not underlying:
        raise OptionLifecycleError("Underlying asset not found.")
    gross = qty_open * eff_price
    net = gross if underlying_dir == AssetMovementType.SELL else -gross

    underlying_mov = AssetMovement(
        id=str(uuid.uuid4()),
        workspace_id=opt.workspace_id,
        asset_id=opt.underlying_id,
        type=underlying_dir,
        event_date=exercise_date,
        quantity=qty_open,
        unit_price=eff_price,
        gross_amount=gross,
        fee=Decimal("0"),
        tax=Decimal("0"),
        net_amount=net,
        currency=underlying.currency,
        fx_rate=Decimal("1"),
        notes=f"Exercício de {opt.ticker} · prêmio R$ {prem_per_share:.4f}/ação aplicado ao strike",
        is_active=True,
        created_at=now,
        updated_at=now,
        created_by=created_by,
        updated_by=created_by,
    )
    db.add(underlying_mov)
    db.flush()

    # 2. EXERCISED on the option, related to the underlying movement
    exercised = AssetMovement(
        id=str(uuid.uuid4()),
        workspace_id=opt.workspace_id,
        asset_id=opt.id,
        type=AssetMovementType.EXERCISED,
        event_date=exercise_date,
        quantity=qty_open,  # zeroes the open position
        unit_price=eff_price,
        gross_amount=Decimal("0"),
        fee=Decimal("0"),
        tax=Decimal("0"),
        net_amount=Decimal("0"),
        currency=opt.currency,
        fx_rate=Decimal("1"),
        notes=f"Underlying adquirido via movement id={underlying_mov.id}",
        related_movement_id=underlying_mov.id,
        is_active=True,
        created_at=now,
        updated_at=now,
        created_by=created_by,
        updated_by=created_by,
    )
    db.add(exercised)

    opt.is_active = False
    opt.updated_at = now
    db.flush()
    return exercised


def expire_option(
    db: Session,
    option_id: str,
    expiration_date: date | None = None,
    created_by: str | None = None,
) -> AssetMovement:
    """Creates EXPIRED movement. Premium received stays. Marks option inactive."""
    opt = db.get(Asset, option_id)
    if not opt or opt.asset_class != AssetClass.OPTION:
        raise OptionLifecycleError(f"Asset {option_id} is not an OPTION.")
    if not opt.is_active:
        raise OptionLifecycleError(f"Option {opt.ticker} is already closed.")

    qty_open, _, _ = _sum_open_qty(db, option_id)
    if qty_open == 0:
        raise OptionLifecycleError("No open position to expire.")

    when = expiration_date or opt.expiration_date or date.today()
    now = datetime.now(timezone.utc)

    expired = AssetMovement(
        id=str(uuid.uuid4()),
        workspace_id=opt.workspace_id,
        asset_id=opt.id,
        type=AssetMovementType.EXPIRED,
        event_date=when,
        quantity=qty_open,
        unit_price=Decimal("0"),
        gross_amount=Decimal("0"),
        fee=Decimal("0"),
        tax=Decimal("0"),
        net_amount=Decimal("0"),
        currency=opt.currency,
        fx_rate=Decimal("1"),
        notes="Opção venceu sem ser exercida (virou pó).",
        is_active=True,
        created_at=now,
        updated_at=now,
        created_by=created_by,
        updated_by=created_by,
    )
    db.add(expired)

    opt.is_active = False
    opt.updated_at = now
    db.flush()
    return expired
