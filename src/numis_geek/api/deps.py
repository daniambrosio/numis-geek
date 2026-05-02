from typing import Generator

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from numis_geek.db.session import SessionLocal
from numis_geek.exceptions import AuthError
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
) -> UserContext:
    try:
        return AuthService.verify_token(credentials.credentials)
    except AuthError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))
