"""Import Notion DB IG Eventos → local CorporateAction.

Reads directly from Notion API via NotionClient (no JSON intermediate).
Idempotent: matches on (external_source=NOTION, external_id=<notion_page_id>).
On match → updates; on new → inserts.

Asset resolution: looks up local Asset by (external_source=NOTION,
external_id=<notion_asset_page_id>). Orphan rows are reported and skipped.

CLI:
    uv run python -m scripts.import_notion_corp_actions          # dry-run
    uv run python -m scripts.import_notion_corp_actions --apply  # commit
"""
from __future__ import annotations

import argparse
import sys
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from numis_geek.db.session import SessionLocal
from numis_geek.integrations.notion import NotionClient, NotionPage
from numis_geek.models.asset import Asset
from numis_geek.models.corporate_action import CorporateAction, CorporateActionType
from numis_geek.models.external import ExternalSource
from numis_geek.models.integration_credential import (
    IntegrationCredential, IntegrationProvider,
)
from numis_geek.models.notion_sync import NotionSyncStatus
from numis_geek.models.workspace import Workspace


DEFAULT_WORKSPACE_NAME = "Família Ambrosio"

# Notion "Tipo Evento" → CorporateActionType
TYPE_MAP = {
    "Split (Desdobramento)": CorporateActionType.SPLIT,
    "Inplit (Agrupamento)": CorporateActionType.GROUPING,
}


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
        IntegrationCredential.key_name == "DB_IG_EVENTOS",
    ).first()
    if not row:
        raise RuntimeError("DB_IG_EVENTOS not in IntegrationCredential.")
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


def _extract_rich_text(prop) -> str | None:
    if not prop or prop.get("type") != "rich_text":
        return None
    parts = prop.get("rich_text") or []
    text = "".join(p.get("plain_text", "") for p in parts)
    return text or None


def _extract_first_relation(prop) -> str | None:
    if not prop or prop.get("type") != "relation":
        return None
    rels = prop.get("relation") or []
    return rels[0]["id"] if rels else None


def _lookup_asset(db: Session, notion_page_id: str) -> Asset | None:
    """Asset external_id stored as full URL or just page id. Match either form."""
    nid = notion_page_id.replace("-", "")
    return db.query(Asset).filter(
        Asset.external_source == ExternalSource.NOTION,
        Asset.external_id.contains(nid),
    ).first()


def process(db: Session, ws_id: str, pages: list[NotionPage], apply: bool) -> dict:
    inserted, updated, skipped_orphan, skipped_type, errors = 0, 0, 0, 0, []
    for p in pages:
        props = p.properties
        tipo = _extract_select(props.get("Tipo Evento"))
        event_type = TYPE_MAP.get(tipo) if tipo else None
        if not event_type:
            skipped_type += 1
            errors.append(f"{p.id}: unmapped Tipo Evento={tipo}")
            continue

        event_date = _extract_date(props.get("Data Evento"))
        if not event_date:
            errors.append(f"{p.id}: missing Data Evento")
            continue

        ratio = _extract_number(props.get("Proporção:"))
        if ratio is None or ratio <= 0:
            errors.append(f"{p.id}: missing/invalid Proporção")
            continue

        asset_notion_id = _extract_first_relation(props.get("Ativo"))
        if not asset_notion_id:
            skipped_orphan += 1
            errors.append(f"{p.id}: no Ativo relation")
            continue
        asset = _lookup_asset(db, asset_notion_id)
        if not asset:
            skipped_orphan += 1
            errors.append(f"{p.id}: orphan asset {asset_notion_id}")
            continue

        notes = _extract_rich_text(props.get("Comentários"))

        # Look up by external_id
        existing = db.query(CorporateAction).filter(
            CorporateAction.external_source == ExternalSource.NOTION,
            CorporateAction.external_id == p.id,
        ).first()

        now = datetime.now(timezone.utc)
        last_edited = datetime.fromisoformat(p.last_edited_time.replace("Z", "+00:00"))

        if existing:
            existing.workspace_id = ws_id
            existing.asset_id = asset.id
            existing.event_date = event_date
            existing.event_type = event_type
            existing.ratio = ratio
            existing.notes = notes
            existing.updated_at = now
            existing.notion_remote_last_edited_at = last_edited
            existing.notion_sync_status = NotionSyncStatus.SYNCED
            updated += 1
        else:
            db.add(CorporateAction(
                id=str(uuid.uuid4()),
                workspace_id=ws_id,
                asset_id=asset.id,
                event_date=event_date,
                event_type=event_type,
                ratio=ratio,
                notes=notes,
                is_active=True,
                external_id=p.id,
                external_source=ExternalSource.NOTION,
                notion_remote_last_edited_at=last_edited,
                notion_sync_status=NotionSyncStatus.SYNCED,
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
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="commit (default: dry-run)")
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

        print(f"Fetching DB IG Eventos via Notion API...", flush=True)
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
    if result["errors"]:
        print(f"\nErrors ({len(result['errors'])}):")
        for e in result["errors"][:20]:
            print(f"  - {e}")
        if len(result["errors"]) > 20:
            print(f"  ... ({len(result['errors']) - 20} more)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
