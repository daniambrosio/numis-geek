"""Spec 58 Stage 4 — deterministic per-FI/per-purpose file parsers.

These bypass the LLM entirely when the upload matches a known
(institution, source_hint, mime_type) tuple. Output mirrors the shape
the LLM would have produced, so downstream apply paths are unchanged.

Add new parsers as `_BY_KEY[(fi_lower, hint, mime)] = parser_func`. The
extraction service consults `parser_for(...)` before falling back to
the LLM.
"""
from __future__ import annotations

from typing import Callable

from numis_geek.models.extraction_job import ExtractionSourceHint

from numis_geek.services.extraction_parsers.avenue_proventos import (
    parse_avenue_proventos_csv,
)


# (fi_short_name_lower, source_hint, mime_type) → parser fn(bytes) → dict
ParserFn = Callable[[bytes], dict]

_BY_KEY: dict[tuple[str, ExtractionSourceHint, str], ParserFn] = {
    ("avenue", ExtractionSourceHint.BROKER_INCOME, "text/csv"):
        parse_avenue_proventos_csv,
}


def parser_for(
    *,
    institution_short_name: str | None,
    source_hint: ExtractionSourceHint,
    mime_type: str | None,
) -> ParserFn | None:
    """Return the deterministic parser for this combination, or None to
    fall back to the LLM."""
    if not institution_short_name or not mime_type:
        return None
    key = (institution_short_name.strip().lower(), source_hint, mime_type.strip().lower())
    return _BY_KEY.get(key)
