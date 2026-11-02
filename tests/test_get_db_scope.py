"""Regressão 2026-11-02 — AuditMiddleware falhava com `database is locked`.

Com `Depends(get_db)` (scope default "request") o commit da rota roda só
depois da resposta; o AuditMiddleware grava em outra sessão antes disso e
esbarra no write lock do SQLite. `scope="function"` faz o commit acontecer
ao fim do endpoint.
"""
from fastapi import Depends, FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from starlette.middleware.base import BaseHTTPMiddleware

from numis_geek.api.app import app
from numis_geek.api.deps import get_db


def _walk(dependant):
    for sub in dependant.dependencies:
        yield sub
        yield from _walk(sub)


def test_every_get_db_dependency_is_function_scoped():
    offenders = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for sub in _walk(route.dependant):
            if sub.call is get_db and getattr(sub, "scope", None) != "function":
                offenders.append(f"{sorted(route.methods)} {route.path}")
    assert offenders == [], f"Depends(get_db) sem scope='function': {offenders}"


def _app_with(dep, tmp_path):
    eng = create_engine(
        f"sqlite:///{tmp_path / 'lock.db'}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(eng, "connect")
    def _pragmas(conn, _):
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=300")
        cur.close()

    with eng.begin() as c:
        c.execute(text("create table t(x)"))
        c.execute(text("create table audit(x)"))
    S = sessionmaker(bind=eng)

    def _get_db():
        db = S()
        try:
            yield db
            db.commit()
        finally:
            db.close()

    mini = FastAPI()
    outcome: dict = {}

    class Audit(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            resp = await call_next(request)
            db = S()
            try:
                db.execute(text("insert into audit values (1)"))
                db.commit()
                outcome["ok"] = True
            except Exception:
                outcome["ok"] = False
            finally:
                db.close()
            return resp

    mini.add_middleware(Audit)

    @mini.post("/w")
    def w(db=dep(_get_db)):
        db.execute(text("insert into t values (1)"))
        return {}

    return mini, outcome


def test_function_scope_lets_middleware_write(tmp_path):
    mini, outcome = _app_with(lambda f: Depends(f, scope="function"), tmp_path)
    assert TestClient(mini).post("/w").status_code == 200
    assert outcome["ok"] is True


def test_request_scope_reproduces_lock(tmp_path):
    # Documenta o mecanismo: se um dia o FastAPI mudar e isso passar a
    # funcionar, o teste avisa que a nota em get_db pode ser revista.
    mini, outcome = _app_with(lambda f: Depends(f), tmp_path)
    assert TestClient(mini).post("/w").status_code == 200
    assert outcome["ok"] is False
