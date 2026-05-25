import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'

import DistributionTotalsLine from './DistributionTotalsLine'

describe('DistributionTotalsLine', () => {
  it('renders all four totals labels', () => {
    render(
      <DistributionTotalsLine
        netBRL={41100} grossBRL={45800} taxBRL={4700} eventCount={1715}
      />,
    )
    expect(screen.getByText('Líquido')).toBeInTheDocument()
    expect(screen.getByText('Bruto')).toBeInTheDocument()
    expect(screen.getByText('IR retido')).toBeInTheDocument()
    expect(screen.getByText(/1\.715 eventos/)).toBeInTheDocument()
  })

  it('uses singular when only 1 event', () => {
    render(
      <DistributionTotalsLine
        netBRL={100} grossBRL={100} taxBRL={0} eventCount={1}
      />,
    )
    expect(screen.getByText(/1 evento$/)).toBeInTheDocument()
  })
})
