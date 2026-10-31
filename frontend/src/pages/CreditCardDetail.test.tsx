/* Spec 69/70 — detalhe do cartão (/credit-cards/:id): hero da fatura aberta,
 * faturas anteriores, fluxos "Fechar fatura", "Nova fatura" e "Pagar
 * fatura", lançamentos reais da fatura aberta.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

import CreditCardDetail from './CreditCardDetail'
import { api, type AccountOut, type CreditCardOut, type InvoiceOut, type TransactionOut, type UserOut } from '../lib/api'

const admin: UserOut = {
  id: 'u1', email: 'd@x.com', name: 'Dani', role: 'admin',
  workspace_id: 'ws1', workspace_name: 'Família', is_active: true,
  created_at: '2026-01-01T00:00:00Z',
}
const member: UserOut = { ...admin, id: 'u2', role: 'member' }

const visa: CreditCardOut = {
  id: 'c1', workspace_id: 'ws1',
  financial_institution_id: 'fi1', financial_institution_name: 'Itaú', fi_logo_slug: null,
  name: 'Itaú Visa', brand: 'Visa', last4: '4421', currency: 'BRL',
  credit_limit: 10000, close_day: 5, due_day: 15, is_active: true,
  open_invoice_total: 2500, limit_used_pct: 0.25,
  created_at: '2026-08-09T00:00:00',
}

function inv(partial: Partial<InvoiceOut> & { id: string }): InvoiceOut {
  return {
    workspace_id: 'ws1', credit_card_account_id: 'c1', credit_card_name: 'Itaú Visa',
    close_date: '2026-10-05', due_date: '2026-10-15', total_amount: null, iof_total: null,
    currency: 'BRL', status: 'OPEN', paid_at: null, notes: null,
    ...partial,
  }
}

const openInv = inv({ id: 'open', close_date: '2026-11-05', due_date: '2026-11-15', iof_total: 12.5 })
const closedInv = inv({ id: 'closed', status: 'CLOSED', total_amount: 1800 })
const paidInv = inv({ id: 'paid', status: 'PAID', close_date: '2026-09-05', due_date: '2026-09-15', total_amount: 900, paid_at: '2026-09-14' })

const itau: AccountOut = {
  id: 'acc1', workspace_id: 'ws1', financial_institution_id: 'fi1', financial_institution_name: 'Itaú',
  name: 'Conta Corrente Itaú', account_type: 'checking', currency: 'BRL', opening_balance: null,
  account_info: null, is_active: true, created_at: '2026-01-01T00:00:00Z',
}

function tx(partial: Partial<TransactionOut> & { id: string }): TransactionOut {
  return {
    workspace_id: 'ws1', source_type: 'CREDIT_CARD', checking_account_id: null, account_name: null,
    credit_card_account_id: 'c1', card_name: 'Itaú Visa', financial_institution_name: 'Itaú', fi_logo_slug: null,
    invoice_id: 'open', event_date: '2026-10-20', description: 'Compra', amount: -100, currency: 'BRL',
    fx_rate: 5, fx_source: 'PTAX', amount_brl: -100, amount_usd: -20, category_id: null, category_name: null,
    category_parent_name: null, category_color: null, category_kind: null, party_id: null, party_name: null,
    tags: [], installment_number: null, installment_total: null, parent_transaction_id: null,
    paid_invoice_id: null, transfer_group_id: null, is_reconciled: false, notes: null,
    created_at: '2026-10-20T00:00:00Z', updated_at: '2026-10-20T00:00:00Z',
    ...partial,
  }
}

function mockTxs(items: TransactionOut[] = []) {
  return vi.spyOn(api, 'listTransactions').mockResolvedValue({ items, total: items.length, page: 1, page_size: 500 })
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/credit-cards/c1']}>
      <Routes>
        <Route path="/credit-cards/:id" element={<CreditCardDetail />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('CreditCardDetail page (spec 69)', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(api, 'listSnapshots').mockResolvedValue([])
    vi.spyOn(api, 'listInvoices').mockResolvedValue([])
    vi.spyOn(api, 'listCreditCards').mockResolvedValue([visa])
    vi.spyOn(api, 'listAccounts').mockResolvedValue([itau])
    vi.spyOn(api, 'listCategories').mockResolvedValue([])
    mockTxs()
  })

  it('hero mostra fatura aberta, vencimento, limite e IOF', async () => {
    vi.spyOn(api, 'me').mockResolvedValue(admin)
    vi.spyOn(api, 'listCardInvoices').mockResolvedValue([openInv, closedInv, paidInv])
    renderPage()

    expect(await screen.findByRole('heading', { name: 'Itaú Visa' })).toBeInTheDocument()
    expect(screen.getByText(/vence 15\/11\/26/)).toBeInTheDocument()
    expect(screen.getByText('25.0%')).toBeInTheDocument()
    expect(screen.getByText(/12,50/)).toBeInTheDocument()  // IOF da fatura aberta
  })

  it('faturas anteriores excluem a aberta e mostram status', async () => {
    vi.spyOn(api, 'me').mockResolvedValue(admin)
    vi.spyOn(api, 'listCardInvoices').mockResolvedValue([openInv, closedInv, paidInv])
    renderPage()

    await screen.findByText('Faturas anteriores')
    expect(screen.queryByText('Fecho 05/11/26')).not.toBeInTheDocument()
    expect(screen.getByText('Fecho 05/10/26')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Pagar/ })).toBeInTheDocument()
    expect(screen.getByText('Paga em 14/09/26')).toBeInTheDocument()
  })

  it('Fechar fatura: envia o total digitado em pt-BR e recarrega', async () => {
    vi.spyOn(api, 'me').mockResolvedValue(admin)
    const listInv = vi.spyOn(api, 'listCardInvoices')
      .mockResolvedValueOnce([openInv])
      .mockResolvedValueOnce([{ ...openInv, status: 'CLOSED', total_amount: 2345.67 }])
    const close = vi.spyOn(api, 'closeInvoice').mockResolvedValue({ ...openInv, status: 'CLOSED', total_amount: 2345.67 })
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: /Fechar fatura/ }))
    const dialog = screen.getByText('Fechar fatura?').parentElement!
    fireEvent.change(within(dialog).getByPlaceholderText('0,00'), { target: { value: '2.345,67' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Fechar fatura' }))

    await waitFor(() => expect(close).toHaveBeenCalledWith('open', 2345.67))
    await waitFor(() => expect(screen.queryByText('Fechar fatura?')).not.toBeInTheDocument())
    expect(listInv).toHaveBeenCalledTimes(2)
    // fatura deixou de estar aberta → some o botão de fechar
    expect(screen.queryByRole('button', { name: /Fechar fatura/ })).not.toBeInTheDocument()
  })

  it('Fechar fatura: total vazio desabilita a confirmação', async () => {
    vi.spyOn(api, 'me').mockResolvedValue(admin)
    vi.spyOn(api, 'listCardInvoices').mockResolvedValue([openInv])
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: /Fechar fatura/ }))
    const dialog = screen.getByText('Fechar fatura?').parentElement!
    expect(within(dialog).getByRole('button', { name: 'Fechar fatura' })).toBeDisabled()
  })

  it('Fechar fatura: erro do backend vira toast e o modal fica aberto', async () => {
    vi.spyOn(api, 'me').mockResolvedValue(admin)
    vi.spyOn(api, 'listCardInvoices').mockResolvedValue([openInv])
    vi.spyOn(api, 'closeInvoice').mockRejectedValue(new Error('Fatura já fechada'))
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: /Fechar fatura/ }))
    const dialog = screen.getByText('Fechar fatura?').parentElement!
    fireEvent.change(within(dialog).getByPlaceholderText('0,00'), { target: { value: '10' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Fechar fatura' }))

    expect(await screen.findByText('Fatura já fechada')).toBeInTheDocument()
    expect(screen.getByText('Fechar fatura?')).toBeInTheDocument()
  })

  it('ESC fecha o modal de fechar fatura', async () => {
    vi.spyOn(api, 'me').mockResolvedValue(admin)
    vi.spyOn(api, 'listCardInvoices').mockResolvedValue([openInv])
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: /Fechar fatura/ }))
    fireEvent.keyDown(document, { key: 'Escape' })
    await waitFor(() => expect(screen.queryByText('Fechar fatura?')).not.toBeInTheDocument())
  })

  it('Nova fatura cria pelo cartão da página', async () => {
    vi.spyOn(api, 'me').mockResolvedValue(admin)
    vi.spyOn(api, 'listCardInvoices').mockResolvedValue([])
    const create = vi.spyOn(api, 'createInvoice').mockResolvedValue(openInv)
    const { container } = renderPage()

    fireEvent.click(await screen.findByRole('button', { name: /Nova fatura/ }))
    const dates = container.ownerDocument.querySelectorAll('input[type="date"]')
    fireEvent.change(dates[0], { target: { value: '2026-11-05' } })
    fireEvent.change(dates[1], { target: { value: '2026-11-15' } })
    fireEvent.click(screen.getByRole('button', { name: 'Criar' }))

    await waitFor(() => expect(create).toHaveBeenCalledWith('c1', {
      close_date: '2026-11-05', due_date: '2026-11-15', total_amount: null,
    }))
  })

  it('member não vê ações de escrita', async () => {
    vi.spyOn(api, 'me').mockResolvedValue(member)
    vi.spyOn(api, 'listCardInvoices').mockResolvedValue([openInv, closedInv])
    renderPage()

    await screen.findByRole('heading', { name: 'Itaú Visa' })
    expect(screen.queryByRole('button', { name: /Nova fatura/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Fechar fatura/ })).not.toBeInTheDocument()
  })

  it('fatura aberta é a OPEN de fechamento mais próximo (parcelas criam OPEN futuras)', async () => {
    vi.spyOn(api, 'me').mockResolvedValue(admin)
    const future = inv({ id: 'future', close_date: '2026-12-05', due_date: '2026-12-15' })
    vi.spyOn(api, 'listCardInvoices').mockResolvedValue([future, openInv])  // ordem desc do backend
    mockTxs([
      tx({ id: 't1', description: 'Mercado' }),
      tx({ id: 't2', description: 'Notebook', installment_number: 1, installment_total: 3, amount: -333.34 }),
      tx({ id: 't3', description: 'Notebook', invoice_id: 'future', installment_number: 2, installment_total: 3, amount: -333.33 }),
    ])
    renderPage()

    expect(await screen.findByText(/vence 15\/11\/26/)).toBeInTheDocument()
    expect(screen.getByText('Mercado')).toBeInTheDocument()
    expect(screen.getByText('parc. 1/3')).toBeInTheDocument()
    expect(screen.queryByText('parc. 2/3')).not.toBeInTheDocument()   // está na fatura seguinte
    // futura não aparece em "Faturas anteriores"
    expect(screen.queryByText('Fecho 05/12/26')).not.toBeInTheDocument()
    // KPIs: 2 lançamentos, 1 parcelada, próxima fatura estimada R$ 333,33
    const main = within(screen.getByRole('main'))
    expect(main.getByText('Lançamentos').parentElement).toHaveTextContent('2')
    expect(main.getByText('Compras parceladas').parentElement).toHaveTextContent('1')
    expect(main.getByText(/Próx\. fatura/).parentElement).toHaveTextContent('333,33')
  })

  it('Fechar fatura sugere a soma dos lançamentos', async () => {
    vi.spyOn(api, 'me').mockResolvedValue(admin)
    vi.spyOn(api, 'listCardInvoices').mockResolvedValue([openInv])
    mockTxs([tx({ id: 't1', amount: -100 }), tx({ id: 't2', amount: -50.5 }), tx({ id: 't3', amount: 20 })])
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: /Fechar fatura/ }))
    const dialog = screen.getByText('Fechar fatura?').parentElement!
    expect(within(dialog).getByPlaceholderText('0,00')).toHaveValue('130,5')
  })

  it('Pagar fatura: escolhe conta, envia valor e recarrega', async () => {
    vi.spyOn(api, 'me').mockResolvedValue(admin)
    vi.spyOn(api, 'listCardInvoices').mockResolvedValue([openInv, closedInv])
    const pay = vi.spyOn(api, 'payInvoice').mockResolvedValue({ ...closedInv, status: 'PAID', paid_at: '2026-10-14' })
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: /Pagar/ }))
    const dialog = screen.getByRole('dialog', { name: 'Pagar fatura' })
    expect(within(dialog).getByLabelText('Valor pago')).toHaveValue('1800')
    fireEvent.change(within(dialog).getByLabelText('Data do pagamento'), { target: { value: '2026-10-14' } })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Pagar fatura' }))

    await waitFor(() => expect(pay).toHaveBeenCalledWith('closed', {
      checking_account_id: 'acc1', paid_on: '2026-10-14', amount: 1800, category_id: null,
    }))
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Pagar fatura' })).not.toBeInTheDocument())
  })

  it('Pagar fatura: erro do backend fica no modal; ESC fecha', async () => {
    vi.spyOn(api, 'me').mockResolvedValue(admin)
    vi.spyOn(api, 'listCardInvoices').mockResolvedValue([openInv, closedInv])
    vi.spyOn(api, 'payInvoice').mockRejectedValue(new Error('Fatura já paga.'))
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: /Pagar/ }))
    const dialog = screen.getByRole('dialog', { name: 'Pagar fatura' })
    fireEvent.click(within(dialog).getByRole('button', { name: 'Pagar fatura' }))
    expect(await within(dialog).findByText('Fatura já paga.')).toBeInTheDocument()
    fireEvent.keyDown(document, { key: 'Escape' })
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Pagar fatura' })).not.toBeInTheDocument())
  })

  it('Lançamento abre o composer de cartão já no cartão da página', async () => {
    vi.spyOn(api, 'me').mockResolvedValue(member)
    vi.spyOn(api, 'listCardInvoices').mockResolvedValue([openInv])
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: /^Lançamento$/ }))
    const dialog = await screen.findByRole('dialog', { name: 'Lançamento de Cartão' })
    expect(within(dialog).getByLabelText('Cartão')).toHaveValue('c1')
  })
})
