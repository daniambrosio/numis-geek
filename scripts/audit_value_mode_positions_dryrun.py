"""Spec 64 dry-run — impacto do fix de semantics value-mode em compute_position.

Roda `compute_position` para todo asset ativo do workspace em cada
period_end_date de snapshot (e "hoje"), e reporta:

- has_position / total_invested_brl / quantity_held por (asset, período)
- se o asset está ou não presente como item no snapshot daquele período

O script NÃO modifica nada. Rode uma vez ANTES do fix (--out before.json)
e uma vez DEPOIS (--out after.json), e compare com --diff.

Uso:
    python scripts/audit_value_mode_positions_dryrun.py --db <path> --out before.json
    python scripts/audit_value_mode_positions_dryrun.py --diff before.json after.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


def _d(v) -> str | None:
    return None if v is None else str(Decimal(v))


def run(db_path: str, out_path: str) -> None:
    os.environ["DATABASE_URL"] = f"sqlite:///{os.path.abspath(db_path)}"
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from numis_geek.models import Asset, PortfolioSnapshot, PortfolioSnapshotItem
    from numis_geek.services.positions import asset_has_position, compute_position

    engine = create_engine(os.environ["DATABASE_URL"])
    db = sessionmaker(bind=engine)()

    snaps = (
        db.query(PortfolioSnapshot)
        .filter(PortfolioSnapshot.is_active == True)  # noqa: E712
        .order_by(PortfolioSnapshot.period_end_date.asc())
        .all()
    )
    assets = (
        db.query(Asset)
        .filter(Asset.is_active == True)  # noqa: E712
        .all()
    )

    rows = []
    for snap in snaps:
        item_by_asset = {
            it.asset_id: it
            for it in db.query(PortfolioSnapshotItem)
            .filter(PortfolioSnapshotItem.snapshot_id == snap.id)
            .all()
        }
        for asset in assets:
            if asset.workspace_id != snap.workspace_id:
                continue
            pos = compute_position(db, asset.id, as_of=snap.period_end_date)
            item = item_by_asset.get(asset.id)
            rows.append({
                "period": snap.period_end_date.isoformat(),
                "snapshot_status": snap.status.value if hasattr(snap.status, "value") else str(snap.status),
                "asset_id": asset.id,
                "asset_name": asset.name,
                "asset_class": asset.asset_class.value if asset.asset_class else None,
                "has_position": asset_has_position(pos, asset),
                "quantity_held": _d(pos["quantity_held"]),
                "total_invested_brl": _d(pos["total_invested_brl"]),
                "item_present": item is not None,
                "item_mv_brl": _d(item.market_value_brl) if item else None,
                "item_invested_brl": _d(item.total_invested_brl) if item else None,
            })

    with open(out_path, "w") as fh:
        json.dump(rows, fh, indent=1)
    print(f"{len(rows)} linhas → {out_path}")


def diff(before_path: str, after_path: str, tolerance: str = "0.05") -> None:
    before = {(r["period"], r["asset_id"]): r for r in json.load(open(before_path))}
    after = {(r["period"], r["asset_id"]): r for r in json.load(open(after_path))}

    changed = []
    for key, a in after.items():
        b = before.get(key)
        if b is None:
            continue
        inv_b = Decimal(b["total_invested_brl"] or "0")
        inv_a = Decimal(a["total_invested_brl"] or "0")
        # Diferenças de centavo são ruído: em modo valor o invested passa a
        # vir de `gross_amount` (NUMERIC 18,2) em vez de qty × unit_price
        # (NUMERIC 18,8). Só interessa mudança de presença ou de valor real.
        if (
            b["has_position"] != a["has_position"]
            or abs(inv_a - inv_b) > Decimal(tolerance)
        ):
            changed.append((b, a))

    if not changed:
        print("Nenhuma diferença.")
        return

    # Agrupado por asset
    by_asset: dict[str, list] = {}
    for b, a in changed:
        by_asset.setdefault(a["asset_id"], []).append((b, a))

    print(f"{len(changed)} (asset, período) mudaram · {len(by_asset)} assets\n")
    for asset_id, pairs in sorted(by_asset.items(), key=lambda kv: kv[1][0][1]["asset_name"]):
        a0 = pairs[0][1]
        print(f"── {a0['asset_name']}  [{a0['asset_class']}]  {asset_id}")
        for b, a in pairs:
            flag = ""
            if not b["has_position"] and a["has_position"]:
                flag = "  ⟵ VOLTA A APARECER" + ("" if a["item_present"] else " (item AUSENTE hoje)")
            print(
                f"   {a['period']} [{a['snapshot_status']:9}] "
                f"invested {b['total_invested_brl']} → {a['total_invested_brl']} · "
                f"has_pos {b['has_position']}→{a['has_position']} · "
                f"item_present={a['item_present']}{flag}"
            )
        print()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db")
    ap.add_argument("--out")
    ap.add_argument("--diff", nargs=2, metavar=("BEFORE", "AFTER"))
    ap.add_argument("--tolerance", default="0.05")
    args = ap.parse_args()
    if args.diff:
        diff(*args.diff, tolerance=args.tolerance)
    else:
        run(args.db, args.out)


if __name__ == "__main__":
    main()
