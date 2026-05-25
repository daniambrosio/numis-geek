import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import ProventosChart from './ProventosChart'
import { api, type ChartDataOut } from '../lib/api'

const FAKE: ChartDataOut = {
  rows: [
    { ym: '2025-06', total: 100, segments: [
      { key: 'STOCK', label: 'Ação', color: '#3b82f6', value: 60 },
      { key: 'REIT', label: 'FII / REIT', color: '#22c55e', value: 40 },
    ]},
    { ym: '2025-07', total: 200, segments: [
      { key: 'STOCK', label: 'Ação', color: '#3b82f6', value: 200 },
    ]},
  ],
  legend: [
    { key: 'STOCK', label: 'Ação', color: '#3b82f6', value: null },
    { key: 'REIT', label: 'FII / REIT', color: '#22c55e', value: null },
  ],
  totals: { sum: 300, monthly_avg: 150, max: 200 },
  currency: 'BRL',
}

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(api, 'getDistributionsChart').mockResolvedValue(FAKE)
})

describe('ProventosChart', () => {
  it('renders KPIs from response', async () => {
    render(<ProventosChart />)
    await waitFor(() => expect(screen.getByText(/Último mês/)).toBeInTheDocument())
    // 200 = lastMonthTotal
    expect(screen.getAllByText(/R\$ 200/).length).toBeGreaterThan(0)
  })

  it('renders all 3 toggles by default', async () => {
    render(<ProventosChart />)
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Classe' })).toBeInTheDocument(),
    )
    expect(screen.getByRole('button', { name: 'R$' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '12M' })).toBeInTheDocument()
  })

  it('hideToggles hides all segmented controls', async () => {
    render(<ProventosChart hideToggles />)
    await waitFor(() => expect(api.getDistributionsChart).toHaveBeenCalled())
    expect(screen.queryByText('Classe')).toBeNull()
  })

  it('compact hides the footer legend + synthetic toggle', async () => {
    render(<ProventosChart compact />)
    await waitFor(() => expect(api.getDistributionsChart).toHaveBeenCalled())
    expect(screen.queryByText(/Incluir dividendos/)).toBeNull()
  })

  it('clicking a toggle refetches with the new value', async () => {
    const user = userEvent.setup()
    render(<ProventosChart />)
    await waitFor(() => expect(api.getDistributionsChart).toHaveBeenCalledWith(
      expect.objectContaining({ period: '12m' }),
    ))
    await user.click(screen.getByText('24M'))
    await waitFor(() => expect(api.getDistributionsChart).toHaveBeenLastCalledWith(
      expect.objectContaining({ period: '24m' }),
    ))
  })

  it('controlled includeSynthetic prop wins over local state', async () => {
    render(
      <ProventosChart
        includeSynthetic={false}
        onIncludeSyntheticChange={() => {}}
      />,
    )
    await waitFor(() => expect(api.getDistributionsChart).toHaveBeenCalledWith(
      expect.objectContaining({ include_synthetic: false }),
    ))
  })

  it('toggling the synthetic checkbox calls onIncludeSyntheticChange', async () => {
    const onChange = vi.fn()
    const user = userEvent.setup()
    render(<ProventosChart includeSynthetic={true} onIncludeSyntheticChange={onChange} />)
    await waitFor(() => expect(api.getDistributionsChart).toHaveBeenCalled())
    await user.click(screen.getByRole('checkbox'))
    expect(onChange).toHaveBeenCalledWith(false)
  })
})
