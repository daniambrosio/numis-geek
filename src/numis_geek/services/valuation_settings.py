"""Hardcoded constants for Spec 61b valuation engine.

When Spec 61.5 introduces workspace-level Valuation Settings (override
per workspace + per-asset overrides), this module becomes a thin
read-through cache. Keeping these as module-level constants means we
have a single place to bump defaults without touching pricing logic.
"""
from __future__ import annotations

from decimal import Decimal

# Required yield (Bazin "preço-teto" rate) by currency. Used as the
# divisor when computing Bazin ceiling and as the threshold for
# DY-based verdict gates.
REQUIRED_YIELD_BRL = Decimal("0.08")
REQUIRED_YIELD_USD = Decimal("0.05")

# Stale threshold — fundamentals older than this trigger a warning pill
# on the UI but DO NOT prevent the verdict from being computed.
FUNDAMENTALS_FRESH_DAYS = 30
FUNDAMENTALS_STALE_DAYS = 90

# STOCK disqualifying gates — any of these blocks "Comprar".
GATE_ROE_MIN = Decimal("0")               # ROE ≥ 0 (no losses)
GATE_DEBT_EBITDA_MAX = Decimal("5")       # Dívida / EBITDA ≤ 5
GATE_EARNINGS_GROWTH_MIN = Decimal("0")   # 5y earnings growth ≥ 0

# STOCK verdict thresholds
GRAHAM_BUY_MULTIPLIER = Decimal("1.2")    # Preço < Graham × 1.2 → barato
GRAHAM_SELL_MULTIPLIER = Decimal("1.5")   # Preço > Graham × 1.5 → caro
SELL_DY_RATIO = Decimal("0.5")            # DY < 50% required yield → caro

# REIT verdict thresholds
REIT_PVP_BUY_MAX = Decimal("0.95")
REIT_PVP_SELL_MIN = Decimal("1.2")
REIT_DY_BUY_RATIO = Decimal("1.2")        # DY > 1.2× required yield → atrativo
REIT_DY_SELL_RATIO = Decimal("0.7")
REIT_VACANCY_MAX = Decimal("0.20")        # vacância > 20% bloqueia BUY
REIT_DIST_COVERAGE_MIN = Decimal("1.0")   # cobertura < 1 bloqueia BUY (US)

# ETF informational thresholds
ETF_EXPENSE_RATIO_GOOD = Decimal("0.005")
ETF_AUM_GOOD = Decimal("1000000000")
