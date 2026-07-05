import bcrypt
from sqlalchemy.orm import Session

from numis_geek.exceptions import PermissionError
from numis_geek.models.user import User, UserRole


class UserService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, workspace_id: str, email: str, password: str, role: UserRole) -> User:
        user = User(
            workspace_id=workspace_id,
            email=email.lower(),
            password_hash=bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode(),
            role=role,
        )
        self.db.add(user)
        self.db.flush()
        return user

    def deactivate(self, user_id: str, acting_user: User) -> None:
        if acting_user.role not in (UserRole.admin, UserRole.sysadmin):
            raise PermissionError("Only admins can deactivate users.")
        user = self.db.get(User, user_id)
        if user:
            user.is_active = False
            self.db.flush()

    def invite(self, workspace_id: str, email: str, password: str, acting_user: User) -> User:
        if acting_user.role not in (UserRole.admin, UserRole.sysadmin):
            raise PermissionError("Only admins can invite users.")
        return self.create(workspace_id, email, password, UserRole.member)
