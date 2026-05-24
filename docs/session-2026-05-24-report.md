# Sessão 2026-05-24 — Specs 18, 19, 20, 21

Relatório consolidado pra leitura matinal. Tudo commitado em `main`.

```
611e0af Specs 20 + 21 — Portfolio page + Distributions UI
bf448ec Spec 19 — Attachments + FinancialInstitution.country + make backup
bc93de0 Spec 18 — frontend shell cleanup + Novo composers
```

Sinais verdes: **238 pytest · npm build limpo · 4 migrations aplicadas**.

---

## Visão geral do que tem hoje no app

Sidebar PT-label · rotas EN. Pontos de entrada operacionais (não-stub):

| Sidebar | Rota | Estado |
|---|---|---|
| Dashboard | `/dashboard` | já existia |
| **Patrimônio** | `/portfolio` | **Spec 20** novo |
| Decision-support | `/decision-support` | stub (Spec 24) |
| Ativos | `/assets`, `/assets/:id` | já existia |
| Lançamentos | `/asset-movements` | renomeado no Spec 18 |
| **Proventos** | `/distributions` | **Spec 21** novo |
| Contas | `/accounts` | já existia |
| Auditoria | `/admin/audit` | já existia |
| Sistema · Usuários | `/admin/users` | sysadmin-only |
| Sistema · Inst. Fin. | `/sysadmin/financial-institutions` | já existia |
| Sistema · Ativos | `/sysadmin/assets` | já existia |
| Sistema · Integrações | `/sysadmin/integrations` | já existia (tokens de API) |
| Sistema · PTAX | `/sysadmin/ptax` | já existia |

Ainda "soon" (deferidos por estarem na **parte financeira**): Movimentações, Cartões, Faturas, Orçamento, Instituições, Decision-support.

---

## Spec 18 — Frontend shell cleanup *(commit bc93de0)*

### O que fiz
- **URLs PT → EN** com redirects de 1 ciclo:
  `/lancamentos → /asset-movements` · `/proventos → /distributions` ·
  `/patrimonio → /portfolio` · `/onde-investir → /decision-support` ·
  `/instituicoes → /financial-institutions` · 4 da parte financeira renomeadas (rotas só, páginas continuam "soon").
- **Sidebar nas 6 seções do protótipo**, "Usuários" movido pra Sistema (sysadmin-only no menu; rota continua acessível por URL pra admin emergencial).
- **Novo dropdown contextual fiel ao protótipo** (`index.html:1115-1167`): 3 grupos (Investimentos · Caixa & Cartões · Cadastros), ícone + label + descrição + atalho letter, sparkle no default contextual, footer "sugerido pelo contexto atual". Itens desabilitados clicáveis com toast "em breve".
- **`LancamentoModal.tsx` → `MovementComposer.tsx`** completamente reescrito pra bater no protótipo (`index.html:4242-4387`): 6 tipos em grid 3×2 com label+hint, pré-visualização ao vivo (Net + transição de posição), atalho `⌘↵` salvar / `esc` fechar.
- **OptionModal mantido** (decisão revisada): cobre fluxo distinto "criar OPTION asset + primeiro movement" via "+ Opção" / "+ Nova opção" no AssetDetail. Eu havia movido pra dentro do MovementComposer; o protótipo deixa separado e tu validou.
- **Notion sync skipped pra opções**: `_MOVEMENT_TYPE_PT` estava sem os 6 tipos de opção → KeyError 500 no bulk sync. Solução: adicionei `NotionSyncStatus.SKIPPED` (migration `e8f9a0b1c2d3` em 5 tabelas), `push_asset_movement` detecta option lifecycle e marca como SKIPPED antes de tocar o Notion. Documentado em `docs/options-rationale.md §3.3`.

### Decisões tomadas
- **Q3 sidebar**: "+Opção" no toolbar do AssetDetail volta com cor **indigo** (não violet — violet só pra badge de classe, não pra ação) e **dentro** do `OpenOptionsCard` também ganha "+ Nova opção" indigo (espelho do protótipo `index.html:3196-3198`).
- **Q4 Movement vs Option**: confirmamos depois de um vai-e-vem que a UX correta é: `MovementComposer` mostra **só** os 6 tipos normais; opções têm seu próprio fluxo via `OptionModal`.
- **Movimento de URL `/lancamentos` → `/asset-movements`**: discutimos `/movements` (curto) vs `/asset-movements` (completo) — tu escolheu o segundo, por consistência com nome de entidade.

### Files
- novos: `frontend/src/components/MovementComposer.tsx`, `frontend/src/pages/AssetMovements.tsx`, `frontend/src/pages/DecisionSupport.tsx`, `specs/18. Frontend Shell Cleanup.md`, `alembic/versions/e8f9a0b1c2d3_notion_sync_skipped.py`
- renomeados/deletados: `LancamentoModal.tsx`, `Lancamentos.tsx`
- modificados: `App.tsx`, `AppLayout.tsx`, `AssetDetail.tsx`, `OpenOptionsCard.tsx`, `AssetModal.tsx` (KLASS adicionou OPTION), `admin/Assets.tsx`, `sysadmin/Integrations.tsx` (PROVIDER_COLOR adicionou NOTION), `services/notion_sync.py`, `models/notion_sync.py`

---

## Spec 19 — Attachments + FI.country + make backup *(commit bf448ec)*

### O que fiz
- **`FinancialInstitution.country`** ISO-2 NOT NULL (default `BR`). Backfill na migration:
  - **US**: Avenue, Coinbase, Wise
  - **BR**: BTG, Bradesco, Caixa, Clear, Fix, Itaú, Mercado Pago, Particular, Santander, XP
- **Tabela `attachment`** polimórfica:
  - `source_type ∈ {asset, movement, distribution}` + `source_id` (app-level FK).
  - `kind`, `filename`, `mime_type`, `size_bytes`, `storage_key`, `uploaded_by`, `is_active`.
  - Soft-delete (`is_active=false`); file no disco permanece pra recovery.
- **Storage local em `./data/attachments/{workspace_id}/{uuid}.{ext}`**:
  - MIME whitelist: `image/png · image/jpeg · image/webp · application/pdf · text/csv`.
  - Size limit: 10 MB.
  - Path-traversal safe (`absolute_path` resolve via `Path.resolve()` e valida com `relative_to(ROOT)`).
- **4 endpoints CRUD** (`/attachments`):
  - `POST` (multipart upload) · `GET ?source_type=&source_id=` · `GET /{id}/download` (FileResponse) · `DELETE` (soft).
  - Autorização: workspace-scoped, sysadmin cross-workspace, masking 404 em vez de 403.
- **`make backup`** target — `sqlite3 numis_geek.db .dump | gzip > data/backups/numis_geek-{ts}.sql.gz`. Output ~725 KB compactado. Roda quando tu quiser snapshot textual versionável.
- **`python-multipart`** adicionado às deps (FastAPI Form/File requirement).
- **22 testes novos**: 19 pra attachments (MIME whitelist, size limit, source validation, workspace isolation, sysadmin override, soft-delete, path-traversal safety) + 3 pra FI.country.

### Decisões / assumptions
- **Atachments polimórficos só em `asset · movement · distribution`** (não em `transaction` ainda — Transaction não existe). Quando a Spec 23+ criar a Transaction, é só estender o enum.
- **`./data/attachments/` e `./data/backups/`** ficam **fora do git** (já cobertos pelo `/data/*` no `.gitignore`). Quando migrar pra VPS, esses dois caminhos viram volume separado (rsync ou bucket).
- **Backup textual**: gzipado, vai pra `./data/backups/` com timestamp. Não versiono no git porque cresce rápido; rode `make backup` quando quiser snapshot diff-able.

### Files
- novos: `src/numis_geek/models/attachment.py`, `src/numis_geek/services/attachment_storage.py`, `src/numis_geek/api/routes/attachments.py`, `alembic/versions/f9a0b1c2d3e4_attachments_and_fi_country.py`, `tests/test_attachments.py`, `specs/19. Attachments and FI country.md`
- modificados: `models/__init__.py`, `models/financial_institution.py`, `api/app.py`, `api/routes/financial_institutions.py` (expõe country + aceita no request), `frontend/src/lib/api.ts` (campo country no type), `Makefile` (target `backup`), `pyproject.toml` (python-multipart)

---

## Spec 20 — Portfolio (`/portfolio`) *(commit 611e0af)*

### O que fiz
- **`services/portfolio_summary.py`** — agrega o último `PortfolioSnapshot` + seus items em:
  - `by_class` (donut data por classe).
  - `by_country` (donut data por país BR vs US).
  - `by_custodian` (lista ordenada por valor: fi_short, logo_slug, value, pct, asset_count).
  - `top_holdings` (10 maiores posições com class/country/fi).
  - `history` (últimos 12 snapshots com `by_class` breakdown por mês).
- **`api/routes/portfolio.py`** — `GET /portfolio` (workspace-scoped; sysadmin precisa de `?workspace_id=`).
- **`pages/Portfolio.tsx`** — espelha o protótipo (`index.html:5231-5475`):
  - Hero card (Total BRL/USD + sparkline + 3 mini-KPIs: Investido / Valor atual / Ganho).
  - Donut por classe (top 8 + "Outros") com lista lateral de %.
  - Donut por país (BR/US) com flags + barras de progresso.
  - Custodian list (FI logo + barra de progresso + % + asset_count). Click navega pra `/financial-institutions` (placeholder; rota é stub do Spec 22).
  - Stacked-bar history 12m (todas as classes que aparecem no DB).
  - Top-10 table com class color stripe + flag + custodian; click navega pra `/assets/:id`.
- **7 testes novos**: service-level (latest snapshot, breakdowns), endpoint (auth, sysadmin workspace_id, cross-workspace block).

### Decisões / assumptions críticas
- **Source strategy: snapshot-first.** Hoje **`Asset.current_price` é NULL nos 160 ativos** (confirmamos isso no debug do ITUB4 ontem). Portfolio usa o último `PortfolioSnapshotItem.market_value_brl` direto. Quando tu rodar o refresh de preços (`/sysadmin/integrations` + Spec 12) e os assets tiverem `current_price`, é trivial adicionar um modo "live" no service.
- **Estado real do DB**: 28 snapshots (12 últimos cobrem maio/2025 → abril/2026), 158 items no snapshot mais recente, total = R$ 12.468.723,90 em 30/04/2026.
- **Patrimônio mostrado é só *investido*** (não inclui caixa/cartões), igual ao protótipo. O *net worth completo* (Investimentos + Caixa − Cartões) entra com o Dashboard quando Transactions existirem.
- **Não há live-mode** ainda; quando o refresh de preços (`current_price`) rodar consistentemente, posso adicionar `source = "live"` no service.

### Files
- novos: `src/numis_geek/services/portfolio_summary.py`, `src/numis_geek/api/routes/portfolio.py`, `frontend/src/pages/Portfolio.tsx`, `tests/test_portfolio.py`, `specs/20. Portfolio.md`
- modificados: `src/numis_geek/api/app.py`, `frontend/src/lib/api.ts` (PortfolioOut + getPortfolio), `frontend/src/App.tsx`, `frontend/src/components/AppLayout.tsx` (Patrimônio não tem mais `placeholder`)

---

## Spec 21 — Distributions (`/distributions`) *(commit 611e0af)*

### O que fiz
- **`DistributionComposer.tsx`** — fiel ao protótipo (`index.html:4396-4498`):
  - 4 tipos em grid 2×2 (DIVIDEND/INTEREST/JCP/SECURITIES_LENDING) com label+hint.
  - Data + Instituição em 2 colunas.
  - Asset (filtrado pelos assets do FI selecionado); **opcional** quando type=`SECURITIES_LENDING` (Avenue genérico).
  - Bruto + IR retido. Currency derives from asset.
  - Pré-visualização ao vivo (líquido + ativo/origem).
  - ⌘↵ salvar / esc fechar.
- **`DistributionDetailPanel.tsx`** — slide-over right-side, espelha `LancamentoDetailPanel`:
  - Header com type badge + ccy pill + asset (ou "Sem ticker · via {FI}").
  - Asset/FI summary card.
  - Fields grid: Data, Moeda, Bruto, IR retido, Líquido, FX rate, Origem, Status.
  - Notes.
  - Footer: Editar / Desativar.
  - **Sem Notion sync section** (importer é one-way; `push_distribution` não existe no backend — não é prioridade).
- **`pages/Distributions.tsx`** — espelha `ProventosPage` (`index.html:3836-4079`):
  - PageHeader com contador + botão "+ Novo Provento".
  - Hero 2 colunas: Total líquido + Por tipo (4 tiles com %).
  - Filtros: search + view toggle (Por mês / Por ativo) + multi-chip de tipo.
  - View=month: tabela agrupada por YYYY-MM; click abre DetailPanel.
  - View=asset: agregação por ativo (eventos + total BRL); click navega pra `/assets/:id` quando há ticker.
- **Novo dropdown**: "Provento" agora habilitado, sparkle aparece em `/distributions`, click abre composer via `?compose=distribution`.
- **Notion importer** (`scripts/import_notion_distributions.py`) — verificado em sync via dry-run:
  - 1761 pages no Notion.
  - 1715 já no DB local (importadas em 2026-05-23 numa rodada anterior).
  - 46 rows "Débito" skipped por design (não são proventos, são debitos de IR).
  - 0 inserts pendentes; 0 erros. **Sincronia confirmada.**

### Decisões / assumptions
- **OPTION_PREMIUM synthetic UNION** (toggle "Incluir dividendos sintéticos" do protótipo) — **deferido**. Para implementar precisa do helper `services/proventos.list_proventos(include_synthetic)` mencionado em `options-rationale.md §5` mas não existe no backend. Vai entrar quando a UI precisar exibir os SELL_OPEN/BUY_TO_CLOSE de opções como proventos sintéticos.
- **DateRangeButton** no protótipo era visual-only (sem filtro real); eu omiti completamente em vez de fazer um botão decorativo.
- **Push Notion das distributions criadas localmente**: não implementei. O importer é one-way (Notion → local). Se virar caso de uso, eu adiciono `push_distribution` no `services/notion_sync.py`, mas hoje (V1) não há ROI.

### Files
- novos: `frontend/src/components/DistributionComposer.tsx`, `frontend/src/components/DistributionDetailPanel.tsx`, `frontend/src/pages/Distributions.tsx`, `specs/21. Distributions.md`
- modificados: `frontend/src/App.tsx`, `frontend/src/components/AppLayout.tsx` (remove placeholder + enable Novo provento), `frontend/src/lib/api.ts` (já existiam os types)

---

## Coisas que descobri / decisões intermediárias que merecem atenção

### 1. `current_price` está NULL em todos os 160 assets
Confirmado no debug do ITUB4. Schema correto, services existem (`compute_position` retorna current_value=None quando price ausente), refresh de preço da Spec 12 nunca rodou (ou rodou e falhou — token brapi ausente?).

**Recomendação**: depois de acordar, login como sysadmin, ir em `/sysadmin/integrations`, verificar tokens. Se faltar BRAPI ou YFINANCE, cadastrar. Depois rodar refresh manual (botão "atualizar preços" em `/assets` que já existe da Spec 12). Aí `/portfolio` ganhará live-mode (e ITUB4 deixa de mostrar "—").

### 2. Tokens de API — debate ficou na fila
Conversamos sobre Notion (workspace-scoped) vs APIs globais (system-wide). **Decisão tua**: deixa como está agora; revisitar quando virar produto multi-user. Não toquei na Spec 11.

### 3. Notion DB schema não suporta option types
A Spec 17 introduziu 6 tipos novos de movement (`SELL_OPEN`, etc.) que **não existem como opção no select `Tipo Transação` do Notion**. Solução: option lifecycle types são marcados `SKIPPED` no notion_sync e nunca tentam fazer push. Esses 2 lançamentos (ITUBR364 + ITUBF475) vão sempre ter status SKIPPED. Quando a Spec quando-quer-que-seja decidir espelhar opções no Notion, é uma linha pra reabilitar.

### 4. Build do frontend está ~500 KB (gzip ~129 KB)
Vite tá avisando que o chunk passou de 500 KB. Por hora ignorei — code-splitting via lazy import é um polish pra depois. Não bloqueia nada.

### 5. UI de Attachments inline ainda não existe
Spec 19 entregou backend completo (table + storage + endpoints). A **UI inline** (⌘V cola imagem no composer, indicador `📄 +N` nas tabelas) **não está implementada**. Decisão consciente: entra com os DetailPanels do Spec 21 (que foi feito, mas o panel ainda não usa attachments) ou num spec dedicado de "polish dos panels". Você decide.

---

## O que está sólido pra rodar amanhã

Login → sidebar → **Patrimônio** mostra os R$ 12.468.723,90 com donuts/custodians/history/top-10.
Click em qualquer ativo → AssetDetail (lembrar que current_price=NULL → KPIs mostrarão "—" exceto preço médio/YOC; rodar refresh primeiro).
Sidebar → **Proventos** → 1715 distributions agrupadas por mês; toggle "Por ativo" mostra Itaú e Bradesco no topo.
Novo dropdown → "Provento" sparkle quando estiver em `/distributions`; "Lançamento" em `/asset-movements`; etc.
Botão Novo → criar provento de teste; salvar; aparece na tabela; click abre DetailPanel.

## Roadmap pós-21 (sugerido)

| Spec | Tema | Tamanho |
|---|---|---|
| 22 | Institutions + FI Hub (sem cards/transactions ainda) | médio |
| 23 | Conta detail variant investment | médio |
| 24 | Decision-support V1 (manual; sem providers) | grande |
| ⏸ | Caixa & Cartões: Transactions, CreditCard, Invoice, Budget | adiado, "parte financeira" |
| ⏸ | UI inline pra notes/attachments nos panels | adiado, polish |

Build dois caminhos em paralelo se quiser: (a) ir pro Spec 22 / 23 / 24 pra fechar a parte de **investimentos visíveis**; ou (b) priorizar polish dos panels + attachments inline pra deixar a base do investimento + experience refinada antes de adicionar superfícies novas.

---

*Relatório feito durante a sessão noturna 2026-05-23 / 2026-05-24.
Tudo testado (238 pytest verde), buildado (npm build limpo), commitado em main.*
