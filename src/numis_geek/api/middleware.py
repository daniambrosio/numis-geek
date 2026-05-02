import jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from numis_geek.config import SECRET_KEY
from numis_geek.db.session import SessionLocal
from numis_geek.services.audit import AuditService

_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
# Routes with explicit audit logging — skip to avoid double entries
_EXPLICIT_PATHS = {
    "/auth/login",
    "/users/invite",
    "/users/me",
    "/users/me/password",
}


def _is_explicit(path: str) -> bool:
    if path in _EXPLICIT_PATHS:
        return True
    # /users/{id}/role  and /users/{id}/deactivate
    parts = path.strip("/").split("/")
    if len(parts) == 3 and parts[0] == "users" and parts[2] in ("role", "deactivate"):
        return True
    return False


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        if request.method not in _MUTATING:
            return response
        if not (200 <= response.status_code < 300):
            return response
        if _is_explicit(request.url.path):
            return response

        # Decode token to get user context (best-effort, no exception on failure)
        user_email = "anonymous"
        workspace_id = None
        user_id = None
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            try:
                payload = jwt.decode(auth_header[7:], SECRET_KEY, algorithms=["HS256"])
                user_id = payload.get("sub")
                workspace_id = payload.get("workspace_id")
                user_email = payload.get("email", user_id or "anonymous")
            except Exception:
                pass

        action = f"http.{request.method.lower()}.{request.url.path}"
        try:
            db = SessionLocal()
            AuditService(db).log(
                user_email=user_email,
                action=action,
                workspace_id=workspace_id,
                user_id=user_id,
            )
            db.commit()
        except Exception:
            pass
        finally:
            db.close()

        return response
