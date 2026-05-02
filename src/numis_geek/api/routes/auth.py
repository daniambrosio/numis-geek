from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from numis_geek.api.deps import get_current_user, get_db
from numis_geek.exceptions import AuthError
from numis_geek.services.audit import AuditService
from numis_geek.services.auth import AuthService, UserContext
from numis_geek.models.user import User

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    remember_me: bool = False


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MeResponse(BaseModel):
    user_id: str
    workspace_id: str
    role: str


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    try:
        token = AuthService(db).login(body.email, body.password, remember_me=body.remember_me)
    except AuthError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))

    user = db.query(User).filter(User.email == body.email.lower()).first()
    if user:
        AuditService(db).log(
            user_email=user.email,
            action="auth.login",
            workspace_id=user.workspace_id,
            user_id=user.id,
            details={"remember_me": body.remember_me},
        )
        db.commit()

    return LoginResponse(access_token=token)


@router.get("/me", response_model=MeResponse)
def me(current_user: UserContext = Depends(get_current_user)):
    return MeResponse(
        user_id=current_user.user_id,
        workspace_id=current_user.workspace_id,
        role=current_user.role.value,
    )
