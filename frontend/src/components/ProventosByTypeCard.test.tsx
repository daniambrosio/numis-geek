import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

import ProventosByTypeCard from './ProventosByTypeCard'
import { api, type ChartDataOut } from '../lib/api'

const FAKE_FULL: ChartDataOut = {
  rows: [
    { ym: '2026-04', total: 1000, segments: [
      { key: 'DIVIDEND',           label: 'Dividendo',        color: '#22c55e', value: 600 },
      { key: 'INTEREST',           label: 'Juros / Cupom',    color: '#3b82f6', value: 100 },
      { key: 'JCP',                label: 'JCP',              color: '#f59e0b', value: 100 },
      { key: 'SECURITIES_LENDING', label: 'Aluguel',          color: '#8b5cf6', value: 50 },
      { key: 'OPTION_PREMIUM',     label: 'Prêmio sintético', color: '#a855f7', value: 150 },
    ]},
  ],
  legend: [],
  totals: { sum: 1000, monthly_avg: 1000, max: 1000 },
  currency: 'BRL',
}

const FAKE_NO_OPTIONS: ChartDataOut = {
  rows: [
    { ym: '2026-04', total: 100, segments: [
      { key: 'DIVIDEND', label: 'Dividendo', color: '#22c55e', value: 100 },
    ]},
  ],
  legend: [],
  totals: { sum: 100, monthly_avg: 100, max: 100 },
  currency: 'BRL',
}

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(api, 'getDistributionsChart').mockResolvedValue(FAKE_FULL)
})

describe('ProventosByTypeCard', () => {
  it('always renders 5 chips in the fixed order, regardless of synthetic toggle', async () => {
    render(<ProventosByTypeCard includeSynthetic={true} />)
    await waitFor(() => {
      expect(screen.getByTestId('type-chip-DIVIDEND')).toBeInTheDocument()
    })
    const order = ['DIVIDEND', 'INTEREST', 'JCP', 'SECURITIES_LENDING', 'OPTION_PREMIUM']
    for (const key of order) {
      expect(screen.getByTestId(`type-chip-${key}`)).toBeInTheDocument()
    }
  })

  it('shows OPÇÕES badge only on the OPTION_PREMIUM chip', async () => {
    render(<ProventosByTypeCard includeSynthetic={true} />)
    await waitFor(() => expect(screen.getByTestId('type-chip-OPTION_PREMIUM')).toBeInTheDocument())
    const optionChip = screen.getByTestId('type-chip-OPTION_PREMIUM')
    expect(optionChip.textContent).toMatch(/OPÇÕES/)
    const divChip = screen.getByTestId('type-chip-DIVIDEND')
    expect(divChip.textContent).not.toMatch(/OPÇÕES/)
  })

  it('dims OPTION_PREMIUM and shows "desligado" when includeSynthetic=false', async () => {
    render(<ProventosByTypeCard includeSynthetic={false} />)
    await waitFor(() => expect(screen.getByTestId('type-chip-OPTION_PREMIUM')).toBeInTheDocument())
    const optionChip = screen.getByTestId('type-chip-OPTION_PREMIUM')
    expect(optionChip.getAttribute('data-off')).toBe('true')
    expect(optionChip.textContent).toMatch(/desligado/)
    // Non-synthetic chips stay enabled.
    expect(screen.getByTestId('type-chip-DIVIDEND').getAttribute('data-off')).toBe('false')
  })

  it('renders chips with zero value when the data has no row for that type', async () => {
    vi.spyOn(api, 'getDistributionsChart').mockResolvedValue(FAKE_NO_OPTIONS)
    render(<ProventosByTypeCard includeSynthetic={true} />)
    await waitFor(() => expect(screen.getByTestId('type-chip-JCP')).toBeInTheDocument())
    // JCP is not in the data → chip exists with R$ 0
    expect(screen.getByTestId('type-chip-JCP').textContent).toMatch(/R\$ 0/)
  })
})
