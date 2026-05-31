import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

import BulkUploadZone from './BulkUploadZone'
import { api } from '../lib/api'

beforeEach(() => {
  vi.restoreAllMocks()
})

describe('BulkUploadZone', () => {
  it('shows the upload zone with instructions', () => {
    render(<BulkUploadZone snapshotId="snap-1" onJobReady={() => {}} />)
    expect(screen.getByText(/Carregar extrato/)).toBeInTheDocument()
    expect(screen.getByText(/cmd\+V/)).toBeInTheDocument()
  })

  it('cmd+V paste triggers uploadAttachment + createBulkExtract and calls onJobReady', async () => {
    vi.spyOn(api, 'uploadAttachment').mockResolvedValue({
      id: 'att-1', workspace_id: 'ws-1',
      source_type: 'snapshot', source_id: 'snap-1',
      kind: 'image', filename: 'pasted.png', mime_type: 'image/png',
      size_bytes: 100, uploaded_at: '', uploaded_by: null, is_active: true,
    })
    vi.spyOn(api, 'createBulkExtract').mockResolvedValue({
      id: 'job-1', status: 'EXTRACTED',
      extracted_json: { positions: [] },
      error_message: null,
    })
    const onJobReady = vi.fn()

    render(<BulkUploadZone snapshotId="snap-1" onJobReady={onJobReady} />)

    const blob = new Blob(['x'], { type: 'image/png' })
    const file = new File([blob], 'paste.png', { type: 'image/png' })

    // Simulate ClipboardEvent with a file item. DataTransfer/clipboardData is
    // not directly constructible in jsdom, so we cast through the event init.
    const items: DataTransferItemList = [{
      kind: 'file',
      type: 'image/png',
      getAsFile: () => file,
    } as unknown as DataTransferItem] as unknown as DataTransferItemList
    const ev = new Event('paste') as ClipboardEvent
    Object.defineProperty(ev, 'clipboardData', {
      value: { items },
      configurable: true,
    })
    document.dispatchEvent(ev)

    await waitFor(() => expect(api.uploadAttachment).toHaveBeenCalled())
    await waitFor(() => expect(api.createBulkExtract).toHaveBeenCalledWith('snap-1', 'att-1'))
    await waitFor(() => expect(onJobReady).toHaveBeenCalled())
  })

  it('surfaces an error when extraction returns FAILED', async () => {
    vi.spyOn(api, 'uploadAttachment').mockResolvedValue({
      id: 'att-1', workspace_id: 'ws-1',
      source_type: 'snapshot', source_id: 'snap-1',
      kind: 'image', filename: 'p.png', mime_type: 'image/png',
      size_bytes: 1, uploaded_at: '', uploaded_by: null, is_active: true,
    })
    vi.spyOn(api, 'createBulkExtract').mockResolvedValue({
      id: 'job-1', status: 'FAILED',
      extracted_json: null,
      error_message: 'LLM timeout',
    })

    render(<BulkUploadZone snapshotId="snap-1" onJobReady={() => {}} />)

    const file = new File([new Blob(['x'])], 'paste.png', { type: 'image/png' })
    const items: DataTransferItemList = [{
      kind: 'file', type: 'image/png', getAsFile: () => file,
    } as unknown as DataTransferItem] as unknown as DataTransferItemList
    const ev = new Event('paste') as ClipboardEvent
    Object.defineProperty(ev, 'clipboardData', { value: { items }, configurable: true })
    document.dispatchEvent(ev)

    await waitFor(() => expect(screen.getByTestId('bulk-upload-error')).toHaveTextContent(/LLM timeout/))
  })
})
