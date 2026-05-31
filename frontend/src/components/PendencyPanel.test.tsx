import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

import PendencyPanel from './PendencyPanel'
import type { SnapshotPendencyOut } from '../lib/api'

function makePendency(overrides: Partial<SnapshotPendencyOut> = {}): SnapshotPendencyOut {
  return {
    id: 'p-1',
    snapshot_id: 's-1',
    asset_id: 'a-1',
    asset_ticker: 'PETR4',
    asset_name: 'Petrobras',
    asset_institution_short_name: null,
    reason: 'API_FAILED',
    action_type: 'RETRY_API',
    detail: 'brapi timeout',
    resolved_at: null,
    resolved_by: null,
    resolution_note: null,
    created_at: '2026-05-25T00:00:00Z',
    previous_unit_price: null,
    previous_period_end: null,
    ...overrides,
  }
}

beforeEach(() => {
  vi.restoreAllMocks()
})

function wrap(children: React.ReactNode) {
  return <MemoryRouter>{children}</MemoryRouter>
}

describe('PendencyPanel', () => {
  it('renders empty state when no pendencies', () => {
    render(wrap(<PendencyPanel pendencies={[]} onResolved={() => {}} />))
    expect(screen.getByText(/Sem pendências/)).toBeInTheDocument()
  })

  it('lists each pendency with the asset ticker', () => {
    render(wrap(<PendencyPanel
      pendencies={[
        makePendency({ id: '1', asset_ticker: 'PETR4' }),
        makePendency({ id: '2', asset_ticker: 'AAPL' }),
      ]}
      onResolved={() => {}}
    />))
    expect(screen.getByText('PETR4')).toBeInTheDocument()
    expect(screen.getByText('AAPL')).toBeInTheDocument()
  })

  it('disables Confirm button while any pendency is open', () => {
    render(wrap(<PendencyPanel
      pendencies={[makePendency()]}
      onResolved={() => {}}
      onConfirm={() => {}}
    />))
    const btn = screen.getByRole('button', { name: /Confirmar/ })
    expect(btn).toBeDisabled()
  })

  it('enables Confirm button when all pendencies are resolved', () => {
    render(wrap(<PendencyPanel
      pendencies={[makePendency({ resolved_at: '2026-05-25T12:00:00Z' })]}
      onResolved={() => {}}
      onConfirm={() => {}}
    />))
    const btn = screen.getByRole('button', { name: /Confirmar/ })
    expect(btn).not.toBeDisabled()
  })

  it('shows Retry button for RETRY_API action', () => {
    render(wrap(<PendencyPanel
      pendencies={[makePendency({ action_type: 'RETRY_API' })]}
      onResolved={() => {}}
    />))
    expect(screen.getByRole('button', { name: /Retry/ })).toBeInTheDocument()
  })

  it('shows Editar button for EDIT_PRICE action', () => {
    render(wrap(<PendencyPanel
      pendencies={[makePendency({ action_type: 'EDIT_PRICE', reason: 'MANUAL_SOURCE' })]}
      onResolved={() => {}}
    />))
    expect(screen.getByRole('button', { name: /Editar/ })).toBeInTheDocument()
  })

  it('shows Upload button for UPLOAD_FILE action', () => {
    render(wrap(<PendencyPanel
      pendencies={[makePendency({ action_type: 'UPLOAD_FILE', reason: 'UPLOAD_REQUIRED' })]}
      onResolved={() => {}}
    />))
    expect(screen.getByRole('button', { name: /Upload/ })).toBeInTheDocument()
  })

  it('groups pendencies by financial institution with ungrouped last', () => {
    render(wrap(<PendencyPanel
      pendencies={[
        makePendency({ id: '1', asset_ticker: 'PETR4', asset_institution_short_name: 'XP' }),
        makePendency({ id: '2', asset_ticker: 'CASA', asset_institution_short_name: null }),
        makePendency({ id: '3', asset_ticker: 'AAPL', asset_institution_short_name: 'Avenue' }),
      ]}
      onResolved={() => {}}
    />))
    expect(screen.getByTestId('pendency-group-Avenue')).toBeInTheDocument()
    expect(screen.getByTestId('pendency-group-XP')).toBeInTheDocument()
    expect(screen.getByTestId('pendency-group-Sem instituição')).toBeInTheDocument()
  })

  it('shows Repetir button when previous_unit_price is present', () => {
    render(wrap(<PendencyPanel
      pendencies={[makePendency({
        action_type: 'EDIT_PRICE',
        reason: 'MANUAL_SOURCE',
        previous_unit_price: '250000.00',
        previous_period_end: '2026-04-30',
      })]}
      onResolved={() => {}}
    />))
    expect(screen.getByRole('button', { name: /Repetir/ })).toBeInTheDocument()
    // Previous-month price label is rendered inline.
    expect(screen.getByText(/Abr\/26/)).toBeInTheDocument()
  })

  it('hides Repetir button when previous_unit_price is null', () => {
    render(wrap(<PendencyPanel
      pendencies={[makePendency({
        action_type: 'EDIT_PRICE',
        reason: 'MANUAL_SOURCE',
        previous_unit_price: null,
        previous_period_end: null,
      })]}
      onResolved={() => {}}
    />))
    expect(screen.queryByRole('button', { name: /Repetir/ })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Editar/ })).toBeInTheDocument()
  })
})
