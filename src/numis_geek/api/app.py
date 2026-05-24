from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from numis_geek.api.middleware import AuditMiddleware
from numis_geek.scheduler import start_scheduler, stop_scheduler
from numis_geek.api.routes import (
    accounts,
    asset_movements,
    assets,
    attachments,
    audit,
    auth,
    corporate_actions,
    distributions,
    financial_institutions,
    integrations,
    notion_sync,
    options,
    portfolio,
    prices,
    ptax,
    snapshots,
    users,
    workspaces,
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler(app)
    yield
    stop_scheduler(app)


app = FastAPI(title="Numis-Geek API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AuditMiddleware)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(audit.router)
app.include_router(financial_institutions.router)
app.include_router(accounts.router)
app.include_router(assets.router)
app.include_router(asset_movements.router)
app.include_router(distributions.router)
app.include_router(workspaces.router)
app.include_router(integrations.router)
app.include_router(ptax.router)
app.include_router(corporate_actions.router)
app.include_router(snapshots.router)
app.include_router(notion_sync.router)
app.include_router(options.router)
app.include_router(attachments.router)
app.include_router(portfolio.router)
app.include_router(prices.router)


@app.get("/health")
def health():
    return {"status": "ok"}
