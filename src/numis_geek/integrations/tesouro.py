"""Tesouro Direto historical prices — Tesouro Transparente CKAN CSV.

The Brazilian Treasury publishes daily prices/rates ("Preços e Taxas
Diários dos Títulos Públicos") as a single ~14 MB CSV that spans the
whole history (2002 → today). No pagination, no auth, no query
parameters — it is a full replace file.

Download URL:
    https://www.tesourotransparente.gov.br/ckan/dataset/df56aa42-484a-4a59-8184-7676580c81e3/resource/796d2059-14e9-44e3-80c9-2d9e30b405c1/download/precotaxatesourodireto.csv

Confirmed schema (semicolon-separated, DD/MM/YYYY dates, comma decimals):

    Tipo Titulo;Data Vencimento;Data Base;Taxa Compra Manha;Taxa Venda Manha;PU Compra Manha;PU Venda Manha;PU Base Manha
    Tesouro IPCA+;15/05/2035;26/03/2010;6,19;6,29;422,52;412,68;412,38

A Tesouro bond is identified by the pair (Tipo Titulo, Data Vencimento),
never by an isolated ticker. This module accepts a free-form
`asset_name` and matches against `"{Tipo Titulo} {vencimento_year}"`
plus a few tolerated variants (e.g. accepting the full
DD/MM/YYYY vencimento in the name).

Because the file is heavy we cache it under `data/tesouro_cache/` keyed
by download date — subsequent lookups on the same day skip the network.
Set `TESOURO_CACHE_DIR` to override the location (used by tests).
"""
from __future__ import annotations

import csv
import io
import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

import httpx

TESOURO_CSV_URL = (
    "https://www.tesourotransparente.gov.br/ckan/dataset/"
    "df56aa42-484a-4a59-8184-7676580c81e3/resource/"
    "796d2059-14e9-44e3-80c9-2d9e30b405c1/download/precotaxatesourodireto.csv"
)
DEFAULT_TIMEOUT = 120.0
_DEFAULT_CACHE_DIR = Path("data/tesouro_cache")


class TesouroError(RuntimeError):
    """Raised when the Tesouro Transparente CSV cannot be fetched or parsed."""


@dataclass(frozen=True)
class TesouroRow:
    tipo_titulo: str
    vencimento: date
    data_base: date
    pu_compra_manha: Decimal | None
    pu_venda_manha: Decimal | None
    pu_base_manha: Decimal | None


# --------------------------------------------------------------------------- #
# Cache
# --------------------------------------------------------------------------- #

def _cache_dir() -> Path:
    override = os.environ.get("TESOURO_CACHE_DIR")
    return Path(override) if override else _DEFAULT_CACHE_DIR


def _cache_path(day: date) -> Path:
    return _cache_dir() / f"precotaxatesourodireto_{day.isoformat()}.csv"


def _download_csv(*, timeout: float = DEFAULT_TIMEOUT) -> bytes:
    try:
        r = httpx.get(TESOURO_CSV_URL, timeout=timeout, follow_redirects=True)
        r.raise_for_status()
        return r.content
    except httpx.HTTPError as e:
        raise TesouroError(f"Tesouro Transparente CSV download failed: {e}") from e


def _load_csv_text(*, use_cache: bool = True) -> str:
    """Return the raw CSV text, caching the download once per calendar day."""
    today = datetime.now(timezone.utc).date()
    cache_file = _cache_path(today)

    if use_cache and cache_file.exists():
        try:
            return cache_file.read_text(encoding="utf-8")
        except OSError:
            pass  # fall through to re-download

    raw = _download_csv()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")

    if use_cache:
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(text, encoding="utf-8")
        except OSError:
            # cache is a best-effort optimisation; a read-only FS
            # should not break lookups.
            pass
    return text


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #

def _parse_date(s: str) -> date:
    s = s.strip()
    return date(int(s[6:10]), int(s[3:5]), int(s[0:2]))


def _parse_decimal(s: str) -> Decimal | None:
    s = (s or "").strip()
    if not s:
        return None
    try:
        return Decimal(s.replace(".", "").replace(",", "."))
    except (InvalidOperation, ValueError):
        return None


def _iter_rows(text: str):
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    required = {
        "Tipo Titulo",
        "Data Vencimento",
        "Data Base",
        "PU Compra Manha",
        "PU Venda Manha",
        "PU Base Manha",
    }
    missing = required - set(reader.fieldnames or ())
    if missing:
        raise TesouroError(
            f"Tesouro CSV missing required columns: {sorted(missing)} "
            f"(got {reader.fieldnames!r})"
        )
    for raw in reader:
        try:
            yield TesouroRow(
                tipo_titulo=(raw["Tipo Titulo"] or "").strip(),
                vencimento=_parse_date(raw["Data Vencimento"]),
                data_base=_parse_date(raw["Data Base"]),
                pu_compra_manha=_parse_decimal(raw["PU Compra Manha"]),
                pu_venda_manha=_parse_decimal(raw["PU Venda Manha"]),
                pu_base_manha=_parse_decimal(raw["PU Base Manha"]),
            )
        except (ValueError, KeyError):
            # skip malformed lines instead of aborting the whole file
            continue


# --------------------------------------------------------------------------- #
# Matching
# --------------------------------------------------------------------------- #

_YEAR_RE = re.compile(r"\b(20\d{2})\b")
_FULL_DATE_RE = re.compile(r"\b(\d{2})/(\d{2})/(20\d{2})\b")


def _norm(s: str) -> str:
    """Case-fold + strip diacritics + collapse whitespace + drop punctuation."""
    if not s:
        return ""
    n = unicodedata.normalize("NFKD", s)
    n = "".join(c for c in n if not unicodedata.combining(c))
    n = n.lower()
    n = re.sub(r"[^a-z0-9+ ]+", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def _row_matches(row: TesouroRow, query_tokens: list[str], query_year: int | None,
                 query_full_date: date | None) -> bool:
    tipo_norm = _norm(row.tipo_titulo)

    # Exact vencimento (DD/MM/YYYY) in the query — must match to the day
    if query_full_date is not None and row.vencimento != query_full_date:
        return False

    # Otherwise a bare year must at least match the vencimento year
    if query_full_date is None and query_year is not None:
        if row.vencimento.year != query_year:
            return False

    if not query_tokens:
        return True

    tipo_tokens = tipo_norm.split(" ")

    # All query tokens must appear in tipo; AND tipo must not carry
    # additional distinguishing tokens the query lacks (e.g. "semestrais",
    # "principal") — otherwise "Tesouro IPCA+ 2035" would tie with
    # "Tesouro IPCA+ com Juros Semestrais 15/05/2035".
    if not all(tok in tipo_tokens for tok in query_tokens):
        return False
    extra = set(tipo_tokens) - set(query_tokens)
    # Common noise words that shouldn't count as "extra distinguishing"
    extra -= {"com", "de", "e", "da", "do"}
    if extra:
        return False
    return True


def _pick_price(row: TesouroRow) -> Decimal | None:
    """User's directive: prioritise the buy price ("o que ele pagaria")."""
    if row.pu_compra_manha is not None:
        return row.pu_compra_manha
    if row.pu_base_manha is not None:
        return row.pu_base_manha
    return row.pu_venda_manha


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def fetch_close_on(
    asset_name: str,
    target_date: date,
    *,
    csv_text: str | None = None,
    use_cache: bool = True,
) -> Decimal | None:
    """Return the Tesouro Direto unit price for `asset_name` on `target_date`.

    Matching rules for `asset_name`:
      * Exact "Tipo Titulo" (e.g. `"Tesouro IPCA+"`) — matches any
        vencimento; combine with a year for disambiguation.
      * `"Tesouro IPCA+ 2035"` — filters vencimento year == 2035.
      * `"Tesouro IPCA+ 15/05/2035"` — exact vencimento day.

    Returns `None` when:
      * no row matches (unknown title, wrong day),
      * the match is ambiguous (2+ different bonds satisfy the query).

    Price column priority: `PU Compra Manha` → `PU Base Manha` →
    `PU Venda Manha`. That reflects "o preço que o usuário pagaria hoje"
    per the spec.

    `csv_text` — inject a raw CSV string (used by tests to skip the
    network entirely). When omitted, the file is fetched with a
    per-calendar-day cache.
    """
    if not asset_name or not asset_name.strip():
        return None

    text = csv_text if csv_text is not None else _load_csv_text(use_cache=use_cache)

    # Detect a full DD/MM/YYYY vencimento in the original query BEFORE
    # normalisation strips its punctuation.
    fd = _FULL_DATE_RE.search(asset_name)
    query_full_date: date | None = None
    stripped = asset_name
    if fd:
        try:
            query_full_date = date(int(fd.group(3)), int(fd.group(2)), int(fd.group(1)))
            stripped = _FULL_DATE_RE.sub(" ", stripped)
        except ValueError:
            query_full_date = None

    query_year: int | None = None
    if query_full_date is None:
        ym = _YEAR_RE.search(stripped)
        if ym:
            query_year = int(ym.group(1))
            stripped = _YEAR_RE.sub(" ", stripped)

    query_norm = _norm(stripped)
    query_tokens = [t for t in query_norm.split(" ") if t]

    matched: list[TesouroRow] = []
    matched_keys: set[tuple[str, date]] = set()

    for row in _iter_rows(text):
        if row.data_base != target_date:
            continue
        if not _row_matches(row, query_tokens, query_year, query_full_date):
            continue
        matched.append(row)
        matched_keys.add((row.tipo_titulo, row.vencimento))

    if not matched:
        return None
    if len(matched_keys) > 1:
        # ambiguous — caller must disambiguate
        return None

    return _pick_price(matched[0])
