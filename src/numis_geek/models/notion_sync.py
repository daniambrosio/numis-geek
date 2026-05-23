"""NotionSyncStatus — used by every entity that gets pushed to Notion.

PENDING — entity was created/updated locally and needs a push
SYNCED  — last push succeeded; `notion_last_synced_at` and
          `notion_remote_last_edited_at` are populated
CONFLICT — last sync attempt detected that the remote page changed since the
          last successful push; UI must prompt user before sobrescrever
ERROR   — last sync raised; `notion_sync_error` has the message
"""
from __future__ import annotations

import enum


class NotionSyncStatus(str, enum.Enum):
    PENDING = "PENDING"
    SYNCED = "SYNCED"
    CONFLICT = "CONFLICT"
    ERROR = "ERROR"
