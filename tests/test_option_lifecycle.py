"""Spec 17 — option lifecycle service tests."""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from numis_geek.db.base import Base
import numis_geek.models  # noqa: F401
from numis_geek.models.account import Account, AccountType, Currency
from numis_geek.models.asset import Asset, AssetClass, OptionType
from numis_geek.models.asset_movement import AssetMovement, AssetMovementType
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.workspace import Workspace
from numis_geek.services.option_lifecycle import (
    OptionLifecycleError,
    auto_settle_expired_options,
    compute_open_options,
    exercise_option,
    expire_option,
    parse_br_option_ticker,
)

TEST_ENGINE = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(bind=TEST_ENGINE, autoflush=False, autocommit=False)


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    Base.metadata.create_all(TEST_ENGINE)
    yield
    Base.metadata.drop_all(TEST_ENGINE)


@pytest.fixture
def db():
    s = TestSession()
    yield s
    s.rollback()
    s.close()


def _seed_world(db) -> dict:
    now = datetime.now(timezone.utc)
    ws = Workspace(id=str(uuid.uuid4()), name="OptWS")
    fi = FinancialInstitution(
        id=str(uuid.uuid4()), long_name="XP", short_name="XP", logo_slug="xp",
        is_active=True, created_at=now, updated_at=now,
    )
    acc = Account(
        id=str(uuid.uuid4()), workspace_id=ws.id, financial_institution_id=fi.id,
        name="XP Inv", account_type=AccountType.investment, currency=Currency.BRL,
        is_active=True, created_at=now, updated_at=now,
    )
    itub4 = Asset(
        id=str(uuid.uuid4()), workspace_id=ws.id, account_id=acc.id,
        asset_class=AssetClass.STOCK, country="BR", name="ITUB4", ticker="ITUB4",
        currency=Currency.BRL, current_price=Decimal("33.42"),
        is_active=True, created_at=now, updated_at=now,
    )
    db.add_all([ws, fi, acc, itub4])
    db.flush()
    return {"ws": ws, "acc": acc, "itub4": itub4, "now": now}


def _seed_option(db, world, *, ticker, opt_type, strike, qty, premium_per_share):
    now = world["now"]
    opt = Asset(
        id=str(uuid.uuid4()), workspace_id=world["ws"].id, account_id=world["acc"].id,
        asset_class=AssetClass.OPTION, country="BR", name=f"{opt_type.value} ITUB4",
        ticker=ticker, currency=Currency.BRL,
        is_active=True,
        underlying_id=world["itub4"].id,
        option_type=opt_type,
        strike_price=strike,
        expiration_date=date(2026, 6, 19),
        contract_size=100,
        created_at=now, updated_at=now,
    )
    db.add(opt)
    db.flush()
    sell_open = AssetMovement(
        id=str(uuid.uuid4()), workspace_id=world["ws"].id, asset_id=opt.id,
        type=AssetMovementType.SELL_OPEN, event_date=date(2026, 5, 2),
        quantity=qty, unit_price=premium_per_share,
        gross_amount=qty * premium_per_share,
        fee=Decimal("0"), tax=Decimal("0"),
        net_amount=qty * premium_per_share,  # premium received
        currency=Currency.BRL, fx_rate=Decimal("1"),
        is_active=True, created_at=now, updated_at=now,
    )
    db.add(sell_open)
    db.flush()
    return opt


# ── Parser tests ─────────────────────────────────────────────────────────────


def test_parse_itubr364():
    p = parse_br_option_ticker("ITUBR364", Decimal("33"))
    assert p is not None
    assert p.prefix == "ITUB"
    assert p.month == 6  # R = Jun PUT
    assert p.option_type == OptionType.PUT
    assert p.strike_suggested == Decimal("36.4")


def test_parse_itubf475():
    p = parse_br_option_ticker("ITUBF475", Decimal("33"))
    assert p.option_type == OptionType.CALL
    assert p.month == 6  # F = Jun CALL
    assert p.strike_suggested == Decimal("47.5")


def test_parse_invalid_returns_none():
    assert parse_br_option_ticker("INVALID") is None


# ── Lifecycle tests ──────────────────────────────────────────────────────────


def test_sold_put_exercised_creates_buy_at_strike_minus_premium(db):
    world = _seed_world(db)
    opt = _seed_option(
        db, world, ticker="ITUBR364", opt_type=OptionType.PUT,
        strike=Decimal("36.40"), qty=Decimal("1000"),
        premium_per_share=Decimal("0.09"),
    )

    exercised = exercise_option(db, opt.id, exercise_date=date(2026, 6, 19))
    assert exercised.type == AssetMovementType.EXERCISED
    assert exercised.related_movement_id is not None

    # Verify the BUY on the underlying
    underlying_mov = db.get(AssetMovement, exercised.related_movement_id)
    assert underlying_mov.type == AssetMovementType.BUY
    assert underlying_mov.asset_id == world["itub4"].id
    assert underlying_mov.quantity == Decimal("1000")
    # price = 36.40 - 0.09 = 36.31
    assert underlying_mov.unit_price == Decimal("36.31")

    # Option marked inactive
    db.refresh(opt)
    assert opt.is_active is False


def test_sold_call_exercised_creates_sell_at_strike_plus_premium(db):
    world = _seed_world(db)
    opt = _seed_option(
        db, world, ticker="ITUBF475", opt_type=OptionType.CALL,
        strike=Decimal("47.50"), qty=Decimal("1000"),
        premium_per_share=Decimal("0.34"),
    )

    exercised = exercise_option(db, opt.id, exercise_date=date(2026, 6, 19))
    underlying_mov = db.get(AssetMovement, exercised.related_movement_id)
    assert underlying_mov.type == AssetMovementType.SELL
    assert underlying_mov.unit_price == Decimal("47.84")  # 47.50 + 0.34


def test_expire_worthless_only_zeroes_position(db):
    world = _seed_world(db)
    opt = _seed_option(
        db, world, ticker="ITUBF475", opt_type=OptionType.CALL,
        strike=Decimal("47.50"), qty=Decimal("1000"),
        premium_per_share=Decimal("0.34"),
    )
    expired = expire_option(db, opt.id, date(2026, 6, 19))
    assert expired.type == AssetMovementType.EXPIRED
    assert expired.related_movement_id is None  # no underlying movement

    # No BUY/SELL on ITUB4 was created by expire
    n = db.query(AssetMovement).filter(
        AssetMovement.asset_id == world["itub4"].id,
    ).count()
    assert n == 0

    db.refresh(opt)
    assert opt.is_active is False


def test_compute_open_options_lists_only_active(db):
    world = _seed_world(db)
    opt1 = _seed_option(
        db, world, ticker="ITUBR364", opt_type=OptionType.PUT,
        strike=Decimal("36.40"), qty=Decimal("1000"),
        premium_per_share=Decimal("0.09"),
    )
    opt2 = _seed_option(
        db, world, ticker="ITUBF475", opt_type=OptionType.CALL,
        strike=Decimal("47.50"), qty=Decimal("1000"),
        premium_per_share=Decimal("0.34"),
    )

    rows = compute_open_options(db, world["itub4"].id, as_of=date(2026, 5, 10))
    assert len(rows) == 2

    # Both PUT and CALL should be present
    types = {r.option_type for r in rows}
    assert OptionType.PUT in types and OptionType.CALL in types

    # PUT (strike 36.40, ITUB4 at 33.42) is ITM → likely_exercise
    put_row = next(r for r in rows if r.option_type == OptionType.PUT)
    assert put_row.verdict == "likely_exercise"
    assert put_row.is_short is True
    assert put_row.premium_received == Decimal("90.00")  # 1000 × 0.09
    assert put_row.effective_price == Decimal("36.31")

    # CALL (strike 47.50, ITUB4 at 33.42) is OTM → likely_worthless
    call_row = next(r for r in rows if r.option_type == OptionType.CALL)
    assert call_row.verdict == "likely_worthless"
    assert call_row.effective_price == Decimal("47.84")


def test_exercise_already_closed_raises(db):
    world = _seed_world(db)
    opt = _seed_option(
        db, world, ticker="ITUBR364", opt_type=OptionType.PUT,
        strike=Decimal("36.40"), qty=Decimal("1000"),
        premium_per_share=Decimal("0.09"),
    )
    exercise_option(db, opt.id, date(2026, 6, 19))
    with pytest.raises(OptionLifecycleError):
        exercise_option(db, opt.id, date(2026, 6, 19))


# ── Auto-settlement ──────────────────────────────────────────────────────────


def _today():
    return date(2026, 6, 22)


def _stub_historical_price(monkeypatch, price: Decimal | None):
    """Substitui fetch_price_on dentro do option_lifecycle por um stub.

    Se price=None, simula HistoricalPriceNotFound.
    Caso contrário devolve um HistoricalPrice com source='stub'.
    """
    from numis_geek.services import option_lifecycle as ol
    from numis_geek.services.historical_price import (
        HistoricalPrice, HistoricalPriceNotFound,
    )

    def _fake(_db, _asset, target):
        if price is None:
            raise HistoricalPriceNotFound("stub: sem preço")
        return HistoricalPrice(price=price, source="stub", effective_date=target)

    monkeypatch.setattr(ol, "fetch_price_on", _fake)


def test_auto_settle_put_out_of_money_expires(db, monkeypatch):
    """ITUB4 = 39.87 em 19/06, strike PUT 36.40 → OTM → vira pó."""
    world = _seed_world(db)
    _stub_historical_price(monkeypatch, Decimal("39.87"))
    opt = _seed_option(
        db, world, ticker="ITUBR364", opt_type=OptionType.PUT,
        strike=Decimal("36.40"), qty=Decimal("1000"),
        premium_per_share=Decimal("0.09"),
    )
    results = auto_settle_expired_options(db, today=_today())
    assert len(results) == 1
    r = results[0]
    assert r.option_id == opt.id
    assert r.decision == "expired"
    assert r.underlying_price == Decimal("39.87")
    assert r.price_source == "stub"
    db.refresh(opt)
    assert opt.is_active is False
    expired_mv = db.query(AssetMovement).filter(
        AssetMovement.asset_id == opt.id,
        AssetMovement.type == AssetMovementType.EXPIRED,
    ).one()
    assert expired_mv.event_date == date(2026, 6, 19)
    assert expired_mv.quantity == Decimal("1000")


def test_auto_settle_put_in_the_money_exercises(db, monkeypatch):
    """ITUB4 = 35.00 em 19/06, strike PUT 36.40 → ITM → exercida."""
    world = _seed_world(db)
    _stub_historical_price(monkeypatch, Decimal("35.00"))
    opt = _seed_option(
        db, world, ticker="ITUBR364", opt_type=OptionType.PUT,
        strike=Decimal("36.40"), qty=Decimal("1000"),
        premium_per_share=Decimal("0.09"),
    )
    results = auto_settle_expired_options(db, today=_today())
    assert len(results) == 1
    assert results[0].decision == "exercised"
    db.refresh(opt)
    assert opt.is_active is False
    buy = db.query(AssetMovement).filter(
        AssetMovement.asset_id == world["itub4"].id,
        AssetMovement.type == AssetMovementType.BUY,
    ).one()
    assert buy.unit_price == Decimal("36.31")


def test_auto_settle_call_in_the_money_exercises(db, monkeypatch):
    """ITUB4 = 50.00 em 19/06, strike CALL 47.50 → ITM → exercida (vende)."""
    world = _seed_world(db)
    _stub_historical_price(monkeypatch, Decimal("50.00"))
    opt = _seed_option(
        db, world, ticker="ITUBF475", opt_type=OptionType.CALL,
        strike=Decimal("47.50"), qty=Decimal("1000"),
        premium_per_share=Decimal("0.34"),
    )
    results = auto_settle_expired_options(db, today=_today())
    assert results[0].decision == "exercised"
    sell = db.query(AssetMovement).filter(
        AssetMovement.asset_id == world["itub4"].id,
        AssetMovement.type == AssetMovementType.SELL,
    ).one()
    assert sell.unit_price == Decimal("47.84")


def test_auto_settle_at_the_money_expires(db, monkeypatch):
    """Convenção: equal vira pó (PCO B3)."""
    world = _seed_world(db)
    _stub_historical_price(monkeypatch, Decimal("36.40"))
    _seed_option(
        db, world, ticker="ITUBR364", opt_type=OptionType.PUT,
        strike=Decimal("36.40"), qty=Decimal("1000"),
        premium_per_share=Decimal("0.09"),
    )
    results = auto_settle_expired_options(db, today=_today())
    assert results[0].decision == "expired"


def test_auto_settle_skips_when_historical_price_unavailable(db, monkeypatch):
    """Sem preço histórico do underlying → skip (sem decisão errada)."""
    world = _seed_world(db)
    _stub_historical_price(monkeypatch, None)
    _seed_option(
        db, world, ticker="ITUBR364", opt_type=OptionType.PUT,
        strike=Decimal("36.40"), qty=Decimal("1000"),
        premium_per_share=Decimal("0.09"),
    )
    results = auto_settle_expired_options(db, today=_today())
    assert results[0].decision == "skipped"
    assert "stub: sem preço" in results[0].reason


def test_auto_settle_uses_expiration_date_price_not_today(db, monkeypatch):
    """Preço cobrado é o da DATA DE VENCIMENTO, não 'hoje'.

    Cenário: opção venceu 19/06 com underlying a R$ 35 (ITM, deveria exercer).
    Em 22/06 (hoje) underlying já está a R$ 45. Se o sistema usasse o preço
    de hoje, decidiria 'pó' errado. Stub recebe a target_date e devolve o
    preço CERTO do dia 19/06.
    """
    world = _seed_world(db)
    world["itub4"].current_price = Decimal("45.00")  # preço "de hoje"
    captured: list[date] = []

    from numis_geek.services import option_lifecycle as ol
    from numis_geek.services.historical_price import HistoricalPrice

    def _fake(_db, _asset, target):
        captured.append(target)
        return HistoricalPrice(
            price=Decimal("35.00"),  # preço REAL do dia 19/06
            source="stub", effective_date=target,
        )

    monkeypatch.setattr(ol, "fetch_price_on", _fake)
    _seed_option(
        db, world, ticker="ITUBR364", opt_type=OptionType.PUT,
        strike=Decimal("36.40"), qty=Decimal("1000"),
        premium_per_share=Decimal("0.09"),
    )
    results = auto_settle_expired_options(db, today=_today())
    assert captured == [date(2026, 6, 19)]  # pediu o preço da expiração
    assert results[0].decision == "exercised"  # decidiu pelo preço CERTO


def test_auto_settle_ignores_not_yet_expired(db, monkeypatch):
    """Opção com expiration_date >= today nem entra na query."""
    world = _seed_world(db)
    _stub_historical_price(monkeypatch, Decimal("39.87"))
    _seed_option(
        db, world, ticker="ITUBR364", opt_type=OptionType.PUT,
        strike=Decimal("36.40"), qty=Decimal("1000"),
        premium_per_share=Decimal("0.09"),
    )
    results = auto_settle_expired_options(db, today=date(2026, 6, 19))
    assert results == []


def test_auto_settle_ignores_already_closed_option(db, monkeypatch):
    """Opção já com is_active=False não é tocada."""
    world = _seed_world(db)
    _stub_historical_price(monkeypatch, Decimal("39.87"))
    opt = _seed_option(
        db, world, ticker="ITUBR364", opt_type=OptionType.PUT,
        strike=Decimal("36.40"), qty=Decimal("1000"),
        premium_per_share=Decimal("0.09"),
    )
    expire_option(db, opt.id, date(2026, 6, 19))
    results = auto_settle_expired_options(db, today=_today())
    assert results == []
