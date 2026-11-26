"""Spec 85 — ARCA: regra derivada, override, metas, resumo e simulador."""
from __future__ import annotations

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
from numis_geek.models.arca import ARCA_PARENT, ARCA_ROLE, ArcaCategory, ArcaSubcategory
from numis_geek.models.asset import Asset, AssetClass, FixedIncomeAsset, FixedIncomeIndexer
from numis_geek.models.asset_fundamentals import AssetFundamentals, FundamentalsSource
from numis_geek.models.distribution import Distribution, DistributionType
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.portfolio_snapshot import (
    PortfolioSnapshot,
    PortfolioSnapshotItem,
    SnapshotSource,
)
from numis_geek.models.target_allocation import TargetAllocationDimension as Dim
from numis_geek.services.arca import (
    ArcaClassificationError,
    ArcaPlanError,
    _water_fill,
    arca_summary,
    contribution_plan,
    derive_arca,
    income_by_asset_12m,
    resolve_arca,
    set_classification,
)
from numis_geek.services.target_allocation import (
    TargetAllocationError,
    TargetEntryIn,
    get_targets,
    upsert_targets,
    validate_entries,
)
from numis_geek.services.workspace import WorkspaceService

ENGINE = create_engine(
    "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
)
Session = sessionmaker(bind=ENGINE, autoflush=False, autocommit=False)
NOW = datetime.now(timezone.utc)
D = Decimal


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    Base.metadata.create_all(ENGINE)
    yield
    Base.metadata.drop_all(ENGINE)


@pytest.fixture
def db():
    s = Session()
    yield s
    s.rollback()
    s.close()


@pytest.fixture
def ws(db):
    w = WorkspaceService(db).create(f"ARCA {uuid.uuid4().hex[:6]}")
    db.flush()
    fi = FinancialInstitution(
        id=str(uuid.uuid4()), long_name="XP", short_name="XP", country="BR",
        is_active=True, created_at=NOW, updated_at=NOW,
    )
    db.add(fi)
    db.flush()
    acc = Account(
        id=str(uuid.uuid4()), workspace_id=w.id, financial_institution_id=fi.id,
        name="Inv", account_type=AccountType.investment, currency=Currency.BRL,
        opening_balance=D("0"), is_active=True, created_at=NOW, updated_at=NOW,
    )
    db.add(acc)
    db.flush()
    return {"id": w.id, "acc": acc.id, "fi": fi.id}


def mk(db, ws, ticker, cls=AssetClass.STOCK, country="BR", currency=Currency.BRL,
       indexer=None, active=True):
    a = Asset(
        id=str(uuid.uuid4()), workspace_id=ws["id"], account_id=ws["acc"],
        asset_class=cls, country=country, name=ticker, ticker=ticker,
        currency=currency, is_active=active, created_at=NOW, updated_at=NOW,
    )
    db.add(a)
    db.flush()
    if indexer is not None:
        db.add(FixedIncomeAsset(
            asset_id=a.id, issuer="Tesouro", maturity_date=date(2030, 1, 1),
            indexer=indexer, rate=D("10"),
        ))
        db.flush()
        db.refresh(a)
    return a


def snap(db, ws, items: dict[str, Decimal], period=date(2026, 10, 31)):
    s = PortfolioSnapshot(
        id=str(uuid.uuid4()), workspace_id=ws["id"], period_end_date=period,
        fx_rate_usd_brl=D("5"), total_value_brl=sum(items.values(), D(0)),
        total_value_usd=D("0"), total_invested_brl=D("0"), total_received_brl=D("0"),
        source=SnapshotSource.MANUAL, is_active=True, created_at=NOW, updated_at=NOW,
    )
    db.add(s)
    db.flush()
    for aid, v in items.items():
        db.add(PortfolioSnapshotItem(
            id=str(uuid.uuid4()), snapshot_id=s.id, asset_id=aid, quantity=D("1"),
            unit_price=v, market_value_native=v, market_value_brl=v, market_value_usd=v / 5,
        ))
    db.flush()
    return s


def dist(db, ws, asset_id, net, when, currency=Currency.BRL, fx=D("1")):
    db.add(Distribution(
        id=str(uuid.uuid4()), workspace_id=ws["id"], financial_institution_id=ws["fi"],
        asset_id=asset_id, type=DistributionType.DIVIDEND, event_date=when,
        gross_amount=net, tax=D("0"), net_amount=net, currency=currency, fx_rate=fx,
        is_active=True, created_at=NOW, updated_at=NOW,
    ))
    db.flush()


def set_arca_targets(db, ws, letters, subs=None):
    upsert_targets(
        db, ws["id"], Dim.ARCA,
        [TargetEntryIn(k, D(v)) for k, v in letters.items()],
        user_email="t", user_id=None,
    )
    if subs:
        upsert_targets(
            db, ws["id"], Dim.ARCA_SUB,
            [TargetEntryIn(k, D(v)) for k, v in subs.items()],
            user_email="t", user_id=None,
        )


EQUAL = {"EQUITY_BR": "0.25", "REAL_ESTATE": "0.25", "CASH": "0.25", "GLOBAL": "0.25"}


# ── Enums ──


def test_every_sub_has_parent_and_role():
    for s in ArcaSubcategory:
        assert s in ARCA_PARENT and s in ARCA_ROLE
    assert ARCA_PARENT[ArcaSubcategory.CASH_PRE_FIXED] == ArcaCategory.CASH
    assert ARCA_PARENT[ArcaSubcategory.RE_FOF] == ArcaCategory.REAL_ESTATE


# ── Regra derivada ──


@pytest.mark.parametrize("kw,cat,sub", [
    (dict(ticker="ITUB4"), "EQUITY_BR", "EQ_DEFENSIVE"),
    (dict(ticker="VALE3"), "EQUITY_BR", "EQ_DOLLAR"),
    (dict(ticker="ZZZZ3"), "EQUITY_BR", "EQ_ACCELERATOR"),
    (dict(ticker="AAPL34"), "GLOBAL", "GL_EQUITY"),  # BDR
    (dict(ticker="AAPL", country="US", currency=Currency.USD), "GLOBAL", "GL_EQUITY"),
    (dict(ticker="HGLG11", cls=AssetClass.REIT), "REAL_ESTATE", "RE_BRICK"),
    (dict(ticker="KNCR11", cls=AssetClass.REIT), "REAL_ESTATE", "RE_PAPER_CDI"),
    (dict(ticker="KNIP11", cls=AssetClass.REIT), "REAL_ESTATE", "RE_PAPER_IPCA"),
    (dict(ticker="BCFF11", cls=AssetClass.REIT), "REAL_ESTATE", "RE_FOF"),
    (dict(ticker="O", cls=AssetClass.REIT, country="US", currency=Currency.USD), "GLOBAL", "GL_REIT"),
    (dict(ticker="TSELIC", cls=AssetClass.FIXED_INCOME, indexer=FixedIncomeIndexer.SELIC), "CASH", "CASH_POST_FIXED"),
    (dict(ticker="CDB", cls=AssetClass.FIXED_INCOME, indexer=FixedIncomeIndexer.CDI), "CASH", "CASH_POST_FIXED"),
    (dict(ticker="PRE", cls=AssetClass.FIXED_INCOME, indexer=FixedIncomeIndexer.PREFIXED), "CASH", "CASH_PRE_FIXED"),
    (dict(ticker="IPCA", cls=AssetClass.FIXED_INCOME, indexer=FixedIncomeIndexer.IPCA), "CASH", "CASH_INFLATION"),
    (dict(ticker="TBILL", cls=AssetClass.FIXED_INCOME, indexer=FixedIncomeIndexer.USD), "GLOBAL", "GL_FIXED_INCOME"),
    (dict(ticker="RFX", cls=AssetClass.FIXED_INCOME), "CASH", None),  # legado sem details
    (dict(ticker="BTC", cls=AssetClass.CRYPTO, country="US"), "GLOBAL", "GL_CRYPTO"),
    (dict(ticker="CC", cls=AssetClass.CASH), "CASH", "CASH_POST_FIXED"),
    (dict(ticker="WISE", cls=AssetClass.CASH, currency=Currency.USD), "GLOBAL", "GL_FIXED_INCOME"),
    (dict(ticker="VOO", cls=AssetClass.ETF, country="US", currency=Currency.USD), "GLOBAL", "GL_EQUITY"),
    (dict(ticker="BOVA11", cls=AssetClass.ETF), None, None),
    (dict(ticker="FUNDO", cls=AssetClass.FUND), None, None),
    (dict(ticker="PGBL", cls=AssetClass.PRIVATE_PENSION), None, None),
    (dict(ticker="CASA", cls=AssetClass.REAL_ESTATE), "OUT_OF_SCOPE", None),
    (dict(ticker="CARRO", cls=AssetClass.VEHICLE), "OUT_OF_SCOPE", None),
    (dict(ticker="FGTS", cls=AssetClass.FGTS), "OUT_OF_SCOPE", None),
])
def test_derive(db, ws, kw, cat, sub):
    a = mk(db, ws, **kw)
    c, s = derive_arca(a)
    assert (c.value if c else None) == cat
    assert (s.value if s else None) == sub


def test_resolve_sources(db, ws):
    a = mk(db, ws, "BOVA11", cls=AssetClass.ETF)
    assert resolve_arca(a).source == "unmapped"
    b = mk(db, ws, "ITUB4")
    r = resolve_arca(b)
    assert (r.category, r.subcategory, r.source) == (
        ArcaCategory.EQUITY_BR, ArcaSubcategory.EQ_DEFENSIVE, "derived")
    assert r.note == "lista de tickers"


def test_override_wins_and_infers_parent(db, ws):
    a = mk(db, ws, "IVVB11", cls=AssetClass.ETF)
    set_classification(db, a, None, "GL_EQUITY", user_email="t", user_id=None)
    r = resolve_arca(a)
    assert (r.category, r.subcategory, r.source) == (
        ArcaCategory.GLOBAL, ArcaSubcategory.GL_EQUITY, "manual")
    # category-only override keeps derived sub when letter matches
    t = mk(db, ws, "PRE", cls=AssetClass.FIXED_INCOME, indexer=FixedIncomeIndexer.PREFIXED)
    set_classification(db, t, "CASH", None, user_email="t", user_id=None)
    assert resolve_arca(t).subcategory == ArcaSubcategory.CASH_PRE_FIXED
    # different letter drops the derived sub
    set_classification(db, t, "GLOBAL", None, user_email="t", user_id=None)
    assert resolve_arca(t).subcategory is None
    # clearing goes back to derived
    set_classification(db, t, None, None, user_email="t", user_id=None)
    assert resolve_arca(t).source == "derived"


def test_override_incompatible_sub_rejected(db, ws):
    a = mk(db, ws, "ITUB4")
    with pytest.raises(ArcaClassificationError):
        set_classification(db, a, "CASH", "EQ_DEFENSIVE", user_email="t", user_id=None)
    with pytest.raises(ArcaClassificationError):
        set_classification(db, a, "OUT_OF_SCOPE", "EQ_DEFENSIVE", user_email="t", user_id=None)


# ── Subcategoria automática (ações e FIIs) ──


def test_stock_sub_from_fundamentals_sector(db, ws):
    a = mk(db, ws, "ABCD3")
    assert derive_arca(a)[1] == ArcaSubcategory.EQ_ACCELERATOR
    db.add(AssetFundamentals(
        id=str(uuid.uuid4()), workspace_id=ws["id"], asset_id=a.id,
        snapshot_date=date(2026, 11, 1), source=list(FundamentalsSource)[0],
        raw_payload='{"summaryProfile": {"sector": "Utilities", "industry": "Utilities—Regulated Water"}}',
    ))
    snap(db, ws, {a.id: D("100")})
    row = next(r for r in arca_summary(db, ws["id"]).assets if r.asset_id == a.id)
    assert row.subcategory == "EQ_DEFENSIVE"
    assert row.derived_note.startswith("setor: Utilities")


@pytest.mark.parametrize("name,sub", [
    ("FII Recebíveis Imobiliários CDI", "RE_PAPER_CDI"),
    ("Fundo de Recebíveis High Yield", "RE_PAPER_IPCA"),
    ("XYZ Fundo de Fundos", "RE_FOF"),
    ("ABC Logística Renda", "RE_BRICK"),
    ("Qualquer FII", "RE_BRICK"),
])
def test_fii_sub_from_name(db, ws, name, sub):
    a = mk(db, ws, "QWER11", cls=AssetClass.REIT)
    a.name = name
    assert derive_arca(a)[1].value == sub


def test_sector_hint_parsing():
    from numis_geek.services.arca_rules import sector_hint_from_payload
    assert sector_hint_from_payload('{"sector": "Energy", "industry": "Oil"}') == "Energy | Oil"
    assert sector_hint_from_payload("not json") is None
    assert sector_hint_from_payload(None) is None
    assert sector_hint_from_payload("{}") is None


# ── Metas ──


def test_arca_targets_sum_and_band():
    ok = [TargetEntryIn(k, D(v)) for k, v in EQUAL.items()]
    assert validate_entries(ok, Dim.ARCA) == []
    bad_sum = [TargetEntryIn("CASH", D("0.30"))] + [e for e in ok if e.key != "CASH"]
    assert any("sum" in e for e in validate_entries(bad_sum, Dim.ARCA))
    out_band = [TargetEntryIn("CASH", D("0.45")), TargetEntryIn("GLOBAL", D("0.15")),
                TargetEntryIn("EQUITY_BR", D("0.20")), TargetEntryIn("REAL_ESTATE", D("0.20"))]
    assert any("band" in e for e in validate_entries(out_band, Dim.ARCA))
    widened = [TargetEntryIn("CASH", D("0.45"), D("0.10"), D("0.50"))] + out_band[1:]
    assert validate_entries(widened, Dim.ARCA) == []
    assert validate_entries([TargetEntryIn("OUT_OF_SCOPE", D("1"))], Dim.ARCA)
    inv = [TargetEntryIn("CASH", D("0.25"), D("0.30"), D("0.20"))] + ok[1:]
    assert any("band" in e for e in validate_entries(inv, Dim.ARCA))


def test_arca_sub_sums_per_letter():
    ok = [
        TargetEntryIn("CASH_POST_FIXED", D("0.3333")),
        TargetEntryIn("CASH_PRE_FIXED", D("0.3333")),
        TargetEntryIn("CASH_INFLATION", D("0.3334")),
        TargetEntryIn("EQ_DEFENSIVE", D("1")),
    ]
    assert validate_entries(ok, Dim.ARCA_SUB) == []
    bad = ok[:2] + ok[3:]
    errs = validate_entries(bad, Dim.ARCA_SUB)
    assert any("CASH" in e for e in errs)
    assert validate_entries([TargetEntryIn("NOPE", D("1"))], Dim.ARCA_SUB)
    assert validate_entries(
        [TargetEntryIn("EQ_DEFENSIVE", D("1"), D("0.1"), None)], Dim.ARCA_SUB
    )


def test_targets_roundtrip_and_isolation(db, ws):
    upsert_targets(db, ws["id"], Dim.CLASS, [TargetEntryIn("STOCK", D("1"))],
                   user_email="t", user_id=None)
    set_arca_targets(db, ws, EQUAL, {"CASH_POST_FIXED": "1"})
    t = get_targets(db, ws["id"])
    assert t["CLASS"].is_valid and t["ARCA"].is_valid and t["ARCA_SUB"].is_valid
    assert len(t["ARCA"].entries) == 4 and t["COUNTRY"].entries == []
    with pytest.raises(TargetAllocationError):
        upsert_targets(db, ws["id"], Dim.ARCA, [TargetEntryIn("CASH", D("1"))],
                       user_email="t", user_id=None)  # fora da banda default


# ── Resumo ──


def _portfolio(db, ws):
    itub = mk(db, ws, "ITUB4")
    hglg = mk(db, ws, "HGLG11", cls=AssetClass.REIT)
    selic = mk(db, ws, "TSELIC", cls=AssetClass.FIXED_INCOME, indexer=FixedIncomeIndexer.SELIC)
    btc = mk(db, ws, "BTC", cls=AssetClass.CRYPTO, country="US")
    casa = mk(db, ws, "CASA", cls=AssetClass.REAL_ESTATE)
    fundo = mk(db, ws, "FUNDO", cls=AssetClass.FUND)
    snap(db, ws, {
        itub.id: D("40000"), hglg.id: D("20000"), selic.id: D("30000"), btc.id: D("10000"),
        casa.id: D("500000"), fundo.id: D("5000"),
    })
    return dict(itub=itub, hglg=hglg, selic=selic, btc=btc, casa=casa, fundo=fundo)


def test_summary_percentages_exclude_out_of_scope_and_unmapped(db, ws):
    a = _portfolio(db, ws)
    set_arca_targets(db, ws, EQUAL)
    s = arca_summary(db, ws["id"])
    assert s.total_brl == D("100000")
    assert s.out_of_scope_brl == D("500000")
    assert s.unmapped_brl == D("5000") and s.unmapped_count == 1
    by = {l.key: l for l in s.letters}
    assert by["EQUITY_BR"].current_pct == pytest.approx(0.40)
    assert by["EQUITY_BR"].status == "IN_BAND"
    assert by["GLOBAL"].current_pct == pytest.approx(0.10) and by["GLOBAL"].status == "IN_BAND"
    assert by["CASH"].gap_brl == D("-5000.00")
    assert by["EQUITY_BR"].unclassified_sub_value_brl == D("0")
    # ataque × defesa: BTC + HGLG11 (tijolo) ataque; Selic + ITUB4 defesa
    assert s.attack_pct == pytest.approx(0.30)
    assert s.defense_pct == pytest.approx(0.70)
    assert s.unknown_role_pct == pytest.approx(0.0)
    assert {r.asset_id for r in s.assets} >= {a["itub"].id, a["fundo"].id}


def test_summary_band_status(db, ws):
    itub = mk(db, ws, "ITUB4")
    selic = mk(db, ws, "TSELIC", cls=AssetClass.FIXED_INCOME, indexer=FixedIncomeIndexer.SELIC)
    snap(db, ws, {itub.id: D("45"), selic.id: D("55")})
    set_arca_targets(db, ws, EQUAL)
    by = {l.key: l for l in arca_summary(db, ws["id"]).letters}
    assert by["EQUITY_BR"].status == "ABOVE_BAND"
    assert by["REAL_ESTATE"].status == "BELOW_BAND"


def test_summary_no_targets(db, ws):
    _portfolio(db, ws)
    s = arca_summary(db, ws["id"])
    assert not s.targets_configured
    assert all(l.status == "NO_TARGET" and l.gap_brl is None for l in s.letters)


def test_income_12m_window_and_usd(db, ws):
    a = _portfolio(db, ws)
    dist(db, ws, a["hglg"].id, D("100"), date(2026, 10, 15))
    dist(db, ws, a["hglg"].id, D("100"), date(2025, 11, 1))  # dentro (> 31/10/2025)
    dist(db, ws, a["hglg"].id, D("999"), date(2025, 10, 31))  # fora
    dist(db, ws, a["itub"].id, D("10"), date(2026, 5, 1), currency=Currency.USD, fx=D("5"))
    inc = income_by_asset_12m(db, ws["id"], date(2026, 10, 31))
    assert inc[a["hglg"].id] == D("200")
    assert inc[a["itub"].id] == D("50")
    s = arca_summary(db, ws["id"])
    by = {l.key: l for l in s.letters}
    assert by["REAL_ESTATE"].income_12m_brl == D("200")
    assert by["REAL_ESTATE"].yield_12m == pytest.approx(0.01)
    assert s.income_12m_total_brl == D("250")
    assert by["REAL_ESTATE"].income_share == pytest.approx(0.8)


def test_income_forward_from_fundamentals(db, ws):
    a = _portfolio(db, ws)
    db.add(AssetFundamentals(
        id=str(uuid.uuid4()), workspace_id=ws["id"], asset_id=a["itub"].id,
        snapshot_date=date(2026, 11, 1), source=list(FundamentalsSource)[0],
        dividend_yield_12m=D("0.08"),
    ))
    db.flush()
    by = {l.key: l for l in arca_summary(db, ws["id"]).letters}
    assert by["EQUITY_BR"].income_forward_brl == D("3200.00")


def test_summary_subcategories_with_targets(db, ws):
    a = _portfolio(db, ws)
    set_arca_targets(db, ws, EQUAL, {
        "CASH_POST_FIXED": "0.5", "CASH_PRE_FIXED": "0.25", "CASH_INFLATION": "0.25",
    })
    cash = {l.key: l for l in arca_summary(db, ws["id"]).letters}["CASH"]
    subs = {s.key: s for s in cash.subcategories}
    assert subs["CASH_POST_FIXED"].value_brl == D("30000")
    assert subs["CASH_POST_FIXED"].target_pct_of_total == D("0.1250")
    assert subs["CASH_PRE_FIXED"].gap_brl == D("6250.00")
    assert subs["CASH_POST_FIXED"].role == "DEFENSE"


# ── Simulador ──


def test_water_fill():
    out = _water_fill({"a": D("100"), "b": D("40"), "c": D("-10")}, D("80"))
    assert out["a"] == D("70") and out["b"] == D("10") and out["c"] == 0
    out = _water_fill({"a": D("10"), "b": D("5")}, D("100"))
    assert out == {"a": D("10"), "b": D("5")}


def test_plan_goes_to_most_behind_and_never_sells_in_band(db, ws):
    _portfolio(db, ws)  # A 40k · R 20k · C 30k · G 10k
    set_arca_targets(db, ws, EQUAL)
    p = contribution_plan(db, ws["id"], D("10000"))
    by = {l.key: l for l in p.letters}
    # total após = 110k → alvo 27.5k por letra; déficits G 17.5k, R 7.5k
    assert by["GLOBAL"].amount_brl == D("10000.00")
    assert by["REAL_ESTATE"].amount_brl == D("0.00")
    assert sum(l.amount_brl for l in p.letters) == D("10000.00")
    assert all(l.sell_suggestion_brl == 0 for l in p.letters)


def test_plan_covers_all_deficits_then_splits_by_target(db, ws):
    _portfolio(db, ws)
    set_arca_targets(db, ws, EQUAL)
    p = contribution_plan(db, ws["id"], D("100000"))  # total 200k → 50k cada
    by = {l.key: l for l in p.letters}
    assert by["EQUITY_BR"].amount_brl == D("10000.00")
    assert by["GLOBAL"].amount_brl == D("40000.00")
    assert sum(l.amount_brl for l in p.letters) == D("100000.00")


def test_plan_sell_suggestion_above_band(db, ws):
    itub = mk(db, ws, "ITUB4")
    selic = mk(db, ws, "TSELIC", cls=AssetClass.FIXED_INCOME, indexer=FixedIncomeIndexer.SELIC)
    snap(db, ws, {itub.id: D("90000"), selic.id: D("10000")})
    set_arca_targets(db, ws, EQUAL)
    p = contribution_plan(db, ws["id"], D("1000"))
    eq = {l.key: l for l in p.letters}["EQUITY_BR"]
    assert eq.amount_brl == 0
    assert eq.sell_suggestion_brl == (D("90000") - D("0.40") * D("101000")).quantize(D("0.01"))


def test_plan_splits_inside_letter(db, ws):
    _portfolio(db, ws)  # Caixa só pós-fixado 30k
    set_arca_targets(db, ws, {"EQUITY_BR": "0.15", "REAL_ESTATE": "0.15", "CASH": "0.40",
                              "GLOBAL": "0.30"},
                     {"CASH_POST_FIXED": "0.3333", "CASH_PRE_FIXED": "0.3333",
                      "CASH_INFLATION": "0.3334"})
    p = contribution_plan(db, ws["id"], D("20000"))
    cash = {l.key: l for l in p.letters}["CASH"]
    keys = {s.key for s in cash.subcategories}
    assert "CASH_POST_FIXED" not in keys
    assert keys <= {"CASH_PRE_FIXED", "CASH_INFLATION"}
    assert sum(s.amount_brl for s in cash.subcategories) == cash.amount_brl


def test_plan_requires_targets_and_positive_amount(db, ws):
    _portfolio(db, ws)
    with pytest.raises(ArcaPlanError):
        contribution_plan(db, ws["id"], D("1000"))
    set_arca_targets(db, ws, EQUAL)
    with pytest.raises(ArcaPlanError):
        contribution_plan(db, ws["id"], D("0"))
