"""Spec 73 (metade categorias) — import das categorias do Notion Numis.

Fonte: prints da DB "DB Numis Categorias" fornecidos pelo user em
2026-08-09 (sem MCP — decisão do user: export/print é mais simples).
A árvore vive AQUI, versionada, transcrita 1:1 dos prints.

Kinds:
  - raiz "Recebimentos" → INCOME; raiz "Transferências" → TRANSFER;
    demais raízes → EXPENSE.
  - Subs herdam a raiz, EXCETO os overrides marcados com "+" nos prints
    (raízes mistas — decisão 2026-08-09: sub pode ter kind próprio).

Pendência conhecida: "Moradia" tem +5 subcategorias ocultas no print —
o user manda depois (decisão registrada); re-rodar o script as adiciona.

Idempotente: chave natural = caminho (root_name, sub_name) por workspace.
Re-run atualiza kind/cor de rows já existentes criadas por este script e
cria só o que falta. Nada é deletado.

Usage:
    python -m scripts.import_numis_categories             # dry-run
    python -m scripts.import_numis_categories --apply
"""
from __future__ import annotations

import argparse
import sys
import uuid
from datetime import datetime, timezone

from numis_geek.db.session import SessionLocal
from numis_geek.models.category import Category, CategoryKind
from numis_geek.models.workspace import Workspace

# (root, color, root_kind, [(sub, override_kind|None), ...])
TREE: list[tuple[str, str, CategoryKind, list[tuple[str, CategoryKind | None]]]] = [
    ("Alimentação", "#f59e0b", CategoryKind.EXPENSE, [
        ("Comer Fora / Delivery", None), ("Mercado", None), ("Lanchonete / Padaria", None),
    ]),
    ("Apps e Serviços Online", "#14b8a6", CategoryKind.EXPENSE, [
        ("Streaming", None), ("Aplicativos", None), ("Storage", None), ("Games", None),
        ("Loyalty / Clube", None), ("Telefonia Celular", None),
    ]),
    ("Bens Móveis", "#8b5cf6", CategoryKind.EXPENSE, [
        ("Eletrodomésticos / UD", None), ("Despesas Compra/Venda Carro", None),
        ("Eletrônicos", None), ("Produtos Genéricos", None),
        ("Receitas Compra/Venda Carro", CategoryKind.INCOME),
        ("Venda Produtos Usados", CategoryKind.INCOME),
    ]),
    ("Consultoria", "#6366f1", CategoryKind.EXPENSE, [
        ("Honorários de Consultoria", CategoryKind.INCOME),
        ("Contabilidade e Documentação", None),
    ]),
    ("Cuidados Pessoais", "#ec4899", CategoryKind.EXPENSE, [
        ("Barbearia / Cabeleireiro", None), ("Vestuário", None), ("Oléos Essenciais", None),
        ("Depilação", None), ("Beleza", None), ("Podologia", None), ("Prática Esportiva", None),
    ]),
    ("Educação", "#3b82f6", CategoryKind.EXPENSE, [
        ("Mensalidade Escolar", None), ("Material Didático / Escolar", None),
        ("Alimentação na Escola", None), ("Atividade Extra", None), ("Matrícula", None),
    ]),
    ("Financeiro", "#64748b", CategoryKind.EXPENSE, [
        ("Tarifa Bancária", None), ("Imposto Op. Fin.", None),
    ]),
    ("Lazer", "#d946ef", CategoryKind.EXPENSE, [
        ("Bares e Festas", None), ("Cinema / Teatro / Musical", None), ("Livros", None),
        ("Fantasias e Enfeites", None), ("Ingresso Show / Jogo", None),
    ]),
    ("Moradia", "#0ea5e9", CategoryKind.EXPENSE, [
        ("Consumo Energia Elétrica", None), ("Consumo de Água", None),
        ("Aluguel e Condomínio", None), ("Consumo de Gás", None),
        ("Seguro e Monitoramento Residencial", None), ("Internet", None),
        ("Piscina", None), ("Jardim", None), ("Aquário", None), ("Impostos Moradia", None),
        # +5 subcategorias ocultas no print — user manda depois; re-run adiciona.
    ]),
    ("O Dani Geek", "#f97316", CategoryKind.EXPENSE, [
        ("Ferramentas", None),
        ("Pagamentos Gumroad", CategoryKind.INCOME),
        ("O Dani Geek Vendas", CategoryKind.INCOME),
        ("Imposto Empresarial", None),
    ]),
    ("Outras Despesas", "#78716c", CategoryKind.EXPENSE, [
        ("Outras Despesas", None), ("Investimento Imobiliário", None), ("Presente", None),
        ("Aposta / Bolão", None), ("Despesa Reembolsável", None),
    ]),
    ("Pet", "#84cc16", CategoryKind.EXPENSE, [
        ("Banho e Tosa", None), ("Veterinário", None), ("Comida Pet", None), ("Outros Pet", None),
    ]),
    ("Recebimentos", "#22c55e", CategoryKind.INCOME, [
        ("Renda Extra", None), ("Salário", None), ("Dividendos e Proventos", None),
        ("Outros Recebimentos", None), ("Estorno", None), ("Benefício Trabalhista", None),
        ("Reembolso", None), ("Rendimentos", None), ("Acordo Judicial", None),
    ]),
    ("Saúde", "#ef4444", CategoryKind.EXPENSE, [
        ("Dentista", None), ("Fisioterapeuta", None), ("Médico", None), ("Remédios", None),
        ("Terapia", None), ("Fonoaudiologia", None), ("Atividade Física", None),
    ]),
    ("Transferências", "#9ca3af", CategoryKind.TRANSFER, [
        ("Débito Transfer Entre Contas", None), ("Crédito Transfer Entre Contas", None),
    ]),
    ("Transporte", "#06b6d4", CategoryKind.EXPENSE, [
        ("Estacionamento e Pedágio", None), ("Seguro Auto", None), ("Combustível", None),
        ("Documentação Veículos", None), ("Uber e Táxi", None), ("Manutenção Carro", None),
        ("Lavagem Carro", None), ("Multas", None),
    ]),
    ("Viagem", "#eab308", CategoryKind.EXPENSE, [
        ("Passagem", None), ("Milhas", None), ("Estadia", None), ("Aluguel de Carro", None),
        ("Passeio", None), ("Seguro Viagem", None), ("Cambio Espécie", None),
    ]),
]


def run(apply: bool) -> int:
    db = SessionLocal()
    try:
        workspaces = db.query(Workspace).all()
        if len(workspaces) != 1:
            print(f"ERRO: esperado exatamente 1 workspace, achei {len(workspaces)}. Aborting.")
            return 1
        ws = workspaces[0]
        now = datetime.now(timezone.utc)

        existing = db.query(Category).filter(Category.workspace_id == ws.id).all()
        roots_by_name = {c.name: c for c in existing if c.parent_id is None}
        by_id = {c.id: c for c in existing}
        subs_by_path = {
            (by_id[c.parent_id].name, c.name): c
            for c in existing if c.parent_id is not None and c.parent_id in by_id
        }

        created, updated, unchanged = 0, 0, 0

        def upsert(name: str, parent: Category | None, kind: CategoryKind, color: str | None) -> Category:
            nonlocal created, updated, unchanged
            row = roots_by_name.get(name) if parent is None else subs_by_path.get((parent.name, name))
            if row is None:
                row = Category(
                    id=str(uuid.uuid4()), workspace_id=ws.id, name=name,
                    parent_id=parent.id if parent else None,
                    kind=kind, color=color, is_active=True,
                    created_at=now, updated_at=now, created_by=None, updated_by=None,
                )
                if apply:
                    db.add(row)
                if parent is None:
                    roots_by_name[name] = row
                else:
                    subs_by_path[(parent.name, name)] = row
                created += 1
                print(f"  CREATE {'  ' if parent else ''}{name}  [{kind.value}]{' ' + color if color else ''}")
            elif row.kind != kind or (color and row.color != color):
                if apply:
                    row.kind = kind
                    row.color = color
                    row.updated_at = now
                updated += 1
                print(f"  UPDATE {'  ' if parent else ''}{name}  → [{kind.value}] {color}")
            else:
                unchanged += 1
            return row

        for root_name, color, root_kind, subs in TREE:
            root = upsert(root_name, None, root_kind, color)
            for sub_name, override in subs:
                upsert(sub_name, root, override or root_kind, color)

        if apply:
            db.commit()
            print(f"\nAPPLIED — created {created}, updated {updated}, unchanged {unchanged}")
        else:
            db.rollback()
            print(f"\nDRY-RUN — would create {created}, update {updated}; unchanged {unchanged}")
            print("Re-run with --apply to persist.")
        total = db.query(Category).filter(Category.workspace_id == ws.id).count()
        print(f"category rows in workspace after run: {total}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="persist (default: dry-run)")
    args = parser.parse_args()
    sys.exit(run(apply=args.apply))
