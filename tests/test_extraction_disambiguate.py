"""Spec 57 — defensive disambiguator for duplicate ticker_raw in LLM output.

Pure unit tests (no DB) for `_disambiguate_duplicate_tickers` and the
`_maturity_from_notes` helper. The integration path (LLM call →
disambiguate → persist) is covered by existing extraction tests using
the FakeLLM fixture.
"""
from __future__ import annotations

from numis_geek.services.extraction import (
    _disambiguate_duplicate_tickers,
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
