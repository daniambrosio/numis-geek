import { useEffect, useMemo, useRef, useState } from 'react'
import { X, Sparkles } from 'lucide-react'
import {
  api,
  type AssetClass,
  type AssetOut,
  type AssetMovementOut,
  type AssetMovementRequest,
  type AssetMovementType,
  type OptionType,
} from '../lib/api'
import { parseDecimal } from '../lib/parseDecimal'
import NotesAttachmentsField, {
  type AttachmentDraft, type PersistedAttachment,
} from './NotesAttachmentsField'

// Unified composer (Spec 36 follow-up v2 2026-06-24):
// A grid mantém só os 6 tiles semânticos. Opção deixou de ser tile;
// passou a ser variante dos tiles Compra/Venda, decidida pelo ATIVO:
//
//   Compra + ação ............ BUY
//   Compra + "+ Nova opção" ... BUY_TO_OPEN  (cria Asset+Movement)
//   Compra + opção existente . BUY_TO_CLOSE (encerra venda anterior)
//   Venda  + ação ............ SELL
//   Venda  + "+ Nova opção" .. SELL_OPEN
//   Venda  + opção existente . SELL_TO_CLOSE
//
// EXERCISED e EXPIRED não cabem na grid (não são decisões livres do
// user): cron de auto-settle resolve o caso comum; manual fica no
// OpenOptionsCard da página do underlying.
interface TypeCfg {
  label: string
  hint: string
  qty: boolean
  price: boolean
  fee: boolean
  tax: boolean
}

// SELL.tax=false is deliberate (deferred): IRRF on sales (Tesouro/FII/
// swing trade) is real and gets retained by the broker, but BR tax rules
// change often. A proper "tax engine" inside the app (regressive table,
// FII 20%, prejuízo compensável, day-trade) is too much maintenance for
// a personal-use tool right now — defer until either a 3rd-party tax
// library matures or the workload justifies it. Users record IRRF as a
// separate Transaction in the cash flow instead. Revisit per
// [[tax_engine_deferred]] memory.
const TYPE_CFG: Record<string, TypeCfg> = {
  BUY:             { label: 'Compra',        hint: 'compra adiciona à posição',     qty: true,  price: true,  fee: true,  tax: false },
  SELL:            { label: 'Venda',         hint: 'venda reduz a posição',         qty: true,  price: true,  fee: true,  tax: false },
  BONUS:           { label: 'Bonificação',   hint: 'unidades grátis · bonificação, rewards, airdrop', qty: true, price: false, fee: false, tax: false },
  SUBSCRIPTION:    { label: 'Subscrição',    hint: 'exercício de subscrição',       qty: true,  price: true,  fee: true,  tax: false },
  COME_COTAS:      { label: 'Come-cotas',    hint: 'imposto semestral · BR',        qty: false, price: false, fee: false, tax: true  },
  FULL_REDEMPTION: { label: 'Resgate Total', hint: 'vencimento ou liquidação',      qty: true,  price: true,  fee: true,  tax: true  },
}

const TYPE_ORDER: AssetMovementType[] = [
  'BUY', 'SELL', 'BONUS', 'SUBSCRIPTION', 'COME_COTAS', 'FULL_REDEMPTION',
]

// Classes válidas como underlying de opção (Spec 36 §2.2).
const OPTION_UNDERLYING_CLASSES = new Set<AssetClass>(['STOCK', 'REIT', 'ETF'])

// Sentinel no <select> de Ativo. Quando assetId === NEW_OPTION_SENTINEL,
// o composer mostra o form inline pra criar a opção.
const NEW_OPTION_SENTINEL = '__NEW_OPTION__'

// Non-cotado classes — for BUY/SELL/SUBSCRIPTION/FULL_REDEMPTION, show a
// single "Valor" (gross_amount) input instead of qty × unit_price.
// User decision: track these classes by value (aporte/resgate em R$), with
// quantity being informational at most. The monthly snapshot from the
// statement is the source of truth for market value.
const NON_COTADO_CLASSES: AssetClass[] = [
  'FGTS', 'PRIVATE_PENSION', 'CASH', 'FUND', 'FIXED_INCOME',
]
const NOTA_NEGOCIACAO_TYPES: AssetMovementType[] = ['BUY', 'SELL', 'FULL_REDEMPTION', 'SUBSCRIPTION']

interface Props {
  initial?: AssetMovementOut
  /** Pre-selected asset (used when opening from /assets detail). */
  preselectedAsset?: AssetOut
  /** Atalho do menu "Nova Opção": abre o composer já no tile Compra ou
   *  Venda com "+ Nova opção" selecionado no dropdown. */
  initialNewOption?: 'BUY' | 'SELL'
  assets: AssetOut[]
  /**
   * Save the movement payload and return the saved entity (so the composer
   * can upload pending attachments against the new ID). Returning void from
   * `onSave` disables attachment upload — keep the typed return when callers
   * need attachments.
   */
  onSave: (data: AssetMovementRequest) => Promise<AssetMovementOut | void>
  /** Called after an OPTION lifecycle action (close/exercise/expire) so the
   *  parent can refresh its movement list (the lifecycle endpoints create
   *  movements server-side that the standard `onSave` flow doesn't know
   *  about). */
  onOptionLifecycleSaved?: () => void | Promise<void>
  onClose: () => void
  /** Already-persisted attachments shown above drafts in edit mode. */
  persistedAttachments?: PersistedAttachment[]
  /** Called once the composer has new drafts ready to upload, returning the
   *  saved entity id. */
  onUploadDrafts?: (entityId: string, drafts: AttachmentDraft[]) => Promise<void>
  onRemovePersistedAttachment?: (attachmentId: string) => Promise<void>
}

const num = (s: string): number => parseDecimal(s) ?? 0

const fmtMoney = (n: number, ccy: 'BRL' | 'USD', opts: { sign?: boolean } = {}) => {
  const sign = opts.sign && n > 0 ? '+ ' : opts.sign && n < 0 ? '− ' : ''
  return sign + Math.abs(n).toLocaleString('pt-BR', { style: 'currency', currency: ccy })
}

const fmtNum = (n: number, digits = 2) =>
  n.toLocaleString('pt-BR', { maximumFractionDigits: digits })

export default function MovementComposer({
  initial, preselectedAsset, initialNewOption, assets, onSave, onOptionLifecycleSaved, onClose,
  persistedAttachments, onUploadDrafts, onRemovePersistedAttachment,
}: Props) {
  const [type, setType] = useState<AssetMovementType>(
    initial?.type ?? initialNewOption ?? 'BUY',
  )
  // Default deliberately NOT taken from `assets[0]` — the server orders by
  // name, but the dropdown sorts by ticker, so the two would diverge. The
  // effect below syncs assetId with the first visible option once
  // sortedAssets is built (also handles the modal-opens-before-load race).
  const [assetId, setAssetId] = useState<string>(
    initial?.asset_id
      ?? preselectedAsset?.id
      ?? (initialNewOption ? NEW_OPTION_SENTINEL : ''),
  )
  const [eventDate, setEventDate] = useState(initial?.event_date ?? new Date().toISOString().slice(0, 10))
  const [quantity, setQuantity] = useState(initial?.quantity != null ? String(initial.quantity) : '')
  const [unitPrice, setUnitPrice] = useState(initial?.unit_price != null ? String(initial.unit_price) : '')
  const [grossAmount, setGrossAmount] = useState(initial?.gross_amount != null ? String(initial.gross_amount) : '')
  const [fee, setFee] = useState(initial?.fee != null ? String(initial.fee) : '')
  const [tax, setTax] = useState(initial?.tax != null ? String(initial.tax) : '')
  const [notes, setNotes] = useState(initial?.notes ?? '')
  const [notaNegociacao, setNotaNegociacao] = useState(initial?.nota_negociacao_number ?? '')
  const [confirmInactive, setConfirmInactive] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [attachmentDrafts, setAttachmentDrafts] = useState<AttachmentDraft[]>([])
  const [attachmentWarning, setAttachmentWarning] = useState<string | null>(null)
  const wrapperRef = useRef<HTMLDivElement>(null)

  // ── Estado específico de OPENs (SELL_OPEN / BUY_TO_OPEN) ─────────────────
  // Esses cria Asset+Movement em uma chamada (POST /api/options). Os campos
  // abaixo só existem visualmente quando mode === 'option-open'.
  const [optTicker, setOptTicker] = useState('')
  const [optUnderlyingId, setOptUnderlyingId] = useState('')
  const [optType, setOptType] = useState<OptionType>('PUT')
  const [optStrike, setOptStrike] = useState('')
  const [optExpiration, setOptExpiration] = useState('')
  // contract_size em opções B3 é fixo em 100 — não exponho input (manteria
  // ruído visual sem ganho real; backend aceita override se algum dia
  // precisar via API). Default 100 hardcoded no submit.
  const [optParsing, setOptParsing] = useState(false)
  const [optParsedHint, setOptParsedHint] = useState<string | null>(null)

  // Bug 8 fix (2026-06-09): no 2º+ abrir, o foco ficava no botão "Novo
  // Lançamento" da página, e o browser não dispara `paste` em elementos
  // não-editáveis. Forçar foco no wrapper (tabIndex=-1) garante que
  // ⌘V dispare o paste event que o NotesAttachmentsField escuta.
  useEffect(() => {
    wrapperRef.current?.focus()
  }, [])

  const cfg = TYPE_CFG[type] ?? TYPE_CFG.BUY

  // Lookup do asset selecionado (incluindo sentinel pra "Nova opção").
  const selectedAsset = (assetId === NEW_OPTION_SENTINEL)
    ? undefined
    : (assets.find(a => a.id === assetId) ?? preselectedAsset)

  // Modo derivado de tile + asset selecionado:
  //   option-open  → tile Compra/Venda + sentinel "Nova opção"
  //   option-close → tile Compra/Venda + asset OPTION existente
  //   normal       → resto
  const tileSupportsOption = type === 'BUY' || type === 'SELL'
  const mode: 'normal' | 'option-open' | 'option-close' =
    tileSupportsOption && assetId === NEW_OPTION_SENTINEL ? 'option-open'
    : tileSupportsOption && selectedAsset?.asset_class === 'OPTION' ? 'option-close'
    : 'normal'

  // Quando user troca pra um tile que não suporta opção (Bonificação, etc)
  // e o asset atual é OPTION ou sentinel, força reset pro primeiro ativo
  // normal disponível.
  useEffect(() => {
    if (tileSupportsOption) return
    if (assetId === NEW_OPTION_SENTINEL || selectedAsset?.asset_class === 'OPTION') {
      const firstNormal = assets.find(a => a.asset_class !== 'OPTION' && a.is_active !== false)
      if (firstNormal) setAssetId(firstNormal.id)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tileSupportsOption])

  // Underlying picker (só pra option-open).
  const underlyingOptions = useMemo(() => {
    return assets
      .filter(a => OPTION_UNDERLYING_CLASSES.has(a.asset_class) && a.is_active !== false)
      .sort((a, b) => (a.ticker ?? a.name).localeCompare(b.ticker ?? b.name, 'pt-BR'))
  }, [assets])
  const selectedUnderlying = mode === 'option-open'
    ? underlyingOptions.find(a => a.id === optUnderlyingId)
    : undefined

  // Pool do dropdown principal: ações + opções com posição aberta. A entry
  // "+ Nova opção…" é injetada no render direto (não está em `assets`).
  const keepInactiveId = initial?.asset_id ?? preselectedAsset?.id ?? null
  const sortedAssets = useMemo(() => {
    const key = (a: AssetOut) => (a.ticker || a.name).toLocaleLowerCase('pt-BR')
    return assets
      .filter(a => a.is_active !== false || a.id === keepInactiveId)
      .sort((a, b) => key(a).localeCompare(key(b), 'pt-BR'))
  }, [assets, keepInactiveId])

  // Keep assetId in sync with what the dropdown actually displays. Fixes:
  //  - Brand-new movement: useState init left assetId='' (no longer relies
  //    on assets[0]); pick the first sorted option once it's available so
  //    Save isn't stuck disabled waiting for the user to "pick something".
  //  - Edit case where the saved asset isn't in the visible pool (rare —
  //    asset hard-deleted out of band): falls back so the dropdown doesn't
  //    silently render the wrong option (ABT/AAPL/whatever is first).
  useEffect(() => {
    if (assetId === NEW_OPTION_SENTINEL) return
    if (sortedAssets.length === 0) return
    if (sortedAssets.some(a => a.id === assetId)) return
    setAssetId(sortedAssets[0].id)
  }, [sortedAssets, assetId])

  const ccy: 'BRL' | 'USD' = (mode === 'option-open'
    ? (selectedUnderlying?.currency ?? 'BRL')
    : (selectedAsset?.currency ?? 'BRL'))

  const isNonCotado = mode === 'normal' && !!selectedAsset
    && NON_COTADO_CLASSES.includes(selectedAsset.asset_class)
  const isCotadoOrValueType = ['BUY', 'SELL', 'SUBSCRIPTION', 'FULL_REDEMPTION'].includes(type)
  const useValueOnly = isNonCotado && isCotadoOrValueType
  const showQuantity = cfg.qty && !useValueOnly
  const showUnitPrice = cfg.price && !useValueOnly
  const showFee = cfg.fee
  const showTax = cfg.tax
  const showNotaNegociacao = mode === 'normal' && NOTA_NEGOCIACAO_TYPES.includes(type)
  const assetInactive = !!selectedAsset && selectedAsset.is_active === false

  // Parser BRAPI do ticker de opção (só popula type + suggestion de strike
  // como hint visual; strike NÃO é auto-preenchido depois do ajuste
  // corporativo deixar o número do ticker fora de sincronia com o strike
  // real — user sempre digita strike à mão).
  useEffect(() => {
    if (mode !== 'option-open') return
    const t = optTicker.trim().toUpperCase()
    if (t.length < 5) {
      setOptParsedHint(null)
      return
    }
    setOptParsing(true)
    api.parseOption(t, selectedUnderlying?.current_price ?? undefined)
      .then(p => {
        if (!p) { setOptParsedHint(null); return }
        setOptType(p.option_type)
        setOptParsedHint(
          `${p.option_type} · mês ${p.month} · strike sugerido R$ ${p.strike_suggested} (digite o strike real à mão)`,
        )
      })
      .catch(() => setOptParsedHint(null))
      .finally(() => setOptParsing(false))
  }, [optTicker, mode, selectedUnderlying?.current_price])

  // Reset asset-related state when asset changes.
  useEffect(() => { setConfirmInactive(false) }, [assetId])

  // Live preview: Net + position transition.
  // Bug 6 fix (2026-06-09): preview seguia convenção de cashflow assinado
  // (BUY negativo) enquanto o backend grava `net_amount` como valor
  // absoluto da operação (gross+fee+tax pra BUY; gross-fee-tax pra SELL).
  // Resultado: tela mostrava "-R$ X,XX" vermelho mas o DB recebia
  // "R$ X,XX" positivo. Aqui matchamos a math do backend
  // (_compute_net_amount em api/routes/asset_movements.py:241).
  const qN = num(quantity), pN = num(unitPrice), feeN = num(fee), tN = num(tax), gN = num(grossAmount)
  const grossN = useValueOnly ? gN : qN * pN
  let net = 0
  if (type === 'BUY' || type === 'SUBSCRIPTION') net = grossN + feeN + tN
  else if (type === 'SELL')                       net = grossN - feeN - tN
  else if (type === 'FULL_REDEMPTION')            net = grossN - feeN - tN
  else if (type === 'COME_COTAS')                 net = -tN
  else if (type === 'BONUS')                      net = 0
  // 2026-06-09: trocado de "saída/entrada" + cor de cashflow pra label
  // semântico (Investido / Recebido / Imposto retido / Sem custo).
  // Cor verde quando representa ganho de patrimônio (cota ou caixa),
  // vermelho só pra perda real (come-cotas), neutro pra BONUS.
  const netLabel: string =
    type === 'BUY' || type === 'SUBSCRIPTION' ? 'Investido'
    : type === 'SELL' || type === 'FULL_REDEMPTION' ? 'Recebido'
    : type === 'COME_COTAS' ? 'Imposto retido'
    : type === 'BONUS' ? 'Sem custo'
    : 'Net'
  const netTone: 'positive' | 'negative' | 'neutral' =
    type === 'COME_COTAS' ? 'negative'
    : type === 'BONUS' ? 'neutral'
    : 'positive'

  // Position delta (illustrative — server is source of truth).
  const positionDelta = (type === 'BUY' || type === 'BONUS' || type === 'SUBSCRIPTION') ? qN
                      : (type === 'SELL' || type === 'FULL_REDEMPTION') ? -qN
                      : 0

  // ESC closes
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
        const form = document.getElementById('movement-form') as HTMLFormElement | null
        form?.requestSubmit()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const missingFields: string[] = []
  if (mode === 'option-open') {
    if (!optTicker.trim()) missingFields.push('Ticker da opção')
    if (!selectedUnderlying) missingFields.push('Underlying')
    if (!(num(optStrike) > 0)) missingFields.push('Strike')
    if (!optExpiration) missingFields.push('Vencimento')
  } else if (!selectedAsset) {
    missingFields.push('Ativo')
  }
  if (cfg.qty && !useValueOnly && !(qN > 0)) missingFields.push('Quantidade')
  if (cfg.price && !useValueOnly && !(pN > 0)) {
    missingFields.push(mode === 'normal' ? 'Preço unitário' : 'Prêmio/ação')
  }
  if (type === 'COME_COTAS' && !(tN > 0)) missingFields.push('Imposto retido')
  if (useValueOnly && !(gN > 0)) missingFields.push('Valor total')
  if (assetInactive && !confirmInactive) missingFields.push('Confirmar ativo inativo')
  const isValid = missingFields.length === 0

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!isValid) return
    setError('')
    setSaving(true)
    try {
      let saved: AssetMovementOut | void

      // ── Branch 1: criar opção (Asset + abertura) ──────────────────────
      if (mode === 'option-open' && !initial) {
        await api.createOption({
          ticker: optTicker.trim().toUpperCase(),
          underlying_id: selectedUnderlying!.id,
          account_id: selectedUnderlying!.account_id,
          option_type: optType,
          strike_price: num(optStrike),
          expiration_date: optExpiration,
          contract_size: 100,
          // Tile Compra → BUY_TO_OPEN; Tile Venda → SELL_OPEN.
          movement_type: type === 'BUY' ? 'BUY_TO_OPEN' : 'SELL_OPEN',
          movement_date: eventDate,
          quantity: num(quantity),
          price_per_share: num(unitPrice),
          fee: fee ? num(fee) : 0,
          notes: notes.trim() || undefined,
        })
        saved = undefined
        if (onOptionLifecycleSaved) await onOptionLifecycleSaved()
      }
      // ── Branch 2: encerrar opção existente (auto-inferido) ─────────────
      else if (mode === 'option-close' && !initial) {
        // Tile Compra → BUY_TO_CLOSE (encerra venda anterior);
        // Tile Venda → SELL_TO_CLOSE (encerra compra anterior).
        await api.closeOption(selectedAsset!.id, {
          close_date: eventDate,
          quantity: num(quantity),
          price_per_share: num(unitPrice),
          movement_type: type === 'BUY' ? 'BUY_TO_CLOSE' : 'SELL_TO_CLOSE',
          fee: fee ? num(fee) : 0,
          notes: notes.trim() || undefined,
        })
        saved = undefined
        if (onOptionLifecycleSaved) await onOptionLifecycleSaved()
      }
      // ── Branch 3: movement normal (BUY/SELL/BONUS/...) ──────────────────
      else {
        const payload: AssetMovementRequest = {
          asset_id: assetId,
          type,
          event_date: eventDate,
          settlement_date: null,
          currency: ccy,
          // fx_rate omitted on purpose — backend auto-fills PTAX of event_date
          // (services/fx.resolve_fx_rate). Applies to BRL AND USD per the
          // bimoneda design (CLAUDE.md feature #3 "Dolarized portfolio view").
          notes: notes.trim() || null,
        }
        if (showQuantity && quantity) payload.quantity = num(quantity)
        if (showUnitPrice && unitPrice) payload.unit_price = num(unitPrice)
        if (useValueOnly || grossAmount) payload.gross_amount = num(grossAmount)
        if (showFee && fee) payload.fee = num(fee)
        if (showTax && tax) payload.tax = num(tax)
        if (showNotaNegociacao && notaNegociacao.trim()) payload.nota_negociacao_number = notaNegociacao.trim()
        if (useValueOnly) {
          payload.quantity = null
          payload.unit_price = null
        }
        saved = await onSave(payload)
      }

      // After the row is persisted, upload pending attachments. A partial
      // failure leaves the row but raises a warning so the user can retry.
      if (attachmentDrafts.length && onUploadDrafts && saved && 'id' in saved) {
        try {
          await onUploadDrafts(saved.id, attachmentDrafts)
        } catch (attErr) {
          setAttachmentWarning(
            attErr instanceof Error
              ? `Lançamento salvo, mas alguns anexos falharam: ${attErr.message}`
              : 'Lançamento salvo, mas alguns anexos falharam.',
          )
          return
        }
      }
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erro ao salvar.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div
        ref={wrapperRef}
        tabIndex={-1}
        className="w-full max-w-2xl max-h-[90vh] bg-white dark:bg-gray-900 rounded-2xl border border-gray-200 dark:border-gray-800 shadow-2xl flex flex-col outline-none"
      >
        {/* Header */}
        <div className="px-6 py-4 border-b border-gray-100 dark:border-gray-800 flex items-start justify-between">
          <div>
            <h2 className="text-base font-semibold text-gray-900 dark:text-white">
              {initial ? 'Editar Lançamento' : 'Novo Lançamento'}
            </h2>
            <p className="text-[12px] text-gray-500 dark:text-gray-400 mt-0.5">
              Movimento de posição em ativo
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="w-7 h-7 inline-flex items-center justify-center rounded-md text-gray-400 hover:text-gray-700 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Body */}
        <form id="movement-form" onSubmit={handleSubmit} className="px-6 py-5 overflow-y-auto flex-1 scrollbar-thin space-y-5">
          {/* Type picker — 6 tiles em grid 3×2. Opção é variante de Compra/Venda
             (definida pelo Ativo selecionado), não tile separado. */}
          <div>
            <FieldLabel>Tipo</FieldLabel>
            <div className="grid grid-cols-3 gap-2 mt-1.5" data-testid="movement-type-grid">
              {TYPE_ORDER.map(id => {
                const c = TYPE_CFG[id]
                const active = type === id
                return (
                  <button
                    key={id}
                    type="button"
                    onClick={() => setType(id)}
                    disabled={!!initial}
                    className={`px-3 py-2.5 rounded-lg text-left border transition-colors disabled:opacity-60 disabled:cursor-not-allowed ${
                      active
                        ? 'bg-indigo-500/10 border-indigo-500'
                        : 'bg-gray-50 dark:bg-gray-800/30 border-gray-200 dark:border-gray-800 hover:border-gray-400 dark:hover:border-gray-700'
                    }`}
                  >
                    <div className={`text-[12px] font-semibold ${active ? 'text-indigo-700 dark:text-indigo-300' : 'text-gray-700 dark:text-gray-300'}`}>
                      {c.label}
                    </div>
                    <div className="text-[10px] text-gray-500 mt-0.5">{c.hint}</div>
                  </button>
                )
              })}
            </div>
          </div>

          {/* Date + Asset (dropdown limpo + botão lateral pra nova opção) */}
          <div className="grid grid-cols-2 gap-4">
            <Field label="Data do evento">
              <input
                type="date"
                value={eventDate}
                onChange={e => setEventDate(e.target.value)}
                required
                className={inputCls}
              />
            </Field>
            <Field label="Ativo">
              {mode === 'option-open' ? (
                // No modo "nova opção", trocamos o select por um placeholder
                // visual com link pra voltar ao modo "existente". O form
                // inline da definição (ticker/strike/venc/etc) renderiza
                // logo abaixo do bloco Date+Asset.
                <div className="flex items-center gap-2">
                  <div className={`${inputCls} flex items-center text-indigo-600 dark:text-indigo-400 font-medium gap-1.5`}>
                    <Sparkles className="w-3.5 h-3.5" />
                    Nova opção
                  </div>
                  <button
                    type="button"
                    onClick={() => setAssetId(sortedAssets[0]?.id ?? '')}
                    className="h-9 px-2 text-[11px] text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 whitespace-nowrap"
                    data-testid="movement-pick-existing-asset"
                  >
                    ← escolher existente
                  </button>
                </div>
              ) : (
                <div className="flex items-center gap-1.5">
                  <select
                    value={assetId}
                    onChange={e => setAssetId(e.target.value)}
                    disabled={!!initial || !!preselectedAsset}
                    required
                    className={inputCls}
                    data-testid="movement-asset-picker"
                  >
                    {sortedAssets.length === 0 && <option value="">Nenhum ativo</option>}
                    {sortedAssets.map(a => (
                      <option key={a.id} value={a.id}>
                        {a.ticker ? `${a.ticker} · ` : ''}{a.name}{a.is_active === false ? ' · INATIVO' : ''}
                      </option>
                    ))}
                  </select>
                  {tileSupportsOption && !initial && !preselectedAsset && (
                    <button
                      type="button"
                      onClick={() => setAssetId(NEW_OPTION_SENTINEL)}
                      title="Nova opção"
                      className="h-9 w-9 shrink-0 inline-flex items-center justify-center rounded-md bg-indigo-500/10 hover:bg-indigo-500/20 border border-indigo-500/30 text-indigo-600 dark:text-indigo-400 transition-colors"
                      data-testid="movement-new-option-btn"
                    >
                      <Sparkles className="w-4 h-4" />
                    </button>
                  )}
                </div>
              )}
            </Field>
          </div>

          {/* Banner pra option-close (auto-inferido) */}
          {mode === 'option-close' && selectedAsset && (
            <div className="rounded-lg border border-indigo-500/20 bg-indigo-500/[0.05] px-3 py-2 text-[12px] text-indigo-700 dark:text-indigo-300">
              Vai encerrar a posição em <strong>{selectedAsset.ticker || selectedAsset.name}</strong>{' '}
              ({type === 'BUY' ? 'recompra de opção vendida' : 'venda de opção comprada'}).
            </div>
          )}

          {/* Form inline da nova opção (só no modo option-open) */}
          {mode === 'option-open' && (
            <div className="space-y-3 rounded-lg border border-indigo-500/20 bg-indigo-500/[0.03] p-3">
              <div className="text-[10px] uppercase tracking-wider font-semibold text-indigo-500 dark:text-indigo-400">
                Definição da opção
              </div>
              <div className="grid grid-cols-2 gap-4">
                <Field label="Ticker B3" hint="ex: ITUBR364">
                  <input
                    type="text"
                    value={optTicker}
                    onChange={e => setOptTicker(e.target.value.toUpperCase())}
                    placeholder="ITUBR364"
                    className={`${inputCls} font-mono`}
                    data-testid="option-ticker-input"
                  />
                  {optParsing && <div className="text-[10px] text-gray-400 mt-1">Parseando…</div>}
                  {optParsedHint && (
                    <div className="text-[10px] text-emerald-600 dark:text-emerald-400 mt-1">{optParsedHint}</div>
                  )}
                </Field>
                <Field label="Underlying">
                  <select
                    value={optUnderlyingId}
                    onChange={e => setOptUnderlyingId(e.target.value)}
                    className={inputCls}
                    data-testid="option-underlying-picker"
                  >
                    <option value="">Selecione…</option>
                    {underlyingOptions.map(a => (
                      <option key={a.id} value={a.id}>
                        {(a.ticker || a.name)}{a.current_price != null ? ` · ${a.currency} ${a.current_price.toFixed(2)}` : ''}
                      </option>
                    ))}
                  </select>
                </Field>
              </div>
              <div className="grid grid-cols-3 gap-4">
                <Field label="Tipo">
                  <select
                    value={optType}
                    onChange={e => setOptType(e.target.value as OptionType)}
                    className={inputCls}
                  >
                    <option value="PUT">PUT</option>
                    <option value="CALL">CALL</option>
                  </select>
                </Field>
                <Field label="Strike · R$">
                  <input
                    type="number" step="0.01" value={optStrike}
                    onChange={e => setOptStrike(e.target.value)}
                    placeholder="ex: 36,40"
                    className={inputCls}
                    data-testid="option-strike-input"
                  />
                </Field>
                <Field label="Vencimento">
                  <input
                    type="date" value={optExpiration}
                    onChange={e => setOptExpiration(e.target.value)}
                    className={inputCls}
                    data-testid="option-expiration-input"
                  />
                </Field>
              </div>
            </div>
          )}

          {/* Numeric fields (conditional per type) */}
          <div className="grid grid-cols-2 gap-4">
            {useValueOnly ? (
              <Field label={`Valor · ${ccy}`}>
                <input
                  type="number" step="0.01" value={grossAmount}
                  onChange={e => setGrossAmount(e.target.value)} required
                  placeholder="ex: 50.000,00"
                  className={inputCls}
                />
              </Field>
            ) : (
              <>
                {showQuantity && (
                  <Field label="Quantidade">
                    <input
                      type="number" step="0.00000001" value={quantity}
                      onChange={e => setQuantity(e.target.value)} required={cfg.qty}
                      placeholder="ex: 100"
                      className={inputCls}
                    />
                  </Field>
                )}
                {showUnitPrice && (
                  <Field label={`Preço unitário · ${ccy}`}>
                    <input
                      type="number" step="0.00000001" value={unitPrice}
                      onChange={e => setUnitPrice(e.target.value)} required={cfg.price}
                      placeholder="ex: 38,90"
                      className={inputCls}
                    />
                  </Field>
                )}
              </>
            )}
            {showFee && (
              <Field label={`Taxa · ${ccy}`} hint="opcional">
                <input
                  type="number" step="0.01" value={fee}
                  onChange={e => setFee(e.target.value)}
                  placeholder="ex: 12,40"
                  className={inputCls}
                />
              </Field>
            )}
            {showTax && (
              <Field
                label={`Imposto retido · ${ccy}`}
                hint={type === 'COME_COTAS' ? undefined : 'opcional'}
              >
                <input
                  type="number" step="0.01" value={tax}
                  onChange={e => setTax(e.target.value)} required={type === 'COME_COTAS'}
                  placeholder="ex: 384,00"
                  className={inputCls}
                />
              </Field>
            )}
          </div>

          {/* Inactive warning */}
          {assetInactive && (
            <div className="p-3 rounded-lg bg-amber-500/10 border border-amber-500/30 text-[12px] text-amber-800 dark:text-amber-300">
              Esse ativo está marcado como zerado.
              <label className="flex items-center gap-2 mt-1.5 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={confirmInactive}
                  onChange={e => setConfirmInactive(e.target.checked)}
                  className="w-3.5 h-3.5 rounded border-amber-400 text-amber-600 focus:ring-amber-500"
                />
                <span>Confirmo que quero registrar mesmo assim.</span>
              </label>
            </div>
          )}

          {/* Brokerage note number */}
          {showNotaNegociacao && (
            <Field label="Nº Nota de Corretagem" hint="opcional">
              <input
                type="text" value={notaNegociacao}
                onChange={e => setNotaNegociacao(e.target.value)}
                maxLength={50} placeholder="ex: 12345"
                className={`${inputCls} font-mono`}
              />
            </Field>
          )}

          {/* Live preview */}
          {selectedAsset && (
            <div className="rounded-lg bg-indigo-500/5 border border-indigo-500/20 p-3.5 space-y-2">
              <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider font-semibold text-indigo-500 dark:text-indigo-400">
                <Sparkles className="w-3 h-3" />
                Pré-visualização
              </div>
              {showQuantity && showUnitPrice && qN > 0 && pN > 0 && (
                <div className="flex items-center justify-between text-[12px]">
                  <span className="text-gray-500 dark:text-gray-400">Bruto</span>
                  <span className="tnum text-gray-700 dark:text-gray-300">
                    {fmtMoney(qN * pN, ccy)}
                    {feeN > 0 && (
                      <span className="text-gray-400 dark:text-gray-500"> · taxa {fmtMoney(feeN, ccy)}</span>
                    )}
                  </span>
                </div>
              )}
              {useValueOnly && gN > 0 && (feeN > 0 || tN > 0) && (
                <div className="space-y-1 text-[12px] border-b border-indigo-500/10 pb-2">
                  <div className="flex items-center justify-between">
                    <span className="text-gray-500 dark:text-gray-400">Valor bruto</span>
                    <span className="tnum text-gray-700 dark:text-gray-300">{fmtMoney(gN, ccy)}</span>
                  </div>
                  {feeN > 0 && (
                    <div className="flex items-center justify-between">
                      <span className="text-gray-500 dark:text-gray-400">− Taxa</span>
                      <span className="tnum text-gray-700 dark:text-gray-300">{fmtMoney(feeN, ccy)}</span>
                    </div>
                  )}
                  {tN > 0 && (
                    <div className="flex items-center justify-between">
                      <span className="text-gray-500 dark:text-gray-400">− Imposto retido</span>
                      <span className="tnum text-gray-700 dark:text-gray-300">{fmtMoney(tN, ccy)}</span>
                    </div>
                  )}
                </div>
              )}
              <div className="flex items-center justify-between">
                <span className="text-[12px] text-gray-500 dark:text-gray-400">
                  {netLabel}
                </span>
                <span className={`tnum text-base font-semibold ${
                  netTone === 'positive' ? 'text-emerald-500 dark:text-emerald-400'
                  : netTone === 'negative' ? 'text-red-500 dark:text-red-400'
                  : 'text-gray-500 dark:text-gray-400'
                }`}>
                  {fmtMoney(Math.abs(net), ccy)}
                </span>
              </div>
              {cfg.qty && (
                <div className="flex items-center justify-between text-[12px]">
                  <span className="text-gray-500 dark:text-gray-400">Posição</span>
                  <span className="tnum text-gray-700 dark:text-gray-300">
                    {positionDelta !== 0 ? (
                      <>
                        Δ <span className={positionDelta > 0 ? 'text-emerald-500 dark:text-emerald-400 font-semibold' : 'text-red-500 dark:text-red-400 font-semibold'}>
                          {positionDelta > 0 ? '+' : ''}{fmtNum(positionDelta, 4)}
                        </span> {selectedAsset.ticker || selectedAsset.name}
                      </>
                    ) : '—'}
                  </span>
                </div>
              )}
            </div>
          )}

          {/* Notes + anexos */}
          <NotesAttachmentsField
            notes={notes}
            onNotesChange={setNotes}
            files={attachmentDrafts}
            onFilesChange={setAttachmentDrafts}
            persisted={persistedAttachments}
            onRemovePersisted={onRemovePersistedAttachment}
            placeholder="ex: tese, motivo da compra, link pra notícia…"
          />

          {error && <p className="text-[12px] text-red-600 dark:text-red-400">{error}</p>}
          {attachmentWarning && (
            <p className="text-[12px] text-amber-600 dark:text-amber-400">{attachmentWarning}</p>
          )}
        </form>

        {/* Footer */}
        <div className="px-6 py-3 border-t border-gray-100 dark:border-gray-800 flex items-center justify-between gap-3">
          <div className="flex flex-col gap-0.5 min-w-0">
            <span className="text-[11px] text-gray-500 dark:text-gray-500">
              <kbd className="px-1.5 py-0.5 mx-0.5 rounded bg-gray-100 dark:bg-gray-800 text-[10px] font-mono">⌘↵</kbd> salvar
              {' · '}
              <kbd className="px-1.5 py-0.5 mx-0.5 rounded bg-gray-100 dark:bg-gray-800 text-[10px] font-mono">esc</kbd> fechar
            </span>
            {missingFields.length > 0 && (
              <span className="text-[11px] text-amber-600 dark:text-amber-400 truncate" title={missingFields.join(', ')}>
                Faltam: {missingFields.join(', ')}
              </span>
            )}
          </div>
          <div className="flex gap-2 shrink-0">
            <button
              type="button"
              onClick={onClose}
              className="h-8 px-3 inline-flex items-center rounded-md text-[12px] text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors"
            >
              Cancelar
            </button>
            <button
              type="submit"
              form="movement-form"
              disabled={!isValid || saving}
              title={!isValid ? `Faltam: ${missingFields.join(', ')}` : undefined}
              className="h-8 px-3 inline-flex items-center gap-1.5 rounded-md bg-indigo-500 hover:bg-indigo-400 text-white text-[12px] font-medium disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {saving ? 'Salvando…' : (initial ? '✓ Salvar alterações' : '✓ Salvar')}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

/* ── Primitives ──────────────────────────────────────────────────────── */

function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <label className="block text-[10px] uppercase tracking-wider font-semibold text-gray-500 dark:text-gray-400">
      {children}
    </label>
  )
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="flex items-baseline justify-between mb-1.5">
        <FieldLabel>{label}</FieldLabel>
        {hint && <span className="text-[10px] text-gray-400 dark:text-gray-600">· {hint}</span>}
      </div>
      {children}
    </div>
  )
}

const inputCls =
  'w-full h-9 px-3 text-[13px] rounded-md bg-gray-50 dark:bg-gray-800/50 border border-gray-200 dark:border-gray-800 text-gray-900 dark:text-white placeholder:text-gray-400 dark:placeholder:text-gray-600 focus:outline-none focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500'
