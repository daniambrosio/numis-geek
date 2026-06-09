/* Helpers de export CSV. Default em pt-BR: separador ';' (excel BR abre
 * sem precisar Text-to-Columns), decimal com vírgula, encoding UTF-8 BOM
 * pra o Excel reconhecer acentos. */

function csvEscape(value: unknown): string {
  if (value == null) return ''
  const s = String(value)
  if (s.includes(';') || s.includes('"') || s.includes('\n')) {
    return `"${s.replace(/"/g, '""')}"`
  }
  return s
}

export function fmtCsvDecimal(n: number | null | undefined, decimals = 2): string {
  if (n == null) return ''
  return n.toFixed(decimals).replace('.', ',')
}

export function downloadCsv(filename: string, rows: (string | number | null)[][]): void {
  const body = rows
    .map(row => row.map(csvEscape).join(';'))
    .join('\r\n')
  // BOM pra Excel detectar UTF-8.
  const blob = new Blob(['﻿' + body], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}
