import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import PriceCell from './PriceCell'
import { api, type AssetOut } from '../lib/api'

function makeAsset(overrides: Partial<AssetOut> = {}): AssetOut {
  return {
    id: 'a-1',
    workspace_id: 'ws-1',
    workspace_name: null,
    account_id: 'acc-1',
    account_name: 'Acc',
    financial_institution_id: 'fi-1',
    financial_institution_name: 'FI',
    asset_class: 'STOCK',
    country: 'BR',
    name: 'Petrobras',
    ticker: 'PETR4',
    cnpj: null,
    currency: 'BRL',
    current_price: 38,
    price_updated_at: '2026-05-24T12:00:00Z',
    price_source: 'BRAPI',
    price_tier: 'FRESH',
    notes: null,
    external_id: null,
    external_source: null,
    is_active: true,
    created_at: '2026-01-01',
    updated_at: '2026-05-24',
    details: null,
    ...overrides,
  } as AssetOut
}

const now = new Date('2026-05-24T18:00:00Z')

beforeEach(() => {
  vi.restoreAllMocks()
})

describe('PriceCell render', () => {
  it('shows dot + relative age', () => {
    render(<PriceCell asset={makeAsset()} now={now} />)
    expect(screen.getByText('há 6h')).toBeInTheDocument()
  })

  it('renders the refresh button when source is automated (BRAPI)', () => {
    render(<PriceCell asset={makeAsset({ price_source: 'BRAPI' })} now={now} />)
    expect(screen.getByRole('button', { name: /Atualizar preço de PETR4/i }))
      .toBeInTheDocument()
  })

  it('does NOT render the refresh button when source is MANUAL', () => {
    render(<PriceCell asset={makeAsset({ price_source: 'MANUAL' })} now={now} />)
    expect(screen.queryByRole('button')).toBeNull()
  })

  it('does NOT render the refresh button when source is null', () => {
    render(<PriceCell asset={makeAsset({ price_source: null })} now={now} />)
    expect(screen.queryByRole('button')).toBeNull()
  })

  it('shows "—" when price_updated_at is null', () => {
    render(
      <PriceCell
        asset={makeAsset({ price_updated_at: null, price_tier: 'UNKNOWN' })}
        now={now}
      />,
    )
    expect(screen.getByText('—')).toBeInTheDocument()
  })
})

describe('PriceCell refresh', () => {
  it('calls refreshAssetPrice + getAsset on click and reports fresh asset to parent', async () => {
    const refreshSpy = vi.spyOn(api, 'refreshAssetPrice').mockResolvedValue({
      asset_id: 'a-1', ticker: 'PETR4', country: 'BR', status: 'ok',
      provider: 'brapi', price_source: 'BRAPI',
      old_price: 38, new_price: 39.5, error: null,
    })
    const updated = makeAsset({ current_price: 39.5 })
    const getSpy = vi.spyOn(api, 'getAsset').mockResolvedValue(updated)
    const onUpdated = vi.fn()

    const user = userEvent.setup()
    render(<PriceCell asset={makeAsset()} onUpdated={onUpdated} now={now} />)
    await user.click(screen.getByRole('button'))

    await waitFor(() => expect(refreshSpy).toHaveBeenCalledWith('a-1'))
    await waitFor(() => expect(getSpy).toHaveBeenCalledWith('a-1'))
    expect(onUpdated).toHaveBeenCalledWith(updated)
  })

  it('does not call onUpdated when refresh returns a non-ok status', async () => {
    vi.spyOn(api, 'refreshAssetPrice').mockResolvedValue({
      asset_id: 'a-1', ticker: 'PETR4', country: 'BR', status: 'failed',
      provider: null, price_source: 'BRAPI',
      old_price: null, new_price: null, error: 'timeout',
    })
    const getSpy = vi.spyOn(api, 'getAsset')
    const onUpdated = vi.fn()

    const user = userEvent.setup()
    render(<PriceCell asset={makeAsset()} onUpdated={onUpdated} now={now} />)
    await user.click(screen.getByRole('button'))

    await waitFor(() => expect(api.refreshAssetPrice).toHaveBeenCalled())
    expect(getSpy).not.toHaveBeenCalled()
    expect(onUpdated).not.toHaveBeenCalled()
  })

  it('button click stops propagation so it does not trigger row navigation', async () => {
    vi.spyOn(api, 'refreshAssetPrice').mockResolvedValue({
      asset_id: 'a-1', ticker: 'PETR4', country: 'BR', status: 'ok',
      provider: 'brapi', price_source: 'BRAPI',
      old_price: 38, new_price: 39.5, error: null,
    })
    vi.spyOn(api, 'getAsset').mockResolvedValue(makeAsset())

    const rowClick = vi.fn()
    const user = userEvent.setup()
    render(
      <div onClick={rowClick}>
        <PriceCell asset={makeAsset()} now={now} />
      </div>,
    )
    await user.click(screen.getByRole('button'))
    expect(rowClick).not.toHaveBeenCalled()
  })
})
