"""Cobertura do services/historical_price.py — fonte hierárquica + walkback."""
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
from numis_geek.models.asset import Asset, AssetClass, PriceSource
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.integration_credential import (
    CredentialTestResult, IntegrationCredential, IntegrationProvider,
)
from numis_geek.models.portfolio_snapshot import (
    PortfolioSnapshot, PortfolioSnapshotItem, SnapshotStatus,
)
from numis_geek.models.ptax_rate import PTAXRate
from numis_geek.models.workspace import Workspace
from numis_geek.models.audit_log import AuditLog
from numis_geek.services import historical_price as hp_module
from numis_geek.services.historical_price import (
    HistoricalPriceNotFound, fetch_on, fetch_price_on,
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


def _world(db) -> dict:
    now = datetime.now(timezone.utc)
    ws = Workspace(id=str(uuid.uuid4()), name=f"WS-{uuid.uuid4().hex[:6]}")
    fi = FinancialInstitution(
        id=str(uuid.uuid4()), long_name="XP", short_name="XP", logo_slug="xp",
        is_active=True, created_at=now, updated_at=now,
    )
    acc = Account(
        id=str(uuid.uuid4()), workspace_id=ws.id, financial_institution_id=fi.id,
        name="acc", account_type=AccountType.investment, currency=Currency.BRL,
        is_active=True, created_at=now, updated_at=now,
    )
    db.add_all([ws, fi, acc])
    db.flush()
    return {"ws": ws, "fi": fi, "acc": acc, "now": now}


def _brapi_asset(db, w, *, ticker="ITUB4", current_price=None, updated_at=None):
    a = Asset(
        id=str(uuid.uuid4()), workspace_id=w["ws"].id, account_id=w["acc"].id,
        asset_class=AssetClass.STOCK, country="BR",
        name=ticker, ticker=ticker, currency=Currency.BRL,
        price_source=PriceSource.BRAPI,
        current_price=current_price,
        price_updated_at=updated_at,
        is_active=True, created_at=w["now"], updated_at=w["now"],
    )
    db.add(a)
    db.flush()
    return a


def _seed_brapi_token(db):
    now = datetime.now(timezone.utc)
    cred = IntegrationCredential(
        id=str(uuid.uuid4()),
        provider=IntegrationProvider.BRAPI,
        key_name="default", secret_value="testtok",
        is_active=True,
        last_tested_at=None, last_test_result=CredentialTestResult.UNTESTED,
        last_test_message=None,
        created_at=now, updated_at=now,
    )
    db.add(cred)
    db.flush()


def test_current_price_wins_when_updated_today(db):
    w = _world(db)
    # price_updated_at = mesmo dia da target_date
    asset = _brapi_asset(
        db, w, current_price=Decimal("42.00"),
        updated_at=datetime(2026, 6, 19, 18, 0, tzinfo=timezone.utc),
    )
    hp = fetch_price_on(db, asset, date(2026, 6, 19))
    assert hp.source == "current_price"
    assert hp.price == Decimal("42.00")
    assert hp.effective_date == date(2026, 6, 19)


def test_brapi_history_walkback_skips_weekend(db, monkeypatch):
    """Vencimento numa segunda. BRAPI só tem fechamento na sexta anterior."""
    from numis_geek.integrations.brapi import BrapiHistoryPoint
    w = _world(db)
    _seed_brapi_token(db)
    asset = _brapi_asset(db, w)
    points = [
        BrapiHistoryPoint(date=date(2026, 6, 12), close=Decimal("39.00")),  # sex
        BrapiHistoryPoint(date=date(2026, 6, 18), close=Decimal("41.00")),  # qui
        BrapiHistoryPoint(date=date(2026, 6, 19), close=Decimal("39.87")),  # sex
    ]
    monkeypatch.setattr(hp_module, "brapi_history", lambda *a, **kw: points)
    # Target em uma segunda (22/06) — BRAPI não tem; walkback pega sex 19/06.
    hp = fetch_price_on(db, asset, date(2026, 6, 22))
    assert hp.source == "brapi"
    assert hp.price == Decimal("39.87")
    assert hp.effective_date == date(2026, 6, 19)


def test_brapi_history_returns_exact_date_when_available(db, monkeypatch):
    from numis_geek.integrations.brapi import BrapiHistoryPoint
    w = _world(db)
    _seed_brapi_token(db)
    asset = _brapi_asset(db, w)
    points = [BrapiHistoryPoint(date=date(2026, 6, 19), close=Decimal("39.87"))]
    monkeypatch.setattr(hp_module, "brapi_history", lambda *a, **kw: points)
    hp = fetch_price_on(db, asset, date(2026, 6, 19))
    assert hp.source == "brapi"
    assert hp.price == Decimal("39.87")
    assert hp.effective_date == date(2026, 6, 19)


def test_snapshot_fallback_when_brapi_unavailable(db, monkeypatch):
    """Sem BRAPI mas com PortfolioSnapshotItem no dia exato."""
    w = _world(db)
    asset = _brapi_asset(db, w)
    # snapshot fechado em 19/06 com unit_price 39.87 pra esse asset
    snap = PortfolioSnapshot(
        id=str(uuid.uuid4()),
        workspace_id=w["ws"].id,
        period_end_date=date(2026, 6, 19),
        status=SnapshotStatus.CLOSED,
        total_invested_brl=Decimal("0"),
        total_received_brl=Decimal("0"),
        total_value_brl=Decimal("0"),
        created_at=w["now"], updated_at=w["now"],
    )
    item = PortfolioSnapshotItem(
        id=str(uuid.uuid4()),
        snapshot_id=snap.id, asset_id=asset.id,
        quantity=Decimal("100"),
        unit_price=Decimal("39.87"),
        market_value_brl=Decimal("3987"),
        average_cost_brl=Decimal("35"),
        total_invested_brl=Decimal("3500"),
        created_at=w["now"], updated_at=w["now"],
    )
    db.add_all([snap, item])
    db.flush()
    # Sem token BRAPI nesse worker → _try_brapi devolve None
    hp = fetch_price_on(db, asset, date(2026, 6, 19))
    assert hp.source == "snapshot"
    assert hp.price == Decimal("39.87")
    assert hp.effective_date == date(2026, 6, 19)


def test_raises_when_no_source_resolves(db):
    """current_price stale + sem BRAPI + sem snapshot → raise."""
    w = _world(db)
    asset = _brapi_asset(db, w)  # sem current_price, sem token, sem snapshot
    with pytest.raises(HistoricalPriceNotFound):
        fetch_price_on(db, asset, date(2026, 6, 19))


def test_current_price_skipped_when_updated_on_different_day(db):
    """price_updated_at != target_date → ignora current_price (evita decisão errada)."""
    w = _world(db)
    asset = _brapi_asset(
        db, w, current_price=Decimal("45.00"),
        updated_at=datetime(2026, 6, 22, 18, 0, tzinfo=timezone.utc),
    )
    with pytest.raises(HistoricalPriceNotFound):
        fetch_price_on(db, asset, date(2026, 6, 19))


# ─────────────────────────────────────────────────────────────────────────────
# Spec 53 wire-in: fetch_on() — chain por price_source + walkback 3 dias úteis
# ─────────────────────────────────────────────────────────────────────────────

def _seed_finnhub_token(db):
    now = datetime.now(timezone.utc)
    cred = IntegrationCredential(
        id=str(uuid.uuid4()),
        provider=IntegrationProvider.FINNHUB,
        key_name="default", secret_value="fh-tok",
        is_active=True,
        last_tested_at=None, last_test_result=CredentialTestResult.UNTESTED,
        last_test_message=None,
        created_at=now, updated_at=now,
    )
    db.add(cred)
    db.flush()


def _finnhub_asset(db, w, *, ticker="AAPL"):
    a = Asset(
        id=str(uuid.uuid4()), workspace_id=w["ws"].id, account_id=w["acc"].id,
        asset_class=AssetClass.STOCK, country="US",
        name=ticker, ticker=ticker, currency=Currency.USD,
        price_source=PriceSource.FINNHUB,
        is_active=True, created_at=w["now"], updated_at=w["now"],
    )
    db.add(a)
    db.flush()
    return a


def _coinbase_asset(db, w, *, ticker="BTC"):
    a = Asset(
        id=str(uuid.uuid4()), workspace_id=w["ws"].id, account_id=w["acc"].id,
        asset_class=AssetClass.CRYPTO, country="US",
        name=ticker, ticker=ticker, currency=Currency.USD,
        price_source=PriceSource.COINBASE,
        is_active=True, created_at=w["now"], updated_at=w["now"],
    )
    db.add(a)
    db.flush()
    return a


def _tesouro_asset(db, w, *, ticker="TESOURO", name="Tesouro IPCA+ 2035"):
    a = Asset(
        id=str(uuid.uuid4()), workspace_id=w["ws"].id, account_id=w["acc"].id,
        asset_class=AssetClass.FIXED_INCOME, country="BR",
        name=name, ticker=ticker, currency=Currency.BRL,
        price_source=PriceSource.TESOURO,
        is_active=True, created_at=w["now"], updated_at=w["now"],
    )
    db.add(a)
    db.flush()
    return a


def _manual_asset(db, w):
    a = Asset(
        id=str(uuid.uuid4()), workspace_id=w["ws"].id, account_id=w["acc"].id,
        asset_class=AssetClass.REAL_ESTATE, country="BR",
        name="Apto Rio", ticker=None, currency=Currency.BRL,
        price_source=PriceSource.MANUAL,
        is_active=True, created_at=w["now"], updated_at=w["now"],
    )
    db.add(a)
    db.flush()
    return a


def test_fetch_on_brapi_hit_exact_date(db, monkeypatch):
    """BRAPI retorna preço no target — sem walkback, sem fallback pra yfinance."""
    w = _world(db)
    _seed_brapi_token(db)
    asset = _brapi_asset(db, w)
    calls: list[tuple] = []

    def _brapi(ticker, token, target):
        calls.append(("brapi", ticker, target))
        return Decimal("41.23") if target == date(2026, 6, 19) else None

    def _yf(symbol, target):
        calls.append(("yfinance", symbol, target))
        raise AssertionError("yfinance should not be reached when brapi hits")

    monkeypatch.setattr(hp_module, "brapi_close_on", _brapi)
    monkeypatch.setattr(hp_module, "yfinance_close_on", _yf)

    price = fetch_on(db, asset, date(2026, 6, 19))
    assert price == Decimal("41.23")
    assert calls == [("brapi", "ITUB4", date(2026, 6, 19))]


def test_fetch_on_brapi_walkback_3_business_days_skips_feriado(db, monkeypatch):
    """Target = segunda pós-feriadão (Good Friday). Walkback pula 3 dias
    não-úteis e volta pra quinta anterior, que é onde BRAPI tem preço.

    2026-04-03 = Good Friday (feriado), 04-04 sáb, 04-05 dom.
    Target 2026-04-06 (seg). BRAPI só tem preço na quinta 2026-04-02.
    Candidatos esperados: [04-06, 04-02, 04-01, 03-31].
    """
    from numis_geek.utils.business_day import is_business_day
    assert not is_business_day(date(2026, 4, 3))   # Good Friday
    assert is_business_day(date(2026, 4, 2))       # quinta
    assert is_business_day(date(2026, 4, 6))       # segunda

    w = _world(db)
    _seed_brapi_token(db)
    asset = _brapi_asset(db, w)

    hits = {date(2026, 4, 2): Decimal("32.10")}
    tried: list[date] = []

    def _brapi(ticker, token, target):
        tried.append(target)
        return hits.get(target)

    monkeypatch.setattr(hp_module, "brapi_close_on", _brapi)
    monkeypatch.setattr(hp_module, "yfinance_close_on", lambda *a, **kw: None)

    price = fetch_on(db, asset, date(2026, 4, 6))
    assert price == Decimal("32.10")
    # Walkback pulou weekend + Good Friday, achou dado na quinta 04-02.
    assert tried[0] == date(2026, 4, 6)
    assert tried[1] == date(2026, 4, 2)
    # Provider parou no primeiro hit; não tocou nos candidatos posteriores.
    assert len(tried) == 2


def test_fetch_on_brapi_gives_up_after_3_business_days(db, monkeypatch):
    """brapi None em tudo, yfinance None em tudo → retorna None (sem exceção)."""
    w = _world(db)
    _seed_brapi_token(db)
    asset = _brapi_asset(db, w)

    brapi_calls: list[date] = []
    yf_calls: list[date] = []

    def _brapi(ticker, token, target):
        brapi_calls.append(target)
        return None

    def _yf(symbol, target):
        yf_calls.append(target)
        return None

    monkeypatch.setattr(hp_module, "brapi_close_on", _brapi)
    monkeypatch.setattr(hp_module, "yfinance_close_on", _yf)

    price = fetch_on(db, asset, date(2026, 6, 19))  # sexta útil
    assert price is None
    # Cada provider bate 4 vezes (target + 3 walkback).
    assert len(brapi_calls) == 4
    assert len(yf_calls) == 4


def test_fetch_on_finnhub_fallback_to_yfinance(db, monkeypatch):
    """finnhub retorna None (endpoint pago), yfinance salva o dia."""
    w = _world(db)
    _seed_finnhub_token(db)
    asset = _finnhub_asset(db, w)

    fh_calls: list[date] = []
    yf_calls: list[tuple[str, date]] = []

    def _fh(symbol, token, target):
        fh_calls.append(target)
        return None

    def _yf(symbol, target):
        yf_calls.append((symbol, target))
        return Decimal("178.42") if target == date(2026, 6, 19) else None

    monkeypatch.setattr(hp_module, "finnhub_close_on", _fh)
    monkeypatch.setattr(hp_module, "yfinance_close_on", _yf)

    price = fetch_on(db, asset, date(2026, 6, 19))
    assert price == Decimal("178.42")
    # finnhub tentou os 4 candidatos, yfinance começou pelo target e acertou.
    assert len(fh_calls) == 4
    assert yf_calls[0] == ("AAPL", date(2026, 6, 19))


def test_fetch_on_coinbase_pair_construction(db, monkeypatch):
    """Chain COINBASE: coinbase(BTC, quote=USD) → yfinance(BTC-USD)."""
    w = _world(db)
    asset = _coinbase_asset(db, w, ticker="BTC")

    cb_calls: list[tuple[str, date, str]] = []
    yf_calls: list[tuple[str, date]] = []

    def _cb(symbol, target, quote_currency="USD"):
        cb_calls.append((symbol, target, quote_currency))
        return None  # força fallback pra yfinance

    def _yf(symbol, target):
        yf_calls.append((symbol, target))
        return Decimal("67000") if target == date(2026, 6, 19) else None

    monkeypatch.setattr(hp_module, "coinbase_close_on", _cb)
    monkeypatch.setattr(hp_module, "yfinance_close_on", _yf)

    price = fetch_on(db, asset, date(2026, 6, 19))
    assert price == Decimal("67000")
    # coinbase chamada com quote_currency=USD
    assert cb_calls[0] == ("BTC", date(2026, 6, 19), "USD")
    # yfinance chamada com "BTC-USD"
    assert yf_calls[0] == ("BTC-USD", date(2026, 6, 19))


def test_fetch_on_tesouro_chain(db, monkeypatch):
    """Chain TESOURO: brapi None → tesouro (por asset.name) devolve preço."""
    w = _world(db)
    _seed_brapi_token(db)
    asset = _tesouro_asset(db, w, ticker="LTN", name="Tesouro IPCA+ 2035")

    brapi_calls: list[date] = []
    tesouro_calls: list[tuple[str, date]] = []
    yf_calls: list = []

    def _brapi(ticker, token, target):
        brapi_calls.append(target)
        return None

    def _tesouro(asset_name, target):
        tesouro_calls.append((asset_name, target))
        return Decimal("3120.55") if target == date(2026, 6, 19) else None

    def _yf(symbol, target):
        yf_calls.append((symbol, target))
        return None

    monkeypatch.setattr(hp_module, "brapi_close_on", _brapi)
    monkeypatch.setattr(hp_module, "tesouro_close_on", _tesouro)
    monkeypatch.setattr(hp_module, "yfinance_close_on", _yf)

    price = fetch_on(db, asset, date(2026, 6, 19))
    assert price == Decimal("3120.55")
    # brapi rodou os 4 candidatos, tesouro acertou no primeiro (target).
    assert len(brapi_calls) == 4
    assert tesouro_calls[0] == ("Tesouro IPCA+ 2035", date(2026, 6, 19))
    # yfinance não foi acionado — tesouro resolveu.
    assert yf_calls == []


def test_fetch_on_manual_returns_none_no_chain(db, monkeypatch):
    """MANUAL → chain vazia. Nenhum adapter é chamado."""
    w = _world(db)
    asset = _manual_asset(db, w)

    def _boom(*a, **kw):
        raise AssertionError("no adapter should be called for MANUAL")

    monkeypatch.setattr(hp_module, "brapi_close_on", _boom)
    monkeypatch.setattr(hp_module, "finnhub_close_on", _boom)
    monkeypatch.setattr(hp_module, "coinbase_close_on", _boom)
    monkeypatch.setattr(hp_module, "tesouro_close_on", _boom)
    monkeypatch.setattr(hp_module, "yfinance_close_on", _boom)

    price = fetch_on(db, asset, date(2026, 6, 19))
    assert price is None


def test_fetch_on_writes_audit_log_on_success(db, monkeypatch):
    """Happy path: audit price.fetch_historical persistido no DB."""
    w = _world(db)
    _seed_brapi_token(db)
    asset = _brapi_asset(db, w)

    monkeypatch.setattr(
        hp_module, "brapi_close_on",
        lambda t, tk, target: Decimal("55.55") if target == date(2026, 6, 19) else None,
    )
    monkeypatch.setattr(hp_module, "yfinance_close_on", lambda *a, **kw: None)

    price = fetch_on(db, asset, date(2026, 6, 19))
    assert price == Decimal("55.55")

    log = (
        db.query(AuditLog)
        .filter(
            AuditLog.action == "price.fetch_historical",
            AuditLog.resource_id == asset.id,
        )
        .one()
    )
    assert log.resource_type == "asset"
    assert log.workspace_id == w["ws"].id
    assert log.user_email == "system@historical_price"
    assert log.details is not None
    import json
    payload = json.loads(log.details)
    assert payload["provider"] == "brapi"
    assert payload["target_date"] == "2026-06-19"
    assert payload["effective_date"] == "2026-06-19"
    assert payload["price"] == "55.55"


def test_fetch_on_missing_token_skips_provider(db, monkeypatch):
    """BRAPI sem credencial → pula direto pra yfinance (sem quebrar)."""
    w = _world(db)
    # NB: propositalmente NÃO chama _seed_brapi_token — chain deve pular brapi.
    asset = _brapi_asset(db, w)

    def _brapi(*a, **kw):
        raise AssertionError("brapi should not be called without a token")

    yf_calls: list[tuple[str, date]] = []

    def _yf(symbol, target):
        yf_calls.append((symbol, target))
        return Decimal("22.22") if target == date(2026, 6, 19) else None

    monkeypatch.setattr(hp_module, "brapi_close_on", _brapi)
    monkeypatch.setattr(hp_module, "yfinance_close_on", _yf)

    price = fetch_on(db, asset, date(2026, 6, 19))
    assert price == Decimal("22.22")
    assert yf_calls[0] == ("ITUB4", date(2026, 6, 19))


# ─────────────────────────────────────────────────────────────────────────────
# Fix 2026-08-01: chain COINBASE devolve USD; se asset.currency=BRL, converter
# via PTAX venda da data efetiva antes de gravar. Sem essa etapa, o refresh
# escrevia preço em USD como se fosse BRL e mv_native ficava ~5x menor,
# disparando SUSPICIOUS_DELTA (visto em BTC/USDC no fechamento Jul/26).
# ─────────────────────────────────────────────────────────────────────────────

def _seed_ptax(db, on_date: date, rate: str):
    now = datetime.now(timezone.utc)
    db.add(PTAXRate(
        id=str(uuid.uuid4()), date=on_date, rate=Decimal(rate),
        source="BCB_SGS", fetched_at=now, created_at=now, updated_at=now,
    ))
    db.flush()


def _coinbase_asset_brl(db, w, *, ticker="BTC"):
    a = Asset(
        id=str(uuid.uuid4()), workspace_id=w["ws"].id, account_id=w["acc"].id,
        asset_class=AssetClass.CRYPTO, country="BR",
        name=ticker, ticker=ticker, currency=Currency.BRL,
        price_source=PriceSource.COINBASE,
        is_active=True, created_at=w["now"], updated_at=w["now"],
    )
    db.add(a)
    db.flush()
    return a


def test_fetch_on_coinbase_brl_converts_via_ptax(db, monkeypatch):
    """Coinbase → USD 63048.34; asset BRL + PTAX 5.20 → 327851.37 BRL."""
    w = _world(db)
    asset = _coinbase_asset_brl(db, w, ticker="BTC")
    _seed_ptax(db, date(2026, 7, 31), "5.20")

    monkeypatch.setattr(
        hp_module, "coinbase_close_on",
        lambda t, target, quote="USD": (
            Decimal("63048.34") if target == date(2026, 7, 31) else None
        ),
    )
    monkeypatch.setattr(hp_module, "yfinance_close_on", lambda *a, **kw: None)

    price = fetch_on(db, asset, date(2026, 7, 31))
    assert price == Decimal("63048.34") * Decimal("5.20")

    import json
    log = (
        db.query(AuditLog)
        .filter(
            AuditLog.action == "price.fetch_historical",
            AuditLog.resource_id == asset.id,
        )
        .one()
    )
    payload = json.loads(log.details)
    assert payload["fx_conversion"]["native_price_usd"] == "63048.34"
    assert payload["fx_conversion"]["ptax_venda"] == "5.20000000"
    assert payload["fx_conversion"]["converted_to"] == "BRL"


def test_fetch_on_coinbase_usd_no_conversion(db, monkeypatch):
    """Asset com currency=USD não converte, mesmo com PTAX disponível."""
    w = _world(db)
    asset = _coinbase_asset(db, w, ticker="BTC")  # currency=USD
    _seed_ptax(db, date(2026, 7, 31), "5.20")

    monkeypatch.setattr(
        hp_module, "coinbase_close_on",
        lambda t, target, quote="USD": (
            Decimal("63048.34") if target == date(2026, 7, 31) else None
        ),
    )
    monkeypatch.setattr(hp_module, "yfinance_close_on", lambda *a, **kw: None)

    price = fetch_on(db, asset, date(2026, 7, 31))
    assert price == Decimal("63048.34")


def test_fetch_on_coinbase_brl_no_ptax_returns_none(db, monkeypatch):
    """Sem PTAX na janela → prefere retornar None a gravar preço USD como BRL.

    A fallback yfinance também devolve USD; sem PTAX, ambas as etapas da
    chain são puladas e fetch_on retorna None. Chamador (pendency retry) vai
    manter o item aguardando edição manual — o comportamento seguro."""
    w = _world(db)
    asset = _coinbase_asset_brl(db, w, ticker="BTC")
    # NB: sem _seed_ptax — tabela vazia dentro da janela de 10 dias.

    monkeypatch.setattr(
        hp_module, "coinbase_close_on",
        lambda t, target, quote="USD": (
            Decimal("63048.34") if target == date(2026, 7, 31) else None
        ),
    )
    monkeypatch.setattr(
        hp_module, "yfinance_close_on",
        lambda symbol, target: (
            Decimal("63048.34") if target == date(2026, 7, 31) else None
        ),
    )

    price = fetch_on(db, asset, date(2026, 7, 31))
    assert price is None
