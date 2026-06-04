"""Spec 54 — build version surface (semver + sha + date).

`get_version_info()` retorna a 3-uple usada tanto pelo `/version`
endpoint quanto pelo título do FastAPI app. Em produção os campos sha
e date vêm de variáveis de ambiente setadas no `docker build`
(`GIT_SHA`, `BUILD_DATE`). Em dev fazemos fallback pra `git rev-parse`
e `date.today()`.
"""
from __future__ import annotations

import os
import subprocess
from datetime import date
from importlib import metadata


def _semver() -> str:
    try:
        return metadata.version("numis-geek")
    except metadata.PackageNotFoundError:
        return "0.0.0"


def _sha() -> str:
    env = os.environ.get("GIT_SHA")
    if env:
        return env
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        )
        return out.decode("utf-8").strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def _build_date() -> str:
    env = os.environ.get("BUILD_DATE")
    if env:
        return env
    return date.today().isoformat()


def get_version_info() -> dict[str, str]:
    return {
        "version": _semver(),
        "sha": _sha(),
        "date": _build_date(),
    }
