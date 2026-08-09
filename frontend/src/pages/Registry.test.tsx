/* Spec 68 — Registry primitives: groupCategories + KindBadge + metas. */
import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'

import { groupCategories, KindBadge, KIND_META, PARTY_KIND_META } from './Registry'
import type { CategoryOut } from '../lib/api'

function cat(partial: Partial<CategoryOut> & { id: string; name: string }): CategoryOut {
  return {
    workspace_id: 'ws',
    parent_id: null,
    kind: 'EXPENSE',
    color: null,
    is_active: true,
    created_at: '2026-08-09T00:00:00',
    ...partial,
  }
}

describe('groupCategories', () => {
  it('groups children under their root, both sorted by name', () => {
    const cats = [
      cat({ id: 'r2', name: 'Mercado' }),
      cat({ id: 'r1', name: 'Casa' }),
      cat({ id: 'c2', name: 'Internet', parent_id: 'r1' }),
      cat({ id: 'c1', name: 'Energia', parent_id: 'r1' }),
    ]
    const grouped = groupCategories(cats)
    expect(grouped.map(g => g.root.name)).toEqual(['Casa', 'Mercado'])
    expect(grouped[0].children.map(c => c.name)).toEqual(['Energia', 'Internet'])
    expect(grouped[1].children).toEqual([])
  })

  it('handles empty input', () => {
    expect(groupCategories([])).toEqual([])
  })

  it('ignores orphan children whose parent is absent (deactivated root)', () => {
    const cats = [cat({ id: 'c1', name: 'Órfã', parent_id: 'gone' })]
    expect(groupCategories(cats)).toEqual([])
  })
})

describe('KindBadge', () => {
  it('renders the PT label for each kind', () => {
    render(<KindBadge kind="EXPENSE" />)
    expect(screen.getByText('Despesa')).toBeInTheDocument()
  })

  it('TRANSFER renders with indigo tone (excluded from expense math)', () => {
    render(<KindBadge kind="TRANSFER" />)
    const el = screen.getByText('Transferência')
    expect(el.className).toMatch(/indigo/)
  })
})

describe('metas', () => {
  it('covers all category kinds', () => {
    expect(Object.keys(KIND_META).sort()).toEqual(['EXPENSE', 'INCOME', 'TRANSFER'])
  })

  it('covers all party kinds with PT labels', () => {
    expect(PARTY_KIND_META).toEqual({ SUPPLIER: 'Fornecedor', CLIENT: 'Cliente', BOTH: 'Ambos' })
  })
})
