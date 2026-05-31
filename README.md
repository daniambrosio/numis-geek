# Numis-Geek

Personal finance management system that consolidates two formerly Notion-based workflows:

- **Investidor-Geek** — investment portfolio (stocks BR/US, FIIs, ETFs, REITs, Bonds, Funds, Crypto, Real Estate, Vehicles, Cash, FGTS, Previdência)
- **Numis** — expense tracking

Built for personal use, runs locally first, designed to migrate to a VPS without rewrite.

---

## Stack

- **Backend:** Python 3.12+, FastAPI, SQLAlchemy 2, Alembic, bcrypt, PyJWT
- **DB:** SQLite locally → PostgreSQL on VPS (database-agnostic models)
- **Frontend:** React 19, Vite, TypeScript, Tailwind CSS v4
- **Scheduler:** APScheduler in-process (PTAX sync, price refresh, monthly snapshot, daily backup)
- **External integrations:** BCB SGS (PTAX), brapi (BR prices), Finnhub (US prices), Anthropic (LLM extraction), Notion (data import). Credentials live in `integration_credential` table — configure at `/sysadmin/integrations`.
- **Tests:** pytest (in-memory SQLite) + vitest (jsdom)

---

## Quick start

### Prerequisites

- Python 3.12+
- Node.js 20+ (for frontend)
- macOS / Linux (Windows untested)

### 1 — Install backend

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
# Optional: LLM extras for bulk extract upload (Spec 48). Adds anthropic
# SDK + Pillow (used to downscale large images before sending to Claude).
.venv/bin/pip install -e ".[dev,llm]"
```

### 2 — Configure environment

```bash
cp .env.example .env
# .env defaults are fine for local dev:
#   DATABASE_URL=sqlite:///./numis_geek.db
#   SECRET_KEY=change-me-in-production
```

For sysadmin password, optionally export `SYSADMIN_PASSWORD` (defaults to `changeme123`):

```bash
export SYSADMIN_PASSWORD=mysecret
```

### 3 — Run migrations + seed

```bash
.venv/bin/alembic upgrade head
.venv/bin/python scripts/seed.py
```

This creates:

- Workspace **"Família Ambrosio"**
- Admin user `daniel.ambrosio@gmail.com` / password `changeme`
- Sysadmin user `sysadmin@numis-geek.internal` / `$SYSADMIN_PASSWORD`
- 13 financial institutions (Itaú, XP, BTG, Avenue, Wise, Coinbase, Particular, ...)
- 13 example accounts
- Asset starter set: empty by default; if `data/notion_export.json` exists, the seed imports from there

### 4 — (Optional) Import real assets from Notion

If you have a Notion export at `data/notion_export.json`, populate it via:

```bash
.venv/bin/python scripts/import_notion_assets.py --dry-run     # preview
.venv/bin/python scripts/import_notion_assets.py --apply       # write to DB
```

The fetch step (Notion → JSON) is orchestrated from a Claude Code session via the Notion MCP server. The Python script itself does **not** depend on Notion access.

### 5 — Install + run frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend dev server: <http://localhost:5173>

### 6 — Run backend

In another terminal:

```bash
.venv/bin/uvicorn numis_geek.api.app:app --reload --port 8000
```

Backend API: <http://localhost:8000>
OpenAPI docs: <http://localhost:8000/docs>

The frontend dev server proxies `/api/*` to `http://localhost:8000/*` (see `frontend/vite.config.ts`).

---

## Login

Open <http://localhost:5173>:

| Email | Password | Role |
|---|---|---|
| `daniel.ambrosio@gmail.com` | `changeme` | admin (workspace) |
| `sysadmin@numis-geek.internal` | `$SYSADMIN_PASSWORD` | sysadmin (system-wide) |

---

## Tests

```bash
.venv/bin/pytest                    # full suite
.venv/bin/pytest tests/test_assets.py -v
.venv/bin/pytest -k "lancamento"
```

Tests use in-memory SQLite — they don't touch `numis_geek.db`. Module-scoped fixtures keep runtime under 30s for the full suite.

---

## Database

- Engine: SQLite locally (`numis_geek.db` at project root), Postgres on VPS later.
- All schema changes go through Alembic — never edit schema directly.
- Generate a migration:
  ```bash
  .venv/bin/alembic revision --autogenerate -m "description"
  ```
- Apply: `.venv/bin/alembic upgrade head`
- Roll back one: `.venv/bin/alembic downgrade -1`
- SQLite-specific care: changes to column nullability or enum values must use `op.batch_alter_table` (see `alembic/versions/c7e4b1a09f23_*.py` for an enum-extending example).

---

## Project structure

```
numis-geek/
├── README.md                          # this file
├── CLAUDE.md                          # project conventions for Claude Code
├── pyproject.toml                     # backend deps + pytest config
├── alembic.ini                        # migration config
├── .env.example                       # environment template
├── alembic/versions/                  # migration scripts
├── data/                              # gitignored — local Notion export, etc.
├── scripts/
│   ├── seed.py                        # idempotent seed (workspace, IFs, accounts)
│   ├── import_notion_assets.py        # JSON → DB asset importer
│   └── fetch_notion_assets.py         # stub explaining the MCP-driven fetch flow
├── specs/                             # numbered feature specs (00–07b so far)
├── src/numis_geek/
│   ├── api/
│   │   ├── app.py                     # FastAPI mount + middleware
│   │   ├── deps.py                    # get_db, get_current_user
│   │   ├── middleware.py              # AuditMiddleware
│   │   └── routes/                    # one module per resource
│   ├── db/                            # session, base
│   ├── models/                        # SQLAlchemy models
│   └── services/                      # auth, audit, positions, user, workspace
├── tests/                             # pytest tests
└── frontend/
    ├── index.html
    ├── vite.config.ts
    └── src/
        ├── App.tsx                    # routes
        ├── lib/
        │   ├── api.ts                 # typed API client
        │   └── theme.ts               # dark/light/system theme
        ├── components/
        │   ├── AppLayout.tsx          # sidebar + topbar
        │   ├── AssetModal.tsx
        │   └── LancamentoModal.tsx
        └── pages/
            ├── Login.tsx, Dashboard.tsx, Profile.tsx
            ├── Lancamentos.tsx
            ├── admin/                 # workspace pages (Accounts, Assets, Users, Audit)
            └── sysadmin/              # cross-workspace pages
```

---

## Development methodology

This project uses a **Multi-Agent SDLC** approach (planner → coder → reviewer → security agents). Claude Code acts as orchestrator, not implementer. See `CLAUDE.md` for full conventions.

Each feature lives as a numbered spec in `specs/` (e.g., `06. Assets.md`, `07b. Lançamentos and Account Assets View.md`). The flow:

1. Interview the user in plan mode
2. Write the spec markdown
3. Delegate implementation to a coder agent
4. Verify all tests pass
5. Commit

A feature is only **done** when all automated tests are written and passing.

### Naming convention

All table names, column names, properties, and model fields are in **English**, even though the domain language and user-facing UI are in **Portuguese**.

### Roles

| Role | Scope | Notes |
|---|---|---|
| `sysadmin` | system-wide | `workspace_id = None`; manages system entities (Financial Institutions); cross-workspace visibility |
| `admin` | workspace | manages users + settings within their workspace |
| `member` | workspace | regular access |

Every role check that allows `admin` must also allow `sysadmin` — pattern `role not in (admin, sysadmin)`. Workspace-scoped queries skip the workspace filter when `role == sysadmin`.

---

## Roadmap (high level)

Shipped (✅) and ongoing tracks — see `specs/` for the authoritative numbered list (00–48+).

| Track | Highlights |
|---|---|
| **Foundation** | ✅ 00–04 (Users, Workspace, Audit, Financial Institutions) · ✅ 05 (Accounts) · ✅ 06 (Assets with custodian) |
| **Notion migration** | ✅ 07a (Assets) · ✅ 07c (Lançamentos) · ✅ 16 (Notion Sync) |
| **Investment domain** | ✅ 07b (Lançamentos + Account Assets) · ✅ 08 (AssetMovement + Distribution) · ✅ 13 (Corporate Actions) · ✅ 17 (Opções B3) |
| **Pricing / FX** | ✅ 11 (PTAX + IntegrationCredential) · ✅ 12 (Asset price update) · ✅ 22–28 (price sources, freshness, manual edit, refresh API + background job, topbar) · ✅ 44 (PriceRefresh redesign) |
| **Snapshot / fechamento** | ✅ 14 (PortfolioSnapshot V1) · ✅ 35 (monthly workflow, lifecycle, pendencies) · ✅ 45 (snapshot detail completeness) · ✅ 46 (asset price history V1) |
| **Dashboards / charts** | ✅ 15 (Dashboard V2) · ✅ 17a–d (reskin) · ✅ 18 (Frontend Shell Cleanup) · ✅ 29–34 (proventos aggregation, chart, redesign) · ✅ 41–42 (dual-currency hero) |
| **Attachments + LLM** | ✅ 19 (Attachments + FI country) · ✅ 38 (LLM extraction per pendency) · ✅ 40 (preview/abertura de anexos) · ✅ 43 (storage robustness) · ✅ **48 (Bulk extract upload)** |
| **UX nits** | ✅ 25 (Topbar PriceRefresh) · ✅ 47 (Pendency render unification) |
| **Ops** | ✅ 24 (APScheduler) · ✅ 37 (DB backup) · ✅ 39 (backup automation) |
| **Pending pre-VPS** | 📝 IntegrationCredential encryption · 📝 multi-worker scheduler safety. See [docs/deployment.md](docs/deployment.md). |
| **Future** | 📝 Expense tracking (Numis side) · 📝 IRPF helpers · 📝 B3 integration · 📝 Object storage backend for attachments |

---

## Troubleshooting

### Login shows "HTTP 502 Bad Gateway"

Backend isn't running. Start it: `.venv/bin/uvicorn numis_geek.api.app:app --reload --port 8000` and retry.

### `git` says "You have not agreed to the Xcode license agreements" (macOS)

Run `sudo xcodebuild -license`, press space to scroll, type `agree`, hit Enter. Or install git via Homebrew (`brew install git`) to bypass Xcode CLT entirely.

### Tests fail after pulling

You probably need to apply pending migrations to your local DB: `.venv/bin/alembic upgrade head`.

### "No active ANTHROPIC IntegrationCredential" / "anthropic SDK not installed"

The bulk extract upload (Spec 48) needs an active Anthropic credential and the SDK.

1. Install the optional extras: `.venv/bin/pip install -e ".[dev,llm]"` (adds `anthropic` + `Pillow`).
2. Log in as **sysadmin**, go to `/sysadmin/integrations`, add a credential of type **Anthropic Claude (LLM extraction)** with your API key, and click "Test".

---

## Optional features

### Bulk extract upload (Spec 48)

On `/snapshots/{ym}` while the snapshot is `IN_REVIEW`, drop a screenshot, drag a PDF, or `cmd+V` paste a clipboard image into the upload zone above the pendency list. The LLM (Claude) extracts a position list and resolves matching pendencies in one click. Images larger than 1568 px are auto-downscaled before sending.

**Requirements:** `pip install -e ".[llm]"` + a configured ANTHROPIC credential.

### Bringing data over from Notion

If you have a Notion export at `data/notion_export.json`, populate it via:

```bash
.venv/bin/python scripts/import_notion_assets.py --dry-run     # preview
.venv/bin/python scripts/import_notion_assets.py --apply       # write to DB
```

---

## Secret storage

API keys (Anthropic, brapi, Finnhub, Notion) and the user session secret all live in places that **must not be shared**:

- `IntegrationCredential.secret_value` — stored **plaintext** in the SQLite DB. The whole `numis_geek.db` file gives away every key. `.gitignore` already excludes `*.db` and `*.db.bak-*` — keep it that way. A future spec will encrypt these (see `docs/deployment.md` § blockers).
- `SECRET_KEY` (JWT signing) — read from `.env`, never committed.
- `data/attachments/` — uploaded screenshots may contain personal financial info. Gitignored, but if you copy backups around, mind the privacy.

---

## VPS deployment

When you're ready to host this on a VPS (nginx + uvicorn + systemd + SQLite-then-Postgres), follow **[docs/deployment.md](docs/deployment.md)**. It covers:

- Provisioning (Ubuntu, firewall, dependencies)
- File layout (`/var/numis/data/{db,attachments,backups}`)
- systemd unit + nginx TLS + SPA proxy
- Daily backups (Makefile + restic to B2)
- Anthropic credential setup
- Known blockers to clear **before** going live (plaintext secrets, scheduler in multi-worker)
- Migration path from SQLite to Postgres
