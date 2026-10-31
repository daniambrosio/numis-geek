"""Spec 70 fase 3 (= fase 2 da spec 80) — saldo derivado da conta corrente.

Regra (spec 80): uma conta corrente tem UMA fonte de saldo — o ledger.

    balance(conta, d) = opening_balance + Σ amount das tx CHECKING da conta
                        com opening_balance_date < event_date <= d

Sem `opening_balance_date`, soma todas as tx até `d` (abertura 0 ou o
valor informado). Moeda nativa da conta.

O ativo CASH com `linked_account_id` é o espelho da conta no fechamento:
com `balance_from_ledger` ligado na conta, em fechamento OPEN/IN_REVIEW com `period_end >= opening_balance_date`, o
item do ativo puxa o saldo derivado em vez do digitado. Fechamento CLOSED
nunca é sobrescrito — a divergência aparece na conferência
(`balance_check`) e a decisão é do user, mês a mês.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from numis_geek.models.account import Account, AccountType, Currency
from numis_geek.models.asset import Asset
from numis_geek.models.portfolio_snapshot import (
    PortfolioSnapshot, PortfolioSnapshotItem, SnapshotPendency, SnapshotStatus,
)
from numis_geek.models.transaction import Transaction, TransactionSourceType

CENT = Decimal("0.01")
DERIVED_NOTE = "Saldo derivado da conta corrente (spec 70) — não precisa de edição manual."


def derived_balance(db: Session, account: Account, as_of: date) -> Decimal:
    q = db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
        Transaction.source_type == TransactionSourceType.CHECKING,
        Transaction.checking_account_id == account.id,
        Transaction.event_date <= as_of,
    )
    if account.opening_balance_date is not None:
        q = q.filter(Transaction.event_date > account.opening_balance_date)
    flow = Decimal(q.scalar() or 0)
    opening = Decimal(account.opening_balance or 0)
    return (opening + flow).quantize(CENT)


def derives_on(account: Account | None, period_end: date) -> bool:
    """O saldo derivado vale pra essa data? Interruptor desligado ou antes da
    abertura, segue digitado."""
    return (
        account is not None
        and account.account_type == AccountType.checking
        and account.balance_from_ledger
        and account.opening_balance_date is not None
        and period_end >= account.opening_balance_date
    )


def linked_account(db: Session, asset: Asset) -> Account | None:
    if not asset.linked_account_id:
        return None
    return db.get(Account, asset.linked_account_id)


def item_values(
    balance: Decimal, currency: Currency, fx: Decimal | None,
) -> tuple[Decimal, Decimal, Decimal | None, Decimal | None]:
    """(unit_price, mv_native, mv_brl, mv_usd) de um item value-mode qty=1.
    Invariante mv_columns_invariant: as 4 colunas andam juntas."""
    mv_brl: Decimal | None = None
    mv_usd: Decimal | None = None
    if currency == Currency.BRL:
        mv_brl = balance
        if fx and fx > 0:
            mv_usd = (balance / fx).quantize(CENT)
    else:
        mv_usd = balance
        if fx and fx > 0:
            mv_brl = (balance * fx).quantize(CENT)
    return balance, balance, mv_brl, mv_usd


def _recompute_header(db: Session, snap: PortfolioSnapshot) -> None:
    items = db.query(PortfolioSnapshotItem).filter(PortfolioSnapshotItem.snapshot_id == snap.id).all()
    snap.total_value_brl = sum((i.market_value_brl or Decimal("0") for i in items), Decimal("0"))
    snap.total_value_usd = sum((i.market_value_usd or Decimal("0") for i in items), Decimal("0"))
    snap.total_invested_brl = sum((i.total_invested_brl or Decimal("0") for i in items), Decimal("0"))


def _resolve_manual_pendencies(db: Session, snap: PortfolioSnapshot, asset_id: str, now: datetime) -> int:
    open_pens = db.query(SnapshotPendency).filter(
        SnapshotPendency.snapshot_id == snap.id,
        SnapshotPendency.asset_id == asset_id,
        SnapshotPendency.resolved_at.is_(None),
    ).all()
    for p in open_pens:
        p.resolved_at = now
        p.resolution_note = DERIVED_NOTE
    return len(open_pens)


def refresh_linked_cash_items(db: Session, snap: PortfolioSnapshot, *, now: datetime | None = None) -> int:
    """Aplica o saldo derivado aos itens de ativos CASH vinculados de um
    fechamento OPEN/IN_REVIEW. Cria o item se faltar (ativo vinculado sempre
    entra no fechamento quando o derivado vale). CLOSED → no-op.
    Retorna quantos itens mudaram."""
    if snap.status == SnapshotStatus.CLOSED or not snap.is_active:
        return 0
    now = now or datetime.now(timezone.utc)
    linked_assets = db.query(Asset).filter(
        Asset.workspace_id == snap.workspace_id,
        Asset.linked_account_id.isnot(None),
        Asset.is_active == True,  # noqa: E712
    ).all()
    changed = 0
    for asset in linked_assets:
        acc = linked_account(db, asset)
        if not derives_on(acc, snap.period_end_date):
            continue
        balance = derived_balance(db, acc, snap.period_end_date)
        unit, mv_native, mv_brl, mv_usd = item_values(balance, acc.currency, snap.fx_rate_usd_brl)
        item = db.query(PortfolioSnapshotItem).filter(
            PortfolioSnapshotItem.snapshot_id == snap.id,
            PortfolioSnapshotItem.asset_id == asset.id,
        ).first()
        if item is None:
            item = PortfolioSnapshotItem(
                snapshot_id=snap.id, asset_id=asset.id,
                average_cost_brl=Decimal("0"), total_invested_brl=Decimal("0"),
                created_at=now,
            )
            db.add(item)
        elif (
            item.quantity == Decimal("1") and item.unit_price == unit and item.market_value_native == mv_native
            and item.market_value_brl == mv_brl and item.market_value_usd == mv_usd
        ):
            _resolve_manual_pendencies(db, snap, asset.id, now)
            continue
        item.quantity = Decimal("1")
        item.unit_price = unit
        item.market_value_native = mv_native
        item.market_value_brl = mv_brl
        item.market_value_usd = mv_usd
        item.updated_at = now
        _resolve_manual_pendencies(db, snap, asset.id, now)
        changed += 1
    if changed:
        db.flush()
        _recompute_header(db, snap)
    db.flush()
    return changed


def refresh_open_snapshots(db: Session, workspace_id: str) -> int:
    """Depois de mexer no ledger: reaplica o derivado em todo fechamento
    aberto do workspace (são poucos — normalmente 0 ou 1)."""
    snaps = db.query(PortfolioSnapshot).filter(
        PortfolioSnapshot.workspace_id == workspace_id,
        PortfolioSnapshot.is_active == True,  # noqa: E712
        PortfolioSnapshot.status != SnapshotStatus.CLOSED,
    ).all()
    return sum(refresh_linked_cash_items(db, s) for s in snaps)


@dataclass
class BalanceCheckRow:
    snapshot_id: str
    period_end_date: date
    status: str
    typed: Decimal | None
    derived: Decimal
    difference: Decimal | None


def balance_check(db: Session, account: Account) -> list[BalanceCheckRow]:
    """Conferência mês a mês: saldo do fechamento (digitado ou já derivado)
    × saldo derivado do ledger, pra cada fechamento a partir da abertura."""
    asset = db.query(Asset).filter(Asset.linked_account_id == account.id).first()
    if asset is None or account.opening_balance_date is None:
        return []
    snaps = db.query(PortfolioSnapshot).filter(
        PortfolioSnapshot.workspace_id == account.workspace_id,
        PortfolioSnapshot.is_active == True,  # noqa: E712
        PortfolioSnapshot.period_end_date >= account.opening_balance_date,
    ).order_by(PortfolioSnapshot.period_end_date.desc()).all()
    rows = []
    for s in snaps:
        item = db.query(PortfolioSnapshotItem).filter(
            PortfolioSnapshotItem.snapshot_id == s.id,
            PortfolioSnapshotItem.asset_id == asset.id,
        ).first()
        typed = Decimal(item.market_value_native) if item and item.market_value_native is not None else None
        derived = derived_balance(db, account, s.period_end_date)
        rows.append(BalanceCheckRow(
            snapshot_id=s.id, period_end_date=s.period_end_date, status=s.status.value,
            typed=typed, derived=derived,
            difference=(derived - typed).quantize(CENT) if typed is not None else None,
        ))
    return rows


def month_end_series(db: Session, account: Account, months: int = 6, today: date | None = None) -> list[tuple[date, Decimal]]:
    """Saldo derivado no último dia de cada um dos últimos `months` meses
    (o corrente = hoje). Sparkline do hero."""
    today = today or date.today()
    out: list[tuple[date, Decimal]] = []
    y, m = today.year, today.month
    for _ in range(months):
        if (y, m) == (today.year, today.month):
            d = today
        else:
            nm_y, nm_m = (y + 1, 1) if m == 12 else (y, m + 1)
            d = date(nm_y, nm_m, 1).fromordinal(date(nm_y, nm_m, 1).toordinal() - 1)
        out.append((d, derived_balance(db, account, d)))
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return list(reversed(out))
