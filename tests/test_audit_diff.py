"""Tests for the audit diff helper used by PUT endpoints (Spec 37)."""
from datetime import date
from decimal import Decimal
from enum import Enum

from numis_geek.utils.audit_diff import diff, snapshot


class Color(Enum):
    RED = "red"
    BLUE = "blue"


class _Box:
    """Tiny stand-in for an SQLA mapped object — `snapshot` reads via getattr."""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


def test_snapshot_serializes_decimal_date_enum():
    obj = _Box(
        amount=Decimal("12.34"),
        when=date(2026, 4, 15),
        color=Color.RED,
        notes="hi",
        missing=None,
    )
    out = snapshot(obj, ["amount", "when", "color", "notes", "missing", "absent"])
    serialized = {k: v[0] for k, v in out.items()}

    assert serialized == {
        "amount": "12.34",
        "when": "2026-04-15",
        "color": "red",
        "notes": "hi",
        "missing": None,
        "absent": None,
    }


def test_diff_decimal_compares_by_value_not_representation():
    """Decimal('20.00000000') and Decimal('20.0') are equal and should NOT appear in the diff."""
    before = snapshot(_Box(price=Decimal("20.00000000")), ["price"])
    after = snapshot(_Box(price=Decimal("20.0")), ["price"])
    assert diff(before, after) == {}


def test_diff_returns_only_changed_fields():
    before = snapshot(_Box(a=1, b="x", c=None, d="same"), ["a", "b", "c", "d"])
    after = snapshot(_Box(a=2, b="x", c="now", d="same"), ["a", "b", "c", "d"])

    result = diff(before, after)

    assert result == {
        "a": {"old": 1, "new": 2},
        "c": {"old": None, "new": "now"},
    }


def test_diff_empty_when_nothing_changes():
    snap = snapshot(_Box(a=1, b="x"), ["a", "b"])
    assert diff(snap, snap) == {}
