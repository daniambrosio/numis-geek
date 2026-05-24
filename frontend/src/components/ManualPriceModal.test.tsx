import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import ManualPriceModal from './ManualPriceModal'
import { api, type AssetOut, type ManualPriceOut } from '../lib/api'

function makeAsset(overrides: Partial<AssetOut> = {}): AssetOut {
  return {
    id: 'casa-1',
    workspace_id: 'ws-1',
    workspace_name: null,
    account_id: 'acc-1',
    account_name: 'Patrimônio',
    financial_institution_id: 'fi-1',
    financial_institution_name: 'Particular',
    asset_class: 'REAL_ESTATE',
    country: 'BR',
    name: 'Casa Curitiba',
    ticker: null,
    cnpj: null,
    currency: 'BRL',
    current_price: 820000,
    price_updated_at: '2026-04-01T00:00:00Z',
    price_source: 'MANUAL',
    price_tier: 'STALE',
    notes: null,
    external_id: null,
    external_source: null,
    is_active: true,
    created_at: '2026-01-01',
    updated_at: '2026-04-01',
    details: null,
    ...overrides,
  } as AssetOut
}

const successResp: ManualPriceOut = {
  price: 850000,
  price_updated_at: '2026-05-24T18:00:00Z',
  price_source: 'MANUAL',
}

beforeEach(() => {
  vi.restoreAllMocks()
})

describe('ManualPriceModal', () => {
  it('renders with current price and asset label', () => {
    render(<ManualPriceModal asset={makeAsset()} onClose={() => {}} onSaved={() => {}} />)
    expect(screen.getByText(/Editar preço.*Casa Curitiba/)).toBeInTheDocument()
    expect(screen.getByLabelText('Novo preço')).toHaveValue('820000')
  })

  it('rejects empty input with an inline error', async () => {
    const user = userEvent.setup()
    render(<ManualPriceModal asset={makeAsset({ current_price: null })} onClose={() => {}} onSaved={() => {}} />)
    await user.click(screen.getByRole('button', { name: /Salvar/ }))
    expect(screen.getByText(/Informe um número/)).toBeInTheDocument()
  })

  it('rejects negative input', async () => {
    const user = userEvent.setup()
    render(<ManualPriceModal asset={makeAsset()} onClose={() => {}} onSaved={() => {}} />)
    const input = screen.getByLabelText('Novo preço')
    await user.clear(input)
    await user.type(input, '-100')
    await user.click(screen.getByRole('button', { name: /Salvar/ }))
    expect(screen.getByText(/Informe um número/)).toBeInTheDocument()
  })

  it('calls api.updateAssetPrice on submit and reports result via onSaved', async () => {
    const spy = vi.spyOn(api, 'updateAssetPrice').mockResolvedValue(successResp)
    const onSaved = vi.fn()
    const user = userEvent.setup()

    render(<ManualPriceModal asset={makeAsset()} onClose={() => {}} onSaved={onSaved} />)
    const input = screen.getByLabelText('Novo preço')
    await user.clear(input)
    await user.type(input, '850000')
    await user.click(screen.getByRole('button', { name: /Salvar/ }))

    await waitFor(() => expect(spy).toHaveBeenCalledWith('casa-1', '850000.00', undefined))
    expect(onSaved).toHaveBeenCalledWith(successResp)
  })

  it('passes the note when filled in', async () => {
    const spy = vi.spyOn(api, 'updateAssetPrice').mockResolvedValue(successResp)
    const user = userEvent.setup()

    render(<ManualPriceModal asset={makeAsset()} onClose={() => {}} onSaved={() => {}} />)
    const input = screen.getByLabelText('Novo preço')
    await user.clear(input); await user.type(input, '850000')
    await user.type(screen.getByPlaceholderText(/Avaliação anual/), 'Marketplace appraisal')
    await user.click(screen.getByRole('button', { name: /Salvar/ }))

    await waitFor(() => expect(spy).toHaveBeenCalledWith('casa-1', '850000.00', 'Marketplace appraisal'))
  })

  it('accepts brazilian decimal format (comma)', async () => {
    const spy = vi.spyOn(api, 'updateAssetPrice').mockResolvedValue(successResp)
    const user = userEvent.setup()
    render(<ManualPriceModal asset={makeAsset()} onClose={() => {}} onSaved={() => {}} />)
    const input = screen.getByLabelText('Novo preço')
    await user.clear(input); await user.type(input, '850000,55')
    await user.click(screen.getByRole('button', { name: /Salvar/ }))
    await waitFor(() => expect(spy).toHaveBeenCalledWith('casa-1', '850000.55', undefined))
  })

  it('ESC closes the modal', async () => {
    const onClose = vi.fn()
    const user = userEvent.setup()
    render(<ManualPriceModal asset={makeAsset()} onClose={onClose} onSaved={() => {}} />)
    await user.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalled()
  })

  it('Cancel button closes the modal', async () => {
    const onClose = vi.fn()
    const user = userEvent.setup()
    render(<ManualPriceModal asset={makeAsset()} onClose={onClose} onSaved={() => {}} />)
    await user.click(screen.getByRole('button', { name: /Cancelar/ }))
    expect(onClose).toHaveBeenCalled()
  })

  it('⌘↵ submits', async () => {
    const spy = vi.spyOn(api, 'updateAssetPrice').mockResolvedValue(successResp)
    const user = userEvent.setup()
    render(<ManualPriceModal asset={makeAsset()} onClose={() => {}} onSaved={() => {}} />)
    await user.keyboard('{Meta>}{Enter}{/Meta}')
    await waitFor(() => expect(spy).toHaveBeenCalled())
  })
})
