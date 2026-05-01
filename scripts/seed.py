"""
Creates an initial workspace and admin user.
Run once: python scripts/seed.py
"""
from numis_geek.db.base import Base
from numis_geek.db.session import engine, SessionLocal
from numis_geek.models import Workspace, User  # noqa: F401 — registers models
from numis_geek.models.user import UserRole
from numis_geek.services.workspace import WorkspaceService
from numis_geek.services.user import UserService

Base.metadata.create_all(engine)

db = SessionLocal()

existing = db.query(User).filter(User.email == "daniel.ambrosio@gmail.com").first()
if existing:
    print("Seed já executado. Nada a fazer.")
    db.close()
    raise SystemExit(0)

ws = WorkspaceService(db).create("Família Ambrosio")
UserService(db).create(ws.id, "daniel.ambrosio@gmail.com", "changeme", UserRole.admin)
db.commit()

ws_name = ws.name
db.close()

print(f"Workspace '{ws_name}' criado.")
print("Usuário: daniel.ambrosio@gmail.com / changeme")
