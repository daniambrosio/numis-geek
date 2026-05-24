import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

import OptionContextCard from './OptionContextCard'
import type { AssetOut } from '../lib/api'

function makeAsset(overrides: Partial<AssetOut> = {}): AssetOut {
  return {
    id: 'asset-1',
    workspace_id: 'ws-1',
    workspace_name: null,
    account_id: 'acc-1',
    account_name: 'Acc',
    financial_institution_id: 'fi-1',
    financial_institution_name: 'FI',
    asset_class: 'STOCK',
    country: 'BR',
    name: 'Test',
    ticker: 'TEST3',
    cnpj: null,
    currency: 'BRL',
    current_price: 100,
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

const underlying = makeAsset({
  id: 'itub4-id',
  ticker: 'ITUB4',
  asset_class: 'STOCK',
  current_price: 39.43,
})

const putOption = makeAsset({
  id: 'itubr364-id',
  ticker: 'ITUBR364',
  asset_class: 'OPTION',
  underlying_id: 'itub4-id',
  option_type: 'PUT',
  strike_price: 36.40,
  expiration_date: '2026-06-19',
  contract_size: 100,
})

const callOption = makeAsset({
  id: 'itube476-id',
  ticker: 'ITUBE476',
  asset_class: 'OPTION',
  underlying_id: 'itub4-id',
  option_type: 'CALL',
  strike_price: 47.50,
  expiration_date: '2026-06-19',
  contract_size: 100,
})

function renderCard(option: AssetOut, u: AssetOut = underlying) {
  return render(
    <MemoryRouter>
      <OptionContextCard option={option} underlying={u} now={new Date('2026-05-24T00:00:00Z')} />
    </MemoryRouter>,
  )
}

describe('OptionContextCard render gate', () => {
  it('returns null when asset_class is not OPTION', () => {
    const { container } = renderCard(makeAsset({ asset_class: 'STOCK' }))
    expect(container.firstChild).toBeNull()
  })

  it('returns null when underlying_id is missing', () => {
    const { container } = renderCard(
      makeAsset({ asset_class: 'OPTION', underlying_id: undefined as unknown as string }),
    )
    expect(container.firstChild).toBeNull()
  })

  it('renders when OPTION + underlying_id set', () => {
    renderCard(putOption)
    expect(screen.getByText('Ativo subjacente')).toBeInTheDocument()
  })
})

describe('OptionContextCard link target', () => {
  it('links the underlying ticker to /assets/{underlyingId}', () => {
    renderCard(putOption)
    const links = screen.getAllByRole('link')
    // Header ticker link + footer "Ver X →" link both go to underlying
    expect(links.length).toBeGreaterThanOrEqual(2)
    for (const a of links) {
      expect(a.getAttribute('href')).toBe('/assets/itub4-id')
    }
  })
})

describe('OptionContextCard ITM/OTM correctness', () => {
  it('PUT with price below strike is ITM', () => {
    renderCard(putOption, makeAsset({ id: 'itub4-id', ticker: 'ITUB4', current_price: 35 }))
    expect(screen.getByTestId('itm-badge').textContent).toBe('ITM')
  })

  it('PUT with price above strike is OTM', () => {
    renderCard(putOption, makeAsset({ id: 'itub4-id', ticker: 'ITUB4', current_price: 39.43 }))
    expect(screen.getByTestId('itm-badge').textContent).toBe('OTM')
  })

  it('CALL with price above strike is ITM', () => {
    renderCard(callOption, makeAsset({ id: 'itub4-id', ticker: 'ITUB4', current_price: 48 }))
    expect(screen.getByTestId('itm-badge').textContent).toBe('ITM')
  })

  it('CALL with price below strike is OTM', () => {
    renderCard(callOption, makeAsset({ id: 'itub4-id', ticker: 'ITUB4', current_price: 39.43 }))
    expect(screen.getByTestId('itm-badge').textContent).toBe('OTM')
  })
})
