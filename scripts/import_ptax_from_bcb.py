"""CLI to backfill/incremental-sync PTAX from BCB SGS.

Usage:
    python -m scripts.import_ptax_from_bcb --mode full
    python -m scripts.import_ptax_from_bcb --mode incremental
"""
from __future__ import annotations

import argparse
import sys
from typing import Literal

from numis_geek.db.session import SessionLocal
from numis_geek.services.ptax_sync import sync_ptax


def main(mode: Literal["full", "incremental"]) -> None:
    db = SessionLocal()
    try:
        result = sync_ptax(db, mode=mode)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    print(f"PTAX sync ({mode})")
    print(f"  range:    {result.range_start} → {result.range_end}")
    print(f"  fetched:  {result.fetched_count}")
    print(f"  inserted: {result.inserted_count}")
    print(f"  updated:  {result.updated_count}")
    print(f"  duration: {result.duration_ms} ms")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["full", "incremental"], default="incremental")
    args = parser.parse_args()
    try:
        main(args.mode)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
