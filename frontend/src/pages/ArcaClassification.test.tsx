/* Spec 85 — página de classificação ARCA. */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

import ArcaClassification from './ArcaClassification'
import { api, type ArcaAssetOut, type ArcaSummaryOut, type UserOut } from '../lib/api'

const me = {
  id: 'u1', email: 'd@x.com', name: 'Dani', role: 'admin',
  workspace_id: 'ws1', workspace_name: 'F', is_active: true, created_at: '2026-01-01T00:00:00Z',
} as UserOut

function asset(id: string, extra: Partial<ArcaAssetOut>): ArcaAssetOut {
  return {
    asset_id: id, ticker: id, name: id, asset_class: 'STOCK', country: 'BR',
    category: 'EQUITY_BR', subcategory: null, derived_category: 'EQUITY_BR',
    derived_subcategory: null, source: 'derived', value_brl: '100', income_12m_brl: '0',
    ...extra,
  }
}

const summary = {
  as_of: null, total_brl: '0', out_of_scope_brl: '0', unmapped_brl: '0', unmapped_count: 1,
  income_12m_total_brl: '0', attack_pct: 0, defense_pct: 0, unknown_role_pct: 0,
  targets_configured: false, letters: [],
  assets: [
    asset('ITUB4', {}),
    asset('BOVA11', { asset_class: 'ETF', category: null, derived_category: null, source: 'unmapped' }),
    asset('SELIC', {
      asset_class: 'FIXED_INCOME', category: 'CASH', subcategory: 'CASH_POST_FIXED',
      derived_category: 'CASH', derived_subcategory: 'CASH_POST_FIXED',
    }),
  ],
} as ArcaSummaryOut

beforeEach(() => vi.restoreAllMocks())

function renderPage() {
  return render(<MemoryRouter><ArcaClassification /></MemoryRouter>)
}

describe('ArcaClassification', () => {
  it('lists assets and filters pending', async () => {
    vi.spyOn(api, 'me').mockResolvedValue(me)
    vi.spyOn(api, 'getArcaSummary').mockResolvedValue(summary)
    renderPage()
    expect(await screen.findByTestId('arca-row-SELIC')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('arca-only-pending'))
    expect(screen.queryByTestId('arca-row-SELIC')).toBeNull()
    expect(screen.getByTestId('arca-row-BOVA11')).toBeInTheDocument()
    expect(screen.getByTestId('arca-row-ITUB4')).toBeInTheDocument() // sem subcategoria
  })

  it('inline edit sends the override', async () => {
    vi.spyOn(api, 'me').mockResolvedValue(me)
    vi.spyOn(api, 'getArcaSummary').mockResolvedValue(summary)
    const put = vi.spyOn(api, 'putArcaClassification').mockResolvedValue(summary)
    renderPage()
    fireEvent.change(await screen.findByLabelText('letra BOVA11'), { target: { value: 'EQUITY_BR' } })
    await waitFor(() => expect(put).toHaveBeenCalledWith('ws1', [
      { asset_id: 'BOVA11', category: 'EQUITY_BR', subcategory: null },
    ]))
    fireEvent.change(screen.getByLabelText('sub ITUB4'), { target: { value: 'EQ_DEFENSIVE' } })
    await waitFor(() => expect(put).toHaveBeenLastCalledWith('ws1', [
      { asset_id: 'ITUB4', category: 'EQUITY_BR', subcategory: 'EQ_DEFENSIVE' },
    ]))
  })

  it('bulk apply', async () => {
    vi.spyOn(api, 'me').mockResolvedValue(me)
    vi.spyOn(api, 'getArcaSummary').mockResolvedValue(summary)
    const put = vi.spyOn(api, 'putArcaClassification').mockResolvedValue(summary)
    renderPage()
    fireEvent.click(await screen.findByLabelText('selecionar ITUB4'))
    fireEvent.click(screen.getByLabelText('selecionar BOVA11'))
    fireEvent.click(screen.getByTestId('arca-bulk-apply'))
    await waitFor(() => expect(put).toHaveBeenCalledWith('ws1', [
      { asset_id: 'ITUB4', category: null, subcategory: null },
      { asset_id: 'BOVA11', category: null, subcategory: null },
    ]))
  })
})
