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
    version="v3",
    system=(
        "Você é um extrator de extratos de posição de corretora (PDF/imagem/CSV). "
        "Extraia CADA linha visível como uma posição JSON — inclusive fundos, "
        "renda fixa, tesouro, ETFs, cripto, bonds, debêntures. NUNCA pule uma "
        "linha só porque não tem ticker de bolsa.\n\n"
        "REGRA DE OURO pra `ticker_raw` (campo obrigatório):\n"
        "**Duas posições NUNCA podem ter o mesmo `ticker_raw`.** Se você ia "
        "repetir, adicione vencimento, cupom, ISIN ou qualquer identificador "
        "visível que torne o valor único. Repetição = falha de extração.\n\n"
        "Convenções por tipo de ativo:\n"
        "- Ações/FIIs/ETFs com ticker visível (PETR4, BTLG11, IVVB11): "
        "ticker exato\n"
        "- US (NASDAQ/NYSE): ticker puro (AAPL, MSFT, VOO)\n"
        "- Fundos sem ticker (ex.: 'Fundo Verde BTG'): NOME completo visível\n"
        "- Tesouro Direto BR: denominação + ano (ex.: 'Tesouro IPCA+ 2029')\n"
        "- US Treasury (T-Bills/T-Notes/T-Bonds): 'US Treasury' + vencimento "
        "ISO (ex.: 'US Treasury 2034-08-16'). NÃO use só 'United States of "
        "America' — sempre inclua o vencimento.\n"
        "- Bonds corporativos US: emissor + vencimento ISO (ex.: 'JPMorgan "
        "Chase 2033-09-14'). NÃO use só o nome da empresa.\n"
        "- Debêntures BR: emissor + vencimento ISO (ex.: 'Marcopolo "
        "2029-04-17')\n"
        "- CDB/LCI/LCA: emissor + vencimento (ex.: 'CDB Itaú 2027-05-10')\n"
        "Use `ticker_normalized` SOMENTE quando houver uma forma canônica "
        "de bolsa; deixe null pra fundos, renda fixa, treasuries e bonds.\n\n"
        "Responda SOMENTE com um objeto JSON validando o schema:\n"
        '{ "as_of_date": str|null (YYYY-MM-DD), "broker_name": str|null, '
        '"positions": [{ "ticker_raw": str, "ticker_normalized": str|null, '
        '"quantity": float, "unit_price": float, "currency": "BRL"|"USD", '
        '"market_value": float|null, "confidence": float (0..1), '
        '"notes": str|null }], '
        '"summary_total_brl": float|null, "summary_total_usd": float|null }'
    ),
    user_prefix=(
        "Extraia TODAS as posições visíveis neste extrato (até as que não "
        "têm ticker de bolsa — use o nome/emissor+vencimento). Lembre: dois "
        "ticker_raw não podem ser iguais. Não invente; se uma coluna "
        "estiver ilegível deixe null e diminua a confidence."
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


# ── Spec 58 Stage 3 — per-FI BROKER_POSITION templates ─────────────────────


BROKER_POSITION_AVENUE = Template(
    version="avenue-v1",
    system=(
        "Você extrai posições de extratos da corretora Avenue (Brasil, "
        "investimentos no exterior). MOEDA padrão: USD para todos os "
        "ativos, salvo indicação explícita de BRL.\n\n"
        "Tipos de ativo TÍPICOS no extrato da Avenue:\n"
        "1. AÇÕES e ETFs (NASDAQ/NYSE): ticker puro (AAPL, MSFT, VOO, GLD).\n"
        "2. FUNDOS MONEY MARKET (MMF): nome completo do fundo (ex.: "
        "'Franklin U.S. Dollar S/T MMF A(acc)USD'). Use o NOME COMPLETO "
        "como ticker_raw, preservando pontuação visível.\n"
        "3. TREASURIES US (T-Bills, T-Notes, T-Bonds): identifique pela "
        "menção a 'United States of America', 'US Treasury', 'T-Bills', "
        "'T-Notes', etc. SEMPRE componha `ticker_raw` como "
        "'US Treasury YYYY-MM-DD' usando o vencimento ISO. Inclua a taxa "
        "de cupom no `notes` (ex.: 'cupom 3.625%'). NUNCA emita só "
        "'United States of America' como ticker_raw — vencimento é "
        "obrigatório pra desambiguar.\n"
        "4. BONDS CORPORATIVOS US: formato '<Emissor> YYYY-MM-DD' (ex.: "
        "'JPMorgan Chase 2033-09-14'). Inclua cupom no notes.\n"
        "5. SALDO EM CONTA / CASH: emita uma posição com "
        "ticker_raw='Avenue Cash USD' (ou similar), unit_price=valor do "
        "saldo, quantity=1, currency=USD.\n\n"
        "REGRA DE OURO: dois `ticker_raw` NUNCA podem ser iguais. Use o "
        "vencimento, cupom ou identificador único disponível na linha pra "
        "desambiguar. Repetição = falha de extração.\n\n"
        "Pra `unit_price`: use o preço POR UNIDADE do extrato. Pra bonds "
        "isso é o preço cotado (% face value, ex.: 105.11). Pra ações é o "
        "preço da ação. Pra MMFs é o NAV (geralmente ~$1).\n\n"
        "Pra `quantity`: número de unidades/lotes do extrato. Pra bonds "
        "Avenue mostra qty em milhares de face value — use o número exato "
        "do extrato sem converter.\n\n"
        "Pra `market_value`: total de mercado em USD da linha.\n\n"
        "Use `ticker_normalized` SOMENTE pra ações/ETFs com ticker "
        "canônico (AAPL, MSFT). Deixe null pra MMFs, treasuries, bonds, "
        "cash.\n\n"
        "Responda SOMENTE com um objeto JSON validando o schema:\n"
        '{ "as_of_date": str|null (YYYY-MM-DD), "broker_name": str|null, '
        '"positions": [{ "ticker_raw": str, "ticker_normalized": str|null, '
        '"quantity": float, "unit_price": float, "currency": "BRL"|"USD", '
        '"market_value": float|null, "confidence": float (0..1), '
        '"notes": str|null }], '
        '"summary_total_brl": float|null, "summary_total_usd": float|null }'
    ),
    user_prefix=(
        "Extraia TODAS as posições visíveis neste extrato da Avenue. "
        "Inclua saldo em conta como linha separada se aparecer. Lembre: "
        "dois ticker_raw não podem ser iguais — use vencimento pra "
        "diferenciar treasuries/bonds. Não invente; se uma coluna estiver "
        "ilegível deixe null e diminua a confidence."
    ),
    output_model=BrokerPositionOutput,
)


# Per-FI BROKER_POSITION overrides. Key is normalized FI short_name
# (lowercase). When no per-FI template exists, fall back to the
# generic BROKER_POSITION.
_BROKER_POSITION_BY_FI: dict[str, Template] = {
    "avenue": BROKER_POSITION_AVENUE,
}


TEMPLATES: dict[ExtractionSourceHint, Template] = {
    ExtractionSourceHint.SCREENSHOT_PRICE: SCREENSHOT_PRICE,
    ExtractionSourceHint.BROKER_POSITION: BROKER_POSITION,
    ExtractionSourceHint.BROKER_INCOME: BROKER_INCOME,
    ExtractionSourceHint.B3_TRADE_NOTE: B3_TRADE_NOTE,
    ExtractionSourceHint.FGTS_BALANCE: FGTS_BALANCE,
}


def template_for(
    hint: ExtractionSourceHint,
    *,
    institution_short_name: str | None = None,
) -> Template:
    """Pick the template for an extraction job.

    Spec 58 Stage 3 — when both `hint == BROKER_POSITION` AND
    `institution_short_name` matches a known FI, use the FI-specific
    template. Otherwise fall back to the generic one.
    """
    if hint in (ExtractionSourceHint.BROKER_POSITION, ExtractionSourceHint.GENERIC):
        if institution_short_name:
            specific = _BROKER_POSITION_BY_FI.get(institution_short_name.strip().lower())
            if specific is not None:
                return specific
        if hint == ExtractionSourceHint.GENERIC:
            # V1 fallback: treat unknown documents as BROKER_POSITION.
            return BROKER_POSITION
    return TEMPLATES[hint]
