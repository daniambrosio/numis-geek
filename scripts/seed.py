"""
Creates initial workspace, admin user, sysadmin user, financial institutions, and example accounts.
Run once: python scripts/seed.py
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import bcrypt

from numis_geek.config import SYSADMIN_PASSWORD
from numis_geek.db.base import Base
from numis_geek.db.session import SessionLocal, engine
from numis_geek.models import Workspace, User, FinancialInstitution  # noqa: F401 — registers models
from numis_geek.models.account import Account, AccountType, Currency
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
    ws = db.query(Workspace).filter(Workspace.id == existing.workspace_id).first()
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
    existing_sysadmin = sysadmin
    print(f"Sysadmin criado: {sysadmin_email} / {SYSADMIN_PASSWORD}")
else:
    print("Sysadmin já existe. Pulando.")

# ── Example accounts ──────────────────────────────────────────────────────────
if ws:
    ws_id = ws.id
    sysadmin_id = existing_sysadmin.id if existing_sysadmin else None

    # Look up financial institutions for seeding
    itau = db.query(FinancialInstitution).filter(FinancialInstitution.short_name == "Itaú").first()
    xp = db.query(FinancialInstitution).filter(FinancialInstitution.short_name == "XP").first()

    example_accounts = []
    if itau:
        example_accounts.append({
            "name": "Itaú Corrente",
            "account_type": AccountType.checking,
            "currency": Currency.BRL,
            "financial_institution_id": itau.id,
            "opening_balance": Decimal("0.00"),
            "account_info": None,
        })
    if xp:
        example_accounts.append({
            "name": "XP Investimentos",
            "account_type": AccountType.investment,
            "currency": Currency.BRL,
            "financial_institution_id": xp.id,
            "opening_balance": None,
            "account_info": None,
        })

    for acc_data in example_accounts:
        existing_acc = db.query(Account).filter(
            Account.workspace_id == ws_id,
            Account.name == acc_data["name"],
        ).first()
        if not existing_acc:
            now = datetime.now(timezone.utc)
            acc = Account(
                id=str(uuid.uuid4()),
                workspace_id=ws_id,
                financial_institution_id=acc_data["financial_institution_id"],
                name=acc_data["name"],
                account_type=acc_data["account_type"],
                currency=acc_data["currency"],
                opening_balance=acc_data["opening_balance"],
                account_info=acc_data["account_info"],
                is_active=True,
                created_at=now,
                updated_at=now,
                created_by=sysadmin_id,
                updated_by=sysadmin_id,
            )
            db.add(acc)
            db.commit()
            print(f"Conta criada: {acc_data['name']}")
        else:
            print(f"Conta '{acc_data['name']}' já existe. Pulando.")

db.close()
