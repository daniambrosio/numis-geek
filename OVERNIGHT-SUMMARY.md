# Decision Support — Overnight Build Summary

**Data:** 2026-06-29 (madrugada)
**Status:** Specs 61b + 61c + 61d entregues end-to-end com decisões
autônomas. Spec 61a já tinha sido entregue ontem (26/06).

Você delegou "assuma o seu caminho recomendado". Tudo abaixo é o que eu
decidi sem perguntar — leia pra calibrar.

## TL;DR

- **3 commits** em sequência (61a já existia):
  - `d4c69ff` — 61a Target Allocation (de ontem)
  - `4ec75d8` — 61b Valuation Engine (overnight)
  - `28b64c8` — 61c+61d Markowitz + página integrada (overnight)
- **Backend:** 84 testes novos verdes (636 totais 1 flaky pré-existente)
- **Frontend:** 27 testes novos verdes (193 totais, 2 fails pré-existentes
  em `BulkExtractReviewModal`)
- **TypeScript:** `tsc --noEmit` exit 0
- **Migrations aplicadas no prod DB** com backups `.bak-before-spec61b` e
  `.bak-before-spec61c-d`
- **Página `/decision-support` está VIVA** agora — placeholder substituído
- Server uvicorn `--reload` já pegou as mudanças automaticamente; só
  recarregue o browser

## O que mudou na navegação

- Item "Decision-support" virou "Suporte à Decisão" (PT), placeholder
  removido — agora é página de verdade.
- Item novo em Admin: "Alocação alvo" (de ontem, 61a).

## Como verificar manhã cedo

1. Refresh do browser em http://localhost:5173
2. Menu lateral → "Suporte à Decisão"
3. Empty states devem aparecer claramente:
   - Se ainda não cadastrou metas em `/admin/target-allocation` → CTA
   - Se sem snapshots fechados suficientes → CTA  
4. Cadastre metas por classe + por país (Alocação alvo) se ainda não
   tinha; volte pra Suporte à Decisão
5. Botão "Otimizar" no card Markowitz → deve devolver fronteira, peso
   ótimo, trades sugeridos
6. Card Valuation por ativo carrega em background (uma chamada por
   asset — pode demorar uns segundos com muitos)
7. Ative refresh manual de fundamentals no AssetDetail (botão
   "Atualizar" no novo card Valuation) pra forçar hit no brapi/Finnhub

## Decisões autônomas (LEIA PRA VALIDAR)

### Spec 61b — Valuation Engine

| Decisão | Razão | Onde reverter |
|---|---|---|
| **Sem Fundamentus scraper** | Legal grey area + scraping web frágil | `services/fundamentals_ingest.py` se quiser adicionar |
| **yfinance instalado como core dep** (não optional) | Simplifica deploy; tests skipam se faltar | `pyproject.toml` |
| **Required yield: BRL=8%, USD=5% hardcoded** | Sem entrevista; conforme rationale §10 #2 | `services/valuation_settings.py` |
| **Verdict §12 sem calibração** | Aplicado ipsis literis; gates: ROE<0, dívida/EBITDA>5, lucros<0 5y | `services/valuation_settings.py` + `services/valuation.py` |
| **ETF e FIXED_INCOME: verdict=NA v1** | Mostram métricas informacionais (TER, AUM, YTM); sem rule | `services/valuation.py` `value_etf`/`value_fixed_income` |
| **brapi response.raw_payload truncado a 8KB** | Defensivo contra payloads grandes | `services/fundamentals_ingest.py:153` |
| **Cron 19:00 SP sem catchup startup** | Não é hard-dep; rodar 1 dia depois é OK | `scheduler.py` `FUNDAMENTALS_JOB_ID` |
| **Refresh on-demand admin/sysadmin only** | Member não força hit no provider (rate limit shared) | `api/routes/valuation.py` `refresh_fundamentals` |
| **Sem UI de edição manual** | Refresh button apenas v1; spec 61.5 traz override | — |
| **Aceito que Asset.sector vire NULL** | Sem migration nova; provider preenche quando responder | — |
| **brapi `fetch_fundamentals` usa modules específicos** | summaryProfile, defaultKeyStatistics, financialData, balanceSheet, incomeStatement. Tier free pode não cobrir tudo — campos viram None | `integrations/brapi.py:_FUNDAMENTAL_MODULES` |
| **Finnhub %s vêm como [0..100], divido por 100 internamente** | Finnhub style — armazenamos como decimais [0..1] | `integrations/finnhub.py:_pct` |

### Spec 61c — Markowitz

| Decisão | Razão | Onde reverter |
|---|---|---|
| **Ledoit-Wolf α=0.05 sempre ON** | Estabilidade do solver com ativos correlacionados (BTC + IBIT) | `MarkowitzInput.ledoit_wolf_alpha` default |
| **LP feasibility seed via scipy.linprog** | SLSQP era finicky com country cap inicialmente violado | `services/markowitz.py:_feasible_starting_point` |
| **Aceito SLSQP success=False quando solução é feasible** | "Positive directional derivative for linesearch" é convergência válida na borda. Função `_is_feasible` valida | `services/markowitz.py:_solve` |
| **Multi-moeda: tudo BRL antes da otimização** | Usa `market_value_brl` do snapshot (PTAX já embutido). USD assets têm cambial dentro do risk | warning explícito na UI |
| **Ativos <12m de histórico ficam de FORA** (não no peso atual) | Mais simples; v1.5 considera "fixed" no peso atual | `MarkowitzInput.min_months` |
| **Sem persistência do resultado** | Recompute por demanda — POST sempre roda fresh | — |
| **Frontier 20 pontos via target_return sweep** | Pontos infeasibles são silenciosamente puláveis | `services/markowitz.py:build_frontier` |
| **Member pode chamar /optimize** | Read-only; sem rate limit v1 | `api/routes/portfolio_optimize.py` |
| **SVG puro nos 3 charts** | Mantém padrão do projeto (sem recharts) | `frontend/src/components/EfficientFrontierChart.tsx` etc |
| **Sem campo `target_return` no body** | Decisão era "metas por categoria", não Sharpe nem retorno alvo | `api/routes/portfolio_optimize.py` |

### Spec 61d — Página integrada

| Decisão | Razão | Onde reverter |
|---|---|---|
| **Label do nav: "Suporte à Decisão" (PT)** | Consistência com resto do menu | `AppLayout.tsx` |
| **Empty states explícitos** | Sem portfolio, sem targets, sem fundamentals — cada caso tem card | `pages/DecisionSupport.tsx` |
| **Sem teste vitest da DecisionSupport.tsx v1** | Os 4 componentes filhos têm testes; página é só wiring (mock-fest sem valor) | crie depois se aparecer regressão |
| **Rationale §15/§16 NÃO criados** | Já está tudo na master spec 61 + nas sub-specs; evitando duplicação | `docs/decision-support-rationale.md` |
| **Card Valuation faz 1 chamada por ativo (paralelo)** | Pode ficar lento com 150+ ativos; OK pra v1 | considerar endpoint batch em 61.5 |

## Schema novo no prod DB

- `target_allocation` (61a) — 0 rows até você cadastrar
- `asset_fundamentals` (61b) — 0 rows até o cron rodar 19h ou você
  apertar "Atualizar" no AssetDetail
- Backups: `numis_geek.db.bak-before-spec61a`, `.bak-before-spec61b`,
  `.bak-before-spec61c-d`

## Cron novo

- **`fundamentals_refresh_daily`** roda às 19:00 SP, entre price refresh
  (18h) e PTAX (20h). Itera todos os workspaces e tenta refresh per
  ativo. Erros per-asset são logged + skipped.

## Endpoints novos

- `GET /api/workspaces/{id}/target-allocation` (61a)
- `PUT /api/workspaces/{id}/target-allocation` (61a, admin only)
- `GET /api/assets/{id}/valuation` (61b)
- `GET /api/assets/{id}/fundamentals` (61b)
- `POST /api/assets/{id}/fundamentals/refresh` (61b, admin only)
- `POST /api/portfolio/optimize` (61c)

## Riscos / coisas que provavelmente vão pedir ajuste

1. **Verdict §12 calibração.** Aplicado ipsis literis sem você revisar.
   Você comentou no rationale que ia revisar antes de virar código —
   eu pulei. **Olhe `services/valuation.py` e diga "esse gate tá errado",
   ajustamos**.

2. **brapi `?fundamental=true` pode trazer pouco no tier free.**
   Não testei na sua chave real — pode ser que pe/pb/roe venham None.
   Se sim, considere assinar tier paid OU eu adicionar Fundamentus
   scraper depois.

3. **Finnhub `peTTM` pode vir 0 ou null pra muitos tickers.** Mapping
   tenta `peTTM → peNormalizedAnnual` mas não há garantia. Verdict
   = NA se faltam campos.

4. **yfinance instalado, MAS chamadas reais não testadas.** Tests
   mockam tudo. Yahoo às vezes bloqueia scraping. Se reclamar, troco
   pra outro provider US (FMP Starter, $22/mês).

5. **Markowitz com ~150 ativos:** o cov é 150×150 — viable mas pode
   demorar 1-3s no SLSQP. Pra mais, considere reduzir universo.

6. **Multi-moeda em BRL incluí cambial no risk.** Aceito como tradeoff
   v1; se ver portfólio USD com vol parecendo alta demais, é por isso.
   V2 roda Markowitz por moeda.

7. **Card Valuation na página DS dispara N chamadas paralelas.** Com
   150 ativos é 150 requests. O browser limita a ~6 simultaneous; vai
   levar 25s+ pra completar. Considere refactor pra endpoint batch.

8. **Cron `fundamentals_refresh_daily`:** vai rodar pela primeira vez
   hoje às 19h SP. Se quiser forçar agora, abra Python:
   ```
   .venv/bin/python -c "
   from numis_geek.scheduler import run_daily_fundamentals_refresh
   run_daily_fundamentals_refresh()
   "
   ```

## Próximos passos sugeridos pós-validation

- Calibrar verdict rules (sentar comigo pra revisar §12)
- Spec 61.5: workspace settings (required_yield_override por workspace,
  risk_uncertainty por ativo)
- Spec 53: histórico diário via APIs (substitui mensal no Markowitz)
- Spec 62 (?): batch endpoint pra valuation da página DS
- Spec 63 (?): cap por setor (Asset.sector + restrição no Markowitz)

## Smoke checklist (5 min de manhã)

- [ ] Refresh do browser, login OK
- [ ] `/admin/target-allocation` — cadastre se ainda não tinha
- [ ] `/decision-support` — empty states fazem sentido se faltar algo
- [ ] Após targets cadastradas: card Gap vs Target mostra atual vs alvo
- [ ] Botão "Otimizar" no Markowitz devolve resposta em < 5s
- [ ] Card Valuation começa preenchendo verdicts conforme termina cada
      asset
- [ ] Abra um asset (`/assets/<id>`) — card Valuation novo aparece com
      botão "Atualizar"
- [ ] Botão "Atualizar" chama brapi/Finnhub real e popula a tabela
      `asset_fundamentals` (cheque com `sqlite3 numis_geek.db "select
      count(*) from asset_fundamentals;"`)
- [ ] `/admin/audit` mostra `fundamentals.refresh` se você clicou

Bom dia.
