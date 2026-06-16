/* Spec 46 — Asset price history chart tests.
 *
 * Covers the 2 invariants that distinguish the new real-data chart
 * from the prior simulated `priceSeries`:
 *  1. Card renders only when the price-history endpoint returns ≥ 2 points.
 *  2. Card is hidden when fewer than 2 points (the prior version would
 *     show a fake interpolation; the new one shows nothing).
 *
 * We do NOT exercise the GroupingToggle interaction here — it's a small
 * UI element and the period switch just re-fetches the same endpoint.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

import AssetDetail from './AssetDetail'
import {
  api,
  type AccountOut, type AssetOut, type AssetPriceHistoryOut,
  type FinancialInstitutionOut, type UserOut,
} from '../lib/api'

const me: UserOut = {
  id: 'u1', email: 'd@x.com', name: 'Dani', role: 'admin',
  workspace_id: 'ws1', workspace_name: 'Família', is_active: true,
  created_at: '2026-01-01T00:00:00Z',
}

function asset(currency: 'BRL' | 'USD' = 'USD'): AssetOut {
  return {
    id: 'a1', workspace_id: 'ws1', workspace_name: 'Família',
    account_id: 'acc1', account_name: 'Avenue Inv',
    financial_institution_id: 'fi1', financial_institution_name: 'Avenue',
    asset_class: 'STOCK', country: 'US',
    name: 'Abbott Laboratories', ticker: 'ABT', cnpj: null,
    currency,
    current_price: 85, price_updated_at: '2026-05-29T00:00:00Z',
    price_source: 'FINNHUB', price_tier: 'STALE',
    notes: null, external_id: null, external_source: null,
    is_active: true, details: null,
    created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
  }
}

const fi: FinancialInstitutionOut = {
  id: 'fi1', short_name: 'Avenue', long_name: 'Avenue Securities LLC',
  country: 'US', logo_slug: 'avenue', is_active: true,
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
}

const account: AccountOut = {
  id: 'acc1', workspace_id: 'ws1',
  financial_institution_id: 'fi1', financial_institution_name: 'Avenue',
  name: 'Conta Investimento Avenue', account_type: 'investment',
  currency: 'USD', opening_balance: 0, account_info: null,
  is_active: true, created_at: '2026-01-01T00:00:00Z',
}

function priceHistory(points: { date: string; unit_price: string }[]): AssetPriceHistoryOut {
  return { asset_id: 'a1', currency: 'USD', period: '24m', points }
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/assets/a1']}>
      <Routes>
        <Route path="/assets/:id" element={<AssetDetail />} />
      </Routes>
    </MemoryRouter>,
  )
}

function mockBoringDeps() {
  vi.spyOn(api, 'me').mockResolvedValue(me)
  vi.spyOn(api, 'getAsset').mockResolvedValue(asset())
  vi.spyOn(api, 'listFinancialInstitutions').mockResolvedValue([fi])
  vi.spyOn(api, 'getAccount').mockResolvedValue(account)
  vi.spyOn(api, 'getAssetPosition').mockResolvedValue({
    asset_id: 'a1', quantity_held: 30, average_cost: 108.20,
    average_cost_brl: 108.20 * 5.5, total_invested_brl: 17000,
    total_received_brl: 97, ttm_dividends_native: 0, currency: 'USD',
    current_price: 85, current_value: 30 * 85,
    current_value_brl: 30 * 85 * 5.5, variation: -0.21,
    rentabilidade: -0.19,
    dividend_yield: null, yield_on_cost: null,
  })
  vi.spyOn(api, 'listAssetMovementsForAsset').mockResolvedValue({
    items: [], total: 0, page: 1, page_size: 200,
  })
  vi.spyOn(api, 'listDistributionsForAsset').mockResolvedValue({
    items: [], total: 0, page: 1, page_size: 200,
  })
}

import { fireEvent } from '@testing-library/react'
import type { AssetMovementOut } from '../lib/api'

const movement: AssetMovementOut = {
  id: 'm1', workspace_id: 'ws1', asset_id: 'a1',
  asset_name: 'Abbott Laboratories', asset_ticker: 'ABT',
  type: 'BUY', type_label: 'Compra',
  event_date: '2026-01-10', settlement_date: null,
  quantity: 10, unit_price: 100,
  gross_amount: 1000, fee: 0, tax: 0, net_amount: 1000,
  currency: 'USD', fx_rate: 5.0,
  notes: null, external_id: null, external_source: null,
  nota_negociacao_number: null,
  is_active: true,
  created_at: '2026-01-10T00:00:00Z', updated_at: '2026-01-10T00:00:00Z',
}

describe('AssetDetail click no lançamento — Spec sessão 2026-06-06', () => {
  beforeEach(() => { vi.restoreAllMocks() })

  it('click numa row de lançamento abre o LancamentoDetailPanel', async () => {
    mockBoringDeps()
    vi.spyOn(api, 'listAssetMovementsForAsset').mockResolvedValue({
      items: [movement], total: 1, page: 1, page_size: 200,
    })
    vi.spyOn(api, 'getAssetPriceHistory').mockRejectedValue(new Error('skip chart'))
    vi.spyOn(api, 'listAttachments').mockResolvedValue([])

    renderPage()

    // Aguarda a tabela aparecer
    await waitFor(() => expect(screen.getByText('Compra')).toBeInTheDocument())

    // Clica no row da tabela (o td "Compra" está dentro do tr)
    fireEvent.click(screen.getByText('Compra'))

    // Panel deve estar visível — usa o botão "Editar" como sinal
    await waitFor(() => expect(screen.getByText('Editar')).toBeInTheDocument())
  })
})

describe('AssetDetail price chart (Spec 46)', () => {
  beforeEach(() => { vi.restoreAllMocks() })

  it('renders the chart card when the endpoint returns ≥ 2 points', async () => {
    mockBoringDeps()
    vi.spyOn(api, 'getAssetPriceHistory').mockResolvedValue(priceHistory([
      { date: '2024-05-31', unit_price: '110.00' },
      { date: '2024-11-29', unit_price: '105.00' },
      { date: '2025-05-30', unit_price: '95.00' },
      { date: '2025-11-28', unit_price: '88.00' },
      { date: '2026-04-30', unit_price: '85.60' },
    ]))

    renderPage()

    expect(await screen.findByText(/Preço · 24 meses/)).toBeInTheDocument()
    expect(screen.getByText(/5 fechamentos · USD/)).toBeInTheDocument()
    // Period selector renders 4 options.
    expect(screen.getByText('6M')).toBeInTheDocument()
    expect(screen.getByText('12M')).toBeInTheDocument()
    expect(screen.getByText('24M')).toBeInTheDocument()
    expect(screen.getByText('Tudo')).toBeInTheDocument()
  })

  it('hides the chart card when the endpoint returns < 2 points', async () => {
    mockBoringDeps()
    vi.spyOn(api, 'getAssetPriceHistory').mockResolvedValue(priceHistory([
      { date: '2026-04-30', unit_price: '85.60' },
    ]))

    renderPage()

    // Wait for the page to settle (any page-level text shows up).
    await waitFor(() => {
      expect(screen.getByText('Abbott Laboratories')).toBeInTheDocument()
    })
    // Critical: the chart title must NOT appear.
    expect(screen.queryByText(/Preço · 24 meses/)).toBeNull()
    expect(screen.queryByText(/fechamentos · USD/)).toBeNull()
  })

  it('hides the chart card when the endpoint fails', async () => {
    mockBoringDeps()
    vi.spyOn(api, 'getAssetPriceHistory').mockRejectedValue(new Error('boom'))

    renderPage()

    await waitFor(() => {
      expect(screen.getByText('Abbott Laboratories')).toBeInTheDocument()
    })
    expect(screen.queryByText(/Preço · 24 meses/)).toBeNull()
  })
})
