"""Spec 23 — Coinbase adapter unit tests."""
from decimal import Decimal
from unittest.mock import MagicMock, patch

import httpx
import pytest

from numis_geek.integrations.coinbase import CoinbaseError, fetch_spot


def _mock_response(payload, status_code=200):
    r = MagicMock(spec=httpx.Response)
    r.json.return_value = payload
    r.raise_for_status.return_value = None
    r.status_code = status_code
    return r


def test_fetch_spot_ok():
    with patch("numis_geek.integrations.coinbase.httpx.get") as g:
        g.return_value = _mock_response(
            {"data": {"amount": "67100.42", "base": "BTC", "currency": "USD"}}
        )
        q = fetch_spot("BTC")
    assert q.symbol == "BTC"
    assert q.price == Decimal("67100.42")
    assert q.currency == "USD"


def test_fetch_spot_lowercases_pair_via_upper():
    with patch("numis_geek.integrations.coinbase.httpx.get") as g:
        g.return_value = _mock_response(
            {"data": {"amount": "3500.00", "base": "ETH", "currency": "USD"}}
        )
        fetch_spot("eth")
        args, kwargs = g.call_args
        assert "ETH-USD" in args[0]


def test_fetch_spot_http_error_wraps_to_coinbase_error():
    with patch("numis_geek.integrations.coinbase.httpx.get") as g:
        g.side_effect = httpx.ConnectError("network down")
        with pytest.raises(CoinbaseError, match="coinbase BTC-USD failed"):
            fetch_spot("BTC")


def test_fetch_spot_unexpected_payload():
    with patch("numis_geek.integrations.coinbase.httpx.get") as g:
        g.return_value = _mock_response({"unexpected": True})
        with pytest.raises(CoinbaseError, match="unexpected payload"):
            fetch_spot("BTC")


def test_fetch_spot_bad_amount():
    with patch("numis_geek.integrations.coinbase.httpx.get") as g:
        g.return_value = _mock_response(
            {"data": {"amount": "not-a-number", "base": "BTC", "currency": "USD"}}
        )
        with pytest.raises(CoinbaseError, match="bad amount"):
            fetch_spot("BTC")
