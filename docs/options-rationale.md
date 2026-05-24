# Options & Synthetic Dividend — Rationale

> Modelo conceitual + UX pra suportar **opções vendidas** (covered call,
> cash-secured put) e o conceito de **dividendo sintético** (prêmio
> recebido como renda visível, mas separado de DY/YoC dos ativos
> subjacentes).
>
> Status: aprovado com o usuário em 2026-05-06. Pronto pra virar spec.

---

## 1. Mental model

Uma **opção** é um derivativo de um ativo subjacente. No nosso sistema,
modelamos como **Asset** de classe nova `OPTION`, com FK pro underlying.
Isso reusa toda a infra de movements, posição, account, notes, etc.

O **prêmio recebido** ao vender uma opção é um **fluxo de caixa positivo**
que o usuário considera "dividendo sintético" — visível na página de
Proventos sob categoria própria (`OPTION_PREMIUM`), mas **NÃO entra no
DY/YoC do underlying**. Isso preserva a integridade dessas métricas
(que medem performance do ativo, não da estratégia de opções sobre ele).

No vencimento, a opção ou:
- **Vira pó** (`EXPIRED`): qty da opção → 0; sem outro impacto.
- **Vira exercida/atribuída** (`EXERCISED` / `ASSIGNED`): qty da opção
  → 0; **dispara automaticamente** um BUY ou SELL no underlying, com
  preço efetivo = strike ± prêmio_por_ação.

---

## 2. Asset class `OPTION`

Adicionar `OPTION` como 12ª asset class. Características:

```
Asset (quando asset_class = OPTION):
  underlying_id       FK → Asset (NOT NULL pra OPTION; NULL pra qualquer outra)
  option_type         enum CALL | PUT (NOT NULL pra OPTION)
  strike_price        Decimal (NOT NULL pra OPTION)
  expiration_date     Date (NOT NULL pra OPTION)
  contract_size       int default 100 (BR padrão; pode variar em mercados US)
```

Outras consequências:

- `country` herda do underlying (ex: PETR4 → BR; AAPL → US)
- `currency` herda do underlying
- `account_id` tipicamente é a mesma conta de investimento onde o
  underlying está custodiado (ex: ITUBR364 na conta XP, mesma conta do
  ITUB4)
- `ticker` é o código da opção (`PETRG520`, `ITUBR364`, etc.)
- `is_active` segue padrão: `true` enquanto a opção existe; `false`
  após `EXPIRED` ou `EXERCISED`

**Display defaults:**
- Página `/ativos` **exclui opções por padrão**, com toggle "Incluir
  opções" pra mostrar (junto com "Incluir zerados")
- Página `/ativo/{underlying_id}` ganha um card "**Opções abertas sobre
  este ativo**" listando todas as opções `OPTION` com `underlying_id`
  apontando pra ele e `is_active = true`
- Opções têm preço médio = prêmio recebido (negativo se prêmio entrou),
  preço atual = mark-to-market via brapi se possível

---

## 3. AssetMovement types — adições

Novos tipos no enum `AssetMovementType` pra cobrir o ciclo de vida das
opções:

| Tipo | Direção | Quando | Efeito |
|---|---|---|---|
| `SELL_OPEN` | venda pra abrir | Você vende uma opção (covered call ou cash-secured put) | qty da opção: + contratos × contract_size (modelado como posição negativa na visualização: você está short) · net_amount: + prêmio_recebido |
| `BUY_TO_OPEN` | compra pra abrir | Você compra uma opção (proteção / hedge / call de aposta) | qty da opção: + contratos × contract_size · net_amount: − prêmio_pago |
| `SELL_TO_CLOSE` | venda pra fechar | Recompra de uma opção que você tinha comprado | qty: − contratos × contract_size · net_amount: + valor_vendido |
| `BUY_TO_CLOSE` | compra pra fechar | Recompra de uma opção vendida (encerra cedo) | qty: − contratos × contract_size · net_amount: − valor_pago |
| `EXERCISED` | exercido contra você | Vencimento de opção vendida que ficou ITM | qty da opção → 0; **dispara movement no underlying** (ver §4) |
| `ASSIGNED` | atribuído | Sinônimo de EXERCISED em alguns contextos (mercado US distingue) — pra BR vamos usar `EXERCISED` sempre |
| `EXPIRED` | expirou worthless | Vencimento de opção OTM (virou pó) | qty da opção → 0; sem outro impacto |

> **Nota sobre posição:** modelar opção vendida com qty positiva e
> rastrear "short" via metadado (ex: `is_short` flag derivado do tipo do
> primeiro movement) é mais limpo do que usar qty negativa. Decisão de
> implementação: a posição computada de uma opção é
> `Σ SELL_OPEN.qty + Σ BUY_TO_OPEN.qty − Σ SELL_TO_CLOSE.qty − Σ BUY_TO_CLOSE.qty − Σ EXERCISED.qty − Σ EXPIRED.qty`.
> Pra opções vendidas, a posição "aberta" é o resultado de
> `SELL_OPEN − BUY_TO_CLOSE − EXERCISED − EXPIRED`.

### 3.1 "Abrir" vs "fechar" — em PT plano

A nomenclatura inglesa (`*_OPEN`, `*_TO_CLOSE`) parece densa, mas é só duas
distinções ortogonais: **direção** (vender/comprar) × **estado** (abrir
nova posição vs fechar posição existente).

**Os 2 tipos de "abrir" (originação)**

- **Vender pra abrir** (`SELL_OPEN`, jargão B3: "lançar opção"): você
  vende a opção sem possuí-la, fica short. Recebe prêmio na hora. Aposta
  que a opção vai virar pó. Risco: exercício te força a comprar (PUT
  vendida) ou vender (CALL vendida) o underlying pelo strike.
- **Comprar pra abrir** (`BUY_TO_OPEN`): você compra a opção, paga prêmio,
  fica long. Aposta que a opção vai ficar valiosa. Perda máxima limitada
  ao prêmio pago.

São os únicos tipos que aparecem na **criação inicial** da opção —
`OptionModal` mostra esses 2 na dropdown "Tipo operação".

**Os 4 tipos de "fechar" / vencimento**

`SELL_TO_CLOSE` / `BUY_TO_CLOSE` fecham uma posição **antes** do
vencimento; `EXERCISED` / `EXPIRED` são o que **acontece** no vencimento.

Estes 4 **não aparecem como tipo escolhido pelo usuário num composer**:

- `EXERCISED` / `EXPIRED` são botões no `OpenOptionsCard` (no detail do
  underlying): "Marcar exercida" / "Marcar vencida".
- `SELL_TO_CLOSE` / `BUY_TO_CLOSE` ficam pra spec dedicada futura
  ("Fechar posição cedo") — ainda não há fluxo no UI.

### 3.2 Onde cada tipo aparece na UX (revisão 2026-05-23)

| Tipo | Composer / fluxo | Origem |
|---|---|---|
| `BUY` / `SELL` / `BONUS` / `SUBSCRIPTION` / `COME_COTAS` / `FULL_REDEMPTION` | `MovementComposer` (dropdown Novo → Lançamento) | spec 18 |
| `SELL_OPEN` / `BUY_TO_OPEN` | `OptionModal` aberto via "+ Opção" no `AssetDetail` ou "+ Nova opção" no `OpenOptionsCard` | spec 17 |
| `EXERCISED` / `EXPIRED` | botões no `OpenOptionsCard` (Marcar exercida / vencida) | spec 17 |
| `SELL_TO_CLOSE` / `BUY_TO_CLOSE` | sem fluxo no UI hoje — spec dedicada futura | TBD |

**Razão da divisão:** o `MovementComposer` mostra os 6 tipos comuns num
grid 3×2 (espelhando o protótipo `index.html:4242-4387`). Misturar os 12
tipos lá polui a tela sem clareza. Opção é um asset distinto com fluxo
próprio.

### 3.3 Sync Notion — option types ficam fora (decidido 2026-05-23)

A base original do Notion (importada via spec 07b) só tem as 6 opções de
`Tipo Transação` clássicas. **Movimentos com `type IN (SELL_OPEN,
BUY_TO_OPEN, SELL_TO_CLOSE, BUY_TO_CLOSE, EXERCISED, EXPIRED)** são
**bloqueados no push pra Notion** — option lifecycle nasceu nesta base, é
conceito novo que o Notion original não modela.

Implementação:
- `services/notion_sync.py::push_asset_movement` detecta option type e
  retorna `SKIPPED` antes de chamar Notion.
- Movimentos skipped não aparecem no contador "Sync Notion (N)" — o
  query de pendentes ignora.
- Pull do Notion não é afetado (option types só são criados aqui).

Se algum dia o Notion source de verdade ganhar opções, reabilitar é uma
linha — remover o early return.

---

## 4. Exercise price adjustment — a regra crítica

Quando uma opção vendida é exercida, o sistema gera automaticamente um
movement no underlying com **preço efetivo = strike ± prêmio_por_ação**:

| Tipo da opção | Direção do underlying | Preço efetivo |
|---|---|---|
| PUT vendida | BUY (você é forçado a comprar) | `strike − prêmio_por_ação` |
| CALL vendida | SELL (você é forçado a vender) | `strike + prêmio_por_ação` |

**Por quê:** o prêmio já foi recebido na venda. No exercício, o cash
que sai/entra é apenas a parcela do strike. O "preço efetivo de
mercado" do ativo, do ponto de vista de quanto você efetivamente pagou
ou recebeu, é o strike ajustado pelo prêmio.

**Exemplo 1 — PUT exercida:**
- Você vende ITUBR364 (PUT ITUB4 strike R$ 36,40) por R$ 0,09/ação ×
  1.000 = R$ 90 recebidos
- ITUB4 cai pra R$ 33 em 19/06 → você é exercido (forçado a comprar
  1.000 ITUB4 a R$ 36,40, pagando R$ 36.400)
- Sistema cria automaticamente:
  - `EXERCISED` no ITUBR364: qty → 0
  - `BUY` no ITUB4: qty = 1.000, **price = R$ 36,31** (36,40 − 0,09)
  - Notes do BUY: `"Exercício de ITUBR364 · prêmio R$ 0,09/ação deduzido do strike"`
  - `notes` do EXERCISED: `"Underlying adquirido via BUY id=<movement_id>"`

**Exemplo 2 — CALL exercida:**
- Você vende ITUBF475 (CALL ITUB4 strike R$ 47,50) por R$ 0,34/ação ×
  1.000 = R$ 340 recebidos
- ITUB4 sobe pra R$ 50 em 19/06 → você é exercido (forçado a vender
  1.000 ITUB4 a R$ 47,50, recebendo R$ 47.500)
- Sistema cria automaticamente:
  - `EXERCISED` no ITUBF475: qty → 0
  - `SELL` no ITUB4: qty = 1.000, **price = R$ 47,84** (47,50 + 0,34)

**Vantagem:** o preço médio do ITUB4 (no caso da PUT) ou o resultado da
venda (no caso da CALL) já refletem o ganho com o prêmio. Não precisa
mental math.

**Detalhe schema:** `AssetMovement.related_movement_id` (nullable, self-FK
opcional) liga o BUY/SELL do underlying ao EXERCISED da opção. Útil pra
auditoria e pra mostrar "puxado de qual opção" no UI.

---

## 5. Synthetic dividend — Opção B com tipificação

A página `/proventos` faz **UNION** entre:
- `DISTRIBUTIONS` (eventos clássicos: DIVIDEND, INTEREST, JCP, SECURITIES_LENDING)
- `MOVEMENTS WHERE type IN (SELL_OPEN, BUY_TO_CLOSE)` (eventos de cash de opções)

Com uma categoria visual nova `OPTION_PREMIUM`:

- `SELL_OPEN` → categoria `OPTION_PREMIUM`, sinal positivo (prêmio recebido)
- `BUY_TO_CLOSE` → categoria `OPTION_PREMIUM`, sinal negativo (custo do encerramento)

**Não duplicamos no schema** (nenhuma Distribution criada
automaticamente). É só uma view/query.

### Regras que essa categoria respeita

1. **NÃO entra em DY/YoC** do underlying. Fórmulas existentes filtram
   explicitamente `type IN (DIVIDEND, INTEREST, JCP, SECURITIES_LENDING)`.
2. **Conta em "Proventos recebidos · 12M"** do Dashboard, MAS com toggle
   "Incluir dividendos sintéticos" (default ON, mas user pode esconder).
3. **Tem KPI próprio** em /proventos: "Dividendo sintético · 12M".
4. **Cor visual diferente** das categorias clássicas (proposta: violet,
   já que amarelo é Aluguel e verde/azul são dividendos/juros).

---

## 6. BR option ticker parser

O código de uma opção BR contém quase tudo que precisamos:

```
[4-letter prefix] + [1 letter] + [3-4 digit strike] + [optional adjustment letter]
       PETR        +     R      +       520         +         W (se ajustada)
```

**Letras de mês + tipo:**

| Mês | CALL | PUT |
|---|---|---|
| Jan | A | M |
| Fev | B | N |
| Mar | C | O |
| Abr | D | P |
| Mai | E | Q |
| **Jun** | **F** | **R** |
| Jul | G | S |
| Ago | H | T |
| Set | I | U |
| Out | J | V |
| Nov | K | W |
| Dez | L | X |

**Vencimento:** sempre na **3ª sexta-feira** do mês (BR).

**Strike:** numérico, com convenção dependente do preço do underlying.
Pra ITUB4 (faixa R$ 30-40), `364` = R$ 36,40 (divide por 10). Pra PETR4
em faixa R$ 30-40, `360` = R$ 36,00 ou `36` = R$ 36,00 dependendo da
série. **Parser deve sempre pedir confirmação do strike**, mas pode
sugerir baseado no preço do underlying.

**Strike ajustado:** quando o underlying paga dividendo grande,
a B3 ajusta o strike e o código ganha uma letra final (W, X, etc.).
Exemplo: `PETRG520` → após ajuste → `PETRG5W` (strike vira algo como
R$ 5,17 — irregular). Parser detecta o sufixo e pede confirmação manual
do strike novo.

### Composer flow

1. Usuário cola código: `ITUBR364`
2. Parser extrai:
   - prefix → busca underlying no portfolio do user → `ITUB4` (se houver
     ambiguidade ITUB3 vs ITUB4, pergunta)
   - letter R → PUT, mês de junho
   - dígitos 364 → sugere R$ 36,40 (pede confirmação)
   - sufixo nenhum → strike limpo
   - vencimento → 3ª sexta de junho do ano corrente ou próximo
3. Pergunta o que faltou:
   - quantidade (em ações, não contratos — segue padrão da corretora)
   - prêmio recebido por ação
   - tipo de operação (default `SELL_OPEN`)
4. Se brapi tiver mark-to-market da opção, mostra "preço atual: R$ 0,12"
   ao lado pra contextualizar

---

## 7. Workflow de vencimento

Sistema track expirations e ajuda o usuário a resolver:

### 7 dias antes do vencimento

Notification badge na sidebar / dashboard:

> **Opções vencendo em 7 dias**
> · ITUBR364 (PUT R$ 36,40) — preço atual R$ 33,20 → provável exercício
> · ITUBF475 (CALL R$ 47,50) — preço atual R$ 33,20 → provável virar pó

Cada linha clicável → preview de "se exercida, vou ter que..." / "se
virar pó, ganho R$ X".

### No dia do vencimento (ou D+1)

Modal/wizard "Como foi o vencimento?":

```
┌─────────────────────────────────────────────────────┐
│  Vencimento · 19/06/2026                            │
│  ─────────────────────────────────────────────      │
│                                                     │
│  ITUBR364 (PUT ITUB4 strike R$ 36,40)              │
│  Preço de fechamento ITUB4: R$ 33,20                │
│                                                     │
│  ○ Foi exercida (eu comprei 1.000 ITUB4 @ 36,40)   │
│  ○ Virou pó (mantive os R$ 90 do prêmio)           │
│                                                     │
│  ─────────────────────────────────────────────      │
│  ITUBF475 (CALL ITUB4 strike R$ 47,50)              │
│  Preço de fechamento ITUB4: R$ 33,20                │
│                                                     │
│  ○ Foi exercida (eu vendi 1.000 ITUB4 @ 47,50)     │
│  ● Virou pó (mantive os R$ 340 do prêmio)          │  (suggested)
│                                                     │
│                          [Cancelar] [Confirmar]    │
└─────────────────────────────────────────────────────┘
```

Sistema **sugere** o default baseado em preço strike vs preço de
fechamento, mas o user confirma (caso o broker tenha algum
behavior incomum).

Ao confirmar:
- Pra cada opção EXERCISED: cria o EXERCISED no asset opção +
  BUY/SELL no underlying com preço efetivo
- Pra cada opção EXPIRED: cria o EXPIRED no asset opção

---

## 8. Naked options — warning, sem bloqueio

Detecção no composer:

| Operação | Cobertura esperada | Detecção |
|---|---|---|
| `SELL_OPEN` CALL | Você precisa ter ≥ contratos × contract_size do underlying na mesma conta | Comparar qty da CALL × contract_size com posição atual do underlying |
| `SELL_OPEN` PUT | Você precisa ter ≥ strike × contratos × contract_size em cash na conta | Comparar potencial obrigação com float da conta de investimento |

Se cobertura insuficiente:

```
⚠️ Esta operação está descoberta

  Você está vendendo 10 CALLs de ITUB4 strike R$ 47,50.
  Sua posição em ITUB4 é de 800 ações; precisa de 1.000 pra cobrir.

  Se exercida, você terá que comprar 200 ITUB4 a mercado pra entregar
  (risco de prejuízo).

  ☐ Entendi e quero prosseguir mesmo assim
                                  [Cancelar] [Lançar mesmo assim]
```

Checkbox obrigatório de confirmação. Audit log registra "naked option
sold" pra rastreio.

---

## 9. Roll over — sequencial por enquanto

Roll over não tem composer dedicado. É:

1. `BUY_TO_CLOSE` na opção atual (recompra antes do vencimento)
2. `SELL_OPEN` numa opção nova (geralmente com vencimento mais longe)

Pra V2+: o sistema pode **detectar** que dois movements em sequência
constituem um roll e oferecer um modo "registrar como roll" que cria os
dois com link entre eles. Por enquanto, é manual.

Pra V3+: o widget de "vencimento próximo" pode **sugerir** opções
candidatas pra roll baseado em vencimentos futuros + probabilidades.
Requer brapi options chain.

---

## 10. Mark-to-market e brapi

Brapi tem endpoint de **option chains** (verificar atual:
`https://brapi.dev/docs/`). Quando disponível:

- Sistema busca preço atual (bid/ask/last) de cada opção aberta
- Mostra "valor de fechamento" da posição no momento atual (positivo se a
  opção vendida ainda vale, negativo se já passou do strike contrário)
- Calcula "lucro/prejuízo se fechasse agora" = prêmio_recebido −
  preço_atual × qty

Se brapi não tiver: campo manual `current_price` com `price_updated_at`,
igual qualquer outro asset.

---

## 11. Schema additions

### `Asset` (novos campos, todos NULL exceto pra OPTION)

- `underlying_id` FK → Asset (NULL pra non-option)
- `option_type` enum CALL | PUT (NULL pra non-option)
- `strike_price` Decimal (NULL pra non-option)
- `expiration_date` Date (NULL pra non-option)
- `contract_size` int (NULL pra non-option; default 100 quando OPTION)

### `AssetMovement` (novos type enum values)

- `SELL_OPEN`
- `BUY_TO_OPEN`
- `SELL_TO_CLOSE`
- `BUY_TO_CLOSE`
- `EXERCISED` (covers BR; US "assigned" também mapeado aqui)
- `EXPIRED`

E o campo novo:
- `related_movement_id` FK → AssetMovement (nullable, self-FK). Liga o
  BUY/SELL no underlying ao EXERCISED da opção que o disparou.

### `KLASS` enum

- Adicionar `OPTION` (12ª classe)

Cor proposta: `#a855f7` (purple-500) — distinguir do amarelo (CRYPTO),
verde (REIT/FII), azul (STOCK).

### View / query layer (não é tabela)

- View materializada ou query helper `proventos_unificados`:

```sql
SELECT id, d, 'distribution' AS source, fi_id, asset_id, type, net, ccy, fx_rate
FROM distribution
WHERE is_active = true
UNION ALL
SELECT id, event_date AS d, 'option_premium' AS source,
       (SELECT financial_institution_id FROM account WHERE id = (SELECT account_id FROM asset WHERE id = mv.asset_id)) AS fi_id,
       (SELECT underlying_id FROM asset WHERE id = mv.asset_id) AS asset_id,
       'OPTION_PREMIUM' AS type,
       net_amount AS net, currency AS ccy, fx_rate
FROM asset_movement mv
WHERE type IN ('SELL_OPEN', 'BUY_TO_CLOSE')
  AND is_active = true;
```

---

## 12. Tributação — pointer pra future spec

Opções têm regime tributário próprio em BR (15% sobre ganho mensal sem
isenção R$ 20k, IRRF de 0,005% na fonte) — diferente de stocks e FIIs.

**Não tratamos tributação dentro desta spec.** Será uma spec dedicada
mais ampla cobrindo:
- Apuração mensal de IR (DARF) por tipo de ativo
- Isenções (FII proventos, stocks < R$ 20k mês, LCI/LCA)
- Tabela regressiva renda fixa
- Dividend US 30% retido na fonte
- Geração de relatório DIRPF anual

Por enquanto, opções entram com `tax` field opcional no AssetMovement —
user pode preencher se quiser começar a padronizar daqui em diante.

---

## 13. Dois casos reais do usuário (referência)

Operações abertas em 06/05/2026, vencimento 19/06/2026:

| Código | Tipo | Underlying | Strike | Qtd | Prêmio/ação | Total | Conta |
|---|---|---|---|---|---|---|---|
| ITUBR364 | PUT (R = Jun) | ITUB4 | R$ 36,40 | 1.000 | R$ 0,09 | R$ 90,00 | XP investimento |
| ITUBF475 | CALL (F = Jun) | ITUB4 | R$ 47,50 | 1.000 | R$ 0,34 | R$ 340,00 | XP investimento |

⚠️ **Confirmar strikes com o usuário** — R$ 36,40 e R$ 47,50 são parse
mais provável dado o preço atual da ITUB4. Se na execução de spec esses
strikes saírem diferentes, ajustar.

Total prêmio: R$ 430. Em /proventos vai aparecer categorizado como
`OPTION_PREMIUM`, contando em "Proventos recebidos 12M" mas excluído de
qualquer DY/YoC do ITUB4.

---

## 14. Phasing sugerido

### V1 (1 spec backend + 1 spec frontend)

- Schema: Asset class OPTION + 4 novos AssetMovement types
  (SELL_OPEN, BUY_TO_OPEN, BUY_TO_CLOSE, SELL_TO_CLOSE, EXERCISED, EXPIRED)
  + related_movement_id
- Composer dedicado OptionComposer com parser BR
- Card "Opções abertas" no Asset detail do underlying
- Categoria OPTION_PREMIUM em /proventos (via UNION)
- Naked options warning
- Wizard de vencimento

### V1.5

- Mark-to-market via brapi options endpoint
- Notification 7 dias antes do vencimento
- Roll detection sugestão

### V2

- US options support (formato OCC distinto)
- Probabilidade ITM via Black-Scholes (precisa de volatilidade)
- Sugestões de roll (precisa de chain)

### Future (spec própria)

- Tributação opções (parte da spec geral de IR)

---

*Aprovado em 2026-05-06. Atualizar conforme implementação revelar
ajustes necessários.*
