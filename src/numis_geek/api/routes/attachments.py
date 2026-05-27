"""Attachment routes — upload / list / download / soft-delete.

Polymorphic over (asset, asset_movement, distribution). See
`docs/conceptual-model.md` §2.9 for the rationale and Spec 19 for the schema.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from numis_geek.api.deps import get_current_user, get_db
from numis_geek.models.asset import Asset
from numis_geek.models.asset_movement import AssetMovement
from numis_geek.models.attachment import (
    Attachment,
    AttachmentKind,
    AttachmentSourceType,
)
from numis_geek.models.distribution import Distribution
from numis_geek.models.user import User, UserRole
from numis_geek.services import attachment_storage
from numis_geek.services.audit import AuditService
from numis_geek.services.auth import UserContext

router = APIRouter(prefix="/attachments", tags=["attachments"])


# ── schemas ───────────────────────────────────────────────────────────────────

class AttachmentOut(BaseModel):
    id: str
    workspace_id: str
    source_type: str
    source_id: str
    kind: str
    filename: str
    mime_type: str
    size_bytes: int
    uploaded_at: str
    uploaded_by: str | None
    is_active: bool

    @classmethod
    def from_orm(cls, a: Attachment) -> "AttachmentOut":
        return cls(
            id=a.id,
            workspace_id=a.workspace_id,
            source_type=a.source_type.value,
            source_id=a.source_id,
            kind=a.kind.value,
            filename=a.filename,
            mime_type=a.mime_type,
            size_bytes=a.size_bytes,
            uploaded_at=a.uploaded_at.isoformat(),
            uploaded_by=a.uploaded_by,
            is_active=a.is_active,
        )


# ── helpers ───────────────────────────────────────────────────────────────────

_SOURCE_MODEL = {
    AttachmentSourceType.ASSET: Asset,
    AttachmentSourceType.MOVEMENT: AssetMovement,
    AttachmentSourceType.DISTRIBUTION: Distribution,
}


def _parse_source_type(value: str) -> AttachmentSourceType:
    try:
        return AttachmentSourceType(value)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid source_type '{value}'. Must be one of: "
            f"{[t.value for t in AttachmentSourceType]}.",
        )


def _verify_source_access(
    db: Session,
    source_type: AttachmentSourceType,
    source_id: str,
    user: UserContext,
) -> str:
    """Confirm the source row exists and the user can write to it. Returns
    the source's workspace_id."""
    model = _SOURCE_MODEL[source_type]
    row = db.get(model, source_id)
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{source_type.value} {source_id} not found.",
        )
    workspace_id = getattr(row, "workspace_id")
    if user.role != UserRole.sysadmin and workspace_id != user.workspace_id:
        # Same masking pattern used in other routes — reveal nothing.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{source_type.value} {source_id} not found.",
        )
    return workspace_id


# ── routes ────────────────────────────────────────────────────────────────────

@router.post("", response_model=AttachmentOut, status_code=status.HTTP_201_CREATED)
async def upload_attachment(
    source_type: str = Form(...),
    source_id: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    source_enum = _parse_source_type(source_type)
    workspace_id = _verify_source_access(db, source_enum, source_id, current_user)

    payload = await file.read()
    mime = file.content_type or ""
    try:
        saved = attachment_storage.save_bytes(workspace_id, payload, mime)
    except attachment_storage.AttachmentMimeNotAllowedError:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"MIME type '{mime}' not allowed.",
        )
    except attachment_storage.AttachmentTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=str(exc),
        )

    att = Attachment(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        source_type=source_enum,
        source_id=source_id,
        kind=saved.kind,
        filename=file.filename or "unnamed",
        mime_type=saved.mime_type,
        size_bytes=saved.size_bytes,
        storage_key=saved.storage_key,
        uploaded_at=datetime.now(timezone.utc),
        uploaded_by=current_user.user_id,
    )
    db.add(att)
    db.flush()

    actor = db.get(User, current_user.user_id)
    AuditService(db).log(
        user_email=actor.email if actor else current_user.user_id,
        action="attachment.uploaded",
        resource_type="attachment",
        resource_id=att.id,
        details={
            "source_type": source_enum.value,
            "source_id": source_id,
            "filename": att.filename,
            "size_bytes": att.size_bytes,
        },
    )
    return AttachmentOut.from_orm(att)


@router.get("", response_model=list[AttachmentOut])
def list_attachments(
    source_type: str,
    source_id: str,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    source_enum = _parse_source_type(source_type)
    _verify_source_access(db, source_enum, source_id, current_user)
    items = (
        db.query(Attachment)
        .filter(
            Attachment.source_type == source_enum,
            Attachment.source_id == source_id,
            Attachment.is_active == True,  # noqa: E712
        )
        .order_by(Attachment.uploaded_at.desc())
        .all()
    )
    return [AttachmentOut.from_orm(a) for a in items]


@router.get("/{attachment_id}/download")
def download_attachment(
    attachment_id: str,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    att = db.get(Attachment, attachment_id)
    if not att or not att.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found.")
    if current_user.role != UserRole.sysadmin and att.workspace_id != current_user.workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found.")
    try:
        path = attachment_storage.absolute_path(att.storage_key)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Storage path resolution failed.",
        )
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Attachment file is missing on disk.",
        )
    return FileResponse(
        path,
        media_type=att.mime_type,
        filename=att.filename,
    )


@router.delete("/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_attachment(
    attachment_id: str,
    db: Session = Depends(get_db),
    current_user: UserContext = Depends(get_current_user),
):
    """Hard delete: remove the file from disk **and** the DB row.

    Spec 43 — replaces the previous soft-delete behaviour. Rejected (409)
    when an ExtractionJob still references the attachment; otherwise the
    file is unlinked and the row is dropped. Audit log preserves the
    record of the deletion.
    """
    from numis_geek.models.extraction_job import ExtractionJob  # local import to keep route loose

    att = db.get(Attachment, attachment_id)
    if not att:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found.")
    if current_user.role != UserRole.sysadmin and att.workspace_id != current_user.workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found.")

    # Guard against breaking an extraction job that still references this file.
    in_use = (
        db.query(ExtractionJob)
        .filter(ExtractionJob.attachment_id == att.id)
        .first()
    )
    if in_use is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Anexo referenciado pelo job de extração {in_use.id}; remova o job antes."
            ),
        )

    snapshot = {
        "filename": att.filename,
        "storage_key": att.storage_key,
        "size_bytes": att.size_bytes,
        "workspace_id": att.workspace_id,
    }

    # Best-effort unlink: if the file is missing on disk we still drop the
    # row (the FS was already out of sync).
    try:
        attachment_storage.delete(att.storage_key)
    except (FileNotFoundError, ValueError):
        pass

    db.delete(att)
    db.flush()

    actor = db.get(User, current_user.user_id)
    AuditService(db).log(
        user_email=actor.email if actor else current_user.user_id,
        action="attachment.deleted",
        resource_type="attachment",
        resource_id=attachment_id,
        details=snapshot,
    )
    return None
