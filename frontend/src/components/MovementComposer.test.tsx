import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import MovementComposer from './MovementComposer'
import { api, type AssetOut } from '../lib/api'

function makeAsset(overrides: Partial<AssetOut> = {}): AssetOut {
  return {
    id: 'a-stock',
    workspace_id: 'ws-1',
    workspace_name: null,
    account_id: 'acc-1',
    account_name: 'XP',
    financial_institution_id: 'fi-1',
    financial_institution_name: 'XP',
    asset_class: 'STOCK',
    country: 'BR',
    name: 'Itau',
    ticker: 'ITUB4',
    cnpj: null,
    currency: 'BRL',
    current_price: 38,
    price_updated_at: null,
    price_source: null,
    price_tier: 'FRESH',
    notes: null,
    external_id: null,
    external_source: null,
    is_active: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    details: null,
    ...overrides,
  }
}

beforeEach(() => {
  vi.restoreAllMocks()
  globalThis.URL.createObjectURL = vi.fn(() => 'blob:test')
  globalThis.URL.revokeObjectURL = vi.fn()
})

describe('MovementComposer dynamic type picker (Spec 36 §3)', () => {
  it('shows the 6 normal types in a 3-col grid for a STOCK asset', () => {
    render(
      <MovementComposer
        assets={[makeAsset()]}
        onSave={async () => {}}
        onClose={() => {}}
      />,
    )
    const grid = screen.getByTestId('movement-type-grid')
    expect(grid.className).toMatch(/grid-cols-3/)
    expect(within(grid).getByText('Compra')).toBeInTheDocument()
    expect(within(grid).getByText('Bonificação')).toBeInTheDocument()
    expect(within(grid).queryByText('Vender / Encerrar')).toBeNull()
  })

  it('switches to the 4 lifecycle types in a 2-col grid for an OPTION asset', async () => {
    const opt = makeAsset({ id: 'a-opt', ticker: 'ITUBR364', asset_class: 'OPTION', name: 'ITUB4 06 PUT 34' })
    render(
      <MovementComposer
        assets={[opt]}
        onSave={async () => {}}
        onClose={() => {}}
      />,
    )
    const grid = screen.getByTestId('movement-type-grid')
    expect(grid.className).toMatch(/grid-cols-2/)
    expect(within(grid).getByText('Vender / Encerrar')).toBeInTheDocument()
    expect(within(grid).getByText('Comprar / Encerrar')).toBeInTheDocument()
    expect(within(grid).getByText('Exercida')).toBeInTheDocument()
    expect(within(grid).getByText('Virou pó')).toBeInTheDocument()
    expect(within(grid).queryByText('Compra')).toBeNull()
  })

  it('EXPIRED submits to api.expireOption and skips the standard movements POST', async () => {
    const opt = makeAsset({ id: 'a-opt', ticker: 'ITUBR364', asset_class: 'OPTION' })
    const expireSpy = vi.spyOn(api, 'expireOption').mockResolvedValue({
      id: 'a-opt', ticker: 'ITUBR364', name: 'foo',
      underlying_id: 'u', underlying_ticker: 'ITUB4',
      option_type: 'PUT', strike_price: 34, expiration_date: '2026-06-20',
      contract_size: 100, currency: 'BRL', is_active: false,
      account_id: 'acc-1', workspace_id: 'ws-1',
    })
    const onSave = vi.fn().mockResolvedValue(undefined)
    const onLifecycle = vi.fn().mockResolvedValue(undefined)

    render(
      <MovementComposer
        assets={[opt]}
        onSave={onSave}
        onOptionLifecycleSaved={onLifecycle}
        onClose={() => {}}
      />,
    )

    await userEvent.click(screen.getByText('Virou pó'))
    // EXPIRED requires no qty/price; the submit button should already be enabled.
    await userEvent.click(screen.getByRole('button', { name: /Salvar/ }))

    expect(expireSpy).toHaveBeenCalled()
    expect(onSave).not.toHaveBeenCalled()  // bypassed for lifecycle
    expect(onLifecycle).toHaveBeenCalled()
  })
})
