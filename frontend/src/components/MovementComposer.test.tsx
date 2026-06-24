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

describe('MovementComposer unified type picker (2026-06-24)', () => {
  it('mostra todos os 12 tipos em 3 grupos (Posição / Opções abrir / Opções encerrar)', () => {
    render(
      <MovementComposer
        assets={[makeAsset()]}
        onSave={async () => {}}
        onClose={() => {}}
      />,
    )
    const grid = screen.getByTestId('movement-type-grid')
    // Grupo Posição
    expect(within(grid).getByText('Compra')).toBeInTheDocument()
    expect(within(grid).getByText('Venda')).toBeInTheDocument()
    expect(within(grid).getByText('Bonificação')).toBeInTheDocument()
    expect(within(grid).getByText('Resgate Total')).toBeInTheDocument()
    // Grupo Opções · abrir
    expect(within(grid).getByText('Vender opção')).toBeInTheDocument()
    expect(within(grid).getByText('Comprar opção')).toBeInTheDocument()
    // Grupo Opções · encerrar
    expect(within(grid).getByText('Fechar venda')).toBeInTheDocument()
    expect(within(grid).getByText('Fechar compra')).toBeInTheDocument()
    expect(within(grid).getByText('Exercer')).toBeInTheDocument()
    expect(within(grid).getByText('Vencer (pó)')).toBeInTheDocument()
  })

  it('initialType pré-seleciona o tile (compose=option → Vender opção)', () => {
    render(
      <MovementComposer
        assets={[makeAsset()]}
        initialType="SELL_OPEN"
        onSave={async () => {}}
        onClose={() => {}}
      />,
    )
    const grid = screen.getByTestId('movement-type-grid')
    const tile = within(grid).getByText('Vender opção').closest('button')
    expect(tile).toHaveClass(/indigo-500/)
  })

  it('OPEN: mostra inputs inline (ticker/strike/vencimento) e esconde dropdown de Ativo', async () => {
    render(
      <MovementComposer
        assets={[makeAsset()]}
        initialType="SELL_OPEN"
        onSave={async () => {}}
        onClose={() => {}}
      />,
    )
    expect(screen.getByTestId('option-ticker-input')).toBeInTheDocument()
    expect(screen.getByTestId('option-strike-input')).toBeInTheDocument()
    expect(screen.getByTestId('option-expiration-input')).toBeInTheDocument()
    expect(screen.getByTestId('option-underlying-picker')).toBeInTheDocument()
  })

  it('Vencer (pó) → POST /options/{id}/expire e bypassa onSave', async () => {
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

    await userEvent.click(screen.getByText('Vencer (pó)'))
    await userEvent.click(screen.getByRole('button', { name: /Salvar/ }))

    expect(expireSpy).toHaveBeenCalled()
    expect(onSave).not.toHaveBeenCalled()
    expect(onLifecycle).toHaveBeenCalled()
  })
})
