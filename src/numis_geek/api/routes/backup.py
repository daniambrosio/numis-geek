"""Spec 37 — sysadmin force-trigger + listing of DB backups."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from numis_geek.api.deps import get_current_user
from numis_geek.config import DATABASE_URL
from numis_geek.models.user import UserRole
from numis_geek.scheduler import BACKUP_DIR
from numis_geek.services.auth import UserContext
from numis_geek.services.backup import (
    BackupResult,
    create_backup,
    rotate_backups,
)

router = APIRouter(prefix="/sysadmin/backup", tags=["backup"])


class BackupOut(BaseModel):
    filename: str
    size_bytes: int
    duration_ms: int | None = None
    pages_copied: int | None = None
    kept_count: int | None = None
    deleted_count: int | None = None

    @classmethod
    def from_result(
        cls, r: BackupResult, kept: int, deleted: int,
    ) -> "BackupOut":
        return cls(
            filename=r.path.name,
            size_bytes=r.size_bytes,
            duration_ms=r.duration_ms,
            pages_copied=r.pages_copied,
            kept_count=kept,
            deleted_count=deleted,
        )


class BackupFileOut(BaseModel):
    filename: str
    size_bytes: int
    modified_at: str


class BackupListOut(BaseModel):
    items: list[BackupFileOut]
    total_bytes: int


def _require_sysadmin(current_user: UserContext) -> None:
    if current_user.role != UserRole.sysadmin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="SysAdmin only.",
        )


@router.post("", response_model=BackupOut)
def trigger_backup(
    current_user: UserContext = Depends(get_current_user),
):
    """Run a backup + rotation now. Returns the new file's metadata."""
    _require_sysadmin(current_user)
    result = create_backup(DATABASE_URL, BACKUP_DIR, label="manual")
    rotated = rotate_backups(BACKUP_DIR)
    return BackupOut.from_result(result, len(rotated.kept), len(rotated.deleted))


@router.get("", response_model=BackupListOut)
def list_backups(
    current_user: UserContext = Depends(get_current_user),
):
    """List existing backup files with size + mtime."""
    _require_sysadmin(current_user)
    if not BACKUP_DIR.exists():
        return BackupListOut(items=[], total_bytes=0)
    items: list[BackupFileOut] = []
    total = 0
    for p in sorted(BACKUP_DIR.iterdir(), reverse=True):
        if not p.is_file() or not p.name.endswith(".db"):
            continue
        st = p.stat()
        items.append(BackupFileOut(
            filename=p.name,
            size_bytes=st.st_size,
            modified_at=datetime.fromtimestamp(st.st_mtime).isoformat(),
        ))
        total += st.st_size
    return BackupListOut(items=items, total_bytes=total)
