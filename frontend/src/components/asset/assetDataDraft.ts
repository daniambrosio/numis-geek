/* Spec 81 — rascunho e PATCH do card "Dados do ativo" (funções puras,
 * separadas do componente por causa do fast refresh). */
import type {
  AssetClass, AssetOut, AssetPatchRequest, FixedIncomeDetails, FixedIncomeIndexer, PhysicalDetails,
} from '../../lib/api'
import { NEEDS_FIXED_INCOME, NEEDS_PHYSICAL } from '../../lib/assetForm'
import { parseDecimal } from '../../lib/parseDecimal'

/** Rascunho dos `details` — tudo string pra casar com os inputs. */
export interface DetailsDraft {
  // renda fixa
  issuer: string
  issue_date: string
  maturity_date: string
  indexer: FixedIncomeIndexer | ''
  rate: string
  face_value: string
  // imóvel
  address: string
  city: string
  state: string
  country: string
  area_m2: string
  registration_number: string
  // veículo
  make: string
  model: string
  year: string
  license_plate: string
  chassis: string
}

export interface Draft {
  name: string
  ticker: string
  cnpj: string
  asset_class: AssetClass
  country: string
  currency: 'BRL' | 'USD'
  fiId: string
  details: DetailsDraft
}

const str = (v: unknown) => (v == null ? '' : String(v))

export function emptyDetailsDraft(): DetailsDraft {
  return {
    issuer: '', issue_date: '', maturity_date: '', indexer: '', rate: '', face_value: '',
    address: '', city: '', state: '', country: '', area_m2: '', registration_number: '',
    make: '', model: '', year: '', license_plate: '', chassis: '',
  }
}

const isDetailsDraftEmpty = (d: DetailsDraft) => Object.values(d).every(v => v === '')

function detailsDraftOf(asset: AssetOut): DetailsDraft {
  const fi = (NEEDS_FIXED_INCOME.includes(asset.asset_class) ? asset.details : null) as FixedIncomeDetails | null
  const ph = (NEEDS_PHYSICAL.includes(asset.asset_class) ? asset.details : null) as PhysicalDetails | null
  return {
    issuer: str(fi?.issuer), issue_date: str(fi?.issue_date), maturity_date: str(fi?.maturity_date),
    indexer: fi?.indexer ?? '', rate: str(fi?.rate), face_value: str(fi?.face_value),
    address: str(ph?.address), city: str(ph?.city), state: str(ph?.state), country: str(ph?.country),
    area_m2: str(ph?.area_m2), registration_number: str(ph?.registration_number),
    make: str(ph?.make), model: str(ph?.model), year: str(ph?.year),
    license_plate: str(ph?.license_plate), chassis: str(ph?.chassis),
  }
}

export function draftOf(asset: AssetOut): Draft {
  return {
    name: asset.name,
    ticker: asset.ticker ?? '',
    cnpj: asset.cnpj ?? '',
    asset_class: asset.asset_class,
    country: asset.country,
    currency: asset.currency,
    fiId: asset.financial_institution_id,
    details: detailsDraftOf(asset),
  }
}

/** Payload de `details` pra classe do rascunho (null quando a classe não usa). */
export function detailsPayload(cls: AssetClass, d: DetailsDraft): Record<string, unknown> | null {
  if (NEEDS_FIXED_INCOME.includes(cls)) {
    return {
      issuer: d.issuer.trim(),
      issue_date: d.issue_date || null,
      maturity_date: d.maturity_date,
      indexer: d.indexer,
      rate: parseDecimal(d.rate),
      face_value: d.face_value === '' ? null : parseDecimal(d.face_value),
    }
  }
  if (NEEDS_PHYSICAL.includes(cls)) {
    return {
      address: d.address.trim() || null,
      city: d.city.trim() || null,
      state: d.state.trim() || null,
      country: d.country.trim() || null,
      area_m2: d.area_m2 === '' ? null : parseDecimal(d.area_m2),
      registration_number: d.registration_number.trim() || null,
      make: d.make.trim() || null,
      model: d.model.trim() || null,
      year: d.year === '' ? null : parseInt(d.year, 10),
      license_plate: d.license_plate.trim() || null,
      chassis: d.chassis.trim() || null,
    }
  }
  return null
}

function sameDetails(a: Record<string, unknown> | null, b: Record<string, unknown> | null): boolean {
  if (a == null || b == null) return a == null && b == null
  const keys = new Set([...Object.keys(a), ...Object.keys(b)])
  for (const k of keys) {
    const x = a[k] ?? null
    const y = b[k] ?? null
    if (typeof x === 'number' || typeof y === 'number') {
      if (Number(x) !== Number(y)) return false
    } else if (x !== y) return false
  }
  return true
}

/** Só os campos que mudaram — o PATCH é parcial de verdade. */
export function buildPatch(asset: AssetOut, d: Draft, accountId: string | null): AssetPatchRequest {
  const patch: AssetPatchRequest = {}
  if (d.name.trim() !== asset.name) patch.name = d.name.trim()
  const ticker = d.ticker.trim() || null
  if (ticker !== (asset.ticker ?? null)) patch.ticker = ticker
  const cnpj = d.cnpj.trim() || null
  if (cnpj !== (asset.cnpj ?? null)) patch.cnpj = cnpj
  if (d.asset_class !== asset.asset_class) patch.asset_class = d.asset_class
  if (d.country !== asset.country) patch.country = d.country
  if (d.currency !== asset.currency) patch.currency = d.currency
  if (accountId && accountId !== asset.account_id) patch.account_id = accountId
  const details = detailsPayload(d.asset_class, d.details)
  if (details) {
    const sameClass = d.asset_class === asset.asset_class
    const current = sameClass ? (asset.details as Record<string, unknown> | null) : null
    // Legado sem details: enquanto o usuário não preenche nada, não entra
    // no PATCH (senão nem renomear funcionaria). Troca de classe sempre entra.
    const untouchedLegacy = sameClass && current == null && isDetailsDraftEmpty(d.details)
    if (!untouchedLegacy && !sameDetails(details, current)) patch.details = details
  }
  return patch
}

/** Problemas nos `details` do rascunho (só o que o backend rejeitaria). */
export function detailsProblems(cls: AssetClass, d: DetailsDraft): string[] {
  const out: string[] = []
  if (NEEDS_FIXED_INCOME.includes(cls)) {
    if (!d.issuer.trim()) out.push('emissor obrigatório')
    if (!d.maturity_date) out.push('vencimento obrigatório')
    if (!d.indexer) out.push('indexador obrigatório')
    if (parseDecimal(d.rate) == null) out.push('taxa obrigatória')
  } else if (cls === 'REAL_ESTATE') {
    if (!d.address.trim() || !d.city.trim() || !d.state.trim() || !d.country.trim()) {
      out.push('imóvel exige endereço, cidade, UF e país')
    }
  } else if (cls === 'VEHICLE') {
    if (!d.make.trim() || !d.model.trim() || !/^\d{4}$/.test(d.year.trim())) {
      out.push('veículo exige marca, modelo e ano')
    }
  }
  return out
}
