"""Spec 85 — subcategoria ARCA automática para ações BR e FIIs.

Ordem de decisão (a primeira que responde ganha):
1. Lista curada de tickers conhecidos (B3) — melhor esforço, revisável.
2. Setor/indústria dos fundamentos (brapi `summaryProfile` / yfinance), quando
   o refresh diário já trouxe.
3. Palavras-chave no nome do ativo (FIIs: "recebíveis", "logística", "FOF"…).
4. Padrão: ação → aceleradora; FII → tijolo (o tipo mais comum).

Cada resposta traz uma nota curta ("lista de tickers", "setor: Utilities",
"padrão") que a página de classificação mostra, para o user conferir e
sobrescrever o que estiver errado.
"""
from __future__ import annotations

import json
import re
import unicodedata

from numis_geek.models.arca import ArcaSubcategory as S

# ── Ações BR: raiz do ticker (4 letras) → subcategoria ──────────────────
# Defensivas (vídeo): energia elétrica, saneamento, grandes bancos. Somamos
# seguradoras e teles, que se comportam igual. Dolarizadas: exportadoras de
# commodities, proteína, celulose, aeronaves.
_STOCK_ROOTS: dict[str, S] = {
    **{r: S.EQ_DEFENSIVE for r in (
        # energia
        "TAEE", "TRPL", "ISAE", "EGIE", "CPLE", "CMIG", "ELET", "ENGI", "EQTL",
        "CPFE", "NEOE", "ALUP", "AURE", "ENBR", "TRAN", "CESP", "EMAE",
        # saneamento
        "SBSP", "SAPR", "CSMG", "AMBP",
        # bancos grandes e holdings
        "ITUB", "BBDC", "BBAS", "SANB", "BPAC", "ITSA", "BRSR", "ABCB",
        # seguros / teles
        "BBSE", "CXSE", "PSSA", "IRBR", "VIVT", "TIMS",
    )},
    **{r: S.EQ_DOLLAR for r in (
        "VALE", "CMIN", "SUZB", "KLBN", "GGBR", "GOAU", "CSNA", "USIM", "BRAP",
        "PETR", "PRIO", "RECV", "BRAV", "RRRP", "ENAT", "UGPA",
        "JBSS", "MRFG", "BEEF", "BRFS", "MBRF", "MDIA",
        "EMBR", "WEGE", "SLCE", "SOJA", "AGRO", "RAIZ", "BRKM", "TTEN", "FRAS",
        "TUPY", "RAPT", "POMO", "LEVE",
    )},
}

# ── FIIs: ticker completo → subcategoria (melhor esforço) ────────────────
_FII_TICKERS: dict[str, S] = {
    **{t: S.RE_BRICK for t in (
        "HGLG11", "XPLG11", "BTLG11", "VILG11", "LVBI11", "BRCO11", "GGRC11",
        "XPML11", "VISC11", "HGBS11", "MALL11", "HSML11", "PVBI11", "HGRE11",
        "JSRE11", "RBRP11", "KNRI11", "HGRU11", "TRXF11", "ALZR11", "RBVA11",
        "HGPO11", "BRCR11", "TGAR11", "RZTR11", "GARE11", "PATL11", "LGCP11",
        "XPIN11", "VINO11", "RCRB11", "GTWR11", "SNEL11", "KNHF11",
    )},
    **{t: S.RE_FOF for t in (
        "BCFF11", "HFOF11", "KFOF11", "RBRF11", "MGFF11", "XPSF11", "BTHF11",
        "KISU11", "OUFF11", "SNFF11", "ITRI11", "BLMG11", "RFOF11",
    )},
    **{t: S.RE_PAPER_CDI for t in (
        "KNCR11", "VGIR11", "RZAK11", "KCRE11", "HGCR11", "MXRF11", "KNUQ11",
        "RBHG11", "VCRI11",
    )},
    **{t: S.RE_PAPER_IPCA for t in (
        "KNIP11", "KNSC11", "KNHY11", "CPTS11", "RECR11", "IRDM11", "VRTA11",
        "CVBI11", "RBRR11", "XPCI11", "BCRI11", "VCJR11", "HCTR11", "DEVA11",
        "RBRY11", "PLCR11", "AFHI11", "HABT11",
    )},
}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return s.upper()


_FII_PAPER_WORDS = re.compile(
    r"RECEB|CREDITO|PAPEL|\bCRI\b|HIGH YIELD|SECURITIES|HIGH GRADE|RENDA IMOBILIARIA FIXA"
)
_FII_CDI_WORDS = re.compile(r"\bCDI\b|POS[- ]?FIX|HIGH GRADE")
_FII_FOF_WORDS = re.compile(r"\bFOF\b|FUNDO DE FUNDOS|FUNDOS DE FUNDOS|MULTIESTRATEGIA|HEDGE FUND")
_FII_BRICK_WORDS = re.compile(
    r"LOGIST|SHOPPING|LAJES|CORPORATE|RENDA URBANA|GALP|AGRO|HOSPITAL|EDUCACIONAL|VAREJO|INDUSTRIAL"
)


def sector_hint_from_payload(raw_payload: str | None) -> str | None:
    """'setor | indústria' do raw_payload dos fundamentos (brapi/yfinance)."""
    if not raw_payload:
        return None
    try:
        data = json.loads(raw_payload)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    prof = data.get("summaryProfile") if isinstance(data.get("summaryProfile"), dict) else data
    sector = prof.get("sector") or prof.get("sectorDisp")
    industry = prof.get("industry") or prof.get("industryDisp")
    parts = [p for p in (sector, industry) if isinstance(p, str) and p.strip()]
    return " | ".join(parts) or None


def _stock_from_sector(hint: str) -> S | None:
    h = hint.upper()
    if "UTILITIES" in h or "UTILIDADE" in h or "ENERGIA ELETRICA" in _norm(h) or "SANEAMENTO" in _norm(h):
        return S.EQ_DEFENSIVE
    if "BANK" in h or "INSURANCE" in h or "TELECOM" in h or "BANCO" in _norm(h):
        return S.EQ_DEFENSIVE
    if any(w in h for w in (
        "BASIC MATERIALS", "ENERGY", "OIL", "STEEL", "MINING", "PAPER", "PULP",
        "FARM PRODUCTS", "PACKAGED FOODS", "AGRICULTURAL", "AEROSPACE",
    )):
        return S.EQ_DOLLAR
    return None


def stock_subcategory(ticker: str | None, name: str | None, hint: str | None) -> tuple[S, str]:
    t = (ticker or "").upper().strip()
    root = t[:4]
    if root in _STOCK_ROOTS:
        return _STOCK_ROOTS[root], "lista de tickers"
    if hint:
        sub = _stock_from_sector(hint)
        if sub:
            return sub, f"setor: {hint}"
    return S.EQ_ACCELERATOR, "padrão (fora da lista de defensivas/dolarizadas)"


def fii_subcategory(ticker: str | None, name: str | None, hint: str | None) -> tuple[S, str]:
    t = (ticker or "").upper().strip()
    if t in _FII_TICKERS:
        return _FII_TICKERS[t], "lista de tickers"
    n = _norm(f"{name or ''} {hint or ''}")
    if _FII_FOF_WORDS.search(n):
        return S.RE_FOF, "nome do fundo"
    if _FII_PAPER_WORDS.search(n):
        if _FII_CDI_WORDS.search(n):
            return S.RE_PAPER_CDI, "nome do fundo"
        return S.RE_PAPER_IPCA, "nome do fundo (papel; IPCA por padrão)"
    if _FII_BRICK_WORDS.search(n):
        return S.RE_BRICK, "nome do fundo"
    return S.RE_BRICK, "padrão (tijolo é o tipo mais comum)"
