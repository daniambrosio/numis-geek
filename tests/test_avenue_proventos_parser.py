"""Spec 58 Stage 4 — unit tests for the Avenue proventos CSV parser.

Pure unit tests: no DB, no LLM. The parser takes raw CSV bytes and
emits a payload dict whose shape mirrors what an LLM would emit for a
BROKER_INCOME job — so the apply layer is source-agnostic.
"""
from __future__ import annotations

import pytest

from numis_geek.services.extraction_parsers.avenue_proventos import (
    parse_avenue_proventos_csv,
)


HEADER = "Data transação,Data liquidação,Descrição,Valor,Saldo\n"


def _parse(rows: list[str]) -> dict:
    return parse_avenue_proventos_csv((HEADER + "\n".join(rows) + "\n").encode("utf-8"))


# ── basic per-pattern coverage ──────────────────────────────────────────────


def test_dividend_paired_with_tax():
    p = _parse([
        "27/05/2026,27/05/2026,Dividendos de WMT,12.32,727.33",
        "27/05/2026,27/05/2026,Imposto sobre dividendo de WMT,-3.70,723.63",
    ])
    assert len(p["events"]) == 1
    e = p["events"][0]
    assert e["event_date"] == "2026-05-27"
    assert e["ticker_raw"] == "WMT"
    assert e["type"] == "DIVIDEND"
    assert e["gross_amount"] == 12.32
    assert e["tax_amount"] == 3.70
    assert e["net_amount"] == pytest.approx(8.62)
    assert e["currency"] == "USD"


def test_dividend_with_adr_fee_combines_into_tax():
    p = _parse([
        "13/05/2026,13/05/2026,Dividendos de BTI,27.00,322.71",
        "13/05/2026,13/05/2026,Taxa sobre ADR de BTI,-0.32,295.71",
    ])
    assert len(p["events"]) == 1
    e = p["events"][0]
    assert e["ticker_raw"] == "BTI"
    assert e["gross_amount"] == 27.00
    assert e["tax_amount"] == 0.32
    assert e["net_amount"] == pytest.approx(26.68)


def test_dividend_with_tax_and_adr_fee_sums_both_into_tax():
    p = _parse([
        "13/05/2026,13/05/2026,Dividendos de BTI,27.00,322.71",
        "13/05/2026,13/05/2026,Imposto sobre dividendo de BTI,-8.10,314.61",
        "13/05/2026,13/05/2026,Taxa sobre ADR de BTI,-0.32,314.29",
    ])
    e = p["events"][0]
    assert e["tax_amount"] == pytest.approx(8.42)
    assert e["net_amount"] == pytest.approx(18.58)


def test_coupon_alone_is_interest_with_no_tax():
    """Treasury coupons come without a paired tax row in Avenue's CSV."""
    p = _parse([
        "16/05/2026,18/05/2026,Cupom de T 4.25 15/11/34,212.50,718.71",
    ])
    e = p["events"][0]
    assert e["type"] == "INTEREST"
    assert e["ticker_raw"] == "T 4.25 15/11/34"
    assert e["event_date"] == "2026-05-18"  # uses Data liquidação
    assert e["gross_amount"] == 212.50
    assert e["tax_amount"] is None
    assert e["net_amount"] == 212.50


def test_securities_lending_paired():
    p = _parse([
        "13/05/2026,13/05/2026,Rentabilidade de aluguel de ativo,0.64,323.35",
        "13/05/2026,13/05/2026,Imposto de aluguel de ativo,-0.19,323.16",
    ])
    e = p["events"][0]
    assert e["type"] == "SECURITIES_LENDING"
    assert e["ticker_raw"] is None
    assert e["gross_amount"] == 0.64
    assert e["tax_amount"] == 0.19
    assert e["net_amount"] == pytest.approx(0.45)


# ── pairing edge cases ─────────────────────────────────────────────────────


def test_tax_appearing_before_gross_still_pairs():
    """CSV row order shouldn't affect pairing — group by (date, ticker, family)."""
    p = _parse([
        "27/05/2026,27/05/2026,Imposto sobre dividendo de WMT,-3.70,723.63",
        "27/05/2026,27/05/2026,Dividendos de WMT,12.32,727.33",
    ])
    assert len(p["events"]) == 1
    e = p["events"][0]
    assert e["gross_amount"] == 12.32
    assert e["tax_amount"] == 3.70


def test_same_ticker_different_dates_are_separate_events():
    """Two VCLT dividends with different settlement dates → 2 events."""
    p = _parse([
        "06/05/2026,06/05/2026,Dividendos de VCLT,0.15,276.37",
        "06/05/2026,06/05/2026,Imposto sobre dividendo de VCLT,-0.05,276.32",
        "06/05/2026,07/05/2026,Dividendos de VCLT,32.41,285.94",
        "06/05/2026,07/05/2026,Imposto sobre dividendo de VCLT,-9.72,276.22",
    ])
    assert len(p["events"]) == 2
    dates = sorted(e["event_date"] for e in p["events"])
    assert dates == ["2026-05-06", "2026-05-07"]


def test_orphan_tax_row_without_gross_is_skipped():
    """Tax row without a matching gross row → no event emitted."""
    p = _parse([
        "27/05/2026,27/05/2026,Imposto sobre dividendo de XYZ,-3.70,723.63",
    ])
    assert p["events"] == []


def test_unknown_description_recorded_in_diagnostics():
    p = _parse([
        "27/05/2026,27/05/2026,Algo completamente novo,5.00,100.00",
    ])
    assert p["events"] == []
    assert "Algo completamente novo" in p["_unparsed_descriptions"]


def test_uses_liquidacao_date_not_transacao():
    """When the two dates differ, event_date follows Data liquidação (cash arrives)."""
    p = _parse([
        "01/05/2026,04/05/2026,Dividendos de XYZ,10.00,100.00",
    ])
    assert p["events"][0]["event_date"] == "2026-05-04"


def test_falls_back_to_transacao_when_liquidacao_missing():
    p = _parse([
        "01/05/2026,,Dividendos de XYZ,10.00,100.00",
    ])
    assert p["events"][0]["event_date"] == "2026-05-01"


# ── real CSV regression ────────────────────────────────────────────────────


def test_real_avenue_csv_smoke():
    """Run the parser on the real fixture file and assert a sane shape."""
    import pathlib
    p = pathlib.Path("/Users/dambrosio/Downloads/avenue-report-statement (4).csv")
    if not p.exists():
        pytest.skip("real Avenue fixture not present on this machine")
    payload = parse_avenue_proventos_csv(p.read_bytes())
    assert payload["broker_name"] == "Avenue"
    assert payload["as_of_date"] == "2026-05-27"
    assert len(payload["events"]) == 20
    assert payload["_unparsed_descriptions"] == []
    # Spot-check a few well-known rows.
    by_key = {(e["event_date"], e["ticker_raw"]): e for e in payload["events"]}
    assert by_key[("2026-05-27", "WMT")]["net_amount"] == pytest.approx(8.62)
    assert by_key[("2026-05-13", "BTI")]["tax_amount"] == pytest.approx(0.32)
    assert by_key[("2026-05-18", "T 4.25 15/11/34")]["type"] == "INTEREST"
    assert by_key[("2026-05-13", None)]["type"] == "SECURITIES_LENDING"


# ── helpers / output shape ─────────────────────────────────────────────────


def test_empty_csv_returns_empty_events():
    p = parse_avenue_proventos_csv(HEADER.encode("utf-8"))
    assert p["events"] == []
    assert p["as_of_date"] is None
    assert p["broker_name"] == "Avenue"


def test_payload_shape_mirrors_llm_broker_income():
    """Same top-level keys as the LLM BROKER_INCOME schema."""
    p = _parse([
        "27/05/2026,27/05/2026,Dividendos de WMT,12.32,727.33",
    ])
    # Top-level
    assert set(p.keys()) >= {"as_of_date", "broker_name", "events"}
    # Per-event
    e = p["events"][0]
    assert set(e.keys()) >= {
        "event_date", "ticker_raw", "type",
        "gross_amount", "tax_amount", "net_amount",
        "currency", "notes", "confidence",
    }


# ── parser_for registry ─────────────────────────────────────────────────────


def test_parser_for_routes_avenue_income_csv():
    from numis_geek.services.extraction_parsers import parser_for
    from numis_geek.models.extraction_job import ExtractionSourceHint

    fn = parser_for(
        institution_short_name="Avenue",
        source_hint=ExtractionSourceHint.BROKER_INCOME,
        mime_type="text/csv",
    )
    assert fn is parse_avenue_proventos_csv


def test_parser_for_returns_none_for_unknown_combo():
    from numis_geek.services.extraction_parsers import parser_for
    from numis_geek.models.extraction_job import ExtractionSourceHint

    # Unknown FI
    assert parser_for(
        institution_short_name="XP", source_hint=ExtractionSourceHint.BROKER_INCOME,
        mime_type="text/csv",
    ) is None
    # Avenue but positions, not income
    assert parser_for(
        institution_short_name="Avenue",
        source_hint=ExtractionSourceHint.BROKER_POSITION,
        mime_type="text/csv",
    ) is None
    # Avenue income but PDF instead of CSV
    assert parser_for(
        institution_short_name="Avenue",
        source_hint=ExtractionSourceHint.BROKER_INCOME,
        mime_type="application/pdf",
    ) is None
    # Missing FI
    assert parser_for(
        institution_short_name=None,
        source_hint=ExtractionSourceHint.BROKER_INCOME,
        mime_type="text/csv",
    ) is None


def test_parser_for_case_insensitive_fi_name():
    from numis_geek.services.extraction_parsers import parser_for
    from numis_geek.models.extraction_job import ExtractionSourceHint

    for variant in ("avenue", "AVENUE", " Avenue "):
        fn = parser_for(
            institution_short_name=variant,
            source_hint=ExtractionSourceHint.BROKER_INCOME,
            mime_type="text/csv",
        )
        assert fn is parse_avenue_proventos_csv
