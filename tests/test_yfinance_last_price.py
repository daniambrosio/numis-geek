"""fetch_last_price — cotação atual via yfinance (fallback do Finnhub)."""
from decimal import Decimal
from unittest.mock import MagicMock, patch

import numis_geek.integrations.yfinance as y


def _with_fast_info(value):
    fi = MagicMock()
    fi.get.return_value = value
    yf = MagicMock()
    yf.Ticker.return_value.fast_info = fi
    return patch.object(y, "yf", yf)


def test_last_price_rounds_float32_noise():
    with _with_fast_info(121.91999816894531):
        assert y.fetch_last_price("IB01.L") == Decimal("121.9200")


def test_last_price_none_when_missing_or_zero():
    with _with_fast_info(None):
        assert y.fetch_last_price("XPTO.L") is None
    with _with_fast_info(0.0):
        assert y.fetch_last_price("XPTO.L") is None
