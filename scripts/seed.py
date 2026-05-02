"""
Creates initial workspace, admin user, and sysadmin user.
Run once: python scripts/seed.py
"""
import uuid
from datetime import datetime, timezone

import bcrypt

from numis_geek.config import SYSADMIN_PASSWORD
from numis_geek.db.base import Base
from numis_geek.db.session import SessionLocal, engine
from numis_geek.models import Workspace, User  # noqa: F401 — registers models
from numis_geek.models.user import UserRole
from numis_geek.services.workspace import WorkspaceService
from numis_geek.services.user import UserService

Base.metadata.create_all(engine)

db = SessionLocal()

# ── Regular admin user ────────────────────────────────────────────────────────
existing = db.query(User).filter(User.email == "daniel.ambrosio@gmail.com").first()
if not existing:
    ws = WorkspaceService(db).create("Família Ambrosio")
    UserService(db).create(ws.id, "daniel.ambrosio@gmail.com", "changeme", UserRole.admin)
    ws_name = ws.name
    db.commit()
    print(f"Workspace '{ws_name}' criado.")
    print("Usuário: daniel.ambrosio@gmail.com / changeme")
else:
    print("Admin já existe. Pulando criação do workspace.")

# ── Sysadmin user ─────────────────────────────────────────────────────────────
sysadmin_email = "sysadmin@numis-geek.internal"
existing_sysadmin = db.query(User).filter(User.email == sysadmin_email).first()
if not existing_sysadmin:
    now = datetime.now(timezone.utc)
    sysadmin = User(
        id=str(uuid.uuid4()),
        workspace_id=None,
        email=sysadmin_email,
        name="System Admin",
        password_hash=bcrypt.hashpw(SYSADMIN_PASSWORD.encode(), bcrypt.gensalt()).decode(),
        role=UserRole.sysadmin,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(sysadmin)
    db.commit()
    print(f"Sysadmin criado: {sysadmin_email} / {SYSADMIN_PASSWORD}")
else:
    print("Sysadmin já existe. Pulando.")

db.close()
