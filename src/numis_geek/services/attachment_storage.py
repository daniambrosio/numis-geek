"""Attachment storage — local filesystem (V1).

Files live under `./data/attachments/{workspace_id}/{uuid}.{ext}`. Move to
object storage when migrating to VPS — the only contract the rest of the
code uses is `storage_key`, a relative path.
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from numis_geek.models.attachment import Attachment, AttachmentKind

ROOT = Path("./data/attachments")
MAX_BYTES = 10 * 1024 * 1024  # 10 MB

# MIME → (kind, file extension). The whitelist is intentionally short — adding
# new types means evaluating their security profile.
_ALLOWED_MIME: dict[str, tuple[AttachmentKind, str]] = {
    "image/png":       (AttachmentKind.IMAGE, "png"),
    "image/jpeg":      (AttachmentKind.IMAGE, "jpg"),
    "image/webp":      (AttachmentKind.IMAGE, "webp"),
    "application/pdf": (AttachmentKind.PDF,   "pdf"),
    "text/csv":        (AttachmentKind.CSV,   "csv"),
}


@dataclass
class SavedFile:
    storage_key: str  # path relative to ROOT, e.g. "{ws}/{uuid}.png"
    kind: AttachmentKind
    size_bytes: int
    mime_type: str


class AttachmentTooLargeError(Exception):
    pass


class AttachmentMimeNotAllowedError(Exception):
    pass


def is_mime_allowed(mime: str) -> bool:
    return mime in _ALLOWED_MIME


def kind_for_mime(mime: str) -> AttachmentKind:
    pair = _ALLOWED_MIME.get(mime)
    return pair[0] if pair else AttachmentKind.OTHER


def save_bytes(workspace_id: str, payload: bytes, mime_type: str) -> SavedFile:
    """Validate and persist `payload` for `workspace_id`. Raises
    AttachmentMimeNotAllowedError or AttachmentTooLargeError on validation
    failure."""
    if mime_type not in _ALLOWED_MIME:
        raise AttachmentMimeNotAllowedError(mime_type)

    size = len(payload)
    if size > MAX_BYTES:
        raise AttachmentTooLargeError(f"{size} bytes > {MAX_BYTES} limit")

    kind, ext = _ALLOWED_MIME[mime_type]
    target_dir = ROOT / workspace_id
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4()}.{ext}"
    target_path = target_dir / filename
    target_path.write_bytes(payload)

    storage_key = f"{workspace_id}/{filename}"
    return SavedFile(
        storage_key=storage_key,
        kind=kind,
        size_bytes=size,
        mime_type=mime_type,
    )


def absolute_path(storage_key: str) -> Path:
    """Safely resolve `storage_key` against ROOT. Raises ValueError on
    attempted directory traversal (e.g. `../etc/passwd`)."""
    candidate = (ROOT / storage_key).resolve()
    root_abs = ROOT.resolve()
    try:
        candidate.relative_to(root_abs)
    except ValueError as exc:
        raise ValueError(f"Path escapes storage root: {storage_key}") from exc
    return candidate


def absolute_path_for(att: Attachment) -> Path:
    """Defense-in-depth resolver (Spec 43 §2).

    Like `absolute_path` but ALSO verifies the storage_key lives under
    the attachment's own workspace subdir. Guards against a corrupted
    row whose storage_key would otherwise point at a file from a
    different workspace.

    Prefer this over `absolute_path()` whenever you hold an Attachment
    instance (download / delete routes, extraction service, etc.).
    """
    expected_prefix = f"{att.workspace_id}/"
    if not att.storage_key.startswith(expected_prefix):
        raise ValueError(
            f"Attachment {att.id} storage_key {att.storage_key!r} "
            f"escapes its workspace subdir (expected prefix {expected_prefix!r})"
        )
    return absolute_path(att.storage_key)


def delete(storage_key: str) -> None:
    """Remove the file from disk. Idempotent — missing files are tolerated."""
    path = absolute_path(storage_key)
    if path.exists():
        os.remove(path)


def delete_for(att: Attachment) -> None:
    """Like `delete` but applies the workspace validation from
    `absolute_path_for` before unlinking (Spec 43 §2)."""
    path = absolute_path_for(att)
    if path.exists():
        os.remove(path)
