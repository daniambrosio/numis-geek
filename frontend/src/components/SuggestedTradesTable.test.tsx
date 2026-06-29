import { describe, expect, it } from 'vitest'
import { render, screen, within } from '@testing-library/react'

import SuggestedTradesTable from './SuggestedTradesTable'
import type { OptimalAllocationOut } from '../lib/api'

const allocations: OptimalAllocationOut[] = [
  {
    asset_id: 'a1', ticker: 'ITUB4', name: 'Itau',
    asset_class: 'STOCK', country: 'BR',
    weight: 0.4, current_weight: 0.36, delta: 0.04,
    target_value_brl: 40000, current_value_brl: 36000,
    trade_action: 'BUY', trade_value_brl: 4000,
  },
  {
    asset_id: 'a2', ticker: 'XPLG11', name: 'XP Log',
    asset_class: 'REIT', country: 'BR',
    weight: 0.30, current_weight: 0.50, delta: -0.20,
    target_value_brl: 30000, current_value_brl: 50000,
    trade_action: 'SELL', trade_value_brl: -20000,
  },
  {
    asset_id: 'a3', ticker: 'AAPL', name: 'Apple',
    asset_class: 'STOCK', country: 'US',
    weight: 0.30, current_weight: 0.30, delta: 0.0,
    target_value_brl: 30000, current_value_brl: 30000,
    trade_action: 'HOLD', trade_value_brl: 0,
  },
]

describe('SuggestedTradesTable', () => {
  it('renders empty state', () => {
    render(<SuggestedTradesTable allocations={[]} />)
    expect(screen.getByText(/Nenhum ativo elegível/)).toBeInTheDocument()
  })

  it('sorts rows by absolute delta descending', () => {
    render(<SuggestedTradesTable allocations={allocations} />)
    const tbody = screen.getByTestId('trades-table').querySelector('tbody')!
    const rows = within(tbody as HTMLElement).getAllByRole('row')
    // First row should be XPLG11 (|delta|=0.20)
    expect(within(rows[0]).getByText('XPLG11')).toBeInTheDocument()
    // Second ITUB4 (|delta|=0.04)
    expect(within(rows[1]).getByText('ITUB4')).toBeInTheDocument()
    // Third AAPL (|delta|=0.0)
    expect(within(rows[2]).getByText('AAPL')).toBeInTheDocument()
  })

  it('renders action badges with correct labels', () => {
    render(<SuggestedTradesTable allocations={allocations} />)
    expect(screen.getByText('Comprar')).toBeInTheDocument()
    expect(screen.getByText('Vender')).toBeInTheDocument()
    expect(screen.getByText('Manter')).toBeInTheDocument()
  })
})
