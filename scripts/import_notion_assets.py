"""Import assets from a Notion-export JSON snapshot into the local DB.

This script does NOT call the Notion API. It only reads `data/notion_export.json`
(produced by orchestration outside the script — see `scripts/fetch_notion_assets.py`)
and idempotently writes the asset rows into the target workspace.

CLI usage:
    python scripts/import_notion_assets.py --dry-run                    # default
    python scripts/import_notion_assets.py --apply
    python scripts/import_notion_assets.py --from-json path/to/file.json --apply

Match key (idempotency):
    - Ticker rows:     (workspace_id, ticker, financial_institution_id)
    - Tickerless rows: (workspace_id, name, financial_institution_id, asset_class)

On match → update name/is_active/notes/subtype/currency in place.
On miss  → insert a new asset row.

Specialized child rows (`fixed_income_asset` / `physical_asset`) are NOT
created — the parent asset row only. The user fills those in via the UI later.

Bypasses the API-layer `details`-required validation by writing directly via
SQLAlchemy. Intentional per spec 07a.
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from sqlalchemy.orm import Session

from numis_geek.db.session import SessionLocal
from numis_geek.models.account import Currency
from numis_geek.models.asset import Asset, AssetClass
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.user import User, UserRole
from numis_geek.models.workspace import Workspace


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_JSON_PATH = REPO_ROOT / "data" / "notion_export.json"
DEFAULT_WORKSPACE_NAME = "Família Ambrosio"
SYSADMIN_EMAIL = "sysadmin@numis-geek.internal"
PARTICULAR_SHORT_NAME = "Particular"


@dataclass
class ImportSummary:
    total: int = 0
    would_create: int = 0
    would_update: int = 0
    skipped: list[tuple[str, str]] = field(default_factory=list)  # (ref, reason)
    by_class: Counter = field(default_factory=Counter)
    fallback_to_particular: list[tuple[str, str]] = field(default_factory=list)  # (ref, requested_if)
    unmapped_classes: list[tuple[str, str]] = field(default_factory=list)  # (ref, raw_class)

    def print_report(self, *, applied: bool) -> None:
        verb = "Applied" if applied else "Dry-run"
        print()
        print(f"=== Notion asset import — {verb} ===")
        print(f"Total rows in JSON:        {self.total}")
        print(f"Would create:              {self.would_create}")
        print(f"Would update:              {self.would_update}")
        print(f"Skipped:                   {len(self.skipped)}")
        print()
        print("By class:")
        for cls, count in sorted(self.by_class.items()):
            print(f"  {cls:20s} {count}")
        if self.fallback_to_particular:
            print()
            print("Fallback to 'Particular' (unmapped IF):")
            for ref, requested in self.fallback_to_particular:
                print(f"  {ref}: requested IF '{requested}'")
        if self.unmapped_classes:
            print()
            print("Unmapped asset_class values (FATAL):")
            for ref, raw in self.unmapped_classes:
                print(f"  {ref}: '{raw}'")
        if self.skipped:
            print()
            print("Skipped:")
            for ref, reason in self.skipped:
                print(f"  {ref}: {reason}")
        print()


def _load_snapshot(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"JSON snapshot not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_workspace(db: Session, name: str) -> Workspace:
    ws = db.query(Workspace).filter(Workspace.name == name).first()
    if not ws:
        raise SystemExit(f"Workspace '{name}' not found. Run scripts/seed.py first.")
    return ws


def _resolve_sysadmin_id(db: Session) -> str | None:
    user = db.query(User).filter(
        User.email == SYSADMIN_EMAIL,
        User.role == UserRole.sysadmin,
    ).first()
    return user.id if user else None


def _build_fi_map(db: Session) -> dict[str, FinancialInstitution]:
    return {
        fi.short_name: fi
        for fi in db.query(FinancialInstitution).filter(FinancialInstitution.is_active.is_(True)).all()
    }


def _resolve_asset_class(raw: str) -> AssetClass | None:
    try:
        return AssetClass(raw)
    except ValueError:
        return None


def _resolve_currency(raw: str) -> Currency | None:
    try:
        return Currency(raw)
    except ValueError:
        return None


def _ref(row: dict) -> str:
    return row.get("notion_id") or row.get("ticker") or row.get("name") or "<unknown>"


def import_from_json(
    json_path: Path | str,
    *,
    apply: bool,
    workspace_name: str = DEFAULT_WORKSPACE_NAME,
    db: Session | None = None,
) -> ImportSummary:
    """Read the JSON snapshot and (optionally) write rows into the DB.

    Returns an ImportSummary regardless of mode. When `apply=False`, no DB
    writes are committed even though we still inspect the DB to compute
    "would_create" vs "would_update".

    Raises SystemExit if any unmapped asset_class is encountered (per spec).
    """
    json_path = Path(json_path)
    snapshot = _load_snapshot(json_path)

    # Allow caller to pass an existing session (used by tests).
    own_session = db is None
    if own_session:
        db = SessionLocal()

    summary = ImportSummary()
    try:
        ws = _resolve_workspace(db, workspace_name)
        sysadmin_id = _resolve_sysadmin_id(db)
        fi_map = _build_fi_map(db)
        particular = fi_map.get(PARTICULAR_SHORT_NAME)
        if not particular:
            raise SystemExit(
                f"Required IF '{PARTICULAR_SHORT_NAME}' not found. "
                "Re-run scripts/seed.py to create it."
            )

        rows: Iterable[dict] = snapshot.get("assets", [])
        for row in rows:
            summary.total += 1
            ref = _ref(row)

            # Class mapping
            raw_class = row.get("asset_class") or ""
            asset_class = _resolve_asset_class(raw_class)
            if asset_class is None:
                summary.unmapped_classes.append((ref, raw_class))
                summary.skipped.append((ref, f"unmapped asset_class '{raw_class}'"))
                continue

            # Currency mapping
            raw_currency = row.get("currency") or ""
            currency = _resolve_currency(raw_currency)
            if currency is None:
                summary.skipped.append((ref, f"unmapped currency '{raw_currency}'"))
                continue

            # FI mapping (with fallback to Particular)
            requested_if = row.get("financial_institution_short_name") or ""
            fi = fi_map.get(requested_if)
            if not fi:
                summary.fallback_to_particular.append((ref, requested_if))
                fi = particular

            ticker = row.get("ticker") or None
            if isinstance(ticker, str):
                ticker = ticker.strip() or None
            name = (row.get("name") or "").strip()
            if not name:
                summary.skipped.append((ref, "empty name"))
                continue

            is_active = bool(row.get("is_active", True))
            subtype = row.get("subtype") or None
            notes = row.get("notes") or None
            # Preserve the Notion URL in notes for traceability if provided
            notion_url = row.get("notion_url")
            if notion_url and (not notes or notion_url not in notes):
                notes = (notes + "\n" if notes else "") + f"Notion: {notion_url}"

            # Idempotency lookup
            q = db.query(Asset).filter(
                Asset.workspace_id == ws.id,
                Asset.financial_institution_id == fi.id,
            )
            if ticker:
                existing = q.filter(Asset.ticker == ticker).first()
            else:
                existing = q.filter(
                    Asset.ticker.is_(None),
                    Asset.name == name,
                    Asset.asset_class == asset_class,
                ).first()

            summary.by_class[asset_class.value] += 1

            if existing:
                summary.would_update += 1
                if apply:
                    existing.name = name
                    existing.asset_class = asset_class
                    existing.currency = currency
                    existing.subtype = subtype
                    existing.notes = notes
                    existing.is_active = is_active
                    existing.updated_at = datetime.now(timezone.utc)
                    if sysadmin_id:
                        existing.updated_by = sysadmin_id
            else:
                summary.would_create += 1
                if apply:
                    now = datetime.now(timezone.utc)
                    db.add(Asset(
                        id=str(uuid.uuid4()),
                        workspace_id=ws.id,
                        financial_institution_id=fi.id,
                        asset_class=asset_class,
                        subtype=subtype,
                        name=name,
                        ticker=ticker,
                        currency=currency,
                        notes=notes,
                        is_active=is_active,
                        created_at=now,
                        updated_at=now,
                        created_by=sysadmin_id,
                        updated_by=sysadmin_id,
                    ))

        if apply:
            db.commit()
    finally:
        if own_session:
            db.close()

    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Read JSON, print summary, no DB writes (default).",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Read JSON and write changes to the DB.",
    )
    parser.add_argument(
        "--from-json",
        type=Path,
        default=DEFAULT_JSON_PATH,
        help=f"Path to the snapshot JSON (default: {DEFAULT_JSON_PATH}).",
    )
    parser.add_argument(
        "--workspace",
        default=DEFAULT_WORKSPACE_NAME,
        help=f"Workspace name to import into (default: '{DEFAULT_WORKSPACE_NAME}').",
    )
    args = parser.parse_args(argv)

    apply = bool(args.apply)
    summary = import_from_json(
        args.from_json,
        apply=apply,
        workspace_name=args.workspace,
    )
    summary.print_report(applied=apply)

    if summary.unmapped_classes:
        print("ERROR: unmapped asset_class values encountered — see above.", file=sys.stderr)
        return 2
    if summary.fallback_to_particular:
        print(
            "ERROR: one or more rows fell back to 'Particular' due to unmapped IF. "
            "Add the missing IFs and re-run.",
            file=sys.stderr,
        )
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
