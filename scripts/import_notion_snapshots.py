"""Import Notion DB IG Lote Apuracao (headers) + DB IG Apuracao (items)
into local PortfolioSnapshot + PortfolioSnapshotItem.

Two-phase process:
1. Lote Apuracao (28 rows) → PortfolioSnapshot (header per month)
   - Data Apuração → period_end_date
   - Cambio Dolar/Real → fx_rate_usd_brl
   - Total Apurado R$/US$ no Lote (formula readonly) ignored on insert; used
     for the divergencias report.
2. Apuracao (2465 rows) → PortfolioSnapshotItem (1 per ativo×lote)
   - Lote Apuracao relation → parent snapshot
   - Ativo relation → asset_id
   - QP Preço Unit. Apurado MC → unit_price
   - AR Valor → market_value_native (cash, fixed_income)
   - QP Qtde (* Eventos) formula → not directly available, infer from
     positions service at as_of=period_end

Divergencias report:
   /data/divergencias_<ts>.csv with rows where Notion totals (from formulas
   already exposed via headers) differ from local-computed totals by >1%.

CLI:
    uv run python -m scripts.import_notion_snapshots          # dry-run
    uv run python -m scripts.import_notion_snapshots --apply
"""
from __future__ import annotations

import argparse
import csv
import sys
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy.orm import Session

from numis_geek.db.session import SessionLocal
from numis_geek.integrations.notion import NotionClient, NotionPage
from numis_geek.models.asset import Asset, AssetClass
from numis_geek.models.external import ExternalSource
from numis_geek.models.integration_credential import (
    IntegrationCredential, IntegrationProvider,
)
from numis_geek.models.notion_sync import NotionSyncStatus
from numis_geek.models.portfolio_snapshot import (
    PortfolioSnapshot, PortfolioSnapshotItem, SnapshotSource,
)
from numis_geek.models.workspace import Workspace
from numis_geek.services.positions import compute_position

DEFAULT_WORKSPACE_NAME = "Família Ambrosio"
REPO_ROOT = Path(__file__).resolve().parent.parent
DIVERGENCIAS_THRESHOLD = Decimal("0.01")  # 1%


def _get_token(db: Session) -> str:
    row = db.query(IntegrationCredential).filter(
        IntegrationCredential.provider == IntegrationProvider.NOTION,
        IntegrationCredential.key_name == "NOTION_TOKEN",
    ).first()
    return row.secret_value


def _get_db_id(db: Session, key: str) -> str:
    row = db.query(IntegrationCredential).filter(
        IntegrationCredential.provider == IntegrationProvider.NOTION,
        IntegrationCredential.key_name == key,
    ).first()
    return row.secret_value


def _extract_date(prop) -> date | None:
    if not prop or prop.get("type") != "date":
        return None
    d = prop.get("date")
    if not d or not d.get("start"):
        return None
    return date.fromisoformat(d["start"][:10])


def _extract_number(prop) -> Decimal | None:
    if not prop or prop.get("type") != "number":
        return None
    n = prop.get("number")
    return Decimal(str(n)) if n is not None else None


def _extract_formula_number(prop) -> Decimal | None:
    """Notion formula → number."""
    if not prop or prop.get("type") != "formula":
        return None
    f = prop.get("formula", {})
    if f.get("type") == "number":
        n = f.get("number")
        return Decimal(str(n)) if n is not None else None
    return None


def _extract_first_relation(prop) -> str | None:
    if not prop or prop.get("type") != "relation":
        return None
    rels = prop.get("relation") or []
    return rels[0]["id"] if rels else None


def _extract_rich_text(prop) -> str | None:
    if not prop or prop.get("type") != "rich_text":
        return None
    parts = prop.get("rich_text") or []
    return "".join(p.get("plain_text", "") for p in parts) or None


def _lookup_asset(db: Session, notion_page_id: str) -> Asset | None:
    nid = notion_page_id.replace("-", "")
    return db.query(Asset).filter(
        Asset.external_source == ExternalSource.NOTION,
        Asset.external_id.contains(nid),
    ).first()


def import_lotes(
    db: Session, ws_id: str, cli: NotionClient, db_id: str, apply: bool,
) -> dict:
    print("Fetching DB IG Lote Apuracao...", flush=True)
    pages = cli.query_all(db_id)
    print(f"  fetched {len(pages)} lotes", flush=True)

    inserted, updated, errors = 0, 0, []
    lote_map: dict[str, dict] = {}  # notion_page_id → {snapshot_id, period_end, notion_totals}

    for p in pages:
        props = p.properties
        period_end = _extract_date(props.get("Data Apuração"))
        if not period_end:
            errors.append(f"{p.id}: missing Data Apuração")
            continue
        fx = _extract_number(props.get("Cambio Dolar/Real"))
        notion_total_brl = _extract_formula_number(props.get("Total Apurado R$ no Lote"))
        notion_total_usd = _extract_formula_number(props.get("Total Apurado US$ no Lote"))

        existing = db.query(PortfolioSnapshot).filter(
            PortfolioSnapshot.external_source == ExternalSource.NOTION,
            PortfolioSnapshot.external_id == p.id,
        ).first()

        now = datetime.now(timezone.utc)
        last_edited = datetime.fromisoformat(p.last_edited_time.replace("Z", "+00:00"))

        if existing:
            existing.period_end_date = period_end
            existing.fx_rate_usd_brl = fx
            existing.updated_at = now
            existing.notion_remote_last_edited_at = last_edited
            existing.notion_sync_status = NotionSyncStatus.SYNCED
            snap_id = existing.id
            updated += 1
        else:
            snap_id = str(uuid.uuid4())
            db.add(PortfolioSnapshot(
                id=snap_id,
                workspace_id=ws_id,
                period_end_date=period_end,
                fx_rate_usd_brl=fx,
                total_value_brl=Decimal("0"),  # filled after items
                total_value_usd=Decimal("0"),
                total_invested_brl=Decimal("0"),
                total_received_brl=Decimal("0"),
                source=SnapshotSource.NOTION_BACKFILL,
                is_active=True,
                external_id=p.id,
                external_source=ExternalSource.NOTION,
                notion_remote_last_edited_at=last_edited,
                notion_sync_status=NotionSyncStatus.SYNCED,
                created_at=now,
                updated_at=now,
            ))
            inserted += 1
        lote_map[p.id] = {
            "snapshot_id": snap_id,
            "period_end": period_end,
            "notion_total_brl": notion_total_brl,
            "notion_total_usd": notion_total_usd,
        }

    if apply:
        db.flush()
    return {"inserted": inserted, "updated": updated, "errors": errors, "lote_map": lote_map}


def import_items(
    db: Session, ws_id: str, cli: NotionClient, db_id: str,
    lote_map: dict[str, dict], apply: bool,
) -> dict:
    print("Fetching DB IG Apuracao (this may take a few minutes)...", flush=True)
    pages = cli.query_all(db_id)
    print(f"  fetched {len(pages)} items", flush=True)

    inserted, updated, skipped_orphan, skipped_no_lote, errors = 0, 0, 0, 0, []
    asset_cache: dict[str, Asset] = {}
    # Aggregate per snapshot: sum(market_value) for divergencias
    local_totals_by_snap: dict[str, Decimal] = {}

    for p in pages:
        props = p.properties
        asset_notion = _extract_first_relation(props.get("Ativo"))
        lote_notion = _extract_first_relation(props.get("Lote Apuracao"))
        if not asset_notion:
            skipped_orphan += 1
            continue
        if not lote_notion or lote_notion not in lote_map:
            skipped_no_lote += 1
            continue
        if asset_notion in asset_cache:
            asset = asset_cache[asset_notion]
        else:
            asset = _lookup_asset(db, asset_notion)
            if asset:
                asset_cache[asset_notion] = asset
        if not asset:
            skipped_orphan += 1
            continue

        unit_price = _extract_number(props.get("QP Preço Unit. Apurado MC"))
        ar_valor = _extract_number(props.get("AR Valor"))
        lote = lote_map[lote_notion]
        snap_id = lote["snapshot_id"]
        period_end = lote["period_end"]

        # Quantity from local positions (event-aware via positions service).
        # compute_position returns dict with keys quantity_held / average_cost_brl /
        # total_invested_brl.
        try:
            pos = compute_position(db, asset.id, as_of=period_end)
            qty = pos["quantity_held"] or Decimal("0")
            avg_cost = pos.get("average_cost_brl")
            invested_brl = pos.get("total_invested_brl")
        except Exception as e:
            errors.append(f"{p.id}: compute_position failed: {e}")
            qty = Decimal("0")
            avg_cost = None
            invested_brl = None

        # Market value. Cotado (STOCK/REIT/ETF/FUND/CRYPTO) is qty × unit_price.
        # Não-cotado (FIXED_INCOME/PRIVATE_PENSION/CASH/FGTS/REAL_ESTATE/VEHICLE)
        # uses AR Valor or unit_price as the *direct* value (Notion stores the
        # total in QP Preço Unit. Apurado MC for non-quoted assets).
        COTADOS = {
            AssetClass.STOCK, AssetClass.REIT, AssetClass.ETF,
            AssetClass.FUND, AssetClass.CRYPTO,
        }
        mv_native = None
        if asset.asset_class in COTADOS:
            if unit_price is not None and qty:
                mv_native = qty * unit_price
        else:
            # Non-quoted: prefer AR Valor; fall back to unit_price (used as total)
            if ar_valor is not None:
                mv_native = ar_valor
            elif unit_price is not None:
                mv_native = unit_price

        mv_brl, mv_usd = None, None
        if mv_native is not None:
            if asset.currency.value == "BRL":
                mv_brl = mv_native
                fx = lote.get("notion_total_brl")  # placeholder
                # Use snapshot fx for usd conversion if available
                snap = db.get(PortfolioSnapshot, snap_id)
                if snap and snap.fx_rate_usd_brl:
                    mv_usd = (mv_brl / snap.fx_rate_usd_brl).quantize(Decimal("0.01"))
            else:
                mv_usd = mv_native
                snap = db.get(PortfolioSnapshot, snap_id)
                if snap and snap.fx_rate_usd_brl:
                    mv_brl = (mv_native * snap.fx_rate_usd_brl).quantize(Decimal("0.01"))

        if mv_brl is not None:
            local_totals_by_snap[snap_id] = local_totals_by_snap.get(snap_id, Decimal("0")) + mv_brl

        existing = db.query(PortfolioSnapshotItem).filter(
            PortfolioSnapshotItem.external_source == ExternalSource.NOTION,
            PortfolioSnapshotItem.external_id == p.id,
        ).first()

        now = datetime.now(timezone.utc)
        last_edited = datetime.fromisoformat(p.last_edited_time.replace("Z", "+00:00"))

        if existing:
            existing.snapshot_id = snap_id
            existing.asset_id = asset.id
            existing.quantity = qty
            existing.unit_price = unit_price
            existing.market_value_native = mv_native
            existing.market_value_brl = mv_brl
            existing.market_value_usd = mv_usd
            existing.average_cost_brl = avg_cost
            existing.total_invested_brl = invested_brl
            existing.notion_remote_last_edited_at = last_edited
            existing.notion_sync_status = NotionSyncStatus.SYNCED
            updated += 1
        else:
            db.add(PortfolioSnapshotItem(
                id=str(uuid.uuid4()),
                snapshot_id=snap_id,
                asset_id=asset.id,
                quantity=qty or Decimal("0"),
                unit_price=unit_price,
                market_value_native=mv_native,
                market_value_brl=mv_brl,
                market_value_usd=mv_usd,
                average_cost_brl=avg_cost,
                total_invested_brl=invested_brl,
                external_id=p.id,
                external_source=ExternalSource.NOTION,
                notion_remote_last_edited_at=last_edited,
                notion_sync_status=NotionSyncStatus.SYNCED,
                created_at=now,
            ))
            inserted += 1

    if apply:
        # Roll up totals onto snapshot headers
        for snap_id, total in local_totals_by_snap.items():
            snap = db.get(PortfolioSnapshot, snap_id)
            if snap:
                snap.total_value_brl = total
                if snap.fx_rate_usd_brl:
                    snap.total_value_usd = (total / snap.fx_rate_usd_brl).quantize(Decimal("0.01"))
        db.commit()
    else:
        db.rollback()

    return {
        "inserted": inserted, "updated": updated,
        "skipped_orphan": skipped_orphan, "skipped_no_lote": skipped_no_lote,
        "errors": errors, "local_totals": local_totals_by_snap,
    }


def write_divergencias_report(lote_map: dict, local_totals: dict[str, Decimal]) -> Path | None:
    """CSV row per lote where |notion - local| / notion > 1%."""
    rows = []
    for notion_id, info in lote_map.items():
        snap_id = info["snapshot_id"]
        notion_brl = info.get("notion_total_brl")
        local_brl = local_totals.get(snap_id, Decimal("0"))
        if notion_brl and notion_brl > 0:
            diff = abs(notion_brl - local_brl)
            pct = diff / notion_brl
            if pct > DIVERGENCIAS_THRESHOLD:
                rows.append({
                    "period_end": info["period_end"].isoformat(),
                    "notion_total_brl": str(notion_brl),
                    "local_total_brl": str(local_brl),
                    "diff_brl": str(notion_brl - local_brl),
                    "diff_pct": f"{pct * 100:.2f}%",
                })
    if not rows:
        return None
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = REPO_ROOT / "data" / f"divergencias_snapshots_{ts}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--workspace", default=DEFAULT_WORKSPACE_NAME)
    args = parser.parse_args()

    db = SessionLocal()
    try:
        ws = db.query(Workspace).filter(Workspace.name == args.workspace).first()
        if not ws:
            print(f"workspace {args.workspace!r} not found", file=sys.stderr)
            return 2
        token = _get_token(db)
        cli = NotionClient(token, timeout=120.0)

        lote_db_id = _get_db_id(db, "DB_IG_LOTE_APURACAO")
        apuracao_db_id = _get_db_id(db, "DB_IG_APURACAO")

        lote_result = import_lotes(db, ws.id, cli, lote_db_id, args.apply)
        print(f"\nLotes: inserted={lote_result['inserted']} updated={lote_result['updated']}", flush=True)

        items_result = import_items(
            db, ws.id, cli, apuracao_db_id, lote_result["lote_map"], args.apply,
        )
        print(f"\nItems: inserted={items_result['inserted']} updated={items_result['updated']} "
              f"skipped_orphan={items_result['skipped_orphan']} "
              f"skipped_no_lote={items_result['skipped_no_lote']}", flush=True)

        if args.apply:
            report = write_divergencias_report(lote_result["lote_map"], items_result["local_totals"])
            if report:
                print(f"\nDivergencias (>1%) saved to: {report}")
                print(f"  Rows with divergence: count via CSV")
            else:
                print(f"\nNo divergencias above 1% threshold.")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
