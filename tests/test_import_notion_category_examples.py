"""Spec 71 — Notion → category_example (mapping, direction, idempotency)."""
import uuid
from decimal import Decimal

from numis_geek.models.category import Category, CategoryKind
from numis_geek.models.category_example import CategoryExample
from numis_geek.models.workspace import Workspace
from scripts.import_notion_category_examples import apply_plan, build_plan, category_map


def _ws(db):
    ws = Workspace(id=str(uuid.uuid4()), name=f"WS {uuid.uuid4().hex[:4]}")
    db.add(ws)
    db.flush()
    root = Category(id=str(uuid.uuid4()), workspace_id=ws.id, name="Moradia")
    db.add(root)
    db.flush()
    dia = Category(id=str(uuid.uuid4()), workspace_id=ws.id, name="Diarista", parent_id=root.id, kind=CategoryKind.EXPENSE)
    sal_root = Category(id=str(uuid.uuid4()), workspace_id=ws.id, name="Receitas")
    db.add_all([dia, sal_root])
    db.flush()
    sal = Category(id=str(uuid.uuid4()), workspace_id=ws.id, name="Salário", parent_id=sal_root.id, kind=CategoryKind.INCOME)
    db.add(sal)
    db.flush()
    return ws, dia, sal


DATA = {"exported_at": "2026-11-02", "source": "notion", "examples": [
    {"key": "PIX TRANSF MARIA N", "sample": "PIX TRANSF MARIA N13/12", "tipo": "Débito",
     "category": "moradia", "subcategory": "DIARISTA", "count": 40, "avg": 420.5, "min": 200, "max": 500,
     "last_date": "2026-08-08"},
    # same bank text with a glued date collapses into the same key
    {"key": "PIX TRANSF MARIA N10/06", "sample": "PIX TRANSF MARIA N10/06", "tipo": "Transfer Débito",
     "category": "Moradia", "subcategory": "Diarista", "count": 2, "avg": 300, "min": 300, "max": 300,
     "last_date": "2026-09-01"},
    {"key": "MERCADO LIVRE SALARIO", "sample": "MERCADO LIVRE SALARIO", "tipo": "Crédito",
     "category": "Receitas", "subcategory": "Salario", "count": 10, "avg": 15000, "min": 14000, "max": 16000,
     "last_date": "2026-08-30"},
    {"key": "UBER", "sample": "UBER *TRIP", "tipo": "Débito", "category": "Transporte", "subcategory": "Uber",
     "count": 7, "avg": 20, "min": 10, "max": 30, "last_date": "2026-08-01"},
    {"key": "X", "sample": "X", "tipo": "???", "category": "Moradia", "subcategory": "Diarista", "count": 1},
]}


def test_mapping_direction_collapse_and_unmapped(db):
    ws, dia, sal = _ws(db)
    plan = build_plan(DATA, category_map(db, ws.id))
    g = plan.groups[("PIX TRANSF MARIA N", "out", dia.id)]
    assert g.count == 42 and g.min_amount == Decimal("200.00") and g.max_amount == Decimal("500.00")
    assert str(g.last_date) == "2026-09-01"
    assert g.avg_amount == Decimal("414.76")                     # weighted
    assert ("MERCADO LIVRE SALARIO", "in", sal.id) in plan.groups   # accent/case-insensitive
    assert plan.unmapped == {"Transporte › Uber": 7}
    assert len(plan.bad_rows) == 1


def test_apply_is_idempotent_upsert(db):
    ws, dia, _ = _ws(db)
    cats = category_map(db, ws.id)
    assert apply_plan(db, ws.id, build_plan(DATA, cats)) == (2, 0)
    assert apply_plan(db, ws.id, build_plan(DATA, cats)) == (0, 0)
    changed = {**DATA, "examples": [{**DATA["examples"][0], "count": 41}] + DATA["examples"][1:]}
    assert apply_plan(db, ws.id, build_plan(changed, cats)) == (0, 1)
    rows = db.query(CategoryExample).filter(CategoryExample.workspace_id == ws.id).all()
    assert len(rows) == 2 and all(r.source == "notion" for r in rows)
    assert next(r for r in rows if r.category_id == dia.id).count == 43
