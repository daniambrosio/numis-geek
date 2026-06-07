"""Spec 57 — defensive disambiguator for duplicate ticker_raw in LLM output.

Pure unit tests (no DB) for `_disambiguate_duplicate_tickers` and the
`_maturity_from_notes` helper. The integration path (LLM call →
disambiguate → persist) is covered by existing extraction tests using
the FakeLLM fixture.
"""
from __future__ import annotations

from numis_geek.services.extraction import (
    _disambiguate_duplicate_tickers,
    _extract_dates,
    _maturity_from_notes,
)
from numis_geek.services.extraction_templates import (
    BrokerPosition,
    BrokerPositionOutput,
)


def _pos(ticker_raw: str, notes: str | None = None) -> BrokerPosition:
    return BrokerPosition(
        ticker_raw=ticker_raw, ticker_normalized=None,
        quantity=1.0, unit_price=None, currency="USD",
        market_value=None, confidence=0.9, notes=notes,
    )


# ── _maturity_from_notes ────────────────────────────────────────────────────


def test_maturity_iso_format():
    assert _maturity_from_notes("Vencimento 2034-08-16") == "2034-08-16"


def test_maturity_ddmmyyyy_format():
    assert _maturity_from_notes("Tesouro US - Vencimento: 16/08/2034") == "2034-08-16"


def test_maturity_mmyyyy_format():
    assert _maturity_from_notes("CDB Itaú - 05/2027") == "2027-05"


def test_maturity_no_date_returns_none():
    assert _maturity_from_notes("Sem data aqui") is None


def test_maturity_none_notes():
    assert _maturity_from_notes(None) is None


def test_maturity_picks_most_specific_first():
    # ISO present alongside DDMMYYYY — ISO wins (tried first).
    assert _maturity_from_notes("Notes 2034-08-16 also 01/01/2025") == "2034-08-16"


# ── _disambiguate_duplicate_tickers ─────────────────────────────────────────


def test_disambiguate_no_duplicates_noop():
    out = BrokerPositionOutput(positions=[
        _pos("AAPL"),
        _pos("MSFT"),
        _pos("VOO"),
    ])
    _disambiguate_duplicate_tickers(out)
    assert [p.ticker_raw for p in out.positions] == ["AAPL", "MSFT", "VOO"]


def test_disambiguate_treasury_dupes_get_maturity_suffix():
    out = BrokerPositionOutput(positions=[
        _pos("United States of America", notes="Tesouro US - Vencimento: 16/08/2034"),
        _pos("United States of America", notes="Tesouro US - Vencimento: 15/11/2034"),
        _pos("United States of America", notes="Tesouro US - Vencimento: 15/08/2029"),
        _pos("AAPL"),  # untouched
    ])
    _disambiguate_duplicate_tickers(out)
    tickers = [p.ticker_raw for p in out.positions]
    assert tickers[0] == "United States of America 2034-08-16"
    assert tickers[1] == "United States of America 2034-11-15"
    assert tickers[2] == "United States of America 2029-08-15"
    assert tickers[3] == "AAPL"
    # All unique.
    assert len(set(tickers)) == len(tickers)


def test_disambiguate_duplicate_with_no_notes_left_as_is():
    """If we can't mine a date, leave ticker_raw alone — better one orphan
    than a misleading rename."""
    out = BrokerPositionOutput(positions=[
        _pos("Mystery Bond", notes=None),
        _pos("Mystery Bond", notes=None),
    ])
    _disambiguate_duplicate_tickers(out)
    # Both still equal — downstream marks one as orphan, but we didn't lie.
    assert [p.ticker_raw for p in out.positions] == ["Mystery Bond", "Mystery Bond"]


def test_disambiguate_collision_with_existing_ticker_appends_suffix():
    """If suffixed value collides with an already-unique ticker_raw, add #N."""
    out = BrokerPositionOutput(positions=[
        _pos("US Treasury 2034-08-16"),  # already exists, unique
        _pos("US Treasury", notes="Vencimento 16/08/2034"),  # dup of nothing yet
        _pos("US Treasury", notes="Vencimento 15/11/2034"),
    ])
    _disambiguate_duplicate_tickers(out)
    # First untouched (no dup of 'US Treasury 2034-08-16' anywhere).
    assert out.positions[0].ticker_raw == "US Treasury 2034-08-16"
    # Second would become 'US Treasury 2034-08-16' → collides → '#2'.
    assert out.positions[1].ticker_raw == "US Treasury 2034-08-16 #2"
    assert out.positions[2].ticker_raw == "US Treasury 2034-11-15"


def test_disambiguate_empty_positions_noop():
    out = BrokerPositionOutput(positions=[])
    _disambiguate_duplicate_tickers(out)
    assert out.positions == []


def test_disambiguate_handles_non_position_output_safely():
    """Other output models (ScreenshotPriceOutput, etc.) have no
    `positions` attribute — function must noop gracefully."""
    class FakeOutput:
        pass
    _disambiguate_duplicate_tickers(FakeOutput())  # must not raise


# ── _extract_dates ──────────────────────────────────────────────────────────


def test_extract_dates_iso():
    assert _extract_dates("US Treasury 2034-05-16") == {"2034-05-16"}


def test_extract_dates_dmy_4digit():
    assert _extract_dates("Vencimento 16/05/2034") == {"2034-05-16"}


def test_extract_dates_dmy_2digit_unambiguous():
    """DD/MM/YY where one interpretation is invalid (MM > 12) returns
    only the valid one."""
    # 14/09/33 — MM=14 invalid → only DD/MM → 2033-09-14
    assert _extract_dates("JPM 5.717 14/09/33") == {"2033-09-14"}
    # 31/08/30 — MM=31 invalid → only DD/MM → 2030-08-31
    assert _extract_dates("T 3.625 31/08/30") == {"2030-08-31"}


def test_extract_dates_dmy_2digit_ambiguous_returns_both():
    """When both DD/MM and MM/DD are valid, return both interpretations."""
    # 11/04/29 — DD=11 MM=04 → 2029-04-11; MM=11 DD=04 → 2029-11-04
    assert _extract_dates("MOVIBZ 7.85 11/04/29") == {
        "2029-04-11", "2029-11-04",
    }


def test_extract_dates_us_format_2digit():
    """MM/DD/YY where DD > 12 (DD/MM interpretation invalid) returns only
    MM/DD interpretation."""
    # 02/15/34 — DD/MM: DD=02 MM=15 invalid; MM/DD: MM=02 DD=15 → 2034-02-15
    assert _extract_dates("T 4 02/15/34") == {"2034-02-15"}


def test_extract_dates_year_pivot():
    """YY < 70 → 20YY, YY >= 70 → 19YY."""
    assert "1995-06-15" in _extract_dates("Old bond 15/06/95")
    assert "2025-06-15" in _extract_dates("New bond 15/06/25")


def test_extract_dates_none_input():
    assert _extract_dates(None) == set()
    assert _extract_dates("") == set()


def test_extract_dates_no_date():
    assert _extract_dates("AAPL") == set()
    assert _extract_dates("Just a string") == set()


def test_extract_dates_multiple():
    """A string with two dates returns both."""
    out = _extract_dates("Issued 2023-01-15 matures 2034-05-16")
    assert out == {"2023-01-15", "2034-05-16"}


def test_extract_dates_iso_does_not_collide_with_dmy_2digit():
    """ISO '2034-05-16' must not be misread as DD/MM/YY '34-05-16' due to
    word-boundary lookahead/lookbehind."""
    assert _extract_dates("2034-05-16") == {"2034-05-16"}


# ── template_for: per-FI routing (Spec 58 Stage 3) ──────────────────────────


def test_template_for_avenue_returns_avenue_template():
    from numis_geek.services.extraction_templates import (
        BROKER_POSITION,
        BROKER_POSITION_AVENUE,
        template_for,
    )
    from numis_geek.models.extraction_job import ExtractionSourceHint

    t = template_for(
        ExtractionSourceHint.BROKER_POSITION,
        institution_short_name="Avenue",
    )
    assert t is BROKER_POSITION_AVENUE
    assert t.version.startswith("avenue-")
    # Generic fallback still works.
    assert template_for(ExtractionSourceHint.BROKER_POSITION) is BROKER_POSITION


def test_template_for_avenue_case_insensitive():
    from numis_geek.services.extraction_templates import (
        BROKER_POSITION_AVENUE,
        template_for,
    )
    from numis_geek.models.extraction_job import ExtractionSourceHint

    for variant in ("avenue", "AVENUE", " Avenue "):
        assert template_for(
            ExtractionSourceHint.BROKER_POSITION,
            institution_short_name=variant,
        ) is BROKER_POSITION_AVENUE


def test_template_for_unknown_fi_falls_back_to_generic():
    from numis_geek.services.extraction_templates import (
        BROKER_POSITION,
        template_for,
    )
    from numis_geek.models.extraction_job import ExtractionSourceHint

    t = template_for(
        ExtractionSourceHint.BROKER_POSITION,
        institution_short_name="UnknownBroker",
    )
    assert t is BROKER_POSITION  # generic, not Avenue


def test_template_for_generic_hint_with_fi_routes_to_fi_template():
    """GENERIC hint is the V1 fallback for unknown documents — even so,
    if we know the FI, use the FI-specific template."""
    from numis_geek.services.extraction_templates import (
        BROKER_POSITION_AVENUE,
        template_for,
    )
    from numis_geek.models.extraction_job import ExtractionSourceHint

    assert template_for(
        ExtractionSourceHint.GENERIC,
        institution_short_name="Avenue",
    ) is BROKER_POSITION_AVENUE
