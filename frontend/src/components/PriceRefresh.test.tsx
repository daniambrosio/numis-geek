/* Spec 44 — PriceRefresh popover tests. Cover the 3 critical visual
 * decisions where the redesign diverged from the previous impl:
 *  1. Source dots default to gray (not tier-colored).
 *  2. "Mais desatualizados (N)" title carries count; stale-only filter.
 *  3. PTAX block renders when status is loaded; degrades gracefully.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

import PriceRefresh from './PriceRefresh'
import { api, type AssetOut, type PTAXStatusOut } from '../lib/api'

function asset(over: Partial<AssetOut> = {}): AssetOut {
  return {
    id: over.id ?? 'a-' + Math.random().toString(36).slice(2, 8),
    workspace_id: 'ws1',
    workspace_name: 'Família',
    account_id: 'acc1',
    account_name: 'XP',
    financial_institution_id: 'fi1',
    financial_institution_name: 'XP',
    asset_class: 'STOCK',
    country: 'BR',
    name: over.name ?? 'PETR4',
    ticker: over.ticker ?? 'PETR4',
    cnpj: null,
    currency: 'BRL',
    current_price: 30,
    price_updated_at: over.price_updated_at ?? new Date().toISOString(),
    price_source: over.price_source ?? 'BRAPI',
    price_tier: over.price_tier ?? 'FRESH',
    notes: null,
    external_id: null,
    external_source: null,
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    details: null,
    ...over,
  }
}

function freshPtax(): PTAXStatusOut {
  // 2 days ago so the age renders deterministically.
  const d = new Date()
  d.setDate(d.getDate() - 2)
  const iso = d.toISOString().slice(0, 10)
  return {
    total_rows: 1567,
    last_date: iso,
    oldest_date: '2021-01-04',
    last_fetched_at: new Date().toISOString(),
  }
}

function renderWidget() {
  return render(
    <MemoryRouter>
      <PriceRefresh />
    </MemoryRouter>,
  )
}

describe('PriceRefresh (Spec 44)', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('renders source dots as gray-400 when idle (no tier color leak)', async () => {
    vi.spyOn(api, 'listAssets').mockResolvedValue([
      asset({ ticker: 'PETR4', price_source: 'BRAPI', price_tier: 'OLD' }),
      asset({ ticker: 'AAPL', price_source: 'FINNHUB', price_tier: 'STALE' }),
    ])
    vi.spyOn(api, 'ptaxStatusWorkspace').mockResolvedValue(freshPtax())

    renderWidget()
    // Open the popover.
    fireEvent.click(screen.getByTitle('Preços e PTAX'))

    // Wait for the BRAPI row to render (data has loaded).
    const brapiRow = await screen.findByTestId('source-row-BRAPI')
    const dot = brapiRow.querySelector('span') as HTMLElement
    expect(dot.className).toMatch(/bg-gray-400/)
    expect(dot.className).not.toMatch(/bg-amber/)
    expect(dot.className).not.toMatch(/bg-red/)
  })

  it('shows "Mais desatualizados (N)" with stale-only count', async () => {
    vi.spyOn(api, 'listAssets').mockResolvedValue([
      asset({ ticker: 'FRESH1', price_source: 'BRAPI', price_tier: 'FRESH' }),
      asset({ ticker: 'STALE1', price_source: 'BRAPI', price_tier: 'STALE' }),
      asset({ ticker: 'OLD1',   price_source: 'FINNHUB', price_tier: 'OLD' }),
    ])
    vi.spyOn(api, 'ptaxStatusWorkspace').mockResolvedValue(freshPtax())

    renderWidget()
    fireEvent.click(screen.getByTitle('Preços e PTAX'))

    const title = await screen.findByTestId('stale-title')
    // Only STALE + OLD count — FRESH excluded.
    expect(title.textContent).toMatch(/\(2\)/)
    expect(screen.getByText('STALE1')).toBeInTheDocument()
    expect(screen.getByText('OLD1')).toBeInTheDocument()
    expect(screen.queryByText('FRESH1')).toBeNull()
  })

  it('renders the PTAX block with last date + age when status loads', async () => {
    vi.spyOn(api, 'listAssets').mockResolvedValue([])
    vi.spyOn(api, 'ptaxStatusWorkspace').mockResolvedValue(freshPtax())

    renderWidget()
    fireEvent.click(screen.getByTitle('Preços e PTAX'))

    expect(await screen.findByText('PTAX')).toBeInTheDocument()
    const age = await screen.findByTestId('ptax-age')
    expect(age.textContent).toMatch(/há \d/)
    expect(screen.getByTestId('ptax-sync-button')).toBeInTheDocument()
    expect(screen.getByText(/1567 cotações armazenadas/)).toBeInTheDocument()
  })

  it('renders PTAX block with — when status fetch fails', async () => {
    vi.spyOn(api, 'listAssets').mockResolvedValue([])
    vi.spyOn(api, 'ptaxStatusWorkspace').mockRejectedValue(new Error('boom'))

    renderWidget()
    fireEvent.click(screen.getByTitle('Preços e PTAX'))

    expect(await screen.findByText('PTAX')).toBeInTheDocument()
    // Sync button still rendered so user can recover.
    expect(screen.getByTestId('ptax-sync-button')).toBeInTheDocument()
    // No row showing "X cotações armazenadas".
    expect(screen.queryByText(/cotações armazenadas/)).toBeNull()
  })

  it('triggers /ptax/sync when clicking Sincronizar', async () => {
    vi.spyOn(api, 'listAssets').mockResolvedValue([])
    vi.spyOn(api, 'ptaxStatusWorkspace').mockResolvedValue(freshPtax())
    const syncSpy = vi.spyOn(api, 'syncPtaxWorkspace').mockResolvedValue({
      mode: 'incremental',
      fetched_count: 1,
      inserted_count: 1,
      updated_count: 0,
      range_start: '2026-05-26',
      range_end: '2026-05-26',
      duration_ms: 8,
    })

    renderWidget()
    fireEvent.click(screen.getByTitle('Preços e PTAX'))
    const btn = await screen.findByTestId('ptax-sync-button')
    fireEvent.click(btn)

    await waitFor(() => {
      expect(syncSpy).toHaveBeenCalledWith('incremental')
    })
  })
})
