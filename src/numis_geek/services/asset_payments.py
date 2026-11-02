"""Spec 83 — Pagar e receber com ativos.

A despesa paga com um ativo (assinatura paga com USDC) ou a receita recebida
como ativo (cashback em BTC) é um PAR:

- `asset_movement` — SELL (despesa) ou BUY (receita), qty do ativo e
  `gross_amount` = valor da despesa/receita na moeda do ativo;
- `transaction` — `source_type=ASSET`, `asset_movement_id` → o movimento,
  `amount` = −gross (despesa) / +gross (receita), categoria e fornecedor.

O par nasce, muda e morre junto: este módulo é o ÚNICO lugar que mantém os
dois lados coerentes (data, valor, quantidade). Não mexe em saldo de conta
corrente nem em fatura. Ganho/perda realizado fica no lado do investimento
(spec 79), sem IR (tax engine adiado).

Mesmas convenções de `services/transactions.py`: levanta `TransactionError`
(422) / `TransactionConflict` (409), faz flush, nunca commit.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from numis_geek.models.account import Account
from numis_geek.models.asset import Asset
from numis_geek.models.asset_movement import AssetMovement, AssetMovementType
from numis_geek.models.transaction import Transaction, TransactionSourceType
from numis_geek.services.fx import resolve_fx_rate
from numis_geek.services.positions import _COTADO_CLASSES
from numis_geek.services.transactions import (
    TransactionConflict, TransactionError, _fill, _new_tx, resolve_tags, set_tags,
    to_cents, validate_category, validate_party,
)

# SELL = saiu ativo pra pagar algo (despesa, tx negativa);
# BUY = entrou ativo como pagamento recebido (receita, tx positiva).
LINKABLE_TYPES = {AssetMovementType.SELL: -1, AssetMovementType.BUY: 1}


QTY_Q = Decimal("0.00000001")


def is_value_mode(asset: Asset) -> bool:
    """Modo valor (memória value_mode_qty_1): qty=1, unit_price = valor
    total. Mesma regra de positions — tudo que não é cotado."""
    return asset.asset_class not in _COTADO_CLASSES


def linked_tx(db: Session, movement_id: str) -> Transaction | None:
    return db.query(Transaction).filter(Transaction.asset_movement_id == movement_id).first()


def linked_txs(db: Session, movement_ids: list[str]) -> dict[str, Transaction]:
    if not movement_ids:
        return {}
    rows = db.query(Transaction).filter(Transaction.asset_movement_id.in_(movement_ids)).all()
    return {t.asset_movement_id: t for t in rows}


def _get_asset(db: Session, workspace_id: str, asset_id: str) -> Asset:
    asset = db.get(Asset, asset_id)
    if not asset or asset.workspace_id != workspace_id:
        raise TransactionError("Ativo não encontrado.")
    if not asset.is_active:
        raise TransactionError("Ativo inativo.")
    linked = db.get(Account, asset.linked_account_id) if asset.linked_account_id else None
    if linked is not None and linked.balance_from_ledger:
        raise TransactionError(
            "Ativo espelho de conta corrente: pague pela conta (Movimentação de conta)."
        )
    return asset


def _quantity(asset: Asset, quantity) -> Decimal:
    if is_value_mode(asset):
        return Decimal("1")
    if quantity is None:
        raise TransactionError("Informe a quantidade do ativo.")
    try:
        q = Decimal(quantity).quantize(QTY_Q, ROUND_HALF_UP)
    except Exception:
        raise TransactionError("Quantidade inválida.")
    if q <= 0:
        raise TransactionError("Quantidade deve ser positiva.")
    return q


def _set_movement_amounts(m: AssetMovement, quantity: Decimal, gross: Decimal) -> None:
    m.quantity = quantity
    m.unit_price = (gross / quantity).quantize(QTY_Q, ROUND_HALF_UP)
    m.gross_amount = gross
    m.fee = None
    m.tax = None
    m.net_amount = gross


def create_asset_payment(
    db: Session,
    workspace_id: str,
    *,
    asset_id: str,
    direction: str,
    event_date: date,
    quantity,
    amount,
    description: str,
    category_id: str | None = None,
    party_id: str | None = None,
    notes: str | None = None,
    tag_ids: list[str] | None = None,
    user_id: str | None = None,
) -> tuple[AssetMovement, Transaction]:
    """Cria o par movimento + tx. `direction` = "EXPENSE" (SELL) ou
    "INCOME" (BUY); `amount` positivo, na moeda do ativo."""
    if direction not in ("EXPENSE", "INCOME"):
        raise TransactionError("Direção deve ser EXPENSE ou INCOME.")
    if event_date is None:
        raise TransactionError("Data obrigatória.")
    if not description or not description.strip():
        raise TransactionError("Descrição obrigatória.")
    gross = to_cents(amount)
    if gross <= 0:
        raise TransactionError("Valor deve ser positivo.")
    asset = _get_asset(db, workspace_id, asset_id)
    qty = _quantity(asset, quantity)
    validate_category(db, workspace_id, category_id)
    validate_party(db, workspace_id, party_id)
    tags = resolve_tags(db, workspace_id, tag_ids)

    now = datetime.now(timezone.utc)
    m = AssetMovement(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        asset_id=asset.id,
        type=AssetMovementType.SELL if direction == "EXPENSE" else AssetMovementType.BUY,
        event_date=event_date,
        currency=asset.currency,
        fx_rate=resolve_fx_rate(db, event_date),
        notes=notes,
        is_active=True,
        created_at=now, updated_at=now, created_by=user_id, updated_by=user_id,
    )
    _set_movement_amounts(m, qty, gross)
    db.add(m)
    db.flush()
    tx = _attach(db, m, description=description, category_id=category_id, party_id=party_id,
                 notes=notes, tag_ids=tags, user_id=user_id)
    return m, tx


def attach_transaction(
    db: Session,
    movement: AssetMovement,
    *,
    description: str,
    category_id: str | None = None,
    party_id: str | None = None,
    notes: str | None = None,
    tag_ids: list[str] | None = None,
    user_id: str | None = None,
) -> Transaction:
    """Liga uma tx a um movimento JÁ existente ("Foi uma despesa/receita" no
    composer de Lançamentos, e o backfill do Coinbase One)."""
    if not description or not description.strip():
        raise TransactionError("Descrição obrigatória.")
    if not movement.is_active:
        raise TransactionError("Lançamento inativo.")
    if movement.type not in LINKABLE_TYPES:
        raise TransactionError("Só venda (despesa) ou compra (receita) viram pagamento com ativo.")
    if linked_tx(db, movement.id) is not None:
        raise TransactionConflict("Esse lançamento já tem uma movimentação vinculada.")
    if movement.gross_amount is None or Decimal(movement.gross_amount) <= 0:
        raise TransactionError("Lançamento sem valor total — informe o valor.")
    _get_asset(db, movement.workspace_id, movement.asset_id)
    validate_category(db, movement.workspace_id, category_id)
    validate_party(db, movement.workspace_id, party_id)
    tags = resolve_tags(db, movement.workspace_id, tag_ids)
    return _attach(db, movement, description=description, category_id=category_id,
                   party_id=party_id, notes=notes, tag_ids=tags, user_id=user_id)


def _attach(db, m, *, description, category_id, party_id, notes, tag_ids, user_id) -> Transaction:
    sign = LINKABLE_TYPES[m.type]
    tx = _new_tx(
        m.workspace_id, user_id,
        source_type=TransactionSourceType.ASSET, asset_movement_id=m.id,
        event_date=m.event_date, description=description.strip(),
        amount=sign * Decimal(m.gross_amount).quantize(Decimal("0.01")),
        category_id=category_id, party_id=party_id, notes=notes,
    )
    # Não há extrato de banco pra conciliar: o lançamento do ativo é o
    # registro. Nasce conciliada pra não ficar pra sempre em "Não reconciliadas".
    tx.is_reconciled = True
    _fill(db, tx, currency=m.currency, statement_rate=None)
    db.add(tx)
    db.flush()
    set_tags(db, tx.id, tag_ids or [])
    return tx


# ── edição: um lado puxa o outro ─────────────────────────────────────────────

def sync_movement_from_tx(
    db: Session, tx: Transaction, *, quantity=None, user_id: str | None = None,
) -> AssetMovement:
    """Depois de editar a tx ASSET: data, valor (e quantidade, se veio)
    vão pro movimento. Sinal não troca — SELL não vira BUY."""
    m = db.get(AssetMovement, tx.asset_movement_id)
    if m is None or not m.is_active:
        raise TransactionConflict("Lançamento do ativo vinculado não existe mais.")
    sign = LINKABLE_TYPES.get(m.type)
    if sign is None or (tx.amount > 0) != (sign > 0):
        raise TransactionConflict(
            "Pagamento com ativo não troca de direção (despesa ↔ receita) — exclua e recrie."
        )
    asset = db.get(Asset, m.asset_id)
    qty = _quantity(asset, quantity) if quantity is not None else Decimal(m.quantity or 1)
    if m.event_date != tx.event_date:
        m.event_date = tx.event_date
        m.fx_rate = resolve_fx_rate(db, tx.event_date)
    _set_movement_amounts(m, qty, abs(Decimal(tx.amount)))
    m.updated_at = datetime.now(timezone.utc)
    m.updated_by = user_id
    db.flush()
    return m


def sync_tx_from_movement(
    db: Session, m: AssetMovement, *, user_id: str | None = None,
) -> Transaction | None:
    """Depois de editar o movimento vinculado: data e valor vão pra tx."""
    tx = linked_tx(db, m.id)
    if tx is None:
        return None
    sign = LINKABLE_TYPES.get(m.type)
    if sign is None:
        raise TransactionConflict(
            "Lançamento vinculado a uma movimentação continua venda/compra — exclua e recrie."
        )
    if m.gross_amount is None or Decimal(m.gross_amount) <= 0:
        raise TransactionError("Lançamento vinculado precisa de valor total positivo.")
    tx.event_date = m.event_date
    tx.amount = sign * to_cents(m.gross_amount)
    _fill(db, tx, currency=m.currency, statement_rate=None)
    tx.updated_at = datetime.now(timezone.utc)
    tx.updated_by = user_id
    db.flush()
    return tx


def deactivate_movement_of(db: Session, tx: Transaction, *, user_id: str | None = None) -> AssetMovement | None:
    """Apagar a tx ASSET desativa o movimento (lançamento de ativo é soft-delete)."""
    m = db.get(AssetMovement, tx.asset_movement_id) if tx.asset_movement_id else None
    if m is None or not m.is_active:
        return None
    m.is_active = False
    m.updated_at = datetime.now(timezone.utc)
    m.updated_by = user_id
    return m
