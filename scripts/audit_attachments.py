"""Spec 43 §3 — orphan/ghost attachment audit.

Walks `attachment_storage.ROOT/{workspace_id}/*` on disk, compares with
the `attachment` table, and reports two mismatches:

  - Orphan files: physical file exists on FS, no Attachment row points
    at it (likely fallout from a race between row delete and FS delete,
    or a sysadmin restoring a backup partially).
  - Ghost rows:   Attachment row exists, but the file is missing on FS
    (manual rm, dir move without DB update, etc.). Same row would
    return HTTP 410 on download today.

REPORT ONLY — no file is touched, no row is deleted. Re-running is
safe and idempotent.

Usage:
    python -m scripts.audit_attachments
    python -m scripts.audit_attachments --root /custom/path

Exit codes:
    0 — no mismatch
    2 — orphans and/or ghosts found
    1 — runtime error (DB unreachable, ROOT missing, ...)
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.orm import Session

from numis_geek.db.session import SessionLocal
from numis_geek.models.attachment import Attachment
from numis_geek.services import attachment_storage


@dataclass(frozen=True)
class AuditResult:
    root: Path
    fs_count: int
    db_count: int
    orphan_files: list[Path] = field(default_factory=list)
    ghost_rows: list[Attachment] = field(default_factory=list)

    @property
    def has_mismatch(self) -> bool:
        return bool(self.orphan_files or self.ghost_rows)


def _walk_files(root: Path) -> list[Path]:
    """Return every regular file under `root` (recursive, sorted).

    Empty when the directory doesn't exist — that's a clean state, not
    an error. The caller emits a friendly message.
    """
    if not root.exists():
        return []
    return sorted(p for p in root.rglob("*") if p.is_file())


def audit(db: Session, root: Path | None = None) -> AuditResult:
    """Compute the audit. Pure read-only — DB and FS untouched."""
    target_root = (root or attachment_storage.ROOT).resolve()
    fs_files = _walk_files(target_root)
    fs_relative = {f.relative_to(target_root).as_posix() for f in fs_files}

    db_rows = db.query(Attachment).all()
    db_keys = {r.storage_key for r in db_rows}

    orphan_files = sorted(
        target_root / rel for rel in fs_relative - db_keys
    )
    ghost_rows = sorted(
        (r for r in db_rows if r.storage_key not in fs_relative),
        key=lambda r: r.storage_key,
    )
    return AuditResult(
        root=target_root,
        fs_count=len(fs_relative),
        db_count=len(db_rows),
        orphan_files=orphan_files,
        ghost_rows=ghost_rows,
    )


def _fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def render(result: AuditResult) -> str:
    """Build the human-facing report. Pure function — easier to test."""
    lines: list[str] = []
    lines.append(f"Audit attachments — root={result.root}")
    lines.append(f"  files on disk:    {result.fs_count}")
    lines.append(f"  attachment rows:  {result.db_count}")
    lines.append(f"  orphan files:     {len(result.orphan_files)}")
    lines.append(f"  ghost rows:       {len(result.ghost_rows)}")

    if result.orphan_files:
        lines.append("")
        lines.append("Orphan files (FS without DB row):")
        for p in result.orphan_files:
            try:
                size = p.stat().st_size
                lines.append(f"  {p.relative_to(result.root).as_posix()}  ({_fmt_size(size)})")
            except OSError:
                lines.append(f"  {p.relative_to(result.root).as_posix()}  (stat failed)")

    if result.ghost_rows:
        lines.append("")
        lines.append("Ghost rows (DB without FS file):")
        for r in result.ghost_rows:
            lines.append(
                f"  {r.id}  storage_key={r.storage_key}  "
                f"size_in_db={_fmt_size(r.size_bytes)}  filename={r.filename!r}"
            )

    if not result.has_mismatch:
        lines.append("")
        lines.append("✓ FS and DB are in sync.")
    return "\n".join(lines)


def main(root: Path | None = None) -> int:
    db = SessionLocal()
    try:
        result = audit(db, root)
    finally:
        db.close()
    print(render(result))
    return 2 if result.has_mismatch else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Override attachments ROOT (default: ./data/attachments).",
    )
    args = parser.parse_args()
    try:
        sys.exit(main(args.root))
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
