/* Spec 70 fase 3 — /accounts/:id (detalhe da conta corrente): hero com saldo
 * derivado, KPIs do mês, conferência com os fechamentos, saldo de abertura
 * editável e vínculo do ativo CASH. Fixtures no shape real do backend
 * (GET /accounts/{id}, /balance-check) — lição jsdom_misses_backend_shape.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

import AccountDetail, { momChange } from './AccountDetail'
import {
  api, type AccountDetailOut, type AssetOut, type BalanceCheckRow, type TransactionOut, type UserOut,
} from '../lib/api'

const admin: UserOut = {
  id: 'u1', email: 'd@x.com', name: 'Dani', role: 'admin',
  workspace_id: 'ws1', workspace_name: 'Família', is_active: true,
  created_at: '2026-01-01T00:00:00Z',
}
const member: UserOut = { ...admin, id: 'u2', role: 'member' }

function detail(partial: Partial<AccountDetailOut> = {}): AccountDetailOut {
  return {
    id: 'itau', workspace_id: 'ws1', financial_institution_id: 'fi1', financial_institution_name: 'Itaú',
    name: 'Conta Corrente Itaú', account_type: 'checking', currency: 'BRL',
    opening_balance: 47496.71, opening_balance_date: '2026-08-31', balance_from_ledger: false, account_info: null,
    is_active: true, created_at: '2026-09-05T00:00:00',
    fi_long_name: 'Itaú Unibanco S.A.', fi_logo_slug: null,
    balance: 33720, balance_brl: 33720,
    balance_series: [
      { date: '2026-05-31', balance: 47496.71 }, { date: '2026-06-30', balance: 47496.71 },
      { date: '2026-07-31', balance: 47496.71 }, { date: '2026-08-31', balance: 47496.71 },
      { date: '2026-09-30', balance: 40000 }, { date: '2026-10-31', balance: 33720 },
    ],
    month: { inflows: 1000, outflows: -7280, net: -6280 },
    linked_asset: { id: 'cash1', name: 'Saldo em Conta (Itaú)' },
    ...partial,
  }
}

const check: BalanceCheckRow[] = [
  { snapshot_id: 's10', period_end_date: '2026-10-31', status: 'IN_REVIEW', typed: 33720, derived: 33720, difference: 0 },
  { snapshot_id: 's9', period_end_date: '2026-09-30', status: 'CLOSED', typed: 33720, derived: 40000, difference: 6280 },
]

function tx(partial: Partial<TransactionOut> & { id: string }): TransactionOut {
  return {
    workspace_id: 'ws1', source_type: 'CHECKING', checking_account_id: 'itau', account_name: 'Conta Corrente Itaú',
    credit_card_account_id: null, card_name: null, financial_institution_name: 'Itaú', fi_logo_slug: null,
    invoice_id: null, event_date: '2026-10-10', description: 'Aluguel', amount: -7280, currency: 'BRL',
    fx_rate: 5, fx_source: 'PTAX', amount_brl: -7280, amount_usd: -1456, category_id: null, category_name: null,
    category_parent_name: null, category_color: null, category_kind: null, party_id: null, party_name: null,
    tags: [], installment_number: null, installment_total: null, parent_transaction_id: null,
    paid_invoice_id: null, transfer_group_id: null, is_reconciled: false, notes: null,
    created_at: '2026-10-10T00:00:00Z', updated_at: '2026-10-10T00:00:00Z',
    ...partial,
  }
}

function cash(id: string, name: string, linked: string | null = null): AssetOut {
  return {
    id, workspace_id: 'ws1', workspace_name: 'Família', account_id: 'inv', account_name: 'Conta Investimento',
    financial_institution_id: 'fi1', financial_institution_name: 'Itaú', asset_class: 'CASH', country: 'BR',
    name, ticker: null, cnpj: null, currency: 'BRL', current_price: null, price_updated_at: null,
    price_source: null, price_tier: 'UNKNOWN', notes: null, external_id: null, external_source: null,
    is_active: true, details: null, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
    linked_account_id: linked,
  } as unknown as AssetOut
}

function mockBase(user: UserOut = admin, d: AccountDetailOut = detail()) {
  vi.spyOn(api, 'me').mockResolvedValue(user)
  vi.spyOn(api, 'listSnapshots').mockResolvedValue([])
  vi.spyOn(api, 'listCreditCards').mockResolvedValue([])
  vi.spyOn(api, 'listInvoices').mockResolvedValue([])
  vi.spyOn(api, 'listCategories').mockResolvedValue([])
  vi.spyOn(api, 'listAssets').mockResolvedValue([cash('cash1', 'Saldo em Conta (Itaú)', 'itau'), cash('cash2', 'Saldo em Conta (XP)'), cash('cash3', 'Saldo Outro', 'other')])
  vi.spyOn(api, 'getAccount').mockResolvedValue(d)
  vi.spyOn(api, 'accountBalanceCheck').mockResolvedValue(check)
  vi.spyOn(api, 'listTransactions').mockResolvedValue({ items: [tx({ id: 't1' })], total: 1, page: 1, page_size: 500 })
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/accounts/itau']}>
      <Routes>
        <Route path="/accounts/:id" element={<AccountDetail />} />
      </Routes>
    </MemoryRouter>,
  )
}

const mainReady = async () => within(await screen.findByRole('main'))

describe('momChange', () => {
  it('variação do último ponto contra o anterior', () => {
    expect(momChange([{ balance: 100 }, { balance: 110 }])).toBeCloseTo(0.1)
    expect(momChange([{ balance: 0 }, { balance: 110 }])).toBeNull()
    expect(momChange([{ balance: 1 }])).toBeNull()
  })
})

describe('AccountDetail page (spec 70 fase 3)', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('hero com saldo derivado, KPIs do mês, movimentações e conferência', async () => {
    mockBase()
    renderPage()
    const m = await mainReady()
    expect(await m.findByRole('heading', { name: 'Conta Corrente Itaú' })).toBeInTheDocument()
    expect(m.getByText('Itaú Unibanco S.A.')).toBeInTheDocument()
    expect(m.getByTestId('account-balance')).toHaveTextContent('33.720,00')
    expect(m.getByText('Entradas · mês').parentElement).toHaveTextContent('1.000,00')
    expect(m.getByText('Aluguel')).toBeInTheDocument()
    expect(m.getByTestId('opening-balance')).toHaveTextContent('47.496,71')
    expect(m.getByTestId('linked-asset')).toHaveTextContent('Saldo em Conta (Itaú)')
    const table = within(m.getByTestId('balance-check'))
    expect(table.getByText('confere')).toBeInTheDocument()
    expect(table.getByText(/\+ R\$ 6\.280,00/)).toBeInTheDocument()
    expect(m.getByText(/Fechamento fechado não é recalculado sozinho/)).toBeInTheDocument()
  })

  it('conta em USD mostra o equivalente em BRL', async () => {
    mockBase(admin, detail({ currency: 'USD', name: 'Conta Corrente Nomad', balance: 1000, balance_brl: 5400 }))
    renderPage()
    const m = await mainReady()
    expect(await m.findByText('R$ 5.400,00')).toBeInTheDocument()
  })

  it('erro de carga aparece na página e não desloga', async () => {
    mockBase()
    vi.spyOn(api, 'getAccount').mockRejectedValue(new Error('Account not found.'))
    renderPage()
    expect(await (await mainReady()).findByText('Account not found.')).toBeInTheDocument()
  })

  it('member não vê edição de abertura nem de vínculo', async () => {
    mockBase(member)
    renderPage()
    const m = await mainReady()
    await m.findByRole('heading', { name: 'Conta Corrente Itaú' })
    expect(m.queryByRole('button', { name: 'Editar saldo de abertura' })).not.toBeInTheDocument()
    expect(m.queryByRole('button', { name: 'Alterar vínculo' })).not.toBeInTheDocument()
    expect(m.queryByRole('button', { name: 'Ligar saldo pelas movimentações' })).not.toBeInTheDocument()
  })

  it('interruptor: nasce digitado, liga pelas movimentações e mostra erro inline', async () => {
    mockBase()
    const patch = vi.spyOn(api, 'updateBalanceSource')
      .mockRejectedValueOnce(new Error('Defina o saldo de abertura antes de ligar.'))
      .mockResolvedValueOnce(detail({ balance_from_ledger: true }))
    renderPage()
    const m = await mainReady()
    expect(await m.findByTestId('balance-source')).toHaveTextContent('Digitado no fechamento')
    fireEvent.click(m.getByRole('button', { name: 'Ligar saldo pelas movimentações' }))
    expect(await m.findByText('Defina o saldo de abertura antes de ligar.')).toBeInTheDocument()
    vi.spyOn(api, 'getAccount').mockResolvedValue(detail({ balance_from_ledger: true }))
    fireEvent.click(m.getByRole('button', { name: 'Ligar saldo pelas movimentações' }))
    await waitFor(() => expect(patch).toHaveBeenLastCalledWith('itau', true))
    await waitFor(() => expect(m.getByTestId('balance-source')).toHaveTextContent('Vem das movimentações'))
    expect(m.getByRole('button', { name: 'Desligar saldo pelas movimentações' })).toBeEnabled()
  })

  it('interruptor desabilitado sem data de abertura', async () => {
    mockBase()
    vi.spyOn(api, 'getAccount').mockResolvedValue(detail({ opening_balance_date: null }))
    renderPage()
    const m = await mainReady()
    expect(await m.findByRole('button', { name: 'Ligar saldo pelas movimentações' })).toBeDisabled()
  })

  it('editar saldo de abertura: exige data, envia pt-BR e fecha no ESC', async () => {
    mockBase()
    const patch = vi.spyOn(api, 'updateOpeningBalance').mockResolvedValue(detail({ opening_balance: 12000, opening_balance_date: '2025-12-31' }))
    renderPage()
    const m = await mainReady()
    fireEvent.click(await m.findByRole('button', { name: 'Editar saldo de abertura' }))
    let dialog = within(screen.getByRole('dialog', { name: 'Saldo de abertura' }))
    fireEvent.change(dialog.getByLabelText('Data do saldo de abertura'), { target: { value: '' } })
    expect(dialog.getByRole('button', { name: 'Salvar' })).toBeDisabled()
    fireEvent.keyDown(document, { key: 'Escape' })
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Saldo de abertura' })).not.toBeInTheDocument())

    fireEvent.click(m.getByRole('button', { name: 'Editar saldo de abertura' }))
    dialog = within(screen.getByRole('dialog', { name: 'Saldo de abertura' }))
    fireEvent.change(dialog.getByLabelText('Saldo de abertura'), { target: { value: '12.000,00' } })
    fireEvent.change(dialog.getByLabelText('Data do saldo de abertura'), { target: { value: '2025-12-31' } })
    fireEvent.click(dialog.getByRole('button', { name: 'Salvar' }))
    await waitFor(() => expect(patch).toHaveBeenCalledWith('itau', { opening_balance: 12000, opening_balance_date: '2025-12-31' }))
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Saldo de abertura' })).not.toBeInTheDocument())
  })

  it('vínculo: só lista CASH livre (ou o atual) e permite desvincular', async () => {
    mockBase()
    const link = vi.spyOn(api, 'setLinkedAsset').mockResolvedValue(detail({ linked_asset: null }))
    renderPage()
    const m = await mainReady()
    fireEvent.click(await m.findByRole('button', { name: 'Alterar vínculo' }))
    const dialog = within(screen.getByRole('dialog', { name: 'Ativo no fechamento' }))
    const opts = within(dialog.getByLabelText('Ativo CASH')).getAllByRole('option').map(o => o.textContent)
    expect(opts).toEqual(['Sem vínculo', 'Saldo em Conta (Itaú)', 'Saldo em Conta (XP)'])
    fireEvent.change(dialog.getByLabelText('Ativo CASH'), { target: { value: '' } })
    fireEvent.click(dialog.getByRole('button', { name: 'Salvar' }))
    await waitFor(() => expect(link).toHaveBeenCalledWith('itau', null))
  })

  it('erro ao salvar vínculo fica no modal', async () => {
    mockBase()
    vi.spyOn(api, 'setLinkedAsset').mockRejectedValue(new Error('Ativo já espelha outra conta corrente.'))
    renderPage()
    const m = await mainReady()
    fireEvent.click(await m.findByRole('button', { name: 'Alterar vínculo' }))
    const dialog = within(screen.getByRole('dialog', { name: 'Ativo no fechamento' }))
    fireEvent.click(dialog.getByRole('button', { name: 'Salvar' }))
    expect(await dialog.findByText('Ativo já espelha outra conta corrente.')).toBeInTheDocument()
  })

  it('Movimentação abre o composer já na conta', async () => {
    mockBase()
    renderPage()
    const m = await mainReady()
    fireEvent.click(await m.findByRole('button', { name: /Movimentação/ }))
    const d = within(await screen.findByRole('dialog', { name: 'Nova Movimentação' }))
    expect(d.getByLabelText('Conta')).toHaveValue('itau')
  })

  it('conta de investimento mostra só o header', async () => {
    mockBase(admin, detail({ account_type: 'investment', name: 'Conta Investimento XP', balance: null, month: null, balance_series: [], linked_asset: null }))
    const list = vi.spyOn(api, 'listTransactions')
    renderPage()
    const m = await mainReady()
    expect(await m.findByText(/Conta de investimento — as posições estão em/)).toBeInTheDocument()
    expect(list).not.toHaveBeenCalled()
  })

  // ── audit adversarial 2026-10-31 ──────────────────────────────────────────

  it('saldo de abertura: valor inválido diz "Valor inválido", data faltando diz a data', async () => {
    mockBase()
    renderPage()
    const m = await mainReady()
    fireEvent.click(await m.findByRole('button', { name: 'Editar saldo de abertura' }))
    const dialog = within(screen.getByRole('dialog', { name: 'Saldo de abertura' }))
    fireEvent.change(dialog.getByLabelText('Saldo de abertura'), { target: { value: 'abc' } })
    expect(dialog.getByText('Valor inválido.')).toBeInTheDocument()
    expect(dialog.queryByText('Informe a data do saldo de abertura.')).not.toBeInTheDocument()
    expect(dialog.getByRole('button', { name: 'Salvar' })).toBeDisabled()
    fireEvent.change(dialog.getByLabelText('Saldo de abertura'), { target: { value: '10,00' } })
    fireEvent.change(dialog.getByLabelText('Data do saldo de abertura'), { target: { value: '' } })
    expect(dialog.queryByText('Valor inválido.')).not.toBeInTheDocument()
    expect(dialog.getByText('Informe a data do saldo de abertura.')).toBeInTheDocument()
  })

  it('falha no recarregamento depois de salvar a abertura vira toast e o modal fecha', async () => {
    mockBase()
    vi.spyOn(api, 'updateOpeningBalance').mockResolvedValue(detail({ opening_balance: 10 }))
    renderPage()
    const m = await mainReady()
    fireEvent.click(await m.findByRole('button', { name: 'Editar saldo de abertura' }))
    vi.spyOn(api, 'getAccount').mockRejectedValue(new Error('503 indisponível'))
    const dialog = within(screen.getByRole('dialog', { name: 'Saldo de abertura' }))
    fireEvent.change(dialog.getByLabelText('Saldo de abertura'), { target: { value: '10' } })
    fireEvent.click(dialog.getByRole('button', { name: 'Salvar' }))
    expect(await screen.findByText(/Salvo, mas a página não recarregou: 503 indisponível/)).toBeInTheDocument()
    expect(screen.queryByRole('dialog', { name: 'Saldo de abertura' })).not.toBeInTheDocument()
  })

  it('composer da conta envia os anexos escolhidos', async () => {
    mockBase()
    vi.spyOn(api, 'listAttachments').mockResolvedValue([])
    vi.spyOn(api, 'createTransaction').mockResolvedValue([tx({ id: 'novo' })])
    const upload = vi.spyOn(api, 'uploadAttachment').mockResolvedValue({ id: 'att1' } as never)
    renderPage()
    const m = await mainReady()
    fireEvent.click(await m.findByRole('button', { name: /Movimentação/ }))
    const dialog = await screen.findByRole('dialog', { name: 'Nova Movimentação' })
    const d = within(dialog)
    fireEvent.change(d.getByLabelText('Descrição'), { target: { value: 'Aluguel' } })
    fireEvent.change(d.getByLabelText('Valor'), { target: { value: '100' } })
    await userEvent.upload(d.getByTestId('notes-attachments-input') as HTMLInputElement,
      new File(['pdf'], 'recibo.pdf', { type: 'application/pdf' }))
    fireEvent.click(d.getByRole('button', { name: /Salvar/ }))
    await waitFor(() => expect(upload).toHaveBeenCalledWith('transaction', 'novo', expect.any(File)))
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Nova Movimentação' })).not.toBeInTheDocument())
  })

  it('movimentações acima de 500: Carregar mais pede a página 2 da conta', async () => {
    mockBase()
    const list = vi.spyOn(api, 'listTransactions')
      .mockResolvedValueOnce({ items: [tx({ id: 't1', description: 'Aluguel' })], total: 2, page: 1, page_size: 500 })
      .mockResolvedValueOnce({ items: [tx({ id: 't2', description: 'Condomínio' })], total: 2, page: 2, page_size: 500 })
    renderPage()
    const m = await mainReady()
    await m.findByText('Aluguel')
    expect(m.getByText('mostrando 1 de 2')).toBeInTheDocument()
    fireEvent.click(m.getByRole('button', { name: 'Carregar mais' }))
    expect(await m.findByText('Condomínio')).toBeInTheDocument()
    expect(list).toHaveBeenLastCalledWith({ account_id: ['itau'], page: 2 })
  })
})

