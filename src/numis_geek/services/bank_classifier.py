"""Spec 71 (2026-11-02) — "System 1": one fast LLM pass that suggests a
category (and, when obvious, the conta a pagar/receber) for every line of an
extracted statement / card invoice.

Inputs per line: date, description, amount, line_kind, counterparty — plus
the workspace's real category tree, **retrieved history** (the user's own
past categorized transactions with the same alias/counterparty/party, last
few, with category and amount) and the PENDING occurrences in the window.

Category is NEVER a party default: the same party (Mercado Livre) pays
salary, sells on the marketplace and runs financial services. History is
evidence; the line in context decides. Learning is free — confirmed imports
become history for the next one.

The result is persisted on `extraction_job.classification_json` (run once
per job: at extraction time, or lazily on the first preview of a job
extracted before this existed) so classify/apply stay deterministic. Cost is
added to the job's tokens/cost_usd. Any failure is recorded and the import
goes on without suggestions — System 1 never blocks an import.
"""
from __future__ import annotations

import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from numis_geek.integrations.llm import LLMCall, get_llm_client, parse_json_block
from numis_geek.models.category import Category
from numis_geek.models.extraction_job import ExtractionJob
from numis_geek.models.party import Party, PartyAlias
from numis_geek.models.scheduled_transaction import ScheduledStatus, ScheduledTransaction
from numis_geek.models.transaction import Transaction
from numis_geek.services.normalize import normalize_description

# Fast/cheap classifier (claude-api skill, 2026-11-02): $0.10 in / $0.50 out per MTok.
SYSTEM1_MODEL = "claude-haiku-5-5"
# v2 (2026-11-02): exemplos do Notion (category_example) + atalho de
# categoria dominante. Versão diferente no job → re-classifica no preview.
SYSTEM1_VERSION = "system1-v2"
NOTION_PER_LINE = 3
DOMINANT_SHARE = 0.8          # categoria com ≥80% dos lançamentos do grupo…
DOMINANT_MIN_COUNT = 3        # … e pelo menos 3 → sugestão determinística
DOMINANT_CONFIDENCE = 0.85
CHUNK_LINES = 30  # 60 linhas davam ~7,3k tokens de saída — encostava no max_tokens e cortava o JSON
HISTORY_PER_LINE = 3
HISTORY_POOL = 3000          # most recent categorized tx scanned for examples
# Suggestion is pre-selected only from this confidence up; below it stays
# "Sem categoria" with the suggestion shown as a hint.
CONFIDENT = 0.7

SYSTEM_PROMPT = (
    "Você classifica movimentações de extrato bancário / fatura de cartão de um "
    "usuário brasileiro nas CATEGORIAS DELE.\n\n"
    "Para cada linha recebida, escolha UMA categoria da lista CATEGORIAS (use o id "
    "exatamente como dado) ou null quando não houver evidência suficiente.\n\n"
    "REGRAS:\n"
    "- A categoria vem da LINHA EM CONTEXTO (descrição, valor, sinal, tipo, "
    "contraparte). NÃO existe categoria fixa por fornecedor: a mesma empresa pode "
    "pagar salário (receita), vender no marketplace (despesa) e prestar serviço "
    "financeiro (tarifa/juros). `historico` = lançamentos JÁ CONFIRMADOS no Numis "
    "(mais recentes — quando discordam do Notion, ganham). `historico_notion` = "
    "grupos de lançamentos que o usuário classificou no Notion (count, faixa de "
    "valor). Use os EXEMPLOS DO HISTÓRICO como evidência de como "
    "ESTE usuário classifica linhas parecidas — mas confira se o contexto (sinal, "
    "valor, tipo) é o mesmo.\n"
    "- Entrada (valor positivo) só vai pra categoria de RECEITA ou TRANSFERÊNCIA; "
    "saída (negativo) pra DESPESA ou TRANSFERÊNCIA. Transferência entre contas "
    "próprias, aplicação/resgate e pagamento de fatura de cartão são TRANSFER.\n"
    "- confidence de 0 a 1: alta (≥0.8) só com exemplo do histórico batendo ou "
    "descrição inequívoca; genérica (\"PIX TRANSF\", \"DDA PAG TIT\") sem histórico → "
    "baixa ou null.\n"
    "- occurrence_id: só quando a linha claramente quita uma das CONTAS A PAGAR/"
    "RECEBER listadas (mesmo sentido, valor e data compatíveis). Senão null.\n"
    "- reason: até 12 palavras em português explicando (ex.: \"igual a 3 lançamentos "
    "anteriores em Mercado\").\n\n"
    "RESPOSTA: APENAS JSON, sem markdown: {\"lines\": [{\"i\": int, \"category_id\": "
    "str|null, \"confidence\": float, \"occurrence_id\": str|null, \"reason\": str}]} "
    "— uma entrada por linha recebida, mesmo i."
)


def _alias_key(text: str | None) -> str:
    from numis_geek.services.bank_import import alias_key
    return alias_key(text or "")


def category_tree(db: Session, workspace_id: str) -> list[dict]:
    """Active subcategories (the only valid targets) with 'Raiz › Sub' path."""
    cats = db.query(Category).filter(Category.workspace_id == workspace_id).all()
    by_id = {c.id: c for c in cats}
    out = []
    for c in cats:
        if c.parent_id is None or not c.is_active:
            continue
        root = by_id.get(c.parent_id)
        if root is not None and not root.is_active:
            continue
        out.append({
            "id": c.id,
            "path": f"{root.name if root else '?'} › {c.name}",
            "kind": c.kind.value if c.kind else None,
        })
    out.sort(key=lambda x: x["path"])
    return out


def _history_index(db: Session, workspace_id: str, paths: dict[str, str]) -> tuple[dict, dict]:
    """Recent categorized tx indexed by alias key and by party."""
    rows = db.query(Transaction).filter(
        Transaction.workspace_id == workspace_id,
        Transaction.category_id.isnot(None),
    ).order_by(Transaction.event_date.desc(), Transaction.created_at.desc()).limit(HISTORY_POOL).all()
    by_key: dict[str, list[dict]] = defaultdict(list)
    by_party: dict[str, list[dict]] = defaultdict(list)
    for t in rows:
        if t.category_id not in paths:
            continue
        ex = {
            "date": t.event_date.isoformat(), "description": t.description,
            "amount": str(t.amount), "category": paths[t.category_id],
        }
        by_key[_alias_key(t.description)].append(ex)
        if t.party_id:
            by_party[t.party_id].append(ex)
    return by_key, by_party


def _notion_index(db: Session, workspace_id: str, paths: dict[str, str]) -> dict[tuple[str, str], list[dict]]:
    """category_example (Notion) → {(alias_key, direction): [grupo, …]} só
    com categorias ainda ativas. Não são transações: só evidência."""
    from numis_geek.models.category_example import CategoryExample
    idx: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for e in db.query(CategoryExample).filter(CategoryExample.workspace_id == workspace_id).all():
        if e.category_id not in paths:
            continue
        idx[(e.alias_key, e.direction)].append({
            "fonte": "Notion", "category_id": e.category_id, "category": paths[e.category_id],
            "count": e.count,
            "faixa": f"{e.min_amount}–{e.max_amount}" if e.min_amount is not None else None,
            "media": str(e.avg_amount) if e.avg_amount is not None else None,
        })
    for lst in idx.values():
        lst.sort(key=lambda g: -g["count"])
    return idx


def _direction(amount: str) -> str:
    return "out" if Decimal(amount) < 0 else "in"


def _notion_for_line(ln: dict, idx: dict) -> list[dict]:
    """Grupos do Notion da linha: contraparte do Pix primeiro, depois a
    descrição sem datas; mesmo sentido (entrada/saída)."""
    d = _direction(ln["amount"])
    for k in (_alias_key(ln.get("counterparty")), _alias_key(ln["description"])):
        if k and idx.get((k, d)):
            return idx[(k, d)]
    return []


def _dominant(groups: list[dict]) -> dict | None:
    total = sum(g["count"] for g in groups)
    if not groups or total <= 0:
        return None
    top = groups[0]
    if top["count"] >= DOMINANT_MIN_COUNT and top["count"] / total >= DOMINANT_SHARE:
        return {"category_id": top["category_id"], "category": top["category"], "count": top["count"]}
    return None


def _real_majority(by_key, by_party, alias_party, ln: dict, paths: dict[str, str]) -> str | None:
    """Categoria mais frequente nas transações JÁ confirmadas no Numis com o
    mesmo texto (e sinal) — ganha do Notion quando discorda."""
    neg = Decimal(ln["amount"]) < 0
    by_path = {p: cid for cid, p in paths.items()}
    counts: dict[str, int] = defaultdict(int)
    for k in (_alias_key(ln.get("counterparty")), _alias_key(ln["description"])):
        if not k:
            continue
        exs = list(by_key.get(k, []))
        pid = alias_party.get(k)
        if pid:
            exs += by_party.get(pid, [])
        for e in exs:
            if (Decimal(e["amount"]) < 0) == neg and e["category"] in by_path:
                counts[by_path[e["category"]]] += 1
    if not counts:
        return None
    return max(counts.items(), key=lambda kv: kv[1])[0]


def _apply_dominant(lines: dict[str, dict], dominant: dict[int, dict]) -> None:
    """Atalho determinístico: grupo do Notion com uma categoria dominante.
    LLM inseguro (ou sem resposta) → vira a sugestão, com o motivo; LLM
    concordando → sobe a confiança; LLM confiante noutra categoria (viu o
    contexto) → fica a do LLM."""
    for i, dom in dominant.items():
        cur = lines.get(str(i)) or {}
        reason = f"igual a {dom['count']} lançamentos do Notion em {dom['category']}"
        if cur.get("category_id") == dom["category_id"]:
            cur["confidence"] = max(cur.get("confidence") or 0, DOMINANT_CONFIDENCE)
            cur["reason"] = cur.get("reason") or reason
        elif not cur.get("category_id") or (cur.get("confidence") or 0) < CONFIDENT:
            cur.update(category_id=dom["category_id"], category_path=dom["category"],
                       confidence=DOMINANT_CONFIDENCE, reason=reason, source="notion")
            cur.setdefault("occurrence_id", None)
        else:
            continue
        lines[str(i)] = cur


def _party_by_alias(db: Session, workspace_id: str) -> dict[str, str]:
    rows = db.query(PartyAlias.alias_normalized, PartyAlias.party_id).join(
        Party, Party.id == PartyAlias.party_id,
    ).filter(PartyAlias.workspace_id == workspace_id, Party.is_active == True).all()  # noqa: E712
    return {a: p for a, p in rows}


def build_lines(job: ExtractionJob) -> list[dict]:
    from numis_geek.services.bank_import import _money, _parse_date, line_kind_of
    out = []
    for i, line in enumerate((job.extracted_json or {}).get("transactions") or []):
        d = _parse_date(line.get("event_date"))
        amount = _money(line.get("amount"))
        desc = (line.get("description") or "").strip()
        if d is None or amount is None or not desc:
            continue
        out.append({
            "i": i, "date": d.isoformat(), "description": desc, "amount": str(amount),
            "line_kind": line_kind_of(desc, amount, line.get("line_kind")),
            "counterparty": (line.get("counterparty") or "").strip() or None,
        })
    return out


def _user_text(
    cats: list[dict], lines: list[dict], occs: list[dict], hist: dict[int, list[dict]],
    notion: dict[int, list[dict]] | None = None,
) -> str:
    notion = notion or {}
    payload = {
        "CATEGORIAS": cats,
        "CONTAS_A_PAGAR_RECEBER": occs,
        "LINHAS": [{**ln, "historico": hist.get(ln["i"], []),
                    "historico_notion": [{k: v for k, v in e.items() if k != "category_id"}
                                         for e in notion.get(ln["i"], [])]}
                   for ln in lines],
    }
    return "Classifique cada linha.\n\n" + json.dumps(payload, ensure_ascii=False)


def _pending_occurrences(db: Session, workspace_id: str, lines: list[dict]) -> list[dict]:
    if not lines:
        return []
    dates = [date.fromisoformat(ln["date"]) for ln in lines]
    occs = db.query(ScheduledTransaction).filter(
        ScheduledTransaction.workspace_id == workspace_id,
        ScheduledTransaction.status == ScheduledStatus.PENDING,
        ScheduledTransaction.due_date >= min(dates) - timedelta(days=10),
        ScheduledTransaction.due_date <= max(dates) + timedelta(days=10),
    ).all()
    return [{
        "id": o.id, "description": o.description, "due_date": o.due_date.isoformat(),
        "amount": str(o.amount), "direction": o.direction.value,
    } for o in occs]


def classify_job(db: Session, job: ExtractionJob, *, force: bool = False) -> dict:
    """Run System 1 once for `job` and persist it. Returns the stored dict
    {version, model, lines: {str(i): {...}}, errors: [...]}"""
    cached = job.classification_json
    if cached is not None and not force and cached.get("version") == SYSTEM1_VERSION:
        return cached
    result: dict = {"version": SYSTEM1_VERSION, "model": SYSTEM1_MODEL, "lines": {}, "errors": []}
    lines = build_lines(job)
    if not lines:
        job.classification_json = result
        db.flush()
        return result
    if cached is not None:
        result["previous_version"] = cached.get("version")

    cats = category_tree(db, job.workspace_id)
    paths = {c["id"]: c["path"] for c in cats}
    by_key, by_party = _history_index(db, job.workspace_id, paths)
    alias_party = _party_by_alias(db, job.workspace_id)
    hist: dict[int, list[dict]] = {}
    for ln in lines:
        keys = [k for k in (_alias_key(ln["counterparty"]), _alias_key(ln["description"])) if k]
        ex: list[dict] = []
        for k in keys:
            ex += by_key.get(k, [])
            pid = alias_party.get(k)
            if pid:
                ex += by_party.get(pid, [])
        seen, uniq = set(), []
        for e in ex:
            sig = (e["date"], e["description"], e["amount"])
            if sig not in seen:
                seen.add(sig)
                uniq.append(e)
        hist[ln["i"]] = uniq[:HISTORY_PER_LINE]
    notion_idx = _notion_index(db, job.workspace_id, paths)
    notion: dict[int, list[dict]] = {}
    dominant: dict[int, dict] = {}
    for ln in lines:
        groups = _notion_for_line(ln, notion_idx)
        notion[ln["i"]] = groups[:NOTION_PER_LINE]
        dom = _dominant(groups)
        if dom is not None:
            real = _real_majority(by_key, by_party, alias_party, ln, paths)
            # Numis confirmado é mais novo: discordou do Notion → sem atalho.
            if real is None or real == dom["category_id"]:
                dominant[ln["i"]] = dom
    occs = _pending_occurrences(db, job.workspace_id, lines)
    occ_ids = {o["id"] for o in occs}

    chunks = [lines[k:k + CHUNK_LINES] for k in range(0, len(lines), CHUNK_LINES)]
    try:
        client = get_llm_client(db)
    except Exception as exc:  # no credential configured etc.
        result["errors"].append(f"System 1 indisponível: {exc}")
        _apply_dominant(result["lines"], dominant)   # o atalho do Notion não depende do LLM
        job.classification_json = result
        db.flush()
        return result

    def one(chunk: list[dict]) -> tuple[LLMCall | None, dict | None, str | None]:
        # Sem temperature (família 5 recusa) a resposta varia: JSON inválido
        # num trecho é refeito uma vez antes de desistir dele.
        total: LLMCall | None = None
        err: str | None = None
        for _ in range(2):
            try:
                call = client.call(system=SYSTEM_PROMPT, user_text=_user_text(cats, chunk, occs, hist, notion),
                                   model=SYSTEM1_MODEL, max_tokens=16000)
            except Exception as exc:
                return total, None, f"System 1 falhou: {exc}"
            total = call if total is None else LLMCall(
                text=call.text, input_tokens=total.input_tokens + call.input_tokens,
                output_tokens=total.output_tokens + call.output_tokens, model=call.model)
            try:
                return total, parse_json_block(call.text), None
            except Exception as exc:
                err = f"System 1 resposta inválida: {exc}"
        return total, None, err

    with ThreadPoolExecutor(max_workers=min(4, len(chunks))) as pool:
        outcomes = list(pool.map(one, chunks))

    in_tok = out_tok = 0
    cost = Decimal("0")
    valid_i = {ln["i"] for ln in lines}
    for call, obj, err in outcomes:
        if call is not None:
            in_tok += call.input_tokens
            out_tok += call.output_tokens
            cost += call.cost_usd()
        if err:
            result["errors"].append(err)
        for item in (obj or {}).get("lines") or [] if isinstance(obj, dict) else []:
            try:
                i = int(item.get("i"))
            except (TypeError, ValueError):
                continue
            if i not in valid_i:
                continue
            cat = item.get("category_id")
            occ = item.get("occurrence_id")
            try:
                conf = max(0.0, min(1.0, float(item.get("confidence") or 0)))
            except (TypeError, ValueError):
                conf = 0.0
            result["lines"][str(i)] = {
                "category_id": cat if cat in paths else None,
                "category_path": paths.get(cat),
                "confidence": round(conf, 2),
                "occurrence_id": occ if occ in occ_ids else None,
                "reason": str(item.get("reason") or "")[:160],
            }

    _apply_dominant(result["lines"], dominant)

    job.input_tokens = (job.input_tokens or 0) + in_tok
    job.output_tokens = (job.output_tokens or 0) + out_tok
    job.cost_usd = (Decimal(job.cost_usd or 0) + cost).quantize(Decimal("0.0001"))
    result["input_tokens"], result["output_tokens"], result["cost_usd"] = in_tok, out_tok, str(cost)
    job.classification_json = result
    db.flush()
    return result


def classify_job_safely(db: Session, job: ExtractionJob) -> None:
    """Never lets System 1 break extraction/preview."""
    try:
        classify_job(db, job)
    except Exception as exc:  # pragma: no cover - backstop
        job.classification_json = {"version": SYSTEM1_VERSION, "lines": {}, "errors": [str(exc)]}
        db.flush()
