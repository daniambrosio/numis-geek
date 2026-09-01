/* Logo por instituição (fix 2026-09-01) — antes o logo vinha de um mapa
 * slug→domínio hardcoded, então instituição nova (Nubank, Nomad) nascia sem
 * logo e sem forma de editar. Cobre a ponta do fluxo que o backend não vê:
 * escolher arquivo no modal, remover, e a validação client-side de formato. */
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'

import SysAdminFinancialInstitutions from './FinancialInstitutions'
import { resetFiLogos } from '../../lib/fiLogos'
import {
  api,
  type FinancialInstitutionLogoOut,
  type FinancialInstitutionOut,
  type UserOut,
} from '../../lib/api'

const sysadmin: UserOut = {
  id: 'u1', email: 'sys@x.com', name: 'Sys', role: 'sysadmin',
  workspace_id: null, workspace_name: null, is_active: true,
  created_at: '2026-01-01T00:00:00Z',
}

function fi(over: Partial<FinancialInstitutionOut> = {}): FinancialInstitutionOut {
  return {
    id: 'fi-nu', long_name: 'Nubank S.A.', short_name: 'Nubank',
    logo_slug: 'nubank', brand_color: null, has_logo: false,
    country: 'BR', is_active: true,
    created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
    ...over,
  }
}

function logoRow(over: Partial<FinancialInstitutionLogoOut> = {}): FinancialInstitutionLogoOut {
  return {
    id: 'fi-nu', logo_slug: 'nubank', short_name: 'Nubank',
    brand_color: '#820ad1', data_url: null,
    ...over,
  }
}

function mockDeps(items: FinancialInstitutionOut[], logos: FinancialInstitutionLogoOut[]) {
  vi.spyOn(api, 'me').mockResolvedValue(sysadmin)
  vi.spyOn(api, 'listFinancialInstitutions').mockResolvedValue(items)
  vi.spyOn(api, 'listFinancialInstitutionLogos').mockResolvedValue(logos)
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/sysadmin/financial-institutions']}>
      <SysAdminFinancialInstitutions />
    </MemoryRouter>,
  )
}

async function openEditModal() {
  await userEvent.click(await screen.findByText('Editar'))
  await screen.findByText('Editar Instituição')
}

describe('sysadmin · logo da instituição financeira', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    resetFiLogos()
    // O cache de logos só busca quando há token — o app real sempre tem.
    localStorage.setItem('token', 'fake-token')
    // jsdom não implementa object URLs; a prévia do arquivo escolhido usa.
    URL.createObjectURL = vi.fn(() => 'blob:preview')
    URL.revokeObjectURL = vi.fn()
  })

  afterEach(() => {
    localStorage.removeItem('token')
    resetFiLogos()
  })

  it('renderiza o logo enviado em vez das iniciais', async () => {
    mockDeps([fi({ has_logo: true })], [logoRow({ data_url: 'data:image/png;base64,AAA' })])
    renderPage()

    const img = await screen.findByAltText('Nubank')
    expect(img).toHaveAttribute('src', 'data:image/png;base64,AAA')
  })

  it('sem logo, cai nas iniciais sobre a cor de marca cadastrada', async () => {
    mockDeps([fi()], [logoRow({ brand_color: '#820ad1' })])
    renderPage()

    await waitFor(() => expect(screen.getByTitle('Nubank')).toBeInTheDocument())
    const tile = screen.getByTitle('Nubank')
    expect(tile).toHaveTextContent('NU')
    expect(tile).toHaveStyle({ background: '#820ad1' })
  })

  it('escolher arquivo e salvar envia o logo', async () => {
    mockDeps([fi()], [logoRow()])
    const update = vi.spyOn(api, 'updateFinancialInstitution').mockResolvedValue(fi())
    const upload = vi.spyOn(api, 'uploadFinancialInstitutionLogo')
      .mockResolvedValue(fi({ has_logo: true }))
    renderPage()
    await openEditModal()

    const file = new File(['png-bytes'], 'nubank.png', { type: 'image/png' })
    await userEvent.upload(screen.getByLabelText('Arquivo do logo'), file)
    await userEvent.click(screen.getByText('Salvar'))

    await waitFor(() => expect(upload).toHaveBeenCalledWith('fi-nu', file))
    expect(update).toHaveBeenCalled()
  })

  it('remover logo chama o delete ao salvar', async () => {
    mockDeps([fi({ has_logo: true })], [logoRow({ data_url: 'data:image/png;base64,AAA' })])
    vi.spyOn(api, 'updateFinancialInstitution').mockResolvedValue(fi({ has_logo: true }))
    const del = vi.spyOn(api, 'deleteFinancialInstitutionLogo').mockResolvedValue(fi())
    renderPage()
    await openEditModal()

    await userEvent.click(screen.getByText('Remover'))
    await userEvent.click(screen.getByText('Salvar'))

    await waitFor(() => expect(del).toHaveBeenCalledWith('fi-nu'))
  })

  it('rejeita formato não suportado sem chamar a API', async () => {
    mockDeps([fi()], [logoRow()])
    const upload = vi.spyOn(api, 'uploadFinancialInstitutionLogo')
      .mockResolvedValue(fi({ has_logo: true }))
    renderPage()
    await openEditModal()

    // fireEvent em vez de userEvent.upload: o `accept` do input já filtraria o
    // arquivo antes do handler, e o que se quer testar aqui é a guarda que
    // pega quem escolhe "todos os arquivos" no diálogo do SO.
    const bad = new File(['nope'], 'logo.txt', { type: 'text/plain' })
    fireEvent.change(screen.getByLabelText('Arquivo do logo'), { target: { files: [bad] } })

    expect(await screen.findByText(/Formato não suportado/)).toBeInTheDocument()
    expect(upload).not.toHaveBeenCalled()
  })
})
