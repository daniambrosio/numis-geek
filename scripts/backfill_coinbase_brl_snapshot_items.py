"""One-off datafix: re-fetch preços Coinbase-BRL de snapshot items IN_REVIEW.

Bug (2026-08-01): historical_price.fetch_on e price_update.refresh_one
gravavam preço em USD direto como se fosse BRL para assets Coinbase com
currency=BRL, causando -79% a -80% de "variação anômala" no fechamento
Jul/26 (visto em BTC e USDC).

Ambos os call-paths foram corrigidos pra multiplicar por PTAX quando
asset.currency=BRL. Este script re-executa fetch_on() nos itens já
gravados errado, atualizando unit_price / mv_native / mv_brl / mv_usd
+ totals do snapshot.

Escopo:
- Assets com price_source=COINBASE E currency=BRL
- Snapshots IN_REVIEW ou explicitamente listados via --snapshot-id
- Um asset por linha reportado com antes/depois

Segurança:
- DRY-RUN por default. --apply escreve.
- Se fetch_on() volta None, pula (registra warning; provavelmente PTAX
  ausente na janela).
- Não abre snapshot CLOSED (retry_pendency_api tem essa lógica; aqui
  restringimos a IN_REVIEW).

Uso:
    uv run python scripts/backfill_coinbase_brl_snapshot_items.py --period 2026-07
    uv run python scripts/backfill_coinbase_brl_snapshot_items.py --period 2026-07 --apply
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import and_

from numis_geek.db.session import SessionLocal
from numis_geek.models.account import Currency
from numis_geek.models.asset import Asset, PriceSource
from numis_geek.models.portfolio_snapshot import (
    PortfolioSnapshot,
    PortfolioSnapshotItem,
    SnapshotStatus,
)
from numis_geek.services.historical_price import fetch_on
from numis_geek.services.snapshot import detect_suspicious_deltas


def _parse_period(s: str) -> tuple[date, date]:
    """'2026-07' -> (2026-07-01, 2026-07-31)."""
    y, m = s.split("-")
    y_i, m_i = int(y), int(m)
    start = date(y_i, m_i, 1)
    if m_i == 12:
        end = date(y_i, 12, 31)
    else:
        end = date(y_i, m_i + 1, 1) - timedelta(days=1)
    return start, end


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--period", required=True,
        help="Período YYYY-MM (ex: 2026-07). Casa qualquer snapshot com "
             "period_end_date dentro do mês.",
    )
    parser.add_argument("--apply", action="store_true",
                        help="Escreve no DB (default: dry-run)")
    parser.add_argument(
        "--include-closed", action="store_true",
        help="Também toca em snapshots CLOSED (default: só IN_REVIEW/DRAFT)",
    )
    args = parser.parse_args()

    period_start, period_end = _parse_period(args.period)
    db = SessionLocal()
    changed = 0
    skipped = 0
    try:
        snap_q = db.query(PortfolioSnapshot).filter(
            and_(
                PortfolioSnapshot.period_end_date >= period_start,
                PortfolioSnapshot.period_end_date <= period_end,
            )
        )
        if not args.include_closed:
            snap_q = snap_q.filter(
                PortfolioSnapshot.status != SnapshotStatus.CLOSED
            )
        snapshots = snap_q.all()
        if not snapshots:
            print(f"Nenhum snapshot em {args.period} (status match).")
            return 0

        for snap in snapshots:
            print(f"\n== Snapshot {snap.id} ({snap.period_end_date}) "
                  f"[{snap.status.value}] fx={snap.fx_rate_usd_brl} ==")
            items = (
                db.query(PortfolioSnapshotItem, Asset)
                .join(Asset, Asset.id == PortfolioSnapshotItem.asset_id)
                .filter(
                    PortfolioSnapshotItem.snapshot_id == snap.id,
                    Asset.price_source == PriceSource.COINBASE,
                    Asset.currency == Currency.BRL,
                )
                .all()
            )
            if not items:
                print("  (nenhum item Coinbase-BRL)")
                continue

            for item, asset in items:
                new_price = fetch_on(db, asset, snap.period_end_date)
                if new_price is None:
                    print(f"  [SKIP] {asset.ticker}: fetch_on retornou None "
                          "(PTAX ausente? provider off?)")
                    skipped += 1
                    continue
                old_unit = item.unit_price
                old_mv_brl = item.market_value_brl
                qty = item.quantity or Decimal("0")
                new_mv_native = qty * new_price
                new_mv_brl = new_mv_native  # asset é BRL
                new_mv_usd = None
                fx = snap.fx_rate_usd_brl
                if fx and fx > 0:
                    new_mv_usd = new_mv_brl / fx
                delta_pct = None
                if old_unit and old_unit > 0:
                    delta_pct = (new_price - old_unit) / old_unit * 100
                print(
                    f"  {asset.ticker}: unit_price "
                    f"{old_unit} -> {new_price} "
                    f"({delta_pct:+.2f}% delta) | mv_brl "
                    f"{old_mv_brl} -> {new_mv_brl}"
                )
                if args.apply:
                    item.unit_price = new_price
                    item.market_value_native = new_mv_native
                    item.market_value_brl = new_mv_brl
                    item.market_value_usd = new_mv_usd
                changed += 1

            if args.apply:
                # Recompute snapshot totals a partir dos items atualizados
                all_items = (
                    db.query(PortfolioSnapshotItem)
                    .filter(PortfolioSnapshotItem.snapshot_id == snap.id)
                    .all()
                )
                snap.total_value_brl = sum(
                    (i.market_value_brl or Decimal("0")) for i in all_items
                )
                snap.total_value_usd = sum(
                    (i.market_value_usd or Decimal("0")) for i in all_items
                )
                db.flush()
                # Re-avalia SUSPICIOUS_DELTA — pendencies que voltaram pra
                # dentro do threshold são resolvidas automaticamente pela
                # próxima chamada; detect_suspicious_deltas é idempotente.
                detect_suspicious_deltas(db, snap.id)

        if args.apply:
            db.commit()
            print(f"\n✅ Commit: {changed} item(s) atualizado(s), "
                  f"{skipped} pulado(s).")
        else:
            db.rollback()
            print(f"\n🔍 DRY-RUN: {changed} item(s) mudariam, "
                  f"{skipped} pulado(s). Passe --apply para gravar.")
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
