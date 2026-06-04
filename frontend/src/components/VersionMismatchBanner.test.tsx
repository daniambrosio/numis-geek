/* Spec 54 — testes do banner de mismatch backend↔frontend. */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi, afterEach } from 'vitest'

import VersionMismatchBanner from './VersionMismatchBanner'
import { api } from '../lib/api'

describe('VersionMismatchBanner (Spec 54)', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('não renderiza nada quando sha do backend bate com o baked', async () => {
    vi.spyOn(api, 'version').mockResolvedValue({
      version: 'test-version', sha: 'test-sha', date: '2026-06-04',
    })

    const { container } = render(<VersionMismatchBanner />)
    await waitFor(() => {
      expect(api.version).toHaveBeenCalled()
    }, { timeout: 3000 })

    expect(container.querySelector('[data-testid="version-mismatch-banner"]')).toBeNull()
  })

  it('renderiza banner quando sha do backend é diferente', async () => {
    vi.spyOn(api, 'version').mockResolvedValue({
      version: '0.53.0', sha: 'ab12cd3', date: '2026-06-05',
    })

    render(<VersionMismatchBanner />)
    expect(await screen.findByTestId('version-mismatch-banner', {}, { timeout: 3000 }))
      .toBeInTheDocument()
    expect(screen.getByText(/0\.53\.0/)).toBeInTheDocument()
    expect(screen.getByText(/ab12cd3/)).toBeInTheDocument()
  })

  it('botão Atualizar dispara location.reload', async () => {
    vi.spyOn(api, 'version').mockResolvedValue({
      version: '0.53.0', sha: 'ab12cd3', date: '2026-06-05',
    })
    const reloadSpy = vi.fn()
    Object.defineProperty(window, 'location', {
      writable: true,
      value: { ...window.location, reload: reloadSpy },
    })

    render(<VersionMismatchBanner />)
    fireEvent.click(
      await screen.findByTestId('version-mismatch-reload', {}, { timeout: 3000 }),
    )
    expect(reloadSpy).toHaveBeenCalled()
  })

  it('X dismissa o banner pra mesma sha', async () => {
    vi.spyOn(api, 'version').mockResolvedValue({
      version: '0.53.0', sha: 'ab12cd3', date: '2026-06-05',
    })

    render(<VersionMismatchBanner />)
    expect(
      await screen.findByTestId('version-mismatch-banner', {}, { timeout: 3000 }),
    ).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('version-mismatch-dismiss'))

    await waitFor(() => {
      expect(screen.queryByTestId('version-mismatch-banner')).toBeNull()
    })
  })

  it('backend offline não quebra o componente (silencia)', async () => {
    vi.spyOn(api, 'version').mockRejectedValue(new Error('Network'))

    const { container } = render(<VersionMismatchBanner />)
    await waitFor(() => {
      expect(api.version).toHaveBeenCalled()
    }, { timeout: 3000 })

    expect(container.querySelector('[data-testid="version-mismatch-banner"]')).toBeNull()
  })
})
