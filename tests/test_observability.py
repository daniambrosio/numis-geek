"""Spec 55 — testes do request ID middleware + audit de 4xx/5xx + logs."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from numis_geek.api.middleware import (
    AuditMiddleware, RequestIDMiddleware, _is_explicit,
)
from numis_geek.logging_config import configure_logging, current_log_path


@pytest.fixture
def app_with_middlewares() -> FastAPI:
    """Mini app só com os middlewares pra testar isoladamente."""
    a = FastAPI()
    a.add_middleware(AuditMiddleware)
    a.add_middleware(RequestIDMiddleware)

    @a.get("/echo")
    def echo(rid: str | None = None):
        return {"ok": True, "rid": rid}

    @a.get("/state-rid")
    def state_rid(request):  # type: ignore[arg-type]
        # FastAPI inject request via parameter rename — not pythonic;
        # use proper Request injection instead.
        return {}

    return a


def test_request_id_header_present(app_with_middlewares):
    client = TestClient(app_with_middlewares)
    r = client.get("/echo")
    assert r.status_code == 200
    rid = r.headers.get("X-Request-ID")
    assert rid is not None
    assert len(rid) == 8


def test_request_id_unique_per_request(app_with_middlewares):
    client = TestClient(app_with_middlewares)
    r1 = client.get("/echo")
    r2 = client.get("/echo")
    assert r1.headers["X-Request-ID"] != r2.headers["X-Request-ID"]


def test_request_state_carries_request_id():
    """request.state.request_id deve estar disponível dentro do handler."""
    a = FastAPI()
    a.add_middleware(RequestIDMiddleware)

    @a.get("/inside-real")
    def inside_real(request: Request):
        return {"rid": request.state.request_id}

    client = TestClient(a)
    r = client.get("/inside-real")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "rid" in body
    assert len(body["rid"]) == 8
    assert r.headers["X-Request-ID"] == body["rid"]


def test_is_explicit_handles_api_prefix():
    # /users/me e /api/users/me devem ambos ser detectados como
    # rotas com audit explícito.
    assert _is_explicit("/users/me") is True
    assert _is_explicit("/api/users/me") is True
    assert _is_explicit("/auth/login") is True
    assert _is_explicit("/api/auth/login") is True
    # /assets é considerado explícito (qualquer prefixo)
    assert _is_explicit("/assets") is True
    assert _is_explicit("/api/assets") is True
    # path arbitrário não-explícito
    assert _is_explicit("/api/snapshots") is False


def test_logging_config_dev_mode_no_file(tmp_path, monkeypatch):
    monkeypatch.delenv("LOG_DIR", raising=False)
    p = configure_logging()
    assert p is None
    assert current_log_path() is None


def test_logging_config_writes_to_file_when_log_dir_set(tmp_path, monkeypatch):
    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    p = configure_logging()
    assert p == tmp_path / "numis.log"

    import logging
    logging.getLogger("test").info("hello from test")
    # Força flush
    for h in logging.getLogger().handlers:
        h.flush()

    content = (tmp_path / "numis.log").read_text()
    assert "hello from test" in content


def test_audit_middleware_logs_5xx_with_request_id(monkeypatch, tmp_path):
    """Erros 5xx devem ir pro audit_log com action http.5xx.*."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from numis_geek.db.base import Base
    import numis_geek.models  # noqa: F401
    from numis_geek.models.audit_log import AuditLog

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False)

    # Hot-swap SessionLocal usada pelo middleware.
    import numis_geek.api.middleware as mw
    monkeypatch.setattr(mw, "SessionLocal", Session)

    a = FastAPI()
    a.add_middleware(AuditMiddleware)
    a.add_middleware(RequestIDMiddleware)

    @a.get("/boom")
    def boom():
        raise HTTPException(status_code=500, detail="kaboom")

    client = TestClient(a, raise_server_exceptions=False)
    r = client.get("/boom")
    assert r.status_code == 500
    rid = r.headers.get("X-Request-ID")
    assert rid is not None

    with Session() as db:
        rows = db.query(AuditLog).all()
        assert len(rows) >= 1
        entry = rows[-1]
        assert entry.action.startswith("http.5xx.")
        assert rid in (entry.details or "")


def test_audit_middleware_logs_4xx(monkeypatch):
    """401/403 também devem ser logados (mesmo GET, não-mutating)."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from numis_geek.db.base import Base
    import numis_geek.models  # noqa: F401
    from numis_geek.models.audit_log import AuditLog

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False)

    import numis_geek.api.middleware as mw
    monkeypatch.setattr(mw, "SessionLocal", Session)

    a = FastAPI()
    a.add_middleware(AuditMiddleware)
    a.add_middleware(RequestIDMiddleware)

    @a.get("/forbidden")
    def forbidden():
        raise HTTPException(status_code=403, detail="nope")

    client = TestClient(a)
    r = client.get("/forbidden")
    assert r.status_code == 403

    with Session() as db:
        rows = db.query(AuditLog).all()
        assert any(r.action.startswith("http.4xx.") for r in rows)
