"""Spec 56 — Backfill total_invested_brl e average_cost_brl em PortfolioSnapshotItem.

Antes do fix (commit X), `compute_position` multiplicava cost-basis por
fx_rate independente da moeda do movement. Movements BRL com PTAX
auto-fillado (~508 rows na prod) viraram total_invested_brl 5x maior
do que o real. Esse erro foi gravado em todos os PortfolioSnapshotItem
criados desde então (frozen).

Esse script:
  1. Itera todos os PortfolioSnapshotItem ativos.
  2. Roda compute_position com a versão corrigida pra cada
     (asset_id, snapshot.period_end_date).
  3. Atualiza `total_invested_brl` e `average_cost_brl` quando diferentes.
  4. NÃO toca em quantity, market_value_*, unit_price (preço é frozen
     por Spec 52).
  5. Em dry-run (default), imprime relatório de mudanças.
  6. Em --apply, escreve no DB.

CLI:
    uv run python scripts/backfill_spec56_snapshot_invested.py            # dry-run
    uv run python scripts/backfill_spec56_snapshot_invested.py --apply    # commit
"""
from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from typing import Iterable

from sqlalchemy.orm import Session

from numis_geek.db.session import SessionLocal
from numis_geek.models.asset import Asset
from numis_geek.models.portfolio_snapshot import (
    PortfolioSnapshot,
    PortfolioSnapshotItem,
)
from numis_geek.services.positions import compute_position


TOLERANCE = Decimal("0.01")


def _fmt(d: Decimal | None) -> str:
    if d is None:
        return "—"
    return f"{float(d):,.2f}"


def iterate_changes(db: Session) -> Iterable[tuple[PortfolioSnapshotItem, dict]]:
    """Yield (item, diff_dict) for every snapshot item whose recompute
    differs from stored. diff_dict contains keys 'old'/'new' for each
    changed column."""
    items = (
        db.query(PortfolioSnapshotItem)
        .join(PortfolioSnapshot, PortfolioSnapshot.id == PortfolioSnapshotItem.snapshot_id)
        .order_by(PortfolioSnapshot.period_end_date, PortfolioSnapshotItem.asset_id)
        .all()
    )
    for it in items:
        snap = db.get(PortfolioSnapshot, it.snapshot_id)
        if snap is None:
            continue
        pos = compute_position(db, it.asset_id, as_of=snap.period_end_date)
        new_invested = pos.get("total_invested_brl") or Decimal("0")
        new_avg_brl = pos.get("average_cost_brl") or Decimal("0")
        old_invested = it.total_invested_brl or Decimal("0")
        old_avg_brl = it.average_cost_brl or Decimal("0")

        diff: dict = {}
        if abs(Decimal(new_invested) - Decimal(old_invested)) > TOLERANCE:
            diff["total_invested_brl"] = {"old": old_invested, "new": Decimal(new_invested)}
        if abs(Decimal(new_avg_brl) - Decimal(old_avg_brl)) > TOLERANCE:
            diff["average_cost_brl"] = {"old": old_avg_brl, "new": Decimal(new_avg_brl)}
        if diff:
            yield it, diff


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write changes (default: dry-run)")
    parser.add_argument("--limit", type=int, default=None, help="Limit rows displayed")
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        changes = list(iterate_changes(db))
        if not changes:
            print("Nenhum item desincronizado — DB já refletindo regra do Spec 56.")
            return 0

        # Por snapshot, contagens
        by_snap: dict[str, list] = {}
        for it, diff in changes:
            by_snap.setdefault(it.snapshot_id, []).append((it, diff))

        print(f"Total de items com diff: {len(changes)} em {len(by_snap)} snapshots")
        print()

        shown = 0
        for snap_id, rows in by_snap.items():
            snap = db.get(PortfolioSnapshot, snap_id)
            print(f"─ {snap.period_end_date} ({snap.status.value}) — {len(rows)} items")
            for it, diff in rows[:5]:
                asset = db.get(Asset, it.asset_id)
                changes_str = []
                if "total_invested_brl" in diff:
                    changes_str.append(
                        f"invested R$ {_fmt(diff['total_invested_brl']['old'])} → "
                        f"R$ {_fmt(diff['total_invested_brl']['new'])}"
                    )
                if "average_cost_brl" in diff:
                    changes_str.append(
                        f"avg_brl R$ {_fmt(diff['average_cost_brl']['old'])} → "
                        f"R$ {_fmt(diff['average_cost_brl']['new'])}"
                    )
                name = asset.name if asset else it.asset_id
                print(f"    · {name[:50]:<50} | {' | '.join(changes_str)}")
                shown += 1
                if args.limit and shown >= args.limit:
                    break
            if len(rows) > 5:
                print(f"    ... (+{len(rows) - 5} ativos)")
            if args.limit and shown >= args.limit:
                print(f"\n[--limit {args.limit} atingido]")
                break

        if not args.apply:
            print()
            print("Dry-run. Pra escrever no DB rode com --apply.")
            return 0

        # APPLY
        print()
        print("Aplicando mudanças…")
        for it, diff in changes:
            if "total_invested_brl" in diff:
                it.total_invested_brl = diff["total_invested_brl"]["new"]
            if "average_cost_brl" in diff:
                it.average_cost_brl = diff["average_cost_brl"]["new"]
        db.commit()
        print(f"OK. {len(changes)} items atualizados.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
