import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'

import AssetDistributionsTab, { sumDistributions } from './AssetDistributionsTab'
import type { DistributionOut, SyntheticPremiumOut } from '../../lib/api'

const dist = (over: Partial<DistributionOut> = {}): DistributionOut => ({
  id: 'd1', workspace_id: 'ws1', financial_institution_id: 'fi1', financial_institution_name: 'XP',
  asset_id: 'a1', asset_name: 'Itaú', asset_ticker: 'ITUB4',
  type: 'DIVIDEND', type_label: 'Dividendo', event_date: '2026-08-10',
  gross_amount: 100, tax: 0, net_amount: 100, currency: 'BRL', fx_rate: 1,
  notes: null, external_id: null, external_source: null, is_active: true,
  created_at: '2026-08-10T00:00:00Z', updated_at: '2026-08-10T00:00:00Z',
  ...over,
})

const premium: SyntheticPremiumOut = {
  id: 'synthetic:m9', movement_id: 'm9', workspace_id: 'ws1',
  financial_institution_id: 'fi1', financial_institution_name: 'XP',
  asset_id: 'a1', underlying_ticker: 'ITUB4', option_asset_id: 'o1', option_ticker: 'ITUBI350',
  type: 'OPTION_PREMIUM', type_label: 'Prêmio sintético', side: 'SELL_OPEN',
  event_date: '2026-08-20', gross_amount: 50, net_amount: 50, currency: 'BRL', fx_rate: 1,
}

describe('AssetDistributionsTab (spec 81)', () => {
  it('lista reais + sintéticos por data desc, total inclui prêmio', () => {
    render(
      <AssetDistributionsTab
        distributions={[dist()]} syntheticPremiums={[premium]}
        onRowClick={() => {}} onNew={() => {}}
      />,
    )
    const rows = screen.getAllByRole('row').slice(1)   // sem o thead
    expect(rows[0]).toHaveAttribute('data-testid', 'premium-row-m9')
    expect(rows[1]).toHaveAttribute('data-testid', 'distribution-row-d1')
    expect(screen.getByText('Prêmio sintético')).toBeInTheDocument()
    expect(screen.getByText('ITUBI350')).toBeInTheDocument()
    expect(screen.getByTestId('distributions-total')).toHaveTextContent('R$ 150')
    expect(screen.getByTestId('distributions-total')).toHaveTextContent('incl. prêmios')
    expect(screen.getByText('Proventos · 2')).toBeInTheDocument()
  })

  it('linha real chama onRowClick; sintética não', () => {
    const onRowClick = vi.fn()
    render(
      <AssetDistributionsTab
        distributions={[dist()]} syntheticPremiums={[premium]}
        onRowClick={onRowClick} onNew={() => {}}
      />,
    )
    fireEvent.click(screen.getByTestId('premium-row-m9'))
    expect(onRowClick).not.toHaveBeenCalled()
    fireEvent.click(screen.getByTestId('distribution-row-d1'))
    expect(onRowClick).toHaveBeenCalledWith(expect.objectContaining({ id: 'd1' }))
  })

  it('"Novo provento" chama onNew', () => {
    const onNew = vi.fn()
    render(<AssetDistributionsTab distributions={[]} syntheticPremiums={[]} onRowClick={() => {}} onNew={onNew} />)
    fireEvent.click(screen.getByTestId('distributions-new'))
    expect(onNew).toHaveBeenCalled()
    expect(screen.getByText('Sem proventos cadastrados.')).toBeInTheDocument()
  })

  it('sumDistributions converte USD pelo fx da linha e não multiplica BRL', () => {
    const t = sumDistributions(
      [dist({ net_amount: 100, currency: 'BRL', fx_rate: 5 }), dist({ id: 'd2', net_amount: 10, currency: 'USD', fx_rate: 5 })],
      [{ ...premium, net_amount: 20, currency: 'USD', fx_rate: 5 }],
    )
    expect(t.brl).toBe(100 + 50 + 100)
    expect(t.usd).toBe(20 + 10 + 20)
  })
})
