"""Import lançamentos from a Notion-export JSON snapshot into the local DB.

This script does NOT call the Notion API. It only reads
`data/notion_lancamento_export.json` (produced by orchestration outside the
script — see `scripts/fetch_notion_lancamentos.py`) and idempotently writes
the lançamento rows into the target workspace.

CLI usage:
    python scripts/import_notion_lancamentos.py --dry-run        # default
    python scripts/import_notion_lancamentos.py --apply          # commit
    python scripts/import_notion_lancamentos.py --apply --force  # ignore errors
    python scripts/import_notion_lancamentos.py --from-json path/to/file.json

Match key (idempotency): `(external_source = 'NOTION', external_id = <notion_id>)`.
On match → update; never duplicate.

Asset resolution: looks up the local Asset by `(external_source='NOTION',
external_id=<asset_url>)` (populated by spec 07a's import). If not found →
record an `ORPHAN_ASSET` error and skip the row.

Validation:
- Hard errors (`errors[]`) and warnings (`warnings[]`) provided by the fetch
  step in the JSON are surfaced in the dry-run summary.
- Two codes are additionally re-validated locally during `--apply`:
  - `ORPHAN_ASSET`: asset external_id not present in the local DB.
  - `NEGATIVE_RUNNING_QTY`: cumulative quantity goes negative for an asset
    without a prior `RESGATE_TOTAL` reset.

Exit codes:
    0  clean
    2  unmapped Tipo Transação
    3  any orphaned lançamento (asset external_id not in local DB)
    4  any hard validation error (only in --apply unless --force)
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy.orm import Session

from numis_geek.db.session import SessionLocal
from numis_geek.models.account import Currency
from numis_geek.models.asset import Asset, AssetClass
from numis_geek.models.external import ExternalSource
from numis_geek.models.asset_movement import AssetMovement, AssetMovementType
from numis_geek.models.notion_sync import NotionSyncStatus
from numis_geek.models.user import User, UserRole
from numis_geek.models.workspace import Workspace


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_JSON_PATH = REPO_ROOT / "data" / "notion_lancamento_export.json"
DEFAULT_WORKSPACE_NAME = "Família Ambrosio"
SYSADMIN_EMAIL = "sysadmin@numis-geek.internal"

NON_COTADO_CLASSES = {
    AssetClass.FIXED_INCOME,
    AssetClass.FGTS,
    AssetClass.PRIVATE_PENSION,
    AssetClass.CASH,
}

# Notion `Tipo Transação` → Numis `AssetMovementType`.
NOTION_TYPE_MAP: dict[str, AssetMovementType] = {
    "Compra": AssetMovementType.BUY,
    "Venda": AssetMovementType.SELL,
    "Bonificação": AssetMovementType.BONUS,
    "Subscrição": AssetMovementType.SUBSCRIPTION,
    "ComeCota": AssetMovementType.COME_COTAS,
    "Resgate Total": AssetMovementType.FULL_REDEMPTION,
}

COTADO_OR_VALUE_TYPES = {
    AssetMovementType.BUY,
    AssetMovementType.SELL,
    AssetMovementType.SUBSCRIPTION,
    AssetMovementType.FULL_REDEMPTION,
}


@dataclass
class ImportSummary:
    total: int = 0
    would_create: int = 0
    would_update: int = 0
    by_type: Counter = field(default_factory=Counter)
    errors: list[dict] = field(default_factory=list)      # hard errors (skip)
    warnings: list[dict] = field(default_factory=list)    # soft issues (import)
    skipped: list[tuple[str, str]] = field(default_factory=list)  # (notion_id, reason)

    def add_error(self, notion_id: str, code: str, message: str, raw: Any | None = None) -> None:
        self.errors.append({"notion_id": notion_id, "code": code, "message": message, "raw": raw})

    def add_warning(self, notion_id: str, code: str, message: str, raw: Any | None = None) -> None:
        self.warnings.append({"notion_id": notion_id, "code": code, "message": message, "raw": raw})

    def grouped_errors(self) -> dict[str, int]:
        c: Counter = Counter()
        for e in self.errors:
            c[e["code"]] += 1
        return dict(c)

    def grouped_warnings(self) -> dict[str, int]:
        c: Counter = Counter()
        for w in self.warnings:
            c[w["code"]] += 1
        return dict(c)

    def has_unmapped_type(self) -> bool:
        return any(e["code"] == "UNKNOWN_TYPE" for e in self.errors)

    def has_orphans(self) -> bool:
        return any(e["code"] == "ORPHAN_ASSET" for e in self.errors)

    def print_report(self, *, applied: bool) -> None:
        verb = "Applied" if applied else "Dry-run"
        print()
        print(f"=== Notion lançamento import — {verb} ===")
        print(f"Total rows in JSON:        {self.total}")
        print(f"Would create:              {self.would_create}")
        print(f"Would update:              {self.would_update}")
        print(f"Skipped (errors):          {len(self.skipped)}")
        print()
        print("By type:")
        for t, count in sorted(self.by_type.items()):
            print(f"  {t:20s} {count}")
        if self.errors:
            print()
            print(f"Hard errors ({len(self.errors)}):")
            for code, count in sorted(self.grouped_errors().items()):
                print(f"  {code:35s} {count}")
        if self.warnings:
            print()
            print(f"Warnings ({len(self.warnings)}):")
            for code, count in sorted(self.grouped_warnings().items()):
                print(f"  {code:35s} {count}")
        print()


def _to_decimal(v: Any) -> Decimal | None:
    if v is None or v == "":
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError):
        return None


def _to_date(v: Any) -> date | None:
    if v is None:
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


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


def _build_asset_index(db: Session, workspace_id: str) -> dict[str, Asset]:
    """Map Notion external_id (URL) → local Asset row in this workspace."""
    rows = db.query(Asset).filter(
        Asset.workspace_id == workspace_id,
        Asset.external_source == ExternalSource.NOTION,
        Asset.external_id.isnot(None),
    ).all()
    return {a.external_id: a for a in rows}


def _compute_net(
    t: AssetMovementType,
    gross: Decimal,
    fee: Decimal,
    tax: Decimal,
) -> Decimal:
    if t == AssetMovementType.BUY:
        return gross + fee + tax
    if t in (AssetMovementType.SELL, AssetMovementType.FULL_REDEMPTION):
        return gross - fee - tax
    if t == AssetMovementType.COME_COTAS:
        return -tax
    if t == AssetMovementType.BONUS:
        return Decimal("0")
    if t == AssetMovementType.SUBSCRIPTION:
        return gross + fee + tax
    # Income types reach here only via direct map; we don't import them now.
    return gross - fee - tax


def import_from_json(
    json_path: Path | str,
    *,
    apply: bool,
    workspace_name: str = DEFAULT_WORKSPACE_NAME,
    force: bool = False,
    db: Session | None = None,
) -> ImportSummary:
    """Read the JSON snapshot and (optionally) write rows into the DB.

    Returns an `ImportSummary` regardless of mode. When `apply=False`, no DB
    writes are committed. When `apply=True` and there are hard errors,
    refuses to proceed unless `force=True`.
    """
    json_path = Path(json_path)
    snapshot = _load_snapshot(json_path)

    own_session = db is None
    if own_session:
        db = SessionLocal()

    summary = ImportSummary()
    # Carry over orchestrator-supplied errors/warnings verbatim.
    for e in snapshot.get("errors", []) or []:
        summary.errors.append(e)
    for w in snapshot.get("warnings", []) or []:
        summary.warnings.append(w)

    try:
        ws = _resolve_workspace(db, workspace_name)
        sysadmin_id = _resolve_sysadmin_id(db)
        asset_index = _build_asset_index(db, ws.id)

        rows: list[dict] = list(snapshot.get("lancamentos", []) or [])
        summary.total = len(rows)

        # Sort chronologically for NEGATIVE_RUNNING_QTY tracking; preserve a
        # stable secondary sort by notion_id so the order is deterministic.
        def _sort_key(r: dict) -> tuple:
            d = _to_date(r.get("event_date")) or date.min
            return (d, r.get("notion_id") or "")

        rows.sort(key=_sort_key)

        # Per-asset cumulative qty tracker (resets on RESGATE_TOTAL, ignores
        # rows that are skipped due to other errors).
        running_qty: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))

        # Track Notion IDs we've already processed in this run, so we can
        # surface DUPLICATE_NOTION_ID locally even if the orchestrator missed it.
        seen_notion_ids: set[str] = set()

        for row in rows:
            notion_id = row.get("notion_id") or ""
            if not notion_id:
                summary.add_error("<no notion_id>", "MISSING_NOTION_ID",
                                  "Row missing notion_id", row)
                summary.skipped.append((notion_id, "missing notion_id"))
                continue

            if notion_id in seen_notion_ids:
                summary.add_error(notion_id, "DUPLICATE_NOTION_ID",
                                  "Duplicate notion_id within snapshot", row)
                summary.skipped.append((notion_id, "duplicate notion_id"))
                continue
            seen_notion_ids.add(notion_id)

            # ── Type mapping ─────────────────────────────────────────────────
            raw_type = row.get("type") or row.get("notion_type") or ""
            ltype: AssetMovementType | None
            if raw_type in NOTION_TYPE_MAP:
                ltype = NOTION_TYPE_MAP[raw_type]
            else:
                # Accept already-mapped Numis enum values too (so test fixtures
                # can use them directly).
                try:
                    ltype = AssetMovementType(raw_type)
                except ValueError:
                    ltype = None

            if ltype is None:
                summary.add_error(notion_id, "UNKNOWN_TYPE",
                                  f"Unmapped Tipo Transação: {raw_type!r}", row)
                summary.skipped.append((notion_id, f"unknown type {raw_type!r}"))
                continue

            # ── Date parsing ─────────────────────────────────────────────────
            event_date = _to_date(row.get("event_date"))
            if event_date is None:
                summary.add_error(notion_id, "MISSING_DATE",
                                  "Data Transação is null/invalid", row)
                summary.skipped.append((notion_id, "missing date"))
                continue
            if event_date > date.today():
                summary.add_error(notion_id, "FUTURE_DATE",
                                  f"Data Transação > today: {event_date}", row)
                summary.skipped.append((notion_id, "future date"))
                continue

            # ── Asset resolution ─────────────────────────────────────────────
            asset_external_id = row.get("asset_external_id") or ""
            if not asset_external_id:
                summary.add_error(notion_id, "MISSING_ASSET",
                                  "Ativo relation empty", row)
                summary.skipped.append((notion_id, "missing asset"))
                continue

            asset = asset_index.get(asset_external_id)
            if asset is None:
                summary.add_error(notion_id, "ORPHAN_ASSET",
                                  f"Asset external_id not found locally: {asset_external_id}",
                                  row)
                summary.skipped.append((notion_id, "orphan asset"))
                continue

            # ── Numeric fields ───────────────────────────────────────────────
            quantity = _to_decimal(row.get("quantity"))
            unit_price = _to_decimal(row.get("unit_price"))
            gross_amount = _to_decimal(row.get("gross_amount"))
            fee = _to_decimal(row.get("fee"))
            tax = _to_decimal(row.get("tax"))
            fx_rate = _to_decimal(row.get("fx_rate")) or Decimal("1")
            currency_raw = row.get("currency") or asset.currency.value
            try:
                currency = Currency(currency_raw)
            except ValueError:
                currency = asset.currency

            # ── Per-type validation rules (locally re-checked) ───────────────
            if ltype in COTADO_OR_VALUE_TYPES:
                has_qty_price = quantity is not None and unit_price is not None
                has_gross = gross_amount is not None
                if not has_qty_price and not has_gross:
                    summary.add_error(notion_id, "COMPRA_VENDA_MISSING_VALUE",
                                      f"{ltype.value} row has neither qty+price nor gross_amount",
                                      row)
                    summary.skipped.append((notion_id, "missing value"))
                    continue
                # No further check: Pydantic already requires (qty+price) OR gross.
                # We intentionally allow cotado assets to use gross-only, because
                # the user's real data (Funds, dust crypto) requires it.
            elif ltype == AssetMovementType.BONUS:
                if quantity is None or quantity <= 0:
                    summary.add_error(notion_id, "BONIFICACAO_MISSING_QTY",
                                      "BONIFICACAO row has null/zero quantity", row)
                    summary.skipped.append((notion_id, "bonificacao missing qty"))
                    continue
            elif ltype == AssetMovementType.COME_COTAS:
                if (tax is None or tax <= 0) and (gross_amount is None or gross_amount <= 0):
                    summary.add_error(notion_id, "COMECOTAS_MISSING_TAX",
                                      "ComeCota row missing both Taxas and AR Valor", row)
                    summary.skipped.append((notion_id, "comecotas missing tax"))
                    continue

            # ── NEGATIVE_RUNNING_QTY check (cotado only) ─────────────────────
            qty_for_running = quantity or Decimal("0")
            if asset.asset_class not in NON_COTADO_CLASSES:
                key = asset.id
                if ltype in (AssetMovementType.BUY, AssetMovementType.SUBSCRIPTION,
                             AssetMovementType.BONUS):
                    running_qty[key] += qty_for_running
                elif ltype in (AssetMovementType.SELL, AssetMovementType.FULL_REDEMPTION):
                    running_qty[key] -= qty_for_running
                    if ltype == AssetMovementType.FULL_REDEMPTION:
                        running_qty[key] = Decimal("0")
                    elif running_qty[key] < -Decimal("1e-6"):
                        summary.add_warning(
                            notion_id, "NEGATIVE_RUNNING_QTY",
                            f"Cumulative qty negative for asset {asset.ticker or asset.name} "
                            f"({running_qty[key]})", row,
                        )

            # ── Persist ─────────────────────────────────────────────────────
            summary.by_type[ltype.value] += 1

            existing = db.query(AssetMovement).filter(
                AssetMovement.workspace_id == ws.id,
                AssetMovement.external_source == ExternalSource.NOTION,
                AssetMovement.external_id == notion_id,
            ).first()

            # Compute persisted gross + net.
            if gross_amount is not None:
                persisted_gross = gross_amount
            elif quantity is not None and unit_price is not None:
                persisted_gross = quantity * unit_price
            elif ltype == AssetMovementType.BONUS:
                persisted_gross = Decimal("0")
            else:
                persisted_gross = Decimal("0")

            net = _compute_net(
                ltype,
                persisted_gross,
                fee or Decimal("0"),
                tax or Decimal("0"),
            )

            notes = row.get("notes") or None
            settlement_date = _to_date(row.get("settlement_date"))
            nota_negociacao_number = row.get("nota_negociacao_number") or None

            if existing:
                summary.would_update += 1
                if apply:
                    now_dt = datetime.now(timezone.utc)
                    existing.asset_id = asset.id
                    existing.type = ltype
                    existing.event_date = event_date
                    existing.settlement_date = settlement_date
                    existing.quantity = quantity
                    existing.unit_price = unit_price
                    existing.gross_amount = persisted_gross
                    existing.fee = fee
                    existing.tax = tax
                    existing.net_amount = net
                    existing.currency = currency
                    existing.fx_rate = fx_rate
                    existing.notes = notes
                    existing.nota_negociacao_number = nota_negociacao_number
                    existing.notion_sync_status = NotionSyncStatus.SYNCED
                    existing.notion_last_synced_at = now_dt
                    existing.notion_remote_last_edited_at = now_dt
                    existing.updated_at = now_dt
                    if sysadmin_id:
                        existing.updated_by = sysadmin_id
            else:
                summary.would_create += 1
                if apply:
                    now = datetime.now(timezone.utc)
                    db.add(AssetMovement(
                        id=str(uuid.uuid4()),
                        workspace_id=ws.id,
                        asset_id=asset.id,
                        type=ltype,
                        event_date=event_date,
                        settlement_date=settlement_date,
                        quantity=quantity,
                        unit_price=unit_price,
                        gross_amount=persisted_gross,
                        fee=fee,
                        tax=tax,
                        net_amount=net,
                        currency=currency,
                        fx_rate=fx_rate,
                        notes=notes,
                        external_id=notion_id,
                        external_source=ExternalSource.NOTION,
                        nota_negociacao_number=nota_negociacao_number,
                        notion_sync_status=NotionSyncStatus.SYNCED,
                        notion_last_synced_at=now,
                        notion_remote_last_edited_at=now,
                        is_active=True,
                        created_at=now,
                        updated_at=now,
                        created_by=sysadmin_id,
                        updated_by=sysadmin_id,
                    ))

        if apply:
            if summary.errors and not force:
                # Refuse to commit — caller must pass --force.
                db.rollback()
            else:
                db.commit()
    finally:
        if own_session:
            db.close()

    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true",
                      help="Read JSON, print summary, no DB writes (default).")
    mode.add_argument("--apply", action="store_true",
                      help="Read JSON and write changes to the DB.")
    parser.add_argument("--from-json", type=Path, default=DEFAULT_JSON_PATH,
                        help=f"Path to the snapshot JSON (default: {DEFAULT_JSON_PATH}).")
    parser.add_argument("--workspace", default=DEFAULT_WORKSPACE_NAME,
                        help=f"Workspace name (default: '{DEFAULT_WORKSPACE_NAME}').")
    parser.add_argument("--force", action="store_true",
                        help="Apply even if there are hard errors.")
    args = parser.parse_args(argv)

    apply = bool(args.apply)
    summary = import_from_json(
        args.from_json,
        apply=apply,
        workspace_name=args.workspace,
        force=args.force,
    )
    summary.print_report(applied=apply)

    if apply and summary.errors and not args.force:
        print(
            "ERROR: hard errors encountered — refusing to commit. "
            "Pass --force to import anyway.",
            file=sys.stderr,
        )

    if summary.has_unmapped_type():
        return 2
    if summary.has_orphans():
        return 3
    if summary.errors:
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
