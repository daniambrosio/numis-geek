import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import ValuationCard from './ValuationCard'
import { api, type ValuationOut } from '../lib/api'

const buyValuation: ValuationOut = {
  asset_id: 'a1',
  asset_class: 'STOCK',
  currency: 'BRL',
  verdict: 'BUY',
  verdict_reason: 'Preço abaixo de Bazin e Graham',
  metrics: [
    { name: 'P/L', value: '12.5', unit: 'ratio', interpretation: 'fair' },
    { name: 'DY 12m', value: '0.085', unit: 'pct', interpretation: 'fair' },
    { name: 'Bazin', value: '125', unit: 'price', interpretation: 'cheap' },
    { name: 'Graham', value: '30', unit: 'price', interpretation: 'cheap' },
  ],
  disqualifying: [],
  fundamentals_as_of: '2026-06-25',
  fundamentals_source: 'BRAPI',
  is_stale: false,
}

const naValuation: ValuationOut = {
  asset_id: 'a2',
  asset_class: 'CRYPTO',
  currency: 'BRL',
  verdict: 'NA',
  verdict_reason: 'Classe fora de escopo',
  metrics: [],
  disqualifying: [],
  fundamentals_as_of: null,
  fundamentals_source: null,
  is_stale: false,
}

const holdWithGates: ValuationOut = {
  ...buyValuation,
  verdict: 'HOLD',
  disqualifying: ['ROE negativo', 'Dívida/EBITDA = 7.5x (limite 5)'],
  verdict_reason: 'Disqualifying gates impedem BUY',
}

beforeEach(() => {
  vi.restoreAllMocks()
})

describe('ValuationCard', () => {
  it('renders verdict + metrics on happy path', async () => {
    vi.spyOn(api, 'getValuation').mockResolvedValue(buyValuation)
    render(<ValuationCard assetId="a1" />)
    await screen.findByText('Comprar')
    expect(screen.getByText('Bazin')).toBeInTheDocument()
    expect(screen.getByText('via BRAPI · 2026-06-25')).toBeInTheDocument()
    // DY 12m formatted as percentage
    expect(screen.getByText('8.50%')).toBeInTheDocument()
  })

  it('shows NA dash for out-of-scope class', async () => {
    vi.spyOn(api, 'getValuation').mockResolvedValue(naValuation)
    render(<ValuationCard assetId="a2" />)
    await screen.findByText('—')
    expect(screen.getByText('Classe fora de escopo')).toBeInTheDocument()
  })

  it('shows disqualifying gates list', async () => {
    vi.spyOn(api, 'getValuation').mockResolvedValue(holdWithGates)
    render(<ValuationCard assetId="a1" />)
    await screen.findByText('Manter')
    expect(screen.getByText('Disqualifying gates ativos')).toBeInTheDocument()
    expect(screen.getByText('ROE negativo')).toBeInTheDocument()
  })

  it('refresh button hidden when canRefresh=false', async () => {
    vi.spyOn(api, 'getValuation').mockResolvedValue(buyValuation)
    render(<ValuationCard assetId="a1" canRefresh={false} />)
    await screen.findByText('Comprar')
    expect(screen.queryByTestId('valuation-refresh')).toBeNull()
  })

  it('refresh button triggers refreshFundamentals + reload', async () => {
    vi.spyOn(api, 'getValuation').mockResolvedValue(buyValuation)
    const refreshSpy = vi.spyOn(api, 'refreshFundamentals').mockResolvedValue(null)
    render(<ValuationCard assetId="a1" canRefresh={true} />)
    const btn = await screen.findByTestId('valuation-refresh')
    fireEvent.click(btn)
    await waitFor(() => expect(refreshSpy).toHaveBeenCalledWith('a1'))
  })

  it('displays error if refresh fails', async () => {
    vi.spyOn(api, 'getValuation').mockResolvedValue(buyValuation)
    vi.spyOn(api, 'refreshFundamentals').mockRejectedValue(new Error('Provider down'))
    render(<ValuationCard assetId="a1" canRefresh={true} />)
    const btn = await screen.findByTestId('valuation-refresh')
    fireEvent.click(btn)
    await waitFor(() => {
      expect(screen.getByTestId('valuation-error').textContent).toMatch(/Provider down/)
    })
  })

  it('shows stale badge when is_stale=true', async () => {
    vi.spyOn(api, 'getValuation').mockResolvedValue({
      ...buyValuation, is_stale: true, fundamentals_as_of: '2026-01-01',
    })
    render(<ValuationCard assetId="a1" />)
    expect(await screen.findByText('Fundamentos antigos')).toBeInTheDocument()
  })
})
