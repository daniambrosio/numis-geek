import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'

import GapVsTargetChart from './GapVsTargetChart'

describe('GapVsTargetChart', () => {
  it('renders empty message', () => {
    render(<GapVsTargetChart dimension="CLASS" slices={[]} />)
    expect(screen.getByText(/Sem dados pra mostrar gap/)).toBeInTheDocument()
  })

  it('renders class rows with delta', () => {
    render(
      <GapVsTargetChart
        dimension="CLASS"
        slices={[
          { key: 'STOCK', current_pct: 0.40, target_pct: 0.30 },
          { key: 'REIT', current_pct: 0.10, target_pct: 0.20 },
        ]}
      />,
    )
    expect(screen.getByTestId('gap-row-STOCK')).toBeInTheDocument()
    expect(screen.getByTestId('gap-row-REIT')).toBeInTheDocument()
    // +10% (overweight STOCK)
    expect(screen.getByText('+10.0%')).toBeInTheDocument()
    // -10% (underweight REIT)
    expect(screen.getByText('-10.0%')).toBeInTheDocument()
  })

  it('renders country labels with flags', () => {
    render(
      <GapVsTargetChart
        dimension="COUNTRY"
        slices={[
          { key: 'BR', current_pct: 0.6, target_pct: 0.7 },
          { key: 'US', current_pct: 0.4, target_pct: 0.3 },
        ]}
      />,
    )
    expect(screen.getByText('Brasil')).toBeInTheDocument()
    expect(screen.getByText('EUA')).toBeInTheDocument()
  })
})
