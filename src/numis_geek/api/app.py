from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from numis_geek.api.routes import auth, users

app = FastAPI(title="Numis-Geek API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(users.router)


@app.get("/health")
def health():
    return {"status": "ok"}
