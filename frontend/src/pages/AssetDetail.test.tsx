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
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from 'react-router-dom'

import AssetDetail from './AssetDetail'
import {
  api,
  type AccountOut, type AssetOut, type AssetPriceHistoryOut, type AssetPriceHistoryPoint,
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
  country: 'US', logo_slug: 'avenue', brand_color: null, has_logo: false, is_active: true,
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
}

const account: AccountOut = {
  id: 'acc1', workspace_id: 'ws1',
  financial_institution_id: 'fi1', financial_institution_name: 'Avenue',
  name: 'Conta Investimento Avenue', account_type: 'investment',
  currency: 'USD', opening_balance: 0, account_info: null,
  is_active: true, created_at: '2026-01-01T00:00:00Z',
}

function priceHistory(points: AssetPriceHistoryPoint[]): AssetPriceHistoryOut {
  return { asset_id: 'a1', currency: 'USD', period: '24m', points }
}

function LocationProbe() {
  const loc = useLocation()
  const navigate = useNavigate()
  return (
    <div>
      <span data-testid="probe-search">{loc.search}</span>
      <button data-testid="probe-back" onClick={() => navigate(-1)}>back</button>
    </div>
  )
}

function renderPage(entry = '/assets/a1') {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <LocationProbe />
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
    asset_id: 'a1', is_value_mode: false, quantity_held: 30, average_cost: 108.20,
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

    // Spec 81 — a tabela vive na aba Lançamentos
    await waitFor(() => expect(screen.getByTestId('asset-tab-movements')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('asset-tab-movements'))
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

describe('AssetDetail KPIs (spec 81 — sem PTAX hardcoded)', () => {
  beforeEach(() => { vi.restoreAllMocks() })

  it('Preço atual USD mostra BRL pelo câmbio implícito da posição', async () => {
    mockBoringDeps()
    vi.spyOn(api, 'getAssetPriceHistory').mockResolvedValue(priceHistory([]))
    renderPage()
    // position: current_value = 30×85, current_value_brl = 30×85×5.5 → fx 5,5
    await waitFor(() => expect(screen.getByTestId('price-brl')).toBeInTheDocument())
    expect(screen.getByTestId('price-brl')).toHaveTextContent('467,50')
  })
})


describe('AssetDetail abas (spec 81)', () => {
  beforeEach(() => { vi.restoreAllMocks() })

  it('abre em Visão geral por padrão e sem ?tab na URL', async () => {
    mockBoringDeps()
    vi.spyOn(api, 'getAssetPriceHistory').mockResolvedValue(priceHistory([]))
    renderPage()
    await waitFor(() => expect(screen.getByTestId('asset-tab-panel-overview')).toBeInTheDocument())
    expect(screen.getByTestId('asset-tab-overview')).toHaveAttribute('aria-selected', 'true')
    expect(screen.queryByTestId('asset-tab-panel-movements')).toBeNull()
    expect(screen.getByTestId('probe-search')).toHaveTextContent('')
  })

  it('?tab=movements abre a aba Lançamentos com a contagem', async () => {
    mockBoringDeps()
    vi.spyOn(api, 'listAssetMovementsForAsset').mockResolvedValue({
      items: [movement], total: 1, page: 1, page_size: 200,
    })
    const ph = vi.spyOn(api, 'getAssetPriceHistory').mockResolvedValue(priceHistory([]))
    renderPage('/assets/a1?tab=movements')
    await waitFor(() => expect(screen.getByTestId('asset-tab-panel-movements')).toBeInTheDocument())
    expect(screen.getByTestId('asset-tab-movements')).toHaveTextContent('1')
    expect(screen.queryByTestId('asset-tab-panel-overview')).toBeNull()
    // price history não é buscado fora da Visão geral (fetch preguiçoso)
    expect(ph).not.toHaveBeenCalled()
  })

  it('clicar numa aba muda a URL e voltar restaura a aba anterior', async () => {
    mockBoringDeps()
    vi.spyOn(api, 'getAssetPriceHistory').mockResolvedValue(priceHistory([]))
    vi.spyOn(api, 'getAssetSnapshotHistory').mockResolvedValue({ asset_id: 'a1', currency: 'USD', items: [] })
    renderPage()
    await waitFor(() => expect(screen.getByTestId('asset-tab-performance')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('asset-tab-performance'))
    await waitFor(() => expect(screen.getByTestId('probe-search')).toHaveTextContent('?tab=performance'))
    expect(screen.getByTestId('asset-tab-panel-performance')).toBeInTheDocument()
    expect(api.getAssetSnapshotHistory).toHaveBeenCalledWith('a1')
    fireEvent.click(screen.getByTestId('probe-back'))
    await waitFor(() => expect(screen.getByTestId('asset-tab-panel-overview')).toBeInTheDocument())
  })

  it('tab desconhecida cai em Visão geral', async () => {
    mockBoringDeps()
    vi.spyOn(api, 'getAssetPriceHistory').mockResolvedValue(priceHistory([]))
    renderPage('/assets/a1?tab=whatever')
    await waitFor(() => expect(screen.getByTestId('asset-tab-panel-overview')).toBeInTheDocument())
  })

  it('botão Lançamento do header abre o composer', async () => {
    mockBoringDeps()
    vi.spyOn(api, 'getAssetPriceHistory').mockResolvedValue(priceHistory([]))
    vi.spyOn(api, 'listAssets').mockResolvedValue([])
    renderPage()
    await waitFor(() => expect(screen.getByTestId('header-new-movement')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('header-new-movement'))
    await waitFor(() => expect(screen.getByText(/Novo lançamento/i)).toBeInTheDocument())
  })
})

describe('AssetDetail proventos (spec 81 fase 4)', () => {
  beforeEach(() => { vi.restoreAllMocks() })

  const distribution = {
    id: 'd1', workspace_id: 'ws1', financial_institution_id: 'fi1', financial_institution_name: 'Avenue',
    asset_id: 'a1', asset_name: 'Abbott Laboratories', asset_ticker: 'ABT',
    type: 'DIVIDEND' as const, type_label: 'Dividendo', event_date: '2026-08-10',
    gross_amount: 12.32, tax: 3.7, net_amount: 8.62, currency: 'USD' as const, fx_rate: 5.5,
    notes: null, external_id: null, external_source: null, is_active: true,
    created_at: '2026-08-10T00:00:00Z', updated_at: '2026-08-10T00:00:00Z',
  }

  it('row de provento abre o DistributionDetailPanel', async () => {
    mockBoringDeps()
    vi.spyOn(api, 'listDistributionsForAsset').mockResolvedValue({
      items: [distribution], synthetic_premiums: [], total: 1, page: 1, page_size: 200,
    })
    vi.spyOn(api, 'listAttachments').mockResolvedValue([])
    renderPage('/assets/a1?tab=distributions')
    await waitFor(() => expect(screen.getByTestId('distribution-row-d1')).toBeInTheDocument())
    expect(api.listDistributionsForAsset).toHaveBeenCalledWith('a1', expect.objectContaining({ include_synthetic: true }))
    fireEvent.click(screen.getByTestId('distribution-row-d1'))
    await waitFor(() => expect(screen.getByText('Editar')).toBeInTheDocument())
  })

  it('"+ Provento" abre o composer com o ativo pré-selecionado', async () => {
    mockBoringDeps()
    vi.spyOn(api, 'getAssetPriceHistory').mockResolvedValue(priceHistory([]))
    renderPage()
    await waitFor(() => expect(screen.getByTestId('header-new-distribution')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('header-new-distribution'))
    await waitFor(() => expect(screen.getByText('Novo Provento')).toBeInTheDocument())
    const assetSelect = screen.getAllByRole('combobox').find(el => (el as HTMLSelectElement).value === 'a1')
    expect(assetSelect).toBeTruthy()
  })
})

describe('AssetDetail rentabilidade (spec 81 fase 5)', () => {
  beforeEach(() => { vi.restoreAllMocks() })

  it('aba Fechamentos carrega /performance e mostra tiles + tabela', async () => {
    mockBoringDeps()
    vi.spyOn(api, 'getAssetSnapshotHistory').mockResolvedValue({ asset_id: 'a1', currency: 'USD', items: [] })
    vi.spyOn(api, 'getAssetPerformance').mockResolvedValue({
      asset_id: 'a1', currency: 'USD', is_value_mode: false,
      items: [{
        period_end_date: '2026-08-31', quantity: '30', unit_price: '85',
        market_value_native: '2550', market_value_brl: '14025', market_value_usd: '2550',
        total_invested_brl: '17000', fx_rate_usd_brl: '5.5', pnl_brl: '-2975', pnl_pct: -0.175,
        contributions_native: '0', withdrawals_native: '0', contributions_brl: '0', withdrawals_brl: '0',
        income_native: '12.49', income_brl: '68.7',
        return_pct: 0.0483, return_brl_pct: 0.061, return_null_reason: null,
      }],
      summary: {
        as_of: '2026-08-31', return_12m_pct: -0.167, return_12m_brl_pct: -0.12,
        return_ytd_pct: -0.1243, return_ytd_brl_pct: -0.09,
        since_inception_pct: -0.0113, since_inception_brl_pct: 0.02,
        months_in_12m: 12, months_in_ytd: 8, income_12m_native: '41.7', income_12m_brl: '229',
      },
    })
    renderPage('/assets/a1?tab=performance')
    await waitFor(() => expect(screen.getByTestId('asset-performance-tiles')).toBeInTheDocument())
    expect(api.getAssetPerformance).toHaveBeenCalledWith('a1')
    expect(screen.getByTestId('asset-performance-tiles')).toHaveTextContent('-16,7%')
    expect(screen.getByTestId('asset-performance-table')).toBeInTheDocument()
    expect(screen.getByTestId('asset-performance-return')).toHaveTextContent('+4,83%')
  })

  it('falha em /performance não quebra a aba', async () => {
    mockBoringDeps()
    vi.spyOn(api, 'getAssetSnapshotHistory').mockResolvedValue({ asset_id: 'a1', currency: 'USD', items: [] })
    vi.spyOn(api, 'getAssetPerformance').mockRejectedValue(new Error('boom'))
    renderPage('/assets/a1?tab=performance')
    await waitFor(() => expect(screen.getByTestId('asset-performance-error')).toBeInTheDocument())
    expect(screen.getByTestId('asset-tab-panel-performance')).toBeInTheDocument()
  })
})

describe('AssetDetail documentos & dados (spec 81 fase 6)', () => {
  beforeEach(() => { vi.restoreAllMocks() })

  it('aba Documentos monta notas/anexos do ativo e busca os anexos com sourceType asset', async () => {
    mockBoringDeps()
    const la = vi.spyOn(api, 'listAttachments').mockResolvedValue([])
    renderPage('/assets/a1?tab=docs')
    await waitFor(() => expect(screen.getByTestId('notes-attachments-card')).toBeInTheDocument())
    expect(la).toHaveBeenCalledWith('asset', 'a1')
    expect(screen.getByText('Notas & documentos do ativo')).toBeInTheDocument()
    expect(screen.getByText('Dados do ativo')).toBeInTheDocument()
  })

  it('"Editar ativo" no header abre a aba Documentos já em edição', async () => {
    mockBoringDeps()
    vi.spyOn(api, 'getAssetPriceHistory').mockResolvedValue(priceHistory([]))
    vi.spyOn(api, 'listAttachments').mockResolvedValue([])
    vi.spyOn(api, 'listAccounts').mockResolvedValue([account])
    renderPage()
    await waitFor(() => expect(screen.getByTestId('header-edit-asset')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('header-edit-asset'))
    await waitFor(() => expect(screen.getByTestId('asset-data-form')).toBeInTheDocument())
    expect(screen.getByTestId('probe-search')).toHaveTextContent('?tab=docs')
  })

  it('salvar nota usa PATCH com notes', async () => {
    mockBoringDeps()
    vi.spyOn(api, 'listAttachments').mockResolvedValue([])
    const patch = vi.spyOn(api, 'patchAsset').mockResolvedValue({ ...asset(), notes: 'tese' })
    vi.useFakeTimers()
    try {
      renderPage('/assets/a1?tab=docs')
      await vi.waitFor(() => expect(screen.getByPlaceholderText(/Adicionar nota/)).toBeInTheDocument())
      fireEvent.change(screen.getByPlaceholderText(/Adicionar nota/), { target: { value: 'tese' } })
      await vi.advanceTimersByTimeAsync(900)
      expect(patch).toHaveBeenCalledWith('a1', { notes: 'tese' })
    } finally {
      vi.useRealTimers()
    }
  })
})

describe('AssetDetail gráfico de preço ajustado por eventos (2026-09-06)', () => {
  beforeEach(() => { vi.restoreAllMocks() })

  it('mostra a nota de ajuste quando há desdobramento na série', async () => {
    mockBoringDeps()
    vi.spyOn(api, 'getAssetPriceHistory').mockResolvedValue({
      ...priceHistory([
        { date: '2025-04-30', unit_price: '9.80', unit_price_raw: '98.00' },
        { date: '2025-05-31', unit_price: '10.04', unit_price_raw: '10.04' },
      ]),
      adjustments: [{ event_date: '2025-05-06', event_type: 'SPLIT', ratio: '10' }],
    })
    renderPage()
    expect(await screen.findByTestId('price-chart-adjustments')).toHaveTextContent('desdobramento 1:10 em 06/05/2025')
  })

  it('sem eventos não mostra nota', async () => {
    mockBoringDeps()
    vi.spyOn(api, 'getAssetPriceHistory').mockResolvedValue(priceHistory([
      { date: '2025-04-30', unit_price: '98.00' }, { date: '2025-05-31', unit_price: '99.00' },
    ]))
    renderPage()
    await waitFor(() => expect(screen.getByText(/Preço · 24 meses/)).toBeInTheDocument())
    expect(screen.queryByTestId('price-chart-adjustments')).toBeNull()
  })
})
