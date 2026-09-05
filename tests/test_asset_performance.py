"""Spec 81 — rentabilidade mês a mês por ativo (services/asset_performance).

Fórmula por mês: r = (mv_fim − mv_ini − aportes + resgates + proventos) / mv_ini
sobre fechamentos CLOSED. Nativo primário, BRL secundário com o fx da linha.
"""
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
from numis_geek.models.distribution import Distribution, DistributionType
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.portfolio_snapshot import (
    PortfolioSnapshot,
    PortfolioSnapshotItem,
    SnapshotSource,
    SnapshotStatus,
)
from numis_geek.services.asset_performance import (
    cash_flows_in_window,
    chain_link,
    compute_asset_performance,
    monthly_return,
)
from numis_geek.services.workspace import WorkspaceService


ENGINE = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Session = sessionmaker(bind=ENGINE, autoflush=False, autocommit=False)

D = Decimal


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    Base.metadata.create_all(ENGINE)
    yield
    Base.metadata.drop_all(ENGINE)


@pytest.fixture
def world():
    db = Session()
    ws = WorkspaceService(db).create(f"PERF WS {uuid.uuid4().hex[:8]}")
    now = datetime.now(timezone.utc)
    fi = FinancialInstitution(
        id=str(uuid.uuid4()), long_name="XP", short_name=f"XP{uuid.uuid4().hex[:4]}",
        logo_slug="xp", is_active=True, created_at=now, updated_at=now,
    )
    db.add(fi)
    account = Account(
        id=str(uuid.uuid4()), workspace_id=ws.id,
        financial_institution_id=fi.id, name="Conta",
        account_type=AccountType.investment, currency=Currency.BRL,
        is_active=True, created_at=now, updated_at=now,
    )
    db.add(account)
    db.commit()
    yield {"db": db, "ws_id": ws.id, "account_id": account.id, "fi_id": fi.id}
    db.close()


def _asset(w, asset_class=AssetClass.STOCK, currency=Currency.BRL, **kw):
    now = datetime.now(timezone.utc)
    a = Asset(
        id=str(uuid.uuid4()), workspace_id=w["ws_id"], account_id=w["account_id"],
        asset_class=asset_class, country="BR" if currency == Currency.BRL else "US",
        name=f"A {uuid.uuid4().hex[:4]}", ticker=kw.pop("ticker", None),
        currency=currency, is_active=True, created_at=now, updated_at=now, **kw,
    )
    w["db"].add(a); w["db"].commit()
    return a


def _snap(w, period: str, *, fx=None, status=SnapshotStatus.CLOSED, is_active=True):
    now = datetime.now(timezone.utc)
    s = PortfolioSnapshot(
        id=str(uuid.uuid4()), workspace_id=w["ws_id"],
        period_end_date=date.fromisoformat(period),
        fx_rate_usd_brl=D(str(fx)) if fx is not None else None,
        source=SnapshotSource.MANUAL, status=status,
        total_value_brl=D("0"), total_value_usd=D("0"),
        total_invested_brl=D("0"), total_received_brl=D("0"),
        is_active=is_active, created_at=now, updated_at=now,
    )
    w["db"].add(s); w["db"].commit()
    return s


def _item(w, snap, asset, *, mv_native=None, mv_brl=None, mv_usd=None,
          qty="1", unit=None, invested=None):
    it = PortfolioSnapshotItem(
        id=str(uuid.uuid4()), snapshot_id=snap.id, asset_id=asset.id,
        quantity=D(qty), unit_price=D(str(unit)) if unit is not None else None,
        market_value_native=D(str(mv_native)) if mv_native is not None else None,
        market_value_brl=D(str(mv_brl)) if mv_brl is not None else None,
        market_value_usd=D(str(mv_usd)) if mv_usd is not None else None,
        total_invested_brl=D(str(invested)) if invested is not None else None,
        created_at=datetime.now(timezone.utc),
    )
    w["db"].add(it); w["db"].commit()
    return it


def _mov(w, asset, mtype, event: str, net, *, currency=Currency.BRL, fx=None,
         is_active=True):
    m = AssetMovement(
        id=str(uuid.uuid4()), workspace_id=w["ws_id"], asset_id=asset.id,
        type=mtype, event_date=date.fromisoformat(event),
        quantity=D("1"), unit_price=D(str(net)), gross_amount=D(str(net)),
        net_amount=D(str(net)), currency=currency,
        fx_rate=D(str(fx)) if fx is not None else None, is_active=is_active,
    )
    w["db"].add(m); w["db"].commit()
    return m


def _dist(w, asset, event: str, net, *, currency=Currency.BRL, fx="1"):
    now = datetime.now(timezone.utc)
    d = Distribution(
        id=str(uuid.uuid4()), workspace_id=w["ws_id"],
        financial_institution_id=w["fi_id"], asset_id=asset.id,
        type=DistributionType.DIVIDEND, event_date=date.fromisoformat(event),
        gross_amount=D(str(net)), tax=D("0"), net_amount=D(str(net)),
        currency=currency, fx_rate=D(fx), is_active=True,
        created_at=now, updated_at=now,
    )
    w["db"].add(d); w["db"].commit()
    return d


def _by_period(perf):
    return {r.period_end_date.isoformat(): r for r in perf.rows}


# ── puras ──────────────────────────────────────────────────────────────────


def test_monthly_return_formula_pure():
    # 1000 → 1150 com aporte 100, resgate 20 e provento 30: ganho real = 100
    r = monthly_return(D("1000"), D("1150"), D("100"), D("20"), D("30"))
    assert r == D("0.1")


def test_chain_link_product_and_gap():
    assert chain_link([D("0.10"), D("-0.05")]) == D("1.10") * D("0.95") - 1
    assert chain_link([D("0.10"), None, D("-0.05")]) is None
    assert chain_link([]) is None


def test_cash_flows_window_is_half_open_and_skips_inactive_and_come_cotas(world):
    a = _asset(world)
    _mov(world, a, AssetMovementType.BUY, "2026-01-31", 100)     # == start: fora
    _mov(world, a, AssetMovementType.BUY, "2026-02-01", 200)
    _mov(world, a, AssetMovementType.SELL, "2026-02-28", 50)      # == end: dentro
    _mov(world, a, AssetMovementType.BUY, "2026-02-10", 999, is_active=False)
    _mov(world, a, AssetMovementType.COME_COTAS, "2026-02-15", -7)
    _mov(world, a, AssetMovementType.BONUS, "2026-02-16", 0)
    movs = world["db"].query(AssetMovement).filter(AssetMovement.asset_id == a.id).all()
    ap, rs = cash_flows_in_window(movs, date(2026, 1, 31), date(2026, 2, 28), in_brl=False)
    assert (ap, rs) == (D("200"), D("50"))


def test_cash_flows_brl_multiplies_fx_only_for_usd_rows(world):
    a = _asset(world, currency=Currency.USD)
    _mov(world, a, AssetMovementType.BUY, "2026-02-05", 100, currency=Currency.USD, fx="5")
    b = _asset(world)
    _mov(world, b, AssetMovementType.BUY, "2026-02-05", 100, currency=Currency.BRL, fx="5")
    ma = world["db"].query(AssetMovement).filter(AssetMovement.asset_id == a.id).all()
    mb = world["db"].query(AssetMovement).filter(AssetMovement.asset_id == b.id).all()
    assert cash_flows_in_window(ma, None, date(2026, 2, 28), in_brl=True)[0] == D("500")
    assert cash_flows_in_window(mb, None, date(2026, 2, 28), in_brl=True)[0] == D("100")


# ── compute_asset_performance ──────────────────────────────────────────────


def test_first_closing_gap_and_zero_start_reasons(world):
    a = _asset(world)
    s1 = _snap(world, "2026-01-31"); _item(world, s1, a, mv_native=1000, mv_brl=1000)
    _snap(world, "2026-02-28")                                     # ativo ausente
    s3 = _snap(world, "2026-03-31"); _item(world, s3, a, mv_native=1100, mv_brl=1100)
    s4 = _snap(world, "2026-04-30"); _item(world, s4, a, mv_native=0, mv_brl=0)
    s5 = _snap(world, "2026-05-31"); _item(world, s5, a, mv_native=500, mv_brl=500)
    rows = _by_period(compute_asset_performance(world["db"], a.id))
    assert list(rows) == ["2026-01-31", "2026-03-31", "2026-04-30", "2026-05-31"]
    assert rows["2026-01-31"].return_null_reason == "FIRST_CLOSING"
    assert rows["2026-03-31"].return_null_reason == "GAP"
    assert rows["2026-04-30"].return_pct == D("-1")               # 1100 → 0
    assert rows["2026-05-31"].return_null_reason == "ZERO_START"


def test_cotado_brl_return_with_buy_and_dividend(world):
    a = _asset(world, ticker="ITUB4")
    s1 = _snap(world, "2026-01-31"); _item(world, s1, a, mv_native=1000, mv_brl=1000, invested=900)
    s2 = _snap(world, "2026-02-28"); _item(world, s2, a, mv_native=1250, mv_brl=1250, invested=1100)
    _mov(world, a, AssetMovementType.BUY, "2026-02-10", 200)
    _dist(world, a, "2026-02-20", 30)
    rows = _by_period(compute_asset_performance(world["db"], a.id))
    r = rows["2026-02-28"]
    # (1250 − 1000 − 200 + 0 + 30) / 1000 = 8%
    assert r.return_pct == D("0.08")
    assert r.return_brl_pct == D("0.08")
    assert r.aportes_native == D("200") and r.proventos_native == D("30")
    assert r.pnl_brl == D("150") and r.pnl_pct == D("150") / D("1100")
    assert rows["2026-01-31"].pnl_brl == D("100")


def test_value_mode_aporte_and_full_redemption(world):
    a = _asset(world, asset_class=AssetClass.FUND)
    s1 = _snap(world, "2026-01-31"); _item(world, s1, a, mv_native=10000, mv_brl=10000)
    s2 = _snap(world, "2026-02-28"); _item(world, s2, a, mv_native=15300, mv_brl=15300)
    s3 = _snap(world, "2026-03-31"); _item(world, s3, a, mv_native=0, mv_brl=0)
    _mov(world, a, AssetMovementType.BUY, "2026-02-05", 5000)
    _mov(world, a, AssetMovementType.FULL_REDEMPTION, "2026-03-10", 15500)
    perf = compute_asset_performance(world["db"], a.id)
    assert perf.is_value_mode is True
    rows = _by_period(perf)
    assert rows["2026-02-28"].return_pct == D("0.03")             # (15300−10000−5000)/10000
    # (0 − 15300 + 15500) / 15300
    assert rows["2026-03-31"].return_pct == D("200") / D("15300")


def test_come_cotas_and_bonus_ignored(world):
    a = _asset(world, asset_class=AssetClass.FUND)
    s1 = _snap(world, "2026-01-31"); _item(world, s1, a, mv_native=1000, mv_brl=1000)
    s2 = _snap(world, "2026-02-28"); _item(world, s2, a, mv_native=1010, mv_brl=1010)
    _mov(world, a, AssetMovementType.COME_COTAS, "2026-02-15", -5)
    _mov(world, a, AssetMovementType.BONUS, "2026-02-16", 0)
    rows = _by_period(compute_asset_performance(world["db"], a.id))
    assert rows["2026-02-28"].return_pct == D("0.01")
    assert rows["2026-02-28"].aportes_native == D("0")
    assert rows["2026-02-28"].resgates_native == D("0")


def test_usd_asset_native_vs_brl_return_uses_row_fx(world):
    a = _asset(world, currency=Currency.USD)
    s1 = _snap(world, "2026-01-31", fx="5.0")
    _item(world, s1, a, mv_native=1000, mv_brl=5000, mv_usd=1000)
    s2 = _snap(world, "2026-02-28", fx="6.0")
    _item(world, s2, a, mv_native=1000, mv_brl=6000, mv_usd=1000)
    _dist(world, a, "2026-02-10", 10, currency=Currency.USD, fx="5.5")
    rows = _by_period(compute_asset_performance(world["db"], a.id))
    r = rows["2026-02-28"]
    assert r.return_pct == D("0.01")                              # (1000−1000+10)/1000
    assert r.return_brl_pct == (D("6000") - D("5000") + D("55")) / D("5000")
    assert r.proventos_brl == D("55")


def test_usd_missing_fx_gives_missing_mv_but_brl_side_stays_none(world):
    a = _asset(world, currency=Currency.USD)
    s1 = _snap(world, "2026-01-31", fx=None)
    _item(world, s1, a, mv_native=None, mv_brl=5000)              # sem nativo nem fx
    s2 = _snap(world, "2026-02-28", fx="6.0")
    _item(world, s2, a, mv_native=1100, mv_brl=6600)
    rows = _by_period(compute_asset_performance(world["db"], a.id))
    r = rows["2026-02-28"]
    assert r.return_pct is None and r.return_null_reason == "MISSING_MV"
    assert r.return_brl_pct is None


def test_usd_native_derived_from_brl_and_fx_when_native_missing(world):
    a = _asset(world, currency=Currency.USD)
    s1 = _snap(world, "2026-01-31", fx="5.0")
    _item(world, s1, a, mv_native=None, mv_brl=5000)              # 1000 USD implícito
    s2 = _snap(world, "2026-02-28", fx="5.0")
    _item(world, s2, a, mv_native=1050, mv_brl=5250)
    rows = _by_period(compute_asset_performance(world["db"], a.id))
    assert rows["2026-02-28"].return_pct == D("0.05")


def test_option_premium_counts_as_provento_for_underlying(world):
    stock = _asset(world, ticker="PETR4")
    opt = _asset(
        world, asset_class=AssetClass.OPTION, ticker="PETRA100",
        underlying_id=stock.id, option_type=OptionType.CALL,
        strike_price=D("40"), expiration_date=date(2026, 3, 20), contract_size=100,
    )
    s1 = _snap(world, "2026-01-31"); _item(world, s1, stock, mv_native=1000, mv_brl=1000)
    s2 = _snap(world, "2026-02-28"); _item(world, s2, stock, mv_native=1000, mv_brl=1000)
    _item(world, s2, opt, mv_native=-20, mv_brl=-20)
    _mov(world, opt, AssetMovementType.SELL_OPEN, "2026-02-12", 50)
    rows = _by_period(compute_asset_performance(world["db"], stock.id))
    assert rows["2026-02-28"].proventos_native == D("50")
    assert rows["2026-02-28"].return_pct == D("0.05")
    # a própria opção nunca tem retorno
    orows = _by_period(compute_asset_performance(world["db"], opt.id))
    assert orows["2026-02-28"].return_null_reason == "OPTION"


def test_inactive_snapshot_and_in_review_ignored(world):
    a = _asset(world)
    s1 = _snap(world, "2026-01-31"); _item(world, s1, a, mv_native=1000, mv_brl=1000)
    s2 = _snap(world, "2026-02-28", is_active=False); _item(world, s2, a, mv_native=5, mv_brl=5)
    s3 = _snap(world, "2026-03-31", status=SnapshotStatus.IN_REVIEW)
    _item(world, s3, a, mv_native=7, mv_brl=7)
    s4 = _snap(world, "2026-04-30"); _item(world, s4, a, mv_native=1100, mv_brl=1100)
    rows = _by_period(compute_asset_performance(world["db"], a.id))
    assert list(rows) == ["2026-01-31", "2026-04-30"]
    assert rows["2026-04-30"].return_pct == D("0.1")


def test_movement_on_period_end_belongs_to_that_month(world):
    a = _asset(world)
    s1 = _snap(world, "2026-01-31"); _item(world, s1, a, mv_native=1000, mv_brl=1000)
    s2 = _snap(world, "2026-02-28"); _item(world, s2, a, mv_native=1100, mv_brl=1100)
    s3 = _snap(world, "2026-03-31"); _item(world, s3, a, mv_native=1100, mv_brl=1100)
    _mov(world, a, AssetMovementType.BUY, "2026-02-28", 100)      # dentro de fev
    _mov(world, a, AssetMovementType.BUY, "2026-01-31", 999)      # dentro de jan (1ª linha)
    rows = _by_period(compute_asset_performance(world["db"], a.id))
    assert rows["2026-02-28"].aportes_native == D("100")
    assert rows["2026-02-28"].return_pct == D("0")
    assert rows["2026-03-31"].aportes_native == D("0")
    assert rows["2026-01-31"].aportes_native == D("999")          # janela do 1º mês


def test_summary_12m_requires_12_rows_and_ytd(world):
    a = _asset(world)
    months = [
        "2025-06-30", "2025-07-31", "2025-08-31", "2025-09-30", "2025-10-31",
        "2025-11-30", "2025-12-31", "2026-01-31", "2026-02-28", "2026-03-31",
        "2026-04-30", "2026-05-31", "2026-06-30",
    ]
    mv = D("1000")
    for i, m in enumerate(months):
        s = _snap(world, m)
        _item(world, s, a, mv_native=mv, mv_brl=mv)
        mv = mv * D("1.01")
    perf = compute_asset_performance(world["db"], a.id)
    sm = perf.summary
    assert sm.as_of == date(2026, 6, 30)
    assert sm.months_in_12m == 12
    assert sm.return_12m_pct is not None
    # mv é Numeric(18,2): cada mês arredonda a 2 casas → tolerância 1e-4
    assert abs(sm.return_12m_pct - (D("1.01") ** 12 - 1)) < D("1e-4")
    assert sm.months_in_ytd == 6
    assert abs(sm.return_ytd_pct - (D("1.01") ** 6 - 1)) < D("1e-4")
    assert abs(sm.since_inception_pct - (D("1.01") ** 12 - 1)) < D("1e-4")


def test_summary_12m_none_with_short_history(world):
    a = _asset(world)
    for m, v in (("2026-04-30", 100), ("2026-05-31", 110), ("2026-06-30", 121)):
        s = _snap(world, m); _item(world, s, a, mv_native=v, mv_brl=v)
    sm = compute_asset_performance(world["db"], a.id).summary
    assert sm.return_12m_pct is None and sm.months_in_12m == 3
    assert sm.return_ytd_pct is None                              # 1ª linha é FIRST_CLOSING
    assert abs(sm.since_inception_pct - D("0.21")) < D("1e-12")


def test_no_closed_snapshots_returns_empty(world):
    a = _asset(world)
    perf = compute_asset_performance(world["db"], a.id)
    assert perf.rows == [] and perf.summary.as_of is None


def test_legacy_item_without_mv_falls_back_to_qty_times_unit_price(world):
    a = _asset(world)
    s1 = _snap(world, "2026-01-31"); _item(world, s1, a, qty="10", unit="100")   # sem mv
    s2 = _snap(world, "2026-02-28"); _item(world, s2, a, mv_native=1100, mv_brl=1100)
    rows = _by_period(compute_asset_performance(world["db"], a.id))
    assert rows["2026-01-31"].market_value_native == D("1000")
    assert rows["2026-02-28"].return_pct == D("0.1")
