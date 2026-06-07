"""Spec 58 Stage 4 — deterministic parser for Avenue proventos CSV.

The Avenue "Extrato" export has a fixed shape:

  Data transação,Data liquidação,Descrição,Valor,Saldo
  27/05/2026,27/05/2026,Dividendos de WMT,12.32,727.33
  27/05/2026,27/05/2026,Imposto sobre dividendo de WMT,-3.70,715.01
  16/05/2026,18/05/2026,Cupom de T 4.25 15/11/34,212.50,718.71
  13/05/2026,13/05/2026,Rentabilidade de aluguel de ativo,0.64,323.35
  13/05/2026,13/05/2026,Imposto de aluguel de ativo,-0.19,323.16
  13/05/2026,13/05/2026,Taxa sobre ADR de BTI,-0.32,295.71

We pair related rows by (event_date, ticker, family) and emit one
entry per logical income event, with `gross`, `tax`, `net` filled in.

Output shape (mirrors LLM payloads — see services.extraction_templates):
  {
    "as_of_date": "<latest event_date YYYY-MM-DD>",
    "broker_name": "Avenue",
    "events": [
      {
        "event_date": "2026-05-27",
        "ticker_raw": "WMT",
        "type": "DIVIDEND",       # DIVIDEND | INTEREST | SECURITIES_LENDING
        "gross_amount": 12.32,
        "tax_amount": 3.70,        # always positive (absolute value)
        "net_amount": 8.62,
        "currency": "USD",
        "notes": null,
        "confidence": 1.0,         # deterministic parser → 1.0
      },
      ...
    ],
  }

`asset_id` resolution + Distribution creation happens in the apply
layer (not here).
"""
from __future__ import annotations

import csv
import io
import re
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Iterable


# ── Description pattern matchers ───────────────────────────────────────────


# "Dividendos de WMT"
_DIVIDEND_RE = re.compile(r"^\s*Dividendos\s+de\s+(?P<ticker>.+?)\s*$", re.IGNORECASE)
# "Imposto sobre dividendo de WMT"
_TAX_DIVIDEND_RE = re.compile(
    r"^\s*Imposto\s+sobre\s+dividend(?:o|os)\s+de\s+(?P<ticker>.+?)\s*$",
    re.IGNORECASE,
)
# "Taxa sobre ADR de BTI"
_ADR_FEE_RE = re.compile(
    r"^\s*Taxa\s+sobre\s+ADR\s+de\s+(?P<ticker>.+?)\s*$", re.IGNORECASE,
)
# "Cupom de T 4.25 15/11/34"
_COUPON_RE = re.compile(r"^\s*Cupom\s+de\s+(?P<ticker>.+?)\s*$", re.IGNORECASE)
# "Imposto sobre cupom de X" (defensive — not seen in sample but plausible)
_TAX_COUPON_RE = re.compile(
    r"^\s*Imposto\s+sobre\s+cupom\s+de\s+(?P<ticker>.+?)\s*$", re.IGNORECASE,
)
# "Rentabilidade de aluguel de ativo" / "Imposto de aluguel de ativo"
_LENDING_INCOME_RE = re.compile(
    r"^\s*Rentabilidade\s+de\s+aluguel\s+de\s+ativo\s*$", re.IGNORECASE,
)
_LENDING_TAX_RE = re.compile(
    r"^\s*Imposto\s+de\s+aluguel\s+de\s+ativo\s*$", re.IGNORECASE,
)


# Families group multiple description rows into a single income event.
# Each row is tagged with (family, ticker_or_None, role).
FAMILY_DIVIDEND = "DIVIDEND"
FAMILY_COUPON = "COUPON"
FAMILY_LENDING = "LENDING"

ROLE_GROSS = "gross"      # the income leg (positive)
ROLE_TAX = "tax"          # the deduction leg (negative)
ROLE_FEE = "fee"          # ADR fee, treated like tax (subtracted from gross)


# ── parse + classify a single description ──────────────────────────────────


def _classify(desc: str) -> tuple[str, str | None, str] | None:
    """Return (family, ticker, role) for a description, or None if the row
    is one we don't understand (skipped with a warning)."""
    for regex, family, role in (
        (_DIVIDEND_RE,     FAMILY_DIVIDEND, ROLE_GROSS),
        (_TAX_DIVIDEND_RE, FAMILY_DIVIDEND, ROLE_TAX),
        (_ADR_FEE_RE,      FAMILY_DIVIDEND, ROLE_FEE),
        (_COUPON_RE,       FAMILY_COUPON,   ROLE_GROSS),
        (_TAX_COUPON_RE,   FAMILY_COUPON,   ROLE_TAX),
    ):
        m = regex.match(desc)
        if m:
            return family, m.group("ticker").strip(), role
    if _LENDING_INCOME_RE.match(desc):
        return FAMILY_LENDING, None, ROLE_GROSS
    if _LENDING_TAX_RE.match(desc):
        return FAMILY_LENDING, None, ROLE_TAX
    return None


# ── parse a single CSV row ─────────────────────────────────────────────────


def _parse_date_dmy(s: str) -> date | None:
    """Avenue uses DD/MM/YYYY exclusively."""
    s = (s or "").strip()
    if not s:
        return None
    try:
        d, m, y = s.split("/")
        return date(int(y), int(m), int(d))
    except (ValueError, AttributeError):
        return None


def _parse_amount(s: str) -> Decimal | None:
    """Avenue uses '.' as decimal separator and no thousands separator
    (e.g. '12.32', '-3.70'). Returns Decimal preserving sign."""
    s = (s or "").strip()
    if not s:
        return None
    try:
        return Decimal(s)
    except Exception:
        return None


# ── main entry point ────────────────────────────────────────────────────────


def parse_avenue_proventos_csv(blob: bytes) -> dict:
    """Parse the Avenue proventos CSV and return a payload dict.

    The result shape matches what a hypothetical LLM extraction would
    return for a BROKER_INCOME job, so downstream apply code is the
    same regardless of source.
    """
    text = blob.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text))

    # Group rows by (event_date_iso, family, ticker_or_None).
    # Each group accumulates one gross leg + optional tax/fee legs.
    Group = dict[str, Decimal]  # role → amount (always positive)
    groups: dict[tuple[str, str, str | None], Group] = defaultdict(
        lambda: {ROLE_GROSS: Decimal("0"), ROLE_TAX: Decimal("0"), ROLE_FEE: Decimal("0")},
    )
    unparsed: list[str] = []

    for row in reader:
        # Use Data liquidação as event_date (when the cash effectively
        # arrives). Falls back to Data transação when missing.
        event_d = (
            _parse_date_dmy(row.get("Data liquidação", ""))
            or _parse_date_dmy(row.get("Data transação", ""))
        )
        desc = (row.get("Descrição") or "").strip()
        amount = _parse_amount(row.get("Valor", ""))
        if event_d is None or not desc or amount is None:
            continue

        cls = _classify(desc)
        if cls is None:
            unparsed.append(desc)
            continue

        family, ticker, role = cls
        key = (event_d.isoformat(), family, ticker)
        groups[key][role] += amount.copy_abs()

    # Convert groups → events.
    events: list[dict] = []
    for (date_iso, family, ticker), parts in sorted(
        groups.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2] or ""),
    ):
        gross = parts[ROLE_GROSS]
        tax = parts[ROLE_TAX] + parts[ROLE_FEE]
        if gross == 0:
            # All-tax / orphan row — skip rather than create a negative event.
            continue
        net = gross - tax
        type_str = {
            FAMILY_DIVIDEND: "DIVIDEND",
            FAMILY_COUPON: "INTEREST",
            FAMILY_LENDING: "SECURITIES_LENDING",
        }[family]
        events.append({
            "event_date": date_iso,
            "ticker_raw": ticker,
            "type": type_str,
            "gross_amount": float(gross),
            "tax_amount": float(tax) if tax > 0 else None,
            "net_amount": float(net),
            "currency": "USD",
            "notes": None,
            "confidence": 1.0,
        })

    as_of = max((e["event_date"] for e in events), default=None)
    return {
        "as_of_date": as_of,
        "broker_name": "Avenue",
        "events": events,
        "_unparsed_descriptions": unparsed,  # diagnostics; apply path can warn
    }


# ── convenience for tests / CLI ─────────────────────────────────────────────


def summarize(payload: dict) -> Iterable[str]:
    """Yield human-readable summary lines (used by tests + ad-hoc debug)."""
    yield f"as_of={payload.get('as_of_date')} broker={payload.get('broker_name')}"
    for e in payload.get("events", []):
        t = e.get("ticker_raw") or "—"
        yield (
            f"  {e['event_date']} {e['type']:<18} {t:<24} "
            f"gross={e['gross_amount']:>10.2f}  tax={e['tax_amount']}  "
            f"net={e['net_amount']:>10.2f}"
        )
    if payload.get("_unparsed_descriptions"):
        yield f"!! {len(payload['_unparsed_descriptions'])} unparsed rows:"
        for d in payload["_unparsed_descriptions"]:
            yield f"   - {d}"
