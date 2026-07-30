"""Histórico de preço por ativo + walkback até dia útil anterior.

Duas funções públicas coexistem aqui:

- :func:`fetch_price_on` — original (spec 17). Retorna :class:`HistoricalPrice`
  usando a hierarquia current_price → BRAPI → PortfolioSnapshotItem. Semântica
  own do auto-settle de opções: **lança** ``HistoricalPriceNotFound`` quando
  nenhuma fonte resolve.

- :func:`fetch_on` — spec 53 wire-in. Retorna apenas ``Decimal | None`` e faz
  fallback chain por ``price_source`` (BRAPI/FINNHUB/COINBASE/TESOURO/MANUAL)
  com walkback de até 3 dias úteis pra trás. Emite audit ``price.fetch_historical``
  no sucesso. Usada pelo pipeline de snapshot/pendency retry pra buscar preço
  histórico direto dos providers, sem depender de snapshot pré-existente.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Callable

from sqlalchemy.orm import Session

from numis_geek.integrations.brapi import (
    BrapiError,
    fetch_close_on as brapi_close_on,
    fetch_history as brapi_history,
)
from numis_geek.integrations.coinbase import (
    CoinbaseError,
    fetch_close_on as coinbase_close_on,
)
from numis_geek.integrations.finnhub import (
    FinnhubError,
    fetch_close_on as finnhub_close_on,
)
from numis_geek.integrations.tesouro import (
    TesouroError,
    fetch_close_on as tesouro_close_on,
)
from numis_geek.integrations.yfinance import (
    YFinanceError,
    fetch_close_on as yfinance_close_on,
)
from numis_geek.models.asset import Asset, PriceSource
from numis_geek.models.integration_credential import (
    IntegrationCredential, IntegrationProvider,
)
from numis_geek.models.portfolio_snapshot import (
    PortfolioSnapshot, PortfolioSnapshotItem,
)
from numis_geek.services.audit import AuditService
from numis_geek.utils.business_day import is_business_day


class HistoricalPriceNotFound(RuntimeError):
    pass


@dataclass(frozen=True)
class HistoricalPrice:
    price: Decimal
    source: str           # 'brapi' | 'snapshot' | 'current_price'
    effective_date: date  # data efetiva do preço (pode ser anterior à pedida via walkback)


def _get_token(db: Session, provider: IntegrationProvider) -> str | None:
    """System-wide credential lookup (workspace_id IS NULL, is_active=True)."""
    cred = (
        db.query(IntegrationCredential)
        .filter(
            IntegrationCredential.workspace_id.is_(None),
            IntegrationCredential.provider == provider,
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
    token = _get_token(db, IntegrationProvider.BRAPI)
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


# ─────────────────────────────────────────────────────────────────────────────
# Spec 53 wire-in: fetch_on() — chain por price_source + walkback 3 dias úteis
# ─────────────────────────────────────────────────────────────────────────────

_WALKBACK_BUSINESS_DAYS = 3


def _walkback_candidates(target: date) -> list[date]:
    """target_date + até 3 dias úteis anteriores (4 candidatos no total).

    Não filtra target por is_business_day — providers cuidam disso; se target
    é fim-de-semana/feriado, retornam None e caímos no próximo candidato.
    """
    candidates: list[date] = [target]
    cursor = target
    for _ in range(_WALKBACK_BUSINESS_DAYS):
        cursor = cursor - timedelta(days=1)
        while not is_business_day(cursor):
            cursor = cursor - timedelta(days=1)
        candidates.append(cursor)
    return candidates


def _try_provider(
    provider_label: str,
    call: Callable[[date], Decimal | None],
    candidates: list[date],
) -> tuple[Decimal, date, str] | None:
    """Itera por candidates; devolve (price, effective_date, provider) no primeiro hit.

    Erros do provider (BrapiError, FinnhubError, etc.) são tratados como
    "sem dado nesta data" — logamos silenciosamente e seguimos pra próxima
    candidate. Se toda a lista falhar, devolvemos None e o caller move pro
    próximo provider da chain.
    """
    for candidate in candidates:
        try:
            price = call(candidate)
        except (
            BrapiError,
            FinnhubError,
            CoinbaseError,
            YFinanceError,
            TesouroError,
        ):
            price = None
        if price is not None:
            return price, candidate, provider_label
    return None


def _chain_for(
    db: Session, asset: Asset,
) -> list[tuple[str, Callable[[date], Decimal | None]]]:
    """Monta a lista [(label, call)] pra tentar em ordem, respeitando price_source.

    Providers sem credencial são pulados silenciosamente (o próximo da chain
    ainda pode responder). MANUAL retorna chain vazia — sem provider automático.
    """
    src = asset.price_source
    ticker = asset.ticker

    if src == PriceSource.MANUAL or src is None:
        return []

    chain: list[tuple[str, Callable[[date], Decimal | None]]] = []

    if src == PriceSource.BRAPI:
        if ticker:
            token = _get_token(db, IntegrationProvider.BRAPI)
            if token:
                chain.append(("brapi", lambda d, t=ticker, tk=token: brapi_close_on(t, tk, d)))
            chain.append(("yfinance", lambda d, t=ticker: yfinance_close_on(t, d)))

    elif src == PriceSource.FINNHUB:
        if ticker:
            token = _get_token(db, IntegrationProvider.FINNHUB)
            if token:
                chain.append(("finnhub", lambda d, t=ticker, tk=token: finnhub_close_on(t, tk, d)))
            chain.append(("yfinance", lambda d, t=ticker: yfinance_close_on(t, d)))

    elif src == PriceSource.COINBASE:
        if ticker:
            chain.append(("coinbase", lambda d, t=ticker: coinbase_close_on(t, d, "USD")))
            yf_symbol = f"{ticker}-USD"
            chain.append(("yfinance", lambda d, s=yf_symbol: yfinance_close_on(s, d)))

    elif src == PriceSource.TESOURO:
        # brapi cobre alguns títulos públicos por ticker; se nada, cai no CSV
        # oficial do Tesouro (matching por nome), e último recurso yfinance.
        if ticker:
            token = _get_token(db, IntegrationProvider.BRAPI)
            if token:
                chain.append(("brapi", lambda d, t=ticker, tk=token: brapi_close_on(t, tk, d)))
        if asset.name:
            chain.append(
                ("tesouro", lambda d, n=asset.name: tesouro_close_on(n, d))
            )
        if ticker:
            chain.append(("yfinance", lambda d, t=ticker: yfinance_close_on(t, d)))

    return chain


def fetch_on(
    db: Session, asset: Asset, target_date: date,
) -> Decimal | None:
    """Preço de fechamento pro ``asset`` em ``target_date`` (spec 53).

    Percorre a chain determinada por ``asset.price_source`` (ver
    ``_chain_for``) e, pra cada provider, tenta ``target_date`` e depois
    até 3 dias úteis anteriores. Retorna o primeiro preço não-None.

    Retorna ``None`` quando:
      * ``price_source`` é MANUAL/None (sem provider automático);
      * nenhum provider da chain devolveu preço em nenhuma das 4 datas.

    No sucesso, grava audit ``price.fetch_historical`` com detalhes do
    provider vencedor e a data efetiva (que pode ser anterior a
    ``target_date`` se caiu em walkback).
    """
    chain = _chain_for(db, asset)
    if not chain:
        return None

    candidates = _walkback_candidates(target_date)

    for provider_label, call in chain:
        result = _try_provider(provider_label, call, candidates)
        if result is None:
            continue
        price, effective_date, provider = result
        AuditService(db).log(
            user_email="system@historical_price",
            action="price.fetch_historical",
            workspace_id=asset.workspace_id,
            resource_type="asset",
            resource_id=asset.id,
            details={
                "provider": provider,
                "target_date": target_date.isoformat(),
                "effective_date": effective_date.isoformat(),
                "price": str(price),
                "ticker": asset.ticker,
                "price_source": asset.price_source.value if asset.price_source else None,
            },
        )
        return price

    return None
