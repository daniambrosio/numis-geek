from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from sqlalchemy.orm import Session

from numis_geek.config import SECRET_KEY
from numis_geek.exceptions import AuthError
from numis_geek.models.user import User, UserRole

_ALGORITHM = "HS256"
_TOKEN_TTL_SHORT_HOURS = 8
_TOKEN_TTL_LONG_DAYS = 30


@dataclass
class UserContext:
    user_id: str
    workspace_id: str
    role: UserRole


class AuthService:
    def __init__(self, db: Session):
        self.db = db

    def login(self, email: str, password: str, remember_me: bool = False) -> str:
        user = self.db.query(User).filter(User.email == email.lower()).first()
        if not user or not bcrypt.checkpw(password.encode(), user.password_hash.encode()):
            raise AuthError("Invalid credentials.")
        if not user.is_active:
            raise AuthError("Account is inactive.")
        ttl = timedelta(days=_TOKEN_TTL_LONG_DAYS) if remember_me else timedelta(hours=_TOKEN_TTL_SHORT_HOURS)
        payload = {
            "sub": user.id,
            "workspace_id": user.workspace_id,
            "role": user.role.value,
            "exp": datetime.now(timezone.utc) + ttl,
        }
        return jwt.encode(payload, SECRET_KEY, algorithm=_ALGORITHM)

    @staticmethod
    def verify_token(token: str) -> UserContext:
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[_ALGORITHM])
        except jwt.ExpiredSignatureError:
            raise AuthError("Token has expired.")
        except jwt.InvalidTokenError:
            raise AuthError("Invalid token.")
        return UserContext(
            user_id=payload["sub"],
            workspace_id=payload["workspace_id"],
            role=UserRole(payload["role"]),
        )
