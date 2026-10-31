/* Spec 72 — página /scheduled-transactions (Contas a Pagar/Receber) +
 * composer "Conta a pagar/receber".
 *
 * Fixtures = shape real do backend (ScheduledTransactionOut /
 * RecurrenceRuleOut / ForecastOut completos) — lição jsdom_misses_backend_shape.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

import ScheduledTransactions, {
  endOfMonthISO, groupByDueMonth, ruleSchedule, startOfMonthISO,
} from './ScheduledTransactions'
import { previewDueDates } from '../components/ScheduledComposer'
import {
  api, type AccountOut, type CategoryOut, type ForecastOut, type RecurrenceRuleOut,
  type ScheduledTransactionOut, type TransactionOut, type UserOut,
} from '../lib/api'

function user(role: string): UserOut {
  return {
    id: 'u1', email: 'd@x.com', name: 'Dani', role,
    workspace_id: 'ws1', workspace_name: 'Família', is_active: true,
    created_at: '2026-01-01T00:00:00Z',
  }
}

const itau: AccountOut = {
  id: 'itau', workspace_id: 'ws1', financial_institution_id: 'fi1', financial_institution_name: 'Itaú',
  name: 'Conta Corrente Itaú', account_type: 'checking', currency: 'BRL', opening_balance: null,
  account_info: null, is_active: true, created_at: '2026-01-01T00:00:00Z',
}
const nomad: AccountOut = { ...itau, id: 'nomad', name: 'Conta Corrente Nomad', currency: 'USD' }

const categories: CategoryOut[] = [
  { id: 'mor', workspace_id: 'ws1', name: 'Moradia', parent_id: null, kind: null, color: '#f97316', is_active: true, created_at: '2026-08-09' },
  { id: 'alug', workspace_id: 'ws1', name: 'Aluguel', parent_id: 'mor', kind: 'EXPENSE', color: null, is_active: true, created_at: '2026-08-09' },
]

function occ(p: Partial<ScheduledTransactionOut> & { id: string }): ScheduledTransactionOut {
  return {
    workspace_id: 'ws1', direction: 'PAYABLE', recurrence_rule_id: null, frequency: null,
    description: 'Aluguel', party_id: null, party_name: null, category_id: null, category_name: null,
    category_color: null, amount: 2500, signed_amount: -2500, currency: 'BRL', due_date: '2026-11-05',
    installment_number: null, installment_total: null, expected_account_id: null, expected_account_name: null,
    status: 'PENDING', display_status: 'PENDING', is_overdue: false, paid_at: null, paid_by_transaction_id: null,
    notes: null, created_at: '2026-10-31T00:00:00', updated_at: '2026-10-31T00:00:00',
    slot_date: p.due_date ?? '2026-11-05',
    ...p,
  }
}

function rule(p: Partial<RecurrenceRuleOut> & { id: string }): RecurrenceRuleOut {
  return {
    workspace_id: 'ws1', direction: 'PAYABLE', description: 'Aluguel', party_id: null, party_name: null,
    category_id: null, category_name: null, category_color: null, amount: 2500, currency: 'BRL',
    frequency: 'MONTHLY', day_of_month: 5, month: null, installment_total: null, installment_paid: null,
    expected_account_id: null, expected_account_name: null, start_date: '2026-10-31', end_date: null,
    is_active: true, notes: null, next_due_date: '2026-11-05', pending_count: 3,
    held_slot_dates: [], held_installment_numbers: [],
    created_at: '2026-10-31T00:00:00', updated_at: '2026-10-31T00:00:00',
    ...p,
  }
}

const forecast: ForecastOut = {
  months: [
    {
      month: '2026-10', count: 2, payable: { brl: 2500, usd: 500 }, receivable: { brl: 12000, usd: 2400 },
      net: { brl: 9500, usd: 1900 },
      by_account: [{ account_id: 'itau', account_name: 'Conta Corrente Itaú', currency: 'BRL', payable: 2500, receivable: 12000, net: 9500 }],
    },
    { month: '2026-11', count: 1, payable: { brl: 2500, usd: 500 }, receivable: { brl: 0, usd: 0 }, net: { brl: -2500, usd: -500 }, by_account: [] },
    { month: '2026-12', count: 0, payable: { brl: 0, usd: 0 }, receivable: { brl: 0, usd: 0 }, net: { brl: 0, usd: 0 }, by_account: [] },
  ],
  overdue: { count: 1, payable: { brl: 800, usd: 160 }, receivable: { brl: 0, usd: 0 } },
  fx_rate: 5,
}

function txOut(p: Partial<TransactionOut> & { id: string }): TransactionOut {
  return {
    workspace_id: 'ws1', source_type: 'CHECKING', checking_account_id: 'itau', account_name: 'Conta Corrente Itaú',
    credit_card_account_id: null, card_name: null, financial_institution_name: 'Itaú', fi_logo_slug: null,
    invoice_id: null, event_date: '2026-10-04', description: 'PIX IMOBILIARIA', amount: -2500, currency: 'BRL',
    fx_rate: 5, fx_source: 'PTAX', amount_brl: -2500, amount_usd: -500, category_id: null, category_name: null,
    category_parent_name: null, category_color: null, category_kind: null, party_id: null, party_name: null,
    tags: [], installment_number: null, installment_total: null, parent_transaction_id: null,
    paid_invoice_id: null, transfer_group_id: null, is_reconciled: true, notes: null,
    created_at: '2026-10-04T00:00:00Z', updated_at: '2026-10-04T00:00:00Z',
    ...p,
  }
}

const overdueOcc = occ({ id: 'late', description: 'Condomínio', due_date: '2026-09-10', amount: 800, signed_amount: -800, display_status: 'OVERDUE', is_overdue: true })
const parcel = occ({
  id: 'fin', description: 'Financiamento', recurrence_rule_id: 'r2', frequency: 'INSTALLMENT', due_date: '2026-11-10',
  installment_number: 37, installment_total: 180,
})
const salary = occ({ id: 'sal', direction: 'RECEIVABLE', description: 'Salário', amount: 12000, signed_amount: 12000, due_date: '2026-11-01', recurrence_rule_id: 'r1', frequency: 'MONTHLY' })
const paid = occ({ id: 'paid', description: 'Luz', due_date: '2026-10-02', status: 'PAID', display_status: 'PAID', paid_at: '2026-10-02' })

function mockBase(role = 'admin', opts: { rows?: ScheduledTransactionOut[]; overdue?: ScheduledTransactionOut[]; rules?: RecurrenceRuleOut[] } = {}) {
  vi.spyOn(api, 'me').mockResolvedValue(user(role))
  vi.spyOn(api, 'listSnapshots').mockResolvedValue([])
  vi.spyOn(api, 'listAccounts').mockResolvedValue([itau, nomad])
  vi.spyOn(api, 'listCategories').mockResolvedValue(categories)
  vi.spyOn(api, 'listParties').mockResolvedValue([])
  vi.spyOn(api, 'scheduledForecast').mockResolvedValue(forecast)
  vi.spyOn(api, 'listRecurrenceRules').mockResolvedValue(opts.rules ?? [
    rule({ id: 'r1', direction: 'RECEIVABLE', description: 'Salário', amount: 12000, day_of_month: 1 }),
    rule({ id: 'r2', description: 'Financiamento', frequency: 'INSTALLMENT', installment_total: 180, installment_paid: 36, day_of_month: 10, is_active: false }),
  ])
  return vi.spyOn(api, 'listScheduled').mockImplementation(async f =>
    f?.overdue ? (opts.overdue ?? [overdueOcc]) : (opts.rows ?? [parcel, salary, paid]),
  )
}

function renderPage(path = '/scheduled-transactions') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/scheduled-transactions" element={<ScheduledTransactions />} />
        <Route path="/login" element={<div>LOGIN PAGE</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

const mainReady = async () => within(await screen.findByRole('main'))

describe('helpers', () => {
  it('groupByDueMonth agrupa crescente (atrasadas primeiro)', () => {
    const g = groupByDueMonth([salary, overdueOcc, parcel])
    expect(g.map(x => x.ym)).toEqual(['2026-09', '2026-11'])
    expect(g[1].items.map(x => x.id)).toEqual(['sal', 'fin'])
  })

  it('ruleSchedule descreve a frequência', () => {
    expect(ruleSchedule(rule({ id: 'a' }))).toBe('Mensal · dia 5')
    expect(ruleSchedule(rule({ id: 'b', frequency: 'YEARLY', month: 3, day_of_month: 15 }))).toBe('Anual · 15/03')
    expect(ruleSchedule(rule({ id: 'c', frequency: 'INSTALLMENT', installment_total: 12 }))).toBe('Parcelada · 12x · dia 5')
  })

  it('previewDueDates espelha o backend (início, parcelas, anual, fim)', () => {
    expect(previewDueDates({ frequency: 'MONTHLY', day: 5, start: '2026-10-31' }).map(p => p.date))
      .toEqual(['2026-11-05', '2026-12-05', '2027-01-05'])
    expect(previewDueDates({ frequency: 'INSTALLMENT', day: 10, start: '2026-11-01', installmentTotal: 38, installmentPaid: 36 }))
      .toEqual([{ date: '2026-11-10', k: 37 }, { date: '2026-12-10', k: 38 }])
    expect(previewDueDates({ frequency: 'YEARLY', day: 15, month: 3, start: '2026-04-01' }).map(p => p.date))
      .toEqual(['2027-03-15', '2028-03-15', '2029-03-15'])
    expect(previewDueDates({ frequency: 'MONTHLY', day: 5, start: '2026-01-01', end: '2026-02-10' }).map(p => p.date))
      .toEqual(['2026-01-05', '2026-02-05'])
    expect(previewDueDates({ frequency: 'MONTHLY', day: 30, start: '2026-01-01' })).toEqual([])
  })

  it('janela de datas é local (sem bug de UTC)', () => {
    const base = new Date(2026, 9, 31, 23, 30)
    expect(startOfMonthISO(base)).toBe('2026-10-01')
    expect(endOfMonthISO(0, base)).toBe('2026-10-31')
    expect(endOfMonthISO(2, base)).toBe('2026-12-31')
  })
})

describe('ScheduledTransactions page (spec 72)', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('KPIs do mês + atrasadas + lista agrupada por mês com badges e parcela k/N', async () => {
    const list = mockBase()
    renderPage()
    const m = await mainReady()
    expect(await m.findByText('Financiamento')).toBeInTheDocument()
    expect(m.getByTestId('kpi-payable')).toHaveTextContent('2,5k')
    expect(m.getByTestId('kpi-receivable')).toHaveTextContent('12,0k')
    expect(m.getByTestId('kpi-net')).toHaveTextContent('9,5k')
    expect(m.getByTestId('kpi-overdue')).toHaveTextContent('1')
    expect(m.getByText('Setembro · 2026')).toBeInTheDocument()
    expect(m.getAllByText('Novembro · 2026').length).toBeGreaterThan(0)
    expect(m.getByText('parcela 37/180')).toBeInTheDocument()
    expect(within(m.getByTestId('occ-late')).getByText('Em atraso')).toBeInTheDocument()
    expect(within(m.getByTestId('occ-sal')).getByText('A vencer')).toBeInTheDocument()
    expect(within(m.getByTestId('occ-sal')).getByText('+ R$ 12.000,00')).toBeInTheDocument()
    expect(within(m.getByTestId('occ-fin')).getByText('− R$ 2.500,00')).toBeInTheDocument()
    // pagas ficam escondidas até o toggle
    expect(m.queryByTestId('occ-paid')).not.toBeInTheDocument()
    fireEvent.click(m.getByLabelText(/mostrar pagas e canceladas/))
    expect(within(m.getByTestId('occ-paid')).getByText('Pago')).toBeInTheDocument()
    // forecast por conta
    expect(within(m.getByTestId('forecast-table')).getByText('Conta Corrente Itaú')).toBeInTheDocument()
    // janela: mês corrente até +2 meses, mais as atrasadas
    expect(list).toHaveBeenCalledWith({ overdue: true })
    expect(list).toHaveBeenCalledWith({ from: startOfMonthISO() })
  })

  it('erro de carga aparece na página e não desloga', async () => {
    mockBase()
    vi.spyOn(api, 'scheduledForecast').mockRejectedValue(new Error('boom 500'))
    renderPage()
    expect(await (await mainReady()).findByText('boom 500')).toBeInTheDocument()
    expect(screen.queryByText('LOGIN PAGE')).not.toBeInTheDocument()
  })

  it('member vê em modo leitura: sem botões de escrita e ?compose ignorado', async () => {
    mockBase('member')
    renderPage('/scheduled-transactions?compose=scheduled')
    const m = await mainReady()
    await m.findByText('Financiamento')
    expect(m.queryByRole('button', { name: /Nova conta/ })).not.toBeInTheDocument()
    expect(m.queryByRole('button', { name: 'Marcar pago' })).not.toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('Marcar pago: lista candidatas, vincula a tx, recarrega; ESC fecha', async () => {
    const list = mockBase()
    const cands = vi.spyOn(api, 'scheduledCandidates').mockResolvedValue([txOut({ id: 'tx1' })])
    const pay = vi.spyOn(api, 'payScheduled').mockResolvedValue(occ({ id: 'late', status: 'PAID', display_status: 'PAID' }))
    renderPage()
    const m = await mainReady()
    await m.findByText('Condomínio')

    fireEvent.click(within(m.getByTestId('occ-late')).getByRole('button', { name: 'Marcar pago' }))
    let dialog = within(await screen.findByRole('dialog', { name: 'Marcar pago' }))
    expect(cands).toHaveBeenCalledWith('late')
    expect(dialog.getByTestId('pay-no-link-warning')).toBeInTheDocument()
    fireEvent.keyDown(document, { key: 'Escape' })
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Marcar pago' })).not.toBeInTheDocument())

    fireEvent.click(within(m.getByTestId('occ-late')).getByRole('button', { name: 'Marcar pago' }))
    dialog = within(await screen.findByRole('dialog', { name: 'Marcar pago' }))
    await waitFor(() => expect(dialog.getAllByRole('option').length).toBe(2))
    fireEvent.change(dialog.getByLabelText('Movimentação que quitou'), { target: { value: 'tx1' } })
    expect(dialog.getByLabelText('Data do pagamento')).toHaveValue('2026-10-04')
    expect(dialog.queryByTestId('pay-no-link-warning')).not.toBeInTheDocument()
    const before = list.mock.calls.length
    fireEvent.click(dialog.getByRole('button', { name: 'Marcar pago' }))
    await waitFor(() => expect(pay).toHaveBeenCalledWith('late', { paid_at: '2026-10-04', transaction_id: 'tx1' }))
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Marcar pago' })).not.toBeInTheDocument())
    expect(list.mock.calls.length).toBeGreaterThan(before)
  })

  it('Marcar pago sem vínculo manda transaction_id null; erro fica no modal', async () => {
    mockBase()
    vi.spyOn(api, 'scheduledCandidates').mockResolvedValue([])
    const pay = vi.spyOn(api, 'payScheduled').mockRejectedValue(new Error('Conta já paga'))
    renderPage()
    const m = await mainReady()
    await m.findByText('Condomínio')
    fireEvent.click(within(m.getByTestId('occ-late')).getByRole('button', { name: 'Marcar pago' }))
    const dialog = within(await screen.findByRole('dialog', { name: 'Marcar pago' }))
    await waitFor(() => expect(dialog.getByRole('option', { name: 'Sem vincular movimentação' })).toBeInTheDocument())
    fireEvent.click(dialog.getByRole('button', { name: 'Marcar pago' }))
    await waitFor(() => expect(pay).toHaveBeenCalledWith('late', expect.objectContaining({ transaction_id: null })))
    expect(await dialog.findByRole('alert')).toHaveTextContent('Conta já paga')
    expect(screen.getByRole('dialog', { name: 'Marcar pago' })).toBeInTheDocument()
  })

  it('Adiar e Cancelar pelo menu ⋯', async () => {
    mockBase()
    const postpone = vi.spyOn(api, 'postponeScheduled').mockResolvedValue(salary)
    const cancel = vi.spyOn(api, 'cancelScheduled').mockResolvedValue(salary)
    renderPage()
    const m = await mainReady()
    await m.findByText('Salário')

    const row = () => within(m.getByTestId('occ-sal'))
    fireEvent.click(row().getByRole('button', { name: 'Ações' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Adiar' }))
    let dialog = within(await screen.findByRole('dialog', { name: 'Adiar vencimento' }))
    expect(dialog.getByRole('button', { name: 'Adiar' })).toBeDisabled()
    fireEvent.change(dialog.getByLabelText('Novo vencimento'), { target: { value: '2026-11-15' } })
    fireEvent.click(dialog.getByRole('button', { name: 'Adiar' }))
    await waitFor(() => expect(postpone).toHaveBeenCalledWith('sal', '2026-11-15'))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())

    fireEvent.click(row().getByRole('button', { name: 'Ações' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Cancelar' }))
    dialog = within(await screen.findByRole('dialog', { name: 'Cancelar conta?' }))
    expect(dialog.getByText(/a recorrência continua gerando/)).toBeInTheDocument()
    fireEvent.click(dialog.getByRole('button', { name: 'Cancelar conta' }))
    await waitFor(() => expect(cancel).toHaveBeenCalledWith('sal'))
  })

  it('aba Recorrências: lista, pausa/reativa e exclui com confirmação', async () => {
    mockBase()
    const update = vi.spyOn(api, 'updateRecurrenceRule').mockResolvedValue({ rule: rule({ id: 'r1' }), created_count: 0, dropped_count: 3 })
    const del = vi.spyOn(api, 'deleteRecurrenceRule').mockResolvedValue(undefined)
    renderPage()
    const m = await mainReady()
    await m.findByText('Financiamento')
    fireEvent.click(m.getByRole('button', { name: 'Recorrências (2)' }))

    const r1 = within(m.getByTestId('rule-r1'))
    expect(r1.getByText('Mensal · dia 1')).toBeInTheDocument()
    expect(r1.getByText('Ativa')).toBeInTheDocument()
    const r2 = within(m.getByTestId('rule-r2'))
    expect(r2.getByText('Parcelada · 180x · dia 10')).toBeInTheDocument()
    expect(r2.getByText('Pausada')).toBeInTheDocument()

    fireEvent.click(r1.getByRole('button', { name: 'Pausar' }))
    await waitFor(() => expect(update).toHaveBeenCalledWith('r1', { is_active: false }))
    fireEvent.click(r2.getByRole('button', { name: 'Reativar' }))
    await waitFor(() => expect(update).toHaveBeenCalledWith('r2', { is_active: true }))

    fireEvent.click(r1.getByRole('button', { name: 'Excluir' }))
    const dialog = within(await screen.findByRole('dialog', { name: 'Excluir recorrência?' }))
    fireEvent.click(dialog.getByRole('button', { name: 'Excluir' }))
    await waitFor(() => expect(del).toHaveBeenCalledWith('r1'))
  })

  it('falha ao pausar vai pro toast da página', async () => {
    mockBase()
    vi.spyOn(api, 'updateRecurrenceRule').mockRejectedValue(new Error('403 Admin'))
    renderPage()
    const m = await mainReady()
    await m.findByText('Financiamento')
    fireEvent.click(m.getByRole('button', { name: 'Recorrências (2)' }))
    fireEvent.click(within(m.getByTestId('rule-r1')).getByRole('button', { name: 'Pausar' }))
    expect(await screen.findByRole('status')).toHaveTextContent('403 Admin')
  })
})

describe('Composer "Conta a pagar/receber"', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('?compose=scheduled abre o composer; avulsa a pagar sai com valor positivo', async () => {
    mockBase()
    const create = vi.spyOn(api, 'createScheduled').mockResolvedValue(occ({ id: 'new' }))
    renderPage('/scheduled-transactions?compose=scheduled')
    const d = within(await screen.findByRole('dialog', { name: 'Nova conta a pagar/receber' }))
    fireEvent.change(d.getByLabelText('Descrição'), { target: { value: 'IPVA 2027' } })
    fireEvent.change(d.getByLabelText('Valor'), { target: { value: '1.234,56' } })
    fireEvent.change(d.getByLabelText('Vencimento'), { target: { value: '2027-01-20' } })
    fireEvent.change(d.getByLabelText('Categoria'), { target: { value: 'alug' } })
    expect(d.getByTestId('scheduled-preview-amount')).toHaveTextContent('− R$ 1.234,56')
    fireEvent.click(d.getByRole('button', { name: /Salvar/ }))
    await waitFor(() => expect(create).toHaveBeenCalledWith(expect.objectContaining({
      direction: 'PAYABLE', description: 'IPVA 2027', amount: 1234.56, due_date: '2027-01-20',
      category_id: 'alug', currency: 'BRL', expected_account_id: null,
    })))
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('recorrência mensal a receber vira rule com day_of_month; moeda vem da conta', async () => {
    mockBase()
    const create = vi.spyOn(api, 'createRecurrenceRule').mockResolvedValue({ rule: rule({ id: 'n' }), created_count: 3, dropped_count: 0 })
    renderPage('/scheduled-transactions?compose=scheduled')
    const d = within(await screen.findByRole('dialog', { name: 'Nova conta a pagar/receber' }))
    fireEvent.click(d.getByRole('button', { name: 'A receber' }))
    fireEvent.click(d.getByRole('button', { name: 'Mensal' }))
    fireEvent.change(d.getByLabelText('Descrição'), { target: { value: 'Consultoria X' } })
    fireEvent.change(d.getByLabelText('Valor'), { target: { value: '3000' } })
    fireEvent.change(d.getByLabelText('Conta prevista'), { target: { value: 'nomad' } })
    expect(d.queryByLabelText('Moeda')).not.toBeInTheDocument()
    fireEvent.change(d.getByLabelText('Dia do vencimento'), { target: { value: '10' } })
    fireEvent.change(d.getByLabelText('Início'), { target: { value: '2026-11-01' } })
    expect(d.getByTestId('scheduled-preview-amount')).toHaveTextContent('+ US$')
    expect(d.getByTestId('scheduled-preview-dates')).toHaveTextContent('10/11/2026 · 10/12/2026 · 10/01/2027')
    fireEvent.click(d.getByRole('button', { name: /Salvar/ }))
    await waitFor(() => expect(create).toHaveBeenCalledWith(expect.objectContaining({
      direction: 'RECEIVABLE', frequency: 'MONTHLY', day_of_month: 10, start_date: '2026-11-01',
      amount: 3000, expected_account_id: 'nomad', month: null, installment_total: null, installment_paid: null,
    })))
    expect(create.mock.calls[0][0].currency).toBeUndefined()
  })

  it('parcelada mostra parcela k/N na prévia; valor 0 não salva; erro fica no modal; ESC fecha', async () => {
    mockBase()
    vi.spyOn(api, 'createRecurrenceRule').mockRejectedValue(new Error('Parcelas já pagas deve ser entre 0 e o total − 1.'))
    renderPage('/scheduled-transactions?compose=scheduled')
    const d = within(await screen.findByRole('dialog', { name: 'Nova conta a pagar/receber' }))
    fireEvent.click(d.getByRole('button', { name: 'Parcelada' }))
    fireEvent.change(d.getByLabelText('Descrição'), { target: { value: 'Financiamento' } })
    fireEvent.change(d.getByLabelText('Valor'), { target: { value: '0' } })
    fireEvent.change(d.getByLabelText('Nº de parcelas'), { target: { value: '180' } })
    fireEvent.change(d.getByLabelText('Parcelas já pagas'), { target: { value: '36' } })
    fireEvent.change(d.getByLabelText('Dia do vencimento'), { target: { value: '10' } })
    fireEvent.change(d.getByLabelText('Início'), { target: { value: '2026-11-01' } })
    expect(d.getByRole('button', { name: /Salvar/ })).toBeDisabled()
    fireEvent.change(d.getByLabelText('Valor'), { target: { value: '1500' } })
    expect(d.getByTestId('scheduled-preview-dates')).toHaveTextContent('10/11/2026 (37/180)')
    fireEvent.click(d.getByRole('button', { name: /Salvar/ }))
    expect(await d.findByRole('alert')).toHaveTextContent('Parcelas já pagas')
    expect(screen.getByRole('dialog', { name: 'Nova conta a pagar/receber' })).toBeInTheDocument()
    fireEvent.keyDown(document, { key: 'Escape' })
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('editar recorrência manda PATCH e avisa que só futuras pendentes mudam', async () => {
    mockBase()
    const update = vi.spyOn(api, 'updateRecurrenceRule').mockResolvedValue({ rule: rule({ id: 'r1' }), created_count: 3, dropped_count: 3 })
    renderPage()
    const m = await mainReady()
    await m.findByText('Financiamento')
    fireEvent.click(m.getByRole('button', { name: 'Recorrências (2)' }))
    fireEvent.click(within(m.getByTestId('rule-r1')).getByRole('button', { name: 'Editar' }))
    const d = within(await screen.findByRole('dialog', { name: 'Editar recorrência' }))
    expect(d.getByText(/só as ocorrências futuras ainda pendentes/)).toBeInTheDocument()
    expect(d.queryByRole('button', { name: 'Avulsa' })).not.toBeInTheDocument()
    fireEvent.change(d.getByLabelText('Valor'), { target: { value: '12.500,00' } })
    fireEvent.click(d.getByRole('button', { name: /Salvar alterações/ }))
    await waitFor(() => expect(update).toHaveBeenCalledWith('r1', expect.objectContaining({
      amount: 12500, frequency: 'MONTHLY', day_of_month: 1, direction: 'RECEIVABLE',
    })))
  })

  it('editar ocorrência isolada só manda os campos da ocorrência', async () => {
    mockBase()
    const update = vi.spyOn(api, 'updateScheduled').mockResolvedValue(salary)
    renderPage()
    const m = await mainReady()
    await m.findByText('Salário')
    const row = within(m.getByTestId('occ-sal'))
    fireEvent.click(row.getByRole('button', { name: 'Ações' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Editar' }))
    const d = within(await screen.findByRole('dialog', { name: 'Editar conta' }))
    expect(d.queryByLabelText('Dia do vencimento')).not.toBeInTheDocument()
    fireEvent.change(d.getByLabelText('Valor'), { target: { value: '12.345,67' } })
    fireEvent.click(d.getByRole('button', { name: /Salvar alterações/ }))
    await waitFor(() => expect(update).toHaveBeenCalledWith('sal', expect.objectContaining({ amount: 12345.67 })))
    expect(update.mock.calls[0][1]).not.toHaveProperty('direction')
  })
})

/* ── audit adversarial (2026-10-31) ─────────────────────────────────────── */

describe('audit 2026-10-31 — prévia da edição espelha o backend', () => {
  it('#6/#20 edição pula slots antes de hoje e meses já mantidos', () => {
    // regra mensal desde jan; hoje 31/10 → próximos são nov/dez/jan
    expect(previewDueDates({ frequency: 'MONTHLY', day: 5, start: '2026-01-01', notBefore: '2026-10-31' }).map(p => p.date))
      .toEqual(['2026-11-05', '2026-12-05', '2027-01-05'])
    // novembro pago adiantado (slot mantido) + dia muda pra 10: novembro não repete
    expect(previewDueDates({
      frequency: 'MONTHLY', day: 10, start: '2026-01-01', notBefore: '2026-10-31', heldSlotDates: ['2026-11-05'],
    }).map(p => p.date)).toEqual(['2026-12-10', '2027-01-10', '2027-02-10'])
    // anual: o ano que já tem ocorrência mantida fica de fora
    expect(previewDueDates({
      frequency: 'YEARLY', day: 20, month: 12, start: '2026-01-01', notBefore: '2026-10-31', heldSlotDates: ['2026-11-20'],
    }).map(p => p.date)).toEqual(['2027-12-20', '2028-12-20', '2029-12-20'])
  })

  it('#18 parcelada: numeração continua da 1ª parcela que ninguém mantém', () => {
    // 12x, parcelas 1..10 mantidas (passado), início movido pra 01/11
    expect(previewDueDates({
      frequency: 'INSTALLMENT', day: 5, start: '2026-11-01', installmentTotal: 12, installmentPaid: 0,
      notBefore: '2026-10-31', heldInstallments: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
    })).toEqual([{ date: '2026-11-05', k: 11 }, { date: '2026-12-05', k: 12 }])
    // parcela 11 paga adiantada (nov mantido): dezembro vira 12 e acabou
    expect(previewDueDates({
      frequency: 'INSTALLMENT', day: 5, start: '2026-01-01', installmentTotal: 12, installmentPaid: 0,
      notBefore: '2026-10-31', heldSlotDates: ['2026-11-05'], heldInstallments: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
    })).toEqual([{ date: '2026-12-05', k: 12 }])
    // "Parcelas já pagas" subindo sobre números mantidos não trava a prévia
    expect(previewDueDates({
      frequency: 'INSTALLMENT', day: 5, start: '2026-01-01', installmentTotal: 12, installmentPaid: 2,
      notBefore: '2026-10-31', heldInstallments: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
    })).toEqual([{ date: '2026-11-05', k: 11 }, { date: '2026-12-05', k: 12 }])
  })
})

describe('audit 2026-10-31 — página e composer', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('#6/#18/#20 editar recorrência: prévia sem datas passadas e com a parcela certa', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date(2026, 9, 31, 12, 0))
    mockBase('admin', {
      rules: [
        rule({ id: 'm', description: 'Aluguel antigo', start_date: '2026-01-01', day_of_month: 5 }),
        rule({
          id: 'p', description: 'Boleto 12x', frequency: 'INSTALLMENT', installment_total: 12, installment_paid: 0,
          start_date: '2026-01-01', day_of_month: 5,
          held_installment_numbers: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
        }),
      ],
    })
    renderPage()
    const m = await mainReady()
    await m.findByText('Financiamento')
    fireEvent.click(m.getByRole('button', { name: 'Recorrências (2)' }))
    fireEvent.click(within(m.getByTestId('rule-m')).getByRole('button', { name: 'Editar' }))
    let d = within(await screen.findByRole('dialog', { name: 'Editar recorrência' }))
    expect(d.getByTestId('scheduled-preview-dates')).toHaveTextContent('05/11/2026 · 05/12/2026 · 05/01/2027')
    fireEvent.keyDown(document, { key: 'Escape' })
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())

    fireEvent.click(within(m.getByTestId('rule-p')).getByRole('button', { name: 'Editar' }))
    d = within(await screen.findByRole('dialog', { name: 'Editar recorrência' }))
    expect(d.getByTestId('scheduled-preview-dates')).toHaveTextContent('05/11/2026 (11/12) · 05/12/2026 (12/12)')
    fireEvent.change(d.getByLabelText('Início'), { target: { value: '2026-11-01' } })
    expect(d.getByTestId('scheduled-preview-dates')).toHaveTextContent('05/11/2026 (11/12) · 05/12/2026 (12/12)')
    expect(d.getByTestId('scheduled-preview-dates')).not.toHaveTextContent('(1/12)')
  })

  it('#21 categoria e fornecedor inativos aparecem "(inativa)" e podem ser limpos', async () => {
    mockBase('admin', {
      rows: [occ({
        id: 'ina', description: 'Com cadastro inativo', category_id: 'old-cat', category_name: 'Antiga',
        party_id: 'old-party', party_name: 'Imobiliária Velha',
      })],
      overdue: [],
    })
    const update = vi.spyOn(api, 'updateScheduled').mockResolvedValue(occ({ id: 'ina' }))
    renderPage()
    const m = await mainReady()
    await m.findByText('Com cadastro inativo')
    fireEvent.click(within(m.getByTestId('occ-ina')).getByRole('button', { name: 'Ações' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Editar' }))
    const d = within(await screen.findByRole('dialog', { name: 'Editar conta' }))
    const cat = d.getByLabelText('Categoria') as HTMLSelectElement
    expect(cat.value).toBe('old-cat')
    expect(cat.selectedOptions[0].textContent).toBe('Antiga (inativa)')
    const party = d.getByLabelText('Fornecedor/Cliente') as HTMLSelectElement
    expect(party.value).toBe('old-party')
    expect(party.selectedOptions[0].textContent).toBe('Imobiliária Velha (inativa)')
    fireEvent.change(cat, { target: { value: '' } })
    fireEvent.change(party, { target: { value: '' } })
    fireEvent.click(d.getByRole('button', { name: /Salvar alterações/ }))
    await waitFor(() => expect(update).toHaveBeenCalledWith('ina', expect.objectContaining({
      category_id: null, party_id: null,
    })))
  })

  it('#21 sem mexer, a categoria inativa é mantida (não vira "Sem categoria" escondida)', async () => {
    mockBase('admin', {
      rows: [occ({ id: 'ina2', description: 'Mantém', category_id: 'old-cat', category_name: 'Antiga' })],
      overdue: [],
    })
    const update = vi.spyOn(api, 'updateScheduled').mockResolvedValue(occ({ id: 'ina2' }))
    renderPage()
    const m = await mainReady()
    await m.findByText('Mantém')
    fireEvent.click(within(m.getByTestId('occ-ina2')).getByRole('button', { name: 'Ações' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Editar' }))
    const d = within(await screen.findByRole('dialog', { name: 'Editar conta' }))
    expect(d.getByRole('option', { name: 'Antiga (inativa)' })).toBeInTheDocument()
    fireEvent.click(d.getByRole('button', { name: /Salvar alterações/ }))
    await waitFor(() => expect(update).toHaveBeenCalledWith('ina2', expect.objectContaining({ category_id: 'old-cat' })))
  })

  it('#22 menu Ações vai num portal fixo fora do wrapper com overflow; ESC e clique fora fecham', async () => {
    mockBase()
    renderPage()
    const m = await mainReady()
    await m.findByText('Salário')
    const row = m.getByTestId('occ-sal')
    fireEvent.click(within(row).getByRole('button', { name: 'Ações' }))
    const menu = screen.getByRole('menu', { name: 'Ações da conta' })
    expect(menu.style.position).toBe('fixed')
    expect(row.closest('.overflow-x-auto')!.contains(menu)).toBe(false)
    expect(within(menu).getAllByRole('menuitem').map(b => b.textContent)).toEqual(['Editar', 'Adiar', 'Cancelar'])
    fireEvent.keyDown(document, { key: 'Escape' })
    await waitFor(() => expect(screen.queryByRole('menu')).not.toBeInTheDocument())
    fireEvent.click(within(row).getByRole('button', { name: 'Ações' }))
    fireEvent.mouseDown(screen.getByTestId('actions-menu-backdrop'))
    await waitFor(() => expect(screen.queryByRole('menu')).not.toBeInTheDocument())
  })

  it('#22 menu abre pra cima quando não cabe embaixo (última linha)', async () => {
    mockBase()
    renderPage()
    const m = await mainReady()
    await m.findByText('Salário')
    const btn = within(m.getByTestId('occ-sal')).getByRole('button', { name: 'Ações' })
    const h = window.innerHeight
    vi.spyOn(btn, 'getBoundingClientRect').mockReturnValue({
      top: h - 30, bottom: h - 6, left: 900, right: 924, width: 24, height: 24, x: 900, y: h - 30, toJSON: () => ({}),
    } as DOMRect)
    fireEvent.click(btn)
    const menu = screen.getByRole('menu', { name: 'Ações da conta' })
    expect(parseFloat(menu.style.top)).toBeLessThan(h - 30)
  })

  it('#16 Desfazer pagamento: só em conta paga, com confirmação e spinner; recarrega', async () => {
    const list = mockBase()
    let resolve!: () => void
    const unpay = vi.spyOn(api, 'unpayScheduled').mockImplementation(() => new Promise(r => {
      resolve = () => r(occ({ id: 'paid' }))
    }))
    renderPage()
    const m = await mainReady()
    await m.findByText('Financiamento')
    fireEvent.click(m.getByLabelText(/mostrar pagas e canceladas/))
    const row = within(m.getByTestId('occ-paid'))
    expect(row.queryByRole('button', { name: 'Marcar pago' })).not.toBeInTheDocument()
    fireEvent.click(row.getByRole('button', { name: 'Ações' }))
    expect(screen.getAllByRole('menuitem').map(b => b.textContent)).toEqual(['Desfazer pagamento'])
    fireEvent.click(screen.getByRole('menuitem', { name: 'Desfazer pagamento' }))
    const d = within(await screen.findByRole('dialog', { name: 'Desfazer pagamento?' }))
    const before = list.mock.calls.length
    const confirm = d.getByRole('button', { name: 'Desfazer pagamento' })
    fireEvent.click(confirm)
    await waitFor(() => expect(unpay).toHaveBeenCalledWith('paid'))
    expect(confirm).toBeDisabled()
    resolve()
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(list.mock.calls.length).toBeGreaterThan(before)
  })

  it('#16 Desfazer pagamento com erro fica no modal; ESC fecha', async () => {
    mockBase()
    vi.spyOn(api, 'unpayScheduled').mockRejectedValue(new Error('Só dá pra desfazer o pagamento de uma conta paga.'))
    renderPage()
    const m = await mainReady()
    await m.findByText('Financiamento')
    fireEvent.click(m.getByLabelText(/mostrar pagas e canceladas/))
    fireEvent.click(within(m.getByTestId('occ-paid')).getByRole('button', { name: 'Ações' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Desfazer pagamento' }))
    const d = within(await screen.findByRole('dialog', { name: 'Desfazer pagamento?' }))
    fireEvent.click(d.getByRole('button', { name: 'Desfazer pagamento' }))
    expect(await d.findByRole('alert')).toHaveTextContent('Só dá pra desfazer')
    fireEvent.keyDown(document, { key: 'Escape' })
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('member não vê o menu Ações nem Desfazer pagamento', async () => {
    mockBase('member')
    renderPage()
    const m = await mainReady()
    await m.findByText('Financiamento')
    fireEvent.click(m.getByLabelText(/mostrar pagas e canceladas/))
    expect(within(m.getByTestId('occ-paid')).queryByRole('button', { name: 'Ações' })).not.toBeInTheDocument()
  })

  it('#23 falha nos cadastros não esconde as listas; aviso inline; não desloga', async () => {
    mockBase()
    vi.spyOn(api, 'listParties').mockRejectedValue(new Error('500 parties'))
    renderPage()
    const m = await mainReady()
    expect(await m.findByText('Financiamento')).toBeInTheDocument()
    expect(await m.findByTestId('lookup-error')).toHaveTextContent('fornecedores/clientes')
    expect(m.getByText('Condomínio')).toBeInTheDocument()
    fireEvent.click(m.getByRole('button', { name: 'Recorrências (2)' }))
    expect(m.getByTestId('rule-r1')).toBeInTheDocument()
    expect(screen.queryByText('LOGIN PAGE')).not.toBeInTheDocument()
    // o que carregou (contas) continua disponível no composer
    fireEvent.click(m.getByRole('button', { name: /Nova conta/ }))
    const d = within(await screen.findByRole('dialog', { name: 'Nova conta a pagar/receber' }))
    expect(d.getByRole('option', { name: /Conta Corrente Itaú/ })).toBeInTheDocument()
  })
})
