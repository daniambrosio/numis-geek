"""Spec 38 — LLM extraction endpoints.

Workflow (sync V1):

    POST /extractions               → creates + runs job inline, returns EXTRACTED
    POST /extractions/{id}/confirm  → applies payload, resolves pendency
    POST /extractions/{id}/reject   → marks REJECTED
    GET  /extractions/{id}          → status polling (in case we ever go async)
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from numis_geek.api.deps import get_current_user, get_db
from numis_geek.models.extraction_job import (
    ExtractionJob, ExtractionSourceHint, ExtractionStatus,
)
from numis_geek.models.user import User, UserRole
from numis_geek.services import extraction as extraction_service
from numis_geek.services.auth import UserContext


router = APIRouter(prefix="/extractions", tags=["extractions"])


# ── schemas ──────────────────────────────────────────────────────────────────

class CreateExtractionBody(BaseModel):
    attachment_id: str
    source_hint: ExtractionSourceHint = ExtractionSourceHint.GENERIC
    pendency_id: str | None = None
    snapshot_id: str | None = None
    asset_id: str | None = None


class ConfirmExtractionBody(BaseModel):
    edited_payload: dict | None = None
    institution_short_name: str | None = None
    # Spec 49 hotfix — { ticker_raw: pendency_id } overrides for manual
    # mapping of orphan rows.
    manual_mappings: dict[str, str] | None = None
    # Spec 49 hotfix — { ticker_raw: price } overrides when the extract has
    # no unit_price (e.g. previdência statements show contributions, not
    # current price).
    manual_prices: dict[str, float] | None = None
    # Spec 49 hotfix #4 — { ticker_raw: "unit" | "total" } override for the
    # auto-detected price semantic. By default the backend infers from
    # asset_class (STOCK/REIT/ETF → unit; FUND/FIXED_INCOME/etc → total).
    manual_modes: dict[str, str] | None = None


class RejectExtractionBody(BaseModel):
    reason: str | None = None


class ExtractionJobOut(BaseModel):
    id: str
    workspace_id: str
    status: str
    source_hint: str
    attachment_id: str
    pendency_id: str | None
    snapshot_id: str | None
    asset_id: str | None
    extracted_json: dict | None
    confidence: float | None
    detected_hint: str | None
    model: str | None
    prompt_version: str | None
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: str | None
    error_message: str | None
    created_at: str
    started_at: str | None
    completed_at: str | None
    confirmed_at: str | None

    @classmethod
    def from_orm(cls, j: ExtractionJob) -> "ExtractionJobOut":
        return cls(
            id=j.id,
            workspace_id=j.workspace_id,
            status=j.status.value,
            source_hint=j.source_hint.value,
            attachment_id=j.attachment_id,
            pendency_id=j.pendency_id,
            snapshot_id=j.snapshot_id,
            asset_id=j.asset_id,
            extracted_json=j.extracted_json,
            confidence=float(j.confidence) if j.confidence is not None else None,
            detected_hint=j.detected_hint.value if j.detected_hint else None,
            model=j.model,
            prompt_version=j.prompt_version,
            input_tokens=j.input_tokens,
            output_tokens=j.output_tokens,
            cost_usd=str(j.cost_usd) if j.cost_usd is not None else None,
            error_message=j.error_message,
            created_at=j.created_at.isoformat() if j.created_at else "",
            started_at=j.started_at.isoformat() if j.started_at else None,
            completed_at=j.completed_at.isoformat() if j.completed_at else None,
            confirmed_at=j.confirmed_at.isoformat() if j.confirmed_at else None,
        )


class BulkApplyDetailOut(BaseModel):
    applied: list[dict]
    matched_no_pendency: list[dict]
    orphan: list[dict]
    pendency_not_in_extract: list[dict]
    # Spec 57 follow-up — assets matched but auto-priced (BRAPI/FINNHUB/…).
    # UI shows them in a collapsed informational bucket; apply ignores them.
    auto_skipped: list[dict] = []


class PreviewExtractionBody(BaseModel):
    institution_short_name: str | None = None
    manual_mappings: dict[str, str] | None = None
    manual_prices: dict[str, float] | None = None
    manual_modes: dict[str, str] | None = None


class ApplyResultOut(BaseModel):
    applied_count: int
    skipped_count: int
    errors: list[str]
    bulk_detail: BulkApplyDetailOut | None = None


# ── helpers ──────────────────────────────────────────────────────────────────

def _resolve_workspace(current_user: UserContext, body_ws_id: str | None) -> str:
    if current_user.role == UserRole.sysadmin:
        if not body_ws_id and current_user.workspace_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="sysadmin must specify a workspace context",
            )
        return body_ws_id or current_user.workspace_id
    return current_user.workspace_id


def _check_access(j: ExtractionJob, current_user: UserContext) -> None:
    if current_user.role == UserRole.sysadmin:
        return
    if j.workspace_id != current_user.workspace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Extraction job not found",
        )


def _actor_email(db: Session, user_id: str | None) -> str | None:
    if not user_id:
        return None
    user = db.get(User, user_id)
    return user.email if user else None


# ── routes ───────────────────────────────────────────────────────────────────

@router.post("", response_model=ExtractionJobOut, status_code=status.HTTP_201_CREATED)
def create_extraction(
    body: CreateExtractionBody,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    workspace_id = current_user.workspace_id
    if not workspace_id and current_user.role != UserRole.sysadmin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="user has no workspace",
        )
    user_email = _actor_email(db, current_user.user_id)
    try:
        job = extraction_service.create_and_run(
            db,
            workspace_id=workspace_id or "",
            attachment_id=body.attachment_id,
            source_hint=body.source_hint,
            pendency_id=body.pendency_id,
            snapshot_id=body.snapshot_id,
            asset_id=body.asset_id,
            user_id=current_user.user_id,
            user_email=user_email,
        )
    except extraction_service.ExtractionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return ExtractionJobOut.from_orm(job)


@router.get("/{job_id}", response_model=ExtractionJobOut)
def get_extraction(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    j = db.get(ExtractionJob, job_id)
    if j is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    _check_access(j, current_user)
    return ExtractionJobOut.from_orm(j)


@router.post("/{job_id}/confirm", response_model=ApplyResultOut)
def confirm_extraction(
    job_id: str,
    body: ConfirmExtractionBody,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    j = db.get(ExtractionJob, job_id)
    if j is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    _check_access(j, current_user)
    user_email = _actor_email(db, current_user.user_id)
    try:
        result = extraction_service.confirm_extraction(
            db,
            job_id=job_id,
            user_id=current_user.user_id,
            user_email=user_email,
            edited_payload=body.edited_payload,
            institution_short_name=body.institution_short_name,
            manual_mappings=body.manual_mappings,
            manual_prices=body.manual_prices,
            manual_modes=body.manual_modes,
        )
    except extraction_service.ExtractionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    detail_out = None
    if result.bulk_detail is not None:
        detail_out = BulkApplyDetailOut(
            applied=result.bulk_detail.applied,
            matched_no_pendency=result.bulk_detail.matched_no_pendency,
            orphan=result.bulk_detail.orphan,
            pendency_not_in_extract=result.bulk_detail.pendency_not_in_extract,
            auto_skipped=result.bulk_detail.auto_skipped,
        )
    return ApplyResultOut(
        applied_count=result.applied_count,
        skipped_count=result.skipped_count,
        errors=result.errors,
        bulk_detail=detail_out,
    )


@router.post("/{job_id}/preview", response_model=ApplyResultOut)
def preview_extraction(
    job_id: str,
    body: PreviewExtractionBody,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    """Spec 57 follow-up — read-only classification preview for a bulk
    job. Returns the same shape as confirm, with no writes. UI uses this
    to render the review modal so what's shown matches what will happen."""
    j = db.get(ExtractionJob, job_id)
    if j is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    _check_access(j, current_user)
    try:
        result = extraction_service.preview_bulk_extract(
            db,
            job_id=job_id,
            institution_short_name=body.institution_short_name,
            manual_mappings=body.manual_mappings,
            manual_prices=body.manual_prices,
            manual_modes=body.manual_modes,
        )
    except extraction_service.ExtractionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    detail_out = None
    if result.bulk_detail is not None:
        detail_out = BulkApplyDetailOut(
            applied=result.bulk_detail.applied,
            matched_no_pendency=result.bulk_detail.matched_no_pendency,
            orphan=result.bulk_detail.orphan,
            pendency_not_in_extract=result.bulk_detail.pendency_not_in_extract,
            auto_skipped=result.bulk_detail.auto_skipped,
        )
    return ApplyResultOut(
        applied_count=result.applied_count,
        skipped_count=result.skipped_count,
        errors=result.errors,
        bulk_detail=detail_out,
    )


@router.post("/{job_id}/reject", response_model=ExtractionJobOut)
def reject_extraction(
    job_id: str,
    body: RejectExtractionBody,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    j = db.get(ExtractionJob, job_id)
    if j is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    _check_access(j, current_user)
    user_email = _actor_email(db, current_user.user_id)
    job = extraction_service.reject_extraction(
        db,
        job_id=job_id,
        user_id=current_user.user_id,
        user_email=user_email,
        reason=body.reason,
    )
    return ExtractionJobOut.from_orm(job)
