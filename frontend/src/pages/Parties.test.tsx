/* Spec 68 — página report-first /parties: lista read-only, busca, empty
 * states e link Gerenciar só pra admin.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

import Parties from './Parties'
import { api, type PartyOut, type UserOut } from '../lib/api'

const admin: UserOut = {
  id: 'u1', email: 'd@x.com', name: 'Dani', role: 'admin',
  workspace_id: 'ws1', workspace_name: 'Família', is_active: true,
  created_at: '2026-01-01T00:00:00Z',
}
const member: UserOut = { ...admin, id: 'u2', role: 'member' }

function party(partial: Partial<PartyOut> & { id: string; name: string }): PartyOut {
  return {
    workspace_id: 'ws1', kind: 'SUPPLIER', notes: null, is_active: true,
    alias_count: 0, created_at: '2026-08-09T00:00:00',
    ...partial,
  }
}

// O topbar (<header>) também tem um "Buscar…" — a busca da página vive no <main>.
function searchBox() {
  return within(screen.getByRole('main')).getByPlaceholderText('Buscar…')
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/parties']}>
      <Routes>
        <Route path="/parties" element={<Parties />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('Parties page (spec 68)', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(api, 'listSnapshots').mockResolvedValue([])
    vi.spyOn(api, 'listCreditCards').mockResolvedValue([])
    vi.spyOn(api, 'listInvoices').mockResolvedValue([])
  })

  it('lista com tipo e contagem de aliases', async () => {
    vi.spyOn(api, 'me').mockResolvedValue(member)
    vi.spyOn(api, 'listParties').mockResolvedValue([
      party({ id: 'p1', name: 'Padaria Real', alias_count: 3 }),
      party({ id: 'p2', name: 'Cliente X', kind: 'CLIENT' }),
    ])
    renderPage()

    expect(await screen.findByText('Padaria Real')).toBeInTheDocument()
    expect(screen.getByText('Fornecedor')).toBeInTheDocument()
    expect(screen.getByText('Cliente')).toBeInTheDocument()
    expect(screen.getByText('3 alias')).toBeInTheDocument()
  })

  it('busca filtra por nome, sem diferenciar maiúsculas', async () => {
    vi.spyOn(api, 'me').mockResolvedValue(member)
    vi.spyOn(api, 'listParties').mockResolvedValue([
      party({ id: 'p1', name: 'Padaria Real' }),
      party({ id: 'p2', name: 'Cliente X', kind: 'CLIENT' }),
    ])
    renderPage()

    await screen.findByText('Padaria Real')
    fireEvent.change(searchBox(), { target: { value: 'PADA' } })
    expect(screen.getByText('Padaria Real')).toBeInTheDocument()
    expect(screen.queryByText('Cliente X')).not.toBeInTheDocument()

    fireEvent.change(searchBox(), { target: { value: 'zzz' } })
    expect(screen.getByText('Nada encontrado.')).toBeInTheDocument()
  })

  it('empty state explica que o import cria as contrapartes', async () => {
    vi.spyOn(api, 'me').mockResolvedValue(member)
    vi.spyOn(api, 'listParties').mockResolvedValue([])
    renderPage()
    expect(await screen.findByText(/Nenhum fornecedor\/cliente ainda/)).toBeInTheDocument()
  })

  it('admin vê "Gerenciar"; member não', async () => {
    vi.spyOn(api, 'listParties').mockResolvedValue([])
    vi.spyOn(api, 'me').mockResolvedValue(admin)
    const { unmount } = renderPage()
    expect(await screen.findByRole('link', { name: /Gerenciar/ })).toHaveAttribute('href', '/admin/registry')
    unmount()

    vi.spyOn(api, 'me').mockResolvedValue(member)
    renderPage()
    await screen.findByText(/Nenhum fornecedor\/cliente ainda/)
    expect(screen.queryByRole('link', { name: /Gerenciar/ })).not.toBeInTheDocument()
  })

  it('erro de carga aparece na página', async () => {
    vi.spyOn(api, 'me').mockResolvedValue(member)
    vi.spyOn(api, 'listParties').mockRejectedValue(new Error('falhou 500'))
    renderPage()
    expect(await screen.findByText('falhou 500')).toBeInTheDocument()
  })
})
