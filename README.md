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
- **Tests:** pytest (in-memory SQLite)

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

| Status | Spec | Topic |
|---|---|---|
| ✅ | 00 | Foundation |
| ✅ | 01–04 | User / Workspace / Audit / Financial Institutions |
| ✅ | 05 | Accounts (Contas) |
| ✅ | 06 | Assets (Ativos) with custodian |
| ✅ | 07a | Notion Asset Import (one-shot) |
| ✅ | 07b | Lançamentos + Account Assets view |
| 📝 | 07c | Notion Lançamentos Import (planned) |
| 📝 | 08 | PTAX exchange rate table |
| 📝 | 09 | Patrimony dashboard |
| 📝 | 10+ | Categories, transactions, budgets, file imports, IRPF helpers, B3 integration |

See `specs/` for the authoritative roadmap.

---

## Troubleshooting

### Login shows "HTTP 502 Bad Gateway"

Backend isn't running. Start it: `.venv/bin/uvicorn numis_geek.api.app:app --reload --port 8000` and retry.

### `git` says "You have not agreed to the Xcode license agreements" (macOS)

Run `sudo xcodebuild -license`, press space to scroll, type `agree`, hit Enter. Or install git via Homebrew (`brew install git`) to bypass Xcode CLT entirely.

### Tests fail after pulling

You probably need to apply pending migrations to your local DB: `.venv/bin/alembic upgrade head`.
