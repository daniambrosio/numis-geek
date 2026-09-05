import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

import AssetPerformanceTable from './AssetPerformanceTable'
import type { AssetPerformanceRow } from '../../lib/api'

const base: AssetPerformanceRow = {
  period_end_date: '2026-08-31', quantity: '100', unit_price: '32.50',
  market_value_native: '3250', market_value_brl: '3250', market_value_usd: '600',
  total_invested_brl: '3000', fx_rate_usd_brl: '5.4', pnl_brl: '250', pnl_pct: 0.0833,
  aportes_native: '0', resgates_native: '0', aportes_brl: '0', resgates_brl: '0',
  proventos_native: '45.5', proventos_brl: '45.5',
  return_pct: 0.0312, return_brl_pct: 0.0312, return_null_reason: null,
}

function mount(rows: AssetPerformanceRow[], over: Partial<{ currency: string; isValueMode: boolean }> = {}) {
  return render(
    <MemoryRouter>
      <AssetPerformanceTable rows={rows} currency={over.currency ?? 'BRL'} isValueMode={over.isValueMode ?? false} assetId="a1" />
    </MemoryRouter>,
  )
}

describe('AssetPerformanceTable (spec 81)', () => {
  it('cabeçalhos canônicos e valores da linha', () => {
    mount([base, { ...base, period_end_date: '2026-07-31', market_value_brl: '3000', return_pct: null, return_null_reason: 'FIRST_CLOSING', proventos_native: '0', proventos_brl: '0' }])
    for (const h of ['Período', 'Qtd', 'Preço unitário', 'Valor total (BRL)', 'Valor total (USD)', 'Investido', 'P&L', 'Proventos no mês', 'Retorno no mês', 'Δ MoM']) {
      expect(screen.getByText(h)).toBeInTheDocument()
    }
    const rows = screen.getAllByTestId('asset-performance-row')
    expect(rows).toHaveLength(2)
    expect(rows[0]).toHaveTextContent('Ago/26')
    expect(rows[0]).toHaveTextContent('+3,12%')
    expect(rows[0]).toHaveTextContent('+8,3%')          // P&L %
    expect(rows[0]).toHaveTextContent('R$ 45,50')       // proventos do mês
    expect(rows[0]).toHaveTextContent('+8,33%')         // Δ MoM 3000→3250
    // null → "—" com o motivo no title
    const ret = screen.getAllByTestId('asset-performance-return')[1]
    expect(ret).toHaveTextContent('—')
    expect(ret).toHaveAttribute('title', 'primeiro fechamento do ativo')
  })

  it('retorno negativo fica vermelho, positivo verde', () => {
    mount([base, { ...base, period_end_date: '2026-07-31', return_pct: -0.02 }])
    const [pos, neg] = screen.getAllByTestId('asset-performance-return')
    expect(pos.className).toMatch(/emerald/)
    expect(neg.className).toMatch(/red/)
  })

  it('modo valor mostra — em Qtd e Preço unitário', () => {
    mount([base], { isValueMode: true })
    const cells = screen.getAllByTestId('asset-performance-row')[0].querySelectorAll('td')
    expect(cells[1]).toHaveTextContent('—')
    expect(cells[2]).toHaveTextContent('—')
    expect(cells[3]).toHaveTextContent('3.250')
  })

  it('ativo USD mostra retorno em BRL como subtexto', () => {
    mount([{ ...base, return_pct: 0.01, return_brl_pct: 0.05 }], { currency: 'USD' })
    expect(screen.getByTestId('asset-performance-return')).toHaveTextContent('+5,00% em BRL')
  })

  it('vazio mostra mensagem', () => {
    mount([])
    expect(screen.getByText(/Sem fechamentos ainda/)).toBeInTheDocument()
  })
})
