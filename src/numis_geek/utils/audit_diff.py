"""Helpers for building JSON diffs of changed fields for audit log entries.

Used by PUT endpoints (Spec 37 §7) so audit entries record `{field: {old, new}}`
only for fields that actually changed. Decimal/date/enum values are serialised
to strings so the resulting dict survives `json.dumps`.
"""
from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal
from typing import Any


def _serialize(value: Any) -> Any:
    """JSON-friendly form for storage in the audit log."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        # Strip trailing zeros so `20.00000000` and `20.0` print the same way.
        normalized = value.normalize()
        # Avoid scientific notation for small values (e.g. Decimal("0.10").normalize() → 0.1)
        return format(normalized, "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, enum.Enum):
        return value.value
    return value


def _comparable(value: Any) -> Any:
    """Form used for deciding whether two values are equal."""
    if isinstance(value, Decimal):
        # `Decimal("20.00") == Decimal("20.0")` is True — keep Decimals as
        # Decimals for the comparison.
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, enum.Enum):
        return value.value
    return value


def snapshot(obj: Any, fields: list[str]) -> dict[str, Any]:
    """Return a mapping `field → (serialized, comparable)` for `obj`.

    The serialized half is what gets persisted; the comparable half is what
    `diff()` uses to decide whether the field changed.
    """
    return {
        f: (_serialize(getattr(obj, f, None)), _comparable(getattr(obj, f, None)))
        for f in fields
    }


def diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return `{field: {old, new}}` for every field whose value differs.

    Inputs should come from `snapshot()` — entries are `(serialized, comparable)`
    tuples. The diff itself only contains the serialized halves so it survives
    `json.dumps`.
    """
    out: dict[str, dict[str, Any]] = {}
    for key in before.keys() | after.keys():
        old_entry = before.get(key, (None, None))
        new_entry = after.get(key, (None, None))
        old_ser, old_cmp = old_entry if isinstance(old_entry, tuple) else (old_entry, old_entry)
        new_ser, new_cmp = new_entry if isinstance(new_entry, tuple) else (new_entry, new_entry)
        if old_cmp != new_cmp:
            out[key] = {"old": old_ser, "new": new_ser}
    return out
