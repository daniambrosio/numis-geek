# Compound Asset Creation — Pattern

> Established in Spec 36 (Options Entry Points). Re-read when adding the
> next compound-create flow (Renda Fixa / Fundo / etc.).

## Definition

A **compound create** is a single user gesture that produces:

1. A new `Asset` row (with class-specific fields), and
2. One or more `AssetMovement` rows that put the asset into the user's
   portfolio in the same transaction.

The canonical example is **Options**: the user fills "ITUBR364 PUT strike
34 vencimento 2026-06-20, vendi 1000 a R$ 0,10" once, and the backend
creates the `Asset(class=OPTION)` plus the `AssetMovement(type=SELL_OPEN)`
atomically.

## Why a dedicated composer per class

The MovementComposer is shaped around **existing** assets — "qual ativo,
qual tipo, qty/price". Compound creates need:

- Class-specific fields (strike + vencimento + contract_size for OPTION,
  indexer + rate + maturity for FIXED_INCOME).
- A second-stage "primeira operação" panel (date + qty + price + fee).
- Optional batch mode ("Salvar e abrir outra" — vendi 5 PUTs hoje).

Trying to unify those into one component bloats it and creates dead UI for
every other class. Each compound class **gets its own composer**.

## The three rules

### 1. One item in `NovoButton` per compound class

`frontend/src/components/AppLayout.tsx` → `NOVO_ITEMS`. Position inside
the "Investimentos" group. Once that group reaches 5 items, split into
"Movimentos" and "Novos ativos".

```ts
{ key: 'option', label: 'Opção', desc: 'PUT/CALL: cria + lança abertura',
  icon: Sigma, group: 'Investimentos', shortcut: 'O',
  enabled: true, composeRoute: '/asset-movements' }
```

`composeRoute` points at the page where the modal lives — Options route
to `/asset-movements` because the page is the natural home for the
generated movements. Future compounds (Renda Fixa) likely route there
too.

### 2. One backend compound endpoint per class

POST `/options` (Spec 17) creates the Asset and the first AssetMovement
in the same DB transaction. Future:
- POST `/fixed-income` — Asset(FIXED_INCOME) + BUY movement.
- POST `/funds` — Asset(FUND) + BUY movement.

**Don't** chain two endpoints (POST /assets then POST /asset-movements)
from the frontend: a failure between them leaves an orphan asset.

### 3. Lifecycle / closer endpoints stay backend-side

Options have `EXERCISED` (2 movements: opção + underlying) and `EXPIRED`
(1 movement + flag flip). The MovementComposer **detects OPTION assets
and dispatches** to `api.exerciseOption` / `api.expireOption` /
`api.closeOption` instead of the standard `POST /asset-movements` —
because those operations are composite and must be atomic in the
backend.

Future compound classes with similar lifecycle (Renda Fixa: vencimento /
liquidação antecipada / venda no secundário) should expose dedicated
endpoints and a similar dispatch rule in the composer.

## Composer skeleton

```tsx
interface Props {
  /** Pre-selected when opened from an asset detail page; absent when
      opened from NovoButton (then show a picker). */
  underlying?: AssetOut
  candidates?: AssetOut[]      // populates the picker
  onClose: () => void
  onSaved: (created?: TheCreatedThing) => void
}
```

Two save buttons:
- **Salvar** — fecha o modal.
- **Salvar e abrir outra** — limpa campos voláteis (ticker, qty, price)
  e mantém o que o user provavelmente quer reusar (underlying, optionType
  pra opções; issuer, indexer pra renda fixa). Foca de volta no primeiro
  campo volátil pra batch entry.

## Tests minimum bar

- Picker shows only the eligible asset classes (Spec 36: STOCK/REIT/ETF
  for options).
- Pre-selected underlying hides the picker.
- "Salvar e abrir outra" clears the right fields and shows a toast.
- The lifecycle dispatch — composer calls the dedicated backend endpoint,
  not the generic POST /asset-movements.
