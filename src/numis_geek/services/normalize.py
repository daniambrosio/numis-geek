"""Spec 68 — shared description normalization.

Single normalization used by BOTH party-alias matching (spec 68/71) and
the transaction dedup fingerprint (spec 70/71). Two divergent
normalizations would silently break the import matching — never fork
this logic.

Rules (in order):
1. uppercase
2. strip `*` (card processors: "UBER *TRIP")
3. drop trailing digit runs and BR state suffixes ("PAO ACUCAR 0042 SP")
4. collapse whitespace, trim
"""
import re

_BR_UFS = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
    "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC",
    "SP", "SE", "TO",
}


def normalize_description(raw: str) -> str:
    s = (raw or "").upper().replace("*", " ")
    # collapse before token inspection
    tokens = s.split()
    # drop trailing tokens that are pure digits or a BR state code
    while tokens and (tokens[-1].isdigit() or tokens[-1] in _BR_UFS):
        tokens.pop()
    s = " ".join(tokens)
    s = re.sub(r"\s+", " ", s).strip()
    return s
