/* Spec 85 — rótulos e preset do método ARCA. Chaves em inglês (backend),
 * labels em português. */
import type { ArcaCategory, ArcaLetter } from './api'
import { parseDecimal } from './parseDecimal'

export const ARCA_LETTERS: ArcaLetter[] = ['EQUITY_BR', 'REAL_ESTATE', 'CASH', 'GLOBAL']

export const ARCA_LETTER_LABEL: Record<ArcaCategory, string> = {
  EQUITY_BR: 'Ações',
  REAL_ESTATE: 'Real Estate',
  CASH: 'Caixa',
  GLOBAL: 'Ativos internacionais',
  OUT_OF_SCOPE: 'Fora da ARCA',
}

export const ARCA_LETTER_SHORT: Record<ArcaLetter, string> = {
  EQUITY_BR: 'A',
  REAL_ESTATE: 'R',
  CASH: 'C',
  GLOBAL: 'A',
}

export const ARCA_LETTER_COLOR: Record<ArcaLetter, string> = {
  EQUITY_BR: '#6366f1',
  REAL_ESTATE: '#f59e0b',
  CASH: '#10b981',
  GLOBAL: '#0ea5e9',
}

export const ARCA_SUBS: Record<ArcaLetter, { key: string; label: string; hint: string }[]> = {
  EQUITY_BR: [
    { key: 'EQ_DEFENSIVE', label: 'Defensivas', hint: 'energia, saneamento, grandes bancos' },
    { key: 'EQ_DOLLAR', label: 'Dolarizadas', hint: 'exportadoras' },
    { key: 'EQ_ACCELERATOR', label: 'Aceleradoras', hint: 'small caps' },
  ],
  REAL_ESTATE: [
    { key: 'RE_BRICK', label: 'Tijolo', hint: 'ataque — sobe quando o juro cai' },
    { key: 'RE_FOF', label: 'Fundo de fundos', hint: 'ataque' },
    { key: 'RE_PAPER_CDI', label: 'Papel CDI', hint: 'defesa — juro alto por mais tempo' },
    { key: 'RE_PAPER_IPCA', label: 'Papel IPCA', hint: 'defesa — inflação' },
    { key: 'RE_DIRECT', label: 'Imóvel de renda', hint: 'imóvel físico alugado' },
  ],
  CASH: [
    { key: 'CASH_POST_FIXED', label: 'Pós-fixado', hint: 'CDI/Selic — munição, liquidez' },
    { key: 'CASH_PRE_FIXED', label: 'Pré-fixado', hint: 'trava a taxa' },
    { key: 'CASH_INFLATION', label: 'IPCA+', hint: 'proteção contra inflação (preferir curto)' },
  ],
  GLOBAL: [
    { key: 'GL_FIXED_INCOME', label: 'Renda fixa em dólar', hint: 'T-bills, treasuries, saldo USD' },
    { key: 'GL_GOLD', label: 'Ouro', hint: 'defesa' },
    { key: 'GL_CRYPTO', label: 'Bitcoin / cripto', hint: 'ataque — pouco e aos poucos' },
    { key: 'GL_EQUITY', label: 'Ações e ETFs no exterior', hint: 'stocks, BDRs' },
    { key: 'GL_REIT', label: 'REITs', hint: 'imóveis no exterior' },
  ],
}

export const ARCA_SUB_LABEL: Record<string, string> = Object.fromEntries(
  Object.values(ARCA_SUBS).flat().map((s) => [s.key, s.label]),
)

export function arcaParent(sub: string): ArcaLetter | null {
  for (const l of ARCA_LETTERS) {
    if (ARCA_SUBS[l].some((s) => s.key === sub)) return l
  }
  return null
}

/** Ponto de partida editável. Vem do próprio método (vídeo "Melhores
 * investimentos pra 2027", O Primo Rico): 25% por letra, banda 10–40%;
 * Caixa em 3 partes iguais; Real Estate em ataque (tijolo + FoF) e defesa
 * (papel CDI + papel IPCA) meio a meio; Ações em 3 partes. Internacional
 * fica sem meta interna — o vídeo não quantifica (só diz "um pouquinho"
 * de Bitcoin). Não é recomendação personalizada. */
export const ARCA_PRESET = {
  letters: {
    EQUITY_BR: { target: '25', min: '10', max: '40' },
    REAL_ESTATE: { target: '25', min: '10', max: '40' },
    CASH: { target: '25', min: '10', max: '40' },
    GLOBAL: { target: '25', min: '10', max: '40' },
  } as Record<ArcaLetter, { target: string; min: string; max: string }>,
  subs: {
    CASH_POST_FIXED: '33.33',
    CASH_PRE_FIXED: '33.33',
    CASH_INFLATION: '33.34',
    RE_BRICK: '25',
    RE_FOF: '25',
    RE_PAPER_CDI: '25',
    RE_PAPER_IPCA: '25',
    EQ_DEFENSIVE: '33.33',
    EQ_DOLLAR: '33.33',
    EQ_ACCELERATOR: '33.34',
  } as Record<string, string>,
}

/** Valor de aporte digitado em pt-BR: "R$ 10.000" e "1.000" são milhares
 * (ponto seguido de exatamente 3 dígitos, sem vírgula); o resto segue o
 * parseDecimal. */
export function parseAmount(raw: string): number | null {
  const s = raw.replace(/R\$/g, '').replace(/\s/g, '')
  if (/^\d{1,3}(\.\d{3})+$/.test(s)) return Number(s.replace(/\./g, ''))
  return parseDecimal(s)
}

