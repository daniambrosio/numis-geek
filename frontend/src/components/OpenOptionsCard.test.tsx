import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'

import OpenOptionsCard from './OpenOptionsCard'
import { api, type OpenOptionOut } from '../lib/api'

const FAKE_OPTIONS: OpenOptionOut[] = [
  {
    option_id: 'opt-1',
    ticker: 'ITUBR364',
    name: 'ITUB PUT 36.40 jun/26',
    option_type: 'PUT',
    strike: 36.40,
    expiration_date: '2026-06-19',
    days_to_expiration: 26,
    contract_size: 100,
    qty: 100,
    is_short: true,
    premium_received: 140,
    premium_per_share: 1.40,
    current_price: 0.85,
    mark_to_market: 85,
    close_now_pnl: 55,
    effective_price: 35.00,
    verdict: 'likely_worthless',
  },
  {
    option_id: 'opt-2',
    ticker: 'ITUBE476',
    name: 'ITUB CALL 47.50 jun/26',
    option_type: 'CALL',
    strike: 47.50,
    expiration_date: '2026-06-19',
    days_to_expiration: 26,
    contract_size: 100,
    qty: 100,
    is_short: true,
    premium_received: 80,
    premium_per_share: 0.80,
    current_price: 0.30,
    mark_to_market: 30,
    close_now_pnl: 50,
    effective_price: 48.30,
    verdict: 'likely_worthless',
  },
]

beforeEach(() => {
  vi.spyOn(api, 'listOpenOptionsForUnderlying').mockResolvedValue(FAKE_OPTIONS)
})

describe('OpenOptionsCard rows as links', () => {
  it('renders each row as an <a> with href /assets/{option_id}', async () => {
    render(
      <MemoryRouter>
        <OpenOptionsCard underlyingId="itub4-id" underlyingTicker="ITUB4" />
      </MemoryRouter>,
    )
    await waitFor(() => expect(screen.getAllByRole('link')).toHaveLength(2))
    const links = screen.getAllByRole('link')
    expect(links[0].getAttribute('href')).toBe('/assets/opt-1')
    expect(links[1].getAttribute('href')).toBe('/assets/opt-2')
  })

  it('clicking "Virou pó" does NOT navigate (preventDefault)', async () => {
    // Stub confirm so the action call doesn't trigger a real fetch.
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/assets/itub4-id']}>
        <OpenOptionsCard underlyingId="itub4-id" underlyingTicker="ITUB4" />
      </MemoryRouter>,
    )
    await waitFor(() => expect(screen.getAllByRole('link')).toHaveLength(2))
    const expireBtns = screen.getAllByText('Virou pó')
    // Click the first expire button — if preventDefault is wired, the
    // surrounding <a> won't navigate. We assert no error + confirm was hit.
    await user.click(expireBtns[0])
    expect(window.confirm).toHaveBeenCalled()
  })
})
