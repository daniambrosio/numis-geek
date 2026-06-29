# Decision-Support Page — Rationale

> Documento de raciocínio antes de desenhar a página de "onde investir o
> dinheiro disponível". Discute jobs to be done, métodos de valuation por
> classe de ativo, arquitetura de dados, e perguntas em aberto.
>
> Quando bater alinhamento nas decisões em §10, parto pro design das telas.

> **2026-06-26 — Atualizações materiais (ver spec 61 master):**
> - §9 abaixo rejeitava Markowitz. **Decisão revisada:** Markowitz entra
>   como peça central do Decision Support v1, com formulação min-variance
>   + class targets como equality constraints. Detalhe na spec 61c.
>   Bullet original mantido tachado abaixo pra preservar histórico.
> - §10 #4 atualizada: APIs integradas desde v1 (brapi + Finnhub +
>   yfinance fundamentals + history). Detalhe na spec 61b.
> - §10 #1: TargetAllocation foi implementada via UI de edição manual em
>   `/admin/target-allocation` (spec 61a, 2026-06-26). Seed do Notion
>   adiado indefinidamente.
> - §10 #5: Watchlist confirmada como v1.5+; v1 fica restrita a ativos
>   owned.

---

## 1. Job to be done

A página existe pra responder uma sequência específica de perguntas que o
usuário (Dani) faz quando aporta dinheiro:

1. **"Quanto eu tenho disponível pra investir?"** — soma do float em
   corretora + saldos de conta corrente acima do colchão de reserva
2. **"O que está barato no que eu já tenho?"** — assets do portfólio
   abaixo do "fair value" segundo o método apropriado pra classe
3. **"O que está pagando bem?"** — DY/yield atrativo vs benchmarks (CDI
   pra BRL, US Treasuries pra USD)
4. **"Onde estou subalocado vs meu target?"** — gap entre alocação atual
   e alocação alvo (por classe, por país, por moeda)
5. **"Há algo novo que vale considerar?"** — watchlist de assets ainda
   não comprados mas monitorados
6. **"Antes de comprar mais X, qual minha exposição já?"** — concentração
   por setor, país, custodiante

**O que essa página NÃO é:**

- Não é um screener de mercado (Investidor10 / Status Invest já fazem
  isso muito bem). É **decision-support sobre o portfólio dele + uma
  watchlist curada**.
- Não é uma plataforma de research (Suno / Morningstar / Seeking Alpha
  são isso). Não pretende substituir a tese — assume que o usuário já
  tem opinião sobre os assets que tracka.
- Não tenta executar trades.

---

## 2. Insights da pesquisa de mercado

A pesquisa em ferramentas existentes (Investidor10, Status Invest, Suno,
Fundamentus, Simply Wall St, Morningstar, Seeking Alpha, Portfolio
Visualizer) destilou algumas ideias que valem importar — e algumas que
valem evitar.

### Borrow

- **Investidor10**: rankings "top X mais baratos por Bazin / menor P/VP" —
  excelente entry point pra "o que está cheap agora" segmentado por classe.
  Vou usar.
- **Status Invest**: heatmap de dividendos esperados por mês — primitive
  de UI util pra income planning. Encaixa pra investidores focados em
  proventos.
- **Suno**: o triplet **preço-teto + posição no ranking + target weight**
  por ativo é o unit decision-support mais limpo que vi. Tells you what to
  buy AND how much. Vou usar — mas o preço-teto é definido pelo usuário
  (na cara do Bazin, mas personalizado).
- **Simply Wall St**: o **snowflake/radar** (5 eixos: Value, Income,
  Growth, Quality, Safety) escala visualmente pra 158 assets melhor que
  qualquer tabela. Mesma forma visual, mas as checks de cada eixo mudam
  por classe — exatamente a abstração que precisamos.
- **Morningstar**: **uncertainty-adjusted fair value** — não basta dizer
  "20% abaixo do fair value"; tem que dizer qual margem de segurança a
  incerteza do ativo demanda. Tesouro IPCA aceita 0%; growth stock
  demanda 25%; crypto não aceita fair value.
- **Seeking Alpha**: factor grids per-classe (não tenta forçar fatores de
  stocks em ETFs/REITs) + **disqualifying grades** que bloqueiam ratings
  altos quando há uma falha fatal. Evita "summed score" enganando.
- **Portfolio Visualizer**: **correlação com holdings existentes** — pra
  158 assets, a próxima compra ideal é frequentemente a que adiciona
  diversificação, não a mais barata em absoluto.

### Avoid

- **Bazin com 6% hardcoded**: rígido demais pra portfólio multi-moeda.
  USD asset a 6% DY não faz sentido vs CDI/SELIC. Target rate fica
  configurável por moeda.
- **Verdict-only (compra/venda)**: sofisticados desconfiam. Sempre ter
  uma view "raw data" lado a lado com a opinionated.
- **Forçar US lens em BR (e vice-versa)**: BDRs no Investidor10 sofrem
  disso; FFO/AFFO inexistente pros US REITs. Cada mercado merece sua
  apresentação.

---

## 3. Métodos de valuation por classe

Pra cada classe do nosso schema (`KLASS` — 11 classes), aqui vai qual
ferramental analítico aplicar:

### `STOCK` (Ação BR + US)

| Método | Quando aplica | Output |
|---|---|---|
| **P/L (P/E)** | Sempre, comparado ao setor + histórico próprio | Múltiplo |
| **P/VP (P/B)** | Empresas capital-intensivas (bancos, segurad., siderúrgicas) | Múltiplo |
| **DY** + payout ratio | Pagadoras de dividendo | % anual |
| **ROE / ROIC** | Qualidade do negócio | % |
| **Margem líquida / EBITDA** | Lucratividade | % |
| **Crescimento de lucros 5y** | Empresas em crescimento | CAGR % |
| **Dívida líquida / EBITDA** | Risco financeiro | x |
| **Graham** (`√(22.5 × EPS × BVPS)`) | Empresas estáveis com lucro positivo. Falha em growth (Amazon, Tesla, etc.) | Fair value R$ |
| **Bazin** (`DPS_anual / required_yield`) | Pagadoras de dividendo. **Required yield configurável por moeda** (não fixo 6%) | Preço-teto R$ |
| **Lynch PEG** (`P/E ÷ growth_rate`) | Growth stocks. PEG < 1 = barato pro crescimento | Múltiplo |
| **DCF 2-stage** | Empresas com FCF previsível. Premium feature, complexidade alta | Fair value R$ |

**Sinal de "barato" sugerido:** ponderação de pelo menos 2 dos 3 (Graham
abaixo do preço atual, Bazin abaixo, Lynch PEG < 1.2). Não 1 isolado.

### `REIT` (FII BR + REIT US)

FII e REIT são funcionalmente o mesmo conceito, mas os métricas diferem:

| Métrica | FII (BR) | REIT (US) |
|---|---|---|
| Múltiplo de book | **P/VP** (price / patrimônio líquido por cota) | **P/NAV** |
| Lucro operacional | DY 12m | **FFO** (Funds From Operations), **AFFO** (Adjusted FFO) — substitui EPS pra REITs |
| Múltiplo de earnings | (não usado) | **P/FFO** |
| Outras | Vacância (físico/contratual), liquidez diária, segmento (tijolo/papel/FoF/híbrido/FIP) | Debt/EBITDA, distribution coverage ratio, occupancy |

**Sinal de "barato" FII:** P/VP < 1 + DY 12m acima do gap target vs
NTN-B (yield real Tesouro IPCA+). Bonus: vacância baixa (tijolo).

**Sinal de "barato" REIT US:** P/FFO no quartil inferior do peer group,
distribution coverage > 1.2, payout ratio razoável.

### `ETF`

ETF não tem "fair value" no sentido tradicional — segue o índice. Foco em
custo, tracking, e adequação à estratégia:

- **TER (Total Expense Ratio)** — quanto menor, melhor
- **Tracking error** vs benchmark — quanto fiel o ETF segue o índice
- **AUM** (patrimônio sob gestão) — liquidez + risco de fechamento
- **Liquidez diária** — bid-ask spread
- **Holdings overlap** com o que já tenho — pra evitar redundância
- **Sector exposure** — concentração

**Sinal de "vale comprar":** TER baixo (< 0.5% pro tipo), tracking error
< 1%, AUM > $1B, overlap baixo com portfolio atual.

### `FIXED_INCOME` (Tesouro + CDB + LCI + LCA + US Treasuries + corporates)

Renda fixa não tem "fair value" — tem **yield**, prazo, risco. Decisão é
de timing (curva de juros) e instrumento certo pro objetivo.

| Sub-classe | Métricas chave |
|---|---|
| Tesouro IPCA+ | **Yield real** (juro além da inflação) · duration · prazo |
| Tesouro SELIC | Taxa equivalente vs CDB (descontado IR) |
| Tesouro PREFIXADO | Yield nominal · expectativa de inflação 5y · risco |
| CDB / LCI / LCA | % CDI ou IPCA+X · prazo · liquidez · FGC R$ 250k cap · isenção IR (LCI/LCA) |
| US Treasury | YTM · spread vs SELIC convertido · duration |
| US Corporate | YTM · spread vs Treasury · credit rating (S&P/Moody's) |

**Sinal de "barato":** yield real acima da mediana 5y (IPCA+ historicamente
> 6% é raro). Pra CDB: > 110% CDI pra prazo > 2 anos, ou LCI > 95% CDI
isento. Pra US: yield real > 2% em TIPS é considerado bom.

### `FUND` (Fundos BR via CNPJ)

Fundo é uma cesta — performance é o que importa:

- **Rentabilidade vs benchmark** (CDI, Ibov, IPCA+X, conforme estratégia)
  em janelas 12m / 24m / 36m / 60m
- **Sharpe ratio** (retorno / risco)
- **Maximum drawdown** + tempo até recuperação
- **Taxa de adm + taxa de performance** (afetam retorno líquido)
- **Patrimônio líquido** (small fund = risco; mega fund = inércia)
- **Idade do fundo** (track record < 3 anos é suspeito)
- **Composição** (% renda fixa, % ações, etc.)

**Sinal de "vale":** Sharpe > 1 em 36m, drawdown < 20%, batendo benchmark
em pelo menos 3 das 4 janelas, taxa total < 2% a.a.

### `CRYPTO`

**Não tem fair value fundamentalista**. Estratégia é DCA + asset
allocation cap (3-5% do portfólio típico).

Métricas relevantes (todas opcionais):

- **% do portfólio total** — alarme se passa do cap configurado
- **Realized P&L vs avg cost** — quão longe do break-even
- **Drawdown atual vs ATH** — sentiment proxy
- **MVRV ratio** (BTC/ETH) — métrica on-chain de sentimento
- **Volatilidade 90d** — risco perceptível

**"Sinal de comprar":** o sinal é cumprir o DCA mensal. Não tem "barato"
defensável aqui — só pode ter "vale comprar pra manter alocação alvo".

### `REAL_ESTATE` (imóvel direto)

Não rola comparação simples. Métricas pra avaliar uma compra OU manter:

- **Cap rate** = aluguel anual líquido / valor do imóvel
- **Yield on cost** desde aquisição
- **Comparable sales** (manual — input de avaliação)
- **Preço/m²** vs região (manual)
- **Liquidez assumida** (semanas/meses pra vender)

Pro nosso protótipo: campo de "current_price" continua manual; cap rate
calculado se o usuário registrar aluguel como Distribution.

### `VEHICLE`

Não é investimento, é ativo depreciante. **Comparar com FIPE** (BR) ou KBB
(US) — só pra honestidade do patrimônio.

### `CASH`

Custo de oportunidade. Show: "este saldo está perdendo X% a.a. vs CDI ao
ficar parado". Pode sugerir Tesouro SELIC ou CDB líquido.

### `FGTS`

Limite de manobra: TR + 3% a.a. (péssimo). Pode mostrar "FGTS rende X
abaixo do CDI" — útil pra decidir saque-aniversário ou usar em imóvel.

### `PRIVATE_PENSION` (PGBL/VGBL)

É um wrapper — avalie o fundo subjacente pelas mesmas métricas de FUND.
Considera também o regime tributário escolhido (regressivo é melhor pra
longo prazo).

---

## 4. O padrão visual unificador: Snowflake / Radar

Independente de classe, cada ativo tem um **score de 5 eixos** com
definição que varia por classe:

```
            Value
              ▲
     Quality ─┼─ Income
              │
   Safety ────┴──── Growth
```

| Eixo | STOCK | REIT/FII | FIXED_INCOME | ETF | CRYPTO |
|---|---|---|---|---|---|
| **Value** | Graham/Bazin/PEG composite | P/VP vs hist + P/FFO | Yield vs mediana 5y | TER inverso | — (cinza) |
| **Income** | DY vs CDI | DY 12m vs NTN-B | Yield | DY se tiver | — |
| **Growth** | Crescimento lucros 5y | Crescimento DY 5y | (curva) | Crescimento AUM | % from ATH |
| **Quality** | ROE + ROIC + margens | Vacância + segmento | Rating | Tracking error inverso | Idade |
| **Safety** | Dívida/EBITDA + uncertainty | Concentração + LTV | Rating + FGC | Liquidez | Volatility inversa |

Cada eixo de 0-5. Total visualizado como pentágono colorido (verde se
score alto, vermelho se baixo). Igual ao Simply Wall St.

**Vantagem do snowflake:** ao olhar uma lista de 158 ativos, eu *vejo*
quais estão fortes em quê. Sem precisar entender 10 métricas por linha.

---

## 5. Margin of safety por classe (Morningstar-inspired)

Cada classe tem um nível de "incerteza" que demanda um desconto diferente
pro fair value antes de considerar compra:

| Classe | Incerteza | Margem demandada |
|---|---|---|
| Tesouro IPCA+/SELIC | Muito baixa | 0% (compra a preço de mercado) |
| FIXED_INCOME (CDB grandes bancos) | Baixa | 0-5% |
| REIT / FII tijolo (logistic, urban) | Baixa-média | 5-10% |
| STOCK blue-chip (ITUB4, PETR4, AAPL, MSFT) | Média | 10-15% |
| REIT / FII papel | Média | 10-15% |
| FUND multimercado | Média-alta | 15-20% (em retorno acumulado) |
| STOCK growth / mid-cap | Alta | 20-30% |
| STOCK small-cap | Muito alta | 30-40% |
| CRYPTO | Extrema | N/A (DCA, sem fair value) |

Esses números são configuráveis por classe + por ativo (override
individual). Default global = essa tabela.

---

## 6. Arquitetura de dados — o que precisa existir

A página depende de dados que o modelo atual **não tem**. Vamos precisar
expandir.

### Schema additions

**Nova tabela: `AssetFundamentals`** — snapshot temporal de fundamentos
por ativo

```
asset_fundamentals {
  id PK
  workspace_id FK
  asset_id FK
  snapshot_date Date  -- quando foi capturado
  source enum  -- 'manual' | 'brapi' | 'fundamentus' | 'fmp' | 'yfinance'
  -- Stocks
  eps Decimal
  bvps Decimal
  pe Decimal
  pb Decimal
  roe Decimal
  roic Decimal
  margin_net Decimal
  margin_ebitda Decimal
  debt_ebitda Decimal
  earnings_growth_5y Decimal
  dividend_yield_12m Decimal
  payout_ratio Decimal
  -- REITs
  ffo_per_share Decimal
  affo_per_share Decimal
  p_ffo Decimal
  p_vp Decimal
  vacancy Decimal
  distribution_coverage Decimal
  -- ETFs
  expense_ratio Decimal
  tracking_error Decimal
  aum Decimal
  -- Fixed income (most also on FixedIncomeAsset)
  ytm Decimal
  duration Decimal
  -- Misc
  raw_payload JSON  -- whatever else the provider returned
}
```

**Nova tabela: `PriceHistory`** — separado de `Asset.current_price`

```
price_history {
  asset_id FK
  date Date
  price Decimal
  source enum
  PRIMARY KEY (asset_id, date)
}
```

**Nova tabela: `TargetAllocation`** — alvo de alocação por classe/país

```
target_allocation {
  workspace_id FK
  dimension enum  -- 'class' | 'country' | 'currency'
  key string  -- 'STOCK' | 'BR' | 'BRL'
  target_pct Decimal
}
```

**Nova tabela: `Watchlist`** — assets que o usuário tracka mas não tem

```
watchlist_asset {
  id PK
  workspace_id FK
  asset_id FK  -- pode ser um Asset 'inativo' com qty=0 ou ter sua própria entidade
  added_at Date
  thesis Text  -- por que está acompanhando
  target_price Decimal
}
```

**Novos campos em `Asset`:**

- `sector string` (opcional — pra computar concentração)
- `risk_uncertainty enum` ('low'|'medium'|'high'|'extreme') — override
  individual do default por classe
- `required_yield_override Decimal` — Bazin personalizado por ativo

**User preferences** (talvez tabela própria):

- `required_yield_brl` (default 8%)
- `required_yield_usd` (default 5%)
- `cash_reserve_brl` (R$ mantido em conta como colchão, fora do "disponível")
- `cash_reserve_usd`
- `crypto_max_pct` (default 5%)

### Data providers

Conforme a pesquisa (`docs/decision-support-rationale.md` será
acompanhado por `docs/data-providers-research.md` se quiser ver
detalhes), o stack recomendado < $50/mês:

| Provider | Cobre | Custo |
|---|---|---|
| **BCB (`python-bcb`)** | PTAX, SELIC, CDI, IPCA | Free |
| **Brapi (free + token)** | BR stocks, FIIs, ETFs — preços + dividendos | Free |
| **Fundamentus scraper** | BR stocks + FIIs — fundamentals (P/VP, DY, ROE, vacância) | Free (uso pessoal, throttle) |
| **CVM `INF_DIARIO`** | BR funds (CNPJ) — cotas diárias | Free |
| **Tesouro Transparente CSV** | Tesouro Direto — preços + yields históricos | Free |
| **yfinance** | US equities/ETFs/REITs — preços + fundamentos básicos + crypto | Free |
| **FMP Starter (~$22/mo)** | US fundamentals deep (income/balance/cashflow/ratios), trend tracking | Paid |
| **CoinGecko free** | Crypto prices | Free |

**Total: ~$22/mês.** Vale o spend pelo aprofundamento US.

**Pattern arquitetural:** abstração `data_provider` por classe/mercado,
não por API. Ex: `BR_STOCK_FUNDAMENTALS` provider hoje aponta pra
Fundamentus, amanhã pode apontar pra Dados de Mercado sem trocar nada
no resto do código.

Cache agressivo em SQLite/Postgres — só bate na API 1 vez por ticker
por dia.

---

## 7. Fluxo de uso esperado

```
1. Usuário entra na página "Onde investir"
2. Vê: cash disponível (auto-calculado), gap vs target allocation, lista
   ranqueada de "top opportunities"
3. Click numa oportunidade → asset detail com snowflake + valuation
   methods relevantes + signal final
4. Decide: clica "Adicionar ao carrinho de compras mental" (lista
   temporária)
5. Quando satisfeito, clica "Plano de compras" → vê impacto na alocação +
   uso do cash + sugestão de ordem de execução (qual broker, etc.)
6. Fora do app: executa as ordens (corretora)
7. Volta no app: lança os AssetMovements (composer existente)
8. Próxima vez que entra na página: cash recalculado, novo gap, novas
   opportunities
```

---

## 8. Phasing sugerido

### V1 — Manual + estrutura básica (2-3 specs)

- Schema: `AssetFundamentals` (manual), `TargetAllocation`, `Watchlist`,
  `risk_uncertainty` em Asset
- UI: página `/onde-investir` com 3 seções:
  - **Cash disponível + Gap vs target**
  - **Top opportunities** (lista simples baseada em rule engine sobre
    fundamentos manualmente cadastrados)
  - **Asset detail** com calculadoras Graham/Bazin/Lynch (stocks),
    P/VP/DY (FIIs), yield (fixed income)
- Snowflake/radar como visual unificador
- Tudo opt-in: se o usuário não cadastrou fundamentals dum ativo, o
  scorecard mostra "sem dados" não erro

### V1.5 — Watchlist + heatmaps (1-2 specs)

- Página watchlist (assets não-owned monitorados)
- Heatmap de dividendos esperados por mês (Status Invest pattern)
- Correlation badge entre ativos do portfolio

### V2 — Automação de dados (3-4 specs)

- Integração com BCB (PTAX + SELIC + CDI + IPCA — já útil pro modelo
  existente)
- Brapi + Fundamentus scraper pra BR (cron diário)
- yfinance + CoinGecko pra US + crypto
- FMP integration (paid, opcional)
- Background jobs + cache strategy

### V3 — Refinamentos (open)

- Backtests
- Tax-aware suggestions (LCI vs CDB tabela IR, US dividend withholding)
- "Plano de compras" com impacto multi-dimensional
- Alertas (preço caiu abaixo do target, DY subiu acima do threshold)

---

## 9. O que NÃO entra (out of scope explícito)

- **Trading automatizado** — fora completamente
- **Recomendações fundamentadas** ("compre X porque…") — não somos
  research firm
- ~~**Otimização de portfólio markowitzeana** — complexidade vs benefício
  ruim pro caso de uso~~ **(REVERTIDO 2026-06-26: entra como peça
  central do Decision Support v1 — ver spec master 61 + spec 61c.)**
- **Live streaming de preços** — EOD é suficiente
- **Análise técnica** (RSI, MACD, candlestick) — não é o estilo do
  usuário
- **Notícias / sentiment** — outras ferramentas fazem melhor

---

## 10. Decisões locked in (respostas do usuário em 2026-05-06)

1. **Target allocation:** existe em tabela no Notion do usuário, campo
   "Objetivo Share". Conteúdo ainda não capturado nesta doc — usuário
   precisa colar/exportar pra estruturar como seed data + UI de edição.
   Schema: tabela `TargetAllocation` por workspace, dimensão (class /
   country / currency / asset), key, target_pct.

2. **Required yield por moeda:** configurável por workspace, com defaults
   fixos por país pra começar:
   - **BRL**: 8% DY (preço-teto Bazin)
   - **USD**: 5% DY
   Usuário interessado em explorar **yield real vs IPCA** depois de
   estudar — V2 candidate (settings ganha "modo Bazin clássico" vs "modo
   yield real").

3. **Reserva de emergência — modelo aprovado:**
   - Campo opcional `is_emergency_reserve` (boolean) em Asset
   - Workspace setting `emergency_reserve_target_brl` (R$ X ou múltiplo
     de despesas mensais quando Orçamento integrar)
   - Cálculo: `reserva_atual = Σ valor_atual dos ativos marcados`
   - Página /onde-investir:
     - `reserva_atual ≥ target` → ✅ "Reserva OK. Cash disponível = todo
       cash em conta corrente."
     - `reserva_atual < target` → ⚠️ "Reserva R$ X abaixo do alvo de
       R$ Y. Sugiro alocar a diferença antes de investir no resto."
   - Respeita o hábito do usuário (reserva fica em ativos líquidos
     investidos), mas alerta se ele acidentalmente esvazia.

4. **API integration desde V1.** Não esperamos manual. Stack do §6
   confirmado: BCB + Brapi + Fundamentus scraper + CVM + Tesouro
   Transparente + yfinance + FMP Starter ($22/mês) + CoinGecko.

5. **V1 só com assets owned.** Watchlist fica pra V1.5.

6. **Real estate / vehicle ficam fora do decision-support.** Atualização
   manual via página separada de "atualizar preço" (que serve pra esses
   + qualquer ativo cuja API falhar). Não aparecem como "oportunidade"
   nem como "barato/caro".

7. **Tax-awareness — spec dedicada própria, não dentro desta.** Ver §11
   abaixo. Padronização daqui em diante: tudo bruto + IR explícito no
   campo `tax` já existente em AssetMovement e Distribution. Histórico
   antigo fica como está (não retrabalha).

8. **Verdict opinativo SIM, mas com regras claras escritas antes.**
   Eu (designer Claude) escrevo as regras de rotulação por classe (são
   opinionadas mas defensáveis); usuário revisa antes de virar código.
   Esboço de regras em §12 desta doc.

9. **Crypto:**
   - Cap vem da tabela Notion (junto com targets de classe)
   - Sem ETH atualmente. Holdings: **BTC + USDC + Meli dólar** (USDC e
     Meli dólar são **stablecoins**)
   - Modelagem: classe `CRYPTO` com flag `is_stablecoin = true`
   - Stablecoins:
     - Não entram no cap de cripto volátil
     - Aparecem visualmente em cor neutra (não amarelo de cripto)
     - Contam como "cash disponível em USD" pro fluxo de "onde investir"
     - Métricas de volatilidade não se aplicam

10. **FGTS — pode julgar com cautela:**
    - Mostra se saque-aniversário está ativo + valor disponível pra saque
    - Mostra "FGTS rende ~ X% a.a. (TR + 3%); CDI atual está em Y% —
      diferença Z% a.a." sem prescrição forte
    - Anota lock-out de 2 anos do saque-aniversário se o usuário voltar
      pra modalidade "saque-rescisão" (caso atual do Dani — voltou em
      maio/2026 por insegurança no trabalho; pode revisar a partir de
      maio/2028)
    - Não recomenda mudar de estratégia sem o usuário pedir

---

## 11. Tax-awareness — spec dedicada futura (pointer)

Tax-awareness cruza praticamente todo o sistema (Stocks, FIIs, Renda
Fixa, Fundos, Opções, dividendos US, etc.). Por isso vira **spec
dedicada própria** depois das features core. Escopo dela:

- Apuração mensal por tipo de ativo (DARFs)
- Isenções e regras especiais:
  - Stocks: isenção em vendas mensais < R$ 20k (não vale pra FII/ETF)
  - FII: isenção em proventos pra PF; 20% sobre venda
  - LCI/LCA: isento de IR sobre rendimento (PF)
  - CDB/Tesouro: tabela regressiva (22.5% → 15% conforme prazo)
  - Renda fixa USD / bonds: regras BR específicas pra exterior
  - **Opções: 15% sobre ganho mensal sem isenção R$ 20k; IRRF 0,005%**
  - Dividend US: 30% withheld na fonte (Form 1042-S)
  - Crypto: 15% acima de R$ 35k mensais
  - Fundos: come-cotas semestral 15-20%
- Geração de DARFs mensais
- Geração de relatório consolidado pra DIRPF (declaração anual)
- Simulação ("se eu vender X agora, IR seria R$ Y")

**Padronização daqui em diante:** todos os lançamentos novos seguem o
padrão `gross + tax` explícito. O campo `tax` já existe em
`AssetMovement` e `Distribution`. O usuário (Dani) padroniza assim. O
histórico antigo pode estar misturado (alguns valores líquidos, outros
brutos) — **não retrabalha**. A tax spec lida com cutoff de
"comportamento antes vs depois" se necessário.

---

## 12. Regras de verdict por classe (rascunho — usuário revisa)

Verdict é uma das 3 labels: **Comprar** (verde) · **Manter** (cinza) ·
**Vender** (vermelho). Cada classe tem regras próprias. Disqualifying
gates impedem rótulo "Comprar" se uma condição crítica falhar (per
Seeking Alpha).

### `STOCK` (BR + US)

| Sinal | Condição |
|---|---|
| **Comprar** | Preço < Bazin (com required_yield configurado) E preço < Graham × 1.2 E nenhum disqualifying gate |
| **Vender** | Preço > Graham × 1.5 E DY < 50% do required_yield |
| **Manter** | Caso contrário |

**Disqualifying gates pra Comprar:**
- ROE < 0 (empresa dando prejuízo)
- Dívida líquida / EBITDA > 5x (alavancagem perigosa)
- Crescimento de lucros negativo nos últimos 3 anos (declínio)

### `REIT` (FII + REIT US)

| Sinal | Condição |
|---|---|
| **Comprar** | P/VP < 0.95 (BR) ou P/FFO no quartil inferior do peer (US) E DY 12m > 1.2× required_yield E nenhum disqualifying gate |
| **Vender** | P/VP > 1.2 E DY 12m < 0.7× required_yield |
| **Manter** | Caso contrário |

**Disqualifying gates:**
- Vacância > 20% (FII tijolo)
- Distribution coverage < 1.0 (REIT US — não cobre o próprio dividendo)
- Liquidez diária < R$ 100k (BR) ou < $1M (US)

### `FIXED_INCOME`

| Sinal | Condição |
|---|---|
| **Comprar** | Yield real > mediana 5y da classe E rating ≥ BBB (corporates) |
| **Manter** | Yield real entre mediana e mediana − 1pp |
| **Sem ação** | Tesouro: nunca "vender" (carrega até vencimento por design) |

Renda fixa raramente é "venda" — o sinal é mais "vale comprar mais
agora" vs "espere por melhor janela".

### `ETF`

| Sinal | Condição |
|---|---|
| **Comprar** | TER < 0.5% E tracking error < 1% E AUM > $1B E overlap com portfolio < 30% |
| **Vender** | AUM em queda > 30% ano (sinal de fechamento) |
| **Manter** | Default |

### `FUND` (BR)

| Sinal | Condição |
|---|---|
| **Comprar** | Bate benchmark 3 das 4 últimas janelas (12/24/36/60m) E Sharpe > 1 E taxa total < 2% |
| **Vender** | Não bate benchmark em janela 36m E taxa total > 2% |
| **Manter** | Default |

### `CRYPTO` (volátil)

Não tem verdict de "barato/caro". Lógica diferente:

| Sinal | Condição |
|---|---|
| **Comprar (DCA)** | % do portfólio < target_pct |
| **Vender (rebalance)** | % do portfólio > target_pct × 1.5 |
| **Manter** | Dentro da faixa target ± 50% |

### `CRYPTO` stablecoin

Tratado como cash USD — não tem verdict.

### `REAL_ESTATE` / `VEHICLE`

Sem verdict — fora do scope de decisão de "onde investir".

### `FGTS` / `PRIVATE_PENSION`

Sem verdict — restrições estruturais. Mostra status (saque-aniversário?
regime tributário escolhido?) sem prescrição.

---

## 13. Notion table — pendente

Usuário tem em
https://www.notion.so/daniambrosio/18007f65cfa48012a594c3b5b221f22e?v=258c1d84e64f4f7ab0d4094b1df18978
uma tabela com campo `Objetivo Share`. Estrutura esperada:

```
Asset name | Class | Country | Objetivo Share % | (outros campos)
```

Pra avançar com seed data + UI de TargetAllocation, **precisamos do
conteúdo dessa tabela** colado aqui ou exportado como CSV.

Enquanto isso, o protótipo usa allocation target plausível inventado
(30/25/20/10/5/10 nas top classes BR/US) só pra ilustrar UI.

---

## 14. Próximo passo

Com as decisões locked (§10-13), seguimos:

1. **Protótipo HTML** (esta sessão):
   - Página `/onde-investir` — cockpit com cash disponível + gap vs
     target + top opportunities + reserva status
   - Extensão da `AtivoDetailPage` — nova seção "Valuation" com os
     métodos apropriados pra classe daquele ativo + verdict label
   - Página `/alocacao-alvo` — settings de target allocation
     (waiting Notion table data pra popular)
   - Snowflake/radar visual em cada asset
   - Card "Opções abertas" no underlying (per `options-rationale.md`)

2. **Pré-requisitos pra Code (próximas specs):**
   - Schema adições: AssetFundamentals, PriceHistory, TargetAllocation,
     emergency reserve fields, options fields, AssetMovement types
   - Data provider abstraction
   - 5-6 specs incrementais

3. **Spec de Tributação** — separada, depois do core.

4. **Watchlist + heatmaps** — V1.5.

---

## Apêndice — Referências consultadas

**Ferramentas:**
- Investidor10: https://investidor10.com.br/acoes/rankings/acoes-mais-baratas-bazin/ , https://investidor10.com.br/fiis/rankings/menor-pvp/
- Status Invest: https://statusinvest.com.br/
- Fundamentus: https://www.fundamentus.com.br/
- Simply Wall St snowflake: https://support.simplywall.st/hc/en-us/articles/360001740916
- Morningstar uncertainty: https://www.morningstar.com/stocks/an-introduction-morningstar-uncertainty-rating
- Seeking Alpha quant: https://help.seekingalpha.com/premium/quant-ratings-and-factor-grades-faq
- Portfolio Visualizer correlations: https://www.portfoliovisualizer.com/asset-correlations

**Métodos:**
- Bazin: https://investidor10.com.br/conteudo/metodo-bazin/
- Lynch PEG: classic Peter Lynch — *One Up On Wall Street*
- DCF para REITs (AFFO): Simply Wall St documentation

**Data sources:**
- Brapi: https://brapi.dev/pricing , https://brapi.dev/docs/acoes
- python-bcb: https://wilsonfreitas.github.io/python-bcb/
- Fundamentus scrapers: https://pypi.org/project/pyfundamentus/ , https://github.com/cammneto/Stock-Screener-bovespa
- CVM Open Data: https://github.com/amgsnt/cvm
- FMP pricing: https://site.financialmodelingprep.com/pricing-plans
- yfinance: https://github.com/ranaroussi/yfinance
- CoinGecko pricing: https://www.coingecko.com/en/api/pricing
- Tesouro/B3 dev: https://developers.b3.com.br/apis/tesouro-direto

*Documento criado em 2026-05-06. Atualizar conforme decisões e iteração.*
