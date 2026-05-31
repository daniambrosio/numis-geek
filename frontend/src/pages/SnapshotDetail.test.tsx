/* Spec 45 — SnapshotDetail completeness tests.
 *
 * Covers the 2 user-reported gaps:
 *  1. Positions table renders ALL items (not the historical 20-row slice).
 *  2. "Eventos do mês" detail table appears when distributions exist
 *     and is hidden otherwise.
 *
 * We mock every api.* call this page makes so the render is deterministic
 * without backend wiring.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

import SnapshotDetail from './SnapshotDetail'
import {
  api,
  type AssetOut, type DistributionOut, type SnapshotItemOut,
  type SnapshotOut, type UserOut,
} from '../lib/api'

const me: UserOut = {
  id: 'u1', email: 'd@x.com', name: 'Dani', role: 'admin',
  workspace_id: 'ws1', workspace_name: 'Família', is_active: true,
  created_at: '2026-01-01T00:00:00Z',
}

const snap: SnapshotOut = {
  id: 's1', workspace_id: 'ws1',
  period_end_date: '2026-04-30',
  fx_rate_usd_brl: '5.0000',
  total_value_brl: '1000000',
  total_value_usd: '200000',
  total_invested_brl: '800000',
  total_received_brl: '0',
  source: 'AUTOMATED', items_count: 0,
  status: 'CLOSED',
  closed_at: '2026-05-01T10:00:00Z',
  closed_by: 'u1',
  scheduled_at: null, auto_run_at: null,
  pendencies_total: 0, pendencies_open: 0,
}

function asset(id: string, ticker: string): AssetOut {
  return {
    id, workspace_id: 'ws1', workspace_name: 'Família',
    account_id: 'acc1', account_name: 'XP',
    financial_institution_id: 'fi1', financial_institution_name: 'XP',
    asset_class: 'STOCK', country: 'BR',
    name: `${ticker} Long Name`, ticker, cnpj: null,
    currency: 'BRL',
    current_price: 30, price_updated_at: '2026-04-30T00:00:00Z',
    price_source: 'BRAPI', price_tier: 'FRESH',
    notes: null, external_id: null, external_source: null,
    is_active: true, details: null,
    created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
  }
}

function item(asset_id: string, value: number): SnapshotItemOut {
  return {
    asset_id, quantity: '100',
    unit_price: '30.00',
    market_value_native: String(value),
    market_value_brl: String(value),
    market_value_usd: String(value / 5),
    average_cost_brl: String(value * 0.8),
    total_invested_brl: String(value * 0.8),
  }
}

function distribution(over: Partial<DistributionOut> = {}): DistributionOut {
  return {
    id: over.id ?? 'd-' + Math.random().toString(36).slice(2, 8),
    workspace_id: 'ws1',
    financial_institution_id: 'fi1',
    financial_institution_name: 'XP',
    asset_id: 'a1', asset_name: 'PETR4 SA', asset_ticker: 'PETR4',
    type: 'DIVIDEND', type_label: 'Dividendo',
    event_date: '2026-04-15',
    gross_amount: 100, tax: 15, net_amount: 85,
    currency: 'BRL', fx_rate: 1,
    notes: null, external_id: null, external_source: null,
    is_active: true,
    created_at: '2026-04-15T00:00:00Z',
    updated_at: '2026-04-15T00:00:00Z',
    ...over,
  }
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/snapshots/2026-04']}>
      <Routes>
        <Route path="/snapshots/:ym" element={<SnapshotDetail />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('SnapshotDetail (Spec 45)', () => {
  beforeEach(() => { vi.restoreAllMocks() })

  it('shows 20 positions by default with "ver todos" link, expands on click', async () => {
    // 25 items — proto-style: default shows 20 + "ver todos" link.
    const N = 25
    const assets = Array.from({ length: N }, (_, i) =>
      asset(`a${i}`, `TICK${String(i).padStart(2, '0')}`),
    )
    const items = assets.map((a, i) => item(a.id, 100_000 - i * 1000))

    vi.spyOn(api, 'me').mockResolvedValue(me)
    vi.spyOn(api, 'listSnapshots').mockResolvedValue([snap])
    vi.spyOn(api, 'listSnapshotItems').mockResolvedValue(items)
    vi.spyOn(api, 'listSnapshotPendencies').mockResolvedValue([])
    vi.spyOn(api, 'listAssets').mockResolvedValue(assets)
    vi.spyOn(api, 'listDistributions').mockResolvedValue({
      items: [], total: 0, page: 1, page_size: 200,
    })

    renderPage()

    // Default: first ticker visible, late ticker (index 24) still
    // hidden behind the slice.
    expect(await screen.findByText('TICK00')).toBeInTheDocument()
    expect(screen.queryByText('TICK24')).toBeNull()
    expect(screen.getByText(/25 ativos/)).toBeInTheDocument()
    expect(screen.getByText(/\+ 5 ativos/)).toBeInTheDocument()

    // Click "ver todos" → late ticker appears.
    fireEvent.click(screen.getByTestId('show-all-positions'))
    await waitFor(() => {
      expect(screen.getByText('TICK24')).toBeInTheDocument()
    })
    // The "+ N ativos" hint disappears once expanded.
    expect(screen.queryByText(/\+ 5 ativos/)).toBeNull()
  })

  it('renders the "Eventos do mês" table when distributions exist', async () => {
    vi.spyOn(api, 'me').mockResolvedValue(me)
    vi.spyOn(api, 'listSnapshots').mockResolvedValue([snap])
    vi.spyOn(api, 'listSnapshotItems').mockResolvedValue([])
    vi.spyOn(api, 'listSnapshotPendencies').mockResolvedValue([])
    vi.spyOn(api, 'listAssets').mockResolvedValue([asset('a1', 'PETR4')])
    vi.spyOn(api, 'listDistributions').mockResolvedValue({
      items: [
        distribution({ id: 'd1', event_date: '2026-04-10', gross_amount: 50, net_amount: 50, tax: 0 }),
        distribution({ id: 'd2', event_date: '2026-04-20', gross_amount: 100, net_amount: 85, tax: 15 }),
      ],
      total: 2, page: 1, page_size: 200,
    })

    renderPage()

    expect(await screen.findByTestId('distributions-table')).toBeInTheDocument()
    expect(screen.getByText(/2 proventos/)).toBeInTheDocument()
    // First event (10/04) and second (20/04) both visible.
    expect(screen.getByText('10/04')).toBeInTheDocument()
    expect(screen.getByText('20/04')).toBeInTheDocument()
  })

  it('hides the "Eventos do mês" table when there are no distributions', async () => {
    vi.spyOn(api, 'me').mockResolvedValue(me)
    vi.spyOn(api, 'listSnapshots').mockResolvedValue([snap])
    vi.spyOn(api, 'listSnapshotItems').mockResolvedValue([])
    vi.spyOn(api, 'listSnapshotPendencies').mockResolvedValue([])
    vi.spyOn(api, 'listAssets').mockResolvedValue([])
    vi.spyOn(api, 'listDistributions').mockResolvedValue({
      items: [], total: 0, page: 1, page_size: 200,
    })

    renderPage()

    // Wait for the page to settle (positions wrapper renders even when empty).
    await waitFor(() => {
      expect(screen.getByTestId('positions-wrapper')).toBeInTheDocument()
    })
    // The eventos table must NOT exist.
    expect(screen.queryByTestId('distributions-table')).toBeNull()
  })
})
