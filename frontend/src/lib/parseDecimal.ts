/** Parse a user-typed decimal, accepting both pt-BR ("9.911,26") and
 *  US ("9,911.26" or plain "9911.26") conventions.
 *
 *  Rule: when both `,` and `.` appear, the RIGHTMOST one is the decimal
 *  separator; the other is thousands. When only one separator appears,
 *  it is decimal unless it repeats (repeats ⇒ thousands).
 *
 *  Returns null on empty input or NaN. Range checks are the caller's job. */
export function parseDecimal(raw: string): number | null {
  const s = raw.trim()
  if (!s) return null
  const commaCount = (s.match(/,/g) ?? []).length
  const dotCount = (s.match(/\./g) ?? []).length
  let normalized: string
  if (commaCount > 0 && dotCount > 0) {
    if (s.lastIndexOf(',') > s.lastIndexOf('.')) {
      normalized = s.replace(/\./g, '').replace(',', '.')
    } else {
      normalized = s.replace(/,/g, '')
    }
  } else if (commaCount > 1) {
    normalized = s.replace(/,/g, '')
  } else if (commaCount === 1) {
    normalized = s.replace(',', '.')
  } else if (dotCount > 1) {
    normalized = s.replace(/\./g, '')
  } else {
    normalized = s
  }
  const n = Number(normalized)
  return Number.isFinite(n) ? n : null
}
