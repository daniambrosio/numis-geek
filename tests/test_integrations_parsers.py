"""Unit tests for integration adapter parsers.

Cobre gaps identificados no audit (task 53):
- integrations/brapi.py: fetch_quote + fetch_fundamentals com payload real
  congelado (dict), assertando shape parseado.
- integrations/finnhub.py: fetch_basic_financials com payload real.
- integrations/yfinance.py: fetch_history_monthly com DataFrame fake.
- integrations/bcb.py: _chunks (chunking de janelas > 9 anos) + fetch_ptax_range
  chamando N vezes.

Padrão: patch em nível de módulo (`httpx.get` / `yfinance.Ticker`) — mesmo
approach de tests/test_coinbase.py.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import httpx
import pytest


# ═══════════════════════════════════════════════════════════════════════════
# BRAPI
# ═══════════════════════════════════════════════════════════════════════════


def _mock_response(payload, status_code=200):
    r = MagicMock(spec=httpx.Response)
    r.json.return_value = payload
    r.raise_for_status.return_value = None
    r.status_code = status_code
    return r


# Payload real da API brapi (formato /api/quote/PETR4) — copiado com
# subset relevante das chaves.
BRAPI_QUOTE_PAYLOAD = {
    "results": [
        {
            "currency": "BRL",
            "symbol": "PETR4",
            "regularMarketPrice": 38.42,
            "regularMarketDayHigh": 38.90,
            "regularMarketDayLow": 38.10,
            "regularMarketTime": 1717000000,
        }
    ],
    "requestedAt": "2026-05-27T14:00:00.000Z",
}


BRAPI_FUNDAMENTALS_PAYLOAD = {
    "results": [
        {
            "symbol": "PETR4",
            "priceEarnings": 5.4,
            "priceToBookValueRatio": 1.2,
            "earningsPerShare": 7.85,
            "dividendYield": 0.14,
            "dividendRate": 6.30,
            "summaryProfile": {"sector": "Energy"},
            "defaultKeyStatistics": {
                "trailingPE": 5.4,
                "priceToBook": 1.2,
                "trailingEps": 7.85,
                "bookValuePerShare": 32.10,
            },
            "financialData": {"returnOnEquity": 0.28},
        }
    ]
}


def test_brapi_fetch_quote_happy():
    from numis_geek.integrations.brapi import fetch_quote

    with patch("numis_geek.integrations.brapi.httpx.get") as g:
        g.return_value = _mock_response(BRAPI_QUOTE_PAYLOAD)
        q = fetch_quote("PETR4", "fake-token")
    assert q.ticker == "PETR4"
    assert q.price == Decimal("38.42")


def test_brapi_fetch_quote_missing_price_raises():
    """Edge: regularMarketPrice ausente → BrapiError."""
    from numis_geek.integrations.brapi import BrapiError, fetch_quote

    bad = {"results": [{"symbol": "PETR4"}]}  # sem regularMarketPrice
    with patch("numis_geek.integrations.brapi.httpx.get") as g:
        g.return_value = _mock_response(bad)
        with pytest.raises(BrapiError, match="missing regularMarketPrice"):
            fetch_quote("PETR4", "fake-token")


def test_brapi_fetch_fundamentals_happy():
    from numis_geek.integrations.brapi import fetch_fundamentals

    with patch("numis_geek.integrations.brapi.httpx.get") as g:
        g.return_value = _mock_response(BRAPI_FUNDAMENTALS_PAYLOAD)
        f = fetch_fundamentals("PETR4", "fake-token")
    assert f.ticker == "PETR4"
    assert f.pe == Decimal("5.4")
    assert f.pb == Decimal("1.2")
    assert f.eps == Decimal("7.85")
    assert f.bvps == Decimal("32.10")
    assert f.roe == Decimal("0.28")
    assert f.dividend_yield_12m == Decimal("0.14")
    assert f.dps_12m == Decimal("6.30")
    assert f.p_vp == Decimal("1.2")
    assert f.sector == "Energy"


def test_brapi_fetch_fundamentals_edge_missing_modules():
    """Edge: `defaultKeyStatistics`/`financialData`/`summaryProfile` ausentes.
    Parser deve tolerar (todos os campos derivados = None) sem levantar."""
    from numis_geek.integrations.brapi import fetch_fundamentals

    minimal = {"results": [{"symbol": "XPLG11"}]}  # apenas symbol
    with patch("numis_geek.integrations.brapi.httpx.get") as g:
        g.return_value = _mock_response(minimal)
        f = fetch_fundamentals("XPLG11", "fake-token")
    assert f.ticker == "XPLG11"
    assert f.pe is None
    assert f.pb is None
    assert f.eps is None
    assert f.roe is None
    assert f.sector is None
    # raw preserva a row original.
    assert f.raw == minimal["results"][0]


# ═══════════════════════════════════════════════════════════════════════════
# FINNHUB
# ═══════════════════════════════════════════════════════════════════════════


# Payload real da API Finnhub /stock/metric?metric=all — subset relevante.
FINNHUB_METRIC_PAYLOAD = {
    "symbol": "AAPL",
    "metricType": "all",
    "metric": {
        "peTTM": 28.5,
        "peNormalizedAnnual": 30.1,
        "pbAnnual": 45.2,
        "epsTTM": 6.10,
        "bookValuePerShareQuarterly": 4.02,
        "roeTTM": 145.5,        # % → 1.455 após _pct
        "roiTTM": 25.0,
        "netProfitMarginTTM": 25.3,
        "ebitdaMargin5Y": 30.1,
        "totalDebt/totalEquityAnnual": 1.85,
        "epsGrowth5Y": 12.5,
        "dividendYieldIndicatedAnnual": 0.55,
        "payoutRatioTTM": 15.0,
        "dividendPerShareTTM": 0.96,
    },
}


def test_finnhub_fetch_basic_financials_happy():
    from numis_geek.integrations.finnhub import fetch_basic_financials

    with patch("numis_geek.integrations.finnhub.httpx.get") as g:
        g.return_value = _mock_response(FINNHUB_METRIC_PAYLOAD)
        f = fetch_basic_financials("AAPL", "fake-token")
    assert f.symbol == "AAPL"
    assert f.pe == Decimal("28.5")
    assert f.pb == Decimal("45.2")
    assert f.eps == Decimal("6.10")
    assert f.bvps == Decimal("4.02")
    # Percentage-shaped metrics: dividido por 100 pelo _pct helper.
    assert f.roe == Decimal("145.5") / Decimal("100")
    assert f.roic == Decimal("25.0") / Decimal("100")
    assert f.net_margin == Decimal("25.3") / Decimal("100")
    assert f.ebitda_margin == Decimal("30.1") / Decimal("100")
    assert f.dividend_yield_12m == Decimal("0.55") / Decimal("100")
    assert f.payout_ratio == Decimal("15.0") / Decimal("100")
    assert f.earnings_growth_5y == Decimal("12.5") / Decimal("100")
    assert f.debt_ebitda == Decimal("1.85")
    assert f.dps_12m == Decimal("0.96")


def test_finnhub_fetch_basic_financials_empty_metric_still_parses():
    """Edge: `metric` presente mas vazio — todos os campos derivados None."""
    from numis_geek.integrations.finnhub import fetch_basic_financials

    empty = {"symbol": "AAPL", "metricType": "all", "metric": {}}
    with patch("numis_geek.integrations.finnhub.httpx.get") as g:
        g.return_value = _mock_response(empty)
        f = fetch_basic_financials("AAPL", "fake-token")
    assert f.symbol == "AAPL"
    assert f.pe is None and f.pb is None and f.eps is None
    assert f.roe is None and f.roic is None
    assert f.dividend_yield_12m is None
    assert f.raw == {}


def test_finnhub_fetch_basic_financials_missing_metric_key_tolerated():
    """Edge: `metric` ausente do payload — parser trata como dict vazio.

    Comportamento atual: `data.get("metric") or {}` → todos None, raw={}.
    (Se algum dia o parser passar a levantar FinnhubError, este teste
    é a regressão pra pegar a mudança silenciosa.)"""
    from numis_geek.integrations.finnhub import fetch_basic_financials

    with patch("numis_geek.integrations.finnhub.httpx.get") as g:
        g.return_value = _mock_response({"symbol": "AAPL"})  # sem "metric"
        f = fetch_basic_financials("AAPL", "fake-token")
    assert f.symbol == "AAPL"
    assert f.pe is None
    assert f.raw == {}


def test_finnhub_fetch_basic_financials_non_dict_payload_raises():
    """Edge: payload não é dict (ex.: lista, string) → FinnhubError."""
    from numis_geek.integrations.finnhub import FinnhubError, fetch_basic_financials

    with patch("numis_geek.integrations.finnhub.httpx.get") as g:
        g.return_value = _mock_response(["unexpected", "list"])
        with pytest.raises(FinnhubError, match="unexpected payload"):
            fetch_basic_financials("AAPL", "fake-token")


# ═══════════════════════════════════════════════════════════════════════════
# YFINANCE
# ═══════════════════════════════════════════════════════════════════════════


class _FakeYFTicker:
    """Emula yfinance.Ticker.history() com um DataFrame in-memory. Não
    depende do pacote yfinance real (evita rede)."""

    def __init__(self, df):
        self._df = df

    def history(self, **kwargs):
        return self._df


def _make_monthly_df(closes: list[tuple[str, float]]):
    """Cria um pandas.DataFrame no shape que yfinance.history retorna."""
    import pandas as pd
    idx = pd.to_datetime([d for d, _ in closes])
    return pd.DataFrame({"Close": [c for _, c in closes]}, index=idx)


def test_yfinance_fetch_history_monthly_happy():
    from numis_geek.integrations import yfinance as yfmod

    df = _make_monthly_df([
        ("2026-01-01", 100.5),
        ("2026-02-01", 101.5),
        ("2026-03-01", 102.5),
    ])
    fake_yf = MagicMock()
    fake_yf.Ticker.return_value = _FakeYFTicker(df)
    with patch.object(yfmod, "yf", fake_yf), patch.object(yfmod, "_HAS_YFINANCE", True):
        points = yfmod.fetch_history_monthly(
            "AAPL", start=date(2026, 1, 1), end=date(2026, 4, 1)
        )
    assert len(points) == 3
    assert points[0].date == date(2026, 1, 1)
    assert points[0].close == Decimal("100.5")
    assert points[1].close == Decimal("101.5")
    assert points[2].date == date(2026, 3, 1)


def test_yfinance_fetch_history_monthly_empty_raises():
    """Edge: DataFrame vazio → YFinanceError."""
    from numis_geek.integrations import yfinance as yfmod

    import pandas as pd
    empty_df = pd.DataFrame({"Close": []})
    fake_yf = MagicMock()
    fake_yf.Ticker.return_value = _FakeYFTicker(empty_df)
    with patch.object(yfmod, "yf", fake_yf), patch.object(yfmod, "_HAS_YFINANCE", True):
        with pytest.raises(yfmod.YFinanceError, match="empty"):
            yfmod.fetch_history_monthly(
                "AAPL", start=date(2026, 1, 1), end=date(2026, 4, 1)
            )


def test_yfinance_fetch_history_monthly_raises_when_pkg_missing():
    """Edge: yfinance não instalado (`_HAS_YFINANCE = False`) → YFinanceError.
    Garante degradação graceful pra ambientes sem o pacote."""
    from numis_geek.integrations import yfinance as yfmod

    with patch.object(yfmod, "_HAS_YFINANCE", False):
        with pytest.raises(yfmod.YFinanceError, match="not installed"):
            yfmod.fetch_history_monthly(
                "AAPL", start=date(2026, 1, 1), end=date(2026, 3, 1)
            )


# ═══════════════════════════════════════════════════════════════════════════
# BCB — _chunks + fetch_ptax_range chunking
# ═══════════════════════════════════════════════════════════════════════════


def test_bcb_chunks_small_window_returns_single_chunk():
    """Janela < 9 anos vira 1 chunk único."""
    from numis_geek.integrations.bcb import _chunks

    chunks = list(_chunks(date(2026, 1, 1), date(2026, 5, 31)))
    assert len(chunks) == 1
    assert chunks[0] == (date(2026, 1, 1), date(2026, 5, 31))


def test_bcb_chunks_large_window_splits():
    """Janela > 9 anos vira múltiplos chunks contíguos (sem gap, sem overlap)."""
    from numis_geek.integrations.bcb import _chunks

    chunks = list(_chunks(date(2000, 1, 1), date(2026, 5, 31)))
    # 26 anos → 3 chunks (9+9+8).
    assert len(chunks) >= 2
    # Chunks contíguos: end[i] + 1d == start[i+1].
    from datetime import timedelta
    for prev, curr in zip(chunks, chunks[1:]):
        assert prev[1] + timedelta(days=1) == curr[0], (
            f"Gap/overlap entre chunks: {prev} → {curr}"
        )
    # Início e fim batem com a janela pedida.
    assert chunks[0][0] == date(2000, 1, 1)
    assert chunks[-1][1] == date(2026, 5, 31)
    # Cada chunk (exceto potencialmente o último) cobre ~9 anos.
    for chunk_start, chunk_end in chunks[:-1]:
        span_days = (chunk_end - chunk_start).days
        # 9 anos ≈ 3285-3287 dias. Tolerância generosa.
        assert 3280 < span_days < 3300, f"chunk {chunk_start}-{chunk_end}"


def test_bcb_fetch_ptax_range_short_window_single_call():
    """400 dias < 9 anos → 1 chunk → 1 HTTP call."""
    from numis_geek.integrations import bcb as bcb_mod

    payload = [
        {"data": "01/01/2026", "valor": "5.10"},
        {"data": "02/01/2026", "valor": "5.11"},
    ]
    with patch("numis_geek.integrations.bcb.httpx.Client") as ClientCls:
        client = MagicMock()
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        client.get.return_value = _mock_response(payload)
        ClientCls.return_value = client

        rows = bcb_mod.fetch_ptax_range(date(2026, 1, 1), date(2026, 2, 5))

    # Uma única chamada BCB (janela < 9 anos).
    assert client.get.call_count == 1
    assert len(rows) == 2
    assert rows[0].date == date(2026, 1, 1)
    assert rows[0].rate == Decimal("5.10")
    assert rows[1].date == date(2026, 1, 2)


def test_bcb_fetch_ptax_range_large_window_multiple_calls():
    """Janela de 20 anos → múltiplas chamadas (uma por chunk)."""
    from numis_geek.integrations import bcb as bcb_mod

    # Cada chamada retorna 1 row com a data do dataInicial (basta pra
    # provar contagem de chunks + dedup por data).
    call_counter = {"n": 0}

    def _get(url, params, timeout):
        call_counter["n"] += 1
        di = params["dataInicial"]
        # Cria uma resposta com 1 row diferente por chunk (data única).
        row_date = f"{di}"
        # Data mock: usa a data inicial do chunk como valor único.
        return _mock_response([
            {"data": row_date, "valor": "5.00"},
        ])

    with patch("numis_geek.integrations.bcb.httpx.Client") as ClientCls:
        client = MagicMock()
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        client.get.side_effect = _get
        ClientCls.return_value = client

        rows = bcb_mod.fetch_ptax_range(date(2000, 1, 1), date(2020, 1, 1))

    # 20 anos → pelo menos 3 chunks.
    assert call_counter["n"] >= 3
    # Cada chunk devolveu 1 row único → dedup por data preserva todos.
    assert len(rows) == call_counter["n"]


def test_bcb_fetch_ptax_range_end_before_start_raises():
    """Precondição: end < start → ValueError."""
    from numis_geek.integrations import bcb as bcb_mod

    with pytest.raises(ValueError, match="precedes start"):
        bcb_mod.fetch_ptax_range(date(2026, 2, 1), date(2026, 1, 1))
