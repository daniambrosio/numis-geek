import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

import PendencyPanel from './PendencyPanel'
import type { AssetOut, SnapshotPendencyOut } from '../lib/api'

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

interface PanelOverrides {
  pendencies: SnapshotPendencyOut[]
  onConfirm?: () => void
  assetById?: Map<string, AssetOut>
  pendingTotal?: number
  totalAssetsCount?: number
  resolvedAssets?: number
  periodEndDate?: string
}

function renderPanel(opts: PanelOverrides) {
  const open = opts.pendencies.filter(p => !p.resolved_at).length
  const pendingTotal = opts.pendingTotal ?? open
  const totalAssetsCount =
    opts.totalAssetsCount ?? Math.max(opts.pendencies.length, 1)
  const resolvedAssets =
    opts.resolvedAssets ?? (totalAssetsCount - open)
  return render(wrap(<PendencyPanel
    pendencies={opts.pendencies}
    assetById={opts.assetById ?? new Map()}
    pendingTotal={pendingTotal}
    totalAssetsCount={totalAssetsCount}
    resolvedAssets={resolvedAssets}
    periodEndDate={opts.periodEndDate ?? '2026-05-31'}
    onResolved={() => {}}
    onConfirm={opts.onConfirm}
  />))
}

describe('PendencyPanel', () => {
  it('renders header with pending/total counts', () => {
    renderPanel({
      pendencies: [makePendency()],
      pendingTotal: 3, totalAssetsCount: 10, resolvedAssets: 7,
    })
    expect(screen.getByText(/Resolver pendências antes de fechar/)).toBeInTheDocument()
    expect(screen.getByText(/3 de 10 ativos/)).toBeInTheDocument()
    expect(screen.getByText(/7 de 10 resolvidos/)).toBeInTheDocument()
  })

  it('lists each open pendency with the asset ticker', () => {
    renderPanel({
      pendencies: [
        makePendency({ id: '1', asset_ticker: 'PETR4' }),
        makePendency({ id: '2', asset_ticker: 'AAPL' }),
      ],
    })
    expect(screen.getByText('PETR4')).toBeInTheDocument()
    expect(screen.getByText('AAPL')).toBeInTheDocument()
  })

  it('disables Confirm button while any pendency is open', () => {
    renderPanel({
      pendencies: [makePendency()],
      onConfirm: () => {},
      pendingTotal: 1, totalAssetsCount: 1, resolvedAssets: 0,
    })
    const btn = screen.getByRole('button', { name: /Confirmar/ })
    expect(btn).toBeDisabled()
  })

  it('enables Confirm button when no pendencies remain', () => {
    renderPanel({
      pendencies: [makePendency({ resolved_at: '2026-05-25T12:00:00Z' })],
      onConfirm: () => {},
      pendingTotal: 0, totalAssetsCount: 1, resolvedAssets: 1,
    })
    const btn = screen.getByRole('button', { name: /Confirmar/ })
    expect(btn).not.toBeDisabled()
  })

  it('shows Retry button for RETRY_API action', () => {
    renderPanel({ pendencies: [makePendency({ action_type: 'RETRY_API' })] })
    expect(screen.getByRole('button', { name: /Retry/ })).toBeInTheDocument()
  })

  it('shows Editar button for EDIT_PRICE action', () => {
    renderPanel({
      pendencies: [makePendency({ action_type: 'EDIT_PRICE', reason: 'MANUAL_SOURCE' })],
    })
    expect(screen.getByRole('button', { name: /Editar/ })).toBeInTheDocument()
  })

  it('shows Upload button for UPLOAD_FILE action', () => {
    renderPanel({
      pendencies: [makePendency({ action_type: 'UPLOAD_FILE', reason: 'UPLOAD_REQUIRED' })],
    })
    expect(screen.getByRole('button', { name: /Upload/ })).toBeInTheDocument()
  })

  it('groups pendencies by financial institution with ungrouped last', () => {
    renderPanel({
      pendencies: [
        makePendency({ id: '1', asset_ticker: 'PETR4', asset_institution_short_name: 'XP' }),
        makePendency({ id: '2', asset_ticker: 'CASA', asset_institution_short_name: null }),
        makePendency({ id: '3', asset_ticker: 'AAPL', asset_institution_short_name: 'Avenue' }),
      ],
    })
    expect(screen.getByTestId('pendency-group-Avenue')).toBeInTheDocument()
    expect(screen.getByTestId('pendency-group-XP')).toBeInTheDocument()
    expect(screen.getByTestId('pendency-group-Sem instituição')).toBeInTheDocument()
  })

  it('shows Repetir button when previous_unit_price is present', () => {
    renderPanel({
      pendencies: [makePendency({
        action_type: 'EDIT_PRICE',
        reason: 'MANUAL_SOURCE',
        previous_unit_price: '250000.00',
        previous_period_end: '2026-04-30',
      })],
    })
    expect(screen.getByRole('button', { name: /Repetir/ })).toBeInTheDocument()
    expect(screen.getByText(/Abr\/26/)).toBeInTheDocument()
  })

  it('hides Repetir button when previous_unit_price is null', () => {
    renderPanel({
      pendencies: [makePendency({
        action_type: 'EDIT_PRICE',
        reason: 'MANUAL_SOURCE',
        previous_unit_price: null,
        previous_period_end: null,
      })],
    })
    expect(screen.queryByRole('button', { name: /Repetir/ })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Editar/ })).toBeInTheDocument()
  })
})
