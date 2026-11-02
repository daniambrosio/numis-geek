"""Spec 73 — transform do snapshot Notion → plano de contas a pagar/receber."""
from decimal import Decimal

import pytest

from numis_geek.models.scheduled_transaction import RecurrenceFrequency, ScheduledDirection
from scripts.import_notion_numis_cadastro import build_plan


def _row(name, *, meio="DDA", freq="Mensal", dia=5, tipo="Débito", sub="Internet",
         conta="Itaú Conta Corrente", last=100.0, last_date="2026-09-05", months=None, est=90.0):
    return {
        "name": name, "tipo_conta": "Fixo", "valor_estimado": est, "meio_pagamento": meio,
        "frequencia": freq, "dia_vencimento": dia, "notion_id": "abc123",
        "hist": {"tipo": tipo, "subcategoria": sub, "conta": conta, "last_val": last,
                 "last_date": last_date, "months": months},
    }


def _plan(*rows):
    return build_plan({"rules": list(rows), "cards": []})


def test_uses_last_paid_value_and_maps_direction_and_account():
    p = _plan(_row("Condomínio", last=1670, est=1229),
              _row("Salário", meio="Depósito em Conta", tipo="Crédito", sub="Salário", last=33968))
    cond, sal = p.rules
    assert cond.amount == Decimal("1670") and cond.direction == ScheduledDirection.PAYABLE
    assert cond.account_name == "Conta Corrente Itaú"
    assert sal.direction == ScheduledDirection.RECEIVABLE and sal.account_name == "Conta Corrente Itaú"


def test_benefit_deposit_goes_to_mercado_pago():
    p = _plan(_row("Benefícios Meli", meio="Depósito em Conta", tipo="Crédito",
                   sub="Benefício Trabalhista", conta="Benefício Alimentação Meli"))
    assert p.rules[0].account_name == "Conta Corrente Mercado Pago"


def test_card_paid_rule_has_no_account():
    p = _plan(_row("Netflix", meio="Cartão Crédito Master Itaú", conta="Cartão Mastercard Itaú"),
              _row("Apple One", meio="Apple Subscription", conta="Cartão Mastercard Itaú"))
    assert [r.account_name for r in p.rules] == [None, None]


def test_caixa_debit_maps_to_new_caixa_account():
    p = _plan(_row("Fotovoltaica", meio="Déb. Aut. Caixa", conta="Caixa Econômica Federal"))
    assert p.rules[0].account_name == "Conta Corrente Caixa"


def test_yearly_month_comes_from_last_payment_then_months():
    p = _plan(_row("PS Plus", freq="Anual", last_date="2026-01-07", months=[1]),
              _row("Goodnotes", freq="Anual", last=None, last_date=None, months=[12], est=49.9))
    ps, gn = p.rules
    assert ps.frequency == RecurrenceFrequency.YEARLY and ps.month == 1
    assert gn.month == 12 and gn.amount == Decimal("49.9")
    assert gn.warnings and "estimativa" in gn.warnings[0]


def test_skips_decided_rules():
    p = _plan(_row("Fatura Cartão MP", tipo="Transfer Débito"), _row("Clube Fortnite Dani"),
              _row("IPVA Carro Próprio", freq="Anual"), _row("Netflix"))
    assert [r.description for r in p.rules] == ["Netflix"]
    assert {n for n, _ in p.skipped} == {"Fatura Cartão MP", "Clube Fortnite Dani", "IPVA Carro Próprio"}


def test_rematricula_splits_into_two_yearly_rules():
    p = _plan(_row("Rematrícula Lara", freq="Variável", dia=10, sub="Matrícula", months=[11, 12]))
    assert [(r.description, r.month, r.amount) for r in p.rules] == [
        ("Rematrícula Lara (nov)", 11, Decimal("3105.49")),
        ("Rematrícula Lara (dez)", 12, Decimal("2794.95")),
    ]
    assert all(r.frequency == RecurrenceFrequency.YEARLY for r in p.rules)


def test_day_after_28_is_clamped_with_warning():
    p = _plan(_row("Gás", dia=30))
    assert p.rules[0].day_of_month == 28 and "dia 30" in p.rules[0].warnings[0]


@pytest.mark.parametrize("row", [
    _row("Sem meio", meio="Cheque"),
    _row("Transfer", tipo="Transfer Débito"),
    _row("Variável sem decisão", freq="Variável"),
    _row("Depósito desconhecido", meio="Depósito em Conta", conta="Banco X"),
])
def test_unmapped_rows_fail_loudly(row):
    with pytest.raises(ValueError):
        _plan(row)
