from sqlalchemy.orm import Session

from numis_geek.models.workspace import Workspace


class WorkspaceService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, name: str) -> Workspace:
        workspace = Workspace(name=name)
        self.db.add(workspace)
        self.db.flush()
        return workspace
