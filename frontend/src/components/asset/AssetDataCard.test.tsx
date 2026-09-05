import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import AssetDataCard, { buildPatch } from './AssetDataCard'
import { api, type AccountOut, type AssetOut, type FinancialInstitutionOut } from '../../lib/api'

const asset: AssetOut = {
  id: 'a1', workspace_id: 'ws1', workspace_name: null,
  account_id: 'acc-xp', account_name: 'XP Inv',
  financial_institution_id: 'fi-xp', financial_institution_name: 'XP',
  asset_class: 'STOCK', country: 'BR', name: 'Itaú PN', ticker: 'ITUB4', cnpj: null,
  currency: 'BRL', current_price: 32, price_updated_at: null, price_source: null, price_tier: 'UNKNOWN',
  notes: null, external_id: null, external_source: null, is_active: true, details: null,
  created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-02T00:00:00Z',
}
const fis: FinancialInstitutionOut[] = [
  { id: 'fi-xp', short_name: 'XP', long_name: 'XP', country: 'BR', logo_slug: 'xp', brand_color: null, has_logo: false, is_active: true, created_at: '', updated_at: '' },
  { id: 'fi-btg', short_name: 'BTG', long_name: 'BTG', country: 'BR', logo_slug: 'btg', brand_color: null, has_logo: false, is_active: true, created_at: '', updated_at: '' },
]
const accounts: AccountOut[] = [
  { id: 'acc-xp', workspace_id: 'ws1', financial_institution_id: 'fi-xp', financial_institution_name: 'XP', name: 'XP Inv', account_type: 'investment', currency: 'BRL', opening_balance: 0, account_info: null, is_active: true, created_at: '' },
  { id: 'acc-btg', workspace_id: 'ws1', financial_institution_id: 'fi-btg', financial_institution_name: 'BTG', name: 'BTG Inv', account_type: 'investment', currency: 'BRL', opening_balance: 0, account_info: null, is_active: true, created_at: '' },
]

function mount(over: Partial<React.ComponentProps<typeof AssetDataCard>> = {}) {
  const props = {
    asset, fi: fis[0], account: accounts[0], institutions: fis, canDeactivate: true,
    costBRL: 1000, receivedBRL: 50, movementsCount: 3, lastMovementDate: '2026-08-01',
    onSaved: vi.fn(), onError: vi.fn(), onEditDetails: vi.fn(), onDeactivate: vi.fn(),
    ...over,
  }
  render(<AssetDataCard {...props} />)
  return props
}

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(api, 'listAccounts').mockResolvedValue(accounts)
})

describe('AssetDataCard (spec 81)', () => {
  it('buildPatch envia só o que mudou', () => {
    const d = { name: 'Itaú PN', ticker: 'ITUB4', cnpj: '', asset_class: 'STOCK' as const, country: 'BR', currency: 'BRL' as const, fiId: 'fi-xp' }
    expect(buildPatch(asset, d, 'acc-xp')).toEqual({})
    expect(buildPatch(asset, { ...d, name: 'Itaú Unibanco PN' }, 'acc-xp')).toEqual({ name: 'Itaú Unibanco PN' })
    expect(buildPatch(asset, { ...d, fiId: 'fi-btg' }, 'acc-btg')).toEqual({ account_id: 'acc-btg' })
    expect(buildPatch(asset, { ...d, ticker: '' , asset_class: 'FUND', cnpj: '12.345' }, 'acc-xp'))
      .toEqual({ ticker: null, cnpj: '12.345', asset_class: 'FUND' })
  })

  it('Salvar chama patchAsset com o campo alterado e volta pro modo leitura', async () => {
    const patch = vi.spyOn(api, 'patchAsset').mockResolvedValue({ ...asset, name: 'Itaú Unibanco PN' })
    const props = mount()
    fireEvent.click(screen.getByTestId('asset-data-edit'))
    const name = screen.getByTestId('asset-data-name')
    fireEvent.change(name, { target: { value: 'Itaú Unibanco PN' } })
    expect(screen.getByTestId('asset-data-save')).not.toBeDisabled()
    fireEvent.click(screen.getByTestId('asset-data-save'))
    await waitFor(() => expect(props.onSaved).toHaveBeenCalled())
    expect(patch).toHaveBeenCalledWith('a1', { name: 'Itaú Unibanco PN' })
    expect(screen.queryByTestId('asset-data-form')).toBeNull()
  })

  it('Salvar fica desabilitado sem mudança e com ticker vazio em ação', () => {
    mount()
    fireEvent.click(screen.getByTestId('asset-data-edit'))
    expect(screen.getByTestId('asset-data-save')).toBeDisabled()
    fireEvent.change(screen.getByTestId('asset-data-ticker'), { target: { value: '' } })
    expect(screen.getByTestId('asset-data-save')).toBeDisabled()
    expect(screen.getByTestId('asset-data-problems')).toHaveTextContent('ticker obrigatório')
  })

  it('Cancelar descarta o rascunho', () => {
    mount()
    fireEvent.click(screen.getByTestId('asset-data-edit'))
    fireEvent.change(screen.getByTestId('asset-data-name'), { target: { value: 'Outro' } })
    fireEvent.click(screen.getByText('Cancelar'))
    expect(screen.queryByTestId('asset-data-form')).toBeNull()
    expect(screen.getByText('Itaú PN')).toBeInTheDocument()
  })

  it('erro de API vira onError e o botão reabilita', async () => {
    vi.spyOn(api, 'patchAsset').mockRejectedValue(new Error('ticker já existe'))
    const props = mount()
    fireEvent.click(screen.getByTestId('asset-data-edit'))
    fireEvent.change(screen.getByTestId('asset-data-name'), { target: { value: 'X' } })
    fireEvent.click(screen.getByTestId('asset-data-save'))
    await waitFor(() => expect(props.onError).toHaveBeenCalledWith('ticker já existe'))
    expect(screen.getByTestId('asset-data-save')).not.toBeDisabled()
    expect(screen.getByTestId('asset-data-form')).toBeInTheDocument()
  })

  it('trocar custodiante resolve a conta de investimento da FI', async () => {
    const patch = vi.spyOn(api, 'patchAsset').mockResolvedValue({ ...asset, account_id: 'acc-btg', financial_institution_id: 'fi-btg' })
    mount()
    fireEvent.click(screen.getByTestId('asset-data-edit'))
    fireEvent.change(screen.getByTestId('asset-data-fi'), { target: { value: 'fi-btg' } })
    await waitFor(() => expect(screen.getByText('conta: BTG Inv')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('asset-data-save'))
    await waitFor(() => expect(patch).toHaveBeenCalledWith('a1', { account_id: 'acc-btg' }))
  })

  it('Zerar ativo só aparece com permissão e chama onDeactivate', () => {
    const props = mount()
    fireEvent.click(screen.getByTestId('asset-data-deactivate'))
    expect(props.onDeactivate).toHaveBeenCalled()
  })
})
