import { describe, expect, it } from 'vitest'
import {
  computeKpis, fmtChart, fmtPct, monthLabel, shouldStrideXAxis, xAxisTicks,
} from './chart'
import type { ChartDataOut } from './api'

describe('monthLabel', () => {
  it('returns Portuguese month abbreviation', () => {
    expect(monthLabel('2026-04')).toBe('Abr')
    expect(monthLabel('2025-12')).toBe('Dez')
  })
  it('appends 2-digit year when requested', () => {
    expect(monthLabel('2026-04', true)).toBe('Abr/26')
  })
  it('falls back to raw input on bad ym', () => {
    expect(monthLabel('xxxx-yy')).toBe('xxxx-yy')
  })
})

describe('fmtChart', () => {
  it('uses R$ for BRL, US$ for USD', () => {
    expect(fmtChart(100, 'BRL')).toBe('R$ 100')
    expect(fmtChart(100, 'USD')).toBe('US$ 100')
  })
  it('compact mode abbreviates thousands and millions', () => {
    expect(fmtChart(5200, 'BRL', true)).toMatch(/mil/)
    expect(fmtChart(1_500_000, 'BRL', true)).toMatch(/mi/)
  })
  it('non-compact rounds to no decimals with pt-BR separators', () => {
    expect(fmtChart(5231, 'BRL')).toBe('R$ 5.231')
  })
  it('returns "R$ 0" / "US$ 0" for zero', () => {
    expect(fmtChart(0, 'BRL')).toBe('R$ 0')
    expect(fmtChart(0, 'USD')).toBe('US$ 0')
  })
  it('renders negative values with leading minus', () => {
    expect(fmtChart(-1500, 'BRL', true)).toMatch(/^-R\$/)
  })
})

describe('fmtPct', () => {
  it('renders percentages with comma decimal', () => {
    expect(fmtPct(0.075)).toBe('7,5%')
  })
  it('respects decimal-place override', () => {
    expect(fmtPct(0.05, 2)).toBe('5,00%')
  })
})

function makeData(rows: { ym: string; total: number }[], totals?: Partial<ChartDataOut['totals']>): ChartDataOut {
  return {
    rows: rows.map(r => ({ ym: r.ym, total: r.total, segments: [] })),
    legend: [],
    totals: {
      sum: rows.reduce((s, r) => s + r.total, 0),
      monthly_avg: rows.length ? rows.reduce((s, r) => s + r.total, 0) / rows.length : 0,
      max: rows.reduce((m, r) => Math.max(m, r.total), 0),
      ...totals,
    },
    currency: 'BRL',
  }
}

describe('computeKpis', () => {
  const today = new Date('2026-05-24T00:00:00Z')

  it('returns lastMonthTotal from the last row', () => {
    const kpis = computeKpis(makeData([
      { ym: '2026-03', total: 100 },
      { ym: '2026-04', total: 250 },
    ]), today)
    expect(kpis.lastMonthTotal).toBe(250)
  })

  it('computes MoM growth vs previous month', () => {
    const kpis = computeKpis(makeData([
      { ym: '2026-03', total: 100 },
      { ym: '2026-04', total: 150 },
    ]), today)
    expect(kpis.momPct).toBeCloseTo(0.5, 4)
  })

  it('momPct is null when previous month was zero', () => {
    const kpis = computeKpis(makeData([
      { ym: '2026-03', total: 0 },
      { ym: '2026-04', total: 100 },
    ]), today)
    expect(kpis.momPct).toBeNull()
  })

  it('YTD sums only buckets within the current year up to today', () => {
    const kpis = computeKpis(makeData([
      { ym: '2025-12', total: 999 },
      { ym: '2026-01', total: 100 },
      { ym: '2026-04', total: 50 },
      { ym: '2026-06', total: 200 }, // future bucket → ignored
    ]), today)
    expect(kpis.ytdSum).toBe(150)
  })
})

describe('xAxisTicks', () => {
  it('shows every row when ≤ 14', () => {
    const rows = Array.from({ length: 12 }, (_, i) => ({ ym: `2026-${String(i + 1).padStart(2, '0')}`, total: 0, segments: [] }))
    const ticks = xAxisTicks(rows)
    expect(ticks.every(t => t.show)).toBe(true)
  })
  it('shows alternating rows when > 14', () => {
    expect(shouldStrideXAxis(15)).toBe(true)
    const rows = Array.from({ length: 24 }, (_, i) => ({ ym: `2025-${String((i % 12) + 1).padStart(2, '0')}`, total: 0, segments: [] }))
    const ticks = xAxisTicks(rows)
    const shown = ticks.filter(t => t.show)
    expect(shown.length).toBe(12)
  })
})
