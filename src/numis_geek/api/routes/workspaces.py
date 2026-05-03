from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from numis_geek.api.deps import get_current_user, get_db
from numis_geek.models.user import UserRole
from numis_geek.models.workspace import Workspace
from numis_geek.services.auth import UserContext

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


class WorkspaceOut(BaseModel):
    id: str
    name: str

    @classmethod
    def from_orm(cls, ws: Workspace) -> "WorkspaceOut":
        return cls(id=ws.id, name=ws.name)


@router.get("", response_model=list[WorkspaceOut])
def list_workspaces(
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    if current_user.role != UserRole.sysadmin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="SysAdmin only.")
    items = db.query(Workspace).order_by(Workspace.name).all()
    return [WorkspaceOut.from_orm(w) for w in items]
