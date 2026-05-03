"""
Creates initial workspace, admin user, sysadmin user, financial institutions,
accounts, and assets. Idempotent — safe to run multiple times.
"""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import bcrypt

from numis_geek.config import SYSADMIN_PASSWORD
from numis_geek.db.base import Base
from numis_geek.db.session import SessionLocal, engine
from numis_geek.models import Workspace, User, FinancialInstitution  # noqa: F401 — registers models
from numis_geek.models.account import Account, AccountType, Currency
from numis_geek.models.asset import (
    Asset,
    AssetClass,
    FixedIncomeAsset,
    FixedIncomeIndexer,
    PhysicalAsset,
)
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
if ws:
    ws_id = ws.id
    sysadmin_id = existing_sysadmin.id if existing_sysadmin else None

    # Refresh FI map (Particular may have been just inserted)
    all_fi = {
        fi.short_name: fi
        for fi in db.query(FinancialInstitution).filter(FinancialInstitution.is_active == True).all()  # noqa: E712
    }

    # (asset_class, ticker, name, currency, fi_short_name, details_dict_or_None)
    ASSETS: list[tuple[AssetClass, str | None, str, Currency, str, dict | None]] = [
        (AssetClass.STOCK_BR, "PETR4",  "Petrobras PN",            Currency.BRL, "XP",         None),
        (AssetClass.STOCK_BR, "ITUB4",  "Itaú Unibanco PN",        Currency.BRL, "XP",         None),
        (AssetClass.STOCK_US, "AAPL",   "Apple Inc.",              Currency.USD, "Avenue",     None),
        (AssetClass.STOCK_US, "MSFT",   "Microsoft Corp.",         Currency.USD, "Avenue",     None),
        (AssetClass.FII,      "HGLG11", "CSHG Logística FII",      Currency.BRL, "XP",         None),
        (AssetClass.ETF,      "BOVA11", "iShares Ibovespa ETF",    Currency.BRL, "XP",         None),
        (AssetClass.ETF,      "SPY",    "SPDR S&P 500 ETF",        Currency.USD, "Avenue",     None),
        (AssetClass.REIT,     "O",      "Realty Income",           Currency.USD, "Avenue",     None),
        (AssetClass.CRYPTO,   "BTC",    "Bitcoin",                 Currency.USD, "Coinbase",   None),
        (
            AssetClass.FIXED_INCOME, None, "CDB BTG 110% CDI 2028", Currency.BRL, "XP",
            {
                "issuer": "Banco BTG Pactual",
                "issue_date": date(2024, 3, 15),
                "maturity_date": date(2028, 3, 15),
                "indexer": FixedIncomeIndexer.CDI,
                "rate": Decimal("110.0000"),
                "face_value": Decimal("50000.00"),
            },
        ),
        (
            AssetClass.REAL_ESTATE, None, "Apto Exemplo (sample)", Currency.BRL, "Particular",
            {
                "address": "Rua Exemplo, 100, ap 1",
                "city": "São Paulo",
                "state": "SP",
                "country": "BR",
                "area_m2": Decimal("75.00"),
            },
        ),
        (
            AssetClass.VEHICLE, None, "Carro Exemplo (sample)", Currency.BRL, "Particular",
            {
                "make": "Toyota",
                "model": "Corolla",
                "year": 2022,
                "license_plate": "ABC1D23",
            },
        ),
    ]

    for asset_class, ticker, name, currency, fi_slug, details in ASSETS:
        fi = all_fi.get(fi_slug)
        if not fi:
            print(f"  ⚠ Instituição '{fi_slug}' não encontrada — pulando '{name}'.")
            continue

        existing_asset = db.query(Asset).filter(
            Asset.workspace_id == ws_id,
            Asset.name == name,
        ).first()

        if existing_asset:
            print(f"  Ativo já existe: {name}")
            continue

        now = datetime.now(timezone.utc)
        asset = Asset(
            id=str(uuid.uuid4()),
            workspace_id=ws_id,
            financial_institution_id=fi.id,
            asset_class=asset_class,
            name=name,
            ticker=ticker,
            currency=currency,
            is_active=True,
            created_at=now,
            updated_at=now,
            created_by=sysadmin_id,
            updated_by=sysadmin_id,
        )
        if asset_class == AssetClass.FIXED_INCOME and details:
            asset.fixed_income = FixedIncomeAsset(
                issuer=details["issuer"],
                issue_date=details.get("issue_date"),
                maturity_date=details["maturity_date"],
                indexer=details["indexer"],
                rate=details["rate"],
                face_value=details.get("face_value"),
            )
        elif asset_class in (AssetClass.REAL_ESTATE, AssetClass.VEHICLE) and details:
            asset.physical = PhysicalAsset(
                address=details.get("address"),
                city=details.get("city"),
                state=details.get("state"),
                country=details.get("country"),
                area_m2=details.get("area_m2"),
                registration_number=details.get("registration_number"),
                make=details.get("make"),
                model=details.get("model"),
                year=details.get("year"),
                license_plate=details.get("license_plate"),
                chassis=details.get("chassis"),
            )
        db.add(asset)
        db.commit()
        print(f"  Ativo criado: {name}")

db.close()
