/** Cache de logos/cores de instituição financeira.
 *
 *  `<FILogo>` é chamado em ~15 lugares e quase sempre só com `logo_slug` —
 *  não dá pra passar a imagem por prop em todos. Este módulo carrega a
 *  listagem uma vez por sessão e notifica os componentes montados via
 *  useSyncExternalStore, então qualquer FILogo passa a renderizar o logo
 *  enviado pelo sysadmin sem mudança de assinatura.
 */
import { useEffect, useSyncExternalStore } from 'react'
import { api, getToken, type FinancialInstitutionLogoOut } from './api'

export type FiLogoMap = Record<string, FinancialInstitutionLogoOut>

const EMPTY: FiLogoMap = {}

let bySlug: FiLogoMap = EMPTY
let byId: FiLogoMap = EMPTY
let loaded = false
let inFlight = false
const listeners = new Set<() => void>()

function emit() {
  for (const l of listeners) l()
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

function load(force: boolean) {
  if (inFlight) return
  if (loaded && !force) return
  // Sem token não há o que buscar — e um 401 aqui limparia o token do usuário.
  if (!getToken()) return
  inFlight = true
  api.listFinancialInstitutionLogos()
    .then(rows => {
      const slugs: FiLogoMap = {}
      const ids: FiLogoMap = {}
      for (const row of rows) {
        if (row.logo_slug) slugs[row.logo_slug] = row
        ids[row.id] = row
      }
      bySlug = slugs
      byId = ids
      loaded = true
      emit()
    })
    .catch(() => {
      // Logo é decoração: falha vira fallback de iniciais, nunca erro na tela.
      loaded = true
    })
    .finally(() => { inFlight = false })
}

export function ensureFiLogosLoaded() {
  load(false)
}

/** Recarrega após upload/remoção de logo ou edição de cor. */
export function refreshFiLogos() {
  load(true)
}

/** Invalida o cache no logout — sessão seguinte recarrega do zero. */
export function resetFiLogos() {
  bySlug = EMPTY
  byId = EMPTY
  loaded = false
  emit()
}

export function useFiLogosBySlug(): FiLogoMap {
  const snap = useSyncExternalStore(subscribe, () => bySlug, () => bySlug)
  useEffect(() => { ensureFiLogosLoaded() }, [])
  return snap
}

export function useFiLogosById(): FiLogoMap {
  const snap = useSyncExternalStore(subscribe, () => byId, () => byId)
  useEffect(() => { ensureFiLogosLoaded() }, [])
  return snap
}
