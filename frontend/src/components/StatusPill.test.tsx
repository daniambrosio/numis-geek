import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'

import StatusPill from './StatusPill'

describe('StatusPill', () => {
  it('renders Portuguese label for SCHEDULED', () => {
    render(<StatusPill status="SCHEDULED" />)
    expect(screen.getByText('Agendado')).toBeInTheDocument()
  })
  it('renders Portuguese label for IN_REVIEW', () => {
    render(<StatusPill status="IN_REVIEW" />)
    expect(screen.getByText('Em revisão')).toBeInTheDocument()
  })
  it('renders Portuguese label for CLOSED', () => {
    render(<StatusPill status="CLOSED" />)
    expect(screen.getByText('Fechado')).toBeInTheDocument()
  })
})
