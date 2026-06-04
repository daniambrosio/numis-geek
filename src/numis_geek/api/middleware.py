"""Spec 35 audit + Spec 55 observability middlewares."""
from __future__ import annotations

import logging
import uuid

import jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from numis_geek.config import SECRET_KEY
from numis_geek.db.session import SessionLocal
from numis_geek.models.user import User
from numis_geek.services.audit import AuditService

logger = logging.getLogger(__name__)

_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
# Routes with explicit audit logging — skip to avoid interfering with their db session commit
_EXPLICIT_PATHS = {
    "/auth/login",
    "/users/invite",
    "/users/me",
    "/users/me/password",
    "/api/auth/login",
    "/api/users/invite",
    "/api/users/me",
    "/api/users/me/password",
}


def _is_explicit(path: str) -> bool:
    if path in _EXPLICIT_PATHS:
        return True
    # Strip /api prefix pra comparar com paths "limpos" das routes
    # registradas com prefix="/api".
    p = path
    if p.startswith("/api/"):
        p = p[4:]
    parts = p.strip("/").split("/")
    # /users/{id}/role, /users/{id}/deactivate, /users/{id}/name
    if len(parts) == 3 and parts[0] == "users" and parts[2] in ("role", "deactivate", "name"):
        return True
    # /financial-institutions and /financial-institutions/{id}[/deactivate]
    if parts[0] == "financial-institutions":
        return True
    # /assets and /assets/{id}[/deactivate]
    if parts[0] == "assets":
        return True
    return False


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Spec 55 — anexa um request_id curto (8 chars) em cada request.

    Disponível como `request.state.request_id` dentro dos handlers e
    devolvido como header `X-Request-ID` na resposta. Costura request
    com audit_log + logs Python pra investigação posterior.
    """

    async def dispatch(self, request: Request, call_next):
        rid = uuid.uuid4().hex[:8]
        request.state.request_id = rid
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response


def _decode_user_from_auth(auth_header: str) -> tuple[str | None, str | None]:
    """Decode JWT pra (user_id, workspace_id) — best-effort, sem raise."""
    if not auth_header.startswith("Bearer "):
        return None, None
    try:
        payload = jwt.decode(auth_header[7:], SECRET_KEY, algorithms=["HS256"])
    except Exception:
        return None, None
    return payload.get("sub"), payload.get("workspace_id")


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        # Defesa contra cache zumbi: o SPA catchall pode ter
        # devolvido HTML pra /api/* num momento de roteamento errado
        # (proxy quebrado, prefix faltando, etc.) e o browser cacheou
        # essa resposta no disco. Setando no-store em toda resposta
        # /api/* garante que nunca mais vamos cachear JSON da API
        # como HTML — fix self-healing pro bug do login em loop.
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"

        status = response.status_code
        method = request.method
        path = request.url.path
        request_id = getattr(request.state, "request_id", None)

        is_mutating_ok = method in _MUTATING and 200 <= status < 300
        is_error = status >= 400
        if not (is_mutating_ok or is_error):
            return response

        # Erros sempre logam (mesmo GET). Mutações 2xx mantêm a regra
        # antiga de skippar paths com audit explícito.
        if is_mutating_ok and _is_explicit(path):
            return response

        user_id, workspace_id = _decode_user_from_auth(
            request.headers.get("Authorization", "")
        )
        user_email = "anonymous"
        if is_error:
            status_class = f"{status // 100}xx"
            action = f"http.{status_class}.{method.lower()}.{path}"
        else:
            action = f"http.{method.lower()}.{path}"

        try:
            db = SessionLocal()
            if user_id:
                u = db.get(User, user_id)
                user_email = u.email if u else user_id
            details = {
                "request_id": request_id,
                "status": status,
                "method": method,
                "path": path,
            }
            AuditService(db).log(
                user_email=user_email,
                action=action,
                workspace_id=workspace_id,
                user_id=user_id,
                details=details,
            )
            db.commit()
        except Exception:
            logger.exception("audit middleware failed for %s %s", method, path)
        finally:
            db.close()

        return response
