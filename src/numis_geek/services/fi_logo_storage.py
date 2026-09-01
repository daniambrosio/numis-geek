"""Financial-institution logo storage — local filesystem.

Files live under `./data/fi-logos/{fi_id}.{ext}`. Diferente de attachments,
logo de instituição é entidade de sistema (sem workspace) e gerenciada só por
sysadmin: um logo por instituição, substituído no lugar. A linha guarda
`logo_storage_key` (caminho relativo à ROOT), que é o único contrato usado
pelo resto do código — trocar por object storage depois não vaza pra fora
deste módulo.

O logo é servido como data URL dentro do JSON de `/financial-institutions/logos`
(o frontend usa Bearer token, e `<img src>` não carrega header), por isso o cap
de tamanho é bem menor que o de attachment.
"""
from __future__ import annotations

import base64
import os
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path("./data/fi-logos")

# 512 KB — logo de banco em PNG/WEBP a 128–256px fica na casa de dezenas de KB.
# O cap existe porque o arquivo trafega embutido (base64) na listagem.
MAX_BYTES = 512 * 1024

# MIME → extensão. SVG entra porque logo vetorial é o formato natural; ele é
# renderizado só dentro de `<img src="data:...">`, contexto em que script
# embutido no SVG não executa.
ALLOWED_MIME: dict[str, str] = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/svg+xml": "svg",
}

HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


@dataclass
class SavedLogo:
    storage_key: str  # caminho relativo à ROOT, ex. "{fi_id}.png"
    mime_type: str
    size_bytes: int


class LogoTooLargeError(Exception):
    pass


class LogoMimeNotAllowedError(Exception):
    pass


def is_mime_allowed(mime: str) -> bool:
    return mime in ALLOWED_MIME


def normalize_hex_color(value: str | None) -> str | None:
    """Valida/normaliza `#RRGGBB` (lowercase). None/'' viram None.
    Levanta ValueError em formato inválido."""
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None
    if not HEX_COLOR_RE.match(raw):
        raise ValueError(f"Cor inválida: {value!r}. Use o formato #RRGGBB.")
    return raw.lower()


def save_bytes(fi_id: str, payload: bytes, mime_type: str) -> SavedLogo:
    """Valida e persiste o logo de `fi_id`. Levanta LogoMimeNotAllowedError
    ou LogoTooLargeError na falha de validação."""
    if mime_type not in ALLOWED_MIME:
        raise LogoMimeNotAllowedError(mime_type)

    size = len(payload)
    if size > MAX_BYTES:
        size_kb = size / 1024
        limit_kb = MAX_BYTES // 1024
        raise LogoTooLargeError(
            f"Logo de {size_kb:.0f} KB excede o limite de {limit_kb} KB.",
        )

    ext = ALLOWED_MIME[mime_type]
    ROOT.mkdir(parents=True, exist_ok=True)
    storage_key = f"{fi_id}.{ext}"
    absolute_path(storage_key).write_bytes(payload)
    return SavedLogo(storage_key=storage_key, mime_type=mime_type, size_bytes=size)


def absolute_path(storage_key: str) -> Path:
    """Resolve `storage_key` sob ROOT. Levanta ValueError em tentativa de
    directory traversal (ex.: `../etc/passwd`)."""
    candidate = (ROOT / storage_key).resolve()
    root_abs = ROOT.resolve()
    try:
        candidate.relative_to(root_abs)
    except ValueError as exc:
        raise ValueError(f"Path escapes storage root: {storage_key}") from exc
    return candidate


def read_bytes(storage_key: str) -> bytes | None:
    """Conteúdo do logo, ou None quando a linha aponta pra arquivo que sumiu
    do disco (restore parcial, volume novo)."""
    try:
        path = absolute_path(storage_key)
    except ValueError:
        return None
    if not path.exists():
        return None
    return path.read_bytes()


def data_url(storage_key: str, mime_type: str) -> str | None:
    """Data URL pronta pro `<img src>`, ou None se o arquivo não existe."""
    payload = read_bytes(storage_key)
    if payload is None:
        return None
    encoded = base64.b64encode(payload).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def delete(storage_key: str) -> None:
    """Remove o arquivo do disco. Idempotente — arquivo ausente é tolerado."""
    try:
        path = absolute_path(storage_key)
    except ValueError:
        return
    if path.exists():
        os.remove(path)
