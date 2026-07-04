from typing import Generator

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from numis_geek.db.session import SessionLocal
from numis_geek.exceptions import AuthError
from numis_geek.models.user import User
from numis_geek.services.auth import AuthService, UserContext

_bearer = HTTPBearer()


def get_db() -> Generator:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: Session = Depends(get_db),
) -> UserContext:
    """Resolve o usuário atual a partir do JWT, mas SEMPRE reconcilia
    role + workspace_id contra o DB. Sem isso, uma promoção/rebaixamento
    de role (ex.: admin → sysadmin) fica invisível pra APIs até o user
    fazer logout+login — enquanto o /me carrega do DB e devolve a role
    nova, gerando estado híbrido "vejo menu sysadmin mas API dá 403".
    Custo: +1 query por request; aceitável dado o baixo QPS do app."""
    try:
        ctx = AuthService.verify_token(credentials.credentials)
    except AuthError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))
    user = db.get(User, ctx.user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer exists or is inactive.",
        )
    # Se DB divergir do JWT (role trocou desde emissão), o DB manda.
    if user.role != ctx.role or user.workspace_id != ctx.workspace_id:
        ctx = UserContext(
            user_id=ctx.user_id,
            workspace_id=user.workspace_id,
            role=user.role,
        )
    return ctx
