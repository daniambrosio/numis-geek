from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable

from sqlalchemy.orm import Session

from numis_geek.models.asset import AssetClass
from numis_geek.models.target_allocation import (
    TargetAllocation,
    TargetAllocationDimension,
)
from numis_geek.services.audit import AuditService


SUM_TOLERANCE = Decimal("0.0001")
ALLOWED_CLASS_KEYS: set[str] = {c.value for c in AssetClass}
ISO2_LEN = 2


@dataclass(frozen=True)
class TargetEntryIn:
    key: str
    target_pct: Decimal


@dataclass(frozen=True)
class TargetEntryOut:
    key: str
    target_pct: Decimal


@dataclass(frozen=True)
class DimensionOut:
    dimension: TargetAllocationDimension
    entries: list[TargetEntryOut]
    total: Decimal
    is_valid: bool


class TargetAllocationError(ValueError):
    """Raised when payload fails validation. Carries a list[str] of issues."""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def _norm_country_key(key: str) -> str:
    return key.strip().upper()


def _norm_class_key(key: str) -> str:
    return key.strip().upper()


def validate_entries(
    entries: Iterable[TargetEntryIn], dimension: TargetAllocationDimension
) -> list[str]:
    errors: list[str] = []
    seen_keys: set[str] = set()
    total = Decimal("0")

    for e in entries:
        norm_key = (
            _norm_class_key(e.key)
            if dimension == TargetAllocationDimension.CLASS
            else _norm_country_key(e.key)
        )
        if not norm_key:
            errors.append("Empty key not allowed.")
            continue
        if norm_key in seen_keys:
            errors.append(f"Duplicate key: {norm_key}.")
            continue
        seen_keys.add(norm_key)

        if dimension == TargetAllocationDimension.CLASS:
            if norm_key not in ALLOWED_CLASS_KEYS:
                errors.append(f"Invalid CLASS key: {norm_key}.")
        else:
            if len(norm_key) != ISO2_LEN or not norm_key.isalpha():
                errors.append(f"Invalid COUNTRY key (must be ISO-2): {norm_key}.")

        if e.target_pct is None:
            errors.append(f"Missing target_pct for {norm_key}.")
            continue
        if e.target_pct < 0:
            errors.append(f"Negative target_pct for {norm_key}.")
            continue
        if e.target_pct > 1:
            errors.append(f"target_pct must be ≤ 1.0 (got {e.target_pct} for {norm_key}).")
            continue
        total += e.target_pct

    if not errors:
        diff = (total - Decimal("1")).copy_abs()
        if diff > SUM_TOLERANCE:
            errors.append(
                f"Targets must sum to 1.0 (got {total.quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)})."
            )

    return errors


def get_targets(db: Session, workspace_id: str) -> dict[str, DimensionOut]:
    rows = (
        db.query(TargetAllocation)
        .filter(TargetAllocation.workspace_id == workspace_id)
        .order_by(TargetAllocation.dimension, TargetAllocation.key)
        .all()
    )
    by_dim: dict[TargetAllocationDimension, list[TargetEntryOut]] = {
        TargetAllocationDimension.CLASS: [],
        TargetAllocationDimension.COUNTRY: [],
    }
    for r in rows:
        by_dim[r.dimension].append(TargetEntryOut(key=r.key, target_pct=r.target_pct))

    out: dict[str, DimensionOut] = {}
    for dim, entries in by_dim.items():
        total = sum((e.target_pct for e in entries), Decimal("0"))
        is_valid = bool(entries) and (total - Decimal("1")).copy_abs() <= SUM_TOLERANCE
        out[dim.value] = DimensionOut(
            dimension=dim, entries=entries, total=total, is_valid=is_valid
        )
    return out


def upsert_targets(
    db: Session,
    workspace_id: str,
    dimension: TargetAllocationDimension,
    entries: list[TargetEntryIn],
    *,
    user_email: str,
    user_id: str | None,
) -> list[TargetEntryOut]:
    """Replace all entries of the given dimension for the workspace.

    Validates first; on success deletes old rows and inserts new ones.
    Writes an audit_log entry. Caller commits.
    """
    errors = validate_entries(entries, dimension)
    if errors:
        raise TargetAllocationError(errors)

    normalize = (
        _norm_class_key
        if dimension == TargetAllocationDimension.CLASS
        else _norm_country_key
    )

    db.query(TargetAllocation).filter(
        TargetAllocation.workspace_id == workspace_id,
        TargetAllocation.dimension == dimension,
    ).delete(synchronize_session=False)

    inserted: list[TargetEntryOut] = []
    for e in entries:
        norm_key = normalize(e.key)
        row = TargetAllocation(
            workspace_id=workspace_id,
            dimension=dimension,
            key=norm_key,
            target_pct=e.target_pct,
            created_by=user_id,
            updated_by=user_id,
        )
        db.add(row)
        inserted.append(TargetEntryOut(key=norm_key, target_pct=e.target_pct))

    db.flush()

    AuditService(db).log(
        user_email=user_email,
        action="target_allocation.update",
        workspace_id=workspace_id,
        user_id=user_id,
        resource_type="target_allocation",
        resource_id=None,
        details={
            "dimension": dimension.value,
            "entries": [{"key": e.key, "pct": float(e.target_pct)} for e in inserted],
        },
    )
    return inserted
