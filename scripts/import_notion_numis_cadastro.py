"""Spec 73 (metade contas fixas) — cadastro do Notion Numis → Numis-Geek.

Fonte: snapshot `data/notion_numis_cadastro_export.json` (gitignored), lido
do Notion via MCP em 2026-11-01:
  - DB Numis Contas a Pagar e Receber (só as ativas — 18 desativadas ficam fora);
  - DB Numis Contas Agrupadoras (cartões);
  - DB Numis Transacoes (histórico real Realizada/Conciliada/Importada), de
    onde saem direção, categoria, mês das anuais e o último valor pago — a
    conta fixa do Notion não tem nenhum desses campos, ou tem defasado.

Os dados do Notion são referência: as decisões abaixo saíram da crítica
apresentada ao user em 2026-11-01 (entrevista) e vivem AQUI, versionadas.

Cria (idempotente — chave natural = nome, nada é atualizado nem deletado):
  - cartões de crédito (Mastercard Itaú, Latam Itaú, Mercado Pago);
  - a conta corrente Caixa (débito automático da Fotovoltaica);
  - uma regra recorrente por conta fixa (+ ocorrências materializadas via
    `scheduled_transactions.create_rule`), sem fornecedor/cliente — esses
    nascem dos extratos na spec 71.

Usage:
    python -m scripts.import_notion_numis_cadastro             # dry-run
    python -m scripts.import_notion_numis_cadastro --apply
    python -m scripts.import_notion_numis_cadastro --snapshot path.json
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from numis_geek.db.session import SessionLocal
from numis_geek.models.account import Account, AccountType, Currency
from numis_geek.models.category import Category
from numis_geek.models.credit_card import CreditCardAccount
from numis_geek.models.financial_institution import FinancialInstitution
from numis_geek.models.scheduled_transaction import (
    RecurrenceFrequency,
    RecurrenceRule,
    ScheduledDirection,
)
from numis_geek.models.workspace import Workspace
from numis_geek.services import scheduled_transactions as sched
from numis_geek.services.audit import AuditService

DEFAULT_SNAPSHOT = Path("data/notion_numis_cadastro_export.json")
ACTOR = "script:import_notion_numis_cadastro"

# Primeira ocorrência materializada. Outubro/26 entra para que o primeiro
# import de extrato (out/26) já quite as ocorrências e valide o matching.
START_DATE = date(2026, 10, 1)

# ── decisões da entrevista 2026-11-01 ───────────────────────────────────────

SKIP: dict[str, str] = {
    "Clube Fortnite Dani": "user: não existe mais",
    "Notion Pessoal + IA (2 usuários)": "user: não existe mais",
    "Notion Dani Geek Hosting": "user: não existe mais",
    "Fatura Cartão XP": "fatura já é a conta a pagar (spec 69); cartão XP fechado",
    "Fatura Cartão MP": "fatura já é a conta a pagar (spec 69)",
    "IPVA Carro Próprio": "pago em 5 parcelas jan–mai; cadastrar com o boleto do ano",
}

# Rematrícula: user escolheu 2 anuais (nov e dez). Valores = pagamentos reais
# de nov/25 e dez/25 (média × 2 − dezembro).
SPLIT_YEARLY: dict[str, list[tuple[int, Decimal]]] = {
    "Rematrícula Lara": [(11, Decimal("3105.49")), (12, Decimal("2794.95"))],
    "Rematrícula Caio": [(11, Decimal("2989.35")), (12, Decimal("2690.41"))],
}

# Salário Meli chega em duas partes (user, 2026-11-02): dia 1 e dia 15.
# Valores = últimos pagamentos reais de cada parte (set/26 e out/26).
SPLIT_MONTHLY: dict[str, list[tuple[int, Decimal]]] = {
    "Salário Meli": [(1, Decimal("23538.89")), (15, Decimal("33968"))],
}

CARDS: list[dict] = [
    {"notion": "Cartão Mastercard Itaú", "name": "Mastercard Itaú", "fi": "Itaú", "brand": "Mastercard"},
    {"notion": "Cartão Latam Itaú", "name": "Latam Itaú", "fi": "Itaú", "brand": None},
    {"notion": "Cartão Mercado Pago", "name": "Mercado Pago", "fi": "Mercado Pago", "brand": None},
]

NEW_ACCOUNTS: list[dict] = [
    {"name": "Conta Corrente Caixa", "fi": "Caixa", "currency": Currency.BRL},
]

# Meio de pagamento do Notion → conta corrente esperada no Numis.
ACCOUNT_BY_MEIO: dict[str, str] = {
    "Déb. Aut. Itaú": "Conta Corrente Itaú",
    "DDA": "Conta Corrente Itaú",
    "Boleto": "Conta Corrente Itaú",
    "PIX": "Conta Corrente Itaú",
    "Déb. Aut. MP": "Conta Corrente Mercado Pago",
    "Déb. Aut. Caixa": "Conta Corrente Caixa",
}
# "Depósito em Conta" → conta vista no histórico. Benefícios Meli caem no
# Mercado Pago (user), não na conta-benefício do Notion.
ACCOUNT_BY_HIST_CONTA: dict[str, str] = {
    "Itaú Conta Corrente": "Conta Corrente Itaú",
    "Mercado Pago Conta Corrente": "Conta Corrente Mercado Pago",
    "Benefício Alimentação Meli": "Conta Corrente Mercado Pago",
}
# Pagos no cartão: a regra não aponta conta (expected_account é conta
# corrente); a ocorrência é quitada pela linha da fatura.
CARD_MEIOS = {"Cartão Crédito Master Itaú", "Apple Subscription", "Cartão Latam", "Cartão XP", "Fatura MP"}


# ── transform puro (testado) ────────────────────────────────────────────────

@dataclass
class RulePlan:
    description: str
    direction: ScheduledDirection
    category_name: str
    amount: Decimal
    frequency: RecurrenceFrequency
    day_of_month: int
    month: int | None
    account_name: str | None
    notes: str
    warnings: list[str] = field(default_factory=list)


@dataclass
class Plan:
    rules: list[RulePlan]
    skipped: list[tuple[str, str]]


def _amount(row: dict) -> tuple[Decimal, str | None]:
    last = row["hist"].get("last_val")
    est = Decimal(str(row["valor_estimado"]))
    if last is None:
        return est, "sem pagamento real no Notion — usando a estimativa"
    return Decimal(str(last)), None


def _month(row: dict) -> int:
    h = row["hist"]
    if h.get("last_date"):
        return int(h["last_date"][5:7])
    if h.get("months"):
        return int(h["months"][0])
    raise ValueError(f"{row['name']}: conta anual sem mês no histórico")


def _account(row: dict) -> str | None:
    meio = row["meio_pagamento"]
    if meio in CARD_MEIOS:
        return None
    if meio == "Depósito em Conta":
        conta = row["hist"].get("conta")
        if conta not in ACCOUNT_BY_HIST_CONTA:
            raise ValueError(f"{row['name']}: depósito em conta sem conta conhecida ({conta})")
        return ACCOUNT_BY_HIST_CONTA[conta]
    if meio not in ACCOUNT_BY_MEIO:
        raise ValueError(f"{row['name']}: meio de pagamento sem mapeamento ({meio})")
    return ACCOUNT_BY_MEIO[meio]


def build_plan(snapshot: dict) -> Plan:
    rules: list[RulePlan] = []
    skipped: list[tuple[str, str]] = []
    for row in snapshot["rules"]:
        name = row["name"]
        if name in SKIP:
            skipped.append((name, SKIP[name]))
            continue
        h = row["hist"]
        if h["tipo"] not in ("Crédito", "Débito"):
            raise ValueError(f"{name}: tipo {h['tipo']} não vira conta a pagar/receber")
        direction = ScheduledDirection.RECEIVABLE if h["tipo"] == "Crédito" else ScheduledDirection.PAYABLE
        notes = f"[notion:{row['notion_id']}] Meio de pagamento no Notion: {row['meio_pagamento']}"
        account = _account(row)
        day = int(row["dia_vencimento"])
        day_warn = None
        if day > 28:  # spec 72: dia do vencimento entre 1 e 28
            day_warn = f"vence dia {day} no Notion — cadastrado no dia 28"
            day = 28
        if name in SPLIT_YEARLY:
            for month, value in SPLIT_YEARLY[name]:
                label = "nov" if month == 11 else "dez" if month == 12 else f"{month:02d}"
                rules.append(RulePlan(
                    description=f"{name} ({label})", direction=direction, category_name=h["subcategoria"],
                    amount=value, frequency=RecurrenceFrequency.YEARLY, day_of_month=day, month=month,
                    account_name=account, notes=notes,
                ))
            continue
        if name in SPLIT_MONTHLY:
            for split_day, value in SPLIT_MONTHLY[name]:
                rules.append(RulePlan(
                    description=f"{name} (dia {split_day})", direction=direction, category_name=h["subcategoria"],
                    amount=value, frequency=RecurrenceFrequency.MONTHLY, day_of_month=split_day, month=None,
                    account_name=account, notes=notes,
                ))
            continue
        amount, warn = _amount(row)
        freq = {"Mensal": RecurrenceFrequency.MONTHLY, "Anual": RecurrenceFrequency.YEARLY}.get(row["frequencia"])
        if freq is None:
            raise ValueError(f"{name}: frequência {row['frequencia']} sem decisão")
        rules.append(RulePlan(
            description=name, direction=direction, category_name=h["subcategoria"], amount=amount,
            frequency=freq, day_of_month=day, month=_month(row) if freq == RecurrenceFrequency.YEARLY else None,
            account_name=account, notes=notes, warnings=[w for w in (warn, day_warn) if w],
        ))
    return Plan(rules=rules, skipped=skipped)


# ── apply ───────────────────────────────────────────────────────────────────

def _fi(db, short_name: str) -> FinancialInstitution:
    fi = db.query(FinancialInstitution).filter(FinancialInstitution.short_name == short_name).one_or_none()
    if fi is None:
        raise SystemExit(f"Instituição '{short_name}' não encontrada")
    return fi


def _sub_categories(db, ws_id: str) -> dict[str, Category]:
    subs = db.query(Category).filter(Category.workspace_id == ws_id, Category.parent_id.isnot(None)).all()
    out: dict[str, Category] = {}
    for c in subs:
        if c.name in out:
            raise SystemExit(f"Subcategoria '{c.name}' ambígua (duas raízes)")
        out[c.name] = c
    return out


def run(snapshot_path: Path, apply: bool, today: date | None = None) -> int:
    snapshot = json.loads(snapshot_path.read_text())
    plan = build_plan(snapshot)
    db = SessionLocal()
    try:
        workspaces = db.query(Workspace).all()
        if len(workspaces) != 1:
            raise SystemExit(f"Esperava 1 workspace, achei {len(workspaces)}")
        ws = workspaces[0]
        audit = AuditService(db)
        now = datetime.now(timezone.utc)
        mode = "APPLY" if apply else "DRY-RUN"
        print(f"== {mode} — workspace {ws.name}")

        print("\n-- Contas correntes novas")
        for spec in NEW_ACCOUNTS:
            existing = db.query(Account).filter(Account.workspace_id == ws.id, Account.name == spec["name"]).one_or_none()
            if existing:
                print(f"  = {spec['name']} (já existe)")
                continue
            print(f"  + {spec['name']} ({spec['fi']}, {spec['currency'].value})")
            if apply:
                acc = Account(
                    id=str(uuid.uuid4()), workspace_id=ws.id, financial_institution_id=_fi(db, spec["fi"]).id,
                    name=spec["name"], account_type=AccountType.checking, currency=spec["currency"],
                    is_active=True, created_at=now, updated_at=now,
                )
                db.add(acc)
                db.flush()
                audit.log(user_email=ACTOR, action="account.created", resource_type="account",
                          resource_id=acc.id, workspace_id=ws.id, details={"name": acc.name, "source": "notion"})

        print("\n-- Cartões")
        notion_cards = {c["name"]: c for c in snapshot["cards"]}
        for spec in CARDS:
            src = notion_cards[spec["notion"]]
            existing = db.query(CreditCardAccount).filter(
                CreditCardAccount.workspace_id == ws.id, CreditCardAccount.name == spec["name"]).one_or_none()
            if existing:
                print(f"  = {spec['name']} (já existe)")
                continue
            print(f"  + {spec['name']} ({spec['fi']}) fecha {src['close_day']}, vence {src['due_day']}")
            if apply:
                card = CreditCardAccount(
                    id=str(uuid.uuid4()), workspace_id=ws.id, financial_institution_id=_fi(db, spec["fi"]).id,
                    name=spec["name"], brand=spec["brand"], currency=Currency.BRL,
                    close_day=src["close_day"], due_day=src["due_day"], is_active=True,
                    created_at=now, updated_at=now,
                )
                db.add(card)
                db.flush()
                audit.log(user_email=ACTOR, action="credit_card.created", resource_type="credit_card_account",
                          resource_id=card.id, workspace_id=ws.id, details={"name": card.name, "source": "notion"})

        print(f"\n-- Contas a pagar/receber ({len(plan.rules)} regras, início {START_DATE.isoformat()})")
        subs = _sub_categories(db, ws.id)
        accounts = {a.name: a for a in db.query(Account).filter(Account.workspace_id == ws.id).all()}
        created = 0
        for r in plan.rules:
            cat = subs.get(r.category_name)
            if cat is None:
                raise SystemExit(f"{r.description}: subcategoria '{r.category_name}' não existe no Numis")
            if db.query(RecurrenceRule).filter(
                    RecurrenceRule.workspace_id == ws.id, RecurrenceRule.description == r.description).first():
                print(f"  = {r.description} (já existe)")
                continue
            sign = "+" if r.direction == ScheduledDirection.RECEIVABLE else "-"
            when = f"dia {r.day_of_month}" + (f"/{r.month:02d}" if r.month else "")
            acc_label = r.account_name or "cartão / sem conta"
            print(f"  + {r.description:<34} {sign}{r.amount:>10}  {r.frequency.value:<7} {when:<9} "
                  f"{cat.name:<28} {acc_label}" + "".join(f"  ⚠ {w}" for w in r.warnings))
            if not apply:
                continue
            acc_id = None
            if r.account_name:
                acc = accounts.get(r.account_name)
                if acc is None:
                    raise SystemExit(f"{r.description}: conta '{r.account_name}' não existe")
                acc_id = acc.id
            rule, occs = sched.create_rule(db, ws.id, sched.RuleInput(
                direction=r.direction, description=r.description, amount=r.amount, frequency=r.frequency,
                day_of_month=r.day_of_month, month=r.month, start_date=START_DATE,
                currency=Currency.BRL if acc_id is None else None, category_id=cat.id,
                expected_account_id=acc_id, notes=r.notes,
            ), today=today)
            audit.log(user_email=ACTOR, action="recurrence_rule.created", resource_type="recurrence_rule",
                      resource_id=rule.id, workspace_id=ws.id,
                      details={"description": rule.description, "source": "notion", "occurrences": len(occs)})
            created += 1

        print("\n-- Fora do import")
        for name, why in plan.skipped:
            print(f"  · {name}: {why}")
        print(f"  · {snapshot.get('inactive_rules_skipped', 0)} contas desativadas no Notion")

        if apply:
            db.commit()
            print(f"\nOK — {created} regras criadas.")
        else:
            db.rollback()
            print("\nDry-run: nada gravado. Rode com --apply.")
        return 0
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    args = ap.parse_args()
    return run(args.snapshot, args.apply)


if __name__ == "__main__":
    sys.exit(main())
