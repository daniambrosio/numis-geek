"""Spec 81 — rentabilidade mês a mês por ativo (retorno total).

Uma linha por fechamento CLOSED em que o ativo tem item. O retorno do mês
é ajustado por fluxo de caixa e inclui proventos:

    r = (mv_fim − mv_ini − aportes + resgates + proventos) / mv_ini

- `mv` vem do PortfolioSnapshotItem (congelado no fechamento).
- Aportes = BUY/SUBSCRIPTION, resgates = SELL/FULL_REDEMPTION, ambos pelo
  `net_amount` (uniforme entre cotado e modo valor, onde qty=1 e
  net=gross). COME_COTAS fica FORA: o imposto já está refletido no mv_fim e
  `asset_movements.py` grava net_amount = -tax — subtrair de novo
  penalizaria duas vezes. BONUS e ciclo de opção não movem caixa.
- Proventos vêm de `services/proventos.list_proventos` (inclui o
  OPTION_PREMIUM sintético atribuído ao subjacente, coerente com /proventos).
- Nativo é o primário (`return_pct`); BRL é secundário (`return_brl_pct`)
  usando o fx da própria linha — nunca recomputa PTAX.
- Janela de atribuição: event_date ∈ (fechamento anterior, fechamento].

`build_monthly_returns` do Markowitz reaproveita `cash_flows_in_window`.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable, Literal

from sqlalchemy.orm import Session

from numis_geek.models.account import Currency
from numis_geek.models.asset import Asset, AssetClass
from numis_geek.models.asset_movement import AssetMovement, AssetMovementType
from numis_geek.models.portfolio_snapshot import (
    PortfolioSnapshot,
    PortfolioSnapshotItem,
    SnapshotStatus,
)
from numis_geek.services.positions import _COTADO_CLASSES
from numis_geek.services.proventos import ProventoRow, list_proventos

APORTE_TYPES: frozenset[AssetMovementType] = frozenset({
    AssetMovementType.BUY,
    AssetMovementType.SUBSCRIPTION,
})
RESGATE_TYPES: frozenset[AssetMovementType] = frozenset({
    AssetMovementType.SELL,
    AssetMovementType.FULL_REDEMPTION,
})

NullReason = Literal["FIRST_CLOSING", "GAP", "ZERO_START", "MISSING_MV", "OPTION"]

_ZERO = Decimal("0")


# ── Data shapes ────────────────────────────────────────────────────────────


@dataclass
class PerformanceRow:
    period_end_date: date
    snapshot_id: str
    quantity: Decimal
    unit_price: Decimal | None
    market_value_native: Decimal | None
    market_value_brl: Decimal | None
    market_value_usd: Decimal | None
    total_invested_brl: Decimal | None
    fx_rate_usd_brl: Decimal | None
    pnl_brl: Decimal | None
    pnl_pct: Decimal | None
    aportes_native: Decimal
    resgates_native: Decimal
    aportes_brl: Decimal
    resgates_brl: Decimal
    proventos_native: Decimal
    proventos_brl: Decimal
    return_pct: Decimal | None
    return_brl_pct: Decimal | None
    return_null_reason: NullReason | None


@dataclass
class PerformanceSummary:
    as_of: date | None
    return_12m_pct: Decimal | None
    return_12m_brl_pct: Decimal | None
    return_ytd_pct: Decimal | None
    return_ytd_brl_pct: Decimal | None
    since_inception_pct: Decimal | None
    since_inception_brl_pct: Decimal | None
    months_in_12m: int
    months_in_ytd: int
    proventos_12m_native: Decimal
    proventos_12m_brl: Decimal


@dataclass
class AssetPerformance:
    asset_id: str
    currency: str
    is_value_mode: bool
    rows: list[PerformanceRow] = field(default_factory=list)  # ASC
    summary: PerformanceSummary = field(default_factory=lambda: PerformanceSummary(
        as_of=None, return_12m_pct=None, return_12m_brl_pct=None,
        return_ytd_pct=None, return_ytd_brl_pct=None,
        since_inception_pct=None, since_inception_brl_pct=None,
        months_in_12m=0, months_in_ytd=0,
        proventos_12m_native=_ZERO, proventos_12m_brl=_ZERO,
    ))


# ── Pure helpers ───────────────────────────────────────────────────────────


def _ccy(value: object) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _effective_fx(currency: object, fx_rate: Decimal | None) -> Decimal:
    """Spec 56 — fx_rate só multiplica quando a linha é USD. Linhas BRL
    guardam fx_rate pra exibição, mas BRL→BRL é sempre 1."""
    if _ccy(currency) == Currency.USD.value:
        return fx_rate or Decimal("1")
    return Decimal("1")


def cash_flows_in_window(
    movements: Iterable[AssetMovement],
    start: date | None,
    end: date,
    *,
    in_brl: bool,
) -> tuple[Decimal, Decimal]:
    """(aportes, resgates) dos movimentos ativos com event_date ∈ (start, end].
    `start=None` significa sem limite inferior."""
    aportes = _ZERO
    resgates = _ZERO
    for m in movements:
        if not m.is_active or m.net_amount is None:
            continue
        if start is not None and m.event_date <= start:
            continue
        if m.event_date > end:
            continue
        amt = Decimal(m.net_amount)
        if in_brl:
            amt *= _effective_fx(m.currency, m.fx_rate)
        if m.type in APORTE_TYPES:
            aportes += amt
        elif m.type in RESGATE_TYPES:
            resgates += amt
    return aportes, resgates


def proventos_in_window(
    rows: Iterable[ProventoRow], start: date | None, end: date,
) -> tuple[Decimal, Decimal]:
    """(nativo, BRL) dos proventos com event_date ∈ (start, end]."""
    native = _ZERO
    brl = _ZERO
    for r in rows:
        if start is not None and r.event_date <= start:
            continue
        if r.event_date > end:
            continue
        net = Decimal(r.net_amount)
        native += net
        brl += net * _effective_fx(r.currency, r.fx_rate)
    return native, brl


def monthly_return(
    mv_start: Decimal, mv_end: Decimal,
    aportes: Decimal, resgates: Decimal, proventos: Decimal,
) -> Decimal:
    return (mv_end - mv_start - aportes + resgates + proventos) / mv_start


def chain_link(returns: Iterable[Decimal | None]) -> Decimal | None:
    """Π(1+r) − 1. None se a lista é vazia ou tem algum None (mês sem
    retorno confiável invalida o acumulado)."""
    acc = Decimal("1")
    seen = False
    for r in returns:
        if r is None:
            return None
        acc *= Decimal("1") + r
        seen = True
    return acc - Decimal("1") if seen else None


def _minus_months(d: date, months: int) -> date:
    y, m = d.year, d.month - months
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def _resolve_mv_native(
    item: PortfolioSnapshotItem, asset_currency: str, fx: Decimal | None,
) -> Decimal | None:
    if item.market_value_native is not None:
        return Decimal(item.market_value_native)
    if item.market_value_brl is None:
        return None
    if asset_currency == Currency.BRL.value:
        return Decimal(item.market_value_brl)
    if fx and fx > 0:
        return Decimal(item.market_value_brl) / fx
    return None


# ── Main ───────────────────────────────────────────────────────────────────


def compute_asset_performance(db: Session, asset_id: str) -> AssetPerformance:
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise ValueError(f"asset {asset_id} not found")
    currency = asset.currency.value
    is_option = asset.asset_class == AssetClass.OPTION
    result = AssetPerformance(
        asset_id=asset.id, currency=currency,
        is_value_mode=asset.asset_class not in _COTADO_CLASSES,
    )

    snapshots: list[PortfolioSnapshot] = (
        db.query(PortfolioSnapshot)
        .filter(
            PortfolioSnapshot.workspace_id == asset.workspace_id,
            PortfolioSnapshot.status == SnapshotStatus.CLOSED,
            PortfolioSnapshot.is_active.is_(True),
        )
        .order_by(PortfolioSnapshot.period_end_date.asc())
        .all()
    )
    if not snapshots:
        return result

    items_by_snap: dict[str, PortfolioSnapshotItem] = {
        it.snapshot_id: it
        for it in db.query(PortfolioSnapshotItem).filter(
            PortfolioSnapshotItem.asset_id == asset.id,
            PortfolioSnapshotItem.snapshot_id.in_([s.id for s in snapshots]),
        ).all()
    }
    if not items_by_snap:
        return result

    movements = (
        db.query(AssetMovement)
        .filter(
            AssetMovement.asset_id == asset.id,
            AssetMovement.is_active.is_(True),
        )
        .all()
    )
    proventos = [
        r for r in list_proventos(db, asset.workspace_id, include_synthetic=True)
        if r.asset_id == asset.id
    ]

    rows: list[PerformanceRow] = []
    seen_any = False
    prev_snap: PortfolioSnapshot | None = None
    for snap in snapshots:
        item = items_by_snap.get(snap.id)
        if item is None:
            prev_snap = snap
            continue
        period_end = snap.period_end_date
        fx = Decimal(snap.fx_rate_usd_brl) if snap.fx_rate_usd_brl is not None else None
        window_start = (
            prev_snap.period_end_date if prev_snap is not None
            else period_end.replace(day=1) - timedelta(days=1)
        )

        ap_n, rs_n = cash_flows_in_window(movements, window_start, period_end, in_brl=False)
        ap_b, rs_b = cash_flows_in_window(movements, window_start, period_end, in_brl=True)
        pv_n, pv_b = proventos_in_window(proventos, window_start, period_end)

        mv_end_native = _resolve_mv_native(item, currency, fx)
        mv_end_brl = Decimal(item.market_value_brl) if item.market_value_brl is not None else None
        invested = Decimal(item.total_invested_brl) if item.total_invested_brl is not None else None
        pnl_brl = pnl_pct = None
        if mv_end_brl is not None and invested is not None:
            pnl_brl = mv_end_brl - invested
            if invested > 0:
                pnl_pct = pnl_brl / invested

        prev_item = items_by_snap.get(prev_snap.id) if prev_snap is not None else None
        ret_native: Decimal | None = None
        ret_brl: Decimal | None = None
        reason: NullReason | None = None
        if is_option:
            reason = "OPTION"
        elif not seen_any:
            reason = "FIRST_CLOSING"
        elif prev_item is None:
            reason = "GAP"
        else:
            prev_fx = (
                Decimal(prev_snap.fx_rate_usd_brl)
                if prev_snap is not None and prev_snap.fx_rate_usd_brl is not None else None
            )
            mv_start_native = _resolve_mv_native(prev_item, currency, prev_fx)
            if mv_start_native is None or mv_end_native is None:
                reason = "MISSING_MV"
            elif mv_start_native <= 0:
                reason = "ZERO_START"
            else:
                ret_native = monthly_return(mv_start_native, mv_end_native, ap_n, rs_n, pv_n)
            mv_start_brl = (
                Decimal(prev_item.market_value_brl)
                if prev_item.market_value_brl is not None else None
            )
            if (
                reason is None and mv_start_brl is not None
                and mv_end_brl is not None and mv_start_brl > 0
            ):
                ret_brl = monthly_return(mv_start_brl, mv_end_brl, ap_b, rs_b, pv_b)

        rows.append(PerformanceRow(
            period_end_date=period_end,
            snapshot_id=snap.id,
            quantity=Decimal(item.quantity) if item.quantity is not None else _ZERO,
            unit_price=Decimal(item.unit_price) if item.unit_price is not None else None,
            market_value_native=mv_end_native,
            market_value_brl=mv_end_brl,
            market_value_usd=(
                Decimal(item.market_value_usd) if item.market_value_usd is not None else None
            ),
            total_invested_brl=invested,
            fx_rate_usd_brl=fx,
            pnl_brl=pnl_brl,
            pnl_pct=pnl_pct,
            aportes_native=ap_n, resgates_native=rs_n,
            aportes_brl=ap_b, resgates_brl=rs_b,
            proventos_native=pv_n, proventos_brl=pv_b,
            return_pct=ret_native,
            return_brl_pct=ret_brl,
            return_null_reason=reason,
        ))
        seen_any = True
        prev_snap = snap

    result.rows = rows
    result.summary = _summarize(rows)
    return result


def _summarize(rows: list[PerformanceRow]) -> PerformanceSummary:
    if not rows:
        return AssetPerformance("", "", False).summary
    as_of = rows[-1].period_end_date
    cutoff_12m = _minus_months(as_of, 12)
    win_12m = [r for r in rows if r.period_end_date > cutoff_12m]
    win_ytd = [r for r in rows if r.period_end_date.year == as_of.year]
    # Desde o início: pula a primeira aparição (FIRST_CLOSING é null por
    # construção); qualquer outro null invalida o acumulado.
    after_first = rows[1:]

    def _chain(win: list[PerformanceRow], attr: str) -> Decimal | None:
        return chain_link(getattr(r, attr) for r in win)

    return PerformanceSummary(
        as_of=as_of,
        return_12m_pct=_chain(win_12m, "return_pct") if len(win_12m) == 12 else None,
        return_12m_brl_pct=_chain(win_12m, "return_brl_pct") if len(win_12m) == 12 else None,
        return_ytd_pct=_chain(win_ytd, "return_pct"),
        return_ytd_brl_pct=_chain(win_ytd, "return_brl_pct"),
        since_inception_pct=_chain(after_first, "return_pct"),
        since_inception_brl_pct=_chain(after_first, "return_brl_pct"),
        months_in_12m=len(win_12m),
        months_in_ytd=len(win_ytd),
        proventos_12m_native=sum((r.proventos_native for r in win_12m), _ZERO),
        proventos_12m_brl=sum((r.proventos_brl for r in win_12m), _ZERO),
    )
