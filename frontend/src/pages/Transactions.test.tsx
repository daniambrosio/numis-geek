/* Spec 70 — página /transactions (Movimentações) + composers de
 * Movimentação, Lançamento de cartão e Transferência.
 *
 * Shapes de fixture = shape real do backend (TransactionOut completo) —
 * lição jsdom_misses_backend_shape: campo undefined derruba modal.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

import Transactions, { groupByMonth, subIdsForRoots } from './Transactions'
import {
  api, type AccountOut, type CategoryOut, type CreditCardOut, type TransactionOut,
  type StatementImportOut, type TransactionSummaryOut, type UserOut,
} from '../lib/api'

const me: UserOut = {
  id: 'u1', email: 'd@x.com', name: 'Dani', role: 'member',
  workspace_id: 'ws1', workspace_name: 'Família', is_active: true,
  created_at: '2026-01-01T00:00:00Z',
}

function account(id: string, name: string, currency: 'BRL' | 'USD' = 'BRL', account_type: 'checking' | 'investment' = 'checking'): AccountOut {
  return {
    id, workspace_id: 'ws1', financial_institution_id: 'fi1', financial_institution_name: 'Banco',
    name, account_type, currency, opening_balance: null, account_info: null, is_active: true,
    created_at: '2026-01-01T00:00:00Z',
  }
}
const itau = account('itau', 'Conta Corrente Itaú')
const wise = account('wise', 'Conta Corrente Wise')
const nomad = account('nomad', 'Conta Corrente Nomad', 'USD')
const invest = account('inv', 'Conta Investimento', 'BRL', 'investment')

const visa: CreditCardOut = {
  id: 'visa', workspace_id: 'ws1', financial_institution_id: 'fi1', financial_institution_name: 'Itaú',
  fi_logo_slug: null, name: 'Itaú Visa', brand: 'Visa', last4: '4421', currency: 'BRL',
  credit_limit: 10000, close_day: 5, due_day: 15, is_active: true, open_invoice_total: 0,
  limit_used_pct: 0, created_at: '2026-08-09T00:00:00',
}

function cat(partial: Partial<CategoryOut> & { id: string; name: string }): CategoryOut {
  return { workspace_id: 'ws1', parent_id: null, kind: null, color: null, is_active: true, created_at: '2026-08-09', ...partial }
}
const categories = [
  cat({ id: 'alim', name: 'Alimentação', color: '#f97316' }),
  cat({ id: 'merc', name: 'Mercado', parent_id: 'alim', kind: 'EXPENSE' }),
  cat({ id: 'rest', name: 'Restaurante', parent_id: 'alim', kind: 'EXPENSE' }),
  cat({ id: 'mov', name: 'Movimentações', color: '#6366f1' }),
  cat({ id: 'transf', name: 'Entre contas', parent_id: 'mov', kind: 'TRANSFER' }),
]

function tx(partial: Partial<TransactionOut> & { id: string }): TransactionOut {
  return {
    workspace_id: 'ws1', source_type: 'CHECKING', checking_account_id: 'itau', account_name: 'Conta Corrente Itaú',
    credit_card_account_id: null, card_name: null, financial_institution_name: 'Itaú', fi_logo_slug: null,
    invoice_id: null, event_date: '2026-10-20', description: 'Padaria', amount: -25.5, currency: 'BRL',
    fx_rate: 5, fx_source: 'PTAX', amount_brl: -25.5, amount_usd: -5.1, category_id: null, category_name: null,
    category_parent_name: null, category_color: null, category_kind: null, party_id: null, party_name: null,
    tags: [], installment_number: null, installment_total: null, parent_transaction_id: null,
    paid_invoice_id: null, transfer_group_id: null, is_reconciled: false, notes: null,
    created_at: '2026-10-20T00:00:00Z', updated_at: '2026-10-20T00:00:00Z',
    ...partial,
  }
}

const summary: TransactionSummaryOut = {
  inflows: { brl: 12000, usd: 2400 }, outflows: { brl: -4500, usd: -900 },
  net: { brl: 7500, usd: 1500 }, unreconciled_count: 3, count: 10,
}

function mockBase(rows: TransactionOut[] = []) {
  vi.spyOn(api, 'me').mockResolvedValue(me)
  vi.spyOn(api, 'listSnapshots').mockResolvedValue([])
  vi.spyOn(api, 'listAccounts').mockResolvedValue([itau, wise, nomad, invest])
  vi.spyOn(api, 'listCreditCards').mockResolvedValue([visa])
  vi.spyOn(api, 'listInvoices').mockResolvedValue([])
  vi.spyOn(api, 'listCategories').mockResolvedValue(categories)
  vi.spyOn(api, 'listParties').mockResolvedValue([])
  vi.spyOn(api, 'listAttachments').mockResolvedValue([])
  vi.spyOn(api, 'transactionSummary').mockResolvedValue(summary)
  return vi.spyOn(api, 'listTransactions').mockResolvedValue({ items: rows, total: rows.length, page: 1, page_size: 500 })
}

function renderPage(path = '/transactions') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/transactions" element={<Transactions />} />
      </Routes>
    </MemoryRouter>,
  )
}

const main = () => within(screen.getByRole('main'))
const mainReady = async () => within(await screen.findByRole('main'))

describe('helpers', () => {
  it('groupByMonth agrupa desc por ano-mês', () => {
    const g = groupByMonth([tx({ id: 'a', event_date: '2026-09-30' }), tx({ id: 'b', event_date: '2026-10-01' }), tx({ id: 'c', event_date: '2026-09-01' })])
    expect(g.map(x => x.ym)).toEqual(['2026-10', '2026-09'])
    expect(g[1].items.map(x => x.id)).toEqual(['a', 'c'])
  })

  it('subIdsForRoots expande raízes nas subs', () => {
    expect(subIdsForRoots(categories, ['alim']).sort()).toEqual(['merc', 'rest'])
    expect(subIdsForRoots(categories, [])).toEqual([])
  })
})

describe('Transactions page (spec 70)', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('KPIs do summary + linhas agrupadas por mês com origem, parcela, categoria e status', async () => {
    mockBase([
      tx({ id: 't1', description: 'Salário', amount: 12000, amount_brl: 12000, is_reconciled: true, event_date: '2026-10-05' }),
      tx({
        id: 't2', source_type: 'CREDIT_CARD', checking_account_id: null, account_name: null,
        credit_card_account_id: 'visa', card_name: 'Itaú Visa', invoice_id: 'inv1',
        description: 'Notebook', amount: -333.34, installment_number: 1, installment_total: 3,
        category_id: 'merc', category_name: 'Mercado', category_color: '#f97316', event_date: '2026-09-10',
      }),
    ])
    renderPage()

    expect(await (await mainReady()).findByText('Salário')).toBeInTheDocument()
    expect(main().getByTestId('kpi-inflows')).toHaveTextContent('12,0k')
    expect(main().getByTestId('kpi-outflows')).toHaveTextContent('4,5k')
    expect(main().getByTestId('kpi-net')).toHaveTextContent('7,5k')
    expect(main().getByTestId('kpi-unreconciled')).toHaveTextContent('3')
    expect(main().getByText('Outubro · 2026')).toBeInTheDocument()
    expect(main().getByText('Setembro · 2026')).toBeInTheDocument()
    expect(main().getByText('parc. 1/3')).toBeInTheDocument()
    expect(main().getAllByText('Mercado').length).toBeGreaterThan(0)
    expect(main().getByText('Sem categoria')).toBeInTheDocument()
    expect(main().getByLabelText('Reconciliada')).toBeInTheDocument()
    expect(main().getByText('transações · 2 fontes', { exact: false })).toBeInTheDocument()
  })

  it('chips de Origem e Categoria viram filtros da API (raiz → subs)', async () => {
    const list = mockBase([])
    renderPage()
    await (await mainReady()).findByText(/Nenhuma movimentação/)

    fireEvent.click(main().getByRole('button', { name: 'Conta Corrente Itaú' }))
    await waitFor(() => expect(list).toHaveBeenLastCalledWith(expect.objectContaining({ account_id: ['itau'], card_id: [] })))
    fireEvent.click(main().getByRole('button', { name: 'Itaú Visa' }))
    await waitFor(() => expect(list).toHaveBeenLastCalledWith(expect.objectContaining({ account_id: ['itau'], card_id: ['visa'] })))
    fireEvent.click(main().getByRole('button', { name: 'Alimentação' }))
    await waitFor(() => {
      const f = list.mock.calls.at(-1)![0]!
      expect([...f.category_id!].sort()).toEqual(['merc', 'rest'])
    })
    // conta de investimento não vira chip de Origem
    expect(main().queryByRole('button', { name: 'Conta Investimento' })).not.toBeInTheDocument()
  })

  it('erro de carga aparece na página e não desloga', async () => {
    mockBase()
    vi.spyOn(api, 'listTransactions').mockRejectedValue(new Error('boom 500'))
    renderPage()
    expect(await (await mainReady()).findByText('boom 500')).toBeInTheDocument()
  })

  it('?compose=transaction: cria saída com valor pt-BR assinado e recarrega', async () => {
    const list = mockBase()
    const create = vi.spyOn(api, 'createTransaction').mockResolvedValue([tx({ id: 'new' })])
    renderPage('/transactions?compose=transaction')

    const dialog = await screen.findByRole('dialog', { name: 'Nova Movimentação' })
    const d = within(dialog)
    fireEvent.change(d.getByLabelText('Descrição'), { target: { value: 'Mercado Pão de Açúcar' } })
    fireEvent.change(d.getByLabelText('Valor'), { target: { value: '1.234,56' } })
    fireEvent.change(d.getByLabelText('Categoria'), { target: { value: 'merc' } })
    expect(d.getByText('− R$ 1.234,56')).toBeInTheDocument()
    const callsBefore = list.mock.calls.length
    fireEvent.click(d.getByRole('button', { name: /Salvar/ }))

    await waitFor(() => expect(create).toHaveBeenCalledWith(expect.objectContaining({
      source_type: 'CHECKING', checking_account_id: 'itau', description: 'Mercado Pão de Açúcar',
      amount: -1234.56, category_id: 'merc',
    })))
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Nova Movimentação' })).not.toBeInTheDocument())
    expect(list.mock.calls.length).toBeGreaterThan(callsBefore)
  })

  it('composer: entrada vira valor positivo; conta só lista correntes; erro fica no modal', async () => {
    mockBase()
    vi.spyOn(api, 'createTransaction').mockRejectedValue(new Error('Sem PTAX'))
    renderPage('/transactions?compose=transaction')

    const d = within(await screen.findByRole('dialog', { name: 'Nova Movimentação' }))
    const opts = within(d.getByLabelText('Conta')).getAllByRole('option').map(o => o.textContent)
    expect(opts).toEqual(['Conta Corrente Itaú · BRL', 'Conta Corrente Wise · BRL', 'Conta Corrente Nomad · USD'])
    fireEvent.click(d.getByRole('button', { name: 'Entrada · receita' }))
    fireEvent.change(d.getByLabelText('Descrição'), { target: { value: 'Salário' } })
    fireEvent.change(d.getByLabelText('Valor'), { target: { value: '100' } })
    fireEvent.click(d.getByRole('button', { name: /Salvar/ }))
    expect(await d.findByText('Sem PTAX')).toBeInTheDocument()
    expect(api.createTransaction).toHaveBeenCalledWith(expect.objectContaining({ amount: 100 }))
  })

  it('composer de cartão: parcelado + internacional manda total, cotação e nota de FX', async () => {
    mockBase()
    const create = vi.spyOn(api, 'createTransaction').mockResolvedValue([tx({ id: 'n1' })])
    renderPage('/transactions?compose=card-tx')

    const d = within(await screen.findByRole('dialog', { name: 'Lançamento de Cartão' }))
    fireEvent.change(d.getByLabelText('Descrição'), { target: { value: 'Apple.com' } })
    fireEvent.click(within(d.getByText('Compra internacional · informar USD + IOF')).getByRole('button'))
    fireEvent.change(d.getByLabelText('Valor USD'), { target: { value: '100' } })
    fireEvent.change(d.getByLabelText('Cotação'), { target: { value: '5,20' } })
    fireEvent.change(d.getByLabelText('IOF'), { target: { value: '18,20' } })
    fireEvent.change(d.getByLabelText('Parcelas'), { target: { value: '3' } })
    expect(d.getByText(/3x de R\$ 179,40/)).toBeInTheDocument()
    fireEvent.click(d.getByRole('button', { name: /Salvar/ }))

    await waitFor(() => expect(create).toHaveBeenCalledWith(expect.objectContaining({
      source_type: 'CREDIT_CARD', credit_card_account_id: 'visa', amount: -538.2,
      fx_rate: 5.2, installments: 3, invoice_id: null,
    })))
    expect(create.mock.calls[0][0].notes).toContain('US$ 100,00 @ R$ 5,2000 + IOF')
  })

  it('composer de cartão: estorno vira crédito positivo', async () => {
    mockBase()
    const create = vi.spyOn(api, 'createTransaction').mockResolvedValue([tx({ id: 'n1' })])
    renderPage('/transactions?compose=card-tx')
    const d = within(await screen.findByRole('dialog', { name: 'Lançamento de Cartão' }))
    fireEvent.change(d.getByLabelText('Descrição'), { target: { value: 'Estorno loja' } })
    fireEvent.change(d.getByLabelText('Valor'), { target: { value: '50' } })
    fireEvent.click(within(d.getByText('Estorno · crédito na fatura')).getByRole('button'))
    fireEvent.click(d.getByRole('button', { name: /Salvar/ }))
    await waitFor(() => expect(create).toHaveBeenCalledWith(expect.objectContaining({ amount: 50, installments: 1 })))
  })

  it('transferência entre moedas pede o valor de entrada e mostra a cotação implícita', async () => {
    mockBase()
    const transfer = vi.spyOn(api, 'createTransfer').mockResolvedValue([tx({ id: 'a' }), tx({ id: 'b' })])
    renderPage('/transactions?compose=transfer')

    const d = within(await screen.findByRole('dialog', { name: 'Transferência' }))
    expect(d.queryByLabelText('Valor que entrou')).not.toBeInTheDocument()
    fireEvent.change(d.getByLabelText('Para'), { target: { value: 'nomad' } })
    fireEvent.change(d.getByLabelText('Valor que saiu'), { target: { value: '5.279,79' } })
    fireEvent.change(d.getByLabelText('Valor que entrou'), { target: { value: '1000' } })
    expect(d.getByText('R$ 5.2798 / US$')).toBeInTheDocument()
    fireEvent.click(d.getByRole('button', { name: /Salvar/ }))

    await waitFor(() => expect(transfer).toHaveBeenCalledWith(expect.objectContaining({
      from_account_id: 'itau', to_account_id: 'nomad', amount_out: 5279.79, amount_in: 1000,
    })))
  })

  it('transferência: mesma conta bloqueia o salvar', async () => {
    mockBase()
    renderPage('/transactions?compose=transfer')
    const d = within(await screen.findByRole('dialog', { name: 'Transferência' }))
    fireEvent.change(d.getByLabelText('Para'), { target: { value: 'itau' } })
    fireEvent.change(d.getByLabelText('Valor que saiu'), { target: { value: '10' } })
    expect(d.getByText('Origem e destino são a mesma conta.')).toBeInTheDocument()
    expect(d.getByRole('button', { name: /Salvar/ })).toBeDisabled()
  })

  it('editar perna de transferência trava o valor e manda só o resto', async () => {
    const leg = tx({ id: 'leg', description: 'Reserva', amount: -1000, transfer_group_id: 'g1' })
    mockBase([leg])
    const update = vi.spyOn(api, 'updateTransaction').mockResolvedValue([leg])
    renderPage()

    fireEvent.click(await (await mainReady()).findByText('Reserva'))
    const d = within(await screen.findByRole('dialog', { name: 'Editar Movimentação' }))
    expect(d.getByLabelText('Valor')).toBeDisabled()
    expect(d.getByLabelText('Conta')).toBeDisabled()
    fireEvent.change(d.getByLabelText('Descrição'), { target: { value: 'Reserva emergência' } })
    fireEvent.click(d.getByRole('button', { name: /Salvar alterações/ }))
    await waitFor(() => expect(update).toHaveBeenCalled())
    const payload = update.mock.calls[0][1]
    expect(payload.description).toBe('Reserva emergência')
    expect(payload).not.toHaveProperty('amount')
  })

  it('excluir 1ª parcela avisa e manda cascade; ESC fecha a confirmação', async () => {
    const parent = tx({
      id: 'p1', source_type: 'CREDIT_CARD', checking_account_id: null, account_name: null,
      credit_card_account_id: 'visa', card_name: 'Itaú Visa', description: 'Geladeira',
      installment_number: 1, installment_total: 10,
    })
    mockBase([parent])
    const del = vi.spyOn(api, 'deleteTransaction').mockResolvedValue(undefined)
    renderPage()

    await (await mainReady()).findByText('Geladeira')
    fireEvent.click(main().getByRole('button', { name: 'Ações' }))
    fireEvent.click(main().getByRole('button', { name: 'Excluir' }))
    const dialog = within(screen.getByRole('dialog', { name: 'Excluir movimentação' }))
    expect(dialog.getByText(/1ª parcela de 10/)).toBeInTheDocument()
    fireEvent.keyDown(document, { key: 'Escape' })
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Excluir movimentação' })).not.toBeInTheDocument())

    fireEvent.click(main().getByRole('button', { name: 'Ações' }))
    fireEvent.click(main().getByRole('button', { name: 'Excluir' }))
    fireEvent.click(within(screen.getByRole('dialog', { name: 'Excluir movimentação' })).getByRole('button', { name: 'Excluir' }))
    await waitFor(() => expect(del).toHaveBeenCalledWith('p1', true))
  })

  it('erro ao excluir vira toast', async () => {
    mockBase([tx({ id: 't1', description: 'Uber' })])
    vi.spyOn(api, 'deleteTransaction').mockRejectedValue(new Error('Fatura já paga'))
    renderPage()
    await (await mainReady()).findByText('Uber')
    fireEvent.click(main().getByRole('button', { name: 'Ações' }))
    fireEvent.click(main().getByRole('button', { name: 'Excluir' }))
    fireEvent.click(within(screen.getByRole('dialog', { name: 'Excluir movimentação' })).getByRole('button', { name: 'Excluir' }))
    expect(await screen.findByText('Fatura já paga')).toBeInTheDocument()
  })

  // ── audit adversarial 2026-10-31 ──────────────────────────────────────────

  it('anexo falhou depois do create: 2º Salvar só re-envia o anexo que falhou, sem criar de novo', async () => {
    mockBase()
    const create = vi.spyOn(api, 'createTransaction').mockResolvedValue([tx({ id: 'new' })])
    const upload = vi.spyOn(api, 'uploadAttachment')
      .mockRejectedValueOnce(new Error('413 grande demais'))
      .mockResolvedValue({ id: 'att1' } as never)
    renderPage('/transactions?compose=transaction')

    const dialog = await screen.findByRole('dialog', { name: 'Nova Movimentação' })
    const d = within(dialog)
    fireEvent.change(d.getByLabelText('Descrição'), { target: { value: 'Mercado' } })
    fireEvent.change(d.getByLabelText('Valor'), { target: { value: '10' } })
    await userEvent.upload(d.getByTestId('notes-attachments-input') as HTMLInputElement,
      new File(['pdf'], 'nota.pdf', { type: 'application/pdf' }))
    fireEvent.click(d.getByRole('button', { name: /Salvar/ }))

    expect(await d.findByText(/alguns anexos falharam/)).toBeInTheDocument()
    expect(create).toHaveBeenCalledTimes(1)
    const retry = d.getByRole('button', { name: /Enviar anexos de novo/ })
    fireEvent.click(retry)
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Nova Movimentação' })).not.toBeInTheDocument())
    expect(create).toHaveBeenCalledTimes(1)
    expect(upload).toHaveBeenCalledTimes(2)
    expect(upload.mock.calls[1][1]).toBe('new')
  })

  it('falha no recarregamento depois do create vai pro toast da página e o composer fecha', async () => {
    const list = mockBase()
    const create = vi.spyOn(api, 'createTransaction').mockResolvedValue([tx({ id: 'new' })])
    renderPage('/transactions?compose=transaction')

    const d = within(await screen.findByRole('dialog', { name: 'Nova Movimentação' }))
    list.mockRejectedValue(new Error('502 gateway'))
    fireEvent.change(d.getByLabelText('Descrição'), { target: { value: 'Mercado' } })
    fireEvent.change(d.getByLabelText('Valor'), { target: { value: '10' } })
    fireEvent.click(d.getByRole('button', { name: /Salvar/ }))

    expect(await screen.findByText(/Salvo, mas a lista não recarregou: 502 gateway/)).toBeInTheDocument()
    expect(screen.queryByRole('dialog', { name: 'Nova Movimentação' })).not.toBeInTheDocument()
    expect(create).toHaveBeenCalledTimes(1)
  })

  it('editar lançamento de cartão sem mudar a data não manda event_date', async () => {
    const card = tx({
      id: 'c1', source_type: 'CREDIT_CARD', checking_account_id: null, account_name: null,
      credit_card_account_id: 'visa', card_name: 'Itaú Visa', invoice_id: 'inv-escolhida', description: 'Livraria',
    })
    mockBase([card])
    const update = vi.spyOn(api, 'updateTransaction').mockResolvedValue([card])
    renderPage()

    fireEvent.click(await (await mainReady()).findByText('Livraria'))
    const d = within(await screen.findByRole('dialog', { name: 'Editar Lançamento de Cartão' }))
    fireEvent.change(d.getByLabelText('Descrição'), { target: { value: 'Livraria Cultura' } })
    fireEvent.click(d.getByRole('button', { name: /Salvar alterações/ }))
    await waitFor(() => expect(update).toHaveBeenCalledTimes(1))
    expect(update.mock.calls[0][1]).not.toHaveProperty('event_date')

    // data mudou → manda
    fireEvent.click(await main().findByText('Livraria'))
    const d2 = within(await screen.findByRole('dialog', { name: 'Editar Lançamento de Cartão' }))
    fireEvent.change(d2.getByLabelText('Data'), { target: { value: '2026-10-25' } })
    fireEvent.click(d2.getByRole('button', { name: /Salvar alterações/ }))
    await waitFor(() => expect(update).toHaveBeenCalledTimes(2))
    expect(update.mock.calls[1][1]).toMatchObject({ event_date: '2026-10-25' })
  })

  it('lista acima de 500: "mostrando X de N" + Carregar mais busca a página 2', async () => {
    const list = mockBase()
    list.mockReset()
    list
      .mockResolvedValueOnce({ items: [tx({ id: 'a', description: 'Primeira' })], total: 2, page: 1, page_size: 500 })
      .mockResolvedValueOnce({ items: [tx({ id: 'b', description: 'Segunda', event_date: '2026-09-01' })], total: 2, page: 2, page_size: 500 })
    renderPage()

    await (await mainReady()).findByText('Primeira')
    expect(main().getByText('mostrando 1 de 2')).toBeInTheDocument()
    fireEvent.click(main().getByRole('button', { name: 'Carregar mais' }))
    expect(await main().findByText('Segunda')).toBeInTheDocument()
    expect(list.mock.calls[1][0]).toMatchObject({ page: 2 })
    expect(main().queryByTestId('load-more')).not.toBeInTheDocument()
  })
})

describe('Transactions — rastreabilidade do import (spec 71)', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('?extraction_job_id filtra pelo arquivo, sem corte de data, e mostra o clipe', async () => {
    const list = mockBase([tx({ id: 't1', extraction_job_id: 'job-1', source_attachment_id: 'att-1', source_attachment_filename: 'itau-out.ofx', is_reconciled: true })])
    renderPage('/transactions?extraction_job_id=job-1')
    const m = await mainReady()
    await waitFor(() => expect(m.getByTestId('import-filter')).toHaveTextContent('Movimentações do arquivo "itau-out.ofx"'))
    await waitFor(() => expect(list).toHaveBeenCalledWith(expect.objectContaining({ extraction_job_id: 'job-1', from: undefined })))
    expect(m.getByRole('button', { name: 'Abrir arquivo de origem: itau-out.ofx' })).toBeInTheDocument()
    fireEvent.click(m.getByRole('button', { name: 'limpar filtro' }))
    await waitFor(() => expect(m.queryByTestId('import-filter')).not.toBeInTheDocument())
  })
})

describe('Transactions — Importar arquivo (spec 71)', () => {
  const job: StatementImportOut = {
    id: 'job-v', status: 'EXTRACTED', source_hint: 'CARD_INVOICE', attachment_id: 'att-v',
    filename: 'fatura.pdf', checking_account_id: null, credit_card_account_id: 'visa',
    statement_period_start: null, statement_period_end: null, line_count: 0, transaction_count: 0,
    error_message: null, cost_usd: null, created_at: '2026-11-02T00:00:00', confirmed_at: null, resumed: false,
  }

  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(api, 'listStatementImports').mockResolvedValue([])
    vi.spyOn(api, 'listInvoiceImports').mockResolvedValue([])
  })

  it('escolhe o cartão, sobe o arquivo e abre a revisão', async () => {
    mockBase()
    const imp = vi.spyOn(api, 'importInvoice').mockResolvedValue(job)
    const stmt = vi.spyOn(api, 'importStatement')
    vi.spyOn(api, 'previewExtraction').mockResolvedValue({
      applied_count: 0, skipped_count: 0, errors: [], bulk_detail: null,
      bank_import: { rows: [], invoice: null, overlaps: [], warnings: [], period: { start: null, end: null }, counts: {} },
    })
    renderPage()
    const m = await mainReady()
    const btn = await m.findByRole('button', { name: /Importar arquivo/ })
    await waitFor(() => expect(btn).toBeEnabled())
    fireEvent.click(btn)
    const d = within(screen.getByRole('dialog', { name: 'Importar arquivo' }))
    expect(d.getByText('Para qual conta ou cartão?')).toBeInTheDocument()
    expect(d.getByLabelText(/Conta Corrente Itaú/)).toBeChecked()
    expect(d.queryByLabelText(/Conta Investimento/)).not.toBeInTheDocument()   // only checking
    fireEvent.click(d.getByLabelText(/Itaú Visa/))
    const file = new File(['%PDF'], 'fatura.pdf', { type: 'application/pdf' })
    await userEvent.upload(d.getByTestId('import-file-input'), file)
    await waitFor(() => expect(imp).toHaveBeenCalledWith('visa', file))
    expect(stmt).not.toHaveBeenCalled()
    expect(await screen.findByRole('dialog', { name: 'Revisar fatura importada' })).toBeInTheDocument()
  })

  it('ESC fecha o seletor; erro do upload vira toast', async () => {
    mockBase()
    vi.spyOn(api, 'importStatement').mockRejectedValue(new Error('Arquivo já importado: "x.ofx"'))
    renderPage()
    const m = await mainReady()
    const btn = await m.findByRole('button', { name: /Importar arquivo/ })
    await waitFor(() => expect(btn).toBeEnabled())
    fireEvent.click(btn)
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByRole('dialog', { name: 'Importar arquivo' })).not.toBeInTheDocument()
    fireEvent.click(btn)
    const d = within(screen.getByRole('dialog', { name: 'Importar arquivo' }))
    await userEvent.upload(d.getByTestId('import-file-input'), new File(['x'], 'x.ofx'))
    expect(await screen.findByText(/Arquivo já importado/)).toBeInTheDocument()
  })

  it('botão fica desabilitado com spinner durante a extração', async () => {
    mockBase()
    let resolve: (v: StatementImportOut) => void = () => {}
    vi.spyOn(api, 'importStatement').mockImplementation(() => new Promise(r => { resolve = r as never }))
    renderPage()
    const m = await mainReady()
    const btn = await m.findByRole('button', { name: /Importar arquivo/ })
    await waitFor(() => expect(btn).toBeEnabled())
    fireEvent.click(btn)
    const d = within(screen.getByRole('dialog', { name: 'Importar arquivo' }))
    await userEvent.upload(d.getByTestId('import-file-input'), new File(['x'], 'x.ofx'))
    expect(await d.findByRole('button', { name: /Lendo arquivo/ })).toBeDisabled()
    fireEvent.keyDown(document, { key: 'Escape' })   // no close mid-upload
    expect(screen.getByRole('dialog', { name: 'Importar arquivo' })).toBeInTheDocument()
    resolve({ ...job, status: 'FAILED', error_message: 'x', source_hint: 'BANK_STATEMENT' })
    expect(await screen.findByText(/Extração falhou/)).toBeInTheDocument()
  })
})

