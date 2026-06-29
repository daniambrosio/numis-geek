from decimal import Decimal

import pytest

from numis_geek.models.target_allocation import (
    TargetAllocation,
    TargetAllocationDimension,
)
from numis_geek.models.workspace import Workspace
from numis_geek.services.target_allocation import (
    TargetAllocationError,
    TargetEntryIn,
    get_targets,
    upsert_targets,
    validate_entries,
)


def _mk_workspace(db, name="WS"):
    ws = Workspace(name=name)
    db.add(ws)
    db.flush()
    return ws


def _entries(*pairs):
    return [TargetEntryIn(key=k, target_pct=Decimal(str(v))) for k, v in pairs]


# ── validate_entries ──────────────────────────────────────────────────────────


def test_validate_class_happy():
    errs = validate_entries(
        _entries(("STOCK", "0.5"), ("REIT", "0.5")),
        TargetAllocationDimension.CLASS,
    )
    assert errs == []


def test_validate_class_invalid_key():
    errs = validate_entries(
        _entries(("BOGUS", "1.0")),
        TargetAllocationDimension.CLASS,
    )
    assert any("Invalid CLASS key" in e for e in errs)


def test_validate_country_happy():
    errs = validate_entries(
        _entries(("BR", "0.7"), ("US", "0.3")),
        TargetAllocationDimension.COUNTRY,
    )
    assert errs == []


def test_validate_country_invalid_iso2():
    errs = validate_entries(
        _entries(("BRA", "1.0")),
        TargetAllocationDimension.COUNTRY,
    )
    assert any("Invalid COUNTRY key" in e for e in errs)


def test_validate_sum_under_one():
    errs = validate_entries(
        _entries(("STOCK", "0.4"), ("REIT", "0.5")),
        TargetAllocationDimension.CLASS,
    )
    assert any("sum to 1.0" in e for e in errs)


def test_validate_sum_within_tolerance():
    # 0.4999 + 0.5001 = 1.0 exactly; tolerance permits small drift.
    errs = validate_entries(
        _entries(("STOCK", "0.4999"), ("REIT", "0.5001")),
        TargetAllocationDimension.CLASS,
    )
    assert errs == []


def test_validate_negative_pct():
    errs = validate_entries(
        _entries(("STOCK", "-0.1"), ("REIT", "1.1")),
        TargetAllocationDimension.CLASS,
    )
    assert any("Negative" in e for e in errs)


def test_validate_above_one_pct():
    errs = validate_entries(
        _entries(("STOCK", "1.5")),
        TargetAllocationDimension.CLASS,
    )
    assert any("must be ≤ 1.0" in e for e in errs)


def test_validate_duplicate_key():
    errs = validate_entries(
        _entries(("STOCK", "0.5"), ("STOCK", "0.5")),
        TargetAllocationDimension.CLASS,
    )
    assert any("Duplicate key" in e for e in errs)


# ── upsert_targets ────────────────────────────────────────────────────────────


def test_upsert_inserts_rows(db):
    ws = _mk_workspace(db)
    upsert_targets(
        db,
        ws.id,
        TargetAllocationDimension.CLASS,
        _entries(("STOCK", "0.6"), ("REIT", "0.4")),
        user_email="u@test",
        user_id=None,
    )
    rows = db.query(TargetAllocation).filter_by(workspace_id=ws.id).all()
    assert len(rows) == 2
    assert {r.key for r in rows} == {"STOCK", "REIT"}


def test_upsert_replaces_existing_dimension(db):
    ws = _mk_workspace(db, "WS-replace")
    upsert_targets(
        db, ws.id, TargetAllocationDimension.CLASS,
        _entries(("STOCK", "0.6"), ("REIT", "0.4")),
        user_email="u@test", user_id=None,
    )
    upsert_targets(
        db, ws.id, TargetAllocationDimension.CLASS,
        _entries(("ETF", "1.0")),
        user_email="u@test", user_id=None,
    )
    rows = db.query(TargetAllocation).filter_by(workspace_id=ws.id).all()
    assert len(rows) == 1
    assert rows[0].key == "ETF"


def test_upsert_dimensions_are_isolated(db):
    ws = _mk_workspace(db, "WS-iso")
    upsert_targets(
        db, ws.id, TargetAllocationDimension.CLASS,
        _entries(("STOCK", "1.0")),
        user_email="u@test", user_id=None,
    )
    upsert_targets(
        db, ws.id, TargetAllocationDimension.COUNTRY,
        _entries(("BR", "0.7"), ("US", "0.3")),
        user_email="u@test", user_id=None,
    )
    rows = db.query(TargetAllocation).filter_by(workspace_id=ws.id).all()
    assert len(rows) == 3
    # Re-write CLASS only — COUNTRY must remain intact.
    upsert_targets(
        db, ws.id, TargetAllocationDimension.CLASS,
        _entries(("REIT", "1.0")),
        user_email="u@test", user_id=None,
    )
    rows = db.query(TargetAllocation).filter_by(workspace_id=ws.id).all()
    assert len(rows) == 3
    keys = {(r.dimension.value, r.key) for r in rows}
    assert keys == {("CLASS", "REIT"), ("COUNTRY", "BR"), ("COUNTRY", "US")}


def test_upsert_raises_on_invalid(db):
    ws = _mk_workspace(db, "WS-invalid")
    with pytest.raises(TargetAllocationError) as exc:
        upsert_targets(
            db, ws.id, TargetAllocationDimension.CLASS,
            _entries(("STOCK", "0.5")),  # sums to 0.5, not 1
            user_email="u@test", user_id=None,
        )
    assert any("sum to 1.0" in e for e in exc.value.errors)


def test_upsert_normalizes_country_case(db):
    ws = _mk_workspace(db, "WS-norm")
    upsert_targets(
        db, ws.id, TargetAllocationDimension.COUNTRY,
        _entries(("br", "0.5"), ("us", "0.5")),
        user_email="u@test", user_id=None,
    )
    rows = db.query(TargetAllocation).filter_by(workspace_id=ws.id).all()
    assert {r.key for r in rows} == {"BR", "US"}


# ── get_targets ───────────────────────────────────────────────────────────────


def test_get_empty_workspace(db):
    ws = _mk_workspace(db, "WS-empty")
    out = get_targets(db, ws.id)
    assert out["CLASS"].entries == []
    assert out["COUNTRY"].entries == []
    assert out["CLASS"].is_valid is False
    assert out["COUNTRY"].is_valid is False


def test_get_returns_grouped_ordered(db):
    ws = _mk_workspace(db, "WS-grouped")
    upsert_targets(
        db, ws.id, TargetAllocationDimension.CLASS,
        _entries(("REIT", "0.4"), ("STOCK", "0.6")),
        user_email="u@test", user_id=None,
    )
    upsert_targets(
        db, ws.id, TargetAllocationDimension.COUNTRY,
        _entries(("US", "0.3"), ("BR", "0.7")),
        user_email="u@test", user_id=None,
    )
    out = get_targets(db, ws.id)
    assert [e.key for e in out["CLASS"].entries] == ["REIT", "STOCK"]
    assert [e.key for e in out["COUNTRY"].entries] == ["BR", "US"]
    assert out["CLASS"].is_valid is True
    assert out["COUNTRY"].is_valid is True
    assert out["CLASS"].total == Decimal("1.0000")
