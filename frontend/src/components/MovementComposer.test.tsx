import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import MovementComposer from './MovementComposer'
import { type AssetOut } from '../lib/api'

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

describe('MovementComposer — 6 tiles + opção via dropdown (2026-06-24 v2)', () => {
  it('mostra os 6 tiles semânticos em grid 3×2 (zero tile de opção)', () => {
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
    expect(within(grid).getByText('Venda')).toBeInTheDocument()
    expect(within(grid).getByText('Bonificação')).toBeInTheDocument()
    expect(within(grid).getByText('Subscrição')).toBeInTheDocument()
    expect(within(grid).getByText('Come-cotas')).toBeInTheDocument()
    expect(within(grid).getByText('Resgate Total')).toBeInTheDocument()
    // Tiles de opção foram REMOVIDOS — opção agora é variante via dropdown.
    expect(within(grid).queryByText('Vender opção')).toBeNull()
    expect(within(grid).queryByText('Vencer (pó)')).toBeNull()
    expect(within(grid).queryByText('Exercer')).toBeNull()
  })

  it('dropdown de Ativo tem "+ Nova opção…" quando tile é Compra/Venda', () => {
    render(
      <MovementComposer
        assets={[makeAsset()]}
        onSave={async () => {}}
        onClose={() => {}}
      />,
    )
    const picker = screen.getByTestId('movement-asset-picker') as HTMLSelectElement
    expect(within(picker).getByText(/Nova opção/)).toBeInTheDocument()
  })

  it('dropdown de Ativo NÃO tem "+ Nova opção…" pra Bonificação', async () => {
    render(
      <MovementComposer
        assets={[makeAsset()]}
        onSave={async () => {}}
        onClose={() => {}}
      />,
    )
    await userEvent.click(screen.getByText('Bonificação'))
    const picker = screen.getByTestId('movement-asset-picker') as HTMLSelectElement
    expect(within(picker).queryByText(/Nova opção/)).toBeNull()
  })

  it('initialNewOption=SELL pré-seleciona Venda + "+ Nova opção" e mostra form inline', () => {
    render(
      <MovementComposer
        assets={[makeAsset()]}
        initialNewOption="SELL"
        onSave={async () => {}}
        onClose={() => {}}
      />,
    )
    // Venda destacado
    const grid = screen.getByTestId('movement-type-grid')
    const tile = within(grid).getByText('Venda').closest('button')
    expect(tile?.className).toMatch(/indigo-500/)
    // Form inline da opção visível
    expect(screen.getByTestId('option-ticker-input')).toBeInTheDocument()
    expect(screen.getByTestId('option-strike-input')).toBeInTheDocument()
    expect(screen.getByTestId('option-expiration-input')).toBeInTheDocument()
    expect(screen.getByTestId('option-underlying-picker')).toBeInTheDocument()
  })

  it('quando ativo é OPTION existente, infere fechamento (mostra banner)', () => {
    const opt = makeAsset({ id: 'a-opt', ticker: 'ITUBR364', asset_class: 'OPTION' })
    render(
      <MovementComposer
        assets={[opt]}
        preselectedAsset={opt}
        onSave={async () => {}}
        onClose={() => {}}
      />,
    )
    // Banner inferido aparece (tile=BUY default, asset=OPTION → BUY_TO_CLOSE)
    expect(screen.getByText(/Vai encerrar a posição/)).toBeInTheDocument()
    expect(screen.getByText(/recompra de opção vendida/)).toBeInTheDocument()
  })
})
