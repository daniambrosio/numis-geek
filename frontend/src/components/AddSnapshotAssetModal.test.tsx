/* Task 49-B — smoke + shape tests para AddSnapshotAssetModal.
 *
 * Renderiza o modal com backend response REAL (AssetOut[] completo,
 * api.ts:210) e valida:
 *  - Dropdown lista apenas assets ativos NÃO presentes em `existingAssetIds`
 *  - Busca por ticker filtra as opções
 *  - Submit chama api.addSnapshotItem(snapshot_id, asset_id)
 *  - ESC fecha
 *
 * IMPORTANTE: o brief pedia "qty=5 clampa pra 1 quando FUND". O modal atual
 * NÃO expõe campo de qty; ele apenas escolhe o asset e o backend calcula a
 * quantidade pela posição corrente. Documentando o comportamento efetivo.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import AddSnapshotAssetModal from './AddSnapshotAssetModal'
import { api, type AssetOut, type SnapshotItemOut } from '../lib/api'

function makeAsset(over: Partial<AssetOut> = {}): AssetOut {
  return {
    id: 'a-petr',
    workspace_id: 'ws-1',
    workspace_name: null,
    account_id: 'acc-1',
    account_name: 'XP',
    financial_institution_id: 'fi-1',
    financial_institution_name: 'XP',
    asset_class: 'STOCK',
    country: 'BR',
    name: 'Petrobras',
    ticker: 'PETR4',
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
    ...over,
  } as AssetOut
}

function makeItem(over: Partial<SnapshotItemOut> = {}): SnapshotItemOut {
  return {
    id: 'item-new',
    asset_id: 'a-aapl',
    quantity: '10',
    unit_price: '200.00',
    market_value_native: '2000.00',
    market_value_brl: '10200.00',
    market_value_usd: '2000.00',
    average_cost_brl: '180.00',
    total_invested_brl: '9200.00',
    updated_at: '2026-05-31T23:59:59Z',
    ...over,
  }
}

beforeEach(() => {
  vi.restoreAllMocks()
})

describe('AddSnapshotAssetModal', () => {
  it('dropdown filtra assets já presentes em existingAssetIds (dedup)', () => {
    const assets = [
      makeAsset({ id: 'a-petr', ticker: 'PETR4', name: 'Petrobras' }),
      makeAsset({ id: 'a-aapl', ticker: 'AAPL', name: 'Apple Inc' }),
      makeAsset({ id: 'a-fund', ticker: null, name: 'BB Ações Multi', asset_class: 'FUND' }),
    ]
    // Snapshot já tem PETR4 → só AAPL e o fundo devem aparecer.
    render(
      <AddSnapshotAssetModal
        snapshotId="snap-1"
        existingAssetIds={new Set(['a-petr'])}
        assets={assets}
        onAdded={() => {}} onClose={() => {}}
      />,
    )
    const select = screen.getByTestId('add-snapshot-asset-select') as HTMLSelectElement
    const options = Array.from(select.options).map(o => o.textContent)
    expect(options.some(o => o?.includes('PETR4'))).toBe(false)
    expect(options.some(o => o?.includes('AAPL'))).toBe(true)
    expect(options.some(o => o?.includes('BB Ações Multi'))).toBe(true)
    // Total de opções não-placeholder = 2 disponíveis (PETR4 filtrado).
    expect(select.options.length).toBe(2)
    // Task 57 fix (2026-07-29): plural correto ("disponíveis"), sem "disponívelis".
    expect(screen.getByText(/Ativo \(2 disponíveis\)/)).toBeInTheDocument()
  })

  it('dropdown ignora is_active=false', () => {
    render(
      <AddSnapshotAssetModal
        snapshotId="snap-1"
        existingAssetIds={new Set()}
        assets={[
          makeAsset({ id: 'a-petr', ticker: 'PETR4', is_active: true }),
          makeAsset({ id: 'a-old', ticker: 'OLDX3', name: 'Empresa X', is_active: false }),
        ]}
        onAdded={() => {}} onClose={() => {}}
      />,
    )
    const select = screen.getByTestId('add-snapshot-asset-select') as HTMLSelectElement
    const options = Array.from(select.options).map(o => o.value)
    expect(options).toContain('a-petr')
    expect(options).not.toContain('a-old')
  })

  it('busca por ticker filtra opções em tempo real', async () => {
    const user = userEvent.setup()
    render(
      <AddSnapshotAssetModal
        snapshotId="snap-1"
        existingAssetIds={new Set()}
        assets={[
          makeAsset({ id: 'a-petr', ticker: 'PETR4', name: 'Petrobras' }),
          makeAsset({ id: 'a-aapl', ticker: 'AAPL', name: 'Apple' }),
        ]}
        onAdded={() => {}} onClose={() => {}}
      />,
    )
    const search = screen.getByTestId('add-snapshot-asset-search')
    await user.type(search, 'AAPL')
    const select = screen.getByTestId('add-snapshot-asset-select') as HTMLSelectElement
    const options = Array.from(select.options).map(o => o.value)
    expect(options).toEqual(['a-aapl'])
    // Contador cai pra 1 → só um item no select (não asseramos o texto
    // pra evitar collision com ancestrais que também contêm "1 disponível").
    expect(select.options.length).toBe(1)
  })

  it('submit chama api.addSnapshotItem(snapshot_id, asset_id) + onAdded com o item', async () => {
    const item = makeItem()
    const spy = vi.spyOn(api, 'addSnapshotItem').mockResolvedValue(item)
    const onAdded = vi.fn()
    const user = userEvent.setup()

    render(
      <AddSnapshotAssetModal
        snapshotId="snap-1"
        existingAssetIds={new Set()}
        assets={[
          makeAsset({ id: 'a-aapl', ticker: 'AAPL', name: 'Apple' }),
          makeAsset({ id: 'a-petr', ticker: 'PETR4', name: 'Petrobras' }),
        ]}
        onAdded={onAdded} onClose={() => {}}
      />,
    )
    // Ordem alfabética por ticker → AAPL primeiro (picked default).
    await user.click(screen.getByTestId('add-snapshot-asset-submit'))
    await waitFor(() => expect(spy).toHaveBeenCalledWith('snap-1', 'a-aapl'))
    expect(onAdded).toHaveBeenCalledWith(item)
  })

  it('assets=[] → apresenta "Nenhum ativo disponível" e submit desabilitado', () => {
    render(
      <AddSnapshotAssetModal
        snapshotId="snap-1"
        existingAssetIds={new Set()}
        assets={[]}
        onAdded={() => {}} onClose={() => {}}
      />,
    )
    expect(screen.getByText('Nenhum ativo disponível')).toBeInTheDocument()
    expect(screen.getByTestId('add-snapshot-asset-submit')).toBeDisabled()
  })

  it('ESC fecha o modal', async () => {
    const onClose = vi.fn()
    const user = userEvent.setup()
    render(
      <AddSnapshotAssetModal
        snapshotId="snap-1"
        existingAssetIds={new Set()}
        assets={[makeAsset()]}
        onAdded={() => {}} onClose={onClose}
      />,
    )
    await user.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalled()
  })
})
