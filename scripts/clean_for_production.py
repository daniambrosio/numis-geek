"""Clean DB before re-importing all data from Notion.

Keeps: user, workspace, integration_credential, financial_institution,
       ptax_rate.
Deletes: account, asset, asset_movement, distribution, corporate_action,
         portfolio_snapshot, portfolio_snapshot_item, audit_log,
         fixed_income_asset, physical_asset.

Run via:
    uv run python -m scripts.clean_for_production --confirm
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from sqlalchemy import text

from numis_geek.db.session import SessionLocal


# Order matters: children before parents to avoid FK errors.
DELETE_ORDER = [
    "portfolio_snapshot_item",
    "portfolio_snapshot",
    "corporate_action",
    "distribution",
    "asset_movement",
    "fixed_income_asset",
    "physical_asset",
    "asset",
    "account",
    "audit_log",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm", action="store_true",
                        help="actually delete (default: dry-run)")
    args = parser.parse_args()

    db = SessionLocal()
    counts_before = {}
    for t in DELETE_ORDER:
        try:
            counts_before[t] = db.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
        except Exception as e:
            counts_before[t] = f"ERR: {e}"

    print("\n=== Counts before cleanup ===")
    for t, c in counts_before.items():
        print(f"  {t:30s}: {c}")
    print()

    print("=== Preserved tables ===")
    for t in ["user", "workspace", "integration_credential", "financial_institution", "ptax_rate"]:
        c = db.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
        print(f"  {t:30s}: {c}")
    print()

    if not args.confirm:
        print("DRY-RUN. Pass --confirm to actually delete.")
        return 0

    print("Deleting...")
    total_deleted = 0
    for t in DELETE_ORDER:
        n = db.execute(text(f"DELETE FROM {t}")).rowcount
        total_deleted += n
        print(f"  {t:30s}: {n} deleted")
    db.commit()
    db.close()
    print(f"\nTotal rows deleted: {total_deleted}")
    print(f"Cleanup completed at {datetime.now(timezone.utc).isoformat()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
