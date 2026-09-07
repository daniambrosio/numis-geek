import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

import SysAdminAssets from './Assets'
import { api, type AssetOut, type FinancialInstitutionOut, type UserOut } from '../../lib/api'

// Spec 81 — regressão: o sysadmin via o drawer AssetDetailPanel em vez da
// página do ativo ("aquele modalzinho"). Agora a linha navega pra /assets/:id.

const me: UserOut = {
  id: 'u1', email: 'd@x.com', name: 'Dani', role: 'sysadmin',
  workspace_id: 'ws1', workspace_name: 'Família', is_active: true,
  created_at: '2026-01-01T00:00:00Z',
}
const fi: FinancialInstitutionOut = {
  id: 'fi1', short_name: 'XP', long_name: 'XP', country: 'BR', logo_slug: 'xp',
  brand_color: null, has_logo: false, is_active: true, created_at: '', updated_at: '',
}
const asset: AssetOut = {
  id: 'a1', workspace_id: 'ws1', workspace_name: 'Família',
  account_id: 'acc1', account_name: 'XP Inv', financial_institution_id: 'fi1', financial_institution_name: 'XP',
  asset_class: 'STOCK', country: 'BR', name: 'Itaú PN', ticker: 'ITUB4', cnpj: null, currency: 'BRL',
  current_price: 32, price_updated_at: null, price_source: null, price_tier: 'UNKNOWN',
  notes: null, external_id: null, external_source: null, is_active: true, details: null,
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
}

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(api, 'me').mockResolvedValue(me)
  vi.spyOn(api, 'listAssets').mockResolvedValue([asset])
  vi.spyOn(api, 'listFinancialInstitutions').mockResolvedValue([fi])
  vi.spyOn(api, 'listWorkspaces').mockResolvedValue([{ id: 'ws1', name: 'Família' } as never])
  vi.spyOn(api, 'getAssetPosition').mockRejectedValue(new Error('skip'))
})

describe('sysadmin Assets (spec 81)', () => {
  it('clicar na linha navega pra página do ativo com estado de retorno', async () => {
    render(
      <MemoryRouter initialEntries={['/sysadmin/assets']}>
        <Routes>
          <Route path="/sysadmin/assets" element={<SysAdminAssets />} />
          <Route path="/assets/:id" element={<div data-testid="asset-page">página do ativo</div>} />
        </Routes>
      </MemoryRouter>,
    )
    // A lista dispara N getAssetPosition em paralelo; sob a suíte inteira o
    // jsdom fica lento — timeout folgado evita flake.
    await waitFor(() => expect(screen.getByText('ITUB4')).toBeInTheDocument(), { timeout: 5000 })
    fireEvent.click(screen.getByText('ITUB4'))
    await waitFor(() => expect(screen.getByTestId('asset-page')).toBeInTheDocument(), { timeout: 5000 })
  })
})
