"""Spec 55 — log configuration with optional file rotation.

Em produção (LOG_DIR setada) escreve em data/logs/numis.log com
RotatingFileHandler (10MB × 5). Sempre também escreve no stdout pra
`docker logs` continuar funcionando.

Em dev: só stdout. Comportamento idêntico ao default do uvicorn antes
desse spec.
"""
from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
_BACKUP_COUNT = 5


def configure_logging() -> Path | None:
    """Setup root logger handlers idempotentemente.

    Retorna o Path do log file quando file rotation está ativa, ou
    None em dev.
    """
    log_dir_env = os.environ.get("LOG_DIR")
    log_path: Path | None = None

    formatter = logging.Formatter(_FORMAT)
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Limpa handlers existentes pra ser idempotente (uvicorn reload).
    for h in list(root.handlers):
        root.removeHandler(h)

    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    root.addHandler(stream)

    if log_dir_env:
        log_dir = Path(log_dir_env)
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "numis.log"
        file_h = RotatingFileHandler(
            log_path, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT,
        )
        file_h.setFormatter(formatter)
        root.addHandler(file_h)

    # Uvicorn access logs também pegam o formatter root via propagação.
    return log_path


def current_log_path() -> Path | None:
    """Path do log file ativo, ou None se file logging não configurado."""
    log_dir_env = os.environ.get("LOG_DIR")
    if not log_dir_env:
        return None
    return Path(log_dir_env) / "numis.log"
