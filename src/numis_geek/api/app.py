import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from numis_geek.api.middleware import AuditMiddleware
from numis_geek.scheduler import start_scheduler, stop_scheduler
from numis_geek.api.routes import (
    accounts,
    asset_movements,
    assets,
    attachments,
    audit,
    auth,
    backup,
    corporate_actions,
    distributions,
    extractions,
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


_cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")

app = FastAPI(title="Numis-Geek API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AuditMiddleware)

app.include_router(auth.router, prefix="/api")
app.include_router(users.router, prefix="/api")
app.include_router(audit.router, prefix="/api")
app.include_router(financial_institutions.router, prefix="/api")
app.include_router(accounts.router, prefix="/api")
app.include_router(assets.router, prefix="/api")
app.include_router(asset_movements.router, prefix="/api")
app.include_router(distributions.router, prefix="/api")
app.include_router(workspaces.router, prefix="/api")
app.include_router(integrations.router, prefix="/api")
app.include_router(ptax.router, prefix="/api")
app.include_router(ptax.workspace_router, prefix="/api")
app.include_router(corporate_actions.router, prefix="/api")
app.include_router(snapshots.router, prefix="/api")
app.include_router(notion_sync.router, prefix="/api")
app.include_router(options.router, prefix="/api")
app.include_router(attachments.router, prefix="/api")
app.include_router(portfolio.router, prefix="/api")
app.include_router(prices.router, prefix="/api")
app.include_router(backup.router, prefix="/api")
app.include_router(extractions.router, prefix="/api")


@app.get("/health")
def health():
    return {"status": "ok"}


# In production the built React app is served from $FRONTEND_DIST.
# All /assets/* files are served directly; every other path falls back to
# index.html for client-side routing.
_dist = Path(os.getenv("FRONTEND_DIST", "frontend/dist"))
if _dist.is_dir():
    _assets = _dist / "assets"
    if _assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(_assets)), name="static-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def _spa(full_path: str):
        candidate = _dist / full_path
        if candidate.is_file():
            return FileResponse(str(candidate))
        return FileResponse(str(_dist / "index.html"))
