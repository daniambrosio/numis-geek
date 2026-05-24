import type { OptionType } from './api'

/** True when the option is in-the-money based on current underlying price. */
export function isITM(
  optionType: OptionType,
  strike: number,
  currentPrice: number,
): boolean {
  return optionType === 'PUT' ? currentPrice < strike : currentPrice > strike
}

/** Distance from underlying price to strike, as a decimal (e.g. 0.085 = +8.5%). */
export function distanceToStrike(strike: number, currentPrice: number): number {
  if (strike === 0) return 0
  return (currentPrice - strike) / strike
}

/** Effective price if exercised (short-position perspective).
 *
 * PUT (sold): you buy the underlying at strike — premium reduces cost basis.
 * CALL (sold): you sell the underlying at strike — premium adds to proceeds.
 *
 * `premiumPerShare` is the absolute value of the premium per share received.
 */
export function effectivePrice(
  optionType: OptionType,
  strike: number,
  premiumPerShare: number,
): number {
  const p = Math.abs(premiumPerShare)
  return optionType === 'PUT' ? strike - p : strike + p
}

/** Whole-day count from `today` (default: now) to the expiration date.
 * Always ≥ 0 — past dates clamp to 0. */
export function daysToExpiration(
  expirationISO: string,
  today: Date = new Date(),
): number {
  const exp = new Date(expirationISO)
  const ms = exp.getTime() - today.getTime()
  return Math.max(0, Math.round(ms / 86_400_000))
}
