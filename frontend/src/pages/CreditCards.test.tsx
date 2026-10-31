/* Spec 69 — página /credit-cards: lista, KPIs, modal de criação (botão e
 * ?compose=card), gate de escrita por role e badge de contagem no sidebar.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

import CreditCards from './CreditCards'
import { api, type CreditCardOut, type FinancialInstitutionOut, type UserOut } from '../lib/api'
import { CARDS_CHANGED_EVENT } from '../lib/useCardCounts'

const admin: UserOut = {
  id: 'u1', email: 'd@x.com', name: 'Dani', role: 'admin',
  workspace_id: 'ws1', workspace_name: 'Família', is_active: true,
  created_at: '2026-01-01T00:00:00Z',
}
const member: UserOut = { ...admin, id: 'u2', role: 'member' }

const itau: FinancialInstitutionOut = {
  id: 'fi1', long_name: 'Itaú Unibanco', short_name: 'Itaú', logo_slug: null,
  brand_color: null, has_logo: false, country: 'BR', is_active: true,
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
}

function card(partial: Partial<CreditCardOut> & { id: string; name: string }): CreditCardOut {
  return {
    workspace_id: 'ws1',
    financial_institution_id: 'fi1',
    financial_institution_name: 'Itaú',
    fi_logo_slug: null,
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

function renderPage(path = '/credit-cards') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/credit-cards" element={<CreditCards />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('CreditCards page (spec 69)', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(api, 'listSnapshots').mockResolvedValue([])
    vi.spyOn(api, 'listInvoices').mockResolvedValue([])
    vi.spyOn(api, 'listFinancialInstitutions').mockResolvedValue([itau])
  })

  it('lista cartões com fatura aberta, % do limite e KPIs somados', async () => {
    vi.spyOn(api, 'me').mockResolvedValue(admin)
    vi.spyOn(api, 'listCreditCards').mockResolvedValue([
      card({ id: 'c1', name: 'Itaú Visa', brand: 'Visa', last4: '4421', open_invoice_total: 1000, credit_limit: 10000, limit_used_pct: 0.1 }),
      card({ id: 'c2', name: 'Nubank', open_invoice_total: 500, credit_limit: 5000, limit_used_pct: 0.1 }),
    ])
    renderPage()

    expect(await screen.findByText('Itaú Visa')).toBeInTheDocument()
    expect(screen.getByText('Nubank')).toBeInTheDocument()
    expect(screen.getByText(/···· 4421/)).toBeInTheDocument()
    expect(screen.getByText(/2 cartões · 10% do limite total utilizado/)).toBeInTheDocument()
    // KPIs: total em fatura aberta R$ 1.500, limite R$ 15.000, disponível R$ 13.500
    expect(screen.getByText(/1\.500,00/)).toBeInTheDocument()
    expect(screen.getByText(/15\.000,00/)).toBeInTheDocument()
    expect(screen.getByText(/13\.500,00/)).toBeInTheDocument()
    // linha do cartão leva ao detalhe
    expect(screen.getByText('Itaú Visa').closest('a')).toHaveAttribute('href', '/credit-cards/c1')
  })

  it('empty state quando não há cartões', async () => {
    vi.spyOn(api, 'me').mockResolvedValue(admin)
    vi.spyOn(api, 'listCreditCards').mockResolvedValue([])
    renderPage()
    expect(await screen.findByText(/Nenhum cartão ainda/)).toBeInTheDocument()
  })

  it('erro de carga aparece na página e não desloga', async () => {
    vi.spyOn(api, 'me').mockResolvedValue(admin)
    vi.spyOn(api, 'listCreditCards').mockRejectedValue(new Error('boom 500'))
    renderPage()
    expect(await screen.findByText('boom 500')).toBeInTheDocument()
  })

  it('member não vê "Novo cartão"', async () => {
    vi.spyOn(api, 'me').mockResolvedValue(member)
    vi.spyOn(api, 'listCreditCards').mockResolvedValue([card({ id: 'c1', name: 'Itaú Visa' })])
    renderPage()
    await screen.findByText('Itaú Visa')
    expect(screen.queryByRole('button', { name: /Novo cartão/ })).not.toBeInTheDocument()
  })

  it('cria cartão pelo modal, converte limite pt-BR e avisa o sidebar', async () => {
    vi.spyOn(api, 'me').mockResolvedValue(admin)
    vi.spyOn(api, 'listCreditCards').mockResolvedValue([])
    const create = vi.spyOn(api, 'createCreditCard').mockResolvedValue(card({ id: 'new', name: 'Itaú Black' }))
    const changed = vi.fn()
    window.addEventListener(CARDS_CHANGED_EVENT, changed)

    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: /Novo cartão/ }))
    fireEvent.change(screen.getByPlaceholderText('Ex: Itaú Visa Infinite'), { target: { value: 'Itaú Black' } })
    fireEvent.change(screen.getByPlaceholderText('35.000,00'), { target: { value: '35.000,00' } })
    fireEvent.click(screen.getByRole('button', { name: 'Salvar' }))

    await waitFor(() => expect(create).toHaveBeenCalledTimes(1))
    expect(create.mock.calls[0][0]).toMatchObject({
      name: 'Itaú Black', financial_institution_id: 'fi1', currency: 'BRL',
      credit_limit: 35000, close_day: 5, due_day: 15, brand: null, last4: null,
    })
    expect(await screen.findByText('Itaú Black')).toBeInTheDocument()
    expect(screen.queryByText('Novo cartão de crédito')).not.toBeInTheDocument()
    expect(changed).toHaveBeenCalled()
    window.removeEventListener(CARDS_CHANGED_EVENT, changed)
  })

  it('?compose=card abre o modal e ESC fecha', async () => {
    vi.spyOn(api, 'me').mockResolvedValue(admin)
    vi.spyOn(api, 'listCreditCards').mockResolvedValue([])
    renderPage('/credit-cards?compose=card')
    expect(await screen.findByText('Novo cartão de crédito')).toBeInTheDocument()
    fireEvent.keyDown(document, { key: 'Escape' })
    await waitFor(() => expect(screen.queryByText('Novo cartão de crédito')).not.toBeInTheDocument())
  })

  it('sidebar mostra a contagem de cartões e faturas', async () => {
    vi.spyOn(api, 'me').mockResolvedValue(admin)
    vi.spyOn(api, 'listCreditCards').mockResolvedValue([card({ id: 'c1', name: 'A' }), card({ id: 'c2', name: 'B' })])
    vi.spyOn(api, 'listInvoices').mockResolvedValue([
      { id: 'i1', workspace_id: 'ws1', credit_card_account_id: 'c1', credit_card_name: 'A', close_date: '2026-08-05',
        due_date: '2026-08-15', total_amount: null, iof_total: null, currency: 'BRL', status: 'OPEN', paid_at: null, notes: null },
    ])
    renderPage()
    expect(await screen.findByTestId('sidebar-count-credit-cards')).toHaveTextContent('2')
    expect(await screen.findByTestId('sidebar-count-invoices')).toHaveTextContent('1')
  })
})
