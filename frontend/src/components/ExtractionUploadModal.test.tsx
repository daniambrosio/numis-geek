import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import ExtractionUploadModal from './ExtractionUploadModal'
import { api, type SnapshotPendencyOut } from '../lib/api'

function makePendency(): SnapshotPendencyOut {
  return {
    id: 'pen-1', snapshot_id: 'snap-1',
    asset_id: 'a-petr', asset_ticker: 'PETR4', asset_name: 'Petrobras',
    asset_institution_short_name: null,
    reason: 'UPLOAD_REQUIRED', action_type: 'UPLOAD_FILE',
    detail: 'precisa de extrato',
    resolved_at: null, resolved_by: null, resolution_note: null,
    created_at: '2026-05-01T00:00:00Z',
    previous_unit_price: null, previous_period_end: null,
  }
}

beforeEach(() => {
  vi.restoreAllMocks()
})

describe('ExtractionUploadModal (Spec 38)', () => {
  it('moves pick → uploading → review → applied on a happy path', async () => {
    vi.spyOn(api, 'uploadAttachment').mockResolvedValue({
      id: 'att-1', workspace_id: 'ws-1',
      source_type: 'asset', source_id: 'a-petr',
      kind: 'image', filename: 'shot.png', mime_type: 'image/png',
      size_bytes: 100, uploaded_at: '', uploaded_by: null, is_active: true,
    })
    vi.spyOn(api, 'createExtraction').mockResolvedValue({
      id: 'job-1', workspace_id: 'ws-1', status: 'EXTRACTED',
      source_hint: 'SCREENSHOT_PRICE',
      attachment_id: 'att-1', pendency_id: 'pen-1',
      snapshot_id: 'snap-1', asset_id: 'a-petr',
      extracted_json: {
        ticker: 'PETR4', price: 42.5, currency: 'BRL',
        as_of_timestamp: null, source_app: 'broker', confidence: 0.93,
      },
      confidence: 0.93, detected_hint: null,
      model: 'claude-sonnet-4-5', prompt_version: 'v1',
      input_tokens: 100, output_tokens: 50, cost_usd: '0.001',
      error_message: null,
      created_at: '', started_at: '', completed_at: '', confirmed_at: null,
    })
    vi.spyOn(api, 'confirmExtraction').mockResolvedValue({
      applied_count: 1, skipped_count: 0, errors: [],
    })
    const onResolved = vi.fn()
    const onClose = vi.fn()

    render(
      <ExtractionUploadModal
        pendency={makePendency()}
        onResolved={onResolved}
        onClose={onClose}
      />,
    )

    const file = new File(['x'], 'shot.png', { type: 'image/png' })
    await userEvent.upload(screen.getByTestId('extraction-file-input'), file)
    await userEvent.click(screen.getByRole('button', { name: /Extrair/ }))

    // Review stage renders once createExtraction resolves.
    await waitFor(() => screen.getByTestId('extraction-review'))
    expect(screen.getByTestId('extraction-review')).toHaveTextContent('PETR4')
    expect(screen.getByTestId('extraction-review')).toHaveTextContent('42.50')

    await userEvent.click(screen.getByTestId('extraction-confirm'))

    await waitFor(() => screen.getByTestId('extraction-applied'))
    expect(screen.getByTestId('extraction-applied')).toHaveTextContent('1')
  })

  it('shows the error and stays on pick stage when extraction FAILS', async () => {
    vi.spyOn(api, 'uploadAttachment').mockResolvedValue({
      id: 'att-1', workspace_id: 'ws-1',
      source_type: 'asset', source_id: 'a-petr',
      kind: 'image', filename: 'x.png', mime_type: 'image/png',
      size_bytes: 1, uploaded_at: '', uploaded_by: null, is_active: true,
    })
    vi.spyOn(api, 'createExtraction').mockResolvedValue({
      id: 'job-bad', workspace_id: 'ws-1', status: 'FAILED',
      source_hint: 'SCREENSHOT_PRICE',
      attachment_id: 'att-1', pendency_id: 'pen-1',
      snapshot_id: 'snap-1', asset_id: 'a-petr',
      extracted_json: null, confidence: null, detected_hint: null,
      model: null, prompt_version: null,
      input_tokens: null, output_tokens: null, cost_usd: null,
      error_message: 'parse error',
      created_at: '', started_at: null, completed_at: '', confirmed_at: null,
    })

    render(
      <ExtractionUploadModal pendency={makePendency()} onResolved={() => {}} onClose={() => {}} />,
    )
    const file = new File(['x'], 'x.png', { type: 'image/png' })
    await userEvent.upload(screen.getByTestId('extraction-file-input'), file)
    await userEvent.click(screen.getByRole('button', { name: /Extrair/ }))

    await waitFor(() => screen.getByTestId('extraction-error'))
    expect(screen.getByTestId('extraction-error')).toHaveTextContent('parse error')
  })
})
