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
import re
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func
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
    PortfolioSnapshot, PortfolioSnapshotItem, SnapshotPendency, SnapshotStatus,
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

    For PREVIEW (read-only): `applied` becomes the prospective list — same
    shape, but `new_price`/`previous_price` reflect what WOULD happen.
    """
    applied: list[dict]              # matched + pendency (resolved for apply, prospective for preview)
    matched_no_pendency: list[dict]  # asset exists but no open pendency in snapshot
    orphan: list[dict]               # extract line had no matching asset
    pendency_not_in_extract: list[dict]  # snapshot pendency the extract didn't cover
    # Spec 57 follow-up — asset matched but price_source is automated
    # (BRAPI/FINNHUB/...); extract is ignored. UI shows this so the user
    # knows the line was recognized but no action is needed.
    auto_skipped: list[dict] = None  # populated only by preview/apply paths that classify

    def __post_init__(self):
        if self.auto_skipped is None:
            self.auto_skipped = []


@dataclass
class ExtractionApplyResult:
    applied_count: int
    skipped_count: int
    errors: list[str]
    bulk_detail: BulkApplyDetail | None = None


class ExtractionError(Exception):
    pass


# ── disambiguator ────────────────────────────────────────────────────────────

# Datas no notes vêm em três formatos vistos em extratos: DD/MM/YYYY,
# YYYY-MM-DD, MM/YYYY. Captura o mais específico que encontrar.
_DATE_PATTERNS = (
    re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"),       # 2034-08-16
    re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b"),       # 16/08/2034
    re.compile(r"\b(\d{2})/(\d{4})\b"),               # 08/2034
)


def _maturity_from_notes(notes: str | None) -> str | None:
    """Return an ISO-ish maturity tag (`2034-08-16` or `2034-08`) extracted
    from the free-text notes, or None if no date pattern matches."""
    if not notes:
        return None
    text = notes
    if m := _DATE_PATTERNS[0].search(text):
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    if m := _DATE_PATTERNS[1].search(text):
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    if m := _DATE_PATTERNS[2].search(text):
        return f"{m.group(2)}-{m.group(1)}"
    return None


def _disambiguate_duplicate_tickers(validated: Any) -> None:
    """Spec 57 defensive layer: when two positions returned by the LLM share
    a ticker_raw (e.g. 10x 'United States of America' for distinct
    Treasury maturities), append the maturity extracted from `notes` to
    make each ticker_raw unique. Mutates `validated.positions` in place.

    Safe no-op when:
    - the output model has no `positions` attribute (other source_hints)
    - all ticker_raws are already unique
    - duplicate has no `notes` to mine a date from (left as-is; downstream
      still flags it as orphan, but at least the user sees ONE per row)
    """
    positions = getattr(validated, "positions", None)
    if not positions:
        return
    counts = Counter(p.ticker_raw for p in positions if p.ticker_raw)
    dups = {t for t, n in counts.items() if n > 1}
    if not dups:
        return
    seen: set[str] = set(t for t in counts if t not in dups)
    for pos in positions:
        if pos.ticker_raw not in dups:
            continue
        maturity = _maturity_from_notes(getattr(pos, "notes", None))
        if not maturity:
            continue
        new_raw = f"{pos.ticker_raw} {maturity}"
        # Bump suffix if a date collision still occurs (rare).
        suffix = 2
        candidate = new_raw
        while candidate in seen:
            candidate = f"{new_raw} #{suffix}"
            suffix += 1
        pos.ticker_raw = candidate
        seen.add(candidate)


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
            image_parts=payload.image_parts,
            model=DEFAULT_MODEL,
        )
        parsed_obj = parse_json_block(call.text)
        validated = template.output_model.model_validate(parsed_obj)
        _disambiguate_duplicate_tickers(validated)

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
    image_parts: list[tuple[bytes, str | None]] | None = None


_ANTHROPIC_IMAGE_MAX_DIM = 8000  # Anthropic's hard limit on either side.


def _split_image_for_anthropic(
    blob: bytes, mime_type: str | None,
) -> list[tuple[bytes, str | None]]:
    """Return a list of (bytes, mime) tiles that all fit Anthropic's bounds.

    For images within the 8000×8000 limit, returns `[(blob, mime)]` unchanged.
    For taller / wider stitched screenshots we slice into tiles (vertical
    strips first, then horizontal if needed). Resolution is preserved — no
    downscale — so small text remains legible to Claude. Tiles are emitted
    as JPEG quality 92 to keep payload under Anthropic's 5MB/image cap.

    Falls back to `[(blob, mime)]` when Pillow isn't installed; the API
    will reject oversize blobs in that case, surfaced as a clear error.
    """
    try:
        from io import BytesIO
        from PIL import Image
    except ImportError:
        return [(blob, mime_type)]
    try:
        img = Image.open(BytesIO(blob))
        w, h = img.size
        if w <= _ANTHROPIC_IMAGE_MAX_DIM and h <= _ANTHROPIC_IMAGE_MAX_DIM:
            return [(blob, mime_type)]
        img = img.convert("RGB") if img.mode in ("RGBA", "P", "LA") else img
        cols = (w + _ANTHROPIC_IMAGE_MAX_DIM - 1) // _ANTHROPIC_IMAGE_MAX_DIM
        rows = (h + _ANTHROPIC_IMAGE_MAX_DIM - 1) // _ANTHROPIC_IMAGE_MAX_DIM
        tiles: list[tuple[bytes, str | None]] = []
        for row in range(rows):
            for col in range(cols):
                left = col * _ANTHROPIC_IMAGE_MAX_DIM
                upper = row * _ANTHROPIC_IMAGE_MAX_DIM
                right = min(left + _ANTHROPIC_IMAGE_MAX_DIM, w)
                lower = min(upper + _ANTHROPIC_IMAGE_MAX_DIM, h)
                buf = BytesIO()
                img.crop((left, upper, right, lower)).save(buf, format="JPEG", quality=92)
                tiles.append((buf.getvalue(), "image/jpeg"))
        return tiles
    except Exception:
        return [(blob, mime_type)]


_XLSX_MIMES = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
)


def _xlsx_to_csv_text(blob: bytes) -> str | None:
    """Convert an Excel workbook to a CSV-like textual representation that
    Claude can read. Returns None when openpyxl isn't installed or the
    workbook can't be parsed — caller falls back to raw bytes."""
    try:
        from io import BytesIO
        import csv as _csv
        from openpyxl import load_workbook
    except ImportError:
        return None
    try:
        wb = load_workbook(BytesIO(blob), read_only=True, data_only=True)
    except Exception:
        return None
    parts: list[str] = []
    for ws in wb.worksheets:
        parts.append(f"# Sheet: {ws.title}")
        from io import StringIO
        out = StringIO()
        writer = _csv.writer(out)
        for row in ws.iter_rows(values_only=True):
            if all(v is None for v in row):
                continue
            writer.writerow([("" if v is None else str(v)) for v in row])
        parts.append(out.getvalue().rstrip())
    return "\n\n".join(parts)


def _read_attachment_payload(attachment: Attachment) -> _Payload:
    """Convert the on-disk attachment into LLM input (image tiles OR text)."""
    path = attachment_storage.absolute_path_for(attachment)
    blob = Path(path).read_bytes()
    if attachment.kind == AttachmentKind.IMAGE:
        parts = _split_image_for_anthropic(blob, attachment.mime_type)
        return _Payload(
            text=None,
            image_bytes=parts[0][0] if parts else None,
            image_mime=parts[0][1] if parts else None,
            image_parts=parts,
        )
    if attachment.mime_type in _XLSX_MIMES:
        text = _xlsx_to_csv_text(blob)
        if text is not None:
            return _Payload(text=text, image_bytes=None, image_mime=None)
        # Fallback: bytes (Anthropic will likely fail, but at least we tried).
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
    if payload.image_parts and len(payload.image_parts) > 1:
        parts.append(
            f"\n\nNOTA: a imagem original excedia o limite de 8000px, então "
            f"está dividida em {len(payload.image_parts)} fatias sequenciais "
            f"(top-to-bottom, left-to-right). Leia todas como uma única "
            f"captura contínua antes de extrair os dados.",
        )
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
    manual_mappings: dict[str, str] | None = None,
    manual_prices: dict[str, float] | None = None,
    manual_modes: dict[str, str] | None = None,
) -> ExtractionApplyResult:
    """Apply the (possibly edited) extracted JSON to the domain model.

    Always resolves the linked SnapshotPendency (if any). When the job is
    bulk-scoped (snapshot_id set, pendency_id None), dispatches to the bulk
    applier which resolves N pendencies. `institution_short_name`, when set,
    restricts the bulk matching to assets of that FI (Spec 48 §1.3).
    `manual_mappings` overrides auto-matching for orphan lines: keys are
    `ticker_raw` strings from the extract, values are pendency IDs the user
    chose to apply the line against (Spec 49 hotfix — review screen lets
    user manually map orphans to open pendencies).
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
        manual_mappings=manual_mappings,
        manual_prices=manual_prices,
        manual_modes=manual_modes,
    )

    job.user_edits = edited_payload if edited_payload is not None else None
    # Spec 49 hotfix #6 — only flip to CONFIRMED when at least 1 pendency
    # was actually resolved. Otherwise leave as EXTRACTED so the user can
    # fix manual_prices / mappings and retry without re-running the LLM.
    if result.applied_count > 0:
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
            "manual_mappings_count": len(manual_mappings) if manual_mappings else 0,
            # Spec 49 hotfix — surface LLM usage in audit so cost can be
            # tracked by aggregating audit rows in addition to inspecting
            # individual extraction_job rows.
            "model": job.model,
            "input_tokens": job.input_tokens,
            "output_tokens": job.output_tokens,
            "cost_usd": str(job.cost_usd) if job.cost_usd is not None else None,
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
    manual_mappings: dict[str, str] | None = None,
    manual_prices: dict[str, float] | None = None,
    manual_modes: dict[str, str] | None = None,
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
            manual_mappings=manual_mappings,
            manual_prices=manual_prices,
            manual_modes=manual_modes,
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
    resolve to a workspace asset. Unmatched lines are reported.

    Assets with an automated price source (BRAPI/FINNHUB/COINBASE/TESOURO)
    are skipped — those prices are owned by their provider, not by
    user-uploaded extracts.
    """
    from numis_geek.services.price_freshness import AUTOMATED_SOURCES

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
        asset = _resolve_asset_by_ticker_or_name(db, job.workspace_id, ticker)
        if asset is None:
            skipped += 1
            errors.append(f"ticker {ticker!r} not found")
            continue
        if asset.price_source in AUTOMATED_SOURCES:
            skipped += 1
            errors.append(
                f"ticker {ticker!r}: preço gerenciado por {asset.price_source.value} "
                "— extrato ignorado (use refresh da API)."
            )
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


def _alnum_lower(s: str | None) -> str:
    """Aggressive normalization for substring matching: keep only
    alphanumeric chars, lowercased. Collapses punctuation/whitespace
    differences (`S/T` vs `-ST`, `U.S.` vs `US`, `A(acc)USD` vs `Aacc`)."""
    if not s:
        return ""
    return "".join(c.lower() for c in s if c.isalnum())


# Date patterns for maturity-based matching across asset name/ticker and
# extracted ticker_raw. Brokers use wildly different formats:
#   - ISO: '2034-05-16'
#   - BR: '16/05/2034' or '16/05/34'
#   - US: '05/16/2034' or '05/16/34'
_DATE_RE_ISO = re.compile(r"(?<!\d)(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?!\d)")
_DATE_RE_DMY4 = re.compile(r"(?<!\d)(\d{1,2})[-/](\d{1,2})[-/](\d{4})(?!\d)")
_DATE_RE_DMY2 = re.compile(r"(?<!\d)(\d{1,2})[-/](\d{1,2})[-/](\d{2})(?!\d)")


def _extract_dates(s: str | None) -> set[str]:
    """Return all ISO YYYY-MM-DD dates extractable from `s`. For 2-digit
    years with a DD/MM-vs-MM/DD ambiguity (e.g. '11/04/29'), returns BOTH
    interpretations when both are valid month-day combos. Year pivot: YY
    < 70 → 20YY, else 19YY (matches industry convention for maturity
    dates that are always in the future or recent past)."""
    if not s:
        return set()
    out: set[str] = set()
    for m in _DATE_RE_ISO.finditer(s):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            out.add(f"{y:04d}-{mo:02d}-{d:02d}")
    for m in _DATE_RE_DMY4.finditer(s):
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            out.add(f"{y:04d}-{mo:02d}-{d:02d}")
    for m in _DATE_RE_DMY2.finditer(s):
        a, b, yy = int(m.group(1)), int(m.group(2)), int(m.group(3))
        full_year = 2000 + yy if yy < 70 else 1900 + yy
        # DD/MM/YY interpretation
        if 1 <= b <= 12 and 1 <= a <= 31:
            out.add(f"{full_year:04d}-{b:02d}-{a:02d}")
        # MM/DD/YY interpretation
        if 1 <= a <= 12 and 1 <= b <= 31:
            out.add(f"{full_year:04d}-{a:02d}-{b:02d}")
    return out


def _resolve_asset_by_ticker_or_name(
    db: Session, workspace_id: str, candidate: str,
) -> Asset | None:
    """Match an extracted line to a workspace Asset.

    1. Case-insensitive ticker match (with strip) — LLM output isn't
       guaranteed to be uppercase or trimmed; DB tickers may also have
       mixed case for funds/CDBs.
    2. Case-insensitive name match — handles funds, fixed income, and other
       assets registered without a canonical exchange ticker (e.g. the
       `Fundo Verde BTG` case where Asset.ticker carries the fund name)
    3. Normalized substring match against `Asset.name` AND `Asset.ticker`,
       either direction — last-resort fuzz. Normalization strips
       punctuation/whitespace, so `Franklin U.S. Dollar` (ticker) matches
       `Franklin U.S. Dollar-ST MMF Adv` (extract). Only returns when
       exactly one asset matches, to avoid spurious resolutions.
    4. Date-based match for fixed income: extracts ISO/BR/US date formats
       from candidate and from each asset's name+ticker. If exactly one
       asset shares a maturity date with the candidate, return it. Handles
       `JPMorgan Chase 2033-09-14` (extract) ↔ `JPM 5.717 14/09/33`
       (asset) — same date, different formats.
    """
    if not candidate:
        return None
    needle = candidate.strip().lower()
    if not needle:
        return None
    # Step 1 — ticker, case-insensitive + trimmed on both sides.
    hit = (
        db.query(Asset)
        .filter(
            Asset.workspace_id == workspace_id,
            Asset.is_active == True,  # noqa: E712
            func.lower(func.trim(Asset.ticker)) == needle,
        )
        .first()
    )
    if hit is not None:
        return hit
    # Step 2 — exact name (case-insensitive).
    hit = next(
        (
            a for a in db.query(Asset)
            .filter(Asset.workspace_id == workspace_id, Asset.is_active == True)  # noqa: E712
            .all()
            if a.name and a.name.lower() == needle
        ),
        None,
    )
    if hit is not None:
        return hit
    # Step 3 — normalized substring against name AND ticker.
    needle_norm = _alnum_lower(candidate)
    if len(needle_norm) < 4:
        return None
    candidates = (
        db.query(Asset)
        .filter(Asset.workspace_id == workspace_id, Asset.is_active == True)  # noqa: E712
        .all()
    )
    matches: list[Asset] = []
    for a in candidates:
        for asset_str in (a.name, a.ticker):
            asset_norm = _alnum_lower(asset_str)
            if len(asset_norm) < 4:
                continue
            if asset_norm in needle_norm or needle_norm in asset_norm:
                matches.append(a)
                break  # one hit per asset is enough
    if len(matches) == 1:
        return matches[0]
    # Step 4 — date overlap. Fixed income often shares only a maturity
    # date across naming variants (Asset.ticker='JPM 5.717 14/09/33',
    # extract='JPMorgan Chase 2033-09-14'). Run only when Step 3 didn't
    # already produce a single hit.
    candidate_dates = _extract_dates(candidate)
    if not candidate_dates:
        return None
    date_matches: list[Asset] = []
    for a in candidates:
        asset_dates = _extract_dates(a.ticker) | _extract_dates(a.name)
        if candidate_dates & asset_dates:
            date_matches.append(a)
    return date_matches[0] if len(date_matches) == 1 else None


def _institution_short_name_for_asset(db: Session, asset: Asset) -> str | None:
    if not asset.account_id:
        return None
    acc = db.get(Account, asset.account_id)
    if acc is None or not acc.financial_institution_id:
        return None
    fi = db.get(FinancialInstitution, acc.financial_institution_id)
    return fi.short_name if fi else None


def _classify_bulk_extract(
    db: Session, job: ExtractionJob, payload: dict,
    *,
    institution_short_name: str | None = None,
    manual_mappings: dict[str, str] | None = None,
    manual_prices: dict[str, float] | None = None,
    manual_modes: dict[str, str] | None = None,
) -> tuple[
    list[dict],  # apply_plan: items the writer must process (incl. pendency, asset, price, mode)
    BulkApplyDetail,
    list[str],   # classification-time errors (e.g. missing ticker, snapshot not found)
]:
    """Spec 57 follow-up — pure classification, no writes.

    Returns the prospective plan PLUS the categorized buckets the UI shows.
    `_apply_bulk_to_snapshot` calls this and then performs writes for each
    item in `apply_plan`. The preview endpoint calls this and discards
    `apply_plan` (or reuses it to show predicted new/previous prices).
    """
    snap = db.get(PortfolioSnapshot, job.snapshot_id) if job.snapshot_id else None
    if snap is None:
        return [], BulkApplyDetail(
            applied=[], matched_no_pendency=[], orphan=[],
            pendency_not_in_extract=[], auto_skipped=[],
        ), [f"snapshot {job.snapshot_id} not found"]

    # Bulk extract only resolves pendencies whose action is "user edits the
    # price" (EDIT_PRICE/UPLOAD_FILE). RETRY_API pendencies belong to assets
    # with an automated price source — their fix is re-fetching the provider,
    # not overwriting the price from a brokerage extract.
    from numis_geek.models.portfolio_snapshot import PendencyAction
    from numis_geek.services.price_freshness import AUTOMATED_SOURCES

    open_pendencies = (
        db.query(SnapshotPendency)
        .filter(
            SnapshotPendency.snapshot_id == snap.id,
            SnapshotPendency.resolved_at.is_(None),
            SnapshotPendency.action_type != PendencyAction.RETRY_API,
        )
        .all()
    )
    pendency_by_asset = {p.asset_id: p for p in open_pendencies}

    positions = payload.get("positions") or []
    apply_plan: list[dict] = []
    applied_preview: list[dict] = []
    matched_no_pendency: list[dict] = []
    orphan: list[dict] = []
    auto_skipped: list[dict] = []
    matched_asset_ids: set[str] = set()
    errors: list[str] = []

    overrides = dict(manual_mappings or {})
    price_overrides = dict(manual_prices or {})
    mode_overrides = dict(manual_modes or {})

    for pos in positions:
        ticker = pos.get("ticker_normalized") or pos.get("ticker_raw")
        ticker_raw_key = pos.get("ticker_raw") or ""
        manual_price = (
            price_overrides.get(ticker_raw_key)
            or price_overrides.get(ticker)
        )
        unit_price_raw = (
            manual_price
            or pos.get("unit_price")
            or pos.get("market_value")
        )
        if not ticker:
            errors.append("position with no ticker")
            continue
        manual_pendency_id = overrides.get(ticker_raw_key) or overrides.get(ticker)
        asset: Asset | None = None
        if manual_pendency_id:
            forced_pen = db.get(SnapshotPendency, manual_pendency_id)
            if forced_pen and forced_pen.snapshot_id == snap.id:
                asset = db.get(Asset, forced_pen.asset_id)
        if asset is None:
            asset = _resolve_asset_by_ticker_or_name(db, job.workspace_id, ticker)
        if asset is None:
            orphan.append({
                "ticker": ticker,
                "unit_price": str(unit_price_raw) if unit_price_raw is not None else None,
            })
            continue

        asset_fi = _institution_short_name_for_asset(db, asset)

        # Auto-priced asset: extract is informational only. Surface in
        # auto_skipped so the UI can show "recognized, no action needed",
        # but never feed it into the apply plan (provider owns the price).
        if asset.price_source in AUTOMATED_SOURCES and not manual_pendency_id:
            auto_skipped.append({
                "asset_id": asset.id,
                "ticker": ticker,
                "asset_name": asset.name,
                "institution_short_name": asset_fi,
                "price_source": asset.price_source.value,
                "unit_price": str(unit_price_raw) if unit_price_raw is not None else None,
            })
            continue

        if (
            institution_short_name
            and asset_fi != institution_short_name
            and not manual_pendency_id
        ):
            # Different FI than the one scoped: silently out of scope.
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
            errors.append(
                f"{ticker!r}: sem preço unitário no extrato "
                "(use o input ao lado do dropdown pra informar manualmente)."
            )
            continue

        effective_mode = (
            mode_overrides.get(ticker_raw_key)
            or mode_overrides.get(ticker)
        )
        new_price = Decimal(str(unit_price_raw))
        apply_plan.append({
            "pendency_id": pendency.id,
            "asset_id": asset.id,
            "ticker": ticker,
            "asset_name": asset.name,
            "institution_short_name": asset_fi,
            "new_price": new_price,
            "previous_price": asset.current_price,
            "effective_mode": effective_mode,
            "ticker_raw_key": ticker_raw_key,
        })
        applied_preview.append({
            "pendency_id": pendency.id,
            "asset_id": asset.id,
            "ticker": ticker,
            "asset_name": asset.name,
            "institution_short_name": asset_fi,
            "new_price": str(new_price),
            "previous_price": (
                str(asset.current_price) if asset.current_price is not None else None
            ),
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

    return apply_plan, BulkApplyDetail(
        applied=applied_preview,
        matched_no_pendency=matched_no_pendency,
        orphan=orphan,
        pendency_not_in_extract=not_in_extract,
        auto_skipped=auto_skipped,
    ), errors


def preview_bulk_extract(
    db: Session, *, job_id: str,
    institution_short_name: str | None = None,
    manual_mappings: dict[str, str] | None = None,
    manual_prices: dict[str, float] | None = None,
    manual_modes: dict[str, str] | None = None,
) -> ExtractionApplyResult:
    """Read-only classification of an EXTRACTED bulk job. Returns the same
    `BulkApplyDetail` shape the UI gets after Apply, but no writes happen.
    Useful for the review modal so it shows exactly what Apply will do."""
    job = db.get(ExtractionJob, job_id)
    if job is None:
        raise ExtractionError(f"Job {job_id} not found")
    if job.snapshot_id is None:
        raise ExtractionError("Preview only available for bulk jobs (snapshot_id set)")
    payload = job.extracted_json or {}
    apply_plan, detail, errors = _classify_bulk_extract(
        db, job, payload,
        institution_short_name=institution_short_name,
        manual_mappings=manual_mappings,
        manual_prices=manual_prices,
        manual_modes=manual_modes,
    )
    _ = apply_plan  # discarded — preview is read-only
    return ExtractionApplyResult(
        applied_count=len(detail.applied),
        skipped_count=len(detail.orphan) + len(detail.matched_no_pendency),
        errors=errors,
        bulk_detail=detail,
    )


def _apply_bulk_to_snapshot(
    db: Session, job: ExtractionJob, payload: dict,
    *,
    user_id: str | None,
    user_email: str | None,
    institution_short_name: str | None = None,
    manual_mappings: dict[str, str] | None = None,
    manual_prices: dict[str, float] | None = None,
    manual_modes: dict[str, str] | None = None,
) -> ExtractionApplyResult:
    """Bulk path (Spec 48): match positions[] by ticker to open pendencies
    in the snapshot. Each match calls resolve_pendency (which updates
    Asset.current_price + PortfolioSnapshotItem + recomputes totals) with
    the bulk attachment as the resolution attachment.

    Returns categorized lists in BulkApplyDetail so the UI can render
    the review/result panel without re-querying.
    """
    apply_plan, detail, errors = _classify_bulk_extract(
        db, job, payload,
        institution_short_name=institution_short_name,
        manual_mappings=manual_mappings,
        manual_prices=manual_prices,
        manual_modes=manual_modes,
    )
    if not apply_plan and not detail.applied:
        # Snapshot-not-found case: detail is empty + error already set.
        return ExtractionApplyResult(
            applied_count=0, skipped_count=0, errors=errors, bulk_detail=detail,
        )

    from numis_geek.services import snapshot as snapshot_service

    actually_applied: list[dict] = []
    for item in apply_plan:
        note = (
            f"bulk extract (job {job.id})"
            + (f" · FI={institution_short_name}" if institution_short_name else "")
            + (f" · mode={item['effective_mode']}" if item["effective_mode"] else "")
        )
        try:
            snapshot_service.resolve_pendency(
                db,
                pendency_id=item["pendency_id"],
                user_id=user_id,
                user_email=user_email,
                new_price=item["new_price"],
                value_mode=item["effective_mode"],
                file_id=job.attachment_id,
                note=note,
            )
        except ValueError as e:
            errors.append(f"pendency {item['pendency_id']}: {e}")
            continue
        actually_applied.append({
            "pendency_id": item["pendency_id"],
            "asset_id": item["asset_id"],
            "ticker": item["ticker"],
            "asset_name": item["asset_name"],
            "institution_short_name": item["institution_short_name"],
            "new_price": str(item["new_price"]),
            "previous_price": (
                str(item["previous_price"]) if item["previous_price"] is not None else None
            ),
        })

    db.flush()
    # Overwrite the prospective `applied` with what actually went through.
    detail.applied = actually_applied
    return ExtractionApplyResult(
        applied_count=len(actually_applied),
        skipped_count=len(detail.orphan) + len(detail.matched_no_pendency),
        errors=errors,
        bulk_detail=detail,
    )
