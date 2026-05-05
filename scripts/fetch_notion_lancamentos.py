"""Stub: fetch the Notion `DB IG Lançamentos` database into
`data/notion_lancamento_export.json`.

The actual fetch is performed by a Claude Code session via the Notion MCP
(`notion-fetch` / `notion-query-database-view` tools) and orchestrated by the
human operator. This script intentionally does not call the Notion API.

Workflow:

  1. Open a Claude Code session with the Notion MCP enabled.
  2. Ask Claude to fetch the database
     `collection://ecd12ddd-b7c3-4c7e-b140-15ccb0d916fc` ("DB IG Lançamentos")
     using the "Todos Lançamentos" view, dumping every row's mapped
     properties into the snapshot format documented in spec 07c.
     Iterate via multiple sort orders to cover the full row count.
  3. Save the result to `data/notion_lancamento_export.json`.
  4. Run `python scripts/import_notion_lancamentos.py --apply` to write the
     rows into the local DB.

Run this stub for a reminder of those steps. It exits non-zero so a CI/CD
pipeline can't accidentally treat "fetch was performed" as success when it
wasn't.
"""
from __future__ import annotations

import sys
from pathlib import Path
from textwrap import dedent

REPO_ROOT = Path(__file__).resolve().parent.parent
TARGET_JSON = REPO_ROOT / "data" / "notion_lancamento_export.json"


def main() -> int:
    print(dedent(
        f"""
        ─── Notion lançamento fetch is a manual / orchestrated step ─────────

        This script does not call the Notion API directly.

        To produce {TARGET_JSON.relative_to(REPO_ROOT)}:

          1. From a Claude Code session with the Notion MCP enabled, ask Claude
             to fetch the `DB IG Lançamentos` database
             (collection://ecd12ddd-b7c3-4c7e-b140-15ccb0d916fc) via the
             "Todos Lançamentos" view, mapping every page's properties into
             the snapshot format in specs/07c. Notion Lançamento Import.md.

          2. Save the result to:
             {TARGET_JSON}

          3. Run the import:
             python scripts/import_notion_lancamentos.py --dry-run    # preview
             python scripts/import_notion_lancamentos.py --apply      # commit

        The orchestrator must populate `errors[]` and `warnings[]` arrays in
        the JSON during the fetch step (see spec for codes).

        See specs/07c. Notion Lançamento Import.md for the full schema.
        ──────────────────────────────────────────────────────────────────────
        """
    ).strip())
    return 1


if __name__ == "__main__":
    sys.exit(main())
