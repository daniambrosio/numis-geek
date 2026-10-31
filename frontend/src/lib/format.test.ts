import { describe, expect, it } from 'vitest'

import { todayISO } from './format'

describe('todayISO', () => {
  it('usa a data local, não UTC (23h em Brasília ainda é o mesmo dia)', () => {
    // 2026-10-30 23:30 no fuso local do teste
    const late = new Date(2026, 9, 30, 23, 30)
    expect(todayISO(late)).toBe('2026-10-30')
  })

  it('zero à esquerda em mês e dia', () => {
    expect(todayISO(new Date(2026, 0, 5, 12))).toBe('2026-01-05')
  })
})
