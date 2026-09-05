import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'

import AssetReturnChart, { accumulate } from './AssetReturnChart'
import type { AssetPerformanceRow } from '../../lib/api'

const row = (date: string, r: number | null): AssetPerformanceRow => ({
  period_end_date: date, quantity: '1', unit_price: null,
  market_value_native: '100', market_value_brl: '100', market_value_usd: null,
  total_invested_brl: null, fx_rate_usd_brl: null, pnl_brl: null, pnl_pct: null,
  contributions_native: '0', withdrawals_native: '0', contributions_brl: '0', withdrawals_brl: '0',
  income_native: '0', income_brl: '0',
  return_pct: r, return_brl_pct: r, return_null_reason: r == null ? 'GAP' : null,
})

describe('AssetReturnChart (spec 81)', () => {
  it('acumula em cadeia e reinicia no buraco', () => {
    const pts = accumulate([
      row('2026-01-31', null), row('2026-02-28', 0.10), row('2026-03-31', -0.05),
      row('2026-04-30', null), row('2026-05-31', 0.02),
    ])
    expect(pts[0].acc).toBeNull()
    expect(pts[1].acc).toBeCloseTo(0.10, 10)
    expect(pts[2].acc).toBeCloseTo(1.10 * 0.95 - 1, 10)   // 4,5%
    expect(pts[3].acc).toBeNull()
    expect(pts[4].acc).toBeCloseTo(0.02, 10)
  })

  it('renderiza o acumulado até o último mês válido', () => {
    render(<AssetReturnChart rows={[row('2026-01-31', null), row('2026-02-28', 0.10), row('2026-03-31', -0.05)]} />)
    expect(screen.getByTestId('asset-return-chart')).toBeInTheDocument()
    expect(screen.getByText(/\+4,5% até Mar\/26/)).toBeInTheDocument()
  })

  it('não renderiza sem pontos válidos', () => {
    const { container } = render(<AssetReturnChart rows={[row('2026-01-31', null), row('2026-02-28', null)]} />)
    expect(container).toBeEmptyDOMElement()
  })
})


it('mês válido isolado entre buracos vira um ponto, não some', () => {
  const rows = [
    row('2026-01-31', null), row('2026-02-28', 0.10), row('2026-03-31', null),
    row('2026-04-30', 0.02), row('2026-05-31', null),
  ]
  const { container } = render(<AssetReturnChart rows={rows} />)
  expect(screen.getAllByTestId('asset-return-lone-point')).toHaveLength(2)
  expect(container.querySelectorAll('path').length).toBe(0)
  expect(screen.getByText(/\+2,0% até Abr\/26/)).toBeInTheDocument()
})
