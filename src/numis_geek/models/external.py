"""ExternalSource enum — identifies the system of record for an imported row.

Used on both `asset.external_source` and `lancamento.external_source`. The pair
`(external_source, external_id)` is the canonical cross-source identity for
a row imported from elsewhere (Notion page URL, B3 ticker history, broker note
number, …).

Extend this enum as new importers come online. Values are short, lowercase-ish
ALL_CAPS strings — they're persisted to disk so renaming them is a breaking
change.
"""
from __future__ import annotations

import enum


class ExternalSource(str, enum.Enum):
    NOTION = "NOTION"
    B3 = "B3"
    BROKER_NOTE = "BROKER_NOTE"
    MANUAL_CSV = "MANUAL_CSV"
