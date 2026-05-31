"""Spec 38 — prompts + expected schemas per `ExtractionSourceHint`.

Each hint has:
- A `system` prompt explaining the task.
- A `user_prefix` rendered before the user-uploaded content/text.
- A pydantic schema (`OutputModel`) validating the LLM's JSON reply.

V1 ships templates for SCREENSHOT_PRICE and BROKER_POSITION; other hints
(BROKER_INCOME, B3_TRADE_NOTE, FGTS_BALANCE) are scaffolded with
placeholder prompts and TODO markers — the service routes to them but
they need real prompts before going to production.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Type

from pydantic import BaseModel

from numis_geek.models.extraction_job import ExtractionSourceHint


# ── per-hint output models ───────────────────────────────────────────────────

class ScreenshotPriceOutput(BaseModel):
    """SCREENSHOT_PRICE — a single ticker + price snap from a broker app."""
    ticker: str | None = None
    price: float
    currency: str = "BRL"
    as_of_timestamp: str | None = None
    source_app: str | None = None
    confidence: float


class BrokerPosition(BaseModel):
    # ticker_raw is the only field we truly require — the rest may come back
    # null when the LLM is uncertain about a row (Spec 48 follow-up). The
    # apply step filters rows missing quantity OR unit_price before touching
    # the DB, so accepting null here just prevents pydantic from failing the
    # whole extract over a few empty hallucinations.
    ticker_raw: str
    ticker_normalized: str | None = None
    quantity: float | None = None
    unit_price: float | None = None
    currency: str = "BRL"
    market_value: float | None = None
    confidence: float = 0.0
    notes: str | None = None


class BrokerPositionOutput(BaseModel):
    as_of_date: str | None = None
    broker_name: str | None = None
    positions: list[BrokerPosition]
    summary_total_brl: float | None = None
    summary_total_usd: float | None = None


# ── template registry ────────────────────────────────────────────────────────

@dataclass
class Template:
    version: str
    system: str
    user_prefix: str
    output_model: Type[BaseModel]


SCREENSHOT_PRICE = Template(
    version="v1",
    system=(
        "Você é um extrator de cotações de ativos a partir de screenshots "
        "de apps de broker ou painéis de cotação. O usuário vai te enviar "
        "uma imagem (1 ticker apenas) e você responde com JSON estrito. "
        "Se não conseguir identificar o ticker, deixe `ticker` como null e "
        "ponha `confidence` < 0.5. NUNCA invente valor.\n\n"
        "Responda SOMENTE com um objeto JSON que valide este schema:\n"
        '{ "ticker": str|null, "price": float, "currency": "BRL"|"USD", '
        '"as_of_timestamp": str|null (ISO 8601), '
        '"source_app": str|null, "confidence": float (0..1) }'
    ),
    user_prefix=(
        "Extraia o ticker e o preço atual deste screenshot. Use ticker B3 "
        "canônico (PETR4, ITUB4, BBSE3...) para ativos brasileiros e "
        "ticker NASDAQ/NYSE puro (AAPL, MSFT) para US."
    ),
    output_model=ScreenshotPriceOutput,
)


BROKER_POSITION = Template(
    version="v1",
    system=(
        "Você é um extrator de extratos de posição de corretora (PDF/imagem/CSV). "
        "Extraia cada posição como uma linha JSON. Use ticker B3 canônico "
        "(PETR4, ITUB4, BBSE3, FIIs com sufixo 11) e para ativos US use ticker "
        "NASDAQ/NYSE puro (AAPL, MSFT). Se não conseguir identificar o ticker, "
        "deixe `ticker_normalized` como null e ponha confidence baixa.\n\n"
        "Responda SOMENTE com um objeto JSON validando o schema:\n"
        '{ "as_of_date": str|null (YYYY-MM-DD), "broker_name": str|null, '
        '"positions": [{ "ticker_raw": str, "ticker_normalized": str|null, '
        '"quantity": float, "unit_price": float, "currency": "BRL"|"USD", '
        '"market_value": float|null, "confidence": float (0..1), '
        '"notes": str|null }], '
        '"summary_total_brl": float|null, "summary_total_usd": float|null }'
    ),
    user_prefix=(
        "Extraia todas as posições deste extrato. Não invente valores; se "
        "uma coluna estiver ilegível, deixe a célula como null e diminua a "
        "confidence da linha."
    ),
    output_model=BrokerPositionOutput,
)


# Placeholder templates — schema defined, prompt TODO before production.

class BrokerIncomeEvent(BaseModel):
    event_date: str
    ticker_raw: str
    ticker_normalized: str | None = None
    type: str
    gross_amount: float
    tax_amount: float | None = None
    net_amount: float | None = None
    currency: str = "BRL"
    notes: str | None = None
    confidence: float


class BrokerIncomeOutput(BaseModel):
    as_of_date: str | None = None
    broker_name: str | None = None
    events: list[BrokerIncomeEvent]


BROKER_INCOME = Template(
    version="v0-draft",
    system="TODO Spec 38 — produção exige prompt validado vs amostras reais.",
    user_prefix="Extraia os eventos de provento deste extrato.",
    output_model=BrokerIncomeOutput,
)


class B3Trade(BaseModel):
    ticker: str
    side: str
    quantity: float
    unit_price: float
    fees: float | None = None
    total: float | None = None
    confidence: float


class B3TradeNoteOutput(BaseModel):
    trade_date: str | None = None
    settlement_date: str | None = None
    broker_name: str | None = None
    trades: list[B3Trade]


B3_TRADE_NOTE = Template(
    version="v0-draft",
    system="TODO Spec 38 — produção exige prompt validado vs amostras reais.",
    user_prefix="Extraia as ordens da nota de corretagem.",
    output_model=B3TradeNoteOutput,
)


class FGTSBalanceOutput(BaseModel):
    as_of_date: str | None = None
    account_owner: str | None = None
    balance_brl: float
    monthly_yield: float | None = None
    confidence: float


FGTS_BALANCE = Template(
    version="v0-draft",
    system=(
        "Extrator de saldo FGTS. Responda SOMENTE com JSON: "
        '{ "as_of_date": str|null, "account_owner": str|null, '
        '"balance_brl": float, "monthly_yield": float|null, '
        '"confidence": float }'
    ),
    user_prefix="Extraia o saldo atual da conta FGTS deste documento.",
    output_model=FGTSBalanceOutput,
)


TEMPLATES: dict[ExtractionSourceHint, Template] = {
    ExtractionSourceHint.SCREENSHOT_PRICE: SCREENSHOT_PRICE,
    ExtractionSourceHint.BROKER_POSITION: BROKER_POSITION,
    ExtractionSourceHint.BROKER_INCOME: BROKER_INCOME,
    ExtractionSourceHint.B3_TRADE_NOTE: B3_TRADE_NOTE,
    ExtractionSourceHint.FGTS_BALANCE: FGTS_BALANCE,
}


def template_for(hint: ExtractionSourceHint) -> Template:
    if hint == ExtractionSourceHint.GENERIC:
        # V1 fallback: treat unknown documents as BROKER_POSITION (most common
        # snapshot pendency upload). The reply schema validation will catch
        # mismatches.
        return BROKER_POSITION
    return TEMPLATES[hint]
