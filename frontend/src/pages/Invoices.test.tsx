/* Spec 69 — primitivas de Faturas/Cartões: filtros, KPIs. */
import { describe, expect, it } from 'vitest'

import { filterInvoices, invoiceKpis } from './Invoices'
import { cardKpis } from './CreditCards'
import type { CreditCardOut, InvoiceOut } from '../lib/api'

function inv(partial: Partial<InvoiceOut> & { id: string }): InvoiceOut {
  return {
    workspace_id: 'ws',
    credit_card_account_id: 'card1',
    credit_card_name: 'Card',
    close_date: '2026-08-05',
    due_date: '2026-08-15',
    total_amount: 100,
    iof_total: null,
    currency: 'BRL',
    status: 'OPEN',
    paid_at: null,
    notes: null,
    ...partial,
  }
}

function card(partial: Partial<CreditCardOut> & { id: string }): CreditCardOut {
  return {
    workspace_id: 'ws',
    financial_institution_id: 'fi',
    financial_institution_name: 'FI',
    fi_logo_slug: null,
    name: 'Card',
    brand: null,
    last4: null,
    currency: 'BRL',
    credit_limit: null,
    close_day: 5,
    due_day: 15,
    is_active: true,
    open_invoice_total: 0,
    limit_used_pct: null,
    created_at: '2026-08-09T00:00:00',
    ...partial,
  }
}

describe('filterInvoices', () => {
  const xs = [
    inv({ id: 'a', status: 'OPEN', due_date: '2026-08-15' }),
    inv({ id: 'b', status: 'CLOSED', due_date: '2026-07-15' }),
    inv({ id: 'c', status: 'PAID', due_date: '2026-06-15', paid_at: '2026-06-14', credit_card_account_id: 'card2' }),
  ]

  it('"open" inclui OPEN e CLOSED (não pagas)', () => {
    expect(filterInvoices(xs, 'open', []).map(i => i.id)).toEqual(['a', 'b'])
  })

  it('"paid" só PAID', () => {
    expect(filterInvoices(xs, 'paid', []).map(i => i.id)).toEqual(['c'])
  })

  it('filtra por cartão e ordena por vencimento desc', () => {
    expect(filterInvoices(xs, 'all', ['card1']).map(i => i.id)).toEqual(['a', 'b'])
    expect(filterInvoices(xs, 'all', []).map(i => i.id)).toEqual(['a', 'b', 'c'])
  })
})

describe('invoiceKpis', () => {
  it('separa em aberto, pagas YTD e média', () => {
    const k = invoiceKpis([
      inv({ id: 'a', status: 'OPEN', total_amount: 100 }),
      inv({ id: 'b', status: 'CLOSED', total_amount: 200 }),
      inv({ id: 'c', status: 'PAID', total_amount: 300, paid_at: '2026-05-10' }),
      inv({ id: 'd', status: 'PAID', total_amount: 400, paid_at: '2025-12-10' }),  // ano anterior
      inv({ id: 'e', status: 'OPEN', total_amount: null }),                         // OPEN sem total
    ], 2026)
    expect(k.totalOpen).toBe(300)
    expect(k.openCount).toBe(3)
    expect(k.totalPaidYTD).toBe(300)
    expect(k.paidCount).toBe(1)
    expect(k.avgInvoice).toBe((100 + 200 + 300 + 400) / 4)
  })
})

describe('cardKpis', () => {
  it('totaliza fatura aberta, limite e disponível', () => {
    const k = cardKpis([
      card({ id: '1', open_invoice_total: 1000, credit_limit: 10000 }),
      card({ id: '2', open_invoice_total: 500, credit_limit: null }),
    ])
    expect(k.total).toBe(1500)
    expect(k.totalLimit).toBe(10000)
    expect(k.available).toBe(8500)
    expect(k.usedPct).toBe(0.15)
  })

  it('sem limite → usedPct 0', () => {
    expect(cardKpis([card({ id: '1', open_invoice_total: 100 })]).usedPct).toBe(0)
  })
})
