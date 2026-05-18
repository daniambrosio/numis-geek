"""BCB SGS (Sistema Gerenciador de Séries Temporais) client.

PTAX is a single daily rate fixed by BCB by averaging interbank trades.
Series 10813 = PTAX venda (the canonical reference for IRPF and USD-BRL
conversions). The API is free, unauthenticated, and limited to ~10 years
per request (we chunk).

Docs: https://dadosabertos.bcb.gov.br/dataset/dolar-americano-usd-todos-os-boletins-diarios
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable

import httpx

BCB_BASE = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{series}/dados"
SERIES_PTAX = 10813  # PTAX venda — the canonical reference

DEFAULT_TIMEOUT = 30.0
CHUNK_YEARS = 9


class BCBError(RuntimeError):
    """Raised when the BCB SGS call fails (network, 4xx/5xx, malformed)."""


@dataclass(frozen=True)
class PTAXRow:
    date: date
    rate: Decimal


def _fmt(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def _parse_date(s: str) -> date:
    return date(int(s[6:10]), int(s[3:5]), int(s[0:2]))


def _chunks(start: date, end: date) -> Iterable[tuple[date, date]]:
    cur = start
    while cur <= end:
        try:
            chunk_end = min(
                end,
                date(cur.year + CHUNK_YEARS, cur.month, cur.day) - timedelta(days=1),
            )
        except ValueError:  # leap-day edge case
            chunk_end = min(end, date(cur.year + CHUNK_YEARS, cur.month, 28) - timedelta(days=1))
        yield (cur, chunk_end)
        cur = chunk_end + timedelta(days=1)


def fetch_ptax_range(start: date, end: date) -> list[PTAXRow]:
    """Fetch PTAX (venda) rows in [start, end] inclusive."""
    if end < start:
        raise ValueError(f"end ({end}) precedes start ({start})")

    out: dict[date, Decimal] = {}
    with httpx.Client() as client:
        for chunk_start, chunk_end in _chunks(start, end):
            url = BCB_BASE.format(series=SERIES_PTAX)
            params = {
                "formato": "json",
                "dataInicial": _fmt(chunk_start),
                "dataFinal": _fmt(chunk_end),
            }
            try:
                r = client.get(url, params=params, timeout=DEFAULT_TIMEOUT)
                r.raise_for_status()
                data = r.json()
            except httpx.HTTPError as e:
                raise BCBError(f"BCB SGS series {SERIES_PTAX} failed: {e}") from e
            except ValueError as e:
                raise BCBError(f"BCB SGS series {SERIES_PTAX} returned non-JSON: {e}") from e

            if not isinstance(data, list):
                raise BCBError(f"BCB SGS series {SERIES_PTAX} returned non-list: {data!r}")

            for row in data:
                try:
                    d = _parse_date(row["data"])
                    v = Decimal(row["valor"])
                except (KeyError, ValueError, TypeError) as e:
                    raise BCBError(
                        f"BCB SGS series {SERIES_PTAX} malformed row {row!r}: {e}"
                    ) from e
                out[d] = v

    return [PTAXRow(date=d, rate=out[d]) for d in sorted(out.keys())]
