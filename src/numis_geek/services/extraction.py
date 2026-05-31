"""Spec 38 — orchestrates LLM extraction jobs.

Three public entrypoints:

- `create_and_run` — builds a job and runs the LLM call inline (sync mode).
- `confirm_extraction` — applies the extracted (or user-edited) payload to
  the domain model and marks the source pendency resolved.
- `reject_extraction` — records a manual rejection.

V1 ships **sync** extraction (no background worker). Files are small
enough that a 10-30s POST is fine. Move to async + APScheduler when
batch uploads become a thing.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from numis_geek.models.account import Account
from numis_geek.models.asset import Asset
from numis_geek.models.attachment import Attachment, AttachmentKind
from numis_geek.models.audit_log import AuditLog  # noqa: F401  (used implicitly via AuditService)
from numis_geek.models.extraction_job import (
    ExtractionJob, ExtractionSourceHint, ExtractionStatus,
)
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.portfolio_snapshot import (
    PortfolioSnapshot, SnapshotPendency, SnapshotStatus,
)
from numis_geek.models.user import User
from numis_geek.services import attachment_storage
from numis_geek.services.audit import AuditService
from numis_geek.services.extraction_templates import Template, template_for
from numis_geek.integrations.llm import (
    DEFAULT_MODEL, LLMClient, get_llm_client, parse_json_block,
)


# ── data classes ─────────────────────────────────────────────────────────────

@dataclass
class BulkApplyDetail:
    """Spec 48 — categorized result of bulk extract apply.

    Each entry is a plain dict so the route layer can serialize via Pydantic
    without re-mapping field names.
    """
    applied: list[dict]              # matched + pendency resolved
    matched_no_pendency: list[dict]  # asset exists but no open pendency in snapshot
    orphan: list[dict]               # extract line had no matching asset
    pendency_not_in_extract: list[dict]  # snapshot pendency the extract didn't cover


@dataclass
class ExtractionApplyResult:
    applied_count: int
    skipped_count: int
    errors: list[str]
    bulk_detail: BulkApplyDetail | None = None


class ExtractionError(Exception):
    pass


# ── create + run (sync) ──────────────────────────────────────────────────────

def create_and_run(
    db: Session,
    *,
    workspace_id: str,
    attachment_id: str,
    source_hint: ExtractionSourceHint,
    pendency_id: str | None = None,
    snapshot_id: str | None = None,
    asset_id: str | None = None,
    user_id: str | None = None,
    user_email: str | None = None,
) -> ExtractionJob:
    """Create an ExtractionJob and run the LLM inline (Spec 38 V1 sync mode)."""
    attachment = db.get(Attachment, attachment_id)
    if attachment is None or not attachment.is_active:
        raise ExtractionError(f"Attachment {attachment_id} not found")
    if attachment.workspace_id != workspace_id:
        raise ExtractionError("Attachment workspace mismatch")

    job = ExtractionJob(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        snapshot_id=snapshot_id,
        pendency_id=pendency_id,
        asset_id=asset_id,
        attachment_id=attachment_id,
        source_hint=source_hint,
        status=ExtractionStatus.PENDING,
        created_at=datetime.now(timezone.utc),
    )
    db.add(job)
    db.flush()

    if user_id or user_email:
        AuditService(db).log(
            user_email=user_email or "system",
            action="extraction.created",
            workspace_id=workspace_id,
            user_id=user_id,
            resource_type="extraction_job",
            resource_id=job.id,
            details={
                "attachment_id": attachment_id,
                "source_hint": source_hint.value,
                "pendency_id": pendency_id,
            },
        )

    run_extraction(db, job_id=job.id)
    return db.get(ExtractionJob, job.id)


def run_extraction(db: Session, *, job_id: str) -> ExtractionJob:
    """Read the attachment, call the LLM, validate the JSON, persist."""
    job = db.get(ExtractionJob, job_id)
    if job is None:
        raise ExtractionError(f"ExtractionJob {job_id} not found")
    if job.status not in (ExtractionStatus.PENDING, ExtractionStatus.FAILED):
        raise ExtractionError(
            f"Cannot run job in status {job.status.value}",
        )

    attachment = db.get(Attachment, job.attachment_id)
    if attachment is None:
        job.status = ExtractionStatus.FAILED
        job.error_message = "Attachment row vanished"
        db.flush()
        return job

    template: Template = template_for(job.source_hint)
    job.status = ExtractionStatus.RUNNING
    job.started_at = datetime.now(timezone.utc)
    job.prompt_version = template.version
    db.flush()

    try:
        client: LLMClient = get_llm_client(db)
        payload = _read_attachment_payload(attachment)
        call = client.call(
            system=template.system,
            user_text=_user_message(template, payload),
            image_bytes=payload.image_bytes,
            image_mime=payload.image_mime,
            model=DEFAULT_MODEL,
        )
        parsed_obj = parse_json_block(call.text)
        validated = template.output_model.model_validate(parsed_obj)

        job.extracted_json = validated.model_dump()
        job.model = call.model
        job.input_tokens = call.input_tokens
        job.output_tokens = call.output_tokens
        job.cost_usd = call.cost_usd()
        job.confidence = _overall_confidence(parsed_obj)
        job.status = ExtractionStatus.EXTRACTED
        job.completed_at = datetime.now(timezone.utc)
        job.error_message = None
    except (ValidationError, ValueError, json.JSONDecodeError) as exc:
        job.status = ExtractionStatus.FAILED
        job.error_message = f"Parse/validate: {exc}"
        job.completed_at = datetime.now(timezone.utc)
    except Exception as exc:  # pragma: no cover - generic backstop
        job.status = ExtractionStatus.FAILED
        job.error_message = str(exc)
        job.completed_at = datetime.now(timezone.utc)

    db.flush()
    return job


@dataclass
class _Payload:
    text: str | None
    image_bytes: bytes | None
    image_mime: str | None


def _read_attachment_payload(attachment: Attachment) -> _Payload:
    """Convert the on-disk attachment into LLM input (image bytes OR text)."""
    path = attachment_storage.absolute_path_for(attachment)
    blob = Path(path).read_bytes()
    if attachment.kind == AttachmentKind.IMAGE:
        return _Payload(text=None, image_bytes=blob, image_mime=attachment.mime_type)
    if attachment.kind == AttachmentKind.CSV:
        return _Payload(text=blob.decode("utf-8", errors="replace"), image_bytes=None, image_mime=None)
    # PDF and others — try utf-8 first, else send as base64 image-fallback.
    # V1 simplification: pass the raw bytes as the prompt for non-image
    # attachments. Real PDF-to-image conversion (pypdfium / pdf2image) is a
    # future improvement.
    try:
        return _Payload(text=blob.decode("utf-8"), image_bytes=None, image_mime=None)
    except UnicodeDecodeError:
        return _Payload(text=None, image_bytes=blob, image_mime=attachment.mime_type)


def _user_message(template: Template, payload: _Payload) -> str:
    parts = [template.user_prefix]
    if payload.text:
        parts.append("\n\n----\n")
        parts.append(payload.text[:50_000])  # safety cap
    return "".join(parts)


def _overall_confidence(parsed: Any) -> Decimal | None:
    if isinstance(parsed, dict):
        if "confidence" in parsed and isinstance(parsed["confidence"], (int, float)):
            return Decimal(str(parsed["confidence"])).quantize(Decimal("0.01"))
        # For list-based hints, average the per-row confidence.
        for list_key in ("positions", "events", "trades"):
            items = parsed.get(list_key)
            if isinstance(items, list) and items:
                values = [
                    float(it.get("confidence"))
                    for it in items
                    if isinstance(it, dict) and isinstance(it.get("confidence"), (int, float))
                ]
                if values:
                    avg = sum(values) / len(values)
                    return Decimal(str(round(avg, 2)))
    return None


# ── confirm / reject ─────────────────────────────────────────────────────────

def confirm_extraction(
    db: Session,
    *,
    job_id: str,
    user_id: str | None,
    user_email: str | None = None,
    edited_payload: dict | None = None,
    institution_short_name: str | None = None,
) -> ExtractionApplyResult:
    """Apply the (possibly edited) extracted JSON to the domain model.

    Always resolves the linked SnapshotPendency (if any). When the job is
    bulk-scoped (snapshot_id set, pendency_id None), dispatches to the bulk
    applier which resolves N pendencies. `institution_short_name`, when set,
    restricts the bulk matching to assets of that FI (Spec 48 §1.3).
    """
    job = db.get(ExtractionJob, job_id)
    if job is None:
        raise ExtractionError(f"ExtractionJob {job_id} not found")
    if job.status != ExtractionStatus.EXTRACTED:
        raise ExtractionError(
            f"Job must be in EXTRACTED state (currently {job.status.value})",
        )

    payload = edited_payload if edited_payload is not None else job.extracted_json
    if payload is None:
        raise ExtractionError("No extracted JSON to apply")

    result = _apply_payload(
        db, job, payload,
        user_id=user_id, user_email=user_email,
        institution_short_name=institution_short_name,
    )

    job.user_edits = edited_payload if edited_payload is not None else None
    job.status = ExtractionStatus.CONFIRMED
    job.confirmed_at = datetime.now(timezone.utc)
    job.confirmed_by = user_id
    db.flush()

    # Resolve the linked pendency (lazy import to avoid circular module).
    if job.pendency_id:
        from numis_geek.services import snapshot as snapshot_service
        try:
            snapshot_service.resolve_pendency(
                db,
                pendency_id=job.pendency_id,
                user_id=user_id,
                user_email=user_email,
                note=f"Extraído via LLM (job {job.id})",
            )
        except ValueError:
            # Pendency might have been deleted between extraction and confirm.
            result.errors.append(f"pendency {job.pendency_id} not found")

    AuditService(db).log(
        user_email=user_email or "system",
        action="extraction.confirmed",
        workspace_id=job.workspace_id,
        user_id=user_id,
        resource_type="extraction_job",
        resource_id=job.id,
        details={
            "applied": result.applied_count,
            "skipped": result.skipped_count,
            "errors": result.errors,
            "pendency_id": job.pendency_id,
            "institution_short_name": institution_short_name,
        },
    )
    return result


def reject_extraction(
    db: Session,
    *,
    job_id: str,
    user_id: str | None,
    user_email: str | None = None,
    reason: str | None = None,
) -> ExtractionJob:
    job = db.get(ExtractionJob, job_id)
    if job is None:
        raise ExtractionError(f"ExtractionJob {job_id} not found")
    job.status = ExtractionStatus.REJECTED
    job.error_message = reason
    job.confirmed_at = datetime.now(timezone.utc)
    job.confirmed_by = user_id
    db.flush()
    AuditService(db).log(
        user_email=user_email or "system",
        action="extraction.rejected",
        workspace_id=job.workspace_id,
        user_id=user_id,
        resource_type="extraction_job",
        resource_id=job.id,
        details={"reason": reason},
    )
    return job


# ── apply per hint ───────────────────────────────────────────────────────────

def _apply_payload(
    db: Session,
    job: ExtractionJob,
    payload: dict,
    *,
    user_id: str | None,
    user_email: str | None,
    institution_short_name: str | None = None,
) -> ExtractionApplyResult:
    hint = job.source_hint
    # Spec 48 — bulk path: BROKER_POSITION + snapshot scope + no specific
    # pendency → resolve N pendencies in the snapshot.
    if (
        hint == ExtractionSourceHint.BROKER_POSITION
        and job.snapshot_id
        and not job.pendency_id
    ):
        return _apply_bulk_to_snapshot(
            db, job, payload,
            user_id=user_id, user_email=user_email,
            institution_short_name=institution_short_name,
        )
    if hint == ExtractionSourceHint.SCREENSHOT_PRICE:
        return _apply_screenshot_price(db, job, payload, user_id=user_id)
    if hint == ExtractionSourceHint.BROKER_POSITION:
        return _apply_broker_position(db, job, payload, user_id=user_id)
    # Other hints are scaffold-only in V1.
    return ExtractionApplyResult(
        applied_count=0, skipped_count=0,
        errors=[f"applying hint {hint.value} not yet implemented in V1"],
    )


def _apply_screenshot_price(
    db: Session, job: ExtractionJob, payload: dict, *, user_id: str | None,
) -> ExtractionApplyResult:
    """SCREENSHOT_PRICE → update Asset.current_price for the matching ticker
    in the same workspace. If the pendency carries an asset_id, prefer that
    over the LLM's `ticker` (the user uploaded the screenshot _for_ that
    asset)."""
    target_asset: Asset | None = None
    pendency = db.get(SnapshotPendency, job.pendency_id) if job.pendency_id else None
    if pendency:
        target_asset = db.get(Asset, pendency.asset_id)
    elif job.asset_id:
        target_asset = db.get(Asset, job.asset_id)
    else:
        ticker = payload.get("ticker")
        if ticker:
            target_asset = (
                db.query(Asset)
                .filter(
                    Asset.workspace_id == job.workspace_id,
                    Asset.ticker == ticker,
                )
                .first()
            )

    if target_asset is None:
        return ExtractionApplyResult(
            applied_count=0, skipped_count=1,
            errors=[
                f"no Asset matches ticker={payload.get('ticker')!r} in workspace",
            ],
        )

    price = payload.get("price")
    if price is None:
        return ExtractionApplyResult(
            applied_count=0, skipped_count=1, errors=["missing price"],
        )

    target_asset.current_price = Decimal(str(price))
    target_asset.price_updated_at = datetime.now(timezone.utc)
    db.flush()
    return ExtractionApplyResult(applied_count=1, skipped_count=0, errors=[])


def _apply_broker_position(
    db: Session, job: ExtractionJob, payload: dict, *, user_id: str | None,
) -> ExtractionApplyResult:
    """BROKER_POSITION → update Asset.current_price for each line we can
    resolve to a workspace asset. Unmatched lines are reported."""
    positions = payload.get("positions") or []
    applied = 0
    skipped = 0
    errors: list[str] = []
    now = datetime.now(timezone.utc)
    for pos in positions:
        ticker = pos.get("ticker_normalized") or pos.get("ticker_raw")
        if not ticker:
            skipped += 1
            errors.append("position with no ticker")
            continue
        asset = (
            db.query(Asset)
            .filter(
                Asset.workspace_id == job.workspace_id,
                Asset.ticker == ticker,
            )
            .first()
        )
        if asset is None:
            skipped += 1
            errors.append(f"ticker {ticker!r} not found")
            continue
        price = pos.get("unit_price")
        if price is None:
            skipped += 1
            continue
        asset.current_price = Decimal(str(price))
        asset.price_updated_at = now
        applied += 1
    db.flush()
    return ExtractionApplyResult(
        applied_count=applied, skipped_count=skipped, errors=errors,
    )


# ── Spec 48 — bulk apply to a snapshot ──────────────────────────────────────


def _institution_short_name_for_asset(db: Session, asset: Asset) -> str | None:
    if not asset.account_id:
        return None
    acc = db.get(Account, asset.account_id)
    if acc is None or not acc.financial_institution_id:
        return None
    fi = db.get(FinancialInstitution, acc.financial_institution_id)
    return fi.short_name if fi else None


def _apply_bulk_to_snapshot(
    db: Session, job: ExtractionJob, payload: dict,
    *,
    user_id: str | None,
    user_email: str | None,
    institution_short_name: str | None = None,
) -> ExtractionApplyResult:
    """Bulk path (Spec 48): match positions[] by ticker to open pendencies
    in the snapshot. Each match calls resolve_pendency (which updates
    Asset.current_price + PortfolioSnapshotItem + recomputes totals) with
    the bulk attachment as the resolution attachment.

    Returns three categorized lists in BulkApplyDetail so the UI can render
    a 3-section review/result panel without re-querying.
    """
    snap = db.get(PortfolioSnapshot, job.snapshot_id)
    if snap is None:
        return ExtractionApplyResult(
            applied_count=0, skipped_count=0,
            errors=[f"snapshot {job.snapshot_id} not found"],
            bulk_detail=BulkApplyDetail(
                applied=[], matched_no_pendency=[], orphan=[],
                pendency_not_in_extract=[],
            ),
        )

    open_pendencies = (
        db.query(SnapshotPendency)
        .filter(
            SnapshotPendency.snapshot_id == snap.id,
            SnapshotPendency.resolved_at.is_(None),
        )
        .all()
    )
    pendency_by_asset = {p.asset_id: p for p in open_pendencies}

    positions = payload.get("positions") or []
    applied_list: list[dict] = []
    matched_no_pendency: list[dict] = []
    orphan: list[dict] = []
    matched_asset_ids: set[str] = set()
    errors: list[str] = []

    # Lazy import to avoid circular: services.snapshot imports models that
    # touch extraction in tests.
    from numis_geek.services import snapshot as snapshot_service

    for pos in positions:
        ticker = pos.get("ticker_normalized") or pos.get("ticker_raw")
        unit_price_raw = pos.get("unit_price")
        if not ticker:
            errors.append("position with no ticker")
            continue
        asset = (
            db.query(Asset)
            .filter(
                Asset.workspace_id == job.workspace_id,
                Asset.ticker == ticker,
            )
            .first()
        )
        if asset is None:
            orphan.append({
                "ticker": ticker,
                "unit_price": str(unit_price_raw) if unit_price_raw is not None else None,
            })
            continue

        asset_fi = _institution_short_name_for_asset(db, asset)
        if institution_short_name and asset_fi != institution_short_name:
            # Asset belongs to a different FI than the user scoped to.
            # Skip silently — neither matched_no_pendency nor orphan; the
            # extract just doesn't apply here.
            continue

        matched_asset_ids.add(asset.id)
        pendency = pendency_by_asset.get(asset.id)
        if pendency is None:
            matched_no_pendency.append({
                "asset_id": asset.id,
                "ticker": ticker,
                "asset_name": asset.name,
                "institution_short_name": asset_fi,
                "unit_price": str(unit_price_raw) if unit_price_raw is not None else None,
            })
            continue
        if unit_price_raw is None:
            errors.append(f"ticker {ticker!r} has no unit_price in extract")
            continue

        previous_price = asset.current_price
        new_price = Decimal(str(unit_price_raw))
        note = (
            f"bulk extract (job {job.id})"
            + (f" · FI={institution_short_name}" if institution_short_name else "")
        )
        try:
            snapshot_service.resolve_pendency(
                db,
                pendency_id=pendency.id,
                user_id=user_id,
                user_email=user_email,
                new_price=new_price,
                file_id=job.attachment_id,
                note=note,
            )
        except ValueError as e:
            errors.append(f"pendency {pendency.id}: {e}")
            continue
        applied_list.append({
            "pendency_id": pendency.id,
            "asset_id": asset.id,
            "ticker": ticker,
            "asset_name": asset.name,
            "institution_short_name": asset_fi,
            "new_price": str(new_price),
            "previous_price": str(previous_price) if previous_price is not None else None,
        })

    # Pendencies still open after this pass — scoped to the FI when set.
    not_in_extract: list[dict] = []
    for p in open_pendencies:
        if p.asset_id in matched_asset_ids:
            continue
        asset = db.get(Asset, p.asset_id)
        if asset is None:
            continue
        asset_fi = _institution_short_name_for_asset(db, asset)
        if institution_short_name and asset_fi != institution_short_name:
            continue
        not_in_extract.append({
            "pendency_id": p.id,
            "asset_id": asset.id,
            "ticker": asset.ticker,
            "asset_name": asset.name,
            "institution_short_name": asset_fi,
        })

    db.flush()
    return ExtractionApplyResult(
        applied_count=len(applied_list),
        skipped_count=len(orphan) + len(matched_no_pendency),
        errors=errors,
        bulk_detail=BulkApplyDetail(
            applied=applied_list,
            matched_no_pendency=matched_no_pendency,
            orphan=orphan,
            pendency_not_in_extract=not_in_extract,
        ),
    )
