# Numis-Geek — Prototype

UI prototype for design validation, **before** rebuilding the actual frontend.

A throwaway reference artifact — not production code. The goal is to lock the
visual language, IA, and component patterns *visually* so the Claude Code
rebuild has a concrete target.

## How to view

Open `index.html` directly in a browser:

```
open prototypes/index.html
```

Single self-contained HTML file. No build step, no deps to install. Loads
React, ReactDOM, Babel, and Tailwind from CDN; everything else (icons,
charts, mock data, components) is inline.

## Routes

All sidebar items are real pages now (no more "soon" placeholders).

**Workspace**
- `#/dashboard` — net-worth hero, allocation, custodians, top movers, mixed activity feed
- `#/login` — standalone login page (renders without shell)

**Investimentos**
- `#/patrimonio` — drilldown: big donuts (class, country), custodian breakdown, allocation history (12 months stacked), top 10 holdings
- `#/ativos` — table with grouping toggles + filter chips; row click → asset page
- `#/ativo/{id}` — full asset detail page: 8 KPIs (Posição, Preço médio, Preço atual com data, P&L, Variação, Rentabilidade, YoC, DY), price chart, full Lançamentos and Proventos tables (clickable rows), notes & documentos, detalhes
- `#/lancamentos` — quick-add bar, type chips, table grouped by month; row click → Lançamento detail panel (notes + attachments)
- `#/proventos` — type chips, view toggle (mês × ativo); row click → Distribution detail panel

**Caixa & Cartões**
- `#/movimentacoes` — cash transactions table (accounts + cards), source filter, category filter, reconciliação status
- `#/cartoes` — credit cards list
- `#/cartao/{id}` — credit card detail (open invoice + history)
- `#/faturas` — cross-card invoice history with filters
- `#/holerites` — payslip list (spec 77): 4 KPIs (bruto, descontos, líquido, alíquota efetiva), employer/type/year/settlement filters, table grouped by year, gross-up explainer, FGTS-per-employer card
- `#/holerite/{id}` — payslip detail: bruto → descontos → líquido cascade, line-by-line rubricas grouped by kind with category editor, liquidação card (linked transactions or "vincular"), FGTS aporte card, despesa reflex card
- `#/orcamento` — categorias × meses grid, color-coded by % usage

**Estrutura**
- `#/instituicoes` — FI cards
- `#/instituicao/{id}` — FI Hub (accounts + cards + assets at this FI)
- `#/contas` — checking + investment accounts
- `#/conta/{id}` — Conta detail (variant per type)

**Admin**
- `#/audit` — audit log table with action and user filters

## Top bar

- **Search** (kbd ⌘K) — visual only
- **Novo** — dropdown with all create options. Context-aware: highlights the most likely action for the current route. Wired to real composers for Lançamento, Provento, Movimentação, Cartão tx, Ativo, Conta, Cartão.
- **`Aa`** — Comfort mode toggle. Scales up small text classes (10/11/12/13px) for mobile reading. State persists.
- **Eye icon** — Privacy mode. Blurs every monetary value via CSS. Hover any value to peek. State persists.
- **Theme** — segmented control: light / dark / system. State persists.
- **Avatar** — visual only.

## Composers (modal-style, type-adaptive)

Open via Novo dropdown or contextual buttons. ESC and click-outside close them.

- **MovementComposer** — 6 movement types; form reshapes per type; live preview shows net, position transition (`1.200 → 1.300 PETR4`), cash side debit/credit, FX info on USD events.
- **DistributionComposer** — 4 types; asset becomes optional for `SECURITIES_LENDING` (Avenue case).
- **TransactionComposer** — direction toggle (in/out), category auto-suggest by description.
- **CardTxComposer** — international purchase mode (USD + IOF).
- **PayslipImportModal** — two steps: upload (employer + expected type + dropzone) → review (competência/tipo/ativo FGTS editáveis, rubrica table with kind + inline category select, sum-drift alert vs. the printed líquido, confidence pills, preview block with bruto/descontos/líquido/aporte FGTS/gross-up). Import button disabled while the sum diverges.
- **NewAssetComposer** — class/country/account/ticker/name/CNPJ.
- **NewAccountComposer** — type/FI/name/currency/opening balance.
- **NewCardComposer** — FI/brand/name/last4/limit/close+due days.

## Detail panels (slide-overs)

ESC closes them.

- **AssetDetailPanel** — KPIs, custódia, sparkline, recent lançamentos + proventos.
- **LancamentoDetailPanel** — fields grid, notes textarea, attachments list with paste/upload zone.
- **DistributionDetailPanel** — same pattern; handles asset-less rows ("Sem ticker") for SECURITIES_LENDING.

## Conventions baked in

- Dark mode default; theme toggle (light / dark / system).
- Indigo accent (`indigo-500`).
- Asset class color tokens (11 classes — `KLASS` map in `index.html`).
- Currency pills (`BRL` amber, `USD` emerald) on every monetary value.
- Tabular numerals (`tnum` class) on every numeric column.
- `.money` class on every monetary span — Privacy mode blurs these via CSS.
- PT-BR copy throughout; entity names in code are English.

## Mock data

Calibrated to the brief's real volumes (~158 assets, ~13 custodians) but with
a representative sample (~30 assets) actually rendered.

Top of `<script type="text/babel">`:
- `FIs` — 13 financial institutions
- `ACCOUNTS` — 12 accounts (checking + investment only)
- `CARDS` — 3 credit cards (separate entity from accounts)
- `ASSETS` — 32 assets, each linked to an investment account via `account` FK (FGTS is split into one asset per employer, mirroring the real DB)
- `MOVEMENTS` — 30 AssetMovements
- `DISTRIBUTIONS` — 24 Distributions (3 with `asset = null`)
- `TRANSACTIONS` — 34 Transactions (cash + card; 8 are salary credits carrying a `payslip` FK)
- `EMPLOYERS` — 3 employers (Meli current, Carrefour + Eletrobras legacy), each with its own FGTS asset
- `PAYSLIPS` — 24 payslips generated from line templates; totals are always derived via `payslipTotals`, never hardcoded
- `PAYSLIP_TX` — payslip → transaction links. Only 2026 has bank statements imported; 2025 payslips are deliberately `UNSETTLED`
- `INVOICES` — 12 invoices across 3 cards
- `AUDIT_ENTRIES` — 15 sample audit log entries
- `CATEGORIES` — 11 budget categories
- `BUDGET_TARGETS` + `BUDGET_ACTUALS` — annual budget data
- `MOVEMENT_NOTES` / `DISTRIBUTION_NOTES` / `ASSET_NOTES` — per-row notes + attachments
- `LAST_TRADE_DATE` — price update date by asset class
- `ACTIVITY` — derived feed for Dashboard

PTAX hardcoded at `R$ 5,12` per USD.

## Conceptual model

The screens design against the **target schema** in
[`../docs/conceptual-model.md`](../docs/conceptual-model.md). Notable choices:

1. **Net worth equation visible** on Dashboard hero: `Investimentos + Caixa − Cartões`.
2. **Asset belongs to an Investment Account** (not directly to FI). The Conta investment page shows account-scoped assets.
3. **CreditCard is its own entity** — separate from Account; lives at `#/cartao/{id}`.
3b. **Payslip is a fatura invertida** (spec 77) — a document with N lines settling into 1..N cash credits. The bank credits the *líquido*; bruto, INSS/IRRF and payroll-deducted expenses exist only on the payslip. Two rules the screens encode:
   - **Gross-up**: a deduction that is a real expense (plano de saúde, odonto) is added to *both* renda and despesa. The month's resultado still equals the cash credit, but the despesa média stops underreporting. INSS/IRRF (`tax`) and the adiantamento offset (`advance`) stay out of both.
   - **ADVANCE is a cash-timing document**, not an earnings one: its net counts as income, its gross never enters the bruto/alíquota totals (the monthly payslip already carries the full bruto and deducts the advance).
4. **Distribution can have `asset = null`** — Avenue's "rendimento de aluguel" case.
5. **Transaction is polymorphic** — belongs to either an Account (cash) or a CreditCard (charge).
6. **Activity feed mixes ledgers** on Dashboard: AssetMovements (blue), Distributions (amber), Transactions (violet).
7. **Reconciliação is a button** on Conta/Cartão detail toolbars, not a sidebar destination.
8. **Variação vs Rentabilidade** distinction: Variação = pure price change; Rentabilidade = price change + proventos received.

## What this prototype is **not**

- Production code. CSS is opinionated for a single-file SPA, not for the React + Vite project structure.
- Source of truth on data. Mock numbers are illustrative.
- Mobile-responsive layout. The Comfort toggle helps mobile reading, but the sidebar doesn't collapse on small screens — that's a frontend rebuild concern.
- Empty / error / skeleton states across all pages. A few placeholders exist but no systematic coverage.
- Light mode polish. Dark mode is first-class; light mode is functional but rough on hover states.
