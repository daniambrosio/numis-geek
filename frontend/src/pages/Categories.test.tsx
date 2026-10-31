/* Spec 68 — página report-first /categories: árvore read-only com badge de
 * tipo em TODA subcategoria (4b014a6), empty state e link Gerenciar só pra admin.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

import Categories from './Categories'
import { api, type CategoryOut, type UserOut } from '../lib/api'

const admin: UserOut = {
  id: 'u1', email: 'd@x.com', name: 'Dani', role: 'admin',
  workspace_id: 'ws1', workspace_name: 'Família', is_active: true,
  created_at: '2026-01-01T00:00:00Z',
}
const member: UserOut = { ...admin, id: 'u2', role: 'member' }

function cat(partial: Partial<CategoryOut> & { id: string; name: string }): CategoryOut {
  return {
    workspace_id: 'ws1', parent_id: null, kind: null, color: null,
    is_active: true, created_at: '2026-08-09T00:00:00',
    ...partial,
  }
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/categories']}>
      <Routes>
        <Route path="/categories" element={<Categories />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('Categories page (spec 68)', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(api, 'listSnapshots').mockResolvedValue([])
    vi.spyOn(api, 'listCreditCards').mockResolvedValue([])
    vi.spyOn(api, 'listInvoices').mockResolvedValue([])
  })

  it('árvore: raiz sem badge, toda sub com badge de tipo', async () => {
    vi.spyOn(api, 'me').mockResolvedValue(admin)
    vi.spyOn(api, 'listCategories').mockResolvedValue([
      cat({ id: 'r1', name: 'Moradia' }),
      cat({ id: 's1', name: 'Aluguel', parent_id: 'r1', kind: 'EXPENSE' }),
      cat({ id: 's2', name: 'Condomínio', parent_id: 'r1', kind: 'EXPENSE' }),
      cat({ id: 'r2', name: 'Trabalho' }),
      cat({ id: 's3', name: 'Salário', parent_id: 'r2', kind: 'INCOME' }),
      cat({ id: 's4', name: 'Entre contas', parent_id: 'r2', kind: 'TRANSFER' }),
    ])
    renderPage()

    expect(await screen.findByText('Moradia')).toBeInTheDocument()
    expect(screen.getAllByText('Despesa')).toHaveLength(2)  // as duas subs EXPENSE, não só exceções
    expect(screen.getAllByText('Renda')).toHaveLength(1)
    expect(screen.getAllByText('Transferência')).toHaveLength(1)
    // raiz é agrupador: linha sem badge
    expect(screen.getByText('Moradia').parentElement!.textContent).toBe('Moradia')
  })

  it('empty state aponta pro import e, pra admin, pros Cadastros', async () => {
    vi.spyOn(api, 'me').mockResolvedValue(admin)
    vi.spyOn(api, 'listCategories').mockResolvedValue([])
    renderPage()
    expect(await screen.findByText(/Nenhuma categoria ainda/)).toBeInTheDocument()
    const empty = screen.getByText(/Nenhuma categoria ainda/)
    expect(within(empty).getByRole('link', { name: 'Cadastros' })).toHaveAttribute('href', '/admin/registry')
  })

  it('admin vê "Gerenciar"; member não', async () => {
    vi.spyOn(api, 'listCategories').mockResolvedValue([])
    vi.spyOn(api, 'me').mockResolvedValue(admin)
    const { unmount } = renderPage()
    expect(await screen.findByRole('link', { name: /Gerenciar/ })).toHaveAttribute('href', '/admin/registry')
    unmount()

    vi.spyOn(api, 'me').mockResolvedValue(member)
    renderPage()
    await screen.findByText(/Nenhuma categoria ainda/)
    expect(screen.queryByRole('link', { name: /Gerenciar/ })).not.toBeInTheDocument()
    expect(within(screen.getByText(/Nenhuma categoria ainda/)).queryByRole('link')).not.toBeInTheDocument()
  })

  it('erro de carga aparece na página', async () => {
    vi.spyOn(api, 'me').mockResolvedValue(member)
    vi.spyOn(api, 'listCategories').mockRejectedValue(new Error('falhou 500'))
    renderPage()
    expect(await screen.findByText('falhou 500')).toBeInTheDocument()
  })
})
