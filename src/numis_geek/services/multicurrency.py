"""Spec 84 — conta multimoeda (Wise): valor de cada linha na moeda da conta.

Isolado do resto do import de propósito: hoje a Wise é UMA conta em reais
(decisão do user, 2026-11-02) e cada gasto é convertido pela cotação do dia
da moeda que SAIU do jar. Se um dia o roteamento por moeda voltar (conta
por jar), é aqui que ele entra — o classify só chama `convert_jar`.

Cotação, em ordem:
1. jar USD → PTAX (tabela local, walkback de 10 dias; mais antiga → aviso);
2. jar EUR/GBP/… → PTAX da moeda no BCB (Olinda), buscada uma vez no 1º
   preview e guardada no job (`extracted_json["_fx_rates"]`), pra preview e
   apply darem o mesmo número;
3. moeda sem cotação no BCB (CLP, UYU, ARS…) → cruzada: taxa moeda/USD
   implícita no próprio documento (conversão entre jars ou linha de 2
   valores mais perto da data) × PTAX;
4. nada → a linha importa com o valor do jar sem conversão + aviso (o user
   corrige).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from numis_geek.models.extraction_job import ExtractionJob
from numis_geek.models.ptax_rate import PTAXRate

CENT = Decimal("0.01")
RATE_Q = Decimal("0.00000001")
WALKBACK_DAYS = 10
NATIVE = ("BRL", "USD")      # moedas que a tabela local de PTAX já cobre
FX_CACHE_KEY = "_fx_rates"


def _d(v) -> Decimal | None:
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _date(v) -> date | None:
    try:
        return date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


def ptax_row(db: Session, d: date):
    return db.query(PTAXRate).filter(PTAXRate.date <= min(d, date.today())).order_by(PTAXRate.date.desc()).first()


# ── BCB por moeda, persistido no job ─────────────────────────────────────────

def needed_currencies(payload: dict) -> dict[str, tuple[date, date]]:
    """Moedas de jar fora de BRL/USD em linhas que NÃO são conversão → faixa de datas."""
    out: dict[str, list[date]] = defaultdict(list)
    for ln in payload.get("transactions") or []:
        cur = (ln.get("jar_currency") or "").upper()
        d = _date(ln.get("event_date"))
        if cur and cur not in NATIVE and d and ln.get("line_kind") != "CONVERSION":
            out[cur].append(d)
    return {c: (min(ds), max(ds)) for c, ds in out.items()}


def ensure_fx_rates(db: Session, job: ExtractionJob) -> None:
    """Busca no BCB (uma vez) a PTAX das moedas de jar que faltam e grava no
    job. Falha de rede fica registrada e é tentada de novo no próximo
    preview; o apply só lê o que está gravado."""
    payload = job.extracted_json or {}
    need = needed_currencies(payload)
    if not need:
        return
    cache = dict(payload.get(FX_CACHE_KEY) or {})
    changed = False
    from numis_geek.integrations import bcb
    for cur, (lo, hi) in need.items():
        entry = cache.get(cur) or {}
        if entry.get("fetched") and not entry.get("error"):
            continue
        try:
            rows = bcb.fetch_currency_ptax_range(cur, lo - timedelta(days=WALKBACK_DAYS), hi)
            cache[cur] = {"fetched": True, "rates": {r.date.isoformat(): str(r.rate) for r in rows}}
        except Exception as exc:  # rede/BCB fora: tenta de novo no próximo preview
            cache[cur] = {"fetched": True, "error": str(exc)[:200], "rates": entry.get("rates") or {}}
        changed = True
    if changed:
        job.extracted_json = {**payload, FX_CACHE_KEY: cache}
        flag_modified(job, "extracted_json")
        db.flush()


def _bcb_rate(cache: dict, cur: str, d: date) -> tuple[Decimal, date] | None:
    rates = ((cache.get(cur) or {}).get("rates")) or {}
    for k in range(WALKBACK_DAYS + 1):
        day = d - timedelta(days=k)
        v = rates.get(day.isoformat())
        if v is not None:
            return Decimal(v), day
    return None


# ── taxa implícita no documento (moeda/USD) ──────────────────────────────────

def implied_usd_rates(payload: dict) -> dict[str, list[tuple[date, Decimal]]]:
    """USD por unidade de cada moeda, das linhas com 2 valores em que um lado
    é USD ("236,100 ARS / 160.70 USD", "To USD · 4.54 USD · 4,365 CLP")."""
    out: dict[str, list[tuple[date, Decimal]]] = defaultdict(list)
    for ln in payload.get("transactions") or []:
        d = _date(ln.get("event_date"))
        a, ac = _d(ln.get("jar_amount")), (ln.get("jar_currency") or "").upper()
        b, bc = _d(ln.get("merchant_amount")), (ln.get("merchant_currency") or "").upper()
        if not d or not a or not b or a == 0 or b == 0 or ac == bc:
            continue
        if ac == "USD" and bc not in NATIVE:
            out[bc].append((d, abs(a) / abs(b)))
        elif bc == "USD" and ac not in NATIVE:
            out[ac].append((d, abs(b) / abs(a)))
    return out


def implied_brl_rates(payload: dict) -> dict[str, list[tuple[date, Decimal]]]:
    """BRL por unidade, direto do documento: conversão BRL→UYU ("To UYU ·
    7,085.86 UYU · 1,000 BRL") ou envio em CLP pago do jar BRL. Melhor que
    cruzar via USD quando está mais perto da data."""
    out: dict[str, list[tuple[date, Decimal]]] = defaultdict(list)
    for ln in payload.get("transactions") or []:
        d = _date(ln.get("event_date"))
        a, ac = _d(ln.get("jar_amount")), (ln.get("jar_currency") or "").upper()
        b, bc = _d(ln.get("merchant_amount")), (ln.get("merchant_currency") or "").upper()
        if not d or not a or not b or a == 0 or b == 0 or ac == bc:
            continue
        if ac == "BRL" and bc not in NATIVE:
            out[bc].append((d, abs(a) / abs(b)))
        elif bc == "BRL" and ac not in NATIVE:
            out[ac].append((d, abs(b) / abs(a)))
    return out


def _nearest(rates: list[tuple[date, Decimal]], d: date) -> tuple[Decimal, date] | None:
    if not rates:
        return None
    day, r = min(((x[0], x[1]) for x in rates), key=lambda x: abs((x[0] - d).days))
    return r, day


# ── conversão ────────────────────────────────────────────────────────────────

def convert_jar(
    db: Session, d: date, jar_amount: Decimal, jar_currency: str, account_currency: str,
    cache: dict, implied: dict[str, list[tuple[date, Decimal]]],
) -> dict:
    """{converted, rate (moeda da conta por unidade do jar), rate_source,
    rate_date, tx_fx_rate (PTAX explícita quando fora da janela), cross,
    warning}. `jar_currency == account_currency` nunca chega aqui."""
    jar_currency = jar_currency.upper()
    warning = None
    cross = None
    ptax = ptax_row(db, d)
    ptax_rate = Decimal(ptax.rate) if ptax else None
    ptax_stale = bool(ptax and (min(d, date.today()) - ptax.date).days > WALKBACK_DAYS)

    if jar_currency == "BRL":
        brl_per_unit, source, rate_day = Decimal(1), "NATIVE", d
    elif jar_currency == "USD":
        if ptax is None:
            return _no_rate(jar_amount, jar_currency, d)
        brl_per_unit, rate_day = ptax_rate, ptax.date
        source = "PTAX_STALE" if ptax_stale else "PTAX"
    else:
        hit = _bcb_rate(cache, jar_currency, d)
        if hit is not None:
            brl_per_unit, rate_day = hit
            source = "BCB"
        else:
            via_usd = _nearest(implied.get(jar_currency, []), d) if ptax_rate is not None else None
            via_brl = _nearest(implied.get(("BRL", jar_currency), []), d)
            # a taxa implícita mais perto da data ganha
            pick = min(
                [c for c in (("USD", via_usd), ("BRL", via_brl)) if c[1] is not None],
                key=lambda c: abs((c[1][1] - d).days), default=None,
            )
            if pick is None:
                return _no_rate(jar_amount, jar_currency, d)
            leg, (r_imp, imp_day) = pick
            if leg == "USD":
                brl_per_unit = (r_imp * ptax_rate).quantize(RATE_Q)
                rate_day = ptax.date
                cross = {"usd_per_unit": str(r_imp.quantize(RATE_Q)), "implied_date": imp_day.isoformat(),
                         "ptax": str(ptax_rate)}
            else:
                brl_per_unit, rate_day = r_imp.quantize(RATE_Q), imp_day
                cross = {"brl_per_unit": str(r_imp.quantize(RATE_Q)), "implied_date": imp_day.isoformat()}
            source = "CROSS"
    if ptax_stale and source in ("PTAX_STALE", "CROSS"):
        warning = f"Sem PTAX até {WALKBACK_DAYS} dias antes de {d.strftime('%d/%m/%Y')} — usei a de {ptax.date.strftime('%d/%m/%Y')}"

    value_brl = Decimal(jar_amount) * brl_per_unit
    if account_currency == "BRL":
        converted, rate = value_brl, brl_per_unit
    else:   # conta USD (Nomad): BRL ÷ PTAX
        if ptax_rate is None:
            return _no_rate(jar_amount, jar_currency, d)
        converted, rate = value_brl / ptax_rate, (brl_per_unit / ptax_rate).quantize(RATE_Q)
    # A tx guarda a PTAX canônica do dia (fx_rate); explícita só quando a
    # tabela não tem PTAX na janela (senão o serviço resolve sozinho).
    tx_fx = ptax_rate if ptax_stale else None
    return {
        "amount": Decimal(jar_amount), "currency": jar_currency, "converted": converted.quantize(CENT),
        "rate": rate.quantize(RATE_Q), "rate_source": source, "rate_date": rate_day,
        "tx_fx_rate": tx_fx, "cross": cross, "warning": warning,
    }


def _no_rate(jar_amount: Decimal, jar_currency: str, d: date) -> dict:
    return {
        "amount": Decimal(jar_amount), "currency": jar_currency, "converted": Decimal(jar_amount).quantize(CENT),
        "rate": Decimal(1), "rate_source": "NONE", "rate_date": d, "tx_fx_rate": None, "cross": None,
        "warning": f"Sem cotação de {jar_currency} pra {d.strftime('%d/%m/%Y')} — gravado com o valor em "
                   f"{jar_currency} sem conversão; corrija o valor depois",
    }
