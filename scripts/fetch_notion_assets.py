"""Stub: fetch the Notion `DB IG Ativos` database into data/notion_export.json.

The actual fetch is performed by a Claude Code session via the Notion MCP
(`notion-fetch` / `notion-query-database-view` tools) and orchestrated by the
human operator. This script intentionally does not call the Notion API.

Workflow:

  1. Open a Claude Code session with the Notion MCP enabled.
  2. Ask Claude to fetch the database
     `collection://b9a053d1-064b-4ef0-985a-1d3482799462` and dump every page's
     mapped properties into the snapshot format documented in
     `specs/07a. Notion Asset Import.md`.
  3. Save the result to `data/notion_export.json`.
  4. Run `python scripts/import_notion_assets.py --apply` to write the rows
     into the local DB.

Run this stub for a reminder of those steps. It exits non-zero so a CI/CD
pipeline can't accidentally treat "fetch was performed" as success when it
wasn't.
"""
from __future__ import annotations

import sys
from pathlib import Path
from textwrap import dedent

REPO_ROOT = Path(__file__).resolve().parent.parent
TARGET_JSON = REPO_ROOT / "data" / "notion_export.json"


def main() -> int:
    print(dedent(
        f"""
        ─── Notion asset fetch is a manual / orchestrated step ───────────────

        This script does not call the Notion API directly.

        To produce {TARGET_JSON.relative_to(REPO_ROOT)}:

          1. From a Claude Code session with the Notion MCP enabled, ask Claude
             to fetch the `DB IG Ativos` database
             (collection://b9a053d1-064b-4ef0-985a-1d3482799462) and dump every
             row's mapped properties into the snapshot format documented in
             specs/07a. Notion Asset Import.md.

          2. Save the result to:
             {TARGET_JSON}

          3. Run the import:
             python scripts/import_notion_assets.py --dry-run    # preview
             python scripts/import_notion_assets.py --apply      # commit

        See specs/07a. Notion Asset Import.md for the JSON schema.
        ──────────────────────────────────────────────────────────────────────
        """
    ).strip())
    return 1


if __name__ == "__main__":
    sys.exit(main())
