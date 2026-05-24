# Prototype deltas — 2026-05-23

> Briefing para a sessão de Code. Resume o que foi adicionado ao protótipo (`prototypes/index.html`) e precisa ser portado para o app real. Para o contexto-base de bootstrap, ver `docs/code-session-kickoff.md`.

## Por que existe este doc

Após o kickoff anterior, o protótipo evoluiu com 3 frentes que ainda não estão em `prototype-deltas`/specs:

1. **Atualização de preços** dos ativos (com origem e idade)
2. **Gráfico mensal de proventos** com toggles (moeda · quebra · período)
3. **Prêmio sintético (OPTION_PREMIUM) como 5ª categoria de tipo de provento**, sempre visível em dashboards

O coder agent deve usar este doc como input para escrever os próximos specs em `./specs/`.

---

## 1. Atualização de preços

### 1.1 Modelo

Acrescentar em `Asset`:

```python
price_updated_at: datetime | None
price_source: PriceSource  # enum
```

Enum `PriceSource`:

| valor | quando usar |
|---|---|
| `BRAPI` | Ações BR, FIIs, ETFs BR, opções BR |
| `YAHOO` | Ações US, REITs US, ETFs US |
| `COINBASE` | Cripto |
| `TESOURO` | Tesouro Direto (via API pública do Tesouro) |
| `MANUAL` | Imóvel, veículo, FGTS, VGBL, CDB, LCI, qualquer ativo sem fonte automatizada |

### 1.2 Regras de "staleness"

```text
APIs    : fresh < 24h · stale < 7d  · old >= 7d
Manuais : fresh < 30d · stale < 90d · old >= 90d
```

Manuais têm threshold mais frouxo pra imóvel/veículo não viverem em vermelho. A cor de "saúde" no topbar deve **considerar apenas ativos com fonte API** (manuais ignorados no agregado).

### 1.3 Endpoints

```text
POST /api/prices/refresh
  body: { source?: "BRAPI" | "YAHOO" | "COINBASE" | "TESOURO" | null,
          asset_ids?: int[] }
  - sem body: refresh em tudo que tem fonte automatizada
  - com source: só essa fonte
  - com asset_ids: só esses
  resp: { ok: int, failed: int,
          errors: [{ asset_id, ticker, reason }] }

POST /api/assets/{id}/refresh-price
  - força refresh de um único ativo
  - 422 se source = MANUAL
  resp: { price, price_updated_at, price_source }

PATCH /api/assets/{id}/price
  - update manual (só para source = MANUAL)
  body: { price: Decimal }
  - também atualiza price_updated_at = now()
```

### 1.4 Background job

Cron diário **18:00 America/Sao_Paulo** que chama `/api/prices/refresh` sem body. Auditar como `price.refresh.cron` no audit log.

### 1.5 UI — topbar (componente `<PriceRefresh />`)

- Botão pequeno entre breadcrumbs e `<NovoButton />`
- Visual: ícone refresh + `há Xh` + dot colorido (verde/âmbar/vermelho conforme worst-tier dos ativos API)
- Click → popover (não modal) com:
  - Idade do mais antigo + total de ativos
  - Botão "Atualizar agora" (disabled enquanto running, ícone spinner)
  - Lista de fontes, cada uma com badge de status (idle/updating/done) e contagem `N/N` no fim
  - Painel de resultado com sucesso/erro depois da execução
  - Top-5 ativos mais desatualizados como atalho (linka pra `/ativo/{id}`)
  - Footer: "Atualizações automáticas diárias às 18h. Ativos manuais precisam ser editados no detalhe."

### 1.6 UI — página `Ativos`

- Nova coluna `Atualizado` antes da coluna de ações:
  - Dot colorido + `há Xh` (texto pequeno)
  - Ícone `↻` por linha
    - Botão habilitado (`stopPropagation`) quando `price_source != MANUAL`
    - Desabilitado/cinza quando `MANUAL`, com tooltip "Sem fonte automatizada — preço manual"
  - Tooltip com fonte + timestamp ISO formatado
- Sort por `price_updated_at ASC` deve estar disponível (escopo V1.5)
- Bulk action "Atualizar selecionados" (V1.5 — não bloqueia). Bulk **ignora silenciosamente** itens MANUAL.

### 1.7 UI — detalhe do ativo

No header de actions, **dois botões dedicados** (em vez de um morph):

| Botão | Ícone | Estado |
|---|---|---|
| `Atualizar preço` | `refresh` | Habilitado quando `price_source != MANUAL`. Desabilitado com `cursor-not-allowed` + border tracejada + tooltip "Sem fonte automatizada — use Editar preço para atualizar manualmente" quando `MANUAL`. |
| `Editar preço` | `edit-2` | Sempre habilitado. Abre modal/inline-edit para sobrescrever `price` e setar `price_updated_at = now()`, `price_source = MANUAL` se vier de outra fonte. Audit log `price.update.manual`. |

KPI "Preço atual":
- Dot colorido no canto superior direito (tooltip explica o tier)
- Sub-text: `há Xh · {source label}` (+ conversão R$ se USD)

> Por quê não morph entre Atualizar/Editar: usuário não enxerga a regra ("por que esse não dá pra atualizar?"). Tendo os dois sempre visíveis com um deles cinza, fica claro qual ação está disponível e por quê.

### 1.8 Auditoria

Cada refresh deve gerar evento:

```
action: "price.refresh"           (manual user-triggered)
        "price.refresh.cron"      (background job)
        "price.update.manual"     (PATCH manual)
resource: "asset/{id}"
details: "PETR4: 38,90 → 39,12 (brapi)"
```

---

## 2. Gráfico mensal de proventos

### 2.1 Endpoint

```text
GET /api/distributions/chart
  query:
    period          = "12m" | "24m" | "ytd"           (default: "12m")
    breakdown       = "klass" | "country" | "fi" | "type" | "total"  (default: "klass")
    currency        = "BRL" | "USD"                   (default: "BRL")
    include_synthetic = bool                          (default: true)
  resp:
    {
      rows: [
        { ym: "2025-06", total: Decimal, segments: [{ key, value, label, color }] }, ...
      ],
      legend: [{ key, label, color }],
      totals: { sum, monthly_avg, max },
      currency: "BRL" | "USD"
    }
```

### 2.2 Conversão de moeda

- `BRL`: cada evento USD vira BRL multiplicando pelo `fxRate` (PTAX do dia do evento) já gravado em `Distribution.fx_rate`
- `USD`: cada evento BRL é dividido pelo PTAX do mês do evento (precisa de `PTAXRate` para esse mês)

> Decisão: **não há modo "BRL+USD lado a lado"**. Duas escalas no mesmo eixo confundem mais do que ajudam — o usuário alterna entre R$ e US$ pra responder cada pergunta.

### 2.3 Cores por categoria (mantenas estritamente — protótipo já usa)

| Tipo | Cor |
|---|---|
| `DIVIDEND` | `#22c55e` |
| `INTEREST` | `#3b82f6` |
| `JCP` | `#f59e0b` |
| `SECURITIES_LENDING` | `#8b5cf6` |
| `OPTION_PREMIUM` | `#a855f7` |

Para breakdown por classe/país/FI: reutilizar as cores já existentes do design system.

### 2.4 UNION com OPTION_PREMIUM

`OPTION_PREMIUM` **não é uma row na tabela Distribution**. É uma view derivada:

```sql
SELECT
  date_trunc('month', mov.d) AS ym,
  opt.account_id, opt.country, 'OPTION' AS klass,
  'OPTION_PREMIUM' AS type,
  mov.net AS net,
  mov.ccy, mov.fx_rate
FROM asset_movement mov
JOIN asset opt ON opt.id = mov.asset_id
WHERE opt.klass = 'OPTION'
  AND mov.type IN ('SELL_OPEN', 'BUY_TO_CLOSE')
```

O endpoint do chart faz UNION dessas linhas com Distribution **quando `include_synthetic=true`**.

A linha sintética aponta para o **underlying** como `asset_id` (não para a opção), mas mantém um `option_asset_id` para o link de detalhe. Mesma regra do protótipo.

### 2.5 UI — componente `<ProventosChart />`

Props:

| prop | default | descrição |
|---|---|---|
| `defaultBreakdown` | `"klass"` | uma das 5 dimensões |
| `defaultCurrency` | `"BRL"` | uma das 3 |
| `defaultPeriod` | `"12m"` | uma das 3 |
| `includeSynthetic` | `true` | bool — pode ser controlado externamente |
| `onIncludeSyntheticChange` | – | callback se for controlado externamente |
| `compact` | `false` | esconde legenda + footer toggle |
| `hideToggles` | `false` | esconde os 3 segmented controls |
| `noCard` | `false` | renderiza sem o `<Card>` wrapper (pra embed em outro card) |

Layout:
- Header: KPIs à esquerda (último mês + MoM · 12M trailing + média/mês · YTD), toggles à direita
- Body: stacked bars com hover tooltip mostrando segmento por segmento
- Footer: legenda + toggle `Incluir dividendos sintéticos`

Visual:
- Barras com `rx=2`, opacity 0.85 default → 1 no hover
- Outline no hover
- Eixo X: labels de mês abreviados (`Mai`, `Jun`...), saltando alternados se cols > 14
- Tooltip flutuante absoluto no canto superior direito do chart

### 2.6 UI — onde aparece

**Página `/proventos`** (substitui os 2 cards de topo antigos):
- `<ProventosChart includeSynthetic={state} onIncludeSyntheticChange={set} />`
- Card "Por tipo" com 5 chips (ver §3)
- Linha de KPIs slim: Líquido (filtrado) · Bruto · IR retido · Eventos
- Filtros + lista (já existia)

**Dashboard**:
- Card span-4 com:
  - `<ProventosChart defaultBreakdown="klass" compact hideToggles noCard />`
  - Lista "Por tipo" embaixo com os 5 tipos sempre listados (ver §3.2)

---

## 3. Prêmio sintético como 5ª categoria de tipo

### 3.1 Regra de negócio

`OPTION_PREMIUM` (= prêmio recebido por opção vendida) é o **5º tipo de provento** alongside:

1. `DIVIDEND`
2. `INTEREST`
3. `JCP`
4. `SECURITIES_LENDING`
5. **`OPTION_PREMIUM`** ← novo

Visualmente, deve ser tratado como categoria de primeira classe em qualquer "Por tipo" — **mesmo quando o toggle de inclusão estiver desligado**, a categoria continua listada (apenas dim/dashed pra indicar "off").

Mantém valendo:
- **Não inflar DY/YoC do underlying** com OPTION_PREMIUM
- Mostrar badge `OPÇÕES` ao lado do label pra deixar a natureza sintética explícita
- Cor `#a855f7` (purple, distinto do `#f59e0b` do JCP e do `#8b5cf6` do Aluguel)

### 3.2 UI — "Por tipo" 5-chip

#### Página Proventos (card grande)

Grid 2-3-5 colunas (responsivo). Cada chip:

```
┌─────────────────────────┐
│ ● TIPO_LABEL  [OPÇÕES]  │  ← badge só no sintético
│ R$ 12,5 mil             │
│ 4%                      │
└─────────────────────────┘
```

Se `OPTION_PREMIUM` e `includeSynthetic=false`:
- Border dashed
- Bg mais claro
- Opacidade 60%
- Sub-text "desligado" no lugar do %

#### Dashboard (lista compacta dentro do card Proventos)

```
Por tipo
● Dividendo           75%  R$ 32 mil
● Juros               12%  R$ 5 mil
● JCP                  8%  R$ 3 mil
● Aluguel              3%  R$ 1 mil
● Prêmio sintético [OPÇÕES]  2%  R$ 1 mil
```

Sempre os 5, ordem fixa, valor zero ok.

---

## 4. Arquivos do protótipo (para diff/audit)

`prototypes/index.html` — alterações desta sessão:

**Constantes/data**:
- `PRICE_NOW_ISO`, `PRICE_META` (map id → {updated_at, source})
- `PROVENTOS_MONTHS` (24m axis), `PTAX_HISTORY`, `ptaxOf()`
- `PROVENTOS_HISTORY` (24m sintético por ativo aplicando regras de pagamento por classe)
- `OPTION_PREMIUMS_TAGGED` (OPTION_PREMIUMS com ym/klass/country/fi)

**Helpers**:
- `priceMetaOf(a)`, `priceAgeStr(iso)`, `priceFreshness(iso, source)`, `aggregatePriceAge(assets)`
- `proventosChartData({months, breakdown, currency, includeSynthetic})`
- `fmtChart(v, ccy, compact)`

**Icons adicionados**: `refresh`, `alert-triangle`, `edit-2`

**Componentes novos**:
- `<PriceRefresh />`
- `<ProventosStackedBar />`
- `<ProventosChart />`

**Componentes modificados**:
- `<TopBar>` — adiciona `<PriceRefresh />`
- `<AtivosTable>` — coluna `Atualizado` com dot + idade + botão refresh
- `<AtivoDetailPage>` — botão Atualizar/Editar preço no header + tile "Preço atual" com freshness
- `<ProventosPage>` — chart no topo, novo card "Por tipo" 5-chip, linha slim de totais
- `<Dashboard>` — card Proventos vira chart compact + lista "Por tipo" sempre com 5 tipos

---

## 5. Defaults & decisões (não re-litigar)

- Chart default: `breakdown=klass`, `currency=BRL`, `period=12m`
- `includeSynthetic` default = `true` em todo contexto (Proventos page state, Dashboard card)
- Synthetic premium **nunca** entra em DY/YoC do underlying
- Por Tipo: 5 categorias sempre exibidas; sintético dim quando off
- Topbar dot color = pior tier entre ativos com fonte API (manuais ignorados)
- Auto-refresh diária 18h (cron)
- Sources: BRAPI / YAHOO / COINBASE / TESOURO / MANUAL — sem outras na V1
- Manuais usam thresholds 30d/90d em vez de 24h/7d

---

## 6. Specs sugeridas (numeração continua da kickoff)

| # | Título | Escopo |
|---|---|---|
| 22 | Asset price source + freshness | Schema (price_updated_at, price_source), enum, migrations, basic API GET enriched |
| 23 | Price refresh API + brapi/yahoo/coinbase integrations | `POST /api/prices/refresh` + per-source adapters + tests with mocks |
| 24 | Price refresh background job | APScheduler ou similar, daily 18h, audit log |
| 25 | Topbar `<PriceRefresh />` component | UI completa do popover + loading states |
| 26 | Ativos page — Atualizado column + per-row refresh | Frontend only (consome endpoints 22-23) |
| 27 | Asset detail — refresh button + KPI freshness | Frontend only |
| 28 | Manual price edit (PATCH) | UI modal/inline edit pra MANUAL sources + audit |
| 29 | OPTION_PREMIUM derived view + UNION in chart endpoint | SQL view ou repository method |
| 30 | `GET /api/distributions/chart` endpoint | Acepta breakdown/currency/period/include_synthetic |
| 31 | `<ProventosChart />` component | All props, hover tooltip, all 3 toggles, KPIs |
| 32 | Proventos page redesign | Inject chart + 5-chip Por Tipo + slim totals |
| 33 | Dashboard Proventos card redesign | Compact chart + 5-type list always-visible |

**Dependências**: 22 → 23 → 24, 25 → 26 → 27 → 28 (frontend), 29 → 30 → 31 → 32 → 33

---

## 7. Open items (não-blocking)

- Sort por staleness na página Ativos
- Bulk "Atualizar selecionados"
- Tooltip rico no chart (hoje só mostra segmentos; falta % de cada)
- Drill-down: clicar numa barra do chart → ir pra lista filtrada por aquele mês
- 36M de período (hoje cai pra 24M porque só temos 24 de dados)
- Snapshot mensal de PTAX rate populado retroativamente
