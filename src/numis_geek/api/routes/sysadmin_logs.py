"""Spec 55 — leitura de tail dos logs via UI (sysadmin only).

Endpoint pra debug rápido sem precisar SSH no servidor. Lê as últimas
N linhas do arquivo principal de log (data/logs/numis.log) ou retorna
404 quando file logging não está habilitado (dev).
"""
from __future__ import annotations

import os
from collections import deque

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from numis_geek.api.deps import get_current_user
from numis_geek.logging_config import current_log_path
from numis_geek.models.user import UserRole
from numis_geek.services.auth import UserContext

router = APIRouter(prefix="/sysadmin", tags=["sysadmin"])


class LogTailOut(BaseModel):
    path: str
    size_bytes: int
    lines: list[str]


@router.get("/logs/tail", response_model=LogTailOut)
def tail_logs(
    n: int = Query(default=200, ge=1, le=2000),
    current_user: UserContext = Depends(get_current_user),
):
    if current_user.role != UserRole.sysadmin:
        raise HTTPException(status_code=403, detail="sysadmin only")

    path = current_log_path()
    if path is None:
        raise HTTPException(
            status_code=404,
            detail="File logging not enabled (LOG_DIR not set).",
        )
    if not path.exists():
        raise HTTPException(
            status_code=404, detail=f"Log file not found: {path}",
        )

    size = os.path.getsize(path)
    # Tail N linhas usando deque pra evitar carregar tudo em memória.
    tail: deque[str] = deque(maxlen=n)
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            tail.append(line.rstrip("\n"))
    return LogTailOut(path=str(path), size_bytes=size, lines=list(tail))
