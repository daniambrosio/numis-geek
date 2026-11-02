"""Spec 71 (2026-11-02) — exemplos de classificação do Notion → category_example.

Fonte: `data/notion_category_examples.json` (gitignored), gerado a partir do
histórico categorizado do Notion Numis (≈1885 grupos / 5418 lançamentos
desde 2025). Formato:

    {"exported_at", "source", "examples": [{"key", "sample", "tipo",
      "category", "subcategory", "count", "avg", "min", "max", "last_date"}]}

Os exemplos são REFERÊNCIA do System 1 (classificador de categorias do
import de extrato) — nunca transações: não entram em Movimentações, saldos,
dashboards nem fechamentos.

- "categoria › subcategoria" → Category do workspace (sub debaixo daquela
  raiz, sem diferenciar maiúsculas/acentos); sem par → relatado e pulado;
- tipo: Débito / Transfer Débito → saída ("out"); Crédito / Transfer
  Crédito → entrada ("in");
- alias_key = bank_import.alias_key(key) (mesma normalização do import,
  datas no fim removidas — inclusive coladas: "GEAN LI10/06");
- upsert idempotente por (workspace, source, alias_key, categoria, sentido):
  grupos que colapsam na mesma chave somam count e juntam faixa/data.

Usage:
    python -m scripts.import_notion_category_examples                 # dry-run
    python -m scripts.import_notion_category_examples --apply
    python -m scripts.import_notion_category_examples --file path.json --workspace "Família Ambrosio"
"""
from __future__ import annotations

import argparse
import json
import sys
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from sqlalchemy.orm import Session

from numis_geek.models.category import Category
from numis_geek.models.category_example import CategoryExample
from numis_geek.models.workspace import Workspace
from numis_geek.services.bank_import import alias_key

DEFAULT_FILE = Path("data/notion_category_examples.json")
SOURCE = "notion"
ACTOR = "script:import_notion_category_examples"

DIRECTION = {
    "DÉBITO": "out", "TRANSFER DÉBITO": "out",
    "CRÉDITO": "in", "TRANSFER CRÉDITO": "in",
}


def _fold(s: str | None) -> str:
    s = unicodedata.normalize("NFKD", (s or "").strip().lower())
    return " ".join("".join(c for c in s if not unicodedata.combining(c)).split())


def _dec(v) -> Decimal | None:
    if v is None:
        return None
    try:
        return Decimal(str(v)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def _date(v) -> date | None:
    try:
        return date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


@dataclass
class Group:
    alias_key: str
    direction: str
    category_id: str
    sample: str | None
    count: int = 0
    weighted_sum: Decimal = Decimal("0")
    min_amount: Decimal | None = None
    max_amount: Decimal | None = None
    last_date: date | None = None

    def add(self, ex: dict) -> None:
        n = int(ex.get("count") or 1)
        avg = _dec(ex.get("avg"))
        self.count += n
        if avg is not None:
            self.weighted_sum += avg * n
        lo, hi = _dec(ex.get("min")), _dec(ex.get("max"))
        if lo is not None:
            self.min_amount = lo if self.min_amount is None else min(self.min_amount, lo)
        if hi is not None:
            self.max_amount = hi if self.max_amount is None else max(self.max_amount, hi)
        d = _date(ex.get("last_date"))
        if d and (self.last_date is None or d > self.last_date):
            self.last_date = d

    @property
    def avg_amount(self) -> Decimal | None:
        return (self.weighted_sum / self.count).quantize(Decimal("0.01")) if self.count else None


@dataclass
class Plan:
    groups: dict[tuple[str, str, str], Group] = field(default_factory=dict)
    unmapped: dict[str, int] = field(default_factory=dict)     # "cat › sub" → lançamentos
    bad_rows: list[str] = field(default_factory=list)


def category_map(db: Session, workspace_id: str) -> dict[tuple[str, str], str]:
    """(raiz, sub) dobrados → id da subcategoria (só ativas)."""
    cats = db.query(Category).filter(Category.workspace_id == workspace_id).all()
    roots = {c.id: c for c in cats if c.parent_id is None}
    out = {}
    for c in cats:
        if c.parent_id and c.is_active and c.parent_id in roots:
            out[(_fold(roots[c.parent_id].name), _fold(c.name))] = c.id
    return out


def build_plan(data: dict, cats: dict[tuple[str, str], str]) -> Plan:
    plan = Plan()
    for ex in data.get("examples") or []:
        direction = DIRECTION.get((ex.get("tipo") or "").strip().upper())
        key = alias_key(ex.get("key") or ex.get("sample") or "")
        if not direction or not key:
            plan.bad_rows.append(f"{ex.get('key')!r} tipo={ex.get('tipo')!r}")
            continue
        cid = cats.get((_fold(ex.get("category")), _fold(ex.get("subcategory"))))
        if cid is None:
            label = f"{ex.get('category')} › {ex.get('subcategory')}"
            plan.unmapped[label] = plan.unmapped.get(label, 0) + int(ex.get("count") or 1)
            continue
        g = plan.groups.setdefault((key, direction, cid), Group(key, direction, cid, (ex.get("sample") or "")[:255] or None))
        g.add(ex)
    return plan


def apply_plan(db: Session, workspace_id: str, plan: Plan) -> tuple[int, int]:
    """Upsert. Returns (created, updated)."""
    existing = {
        (e.alias_key, e.direction, e.category_id): e
        for e in db.query(CategoryExample).filter(
            CategoryExample.workspace_id == workspace_id, CategoryExample.source == SOURCE,
        ).all()
    }
    created = updated = 0
    for k, g in plan.groups.items():
        row = existing.get(k)
        if row is None:
            db.add(CategoryExample(
                id=str(uuid.uuid4()), workspace_id=workspace_id, alias_key=g.alias_key,
                sample_description=g.sample, direction=g.direction, category_id=g.category_id,
                count=g.count, avg_amount=g.avg_amount, min_amount=g.min_amount, max_amount=g.max_amount,
                last_date=g.last_date, source=SOURCE, created_at=datetime.now(timezone.utc),
            ))
            created += 1
            continue
        vals = dict(count=g.count, avg_amount=g.avg_amount, min_amount=g.min_amount,
                    max_amount=g.max_amount, last_date=g.last_date, sample_description=g.sample)
        if any(getattr(row, f) != v for f, v in vals.items()):
            for f, v in vals.items():
                setattr(row, f, v)
            updated += 1
    db.flush()
    return created, updated


def _workspace(db: Session, ref: str | None) -> Workspace:
    if ref:
        ws = db.get(Workspace, ref) or db.query(Workspace).filter(Workspace.name == ref).one_or_none()
        if ws is None:
            raise SystemExit(f"Workspace não encontrado: {ref}")
        return ws
    wss = db.query(Workspace).all()
    if len(wss) != 1:
        raise SystemExit(f"Esperava 1 workspace, achei {len(wss)} — passe --workspace")
    return wss[0]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="grava (sem isso é dry-run)")
    ap.add_argument("--file", type=Path, default=DEFAULT_FILE)
    ap.add_argument("--workspace", help="id ou nome (default: o único workspace)")
    args = ap.parse_args()
    if not args.file.exists():
        print(f"arquivo não encontrado: {args.file}", file=sys.stderr)
        return 1
    data = json.loads(args.file.read_text(encoding="utf-8"))

    from numis_geek.db.session import SessionLocal
    from numis_geek.services.audit import AuditService
    db = SessionLocal()
    try:
        ws = _workspace(db, args.workspace)
        plan = build_plan(data, category_map(db, ws.id))
        n_src = len(data.get("examples") or [])
        mapped = sum(g.count for g in plan.groups.values())
        print(f"== {'APPLY' if args.apply else 'DRY-RUN'} — workspace {ws.name}")
        print(f"grupos no arquivo: {n_src} · chaves resultantes: {len(plan.groups)} · lançamentos mapeados: {mapped}")
        if plan.bad_rows:
            print(f"linhas sem tipo/chave válidos: {len(plan.bad_rows)}")
            for b in plan.bad_rows[:20]:
                print(f"  - {b}")
        if plan.unmapped:
            print(f"categorias sem par no Numis ({len(plan.unmapped)}), pulados {sum(plan.unmapped.values())} lançamentos:")
            for label, n in sorted(plan.unmapped.items(), key=lambda kv: -kv[1]):
                print(f"  - {label}: {n}")
        created, updated = apply_plan(db, ws.id, plan)
        print(f"category_example: {created} novos · {updated} atualizados")
        if args.apply:
            AuditService(db).log(
                user_email=ACTOR, action="category_example.imported", workspace_id=ws.id,
                resource_type="category_example", details={
                    "file": str(args.file), "exported_at": data.get("exported_at"),
                    "created": created, "updated": updated, "unmapped": plan.unmapped,
                },
            )
            db.commit()
            print("gravado.")
        else:
            db.rollback()
            print("dry-run — nada gravado (use --apply).")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
