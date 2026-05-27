import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'

import NotesAttachmentsField, {
  type AttachmentDraft, type PersistedAttachment,
} from './NotesAttachmentsField'

beforeEach(() => {
  // jsdom doesn't implement URL.createObjectURL.
  globalThis.URL.createObjectURL = vi.fn(() => 'blob:test')
  globalThis.URL.revokeObjectURL = vi.fn()
})

function Harness({ initialPersisted, onRemovePersisted }: {
  initialPersisted?: PersistedAttachment[]
  onRemovePersisted?: (id: string) => void
} = {}) {
  const [notes, setNotes] = useState('')
  const [files, setFiles] = useState<AttachmentDraft[]>([])
  return (
    <NotesAttachmentsField
      notes={notes}
      onNotesChange={setNotes}
      files={files}
      onFilesChange={setFiles}
      persisted={initialPersisted}
      onRemovePersisted={onRemovePersisted}
    />
  )
}

describe('NotesAttachmentsField', () => {
  it('accepts a valid PNG via the hidden file picker', async () => {
    render(<Harness />)
    const input = screen.getByTestId('notes-attachments-input') as HTMLInputElement
    const png = new File(['fake-png'], 'shot.png', { type: 'image/png' })

    await userEvent.upload(input, png)

    const drafts = screen.getAllByTestId('notes-attachments-draft')
    expect(drafts).toHaveLength(1)
    expect(drafts[0]).toHaveTextContent('shot.png')
    expect(drafts[0]).toHaveTextContent('novo')
  })

  it('rejects an unsupported MIME and shows an inline error', () => {
    // Bypass the input's `accept` filter via a drop event so we can verify
    // the component's own validation rather than the browser's pre-filter.
    render(<Harness />)
    const exe = new File(['x'], 'virus.exe', { type: 'application/x-msdownload' })

    fireEvent.drop(screen.getByTestId('notes-attachments-dropzone'), {
      dataTransfer: { files: [exe] },
    })

    expect(screen.queryAllByTestId('notes-attachments-draft')).toHaveLength(0)
    expect(screen.getByTestId('notes-attachments-error')).toHaveTextContent('não permitido')
  })

  it('rejects oversized files (>10 MB) and shows an inline error', async () => {
    render(<Harness />)
    const input = screen.getByTestId('notes-attachments-input') as HTMLInputElement
    const big = new File([new Uint8Array(11 * 1024 * 1024)], 'big.pdf', { type: 'application/pdf' })

    await userEvent.upload(input, big)

    expect(screen.queryAllByTestId('notes-attachments-draft')).toHaveLength(0)
    expect(screen.getByTestId('notes-attachments-error')).toHaveTextContent('excede o limite')
  })

  it('accepts a pasted PDF via the textarea', () => {
    render(<Harness />)
    const ta = screen.getByPlaceholderText(/tese, motivo/)
    const pdf = new File(['pdf'], 'note.pdf', { type: 'application/pdf' })

    fireEvent.paste(ta, { clipboardData: { files: [pdf] } })

    const drafts = screen.getAllByTestId('notes-attachments-draft')
    expect(drafts).toHaveLength(1)
    expect(drafts[0]).toHaveTextContent('note.pdf')
  })

  it('removes a draft when the X button is clicked', async () => {
    render(<Harness />)
    const input = screen.getByTestId('notes-attachments-input') as HTMLInputElement
    await userEvent.upload(input, new File(['x'], 'a.png', { type: 'image/png' }))
    expect(screen.getAllByTestId('notes-attachments-draft')).toHaveLength(1)

    await userEvent.click(screen.getByTitle('Descartar'))  // drafts get the "Descartar" tooltip via the badge branch
    expect(screen.queryAllByTestId('notes-attachments-draft')).toHaveLength(0)
  })

  it('shows persisted attachments above drafts and emits onRemovePersisted', async () => {
    const onRemove = vi.fn()
    render(<Harness
      initialPersisted={[{
        id: 'att-1', filename: 'nota_corretagem.pdf',
        size_bytes: 12345, mime_type: 'application/pdf', kind: 'pdf',
      }]}
      onRemovePersisted={onRemove}
    />)

    const persisted = screen.getByTestId('notes-attachments-persisted')
    expect(persisted).toHaveTextContent('nota_corretagem.pdf')

    await userEvent.click(screen.getByTitle('Remover'))
    expect(onRemove).toHaveBeenCalledWith('att-1')
  })
})
