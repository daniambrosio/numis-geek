"""Import Notion DB IG Proventos → local Distribution.

Mapping Notion "Tipo Provento" → DistributionType:
    Dividendos       → DIVIDEND
    Rendimentos      → DIVIDEND
    Reembolso        → DIVIDEND
    Juros            → JCP
    Cupom            → INTEREST
    BTC              → SECURITIES_LENDING (Banco de Títulos)
    Débito           → SKIP (it's an IR/tax debit row, not a distribution)

financial_institution_id is derived from Asset.account.financial_institution_id.

CLI:
    uv run python -m scripts.import_notion_distributions          # dry-run
    uv run python -m scripts.import_notion_distributions --apply
"""
from __future__ import annotations

import argparse
import sys
import uuid
from collections import Counter
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from numis_geek.db.session import SessionLocal
from numis_geek.integrations.notion import NotionClient, NotionPage
from numis_geek.models.account import Account, Currency
from numis_geek.models.asset import Asset
from numis_geek.models.distribution import Distribution, DistributionType
from numis_geek.models.external import ExternalSource
from numis_geek.models.integration_credential import (
    IntegrationCredential, IntegrationProvider,
)
from numis_geek.models.workspace import Workspace


DEFAULT_WORKSPACE_NAME = "Família Ambrosio"

TYPE_MAP = {
    "Dividendos": DistributionType.DIVIDEND,
    "Rendimentos": DistributionType.DIVIDEND,
    "Reembolso": DistributionType.DIVIDEND,
    "Juros": DistributionType.JCP,
    "Cupom": DistributionType.INTEREST,
    "BTC": DistributionType.SECURITIES_LENDING,
}

# Treated as cost/tax adjustment in the source provento; not a distribution.
SKIP_TYPES = {"Débito"}


def _get_token(db: Session) -> str:
    row = db.query(IntegrationCredential).filter(
        IntegrationCredential.provider == IntegrationProvider.NOTION,
        IntegrationCredential.key_name == "NOTION_TOKEN",
        IntegrationCredential.is_active.is_(True),
    ).first()
    if not row:
        raise RuntimeError("NOTION_TOKEN not in IntegrationCredential.")
    return row.secret_value


def _get_db_id(db: Session) -> str:
    row = db.query(IntegrationCredential).filter(
        IntegrationCredential.provider == IntegrationProvider.NOTION,
        IntegrationCredential.key_name == "DB_IG_PROVENTOS",
    ).first()
    if not row:
        raise RuntimeError("DB_IG_PROVENTOS not in IntegrationCredential.")
    return row.secret_value


def _extract_select(prop) -> str | None:
    if not prop or prop.get("type") != "select":
        return None
    sel = prop.get("select")
    return sel.get("name") if sel else None


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


def _extract_first_relation(prop) -> str | None:
    if not prop or prop.get("type") != "relation":
        return None
    rels = prop.get("relation") or []
    return rels[0]["id"] if rels else None


def _lookup_asset(db: Session, notion_page_id: str) -> Asset | None:
    nid = notion_page_id.replace("-", "")
    return db.query(Asset).filter(
        Asset.external_source == ExternalSource.NOTION,
        Asset.external_id.contains(nid),
    ).first()


def process(db: Session, ws_id: str, pages: list[NotionPage], apply: bool) -> dict:
    inserted, updated, skipped_orphan, skipped_type, skipped_debito, errors = 0, 0, 0, 0, 0, []
    type_counts = Counter()
    asset_cache: dict[str, Asset] = {}

    for p in pages:
        props = p.properties
        tipo = _extract_select(props.get("Tipo Provento"))
        type_counts[tipo or "(empty)"] += 1

        if tipo in SKIP_TYPES:
            skipped_debito += 1
            continue
        dist_type = TYPE_MAP.get(tipo) if tipo else None
        if not dist_type:
            skipped_type += 1
            errors.append(f"{p.id}: unmapped Tipo Provento={tipo}")
            continue

        event_date = _extract_date(props.get("Data Apuração"))
        if not event_date:
            errors.append(f"{p.id}: missing Data Apuração")
            continue

        value = _extract_number(props.get("Valor Provento MC"))
        if value is None:
            errors.append(f"{p.id}: missing Valor Provento MC")
            continue
        debito = _extract_number(props.get("Debito MC")) or Decimal("0")

        asset_notion_id = _extract_first_relation(props.get("Ativo"))
        if not asset_notion_id:
            skipped_orphan += 1
            errors.append(f"{p.id}: no Ativo relation")
            continue
        if asset_notion_id in asset_cache:
            asset = asset_cache[asset_notion_id]
        else:
            asset = _lookup_asset(db, asset_notion_id)
            if asset:
                asset_cache[asset_notion_id] = asset
        if not asset:
            skipped_orphan += 1
            errors.append(f"{p.id}: orphan asset {asset_notion_id}")
            continue

        # FI via Asset → Account → financial_institution_id
        account = db.get(Account, asset.account_id)
        if not account:
            errors.append(f"{p.id}: asset {asset.id} has no account")
            continue
        fi_id = account.financial_institution_id

        # Currency from Asset
        currency = asset.currency
        # fx_rate: USD → fetch from Notion field "Cambio Lote (R$)" if available; default 1.0
        # For now, leave 1.0 and rely on the snapshot pass to backfill FX.
        fx_rate = Decimal("1.0")

        gross = value
        tax = abs(debito) if debito else None
        net = gross - (tax or Decimal("0"))

        existing = db.query(Distribution).filter(
            Distribution.external_source == ExternalSource.NOTION,
            Distribution.external_id == p.id,
        ).first()

        now = datetime.now(timezone.utc)
        if existing:
            existing.workspace_id = ws_id
            existing.financial_institution_id = fi_id
            existing.asset_id = asset.id
            existing.type = dist_type
            existing.event_date = event_date
            existing.gross_amount = gross
            existing.tax = tax
            existing.net_amount = net
            existing.currency = currency
            existing.fx_rate = fx_rate
            existing.updated_at = now
            updated += 1
        else:
            db.add(Distribution(
                id=str(uuid.uuid4()),
                workspace_id=ws_id,
                financial_institution_id=fi_id,
                asset_id=asset.id,
                type=dist_type,
                event_date=event_date,
                gross_amount=gross,
                tax=tax,
                net_amount=net,
                currency=currency,
                fx_rate=fx_rate,
                is_active=True,
                external_id=p.id,
                external_source=ExternalSource.NOTION,
                created_at=now,
                updated_at=now,
            ))
            inserted += 1

    if apply:
        db.commit()
    else:
        db.rollback()

    return {
        "inserted": inserted, "updated": updated,
        "skipped_orphan": skipped_orphan, "skipped_type": skipped_type,
        "skipped_debito": skipped_debito,
        "type_counts": dict(type_counts),
        "errors": errors,
    }


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
        db_id = _get_db_id(db)
        cli = NotionClient(token, timeout=60.0)

        print("Fetching DB IG Proventos via Notion API...", flush=True)
        pages = cli.query_all(db_id)
        print(f"  fetched {len(pages)} pages", flush=True)

        result = process(db, ws.id, pages, args.apply)
    finally:
        db.close()

    print(f"\nResult ({'APPLY' if args.apply else 'DRY-RUN'}):")
    print(f"  inserted:       {result['inserted']}")
    print(f"  updated:        {result['updated']}")
    print(f"  skipped_orphan: {result['skipped_orphan']}")
    print(f"  skipped_type:   {result['skipped_type']}")
    print(f"  skipped_debito: {result['skipped_debito']}")
    print(f"\nNotion type distribution:")
    for t, c in sorted(result["type_counts"].items(), key=lambda x: -x[1]):
        print(f"  {t!s:25s}: {c}")
    if result["errors"]:
        print(f"\nErrors ({len(result['errors'])}):")
        for e in result["errors"][:15]:
            print(f"  - {e}")
        if len(result["errors"]) > 15:
            print(f"  ... ({len(result['errors']) - 15} more)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
