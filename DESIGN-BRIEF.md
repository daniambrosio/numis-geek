# Numis-Geek — Design Brief

> Document intended to be fed into an AI design tool (v0, Galileo, Lovable, Magic Patterns, etc.) to generate UI prototypes for a personal finance management web app.

---

## 1. Product in one paragraph

**Numis-Geek** is a personal finance management web app for a single sophisticated owner (and eventually a small family workspace). It consolidates two things that usually live in separate apps: **investment portfolio tracking** (stocks BR/US, FIIs, REITs, ETFs, Bonds, Funds, Crypto, real estate, vehicles, fixed income, FGTS, private pension, cash) and **expense tracking** (planned for a later phase). The user wants a calm, data-dense, dark-mode-friendly dashboard that gives them clarity about their net worth, dividend yield, asset allocation, and historical movements — without the flashy "trading app" energy. Domain language is **Brazilian Portuguese**; technical terms in English (BR/US/USD/BRL/PTAX/CDI/IPCA/FGTS).

---

## 2. Target user

**A single power user** ("Dani"), with these traits:

- Sophisticated investor: holds 181 assets across 12+ custodians (XP, Avenue, Itaú, BTG, Caixa, Bradesco, Santander, Wise, Coinbase, Mercado Pago, Clear, plus "Particular" for non-financial assets).
- Comfortable with dense tables and numeric data; does NOT want oversimplified or gamified views.
- Mostly uses dark mode on macOS.
- Prefers keyboard-friendly flows; will appreciate terse density over chrome.
- Speaks Portuguese (BR) day-to-day; reads English fine for technical labels.
- Roles model exists for future: `sysadmin`, `admin`, `member`. Today there is one `admin` (Dani) and one `sysadmin` (system maintenance only).

**The user is also the developer** of the project. Take that as license to assume technical literacy in copy and information architecture. Avoid hand-holding tooltips for basic financial concepts.

---

## 3. Core jobs to be done

In rough priority order:

1. **"What's my patrimônio total agora, em BRL e em USD?"** — net worth at a glance, broken down by asset class and country (BR vs US).
2. **"Quanto recebi de proventos nos últimos 12 meses?"** — dividend / interest received, with YoC and DY metrics per asset.
3. **Record a lançamento in under 30 seconds** — compra, venda, dividendo, juros, JCP, come-cotas, bonificação, subscrição. The form must adapt to the type.
4. **"O que tenho na XP?"** — drill into a custodian (financial institution) and see all accounts + assets there.
5. **Compare BR vs US allocation** — split charts.
6. **Inspect a single asset's history** — list of all lançamentos for that asset, current position, average cost, total invested vs total received.
7. **See zerados (closed positions)** — for IR / tax review; usually surfaced under a filter or toggle, never crowding the main "current portfolio" view.
8. **Future: track expenses against monthly/yearly budget** (out of scope for this brief — flag as "a later page in the same shell").

---

## 4. Domain model (entities + relationships)

```
Workspace ──┬─ User (admin/member)
            ├─ Account (checking | investment, BRL | USD, opening_balance)
            ├─ Asset (workspace-scoped, 14 classes, links to Custodian)
            └─ Lancamento (8 types, linked to one Asset, has currency + fx_rate)

System level (cross-workspace):
- Financial Institution (a.k.a. "Custodian" / "IF"): Itaú, XP, ..., Particular
- Sysadmin user
```

### Asset classes (14, with PT labels)

| Code | PT label | Notes / typical example |
|---|---|---|
| `STOCK_BR` | Ação BR | PETR4, ITUB4 |
| `STOCK_US` | Ação US | AAPL, MSFT |
| `FII` | FII | HGLG11 (BR REIT-like) |
| `ETF` | ETF | BOVA11, SPY |
| `REIT` | REIT | O, VICI (US real estate) |
| `BOND` | Bond | US Treasuries, corporate bonds in USD |
| `FIXED_INCOME` | Renda Fixa | CDB, Tesouro Direto, LCI, LCA |
| `FUND` | Fundo | BR investment funds (CNPJ) |
| `CRYPTO` | Cripto | BTC, ETH |
| `REAL_ESTATE` | Imóvel | apartments, houses, land |
| `VEHICLE` | Veículo | cars, motorcycles |
| `CASH` | Dinheiro | broker float, physical cash positions |
| `FGTS` | FGTS | BR forced-savings |
| `PRIVATE_PENSION` | Previdência Privada | PGBL, VGBL |

Each asset has: workspace, **custodian (required)**, class, optional ticker, optional CNPJ (for FUND), name, currency, subtype free-text, notes, `is_active` (soft delete for sold-out positions), audit metadata.

Specialized 1:1 child rows exist for `FIXED_INCOME` (issuer, maturity, indexer, rate) and `REAL_ESTATE`/`VEHICLE` (address, area, plate, etc.) — present in some rows, missing in many today (will be filled progressively).

### Lançamento types (8)

| Code | PT label | Has qty? | Has unit_price? | Has gross? | Special |
|---|---|---|---|---|---|
| `COMPRA` | Compra | yes | yes | computed = qty × price (override allowed) | — |
| `VENDA` | Venda | yes | yes | computed | — |
| `DIVIDENDO` | Dividendo | no | no | required > 0 | currency must match asset |
| `JUROS` | Juros / Cupom | no | no | required > 0 | currency must match asset |
| `JCP` | JCP | no | no | required > 0 | currency must match asset; BR-only |
| `COME_COTAS` | Come-cotas | no | no | required (semi-annual fund tax) | only `tax`, no fee |
| `BONIFICACAO` | Bonificação | yes | no | default 0 (override allowed for FMV) | free shares |
| `SUBSCRICAO` | Subscrição | yes | yes | computed | rights issue |

Lançamento always has: `event_date`, optional `settlement_date`, `currency`, `fx_rate` (default 1.0 — bridge to a future PTAX table), `notes`, `is_active`.

### Position (computed, not stored)

For each asset, on demand:

```
quantity_held = Σ qty (COMPRA + BONIFICACAO + SUBSCRICAO) − Σ qty (VENDA)
average_cost  = weighted avg of (qty × unit_price) over basis-affecting types
total_invested_brl = quantity_held × average_cost × fx_rate
total_received_brl = Σ net_amount × fx_rate of DIVIDENDO/JUROS/JCP
```

These derived values feed every dashboard chart and table.

---

## 5. Information architecture (current sidebar)

```
[Workspace section]
  Dashboard
  Ativos
  Lançamentos
  Contas
  Perfil

[Admin section — admin only]
  Usuários
  Audit log

[Sistema section — sysadmin only]
  Instituições Financeiras
  Ativos (cross-workspace)
  Contas (cross-workspace)

Top bar
  Theme toggle (dark / light / system)
  Logout
```

The sidebar is the primary nav. Each page has its own filters + actions (no global search yet — but a future "Cmd+K" surface is on the wishlist).

---

## 6. Key screens that need design

For each: existing state (rough), what it should become, key data shown.

### 6.1 Dashboard `/dashboard`

**Today:** placeholder with welcome message + quick links. **Effectively empty.**

**Should become — the most important page in the app:**

- Header card: **Patrimônio total** in BRL + the same in USD (toggle), with delta (week / month / YTD).
- Allocation donut chart: by asset class (14 categories collapse into ~6 visual buckets — group "small" classes into "Outros" beyond top 5 by value).
- Allocation bar/list: by custodian (top 5 + "outros").
- Allocation card: BR vs US (geographic split).
- "Proventos 12M" card: total dividends + JCP + interest received in last 12 months in BRL, with sparkline of monthly receipts.
- Top movers table (top 5 winners, top 5 losers, % return).
- Recent lançamentos (last 10): compact list with type icon, asset, date, amount.

**Visual priority:** dense, scannable, no marketing copy. Numbers should be the heroes. Icons may be used for asset class badges but never as decoration.

### 6.2 Ativos (Assets list) `/assets`

**Today:** flat table with class badge, ticker, name, currency, custodian, edit/deactivate actions, search + class filter + "show inactive" toggle.

**Should become:** the same table but with grouping options:
- Default flat table sorted by current value DESC
- Toggle: group by class | group by custodian | group by country (BR/US)
- Inline current position (quantity_held + value_brl) on each row when computed
- Search/filter UX should be at the top, with active filters as removable chips
- Click row → asset detail panel (slide-over from right) showing position metrics, recent lançamentos, "+ Novo Lançamento" button

### 6.3 Lançamentos `/lancamentos`

**Today:** filtered table with date, type badge, asset, qty, unit_price, net_amount, currency. Filters: asset (dropdown), type, date range, "show inactive". Modal for create/edit adapts per type.

**Should become:** keep the table but improve:
- Type filter as multi-select chips at the top
- Date range picker should be visible without expanding a filter panel
- Quick-add: a single-line composer at the top ("Novo lançamento: tipo + ativo + valor + data") that expands into the full modal only if type needs more fields
- Group rows by month visually (subtle date headers)
- Asset cell should show ticker + name + class color
- Inactive rows use opacity 60 + strikethrough on amount

### 6.4 Contas `/accounts`

**Today:** table of accounts + a tab "Ativos" that groups by custodian (collapsible).

**Should become:** more intentional split:
- Tab "Contas": flat table of all accounts (current implementation)
- Tab "Custodians" (rename "Ativos" → "Custodians"): treemap or card grid where each card represents a custodian with: logo, total value held, # of accounts, # of assets, breakdown sparkline. Click a card → drill-down panel showing accounts + assets at that custodian.

### 6.5 Asset detail (modal or slide-over)

Currently part of the AssetModal in edit mode. Should split into:
- **Form panel** (when creating or editing): class-driven form
- **Detail panel** (when viewing): hero with ticker + name + custodian; KPIs (qty, avg cost, current value, total received, YoC, DY); chart of position value over time (placeholder until cotação spec exists); recent lançamentos timeline; quick-add lançamento

### 6.6 Lançamento create/edit modal

Currently a long form modal. Could become a multi-step wizard for first-time-tutorial users, OR remain a one-page form but with smart layout:
- Step 0: Type selector with icons + 1-line description per type
- Step 1: All fields, where the form is visually re-shaped per type (only relevant fields appear, others hidden — never disabled in place)
- Inline preview of computed `net_amount` and `position impact` as user types
- Inactive-asset warning banner with confirmation checkbox (already implemented, keep this UX)

### 6.7 Login `/login`

Today: minimal email + password + "remember me 30 days" + button. **Keep simple.** Just polish: subtle gradient or pattern; product name as wordmark; no marketing copy.

### 6.8 Sysadmin pages

`/sysadmin/financial-institutions`, `/sysadmin/assets`, `/sysadmin/accounts`. Same patterns as workspace pages but with a workspace-selector dropdown (`Todos` + each workspace) at the top. Visually identical to admin pages — sysadmin is just an elevated viewport.

---

## 7. Visual language

### Existing decisions (Tailwind v4, do not overhaul)

- **Accent color:** Indigo (`indigo-500` / `indigo-600` for primary actions; `indigo-400` for dark-mode hover).
- **Neutrals:** Tailwind's `gray-*` family. Light mode background `gray-50`, dark mode `gray-950`. Cards: `gray-100`/`gray-900`. Borders: `gray-200`/`gray-800`.
- **Type:** system sans-serif (no custom font yet — open to a tasteful pairing if proposed).
- **Spacing:** 4px base, comfortable but not airy. Tables use `py-2 px-3.5` cells.
- **Corners:** `rounded-lg` for inputs/buttons, `rounded-2xl` for cards/modals.
- **Shadows:** subtle (`shadow-sm`); avoid pronounced drop shadows.
- **Transitions:** 150ms ease for hover/focus.
- **Dark mode:** first-class. The user lives there. Light mode must work but it's not the focus.

### Suggested extensions for the prototype

- **Asset class color tokens:** propose 14 distinct hues that work in both themes, used as small badges/dots.
  - Stocks (BR/US): blue
  - FII / REIT: green
  - ETF: violet
  - Bond / FIXED_INCOME: amber/orange
  - FUND: teal
  - Crypto: yellow
  - Cash: slate
  - Real estate / vehicle: pink/red
  - FGTS: lime
  - Private pension: cyan
- **Currency tokens:** BRL = warm (amber), USD = cool (emerald). Used as tiny pill on amounts.
- **Status colors:** active = neutral; inactive = `gray-500` + strikethrough on amount; warning = `amber-600`.
- **Numbers:** tabular nums (`font-variant-numeric: tabular-nums`) on all monetary columns.
- **Empty states:** illustrated only if it adds clarity; otherwise a single line of grey text.

### Inspirations to lean on

| Inspiration | Why |
|---|---|
| **Linear** | Density, keyboard-first, calm dark |
| **Notion** | Soft rounded cards, neutral palette, hover affordances |
| **Stripe Dashboard** | Numbers are heroes; sparklines integrated into tables |
| **Mercury Bank** | Calm financial dashboard with subtle accent and lots of white/black space |
| **Things 3** | Dense list rows with breathing room, micro-typography |

### Anti-inspirations

- **Robinhood / TradingView** — too flashy / too "trader brain"
- **Mint / NerdWallet** — too consumer / too gamified
- **Bloomberg Terminal** — too overwhelming; we want clarity, not maximalism

---

## 8. Tone of voice (PT-BR)

- **Conversational but precise.** "Quanto você tem aplicado", not "Total Capital Investido".
- **Avoid English where PT works:** "Lançamento" not "Entry", "Custodian/Custódia" is a borderline OK loanword — currently used as "IF / Custodiante / Custodian" interchangeably.
- **Numbers always with locale**: `R$ 1.234.567,89` (BR formatting), `US$ 1,234,567.89`.
- **Dates**: `03/05/2026` (DD/MM/YYYY) in tables; "Hoje", "Ontem", "Há 3 dias" in timelines.
- **No marketing fluff** ("revolucionário", "inteligente", "ai-powered" — never).

---

## 9. Real data scale (for prototypes)

Use these numbers to populate prototypes — they reflect actual current state:

| Entity | Count | Notes |
|---|---|---|
| Workspaces | 1 | "Família Ambrosio" |
| Users | 2 | 1 admin + 1 sysadmin |
| Financial Institutions | 13 | Real Brazilian + US brokers |
| Accounts | 13 | mix of checking + investment, BRL + USD |
| Assets (active) | 158 | spread across 14 classes |
| Assets (inactive / zerados) | 23 | sold-out positions kept for IR |
| Lançamentos | 0 today, will grow to ~500–2000 historical | once Notion lançamento import runs |

### Asset distribution by class (real)

| Class | Count |
|---|---|
| STOCK_BR | 30 |
| FII | 28 |
| FIXED_INCOME | 27 |
| STOCK_US | 24 |
| ETF | 23 |
| BOND | 15 |
| PRIVATE_PENSION | 7 |
| FUND | 7 |
| REIT | 5 |
| CASH | 5 |
| FGTS | 3 |
| CRYPTO | 3 |
| VEHICLE | 2 |
| REAL_ESTATE | 2 |

### Custodian distribution by # of assets (real)

XP 71 · Avenue 48 · Itaú 6 · Particular 4 · Caixa 3 · Mercado Pago 3 · Coinbase 2 · Wise 1 · Bradesco 1 · Santander 1 · BTG 1 (and a few zerados without a current custodian).

---

## 10. Constraints / non-goals

- **No real-time market data UI** — prices are imported manually or via batched APIs in a future spec. Treat current price as an editable field, not a streaming number.
- **No social features** — no leaderboards, no follower counts, no public sharing.
- **No mobile app** in this phase. Responsive web is enough; design for ≥ 1024px width as primary, ≥ 768px as fallback. Mobile native is a future concern.
- **No third-party integrations in the UI yet** — Notion / B3 / brokers are import scripts triggered manually.
- **No localization toggle** — PT-BR only. No EN/ES/i18n.
- **Currency support** — BRL and USD only. No EUR, GBP, etc.
- **Single workspace mostly** — design must accommodate a workspace switcher for future, but optimize for "current workspace = the only one I see most of the time".

---

## 11. Brand cues

- **Name:** Numis-Geek
  - "Numis" — root of *numismática* (study of currencies/coins). Implies seriousness about money.
  - "Geek" — the user's playful nod to a data-driven, hands-on, build-my-own approach.
- **No logo yet.** A wordmark would suffice. If logomark is proposed, lean toward something abstract (a stylized coin, an N-glyph) rather than literal money imagery.
- **No tagline yet.** Open to suggestions — should be calm and self-evident, not sales-y.

---

## 12. Specific micro-interactions to design

- **Theme toggle:** cycles `dark → light → system`; the icon morphs (sun/moon/auto). Currently a small button in the top bar.
- **Inline edit on number cells** in tables (current value, manual price overrides) — desirable; not yet implemented.
- **Drag-to-reorder columns** (later — not v1).
- **Bulk actions** on tables: select multiple lançamentos to deactivate, etc. Not yet implemented; design space for it in toolbars.
- **Empty states** for: zero assets, zero lançamentos in a date range, zero positions in the dashboard "Top movers".
- **Loading states**: skeletons in tables (rows with shimmer); never spinners over the whole page.
- **Errors**: inline near the action, never global toast walls. Login page error already follows this.

---

## 13. Tech context (for the design tool to know)

- **Stack:** React 19 + Vite + TypeScript + Tailwind v4 + react-router-dom v7
- **Components today** are bespoke (no Headless UI, no shadcn/ui currently). Open to introducing **shadcn/ui** components if the design suggests it — would be a welcome upgrade.
- **Icons**: none yet (no lucide / heroicons installed). Proposing an icon set is fine.
- **Charting library**: none yet. Recharts or Visx are good fits given the React stack.
- **Animation**: Framer Motion not installed; CSS transitions only today. Open to adding if proposed.

---

## 14. What to deliver from the design tool

In rough priority:

1. **Dashboard `/dashboard`** — full mock with real-ish numbers from §9
2. **Ativos `/assets`** — table + grouping toggle + asset detail slide-over
3. **Lançamentos `/lancamentos`** — table with filter chips + adaptive create modal
4. **Contas `/accounts`** — Contas tab + Custodians treemap
5. **Login `/login`** — polish pass
6. **Empty states + error states** for each major page
7. **Sidebar + top bar** — full shell mockup that all pages live inside

Optional but nice:

- A small style guide page documenting color tokens, type scale, spacing, button variants, badge variants, table conventions

---

## 15. What NOT to design (out of scope this round)

- Onboarding / signup flow (single-user app, no signup)
- Settings page beyond Profile (theme, password)
- Notification center
- Search / Cmd+K palette (future)
- Mobile-specific layouts
- Marketing site / landing page
- Email templates

---

*This brief is meant to be self-contained. If any section is ambiguous, ask Dani directly — he's both the user and the developer.*
