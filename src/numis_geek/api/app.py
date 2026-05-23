from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from numis_geek.api.middleware import AuditMiddleware
from numis_geek.api.routes import (
    accounts,
    asset_movements,
    assets,
    audit,
    auth,
    corporate_actions,
    distributions,
    financial_institutions,
    integrations,
    notion_sync,
    ptax,
    snapshots,
    users,
    workspaces,
)

app = FastAPI(title="Numis-Geek API", version="0.1.0")

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


@app.get("/health")
def health():
    return {"status": "ok"}
