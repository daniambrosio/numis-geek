"""Unit tests for the Tesouro Transparente historical price adapter.

The real CSV is 14 MB; we inject a small in-memory fixture via the
`csv_text` kwarg so the tests are hermetic and never touch the network.
The HTTP path is exercised separately by patching `httpx.get`.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import httpx
import pytest

from numis_geek.integrations import tesouro
from numis_geek.integrations.tesouro import (
    TesouroError,
    fetch_close_on,
)


# Realistic-shape fixture. Semicolon-separated, DD/MM/YYYY, comma decimals.
FIXTURE_CSV = (
    "Tipo Titulo;Data Vencimento;Data Base;Taxa Compra Manha;Taxa Venda Manha;"
    "PU Compra Manha;PU Venda Manha;PU Base Manha\n"
    # Bond A — Tesouro IPCA+ 2035, three consecutive days
    "Tesouro IPCA+;15/05/2035;24/07/2026;6,19;6,25;1234,50;1230,00;1232,10\n"
    "Tesouro IPCA+;15/05/2035;25/07/2026;6,20;6,26;1235,00;1231,00;1233,00\n"
    "Tesouro IPCA+;15/05/2035;28/07/2026;6,21;6,27;1236,77;1232,10;1234,00\n"
    # Bond B — same title but different vencimento
    "Tesouro IPCA+;15/05/2045;28/07/2026;6,80;6,88;900,10;895,00;897,50\n"
    # Bond C — different title (Semestrais) same year as Bond A
    "Tesouro IPCA+ com Juros Semestrais;15/05/2035;28/07/2026;6,15;6,20;4000,00;3990,00;3995,00\n"
    # Bond D — Selic short-term
    "Tesouro Selic;01/03/2029;28/07/2026;0,05;0,05;15100,20;15099,00;15100,00\n"
    # Bond E — Prefixado, only a base column populated (compra empty)
    "Tesouro Prefixado;01/01/2030;28/07/2026;10,50;10,60;;760,00;762,50\n"
)


# --------------------------------------------------------------------------- #
# Matching / lookup
# --------------------------------------------------------------------------- #

def test_hit_exact_by_title_and_year():
    price = fetch_close_on(
        "Tesouro IPCA+ 2035", date(2026, 7, 28), csv_text=FIXTURE_CSV
    )
    # PU Compra Manha wins — user pays this to buy
    assert price == Decimal("1236.77")


def test_hit_exact_by_full_vencimento():
    price = fetch_close_on(
        "Tesouro IPCA+ 15/05/2035", date(2026, 7, 25), csv_text=FIXTURE_CSV
    )
    assert price == Decimal("1235.00")


def test_hit_disambiguates_by_year_between_titles_sharing_a_prefix():
    # "Tesouro IPCA+ 2035" MUST NOT collide with
    # "Tesouro IPCA+ com Juros Semestrais 15/05/2035".
    price = fetch_close_on(
        "Tesouro IPCA+ 2035", date(2026, 7, 28), csv_text=FIXTURE_CSV
    )
    assert price == Decimal("1236.77")

    semestrais = fetch_close_on(
        "Tesouro IPCA+ com Juros Semestrais 2035",
        date(2026, 7, 28),
        csv_text=FIXTURE_CSV,
    )
    assert semestrais == Decimal("4000.00")


def test_hit_selic_short_ticker_like_form():
    price = fetch_close_on(
        "Tesouro Selic 2029", date(2026, 7, 28), csv_text=FIXTURE_CSV
    )
    assert price == Decimal("15100.20")


def test_falls_back_to_base_when_compra_empty():
    # Bond E has an empty PU Compra Manha — must fall back to PU Base Manha
    price = fetch_close_on(
        "Tesouro Prefixado 2030", date(2026, 7, 28), csv_text=FIXTURE_CSV
    )
    assert price == Decimal("762.50")


# --------------------------------------------------------------------------- #
# Misses
# --------------------------------------------------------------------------- #

def test_returns_none_when_date_absent():
    price = fetch_close_on(
        "Tesouro IPCA+ 2035", date(1999, 1, 1), csv_text=FIXTURE_CSV
    )
    assert price is None


def test_returns_none_when_asset_name_absent():
    price = fetch_close_on(
        "Tesouro Nonexistent 2035", date(2026, 7, 28), csv_text=FIXTURE_CSV
    )
    assert price is None


def test_returns_none_when_asset_name_year_mismatches_available_bond():
    price = fetch_close_on(
        "Tesouro IPCA+ 2099", date(2026, 7, 28), csv_text=FIXTURE_CSV
    )
    assert price is None


def test_returns_none_on_empty_query():
    assert fetch_close_on("", date(2026, 7, 28), csv_text=FIXTURE_CSV) is None
    assert fetch_close_on("   ", date(2026, 7, 28), csv_text=FIXTURE_CSV) is None


def test_returns_none_when_ambiguous_across_vencimentos():
    # "Tesouro IPCA+" without a year hits both 2035 and 2045 on 28/07 — ambiguous.
    price = fetch_close_on(
        "Tesouro IPCA+", date(2026, 7, 28), csv_text=FIXTURE_CSV
    )
    assert price is None


# --------------------------------------------------------------------------- #
# Parsing hardening
# --------------------------------------------------------------------------- #

def test_missing_column_raises_tesouro_error():
    bad_csv = "Tipo Titulo;Data Vencimento\nTesouro IPCA+;15/05/2035\n"
    with pytest.raises(TesouroError, match="missing required columns"):
        fetch_close_on("Tesouro IPCA+ 2035", date(2026, 7, 28), csv_text=bad_csv)


def test_malformed_rows_are_skipped_not_fatal():
    csv_with_junk = FIXTURE_CSV + "not;a;valid;row\n"
    price = fetch_close_on(
        "Tesouro IPCA+ 2035", date(2026, 7, 28), csv_text=csv_with_junk
    )
    assert price == Decimal("1236.77")


# --------------------------------------------------------------------------- #
# HTTP + cache
# --------------------------------------------------------------------------- #

def _mock_get_response(body: bytes, status: int = 200):
    r = MagicMock(spec=httpx.Response)
    r.content = body
    r.status_code = status
    r.raise_for_status.return_value = None
    return r


def test_downloads_and_caches_csv(tmp_path, monkeypatch):
    monkeypatch.setenv("TESOURO_CACHE_DIR", str(tmp_path))

    with patch("numis_geek.integrations.tesouro.httpx.get") as g:
        g.return_value = _mock_get_response(FIXTURE_CSV.encode("utf-8"))
        first = fetch_close_on("Tesouro IPCA+ 2035", date(2026, 7, 28))
        assert first == Decimal("1236.77")
        assert g.call_count == 1

        # Second call on the same day must reuse the cached file
        # — no additional HTTP request.
        second = fetch_close_on("Tesouro IPCA+ 2045", date(2026, 7, 28))
        assert second == Decimal("900.10")
        assert g.call_count == 1

    # Cache file must exist on disk under the configured directory
    files = list(tmp_path.glob("precotaxatesourodireto_*.csv"))
    assert len(files) == 1


def test_http_error_wraps_to_tesouro_error(tmp_path, monkeypatch):
    monkeypatch.setenv("TESOURO_CACHE_DIR", str(tmp_path))
    with patch("numis_geek.integrations.tesouro.httpx.get") as g:
        g.side_effect = httpx.ConnectError("network down")
        with pytest.raises(TesouroError, match="download failed"):
            fetch_close_on(
                "Tesouro IPCA+ 2035", date(2026, 7, 28), use_cache=False,
            )


def test_cache_dir_override_via_env(tmp_path, monkeypatch):
    monkeypatch.setenv("TESOURO_CACHE_DIR", str(tmp_path / "custom"))
    assert tesouro._cache_dir() == tmp_path / "custom"
