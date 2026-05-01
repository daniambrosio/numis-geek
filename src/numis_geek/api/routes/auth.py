from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from numis_geek.api.deps import get_current_user, get_db
from numis_geek.exceptions import AuthError
from numis_geek.services.auth import AuthService, UserContext

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


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
        token = AuthService(db).login(body.email, body.password)
    except AuthError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))
    return LoginResponse(access_token=token)


@router.get("/me", response_model=MeResponse)
def me(current_user: UserContext = Depends(get_current_user)):
    return MeResponse(
        user_id=current_user.user_id,
        workspace_id=current_user.workspace_id,
        role=current_user.role.value,
    )
