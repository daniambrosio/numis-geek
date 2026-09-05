import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'

import NotesAttachmentsCard from './NotesAttachmentsCard'

vi.mock('../lib/api', () => ({
  api: { listAttachments: vi.fn(async () => []) },
  getToken: () => 'tok',
}))

/** Mimics LancamentoDetailPanel: the PUT resolves later and the parent
 *  then re-renders with the *saved* value as the `notes` prop. */
function Harness({ save }: { save: (v: string) => Promise<string> }) {
  const [notes, setNotes] = useState('')
  return (
    <NotesAttachmentsCard
      notes={notes}
      onNotesSave={async v => { setNotes(await save(v)) }}
      sourceType="movement"
      sourceId="m1"
      attachments={[]}
      onAttachmentsChanged={() => {}}
    />
  )
}

function textarea(): HTMLTextAreaElement {
  return screen.getByPlaceholderText(/Adicionar nota/) as HTMLTextAreaElement
}

describe('NotesAttachmentsCard — auto-save das notas', () => {
  beforeEach(() => { vi.useFakeTimers() })
  afterEach(() => { vi.useRealTimers() })

  it('não sobrescreve o que foi digitado enquanto o PUT anterior estava em voo', async () => {
    const saved: string[] = []
    const save = vi.fn(async (v: string) => {
      saved.push(v)
      await new Promise(r => setTimeout(r, 500))   // PUT demora 500 ms
      return v
    })
    render(<Harness save={save} />)

    fireEvent.change(textarea(), { target: { value: 'abc' } })
    await act(async () => { await vi.advanceTimersByTimeAsync(800) })  // dispara PUT("abc")
    expect(save).toHaveBeenCalledTimes(1)

    // Usuário continua digitando enquanto o PUT está em voo.
    fireEvent.change(textarea(), { target: { value: 'abcdef' } })
    await act(async () => { await vi.advanceTimersByTimeAsync(500) })  // PUT("abc") volta, pai ecoa "abc"

    // O eco do servidor NÃO pode apagar "def".
    expect(textarea().value).toBe('abcdef')

    // E o valor final é persistido em seguida (sem PUT concorrente).
    await act(async () => { await vi.advanceTimersByTimeAsync(2000) })
    expect(saved).toEqual(['abc', 'abcdef'])
    expect(textarea().value).toBe('abcdef')
  })

  it('serializa PUTs: nunca dois em voo ao mesmo tempo', async () => {
    let inFlight = 0
    let maxInFlight = 0
    const save = vi.fn(async (v: string) => {
      inFlight += 1; maxInFlight = Math.max(maxInFlight, inFlight)
      await new Promise(r => setTimeout(r, 2000))
      inFlight -= 1
      return v
    })
    render(<Harness save={save} />)

    fireEvent.change(textarea(), { target: { value: 'a' } })
    await act(async () => { await vi.advanceTimersByTimeAsync(800) })
    fireEvent.change(textarea(), { target: { value: 'ab' } })
    await act(async () => { await vi.advanceTimersByTimeAsync(800) })
    fireEvent.change(textarea(), { target: { value: 'abc' } })
    await act(async () => { await vi.advanceTimersByTimeAsync(6000) })

    expect(maxInFlight).toBe(1)
    expect(save).toHaveBeenLastCalledWith('abc')
    expect(textarea().value).toBe('abc')
  })

  it('salva a nota pendente ao desmontar (fechar o painel dentro do debounce)', async () => {
    const save = vi.fn(async (v: string) => v)
    const { unmount } = render(<Harness save={save} />)

    fireEvent.change(textarea(), { target: { value: 'fechou rápido' } })
    unmount()   // antes dos 800 ms

    expect(save).toHaveBeenCalledWith('fechou rápido')
  })

  it('aceita notas novas do pai quando não há edição pendente', async () => {
    function Parent() {
      const [notes, setNotes] = useState('inicial')
      return (
        <>
          <button onClick={() => setNotes('do servidor')}>reload</button>
          <NotesAttachmentsCard
            notes={notes} onNotesSave={async () => {}}
            sourceType="movement" sourceId="m1"
            attachments={[]} onAttachmentsChanged={() => {}}
          />
        </>
      )
    }
    render(<Parent />)
    expect(textarea().value).toBe('inicial')
    fireEvent.click(screen.getByText('reload'))
    expect(textarea().value).toBe('do servidor')
  })
})
