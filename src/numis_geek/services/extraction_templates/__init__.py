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
    # Seção do extrato onde a linha aparece ("ETFs", "Renda fixa"...). Casa
    # com `section_totals` pra checar integridade (bug Avenue 2026-11-02).
    section: str | None = None


class SectionTotal(BaseModel):
    section: str
    market_value: float
    currency: str | None = None


class BrokerPositionOutput(BaseModel):
    as_of_date: str | None = None
    broker_name: str | None = None
    positions: list[BrokerPosition]
    summary_total_brl: float | None = None
    summary_total_usd: float | None = None
    # Total que o PRÓPRIO extrato mostra no cabeçalho de cada seção. A soma
    # das linhas extraídas tem que bater — se não bate, faltou ou foi
    # inventada linha (ver extraction._integrity_issues).
    section_totals: list[SectionTotal] | None = None


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
    # v5 (2026-11-02): section + section_totals pra checagem de integridade
    # (extraction._integrity_issues) — antes só o template da Avenue pedia.
    version="v5",
    system=(
        "Você é um extrator de extratos de posição de corretora (PDF/imagem/CSV). "
        "Extraia CADA linha visível como uma posição JSON — inclusive fundos, "
        "renda fixa, tesouro, ETFs, cripto, bonds, debêntures. NUNCA pule uma "
        "linha só porque não tem ticker de bolsa.\n\n"
        "REGRA DE OURO pra `ticker_raw` (campo obrigatório):\n"
        "**Duas posições NUNCA podem ter o mesmo `ticker_raw`.** Se você ia "
        "repetir, adicione vencimento, cupom, ISIN ou qualquer identificador "
        "visível que torne o valor único. Repetição = falha de extração.\n\n"
        "REGRA DE OURO pra números (v4 — 2026-07-04, adicionado depois de "
        "erros sistemáticos com Avenue onde qty × unit_price ≠ market_value "
        "por 10-50%):\n"
        "1. Extratos costumam ter VÁRIAS colunas de dinheiro por linha: "
        "custo médio, preço atual, valor de mercado, variação do dia, "
        "ganho/perda. Você DEVE ler o header pra identificar cada coluna "
        "e pegar SÓ os valores corretos.\n"
        "2. **`unit_price`** = preço ATUAL / preço de fechamento / cotação "
        "de mercado. Rótulos comuns: 'Price', 'Last Price', 'Cotação', "
        "'Preço atual', 'Preço unit'. NÃO é 'Average Cost', 'Custo médio', "
        "'PM', 'Cost Basis' — esses são custo histórico e vão pro campo "
        "notes se relevante.\n"
        "3. **`market_value`** = coluna 'Market Value', 'Valor de mercado', "
        "'Total', 'Valor total'. NÃO é 'Total Cost', 'Unrealized Gain'.\n"
        "4. **INVARIANTE OBRIGATÓRIO**: `quantity × unit_price ≈ market_value` "
        "(dentro de 1%). Se você extraiu os três e a conta não bate, "
        "provavelmente pegou uma coluna errada — **releia** e corrija. Se "
        "mesmo assim não conseguir alinhar, baixe `confidence` pra ≤ 0.5 "
        "e explique em `notes` (ex.: 'divergência qty×price vs mv: "
        "confira coluna de custo médio').\n"
        "5. Pra Treasuries US e bonds cotados como % do valor de face: "
        "`quantity` = valor de face em USD (ex.: 10000), `unit_price` = "
        "preço percentual (ex.: 99.943), `market_value` = qty × price / 100. "
        "Confira que a conta bate.\n"
        "6. Confidence honesta: 0.95+ SÓ quando os 3 números batem "
        "matematicamente. Se você tem que chutar unit_price ou o header "
        "está ambíguo, cai pra 0.7-0.85. Confidence de 0.95 num extrato "
        "que a conta erra 50% é falha grave de extração.\n\n"
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
        "SEÇÕES E TOTAIS (checagem de integridade):\n"
        "- Preencha `section` de cada posição com o título do grupo de TOPO "
        "onde ela aparece — o bloco que tem o total ('Saldo') no cabeçalho "
        "(ex.: 'Ações', 'Fundos Imobiliários', 'Renda Fixa', 'Tesouro "
        "Direto', 'Previdência Privada'). Subgrupos dentro dele (ex.: na XP, "
        "'Renda Variável Brasil', 'Pós-Fixado', 'Alternativos' dentro de "
        "'Ações') NÃO são seções: as linhas deles levam o nome do grupo de "
        "topo. Sem agrupamento visível → null.\n"
        "- Blocos que não são posição (ex.: 'Proventos' provisionados, "
        "'Custódia Remunerada' — ações emprestadas já listadas em Ações —, "
        "histórico de movimentações) não geram posições nem totais.\n"
        "- SALDO EM CONTA / caixa disponível É posição: emita uma linha "
        "'Saldo em conta <MOEDA>' (ex.: 'Saldo em conta USD') com "
        "quantity=1, unit_price=market_value=saldo, uma por moeda com "
        "saldo.\n"
        "- EXCEÇÃO à regra 'cada linha é uma posição' — PREVIDÊNCIA: um "
        "plano é UMA posição, mesmo que o extrato o quebre em várias "
        "contas (ex.: bloco 'Saldo do Período Final' com linhas 'BASICA "
        "PARTICIPANTE', 'NORMAL PATROCINADORA', 'AUTOPATROCINIO…' e uma "
        "linha TOTAL). Emita UMA posição: ticker_raw = nome do plano (ex.: "
        "'FOLHAPREV'), quantity=1, unit_price=market_value= o TOTAL do "
        "saldo final; as contas vão em notes. Ignore o histórico de "
        "contribuições/rentabilidade.\n"
        "- Em `section_totals`, liste SÓ os totais que o extrato MOSTRA "
        "escritos no cabeçalho ou rodapé de cada seção — copie o número, "
        "NUNCA some você mesmo. Seção sem total impresso → não inclua. Use "
        "exatamente o mesmo texto de `section` das posições. Se o total da "
        "seção inclui algo que não é linha de posição (ex.: provisões, "
        "juros a receber, saldo), NÃO inclua essa seção.\n"
        "- Se o documento não tem seções com total, devolva "
        "`section_totals: []`.\n\n"
        "Responda SOMENTE com um objeto JSON validando o schema:\n"
        '{ "as_of_date": str|null (YYYY-MM-DD), "broker_name": str|null, '
        '"positions": [{ "ticker_raw": str, "ticker_normalized": str|null, '
        '"quantity": float, "unit_price": float, "currency": "BRL"|"USD", '
        '"market_value": float|null, "confidence": float (0..1), '
        '"notes": str|null, "section": str|null }], '
        '"section_totals": [{ "section": str, "market_value": float, '
        '"currency": "BRL"|"USD" }], '
        '"summary_total_brl": float|null, "summary_total_usd": float|null }'
    ),
    user_prefix=(
        "Extraia TODAS as posições visíveis neste extrato (até as que não "
        "têm ticker de bolsa — use o nome/emissor+vencimento). Antes de "
        "responder, VERIFIQUE: pra cada linha, quantity × unit_price bate "
        "com market_value? Se não, releia — provavelmente confundiu com a "
        "coluna de custo médio. Lembre: dois ticker_raw não podem ser "
        "iguais; previdência com várias contas do mesmo plano = UMA linha "
        "com o saldo total; saldo em conta é linha. Não invente; se uma "
        "coluna estiver ilegível deixe null e diminua a confidence."
    ),
    output_model=BrokerPositionOutput,
)


# Placeholder templates — schema defined, prompt TODO before production.

class PaymentInKind(BaseModel):
    """Spec 66 — provento pago em cripto (Coinbase paga recompensa de USDC
    em BTC). Vira um BUY do ativo pago, pareado com o INTEREST."""
    ticker: str
    quantity: float


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
    payment_in_kind: PaymentInKind | None = None


class BrokerOptionEvent(BaseModel):
    """Linha de prêmio de venda/recompra de opção identificada no extrato
    de proventos. Roteada server-side pra AssetMovement (não Distribution).
    """
    event_date: str
    option_ticker_raw: str  # ITUBR364, PETRR300, etc.
    side: str               # "SELL_OPEN" ou "BUY_TO_CLOSE"
    quantity: float
    unit_price: float       # prêmio por opção
    gross_amount: float     # quantity × unit_price (antes de fees)
    fee: float | None = None
    net_amount: float | None = None
    currency: str = "BRL"
    notes: str | None = None
    confidence: float


class BrokerIncomeOutput(BaseModel):
    as_of_date: str | None = None
    broker_name: str | None = None
    events: list[BrokerIncomeEvent]
    # Prêmios de opção vão aqui em vez de events[] — viram AssetMovement,
    # não Distribution. Default [] mantém retro-compat com extratos sem opção.
    option_events: list[BrokerOptionEvent] = []


BROKER_INCOME = Template(
    version="broker-income-v3",
    system=(
        "Você extrai eventos de PROVENTOS de extratos de corretora "
        "(brasileiras ou exterior). Um arquivo pode conter movimentações "
        "variadas (compras, vendas, taxas administrativas, IOF de câmbio, "
        "transferências, etc.) — IGNORE TUDO QUE NÃO FOR PROVENTO.\n\n"
        "FORMATO: arquivo pode chegar como CSV, PDF, XLSX ou screenshot. "
        "Use o conteúdo, não a extensão.\n\n"
        "RESPOSTA: APENAS o objeto JSON. Sem markdown, sem ```json fence, "
        "sem texto antes ou depois. Sem 'Aqui está', sem 'Observação'. "
        "O parser falha em qualquer caractere fora do objeto JSON.\n\n"
        "O QUE CONTA COMO PROVENTO (use SOMENTE estes valores em `type`):\n"
        "- DIVIDEND — dividendo de ação/ETF/REIT. Inclua TAMBÉM rendimento "
        "mensal de FII (no BR FII paga como 'rendimento', mas mapeia pra "
        "DIVIDEND no nosso schema).\n"
        "- JCP — juros sobre capital próprio (específico BR).\n"
        "- INTEREST — juros/cupom de renda fixa, treasury, bond, CDB, "
        "debênture. Use TAMBÉM pra amortização de principal de renda fixa. "
        "Use TAMBÉM pra CRYPTO REWARDS/STAKING/YIELDS pagos por exchanges "
        "(Coinbase 'USDC rewards', Binance 'Earn', 'Staking rewards', "
        "'Learn & Earn', etc.) — mapear como INTEREST com ticker_raw = "
        "símbolo da cripto que gerou o rendimento (USDC/ETH/BTC/etc.), "
        "mesmo que o pagamento venha em outra cripto (ex.: Coinbase paga "
        "rewards de USDC em BTC — ticker_raw='USDC', mas gross_amount em "
        "BRL/USD conforme mostrado).\n"
        "- SECURITIES_LENDING — empréstimo/aluguel de ações (BTC).\n\n"
        "PAGAMENTO EM CRIPTO (payment_in_kind):\n"
        "- Quando o rendimento é creditado como QUANTIDADE de uma cripto "
        "(ex.: Coinbase 'USDC rewards  +R$ 187,72  +0.000571 BTC'), emita UM "
        "evento INTEREST com ticker_raw = cripto que GEROU o rendimento "
        "('USDC'), gross_amount/net_amount = valor em BRL/USD mostrado, e "
        "payment_in_kind = { \"ticker\": cripto recebida ('BTC'), "
        "\"quantity\": quantidade recebida (0.000571) }.\n"
        "- Vale também quando a cripto recebida é a mesma que gerou "
        "(recompensa de USDC paga em USDC → payment_in_kind.ticker='USDC').\n"
        "- Copie a quantidade com TODAS as casas decimais visíveis. Não "
        "emita um evento separado pra quantidade recebida.\n"
        "- Rendimento creditado em dinheiro (BRL/USD na conta) → "
        "payment_in_kind = null.\n\n"
        "NÃO EXTRAIR em events[] (ignore ou roteie diferente):\n"
        "- Compras/vendas de ação/ETF/FII (são trades, não proventos).\n"
        "- Taxa de custódia, taxa de administração, IOF de câmbio, "
        "tarifas bancárias, mensalidade da corretora.\n"
        "- Transferências entre contas, depósitos, saques.\n"
        "- Eventos corporativos sem cash (split, grupamento, bonificação "
        "em ações).\n\n"
        "PRÊMIOS DE OPÇÃO (vão em option_events[], NÃO em events[]):\n"
        "- Quando o extrato mostra venda/recompra de opção (PUT ou CALL) com "
        "ticker tipo PETRR300, ITUBR364, ITUBF475, WEGER408 — emita uma "
        "linha em option_events[] em vez de events[]:\n"
        "  - option_ticker_raw: o ticker exato (PETRR300, ITUBR364, …).\n"
        "  - side: SELL_OPEN se for venda pra abrir; BUY_TO_CLOSE se "
        "recompra pra fechar.\n"
        "  - quantity: número de opções (ex.: 1000).\n"
        "  - unit_price: prêmio por opção (ex.: 0.09).\n"
        "  - gross_amount: quantity × unit_price.\n"
        "  - fee: corretagem/taxa se isolada na linha; senão null.\n"
        "  - net_amount: valor líquido creditado/debitado em conta.\n"
        "  - currency: BRL ou USD.\n"
        "  - notes: copie qualquer info adicional (strike, vencimento) se "
        "aparecer.\n"
        "- Linhas sem ticker de opção claro → NÃO chute. Coloque em events[] "
        "como erro de classificação só se realmente parecer provento; "
        "caso contrário ignore.\n\n"
        "TRATAMENTO DE IMPOSTO:\n"
        "- Quando o extrato mostra IRRF/IR retido DIRETAMENTE relacionado "
        "a um provento (mesma linha ou linha-par), preencha `tax_amount` "
        "no evento correspondente. `gross_amount` = bruto antes do IR; "
        "`net_amount` = bruto - imposto.\n"
        "- Se IRRF aparece em linha separada com referência ao provento, "
        "consolide no mesmo evento (não emita um evento separado de imposto).\n\n"
        "CAMPOS POR EVENTO:\n"
        "- event_date: ISO YYYY-MM-DD da data de pagamento (não a "
        "data ex/com).\n"
        "- ticker_raw: ticker/símbolo exatamente como aparece (PETR4, "
        "AAPL, HGLG11, 'US Treasury 2034-08-15', etc.).\n"
        "- type: DIVIDEND, JCP, INTEREST ou SECURITIES_LENDING (sem variações).\n"
        "- gross_amount: valor bruto (antes do IR). Decimal positivo.\n"
        "- tax_amount: IRRF/IOF SE for retido no provento (caso contrário null).\n"
        "- net_amount: valor líquido recebido em conta (= gross - tax).\n"
        "- currency: BRL ou USD conforme a moeda do pagamento.\n"
        "- payment_in_kind: { ticker, quantity } ou null (ver acima).\n"
        "- confidence: 0–1.\n\n"
        "Se nenhum provento for encontrado, retorne `events: []`."
    ),
    user_prefix="Extraia TODOS os proventos deste extrato.",
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


# ── Spec 71 — extrato bancário e fatura de cartão (Numis) ───────────────────


class StatementPeriod(BaseModel):
    start: str | None = None
    end: str | None = None


class StatementFx(BaseModel):
    """Compra internacional: valor em USD e a cotação usada pelo emissor."""
    usd_amount: float | None = None
    rate: float | None = None


class StatementLine(BaseModel):
    event_date: str
    description: str
    # Sinal da movimentação: saída/compra NEGATIVA, entrada/estorno POSITIVA.
    amount: float
    currency: str = "BRL"
    balance_after: float | None = None
    # CARD_INVOICE apenas.
    installment: str | None = None          # "5/12"
    fx: StatementFx | None = None
    is_invoice_payment: bool = False        # "Pagamento recebido" da fatura anterior
    # Spec 71 (2026-11-02) — tipo da linha + contraparte (Pix/TED/DOC/boleto).
    line_kind: str | None = None            # PURCHASE|IOF|BANK_FEE|PIX|TED|BOLETO|SALARY|OTHER
    counterparty: str | None = None
    category_hint: str | None = None        # sugestão; aplicar é spec futura
    confidence: float | None = None
    # Spec 84 (Wise, conta multimoeda) — aditivo; null nos demais bancos.
    date_text: str | None = None            # data como impressa ("19 October", "19 October 2025")
    jar_amount: float | None = None         # valor que SAIU/ENTROU no saldo (jar) — com sinal
    jar_currency: str | None = None
    merchant_amount: float | None = None    # valor na moeda do comerciante, quando diferente
    merchant_currency: str | None = None
    multi_jar: str | None = None            # "EUR, USD": pago com mais de um saldo


class BankStatementOutput(BaseModel):
    period: StatementPeriod | None = None
    institution_name: str | None = None
    transactions: list[StatementLine]
    confidence: float | None = None
    parse_warnings: list[str] = []          # spec 84: avisos do parser/extração


class InvoiceSummary(BaseModel):
    close_date: str | None = None
    due_date: str | None = None
    total: float | None = None
    iof_total: float | None = None


class CardInvoiceOutput(BankStatementOutput):
    invoice: InvoiceSummary | None = None


_STATEMENT_COMMON = (
    "FORMATO: o arquivo pode chegar como OFX, CSV, XLSX, PDF ou screenshot. "
    "Use o conteúdo, não a extensão.\n\n"
    "RESPOSTA: APENAS o objeto JSON. Sem markdown, sem ```json fence, sem "
    "texto antes ou depois. O parser falha em qualquer caractere fora do "
    "objeto JSON.\n\n"
    "CAMPOS POR LINHA (transactions[]):\n"
    "- event_date: ISO YYYY-MM-DD.\n"
    "- description: texto da linha EXATAMENTE como aparece (não traduza, não "
    "resuma, não corrija maiúsculas). É a base da detecção de duplicatas.\n"
    "- amount: decimal COM SINAL — saída/débito/compra NEGATIVO; "
    "entrada/crédito/estorno POSITIVO.\n"
    "- currency: BRL ou USD (moeda da conta/cartão).\n"
    "- category_hint: opcional, uma palavra (Mercado, Transporte, …) ou null.\n"
    "- line_kind: tipo da linha — IOF (qualquer IOF: compra internacional, "
    "cheque especial, câmbio), BANK_FEE (tarifa, anuidade, cesta de serviços, "
    "juros/encargos/multa cobrados pelo PRÓPRIO banco/cartão), PIX (enviado "
    "ou recebido), TED (TED/DOC), BOLETO, PURCHASE (compra), SALARY, OTHER.\n"
    "- counterparty: em Pix, TED/DOC e boleto, o NOME da pessoa/empresa do "
    "outro lado (recebedor de um envio, pagador de um recebimento, "
    "beneficiário do boleto), sem prefixos (\"PIX TRANSF\", \"TED\"), sem "
    "datas e sem CPF/CNPJ. Ex.: \"PIX TRANSF JOAO S 12/03\" com detalhe "
    "\"João da Silva\" → \"João da Silva\". Só preencha se o documento "
    "mostrar; senão null. Nas demais linhas, null.\n"
    "- confidence: 0–1.\n\n"
    "period: { start, end } em ISO — o período que o documento declara "
    "cobrir (\"Extrato de 01/10 a 31/10\"). Se não declarar, use a menor "
    "e a maior data das linhas.\n\n"
    "NÃO invente linhas. Linhas de SALDO (\"Saldo anterior\", \"Saldo do "
    "dia\", \"SALDO TOTAL\") NÃO são movimentações — não emita; use o valor "
    "em balance_after da linha anterior quando fizer sentido.\n"
    "Seções de LANÇAMENTOS FUTUROS (\"lançamentos futuros\", \"saídas "
    "futuras\", \"entradas futuras\", \"agendamentos\", \"próximas "
    "faturas\") NÃO entram: são agendados que ainda não aconteceram. Emita "
    "só o que já foi lançado até a data de geração do documento.\n"
)

BANK_STATEMENT = Template(
    version="bank-statement-v3",
    system=(
        "Você extrai as MOVIMENTAÇÕES de um extrato de conta corrente "
        "(banco, fintech, conta global — Itaú, Nubank, Wise, Nomad, etc.).\n\n"
        + _STATEMENT_COMMON
        + "- balance_after: saldo após a linha, quando o extrato mostrar; senão null.\n\n"
        "Responda com: { \"period\": {\"start\": str, \"end\": str}, "
        "\"institution_name\": str|null, \"transactions\": [ {event_date, "
        "description, amount, currency, balance_after, category_hint, "
        "line_kind, counterparty, confidence} ], \"confidence\": float }"
    ),
    user_prefix="Extraia TODAS as movimentações deste extrato de conta.",
    output_model=BankStatementOutput,
)

BANK_STATEMENT_WISE = Template(
    version="bank-statement-wise-v1",
    system=(
        "Você extrai TODAS as linhas do extrato \"all transactions\" da Wise "
        "(conta multimoeda: saldos/jars em BRL, USD, EUR, GBP, CLP, UYU…, tudo "
        "numa lista só, da mais nova pra mais antiga).\n\n"
        "RESPOSTA: APENAS o objeto JSON, sem markdown nem texto fora dele.\n\n"
        "ESTRUTURA DO TEXTO: um cabeçalho de data (\"19 October\" no ano corrente, "
        "\"19 October 2025\" nos anteriores) seguido das linhas daquele dia. Cada "
        "linha tem um nome e 1 ou 2 valores. Ignore cabeçalho/rodapé da página "
        "(\"Transactions\", \"Search Filters\", \"Wise - Home\", URL, "
        "\"11/2/26, 12:02 PM\", \"Earn R$…\").\n\n"
        "POR LINHA (transactions[]):\n"
        "- date_text: o cabeçalho de data EXATAMENTE como impresso (com ou sem ano). "
        "Se o trecho começa sem cabeçalho, use o \"cabeçalho em vigor\" informado.\n"
        "- event_date: ISO; sem ano no cabeçalho → o ano corrente informado.\n"
        "- description: o nome da linha exatamente como aparece.\n"
        "- line_kind: CONVERSION (\"To EUR\" / \"To USD Jar\" + Moved/Added: troca "
        "entre jars), SPEND (compra/pagamento no cartão), DEPOSIT (entrada, ex.: nome "
        "da pessoa + valor positivo), FEE (\"Assets fee\" e tarifas), REFUND "
        "(\"Refund …\"), CASHBACK, SENT (\"Sent\": envio a terceiro).\n"
        "- jar_amount / jar_currency: o valor que SAIU do saldo (negativo) ou ENTROU "
        "(positivo, com \"+\"). Linha com 2 valores: o jar é o SEGUNDO valor "
        "(\"91.25 EUR / 103.02 USD\" → jar −103.02 USD). Linha com 1 valor: é ele.\n"
        "- merchant_amount / merchant_currency: em linha com 2 valores, o PRIMEIRO "
        "(moeda do comerciante, mesmo sinal). Senão null.\n"
        "- CONVERSION: jar = o que saiu (\"To EUR · 178.69 EUR · 200 USD\" → jar "
        "−200 USD, merchant +178.69 EUR; \"To USD · Added · +1,000 USD · 5,279.79 BRL\" "
        "→ jar −5279.79 BRL, merchant +1000 USD).\n"
        "- amount = jar_amount; currency = jar_currency.\n"
        "- counterparty: em DEPOSIT/SENT o nome da pessoa; senão null.\n"
        "- Números: \"1,000\" = mil, \"236,100 ARS\" = 236100, \"5,279.79\" = 5279.79.\n"
        "- confidence: 0–1.\n\n"
        "NÃO pule linhas: cada linha do texto com nome + valor(es) vira uma entrada.\n\n"
        "Responda com: { \"period\": {\"start\": str, \"end\": str}, "
        "\"institution_name\": \"Wise\", \"transactions\": [ {date_text, event_date, "
        "description, line_kind, amount, currency, jar_amount, jar_currency, "
        "merchant_amount, merchant_currency, counterparty, confidence} ] }"
    ),
    user_prefix="Extraia TODAS as linhas deste extrato da Wise.",
    output_model=BankStatementOutput,
)

CARD_INVOICE = Template(
    version="card-invoice-v4",
    system=(
        "Você extrai os LANÇAMENTOS de uma fatura de cartão de crédito "
        "(inclui cartões adicionais — todos na mesma lista).\n\n"
        + _STATEMENT_COMMON
        + "\nESPECÍFICO DE FATURA:\n"
        "- Compras são NEGATIVAS; estornos/créditos POSITIVOS.\n"
        "- event_date de compra parcelada: a data ORIGINAL da compra, como a "
        "fatura mostra (\"10/01 NOTEBOOK 05/12\" → event_date do dia 10/01, "
        "installment \"5/12\"). O sistema calcula o mês da parcela.\n"
        "- installment: \"X/Y\" quando a linha é parcela; senão null. Tire o "
        "\"05/12\" da description.\n"
        "- fx: compra internacional → { usd_amount, rate } (valor em USD e "
        "cotação aplicada); amount continua no valor cobrado na moeda do cartão.\n"
        "- IOF de compra internacional: linha própria (amount negativo) e some "
        "em invoice.iof_total.\n"
        "- A linha \"Pagamento recebido\" / \"Pagamento efetuado\" / "
        "\"Pagto. fatura\" (pagamento da fatura ANTERIOR) → emita com "
        "amount POSITIVO e is_invoice_payment = true. Não é estorno.\n"
        "- Não emita linhas de resumo (Total da fatura, Saldo anterior, "
        "Encargos do próximo período, Limite).\n\n"
        "invoice: { close_date, due_date, total (valor a pagar; saldo credor → "
        "negativo ou 0), iof_total|null } em ISO.\n"
        "period da fatura: o ciclo (dia seguinte ao fechamento anterior → "
        "fechamento) — NUNCA a menor data de compra parcelada.\n\n"
        "Responda com: { \"period\": {...}, \"institution_name\": str|null, "
        "\"invoice\": {...}, \"transactions\": [ {event_date, description, "
        "amount, currency, installment, fx, is_invoice_payment, category_hint, "
        "line_kind, counterparty, confidence} ], \"confidence\": float }"
    ),
    user_prefix="Extraia TODOS os lançamentos desta fatura de cartão.",
    output_model=CardInvoiceOutput,
)


# ── Spec 58 Stage 3 — per-FI BROKER_POSITION templates ─────────────────────


BROKER_POSITION_AVENUE = Template(
    # v3 (2026-11-02): fechamento Out/26 — o modelo pegou "Total investido"
    # em vez de "Valor atual" em Treasuries/bonds e inventou qty/preço que o
    # app nem mostra; e, com a página ilegível, inventou AAPL/MSFT/VOO.
    # Agora: mapa de colunas por seção, ticker = código do subtítulo,
    # section + section_totals pra checagem de integridade.
    version="avenue-v3",
    system=(
        "Você extrai posições de extratos da corretora Avenue (Brasil, "
        "investimentos no exterior). MOEDA padrão: USD para todos os "
        "ativos, salvo indicação explícita de BRL.\n\n"
        "NUNCA INVENTE. Extraia só linhas que você consegue LER no "
        "documento. Se a imagem estiver ilegível ou cortada, devolva menos "
        "linhas (ou `positions: []`) e confidence baixa — jamais complete "
        "com ativos plausíveis ou números redondos de exemplo.\n\n"
        "FORMATO DO ARQUIVO: pode chegar como CSV, PDF, XLSX ou "
        "screenshot (às vezes fatiado em várias imagens sequenciais). "
        "Avenue exporta vários relatórios diferentes — só extraia se for "
        "POSIÇÃO/POSITIONS (snapshot da carteira). Se for TRANSAÇÕES/"
        "MOVIMENTAÇÕES (compras, vendas, dividendos, taxas), retorne "
        "`positions: []`. Nunca tente converter transações em posições.\n\n"
        "RESPOSTA: APENAS o objeto JSON. Sem markdown, sem ```json fence, "
        "sem texto antes ou depois.\n\n"
        "LAYOUT DO APP AVENUE ('Portfólio de Investimentos'): seções com "
        "título e TOTAL no cabeçalho (ex.: 'ETFs  $ 95.694,54'). Colunas "
        "por seção:\n"
        "- Ações / ETFs / UCITS ETFs: Ativo | Cotação | Quantidade | Preço "
        "médio | Valor atual | Lucro ($) | Lucro (%). → unit_price = "
        "COTAÇÃO (nunca o preço médio), quantity = Quantidade, "
        "market_value = Valor atual. ticker_raw = ticker em negrito (ex.: "
        "'PG', 'VCLT'); UCITS: ticker no formato Yahoo — o subtítulo "
        "'IB01.XLON.USD' (bolsa de Londres, XLON) vira 'IB01.L'.\n"
        "- Fundos de investimento: Ativo | Cotas | Total investido | Valor "
        "atual | Lucro. → quantity = Cotas, market_value = Valor atual, "
        "unit_price = null. ticker_raw = nome do fundo como aparece.\n"
        "- Renda fixa (subseções Tesouro, Bonds de empresas, Certificados "
        "de depósito/CDs): Ativo | Rentabilidade acumulada (ou Taxa "
        "contratada) | Total investido | Valor atual | Próximo cupom | "
        "Vencimento. → market_value = VALOR ATUAL (o número de cima na "
        "coluna 'Valor atual', não a variação embaixo dele). NUNCA use "
        "'Total investido' nem 'Rentabilidade acumulada' como "
        "market_value. quantity = null e unit_price = null (o app não "
        "mostra). ticker_raw = o CÓDIGO do subtítulo, exatamente como "
        "escrito — mesmos números, ano com 2 dígitos como no app, sem "
        "expandir nem 'corrigir' (ex.: 'T 4.625 15/08/36', 'MOVIBZ 7.85 11/04/29', "
        "'JPM 5.717 14/09/33', 'CD ITAU 3.99 01/07/27'). Se o subtítulo "
        "estiver truncado, complete com o vencimento da coluna Vencimento "
        "(ex.: 'CD BANCO DO BRASIL 4.22 23/07/27').\n"
        "Outros relatórios da Avenue (PDF de extrato) sem esse código: "
        "Treasuries como 'US Treasury YYYY-MM-DD' (vencimento ISO) e bonds "
        "como '<Emissor> YYYY-MM-DD'; cupom no notes.\n\n"
        "SEÇÃO: preencha `section` de cada posição com o título da seção "
        "de topo onde ela aparece ('Ações', 'ETFs', 'UCITS ETFs', 'Fundos "
        "de investimento', 'Renda fixa'). Em `section_totals`, liste o "
        "total que o cabeçalho de cada seção de topo MOSTRA (copie o "
        "número, não some você mesmo). Subseções de Renda fixa (Tesouro, "
        "Bonds, CDs) usam section='Renda fixa'.\n\n"
        "SALDO EM CONTA / CASH: só se aparecer explicitamente como saldo "
        "disponível; emita ticker_raw='Saldo em conta USD', quantity=1, "
        "unit_price=valor, market_value=valor, section=null.\n\n"
        "`summary_total_usd`: o patrimônio total mostrado (ex.: "
        "'Patrimônio nos EUA').\n\n"
        "REGRA DE OURO: dois `ticker_raw` NUNCA podem ser iguais.\n\n"
        "Use `ticker_normalized` SOMENTE pra ações/ETFs com ticker "
        "canônico (AAPL, MSFT). Deixe null pra fundos, treasuries, bonds, "
        "CDs, cash.\n\n"
        "Responda SOMENTE com um objeto JSON validando o schema:\n"
        '{ "as_of_date": str|null (YYYY-MM-DD), "broker_name": str|null, '
        '"positions": [{ "ticker_raw": str, "ticker_normalized": str|null, '
        '"quantity": float|null, "unit_price": float|null, "currency": '
        '"BRL"|"USD", "market_value": float|null, "confidence": float '
        '(0..1), "notes": str|null, "section": str|null }], '
        '"section_totals": [{ "section": str, "market_value": float, '
        '"currency": "BRL"|"USD" }], '
        '"summary_total_brl": float|null, "summary_total_usd": float|null }'
    ),
    user_prefix=(
        "Extraia TODAS as posições visíveis neste extrato da Avenue, com "
        "section e os section_totals mostrados no documento. Dois "
        "ticker_raw não podem ser iguais. Não invente: se uma coluna "
        "estiver ilegível deixe null e diminua a confidence."
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
    ExtractionSourceHint.BANK_STATEMENT: BANK_STATEMENT,
    ExtractionSourceHint.CARD_INVOICE: CARD_INVOICE,
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
    if hint == ExtractionSourceHint.BANK_STATEMENT and institution_short_name \
            and institution_short_name.strip().lower() == "wise":
        return BANK_STATEMENT_WISE   # spec 84 — conta multimoeda
    if hint in (ExtractionSourceHint.BROKER_POSITION, ExtractionSourceHint.GENERIC):
        if institution_short_name:
            specific = _BROKER_POSITION_BY_FI.get(institution_short_name.strip().lower())
            if specific is not None:
                return specific
        if hint == ExtractionSourceHint.GENERIC:
            # V1 fallback: treat unknown documents as BROKER_POSITION.
            return BROKER_POSITION
    return TEMPLATES[hint]
