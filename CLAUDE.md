# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Numis-Geek** is a personal finance management system that consolidates two Notion-based workflows:
- **Investidor-Geek** — investment portfolio management
- **Numis** — expense tracking

The system is built for the owner's personal use, running locally first, with architecture designed to migrate to a VPS.

## Development Methodology: Multi-Agent SDLC

This project uses a **Multi-Agent SDLC** approach with specialized agents per phase:
- **Planner agent** — design and spec phase
- **Coder agent** — implementation
- **Reviewer agent** — code review
- **Security agent** — security review

Claude acts as the **orchestrator**, not the implementer. Frameworks like LangGraph, AutoGen, or CrewAI may be used to formalize agent handoffs.

## Development Process

1. Features live in `./specs/` as numbered files (e.g., `01. User Authentication.md`)
2. **Interview the user in plan mode** before writing each spec
3. A feature is only considered done when **all automated tests are written and passing**
4. If needed, create a dedicated testing agent for automated test generation

## Tech Stack

- **Language:** Python 3.12+
- **ORM:** SQLAlchemy 2.x (database-agnostic; start SQLite, migrate to PostgreSQL on VPS)
- **Migrations:** Alembic (autogenerate enabled, every schema change needs a migration script)
- **Auth:** bcrypt (direct, not passlib — incompatible with Python 3.14) for password hashing, PyJWT for sessions
- **Testing:** pytest with in-memory SQLite fixtures
- **Config:** python-dotenv (`.env` for `DATABASE_URL`, `SECRET_KEY`)
- **Version control:** Git

## Naming Convention

**All table names, column names, properties, and model fields must be in English**, even though the domain language and user-facing UI may be in Portuguese.

## Domain Model

| Entity | Description |
|---|---|
| Financial Institutions | Banks, brokers, fintechs |
| Checking Accounts | With or without yield; used for payments, Pix, transfers |
| Investment Accounts | Where assets are bought; receives dividends/yields |
| Credit Card Accounts | Tied to a financial institution; modeled as accounts; have statement close date and payment due date; additional cards appear in the same invoice |
| Entries (Lançamentos) | Investment events: purchases, sales, come-cotas, bonificações, subscriptions, redemptions |
| Transactions (Transações) | Cash flows: expenses, salary, consulting, sales |
| Statement Files | Extracts from exchanges, banks, fintechs, brokers — used for reconciliation |
| Trade Notes | Operation notes from brokers for asset movement tracking |
| Invoice Files | Credit card invoices — contain expenses, IOF, FX charges |

## Features (Planned)

1. **Multi-currency** — USD and BRL; every transaction stores the closing PTAX rate for conversion
2. **PTAX exchange rate table** — maintains daily PTAX closing rates
3. **Dolarized portfolio view** — converts BRL investments to USD for a unified view
4. **Manual entries** — support for manual ledger entries
5. **Accounts payable/receivable** — with frequency control (one-time, recurring)
6. **Audit log** — full action history with user attribution
7. **User management** — email-based auth; multi-user workspace support (workspace is the top-level grouping)
8. **Dark / Light / System UI mode**
9. **Notion data migration** — import existing data from Notion
10. **Reconciliation** — transactions and entries must be reconciled against imported files; maintain traceability links
11. **Dashboards** — separate dashboards for investments and expenses
12. **KPIs** — defined during each feature's spec process
13. **Annual budgets** — for expenses, with monthly tracking against targets
14. **Investment performance** — monthly, by institution, by asset class, YoY, MoM, etc.
15. **Monthly portfolio snapshot** — record all investments on the last day of the month; some auto-imported via public APIs
16. **Intelligent file import** — supports CSV, PDF, XLS, screenshots; use LLM agent for content detection and parsing
17. **Investment goals** — track targets like annual dividends per country
18. **Smart dividend import** — from broker statement files, likely using an LLM
19. **Asset current value updates** — enables valuation methods: price ceiling, Bazin, Graham, Peter Lynch, intrinsic value, etc.

### Advanced (Future)
- Index data for benchmarking: CDI, Ibovespa, Nasdaq, S&P, IFIX
- Historical inflation data for real-return calculations
- B3 integration for automatic data import
- IRPF tax declaration assistance
- Batch import and AI analysis of investor relations (RI) documents

## Architecture Constraints

- The database engine must be portable: start local, migrate to VPS without a full rewrite
- Every schema change requires a migration script — no ad-hoc schema edits
- The workspace is the top-level grouping for all entities (users, accounts, transactions, entries)
- Authentication and authorization are email-based
- Reference screenshots for the investment dashboard are in `assets/references/`

## Roles & Authorization

Three roles exist: `sysadmin`, `admin`, `member`.

- **sysadmin** — system-level super-user; `workspace_id = None`; manages system entities (Financial Institutions, etc.) and can view/edit data across all workspaces
- **admin** — workspace-scoped; manages users and settings within their workspace
- **member** — workspace-scoped; regular access

**Every role check that allows `admin` must also allow `sysadmin`** — use `role not in (admin, sysadmin)` pattern, never `role != admin`. Every workspace-scoped query must skip the workspace filter when `role == sysadmin`.

## Backend Patterns

- `get_db()` in `api/deps.py` must commit on success and rollback on error — never just `finally: db.close()` without committing first.
- SQLite migrations that change column nullability or enum values require `op.batch_alter_table`.

## Frontend Patterns

- **Never catch data-fetch errors with `navigate('/login')`**. Only `api.me()` should trigger a login redirect on failure. All other fetches (listUsers, listAudit, etc.) should handle errors separately — a 403 or 500 on a data call must never log the user out.
- Split `api.me()` and data fetches into separate `useEffect` hooks; gate the data fetch on `me` being set.
- **Every modal must close on ESC.** Use the `useEscapeKey` hook from `frontend/src/lib/useEscapeKey.ts`, passing a close handler that's a no-op when the modal isn't open (e.g. `useEscapeKey(() => { if (confirmDeactivate) setConfirmDeactivate(null) })`). Applies to component-level modals (e.g. `AssetModal`, `MovementComposer`) and to inline confirm/edit dialogs rendered directly inside a page. Never ship a new overlay without this.
