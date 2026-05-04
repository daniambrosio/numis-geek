import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from numis_geek.api.deps import get_current_user, get_db
from numis_geek.models.account import Account, AccountType, Currency
from numis_geek.models.asset import Asset
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.user import UserRole
from numis_geek.services.audit import AuditService
from numis_geek.services.auth import UserContext

router = APIRouter(prefix="/accounts", tags=["accounts"])


# ── schemas ───────────────────────────────────────────────────────────────────

class AccountOut(BaseModel):
    id: str
    workspace_id: str
    financial_institution_id: str
    financial_institution_name: str
    name: str
    account_type: str
    currency: str
    opening_balance: float | None
    account_info: str | None
    is_active: bool
    created_at: str

    @classmethod
    def from_orm(cls, account: Account, fi_name: str) -> "AccountOut":
        return cls(
            id=account.id,
            workspace_id=account.workspace_id,
            financial_institution_id=account.financial_institution_id,
            financial_institution_name=fi_name,
            name=account.name,
            account_type=account.account_type.value,
            currency=account.currency.value,
            opening_balance=float(account.opening_balance) if account.opening_balance is not None else None,
            account_info=account.account_info,
            is_active=account.is_active,
            created_at=account.created_at.isoformat(),
        )


class AccountRequest(BaseModel):
    name: str
    account_type: AccountType
    financial_institution_id: str
    currency: Currency
    opening_balance: Decimal | None = None
    account_info: str | None = None


# ── helpers ───────────────────────────────────────────────────────────────────

def _require_admin(current_user: UserContext) -> None:
    if current_user.role not in (UserRole.admin, UserRole.sysadmin):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only.")


def _get_or_404(db: Session, account_id: str) -> Account:
    acc = db.get(Account, account_id)
    if not acc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found.")
    return acc


def _fi_name(db: Session, fi_id: str) -> str:
    fi = db.get(FinancialInstitution, fi_id)
    return fi.short_name if fi else fi_id


# ── routes ────────────────────────────────────────────────────────────────────

@router.get("", response_model=list[AccountOut])
def list_accounts(
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    q = db.query(Account).filter(Account.is_active == True)  # noqa: E712
    if current_user.role != UserRole.sysadmin:
        q = q.filter(Account.workspace_id == current_user.workspace_id)
    accounts = q.order_by(Account.name).all()
    fi_ids = {a.financial_institution_id for a in accounts}
    fi_map = {
        fi.id: fi.short_name
        for fi in db.query(FinancialInstitution).filter(FinancialInstitution.id.in_(fi_ids)).all()
    }
    return [AccountOut.from_orm(a, fi_map.get(a.financial_institution_id, a.financial_institution_id)) for a in accounts]


class AssetLite(BaseModel):
    id: str
    workspace_id: str
    name: str
    ticker: str | None
    asset_class: str
    currency: str


class FinancialInstitutionLite(BaseModel):
    id: str
    short_name: str
    long_name: str
    logo_slug: str | None


class CustodianGroupOut(BaseModel):
    financial_institution: FinancialInstitutionLite
    accounts: list[AccountOut]
    assets: list[AssetLite]


@router.get("/by-custodian", response_model=list[CustodianGroupOut])
def list_by_custodian(
    workspace_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    """Group investment-type accounts and active assets by custodian (FI).

    Sysadmin: with `?workspace_id=` filter to that workspace; otherwise crosses
    all workspaces. Members/admins are always scoped to their own workspace.
    Skips FIs with neither investment accounts nor assets.
    """
    acc_q = db.query(Account).filter(
        Account.is_active == True,  # noqa: E712
        Account.account_type == AccountType.investment,
    )
    asset_q = db.query(Asset).filter(Asset.is_active == True)  # noqa: E712

    if current_user.role == UserRole.sysadmin:
        if workspace_id:
            acc_q = acc_q.filter(Account.workspace_id == workspace_id)
            asset_q = asset_q.filter(Asset.workspace_id == workspace_id)
    else:
        acc_q = acc_q.filter(Account.workspace_id == current_user.workspace_id)
        asset_q = asset_q.filter(Asset.workspace_id == current_user.workspace_id)

    accounts = acc_q.all()
    assets = asset_q.all()

    fi_ids = {a.financial_institution_id for a in accounts} | {a.financial_institution_id for a in assets}
    if not fi_ids:
        return []

    fis = {
        fi.id: fi
        for fi in db.query(FinancialInstitution).filter(FinancialInstitution.id.in_(fi_ids)).all()
    }

    groups: list[CustodianGroupOut] = []
    for fi_id, fi in fis.items():
        fi_accounts = [a for a in accounts if a.financial_institution_id == fi_id]
        fi_assets = [a for a in assets if a.financial_institution_id == fi_id]
        if not fi_accounts and not fi_assets:
            continue
        groups.append(
            CustodianGroupOut(
                financial_institution=FinancialInstitutionLite(
                    id=fi.id,
                    short_name=fi.short_name,
                    long_name=fi.long_name,
                    logo_slug=fi.logo_slug,
                ),
                accounts=[AccountOut.from_orm(a, fi.short_name) for a in fi_accounts],
                assets=sorted(
                    [
                        AssetLite(
                            id=a.id,
                            workspace_id=a.workspace_id,
                            name=a.name,
                            ticker=a.ticker,
                            asset_class=a.asset_class.value,
                            currency=a.currency.value,
                        )
                        for a in fi_assets
                    ],
                    key=lambda x: (x.ticker or "", x.name),
                ),
            )
        )
    groups.sort(key=lambda g: g.financial_institution.short_name.lower())
    return groups


@router.post("", response_model=AccountOut, status_code=status.HTTP_201_CREATED)
def create_account(
    body: AccountRequest,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    _require_admin(current_user)
    fi = db.get(FinancialInstitution, body.financial_institution_id)
    if not fi or not fi.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Financial institution not found.")
    workspace_id = current_user.workspace_id
    if workspace_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Sysadmin must specify workspace.")
    now = datetime.now(timezone.utc)
    account = Account(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        financial_institution_id=body.financial_institution_id,
        name=body.name,
        account_type=body.account_type,
        currency=body.currency,
        opening_balance=body.opening_balance if body.account_type == AccountType.checking else None,
        account_info=body.account_info,
        is_active=True,
        created_at=now,
        updated_at=now,
        created_by=current_user.user_id,
        updated_by=current_user.user_id,
    )
    db.add(account)
    db.flush()
    AuditService(db).log(
        user_email=current_user.user_id,
        action="account.created",
        workspace_id=workspace_id,
        user_id=current_user.user_id,
        resource_type="account",
        resource_id=account.id,
        details={"name": account.name, "account_type": account.account_type.value},
    )
    return AccountOut.from_orm(account, fi.short_name)


@router.put("/{account_id}", response_model=AccountOut)
def update_account(
    account_id: str,
    body: AccountRequest,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    _require_admin(current_user)
    account = _get_or_404(db, account_id)
    fi = db.get(FinancialInstitution, body.financial_institution_id)
    if not fi or not fi.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Financial institution not found.")
    account.name = body.name
    account.account_type = body.account_type
    account.financial_institution_id = body.financial_institution_id
    account.currency = body.currency
    account.opening_balance = body.opening_balance if body.account_type == AccountType.checking else None
    account.account_info = body.account_info
    account.updated_at = datetime.now(timezone.utc)
    account.updated_by = current_user.user_id
    db.flush()
    AuditService(db).log(
        user_email=current_user.user_id,
        action="account.updated",
        workspace_id=current_user.workspace_id,
        user_id=current_user.user_id,
        resource_type="account",
        resource_id=account.id,
        details={"name": account.name},
    )
    return AccountOut.from_orm(account, fi.short_name)


@router.put("/{account_id}/deactivate", response_model=AccountOut)
def deactivate_account(
    account_id: str,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    _require_admin(current_user)
    account = _get_or_404(db, account_id)
    account.is_active = False
    account.updated_at = datetime.now(timezone.utc)
    account.updated_by = current_user.user_id
    db.flush()
    fi_name = _fi_name(db, account.financial_institution_id)
    AuditService(db).log(
        user_email=current_user.user_id,
        action="account.deactivated",
        workspace_id=current_user.workspace_id,
        user_id=current_user.user_id,
        resource_type="account",
        resource_id=account.id,
        details={"name": account.name},
    )
    return AccountOut.from_orm(account, fi_name)
