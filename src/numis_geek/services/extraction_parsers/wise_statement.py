"""Spec 84 — Wise "all transactions" PDF (impressão da página web) → linhas.

Determinístico (sem LLM): o PDF tem camada de texto e um formato fixo. Uma
lista só, da mais nova pra mais antiga, com todas as moedas:

    19 October                      ← cabeçalho de data (sem ano = ano corrente)
    Refund Globalblue.com + 6.12 BRL   ← nome + valor na mesma linha
    AQUA Hotel                      ← nome
    2 EUR                           ← 2 valores: comerciante / jar
    2.25 USD
    To EUR                          ← conversão entre jars
    Moved
    178.69 EUR                      ← recebido
    200 USD                         ← saiu do jar
    19 October 2025                 ← ano explícito nos anos anteriores

Regras:
- linha com 2 valores: o jar é o SEGUNDO; com 1 valor, é ele;
- "+" = entrou no saldo; sem sinal = saiu;
- "To XXX" + Moved/Added = CONVERSION (o 1º valor entrou, o 2º saiu);
- "Sent" = envio a terceiro; "Assets fee" = FEE; "Cashback"; "Refund …";
  entrada "+" de pessoa = DEPOSIT;
- o ano corrente sai do rodapé de impressão ("11/2/26, 12:02 PM") ou da URL
  (to=2026-11-02), nunca de "hoje".

Saída no mesmo formato do template BANK_STATEMENT_WISE, então o resto do
pipeline (classify/apply) não sabe de onde veio. PDF sem texto →
`NotApplicable` (o serviço cai pro LLM).
"""
from __future__ import annotations

import re
from datetime import date

MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"], start=1)}

_DATE = re.compile(r"^(\d{1,2}) (" + "|".join(MONTHS) + r")(?: (\d{4}))?$")
_AMOUNT = r"([+\-])?\s?(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?) ([A-Z]{3})"
_AMOUNT_LINE = re.compile(r"^" + _AMOUNT + r"$")
_INLINE = re.compile(r"^(.*?\S)\s*" + _AMOUNT + r"$")
_STATUS = {"Moved", "Added", "Sent", "Card checked", "Cancelled", "Declined"}
# Não movimentam dinheiro: verificação de cartão (0 GBP), cancelada, recusada.
_NO_MONEY = {"Card checked", "Cancelled", "Declined"}
# "EUR, USD" depois do valor: pago com mais de um saldo (split não informado).
_MULTI_JAR = re.compile(r"^[A-Z]{3}(?:, [A-Z]{3})+$")
_FOOTER_TAIL = " Home Cards Recipients Payments"
_NOISE = (
    re.compile(r"^Transactions$"),
    re.compile(r"^Search Filters"),
    re.compile(r"^Home Cards Recipients Payments$"),
    re.compile(r"Wise - Home$"),
    re.compile(r"^https?://"),
    re.compile(r"^Earn R\$"),
)
_PRINT_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{2}), \d{1,2}:\d{2}")
_URL_TO = re.compile(r"[?&]to=(\d{4})-(\d{2})-(\d{2})")


class NotApplicable(ValueError):
    """Not a Wise text PDF — the extraction service falls back to the LLM."""


def pdf_pages_text(blob: bytes) -> list[str]:
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:
        raise NotApplicable("pypdfium2 indisponível") from exc
    try:
        doc = pdfium.PdfDocument(blob)
    except Exception as exc:
        raise NotApplicable(f"PDF ilegível: {exc}") from exc
    return [doc[i].get_textpage().get_text_range() for i in range(len(doc))]


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def export_year(lines: list[str]) -> int | None:
    for ln in lines:
        m = _URL_TO.search(ln)
        if m:
            return int(m.group(1))
    for ln in lines:
        m = _PRINT_DATE.match(ln)
        if m:
            return 2000 + int(m.group(3))
    return None


def _is_noise(ln: str) -> bool:
    return any(p.search(ln) for p in _NOISE)


def parse_text(pages: list[str]) -> dict:
    raw = [ln.strip() for p in pages for ln in p.replace("\r", "").split("\n")]
    year_now = export_year(raw)
    if year_now is None:
        raise NotApplicable("não parece o extrato 'all transactions' da Wise")
    lines = []
    for ln in raw:
        if not ln:
            continue
        if ln.endswith(_FOOTER_TAIL):
            ln = ln[: -len(_FOOTER_TAIL)].strip()
        if ln and not _is_noise(ln):
            lines.append(ln)

    entries: list[dict] = []
    warnings: list[str] = []
    cur_date: date | None = None
    cur_text: str | None = None
    entry: dict | None = None

    skipped_no_money = 0

    def close() -> None:
        nonlocal entry, skipped_no_money
        if entry is None:
            return
        if entry["status"] in _NO_MONEY or (entry["amounts"] and all(a[1] == 0 for a in entry["amounts"])):
            skipped_no_money += 1
        elif not entry["amounts"]:
            warnings.append(f"Linha sem valor ignorada: {entry['name']} ({entry['date_text']})")
        else:
            entries.append(entry)
        entry = None

    for ln in lines:
        m = _DATE.match(ln)
        if m:
            close()
            y = int(m.group(3)) if m.group(3) else year_now
            cur_date = date(y, MONTHS[m.group(2)], int(m.group(1)))
            cur_text = ln
            continue
        if ln in _STATUS:
            if entry is not None:
                entry["status"] = ln
            continue
        if _MULTI_JAR.match(ln):
            if entry is not None:
                entry["multi_jar"] = ln
            continue
        am = _AMOUNT_LINE.match(ln)
        if am:
            if entry is not None and len(entry["amounts"]) < 2:
                entry["amounts"].append((am.group(1) or "", _num(am.group(2)), am.group(3)))
            else:
                warnings.append(f"Valor solto ignorado: {ln} ({cur_text})")
            continue
        close()
        if cur_date is None:
            warnings.append(f"Linha antes do 1º cabeçalho de data ignorada: {ln}")
            continue
        entry = {"name": ln, "date": cur_date, "date_text": cur_text, "status": None, "amounts": [], "multi_jar": None}
        im = _INLINE.match(ln)
        if im:
            entry["name"] = im.group(1).rstrip(" +")
            entry["amounts"].append((im.group(2) or "", _num(im.group(3)), im.group(4)))
    close()
    if skipped_no_money:
        warnings.append(f"{skipped_no_money} linha(s) sem movimento de dinheiro ignoradas "
                        "(verificação de cartão, cancelada, recusada)")

    out = [_to_line(e) for e in entries]
    dates = [e["date"] for e in entries]
    return {
        "institution_name": "Wise",
        "period": {"start": min(dates).isoformat(), "end": max(dates).isoformat()} if dates else None,
        "transactions": out,
        "parse_warnings": warnings,
        "confidence": 1.0,
    }


def _signed(sign: str, value: float, *, outflow_default: bool = True) -> float:
    if sign == "+":
        return value
    if sign == "-":
        return -value
    return -value if outflow_default else value


def _to_line(e: dict) -> dict:
    name, amounts, status = e["name"], e["amounts"], e["status"]
    first = amounts[0]
    second = amounts[1] if len(amounts) > 1 else None
    if name.startswith("To ") or (status in ("Moved", "Added") and name.split()[0] == "To"):
        kind = "CONVERSION"
        # 1º valor entrou num jar, 2º saiu do outro
        merchant = (abs(first[1]), first[2])
        jar = (-abs(second[1]), second[2]) if second else (-abs(first[1]), first[2])
        if not second:
            merchant = (None, None)
    else:
        if status == "Sent":
            kind = "SENT"
        elif name.lower().startswith("assets fee") or name.lower().endswith(" fee"):
            kind = "FEE"
        elif name.lower().startswith("cashback"):
            kind = "CASHBACK"
        elif name.lower().startswith("refund"):
            kind = "REFUND"
        elif first[0] == "+":
            kind = "DEPOSIT"
        else:
            kind = "SPEND"
        inflow = first[0] == "+" or kind in ("CASHBACK", "REFUND", "DEPOSIT")
        if second:
            merchant = (abs(first[1]) * (1 if inflow else -1), first[2])
            jar = (abs(second[1]) * (1 if inflow else -1), second[2])
        else:
            merchant = (None, None)
            jar = (abs(first[1]) * (1 if inflow else -1), first[2])
    counterparty = name if kind in ("DEPOSIT", "SENT") else None
    return {
        "date_text": e["date_text"],
        "event_date": e["date"].isoformat(),
        "description": name,
        "line_kind": kind,
        "amount": jar[0],
        "currency": jar[1],
        "jar_amount": jar[0],
        "jar_currency": jar[1],
        "merchant_amount": merchant[0],
        "merchant_currency": merchant[1],
        "counterparty": counterparty,
        "multi_jar": e.get("multi_jar"),
        "confidence": 1.0,
    }


def parse_wise_statement_pdf(blob: bytes) -> dict:
    pages = pdf_pages_text(blob)
    if not any(p.strip() for p in pages):
        raise NotApplicable("PDF sem camada de texto")
    return parse_text(pages)
