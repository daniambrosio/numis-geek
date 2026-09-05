import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import BulkAttachmentManager from './BulkAttachmentManager'
import { api, type AttachmentOut } from '../lib/api'

// 2026-09-05 — regressão: anexo subido num bloco por FI sem clicar em
// "Extrair" sumia de todos os blocos após refresh, porque o filtro só
// aceitava anexos com extraction job. Agora o slot (FI + purpose) é
// persistido no upload e o filtro usa isso.

function att(over: Partial<AttachmentOut>): AttachmentOut {
  return {
    id: 'att-1', workspace_id: 'ws', source_type: 'snapshot', source_id: 'snap-1',
    kind: 'csv', filename: 'proventos-xp.xlsx', mime_type: 'text/csv', size_bytes: 100,
    uploaded_at: '2026-09-05T17:48:00Z', uploaded_by: null, is_active: true,
    ...over,
  }
}

beforeEach(() => {
  vi.restoreAllMocks()
  vi.spyOn(api, 'listSnapshotExtractions').mockResolvedValue([])
})

function mount(purpose: 'positions' | 'income', institutionId = 'fi-xp') {
  return render(
    <BulkAttachmentManager
      snapshotId="snap-1" pendencies={[]} onResolved={() => {}}
      institutionId={institutionId} purpose={purpose}
    />,
  )
}

describe('BulkAttachmentManager — slot persistido no anexo', () => {
  it('mostra anexo do slot mesmo sem extraction job (após refresh)', async () => {
    vi.spyOn(api, 'listSnapshotAttachments').mockResolvedValue([
      att({ institution_id: 'fi-xp', purpose: 'income' }),
    ])
    mount('income')
    await waitFor(() => expect(screen.getByTestId('attachment-row-att-1')).toBeInTheDocument())
    expect(screen.getByTestId('attachment-row-att-1')).toHaveTextContent('proventos-xp.xlsx')
  })

  it('não mostra anexo de outro purpose nem de outra FI', async () => {
    vi.spyOn(api, 'listSnapshotAttachments').mockResolvedValue([
      att({ id: 'att-inc', institution_id: 'fi-xp', purpose: 'income' }),
      att({ id: 'att-other-fi', institution_id: 'fi-btg', purpose: 'positions' }),
    ])
    mount('positions')
    await waitFor(() => expect(api.listSnapshotAttachments).toHaveBeenCalled())
    await waitFor(() => expect(screen.queryByText(/Carregando/)).toBeNull())
    expect(screen.queryByTestId('attachment-row-att-inc')).toBeNull()
    expect(screen.queryByTestId('attachment-row-att-other-fi')).toBeNull()
  })

  it('anexo antigo sem slot ainda aparece via extraction job da FI', async () => {
    vi.spyOn(api, 'listSnapshotAttachments').mockResolvedValue([
      att({ id: 'att-legacy', institution_id: null, purpose: null }),
    ])
    vi.spyOn(api, 'listSnapshotExtractions').mockResolvedValue([{
      id: 'job-1', attachment_id: 'att-legacy', status: 'CONFIRMED',
      source_hint: 'BROKER_INCOME', institution_id: 'fi-xp', institution_short_name: 'XP',
      created_at: '2026-09-01T00:00:00Z',
    } as never])
    mount('income')
    await waitFor(() => expect(screen.getByTestId('attachment-row-att-legacy')).toBeInTheDocument())
  })

  it('upload envia o slot (FI + purpose) junto com o arquivo', async () => {
    vi.spyOn(api, 'listSnapshotAttachments').mockResolvedValue([])
    const upload = vi.spyOn(api, 'uploadAttachment').mockResolvedValue(
      att({ id: 'att-new', institution_id: 'fi-xp', purpose: 'income' }),
    )
    const { container } = mount('income')
    await waitFor(() => expect(api.listSnapshotAttachments).toHaveBeenCalled())
    const input = container.querySelector('input[type="file"]') as HTMLInputElement
    const file = new File(['a,b'], 'extrato.csv', { type: 'text/csv' })
    fireEvent.change(input, { target: { files: [file] } })
    await waitFor(() => expect(upload).toHaveBeenCalled())
    expect(upload).toHaveBeenCalledWith(
      'snapshot', 'snap-1', expect.any(File),
      { institution_id: 'fi-xp', purpose: 'income' },
    )
  })
})
