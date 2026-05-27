/* Spec 41 — dual-currency Pill (Dashboard hero tiles).
 *
 * `<Pill>` is the tile primitive used in the Dashboard hero. After Spec 41
 * it accepts an optional `usdValue` to render the USD sub-line in dim
 * below the BRL principal. These tests verify that exact behavior.
 */
import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'

import { Pill } from './Dashboard'

describe('Pill — dual-currency sub-line (Spec 41)', () => {
  it('renders only the BRL principal when usdValue is omitted', () => {
    render(<Pill label="Investido" value="R$ 1,2 mi" />)
    expect(screen.getByText('Investido')).toBeInTheDocument()
    expect(screen.getByText('R$ 1,2 mi')).toBeInTheDocument()
    // Anything matching $X (USD prefix) should not be present.
    expect(screen.queryByText(/\$\d/)).toBeNull()
  })

  it('renders BRL principal + USD sub-line when usdValue is provided', () => {
    render(
      <Pill
        label="Investido"
        value="R$ 1,2 mi"
        usdValue="$240K"
      />,
    )
    expect(screen.getByText('R$ 1,2 mi')).toBeInTheDocument()
    expect(screen.getByText('$240K')).toBeInTheDocument()
  })

  it('renders signed BRL principal + signed USD sub-line (Ganho/perda case)', () => {
    render(
      <Pill
        label="Ganho/perda"
        value="+R$ 320K"
        usdValue="+$64K"
        tone="positive"
        money
      />,
    )
    const brl = screen.getByText('+R$ 320K')
    expect(brl).toBeInTheDocument()
    expect(brl.parentElement?.className).toMatch(/emerald/)
    expect(screen.getByText('+$64K')).toBeInTheDocument()
  })

  it('renders dim small text for the USD sub-line', () => {
    render(<Pill label="Proventos" value="R$ 12K" usdValue="$2.4K" />)
    const usd = screen.getByText('$2.4K')
    expect(usd.className).toMatch(/text-\[10px\]/)
    expect(usd.className).toMatch(/text-gray-500/)
  })
})
