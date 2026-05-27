import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'

import ConfidencePill from './ConfidencePill'

describe('ConfidencePill (Spec 38)', () => {
  it('renders green for >= 0.9', () => {
    render(<ConfidencePill value={0.95} />)
    const pill = screen.getByTestId('confidence-pill')
    expect(pill).toHaveTextContent('95%')
    expect(pill.className).toMatch(/emerald/)
  })
  it('renders amber for 0.7..0.9', () => {
    render(<ConfidencePill value={0.8} />)
    expect(screen.getByTestId('confidence-pill').className).toMatch(/amber/)
  })
  it('renders red for < 0.7', () => {
    render(<ConfidencePill value={0.4} />)
    expect(screen.getByTestId('confidence-pill').className).toMatch(/red/)
  })
  it('renders neutral dash when value is null', () => {
    render(<ConfidencePill value={null} />)
    expect(screen.queryByTestId('confidence-pill')).toBeNull()
  })
})
