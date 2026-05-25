import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'

import SourceMixBar from './SourceMixBar'

describe('SourceMixBar', () => {
  it('shows em-dash when total is zero', () => {
    render(<SourceMixBar slices={[{ label: 'A', count: 0, color: '#000' }]} />)
    expect(screen.getByText('—')).toBeInTheDocument()
  })

  it('renders count labels by default', () => {
    render(
      <SourceMixBar slices={[
        { label: 'API ok', count: 10, color: '#22c55e' },
        { label: 'Manual', count: 2, color: '#3b82f6' },
      ]} />,
    )
    expect(screen.getByText('API ok: 10')).toBeInTheDocument()
    expect(screen.getByText('Manual: 2')).toBeInTheDocument()
  })

  it('omits labels when showCounts=false', () => {
    render(
      <SourceMixBar
        slices={[{ label: 'API ok', count: 10, color: '#22c55e' }]}
        showCounts={false}
      />,
    )
    expect(screen.queryByText(/API ok:/)).toBeNull()
  })
})
