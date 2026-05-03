"""
Creates initial workspace, admin user, sysadmin user, financial institutions,
and accounts. Idempotent — safe to run multiple times.

Assets are no longer seeded from a hard-coded list. Instead, if
`data/notion_export.json` exists at seed time it is imported via
`scripts/import_notion_assets.import_from_json`. Otherwise, asset seeding is
skipped with an info message.
"""
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import bcrypt

from numis_geek.config import SYSADMIN_PASSWORD
from numis_geek.db.base import Base
from numis_geek.db.session import SessionLocal, engine
from numis_geek.models import Workspace, User, FinancialInstitution  # noqa: F401 — registers models
from numis_geek.models.account import Account, AccountType, Currency
from numis_geek.models.user import UserRole
from numis_geek.services.workspace import WorkspaceService
from numis_geek.services.user import UserService

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from import_notion_assets import (  # noqa: E402  — must be after sys.path tweak
    DEFAULT_JSON_PATH as NOTION_EXPORT_PATH,
    import_from_json as import_notion_assets,
)

Base.metadata.create_all(engine)

db = SessionLocal()

# ── Regular admin user ────────────────────────────────────────────────────────
existing = db.query(User).filter(User.email == "daniel.ambrosio@gmail.com").first()
if not existing:
    ws = WorkspaceService(db).create("Família Ambrosio")
    UserService(db).create(ws.id, "daniel.ambrosio@gmail.com", "changeme", UserRole.admin)
    db.commit()
    print(f"Workspace '{ws.name}' criado.")
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

# ── 'Particular' financial institution (fallback custodian) ───────────────────
existing_particular = db.query(FinancialInstitution).filter(
    FinancialInstitution.short_name == "Particular"
).first()
if not existing_particular:
    now = datetime.now(timezone.utc)
    particular = FinancialInstitution(
        id=str(uuid.uuid4()),
        long_name="Particular (sem instituição)",
        short_name="Particular",
        logo_slug="particular",
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(particular)
    db.commit()
    print("Instituição 'Particular' criada.")
else:
    print("Instituição 'Particular' já existe.")

# ── Accounts ──────────────────────────────────────────────────────────────────
if ws:
    ws_id = ws.id
    sysadmin_id = existing_sysadmin.id if existing_sysadmin else None

    # Build a lookup map: short_name → FI
    all_fi = {fi.short_name: fi for fi in db.query(FinancialInstitution).filter(FinancialInstitution.is_active == True).all()}  # noqa: E712

    # (name, account_type, currency, fi_short_name)
    ACCOUNTS = [
        ("Conta Corrente Itaú",           AccountType.checking,   Currency.BRL, "Itaú"),
        ("Conta Investimento Itaú",        AccountType.investment,  Currency.BRL, "Itaú"),
        ("Conta Investimento XP",          AccountType.investment,  Currency.BRL, "XP"),
        ("Conta Investimento BTG",         AccountType.investment,  Currency.BRL, "BTG"),
        ("Conta Previdência Bradesco",     AccountType.investment,  Currency.BRL, "Bradesco"),
        ("Conta Corrente Wise",            AccountType.checking,   Currency.BRL, "Wise"),
        ("Conta Investimento Avenue",      AccountType.investment,  Currency.USD, "Avenue"),
        ("Conta Corrente Caixa",           AccountType.checking,   Currency.BRL, "Caixa"),
        ("Conta Investimento Clear",       AccountType.investment,  Currency.BRL, "Clear"),
        ("Conta Investimento Coinbase",    AccountType.investment,  Currency.USD, "Coinbase"),
        ("Conta Corrente Mercado Pago",    AccountType.checking,   Currency.BRL, "Mercado Pago"),
        ("Conta Investimento Mercado Pago",AccountType.investment,  Currency.BRL, "Mercado Pago"),
        ("Conta Previdência Santander",    AccountType.investment,  Currency.BRL, "Santander"),
    ]

    for name, acc_type, currency, fi_slug in ACCOUNTS:
        fi = all_fi.get(fi_slug)
        if not fi:
            print(f"  ⚠ Instituição '{fi_slug}' não encontrada — pulando '{name}'.")
            continue

        existing_acc = db.query(Account).filter(
            Account.workspace_id == ws_id,
            Account.name == name,
        ).first()

        if not existing_acc:
            now = datetime.now(timezone.utc)
            acc = Account(
                id=str(uuid.uuid4()),
                workspace_id=ws_id,
                financial_institution_id=fi.id,
                name=name,
                account_type=acc_type,
                currency=currency,
                opening_balance=None,
                account_info=None,
                is_active=True,
                created_at=now,
                updated_at=now,
                created_by=sysadmin_id,
                updated_by=sysadmin_id,
            )
            db.add(acc)
            db.commit()
            print(f"  Conta criada: {name}")
        else:
            print(f"  Conta já existe: {name}")

# ── Assets ────────────────────────────────────────────────────────────────────
# Hard-coded starter assets are gone. Asset data now comes from
# data/notion_export.json (produced by orchestration outside the script).
if ws and NOTION_EXPORT_PATH.exists():
    print(f"Importando ativos de {NOTION_EXPORT_PATH.relative_to(REPO_ROOT)}…")
    summary = import_notion_assets(NOTION_EXPORT_PATH, apply=True, workspace_name=ws.name)
    summary.print_report(applied=True)
elif ws:
    print(
        f"Snapshot Notion não encontrado em {NOTION_EXPORT_PATH.relative_to(REPO_ROOT)} "
        "— pulando seed de ativos."
    )

db.close()
