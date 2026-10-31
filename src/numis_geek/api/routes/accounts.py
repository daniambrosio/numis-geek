import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, model_validator
from sqlalchemy.orm import Session

from numis_geek.api.deps import get_current_user, get_db
from numis_geek.models.account import Account, AccountType, Currency
from numis_geek.models.asset import Asset, AssetClass
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.transaction import Transaction, TransactionSourceType
from numis_geek.models.user import UserRole
from numis_geek.models.workspace import Workspace
from numis_geek.services import account_balance
from numis_geek.services.audit import AuditService
from numis_geek.services.fx import FxRateNotFound, fx_rate_on
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
    opening_balance_date: str | None
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
            opening_balance_date=(
                account.opening_balance_date.isoformat()
                if account.opening_balance_date is not None else None
            ),
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
    # Spec 80 — a partir de quando o saldo derivado soma transações.
    # Obrigatória quando há saldo de abertura: sem data o valor é ambíguo.
    opening_balance_date: date | None = None
    account_info: str | None = None

    @model_validator(mode="after")
    def _validate(self) -> "AccountRequest":
        if self.account_type == AccountType.checking and self.opening_balance is not None:
            if self.opening_balance_date is None:
                raise ValueError(
                    "opening_balance_date is required when opening_balance is set",
                )
        return self


# ── helpers ───────────────────────────────────────────────────────────────────

def _require_admin(current_user: UserContext) -> None:
    if current_user.role not in (UserRole.admin, UserRole.sysadmin):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only.")


def _get_or_404(db: Session, account_id: str) -> Account:
    acc = db.get(Account, account_id)
    if not acc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found.")
    return acc


def _check_workspace_access(acc: Account, current_user: UserContext) -> None:
    """Audit 2026-07-05: PUT /accounts/{id} + deactivate não checavam
    workspace. Admin de ws A conseguia editar/desativar account de ws B
    conhecendo o UUID. Sysadmin (híbrido ou puro) continua com acesso
    cross-workspace por design."""
    if current_user.role == UserRole.sysadmin:
        return
    if acc.workspace_id != current_user.workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found.")


def _fi_name(db: Session, fi_id: str) -> str:
    fi = db.get(FinancialInstitution, fi_id)
    return fi.short_name if fi else fi_id


# ── routes ────────────────────────────────────────────────────────────────────

@router.get("", response_model=list[AccountOut])
def list_accounts(
    workspace_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    q = db.query(Account).filter(Account.is_active == True)  # noqa: E712
    if current_user.role == UserRole.sysadmin:
        # Sysadmin híbrido: default no do user; ?workspace_id= sobrescreve.
        target_ws = workspace_id or current_user.workspace_id
        if target_ws:
            q = q.filter(Account.workspace_id == target_ws)
    else:
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
        # Sysadmin híbrido: default no do user; ?workspace_id= sobrescreve.
        target_ws = workspace_id or current_user.workspace_id
        if target_ws:
            acc_q = acc_q.filter(Account.workspace_id == target_ws)
            asset_q = asset_q.filter(Asset.workspace_id == target_ws)
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
    workspace_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    _require_admin(current_user)
    fi = db.get(FinancialInstitution, body.financial_institution_id)
    if not fi or not fi.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Financial institution not found.")
    # Fase 3.6 (2026-07-22): sysadmin híbrido usa o próprio workspace por
    # default; sysadmin puro (workspace_id=None) tem que passar via
    # query param — antes batia 400 permanente.
    if current_user.role == UserRole.sysadmin:
        target_ws = workspace_id or current_user.workspace_id
        if not target_ws:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="workspace_id is required for sysadmin without workspace.",
            )
        # Sanity: workspace precisa existir
        if not db.get(Workspace, target_ws):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found.")
        workspace_id = target_ws
    else:
        workspace_id = current_user.workspace_id
        if workspace_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No workspace bound to user.")
    now = datetime.now(timezone.utc)
    account = Account(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        financial_institution_id=body.financial_institution_id,
        name=body.name,
        account_type=body.account_type,
        currency=body.currency,
        opening_balance=body.opening_balance if body.account_type == AccountType.checking else None,
        opening_balance_date=(
            body.opening_balance_date if body.account_type == AccountType.checking else None
        ),
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
    _check_workspace_access(account, current_user)
    fi = db.get(FinancialInstitution, body.financial_institution_id)
    if not fi or not fi.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Financial institution not found.")
    account.name = body.name
    account.account_type = body.account_type
    account.financial_institution_id = body.financial_institution_id
    account.currency = body.currency
    account.opening_balance = body.opening_balance if body.account_type == AccountType.checking else None
    account.opening_balance_date = (
        body.opening_balance_date if body.account_type == AccountType.checking else None
    )
    account.account_info = body.account_info
    account.updated_at = datetime.now(timezone.utc)
    account.updated_by = current_user.user_id
    db.flush()
    AuditService(db).log(
        user_email=current_user.user_id,
        action="account.updated",
        # Fase 3 audit: workspace do RECURSO, não do ator. Sysadmin
        # editando conta de outro workspace precisa aparecer no audit
        # log do workspace da conta pra rastreabilidade.
        workspace_id=account.workspace_id,
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
    _check_workspace_access(account, current_user)
    account.is_active = False
    account.updated_at = datetime.now(timezone.utc)
    account.updated_by = current_user.user_id
    db.flush()
    fi_name = _fi_name(db, account.financial_institution_id)
    AuditService(db).log(
        user_email=current_user.user_id,
        action="account.deactivated",
        workspace_id=account.workspace_id,
        user_id=current_user.user_id,
        resource_type="account",
        resource_id=account.id,
        details={"name": account.name},
    )
    return AccountOut.from_orm(account, fi_name)


# ── Spec 70 fase 3 — detalhe da conta corrente, saldo derivado, conferência ──

class LinkedAssetRef(BaseModel):
    id: str
    name: str


class BalancePoint(BaseModel):
    date: str
    balance: float


class MonthFlow(BaseModel):
    inflows: float
    outflows: float
    net: float


class AccountDetailOut(AccountOut):
    fi_long_name: str | None
    fi_logo_slug: str | None
    # Saldo derivado hoje (checking); None em conta de investimento.
    balance: float | None
    # Conta em USD: saldo × PTAX de hoje (walkback); BRL = o próprio saldo.
    balance_brl: float | None
    balance_series: list[BalancePoint]
    month: MonthFlow | None
    linked_asset: LinkedAssetRef | None


class BalanceCheckRowOut(BaseModel):
    snapshot_id: str
    period_end_date: str
    status: str
    typed: float | None
    derived: float
    difference: float | None


class OpeningBalanceRequest(BaseModel):
    opening_balance: Decimal | None = None
    opening_balance_date: date | None = None

    @model_validator(mode="after")
    def _validate(self) -> "OpeningBalanceRequest":
        if self.opening_balance is not None and self.opening_balance_date is None:
            raise ValueError("opening_balance_date is required when opening_balance is set")
        return self


class LinkAssetRequest(BaseModel):
    asset_id: str | None = None  # None desvincula


def _scoped_or_404(db: Session, account_id: str, current_user: UserContext) -> Account:
    acc = _get_or_404(db, account_id)
    _check_workspace_access(acc, current_user)
    return acc


def _detail(db: Session, acc: Account) -> AccountDetailOut:
    fi = db.get(FinancialInstitution, acc.financial_institution_id)
    base = AccountOut.from_orm(acc, fi.short_name if fi else acc.financial_institution_id).model_dump()
    linked = db.query(Asset).filter(Asset.linked_account_id == acc.id).first()
    balance = None
    balance_brl = None
    series: list[BalancePoint] = []
    month = None
    if acc.account_type == AccountType.checking:
        today = date.today()
        balance_dec = account_balance.derived_balance(db, acc, today)
        balance = float(balance_dec)
        if acc.currency == Currency.BRL:
            balance_brl = balance
        else:
            try:
                balance_brl = float((balance_dec * fx_rate_on(db, today)).quantize(Decimal("0.01")))
            except FxRateNotFound:
                balance_brl = None
        series = [
            BalancePoint(date=d.isoformat(), balance=float(b))
            for d, b in account_balance.month_end_series(db, acc, 6, today)
        ]
        rows = db.query(Transaction.amount).filter(
            Transaction.source_type == TransactionSourceType.CHECKING,
            Transaction.checking_account_id == acc.id,
            Transaction.event_date >= today.replace(day=1),
            Transaction.event_date <= today,
        ).all()
        inflows = sum((float(a) for (a,) in rows if a > 0), 0.0)
        outflows = sum((float(a) for (a,) in rows if a < 0), 0.0)
        month = MonthFlow(inflows=inflows, outflows=outflows, net=inflows + outflows)
    return AccountDetailOut(
        **base,
        fi_long_name=fi.long_name if fi else None,
        fi_logo_slug=fi.logo_slug if fi else None,
        balance=balance,
        balance_brl=balance_brl,
        balance_series=series,
        month=month,
        linked_asset=LinkedAssetRef(id=linked.id, name=linked.name) if linked else None,
    )


@router.get("/{account_id}", response_model=AccountDetailOut)
def get_account(
    account_id: str,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    return _detail(db, _scoped_or_404(db, account_id, current_user))


@router.get("/{account_id}/balance-check", response_model=list[BalanceCheckRowOut])
def get_balance_check(
    account_id: str,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    """Conferência mês a mês: fechamento × saldo derivado (spec 70 fase 3)."""
    acc = _scoped_or_404(db, account_id, current_user)
    return [
        BalanceCheckRowOut(
            snapshot_id=r.snapshot_id,
            period_end_date=r.period_end_date.isoformat(),
            status=r.status,
            typed=float(r.typed) if r.typed is not None else None,
            derived=float(r.derived),
            difference=float(r.difference) if r.difference is not None else None,
        )
        for r in account_balance.balance_check(db, acc)
    ]


@router.patch("/{account_id}/opening-balance", response_model=AccountDetailOut)
def update_opening_balance(
    account_id: str,
    body: OpeningBalanceRequest,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    """Saldo de abertura editável — recua quando entram extratos antigos.
    Reaplica o derivado nos fechamentos abertos; CLOSED não muda."""
    _require_admin(current_user)
    acc = _scoped_or_404(db, account_id, current_user)
    if acc.account_type != AccountType.checking:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Saldo de abertura só existe em conta corrente.",
        )
    before = {
        "opening_balance": str(acc.opening_balance) if acc.opening_balance is not None else None,
        "opening_balance_date": acc.opening_balance_date.isoformat() if acc.opening_balance_date else None,
    }
    acc.opening_balance = body.opening_balance
    acc.opening_balance_date = body.opening_balance_date
    acc.updated_at = datetime.now(timezone.utc)
    acc.updated_by = current_user.user_id
    db.flush()
    account_balance.refresh_open_snapshots(db, acc.workspace_id)
    AuditService(db).log(
        user_email=current_user.user_id,
        action="account.opening_balance_updated",
        workspace_id=acc.workspace_id,
        user_id=current_user.user_id,
        resource_type="account",
        resource_id=acc.id,
        details={
            "name": acc.name,
            "before": before,
            "after": {
                "opening_balance": str(body.opening_balance) if body.opening_balance is not None else None,
                "opening_balance_date": body.opening_balance_date.isoformat() if body.opening_balance_date else None,
            },
        },
    )
    return _detail(db, acc)


@router.put("/{account_id}/linked-asset", response_model=AccountDetailOut)
def set_linked_asset(
    account_id: str,
    body: LinkAssetRequest,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    """Vincula (ou desvincula, asset_id=null) o ativo CASH espelho desta conta.
    Invariantes da spec 80: só CASH, só checking, 1:1, mesmo workspace."""
    from numis_geek.api.routes.assets import _resolve_linked_account

    _require_admin(current_user)
    acc = _scoped_or_404(db, account_id, current_user)
    current = db.query(Asset).filter(Asset.linked_account_id == acc.id).first()
    now = datetime.now(timezone.utc)
    if body.asset_id is None:
        if current is not None:
            current.linked_account_id = None
            current.updated_at = now
            current.updated_by = current_user.user_id
    else:
        asset = db.get(Asset, body.asset_id)
        if asset is None or asset.workspace_id != acc.workspace_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found.")
        if asset.asset_class != AssetClass.CASH:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Só ativo CASH pode espelhar conta corrente.",
            )
        if asset.linked_account_id and asset.linked_account_id != acc.id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Ativo já espelha outra conta corrente.",
            )
        # Troca de ativo: solta o atual antes de validar o 1:1.
        if current is not None and current.id != asset.id:
            current.linked_account_id = None
            current.updated_at = now
            current.updated_by = current_user.user_id
            db.flush()
        _resolve_linked_account(db, acc.id, acc.workspace_id, asset_id=asset.id)
        asset.linked_account_id = acc.id
        asset.updated_at = now
        asset.updated_by = current_user.user_id
    db.flush()
    account_balance.refresh_open_snapshots(db, acc.workspace_id)
    AuditService(db).log(
        user_email=current_user.user_id,
        action="account.linked_asset_updated",
        workspace_id=acc.workspace_id,
        user_id=current_user.user_id,
        resource_type="account",
        resource_id=acc.id,
        details={"name": acc.name, "before": current.id if current else None, "after": body.asset_id},
    )
    return _detail(db, acc)
