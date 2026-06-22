"""Histórico de preço por ativo + walkback até dia útil anterior.

Usado pelo auto-settlement de opções pra pegar o preço do underlying na
data exata de vencimento (não o "hoje"). Estratégia de fontes:

1. BRAPI history (assets BR com price_source=BRAPI)
2. PortfolioSnapshotItem na expiration_date (fallback universal)
3. Asset.current_price se price_updated_at coincide com a data alvo
   (degrade gracioso pra ativos sem provider histórico)

Walkback: se a data exata não tem fechamento (feriado/weekend), volta
até `max_walkback_days` dias úteis pro último fechamento disponível.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from numis_geek.integrations.brapi import BrapiError, fetch_history as brapi_history
from numis_geek.models.asset import Asset, PriceSource
from numis_geek.models.integration_credential import (
    IntegrationCredential, IntegrationProvider,
)
from numis_geek.models.portfolio_snapshot import (
    PortfolioSnapshot, PortfolioSnapshotItem,
)


class HistoricalPriceNotFound(RuntimeError):
    pass


@dataclass(frozen=True)
class HistoricalPrice:
    price: Decimal
    source: str           # 'brapi' | 'snapshot' | 'current_price'
    effective_date: date  # data efetiva do preço (pode ser anterior à pedida via walkback)


def _brapi_token(db: Session) -> str | None:
    cred = (
        db.query(IntegrationCredential)
        .filter(
            IntegrationCredential.provider == IntegrationProvider.BRAPI,
            IntegrationCredential.is_active.is_(True),
        )
        .first()
    )
    return cred.secret_value if cred else None


def _try_brapi(
    db: Session, asset: Asset, target: date, *, max_walkback_days: int,
) -> HistoricalPrice | None:
    if asset.price_source != PriceSource.BRAPI or not asset.ticker:
        return None
    token = _brapi_token(db)
    if not token:
        return None
    try:
        # Janela de 3 meses cobre walkback amplo sem custo extra na API.
        points = brapi_history(asset.ticker, token, range_="3mo", interval="1d")
    except BrapiError:
        return None
    if not points:
        return None
    # by_date pra lookup direto + walkback
    by_date = {p.date: p.close for p in points}
    cutoff = target - timedelta(days=max_walkback_days)
    cursor = target
    while cursor >= cutoff:
        if cursor in by_date:
            return HistoricalPrice(
                price=by_date[cursor], source="brapi", effective_date=cursor,
            )
        cursor -= timedelta(days=1)
    return None


def _try_snapshot(
    db: Session, asset: Asset, target: date,
) -> HistoricalPrice | None:
    """Procura PortfolioSnapshotItem com period_end_date == target."""
    row = (
        db.query(PortfolioSnapshotItem.unit_price, PortfolioSnapshot.period_end_date)
        .join(
            PortfolioSnapshot,
            PortfolioSnapshot.id == PortfolioSnapshotItem.snapshot_id,
        )
        .filter(
            PortfolioSnapshotItem.asset_id == asset.id,
            PortfolioSnapshotItem.unit_price.isnot(None),
            PortfolioSnapshot.period_end_date == target,
            PortfolioSnapshot.workspace_id == asset.workspace_id,
        )
        .first()
    )
    if row is None:
        return None
    return HistoricalPrice(
        price=row[0], source="snapshot", effective_date=row[1],
    )


def _try_current_price(
    asset: Asset, target: date,
) -> HistoricalPrice | None:
    """Aceita current_price só se price_updated_at é do mesmo dia (UTC).

    Útil pro caso normal: opção vence hoje, price_refresh às 18h SP
    atualizou current_price pro fechamento de hoje, auto-settle às 18h05
    usa esse mesmo preço.
    """
    if asset.current_price is None or asset.price_updated_at is None:
        return None
    if asset.price_updated_at.date() != target:
        return None
    return HistoricalPrice(
        price=asset.current_price,
        source="current_price",
        effective_date=target,
    )


def fetch_price_on(
    db: Session,
    asset: Asset,
    target_date: date,
    *,
    max_walkback_days: int = 5,
) -> HistoricalPrice:
    """Preço do `asset` na `target_date`, com walkback até dia útil anterior.

    Estratégia (primeira fonte que devolver venceu):
      1. current_price (se price_updated_at == target_date)
      2. BRAPI history (se price_source=BRAPI)
      3. PortfolioSnapshotItem com period_end_date=target_date

    Walkback aplica em BRAPI history (volta dia a dia até achar fechamento).
    Snapshot/current_price não tem walkback (só ALL-OR-NOTHING no dia exato).

    Lança HistoricalPriceNotFound quando nenhuma fonte resolveu.
    """
    for fn in (
        lambda: _try_current_price(asset, target_date),
        lambda: _try_brapi(db, asset, target_date, max_walkback_days=max_walkback_days),
        lambda: _try_snapshot(db, asset, target_date),
    ):
        hp = fn()
        if hp is not None:
            return hp
    raise HistoricalPriceNotFound(
        f"sem preço disponível para {asset.ticker or asset.id} em {target_date}"
    )
