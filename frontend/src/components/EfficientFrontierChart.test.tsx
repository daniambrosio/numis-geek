import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'

import EfficientFrontierChart from './EfficientFrontierChart'

describe('EfficientFrontierChart', () => {
  it('renders empty message when no points', () => {
    render(<EfficientFrontierChart frontier={[]} />)
    expect(screen.getByText(/Sem pontos de fronteira/)).toBeInTheDocument()
  })

  it('renders frontier path + current + optimal markers', () => {
    render(
      <EfficientFrontierChart
        frontier={[
          { vol: 0.1, ret: 0.05 },
          { vol: 0.15, ret: 0.08 },
          { vol: 0.2, ret: 0.10 },
        ]}
        currentPoint={{ vol: 0.18, ret: 0.07 }}
        optimalPoint={{ vol: 0.12, ret: 0.075 }}
      />,
    )
    expect(screen.getByTestId('frontier-chart')).toBeInTheDocument()
    expect(screen.getByTestId('current-marker')).toBeInTheDocument()
    expect(screen.getByTestId('optimal-marker')).toBeInTheDocument()
    expect(screen.getByText('atual')).toBeInTheDocument()
    expect(screen.getByText('sugerido')).toBeInTheDocument()
  })
})
