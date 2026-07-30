"""Spec 20 — testes granulares dos helpers privados de portfolio_summary.

Foco: `_history`, `_total_received_brl`, `_received_by_type` e ranking
`top_holdings` isolados do endpoint (que já é coberto por test_portfolio.py).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from numis_geek.db.base import Base
import numis_geek.models  # noqa: F401 — registra todos os modelos
from numis_geek.models.account import Account, AccountType, Currency
from numis_geek.models.asset import Asset, AssetClass
from numis_geek.models.distribution import Distribution, DistributionType
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.portfolio_snapshot import (
    PortfolioSnapshot,
    PortfolioSnapshotItem,
    SnapshotSource,
)
from numis_geek.services.portfolio_summary import (
    _history,
    _received_by_type,
    _total_received_brl,
    compute_portfolio_summary,
)
from numis_geek.services.workspace import WorkspaceService


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


# ── Fixture builders ────────────────────────────────────────────────────────


def _mk_workspace(db, name: str) -> str:
    ws = WorkspaceService(db).create(name)
    db.flush()
    return ws.id


def _mk_fi(db, short_name: str = "XP", country: str = "BR") -> FinancialInstitution:
    now = datetime.now(timezone.utc)
    fi = FinancialInstitution(
        id=str(uuid.uuid4()),
        long_name=short_name,
        short_name=short_name,
        logo_slug=short_name.lower(),
        country=country,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(fi)
    db.flush()
    return fi


def _mk_account(
    db, workspace_id: str, fi_id: str, name: str = "Inv", currency=Currency.BRL,
) -> Account:
    now = datetime.now(timezone.utc)
    acc = Account(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        financial_institution_id=fi_id,
        name=name,
        account_type=AccountType.investment,
        currency=currency,
        opening_balance=Decimal("0"),
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(acc)
    db.flush()
    return acc


def _mk_asset(
    db, workspace_id: str, account_id: str, ticker: str,
    asset_class=AssetClass.STOCK, country: str = "BR", currency=Currency.BRL,
) -> Asset:
    now = datetime.now(timezone.utc)
    a = Asset(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        account_id=account_id,
        asset_class=asset_class,
        country=country,
        name=ticker,
        ticker=ticker,
        currency=currency,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(a)
    db.flush()
    return a


def _mk_snapshot(
    db, workspace_id: str, period_end: date, total_brl: Decimal,
) -> PortfolioSnapshot:
    now = datetime.now(timezone.utc)
    snap = PortfolioSnapshot(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        period_end_date=period_end,
        fx_rate_usd_brl=Decimal("5.00"),
        total_value_brl=total_brl,
        total_value_usd=total_brl / Decimal("5.00"),
        total_invested_brl=total_brl,
        total_received_brl=Decimal("0"),
        source=SnapshotSource.MANUAL,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(snap)
    db.flush()
    return snap


def _mk_item(
    db, snap_id: str, asset_id: str, mv_brl: Decimal, qty: Decimal = Decimal("1"),
    unit_price: Decimal | None = None,
) -> PortfolioSnapshotItem:
    unit_price = unit_price if unit_price is not None else mv_brl
    it = PortfolioSnapshotItem(
        id=str(uuid.uuid4()),
        snapshot_id=snap_id,
        asset_id=asset_id,
        quantity=qty,
        unit_price=unit_price,
        market_value_native=mv_brl,
        market_value_brl=mv_brl,
        market_value_usd=mv_brl / Decimal("5.00"),
    )
    db.add(it)
    db.flush()
    return it


def _mk_distribution(
    db, workspace_id: str, fi_id: str, asset_id: str | None,
    dtype: DistributionType, net_brl: Decimal, event_date: date,
    is_active: bool = True, currency=Currency.BRL, fx_rate=Decimal("1.0"),
) -> Distribution:
    now = datetime.now(timezone.utc)
    d = Distribution(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        financial_institution_id=fi_id,
        asset_id=asset_id,
        type=dtype,
        event_date=event_date,
        gross_amount=net_brl,
        tax=Decimal("0"),
        net_amount=net_brl,
        currency=currency,
        fx_rate=fx_rate,
        is_active=is_active,
        created_at=now,
        updated_at=now,
    )
    db.add(d)
    db.flush()
    return d


# ── _history ────────────────────────────────────────────────────────────────


def test_history_returns_all_snapshots_asc(db):
    ws = _mk_workspace(db, "hist-ws")
    fi = _mk_fi(db)
    acc = _mk_account(db, ws, fi.id)
    asset = _mk_asset(db, ws, acc.id, "PETR4", asset_class=AssetClass.STOCK)

    # 5 snapshots consecutivos (Jan..May 2026).
    dates = [date(2026, m, 28) for m in (1, 2, 3, 4, 5)]
    snaps = [_mk_snapshot(db, ws, d, Decimal("1000") + Decimal(i * 100))
             for i, d in enumerate(dates)]
    for snap in snaps:
        _mk_item(db, snap.id, asset.id, Decimal("500"))

    points = _history(db, ws, limit=12)
    assert len(points) == 5
    # ASC ordering pra charts.
    assert [p.period_end for p in points] == [d.isoformat() for d in dates]
    # by_class populado a partir dos items.
    for p in points:
        assert p.by_class == {"STOCK": Decimal("500")}
        assert p.total_brl == points[dates.index(date.fromisoformat(p.period_end))].total_brl


def test_history_respects_limit(db):
    ws = _mk_workspace(db, "hist-limit-ws")
    for m in range(1, 6):  # 5 snapshots
        _mk_snapshot(db, ws, date(2026, m, 28), Decimal("0"))
    points = _history(db, ws, limit=3)
    # Últimos 3 (Mar, Apr, May) em ASC.
    assert [p.period_end for p in points] == [
        "2026-03-28", "2026-04-28", "2026-05-28",
    ]


def test_history_empty_workspace(db):
    ws = _mk_workspace(db, "hist-empty-ws")
    assert _history(db, ws) == []


# ── _total_received_brl / _received_by_type ─────────────────────────────────


def test_total_received_brl_sums_and_excludes_inactive(db):
    ws = _mk_workspace(db, "dist-ws")
    fi = _mk_fi(db)
    acc = _mk_account(db, ws, fi.id)
    asset = _mk_asset(db, ws, acc.id, "PETR4")

    # 3 distributions ativas.
    _mk_distribution(
        db, ws, fi.id, asset.id, DistributionType.DIVIDEND,
        Decimal("100.00"), date(2026, 1, 15),
    )
    _mk_distribution(
        db, ws, fi.id, asset.id, DistributionType.JCP,
        Decimal("50.00"), date(2026, 2, 15),
    )
    # USD distribution — deve multiplicar por fx_rate.
    _mk_distribution(
        db, ws, fi.id, asset.id, DistributionType.INTEREST,
        Decimal("20.00"), date(2026, 3, 15),
        currency=Currency.USD, fx_rate=Decimal("5.00"),  # → 100 BRL
    )
    # 1 desativada — NÃO deve entrar na soma.
    _mk_distribution(
        db, ws, fi.id, asset.id, DistributionType.DIVIDEND,
        Decimal("999.00"), date(2026, 1, 1), is_active=False,
    )

    total = _total_received_brl(db, ws)
    assert total == Decimal("250.00")  # 100 + 50 + (20 * 5)


def test_total_received_brl_empty(db):
    ws = _mk_workspace(db, "no-dist-ws")
    assert _total_received_brl(db, ws) == Decimal("0")


def test_received_by_type_groups_and_defaults_missing_to_zero(db):
    ws = _mk_workspace(db, "by-type-ws")
    fi = _mk_fi(db)
    acc = _mk_account(db, ws, fi.id)
    asset = _mk_asset(db, ws, acc.id, "PETR4")

    _mk_distribution(
        db, ws, fi.id, asset.id, DistributionType.DIVIDEND,
        Decimal("100"), date(2026, 1, 10),
    )
    _mk_distribution(
        db, ws, fi.id, asset.id, DistributionType.DIVIDEND,
        Decimal("50"), date(2026, 2, 10),
    )
    _mk_distribution(
        db, ws, fi.id, asset.id, DistributionType.JCP,
        Decimal("30"), date(2026, 3, 10),
    )
    _mk_distribution(
        db, ws, fi.id, asset.id, DistributionType.SECURITIES_LENDING,
        Decimal("7"), date(2026, 4, 10),
    )

    by_type = _received_by_type(db, ws)
    # Chaves cobrem todos os DistributionType (invariante do contrato).
    assert set(by_type.keys()) == {t.value for t in DistributionType}
    assert by_type["DIVIDEND"] == Decimal("150")
    assert by_type["JCP"] == Decimal("30")
    assert by_type["SECURITIES_LENDING"] == Decimal("7")
    # INTEREST não teve rows → zero, mas chave presente.
    assert by_type["INTEREST"] == Decimal("0")


def test_received_by_type_all_types_zero_when_no_rows(db):
    ws = _mk_workspace(db, "empty-by-type-ws")
    by_type = _received_by_type(db, ws)
    assert set(by_type.keys()) == {t.value for t in DistributionType}
    assert all(v == Decimal("0") for v in by_type.values())


# ── top_holdings ranking ────────────────────────────────────────────────────


def test_top_holdings_sorted_desc_with_pct(db):
    """5+ assets em posições variadas → ordenados DESC por market_value_brl,
    pct = value / total. Limit 10 (5 aqui, todos aparecem)."""
    ws = _mk_workspace(db, "top-ws")
    fi = _mk_fi(db)
    acc = _mk_account(db, ws, fi.id)

    tickers_values = [
        ("A", Decimal("1000")),
        ("B", Decimal("500")),
        ("C", Decimal("2000")),   # maior
        ("D", Decimal("300")),
        ("E", Decimal("100")),
    ]
    assets = {t: _mk_asset(db, ws, acc.id, t) for t, _ in tickers_values}
    snap = _mk_snapshot(db, ws, date(2026, 4, 30), sum(v for _, v in tickers_values))
    snap.total_value_brl = sum(v for _, v in tickers_values)
    for t, v in tickers_values:
        _mk_item(db, snap.id, assets[t].id, v)
    db.flush()

    summary = compute_portfolio_summary(db, ws)
    tickers_in_order = [h.ticker for h in summary.top_holdings]
    assert tickers_in_order == ["C", "A", "B", "D", "E"]

    total = Decimal("3900")
    # pct exato pra top holding.
    top = summary.top_holdings[0]
    assert top.value_brl == Decimal("2000")
    assert top.pct == pytest.approx(float(Decimal("2000") / total))

    # Soma dos pcts == 1 (dentro do erro float).
    assert sum(h.pct for h in summary.top_holdings) == pytest.approx(1.0)


def test_top_holdings_limited_to_10(db):
    """Cria 12 assets → summary devolve só os 10 maiores."""
    ws = _mk_workspace(db, "top10-ws")
    fi = _mk_fi(db)
    acc = _mk_account(db, ws, fi.id)

    values = [Decimal(str(v)) for v in (
        1200, 1100, 1000, 900, 800, 700, 600, 500, 400, 300, 200, 100,
    )]
    assets = [
        _mk_asset(db, ws, acc.id, f"T{i:02d}")
        for i in range(len(values))
    ]
    snap = _mk_snapshot(db, ws, date(2026, 5, 31), sum(values))
    snap.total_value_brl = sum(values)
    for a, v in zip(assets, values):
        _mk_item(db, snap.id, a.id, v)
    db.flush()

    summary = compute_portfolio_summary(db, ws)
    assert len(summary.top_holdings) == 10
    # Ordem DESC preservada; o menor incluído deve ser 300 (10º maior).
    assert summary.top_holdings[0].value_brl == Decimal("1200")
    assert summary.top_holdings[-1].value_brl == Decimal("300")
    # Assets com valores 200 e 100 foram cortados.
    included_values = {h.value_brl for h in summary.top_holdings}
    assert Decimal("200") not in included_values
    assert Decimal("100") not in included_values
