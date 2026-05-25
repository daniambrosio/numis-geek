"""CLI to create a PortfolioSnapshot for a workspace at a given date.

Usage:
    python -m scripts.create_snapshot --workspace "Família Ambrosio" --period 2026-04-30
    python -m scripts.create_snapshot --workspace "Família Ambrosio" --period 2026-04-30 --auto
    python -m scripts.create_snapshot --workspace "Família Ambrosio" --period 2026-04-30 --force

--auto   Use SnapshotSource.AUTOMATED (same path as the cron job; detects
         pendencies + downgrades to IN_REVIEW when needed).
--force  Overwrite an existing CLOSED snapshot (otherwise the operation
         refuses to silently discard data).
"""
from __future__ import annotations

import argparse
import sys
from datetime import date

from numis_geek.db.session import SessionLocal
from numis_geek.models.portfolio_snapshot import SnapshotSource, SnapshotStatus
from numis_geek.models.workspace import Workspace
from numis_geek.services.snapshot import create_snapshot


def main(
    workspace_name: str, period_end: date,
    *, auto: bool = False, force: bool = False,
) -> None:
    db = SessionLocal()
    try:
        ws = db.query(Workspace).filter(Workspace.name == workspace_name).first()
        if not ws:
            print(f"Workspace '{workspace_name}' not found", file=sys.stderr)
            sys.exit(2)
        result = create_snapshot(
            db, workspace_id=ws.id, period_end=period_end,
            source=SnapshotSource.AUTOMATED if auto else SnapshotSource.MANUAL,
            initial_status=SnapshotStatus.CLOSED,
            force_reopen=force,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    print(f"Snapshot created for {workspace_name} @ {period_end}")
    print(f"  snapshot_id:    {result.snapshot_id}")
    print(f"  items:          {result.items_count}")
    print(f"  status:         {result.status.value}")
    print(f"  pendencies:     {result.pendencies_count}")
    print(f"  total BRL:      {result.total_value_brl}")
    print(f"  total USD:      {result.total_value_usd}")
    print(f"  fx USD->BRL:    {result.fx_rate_usd_brl}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--period", required=True, help="period_end_date YYYY-MM-DD")
    parser.add_argument("--auto", action="store_true",
                        help="Use SnapshotSource.AUTOMATED (cron-like behavior)")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite an existing CLOSED snapshot")
    args = parser.parse_args()
    main(
        args.workspace,
        date.fromisoformat(args.period),
        auto=args.auto,
        force=args.force,
    )
