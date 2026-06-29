import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'

import VerdictBadge from './VerdictBadge'

describe('VerdictBadge', () => {
  it('renders BUY in green', () => {
    render(<VerdictBadge verdict="BUY" />)
    const el = screen.getByText('Comprar')
    expect(el).toBeInTheDocument()
    expect(el.className).toMatch(/emerald/)
  })

  it('renders SELL in red', () => {
    render(<VerdictBadge verdict="SELL" />)
    const el = screen.getByText('Vender')
    expect(el.className).toMatch(/red/)
  })

  it('renders HOLD in gray', () => {
    render(<VerdictBadge verdict="HOLD" />)
    expect(screen.getByText('Manter')).toBeInTheDocument()
  })

  it('renders NA as dash', () => {
    render(<VerdictBadge verdict="NA" />)
    expect(screen.getByText('—')).toBeInTheDocument()
  })

  it('attaches title for tooltip', () => {
    render(<VerdictBadge verdict="BUY" title="Cheap by Bazin" />)
    const el = screen.getByText('Comprar')
    expect(el.getAttribute('title')).toBe('Cheap by Bazin')
  })
})
