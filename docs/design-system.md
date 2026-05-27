# Design System — Numis-Geek

Padrões de UI vinculantes. Atualizado pelo Spec 41 (Dual-currency Hero
Views) e Spec 42 (CcyPill Cleanup).

---

## `<CcyPill ccy="BRL|USD"/>` — when to use

`<CcyPill>` (definido em `frontend/src/components/ui.tsx`) marca a moeda
de um valor monetário. **Não é universal** — ele só agrega informação
quando o número aparece sem contexto suficiente pra moeda ser óbvia.

### Use quando

- O valor flutua isolado, sem coluna explicando a moeda — por exemplo,
  um campo "Moeda" num detail panel (Lançamento, Provento, Asset,
  Conta) onde o número aparece sozinho.
- A pill marca uma **exceção** numa lista onde a maioria é implícita —
  por exemplo, USD numa lista majoritariamente BRL onde o prefixo `R$`
  está omitido (caso da tabela de Movimentações: BRL é maioria sem
  prefixo, USD ganha pill como marcador de anomalia).

### NÃO use quando

- O valor já tem prefixo de símbolo visível (`R$ 3.890,00`, `$ 7.76`) —
  a pill duplica sinalização.
- Existe sub-linha com par converso (`R$ X` em cima, `$ Y` em baixo) —
  o stacking BRL/USD já é o disambiguador (padrão de Hero Views do
  Spec 41).
- A coluna da tabela já especifica a moeda no cabeçalho (mas: cabeçalho
  "Valor" sem `(BRL)` é o padrão atual; usar dual-display na célula
  ao invés disso).
- O valor é uma porcentagem ou outro número adimensional.

### Onde a pill sobrevive (não mexer)

- Detail panels: `LancamentoDetailPanel`, `DistributionDetailPanel`,
  `AssetDetailPanel` (campo "Moeda" do header).
- `<KpiTile>` quando recebe `ccy` prop (componente genérico, usado em
  vários lugares onde o valor flutua isolado).
- Tabela de Movimentações: linha USD ganha pill como **marcador de
  exceção** (a maioria é BRL implícita; USD é a anomalia visualmente
  útil).
- Cards de alocação BRL/USD na Dashboard (legenda semântica).

---

## Dual-currency display — pattern (Spec 41)

Em **Hero Views** (Dashboard, Patrimônio, Snapshot detail/list),
valores monetários agregados aparecem com **BRL principal + USD em dim
embaixo**. Sem toggle, sem preferência salva. Quem só pensa em BRL
ignora a sub-linha; quem quer pensar em USD olha um pixel pra baixo.

### Classes canônicas

```tsx
// Tile / KPI canonical:
const dualMainCls = "text-sm font-semibold tnum money";
const dualSubCls  = "text-[10px] tnum money text-gray-500 dark:text-gray-600 mt-0.5";

// Hero big number:
<div className="text-4xl lg:text-5xl font-semibold tracking-tight tnum money">
  {fmtBRL(value)}
</div>
{ptaxRate && (
  <div className="mt-1 flex items-baseline gap-2">
    <div className="text-base text-gray-500 tnum money">
      {fmtUSD(value / ptaxRate)}
    </div>
    <span className="text-[11px] text-gray-500">PTAX R$ {ptaxRate.toFixed(4)}</span>
  </div>
)}

// Table cell 2-line:
<td className="px-2 text-right">
  <div className="tnum money font-medium">{fmtBRL(value, { compact: true })}</div>
  <div className="tnum money text-[10px] text-gray-500 dark:text-gray-600">
    {fmtUSD(value / ptaxRate, { compact: true })}
  </div>
</td>
```

### Conversão "agora" vs "época"

- **Estado atual** (Dashboard, Patrimônio): usa `ptax_rate` retornado
  pelo endpoint `/portfolio` (PTAX do último dia útil disponível —
  fonte canônica do dia).
- **Estado histórico** (Snapshot detail, Snapshot list): usa
  `snap.fx_rate_usd_brl` carimbado no snapshot da época. **Não
  recalcular** com PTAX de hoje — seria revisionismo de valor.

### Out of scope

- **Toggle global BRL↔USD** — não existe. Reabrir como spec maior se
  virar pedido recorrente.
- **Conversão em tabelas densas** (Lançamentos, Proventos,
  AssetMovements, CreditCardInvoices) — cada linha mostra `ccy`
  original; dual ali poluiria 30+ rows por viewport.
- **Conversão em fields de input** (composers) — strike de PUT em BRL
  não vira "$X" no input.

---

## Locality de helpers monetários

`fmtBRL` / `fmtUSD` / `fmtMoney` estão **definidos localmente em cada
página** que precisa (Dashboard.tsx, Portfolio.tsx, SnapshotDetail.tsx).
**Não promover** pra util compartilhado enquanto < 5 lugares adotam o
mesmo helper. Quando passar disso, mover pra `frontend/src/lib/format.ts`
ou similar.

Helpers seguem convenção de locale:
- BRL → `pt-BR`, símbolo `R$`, compact = "mi/bi"
- USD → `en-US`, símbolo `$`, compact = "K/M"

---

## Mantenedor do padrão

Toda nova PR que toca valores monetários em hero/list/detail **deve
citar essa regra** ao justificar uso (ou não) de `<CcyPill>`. Code review
checklist:

- Hero / KPI / tile com agregado: dual-display, **sem pill**.
- Detail panel com campo "Moeda": pill OK.
- Tabela densa com coluna `ccy`: `fmtMoney(value, ccy)` na célula,
  **sem pill** por linha.
- Pill como marcador de exceção (USD numa lista BRL implícita): OK,
  mas justificar.
