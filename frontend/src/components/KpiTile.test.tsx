import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'

import KpiTile from './KpiTile'

describe('KpiTile (spec 81 — compartilhado)', () => {
  it('renderiza label, valor e sub', () => {
    render(<KpiTile label="Posição" value="R$ 1,2k" sub="30 unidades" />)
    expect(screen.getByText('Posição')).toBeInTheDocument()
    expect(screen.getByText('R$ 1,2k')).toBeInTheDocument()
    expect(screen.getByText('30 unidades')).toBeInTheDocument()
    expect(screen.queryByTestId('kpi-dot')).toBeNull()
  })
  it('intent colore o valor', () => {
    render(<KpiTile label="P&L" value="−R$ 10" intent="negative" />)
    expect(screen.getByText('−R$ 10').className).toMatch(/text-red/)
  })
  it('cornerDot mostra o ponto de frescor com title', () => {
    render(<KpiTile label="Preço" value="R$ 1" cornerDot={{ color: '#0f0', title: 'Atualizado' }} />)
    const dot = screen.getByTestId('kpi-dot')
    expect(dot).toHaveAttribute('title', 'Atualizado')
    expect(dot.style.background).toBeTruthy()
  })
})
