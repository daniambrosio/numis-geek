"""Spec 61b — Valuation pure-fn calculator tests.

Bazin, Graham, Lynch PEG. Plus the per-class orchestrators with synthetic
fixtures (no DB needed for the calculator tests).
"""
from decimal import Decimal

import pytest

from numis_geek.services.valuation import (
    bazin_ceiling, graham_intrinsic, lynch_peg, required_yield_for,
)


# ── Bazin ────────────────────────────────────────────────────────────────────


def test_bazin_happy_brl():
    # DPS=10 / 8% = 125
    out = bazin_ceiling(Decimal("10"), Decimal("0.08"))
    assert out == Decimal("125")


def test_bazin_happy_usd():
    # DPS=5 / 5% = 100
    out = bazin_ceiling(Decimal("5"), Decimal("0.05"))
    assert out == Decimal("100")


def test_bazin_zero_dps_returns_none():
    assert bazin_ceiling(Decimal("0"), Decimal("0.08")) is None


def test_bazin_negative_dps_returns_none():
    assert bazin_ceiling(Decimal("-1"), Decimal("0.08")) is None


def test_bazin_zero_yield_returns_none():
    assert bazin_ceiling(Decimal("10"), Decimal("0")) is None


def test_bazin_none_dps_returns_none():
    assert bazin_ceiling(None, Decimal("0.08")) is None


# ── Graham ───────────────────────────────────────────────────────────────────


def test_graham_happy():
    # √(22.5 × 4 × 10) = √900 = 30
    out = graham_intrinsic(Decimal("4"), Decimal("10"))
    assert out is not None and abs(out - Decimal("30")) < Decimal("0.001")


def test_graham_zero_eps_returns_none():
    assert graham_intrinsic(Decimal("0"), Decimal("10")) is None


def test_graham_negative_eps_returns_none():
    assert graham_intrinsic(Decimal("-1"), Decimal("10")) is None


def test_graham_none_returns_none():
    assert graham_intrinsic(None, Decimal("10")) is None
    assert graham_intrinsic(Decimal("4"), None) is None


# ── Lynch PEG ────────────────────────────────────────────────────────────────


def test_peg_happy():
    # P/E=20, growth=10% (0.10) → 20 / 10 = 2.0
    out = lynch_peg(Decimal("20"), Decimal("0.10"))
    assert out == Decimal("2")


def test_peg_zero_growth_returns_none():
    assert lynch_peg(Decimal("20"), Decimal("0")) is None


def test_peg_negative_growth_returns_none():
    assert lynch_peg(Decimal("20"), Decimal("-0.05")) is None


def test_peg_none_returns_none():
    assert lynch_peg(None, Decimal("0.10")) is None
    assert lynch_peg(Decimal("20"), None) is None


# ── Required yield resolution ────────────────────────────────────────────────


def test_required_yield_brl():
    assert required_yield_for("BRL") == Decimal("0.08")


def test_required_yield_usd():
    assert required_yield_for("USD") == Decimal("0.05")


def test_required_yield_default_brl():
    # Anything unknown defaults to BRL
    assert required_yield_for("XYZ") == Decimal("0.08")
