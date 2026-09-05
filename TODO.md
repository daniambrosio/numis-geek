# TODO — pendências entre sessões

Arquivo vivo de pendências que atravessam sessões de trabalho. Convenções:
`[user]` = ação do Daniel · `[claude]` = ação do Claude na próxima sessão pertinente ·
item concluído ou dropado sai daqui e vai pro `TODO-done.md` (com data).

## Fechamento e cost basis (pós-fix bonificação d2b14f6)

- [x] ~~**Fechamento Ago/26 — degrau de PM/invested.**~~ RESOLVIDO em 2026-09-05 por
  decisão do user: em vez de conviver com o degrau, os meses fechados foram recomputados.
  O `invested`/`average_cost_brl` congelado de 223 itens (19 ativos) foi corrigido —
  9 cotados que divergiam por causa do `d2b14f6` (BTHF11, ITSA4, BTC, EGIE3, AURE3,
  KLBN11, ITUB4, BHIA3) + 11 de modo valor com invested legado errado. Não existe mais
  degrau: dez/24→ago/26 usam o mesmo algoritmo. Backup
  `numis_geek.db.bak-before-frozen-invested-20260905-144907`.
- [ ] `[user]` **Notion legado — bonificações ITUB4 com Preço Unit. = 0.** O Notion nunca
  teve o valor de incorporação (R$ 34,00 mar/2025 · R$ 40,00 dez/2025). Corrigir lá só
  se quiser consistência do histórico legado; o numis-geek já está correto.
- [ ] `[claude]` **Spec nova: SELL parcial deve reduzir basis proporcionalmente.** Audit
  adversarial do d2b14f6 apontou: convenção "SELL não reduz basis_qty" + BONUS infla
  `total_invested` (ex.: BUY 100@30, SELL 50, BONUS 50 → invested 2.000 vs fiscal 1.500).
  Pré-existente e ficou MENOR com o fix, mas merece spec própria — impacto em IR de
  ganho de capital. Antes da spec, escrever teste-caracterização travando o
  comportamento atual (hoje não há teste documentando o invested inflado).

## Specs pausadas / em andamento

- [ ] `[claude]` **Spec 59 (Comparativo) — retomar da Fase 0.1.** Protótipo da 1ª tela
  plantado e funcionando; 3 perguntas de UX em aberto pro user; fila Fases 0.2→6 pendente.
  Contexto completo de retomada na memory `session_state_spec_59_fase_0_1`.
- [ ] `[claude]` **Spec 65 — Fase 1 (cleanup backend) — ANTES do fechamento Ago/26.**
  ~60% entregue (frontend em 25c7bfd/93c80d2); falta deletar o legado SUSPICIOUS_DELTA —
  enum, `detect_suspicious_deltas`, endpoints, testes e migration de drop. NÃO é
  dormente (audit 2026-08-18): `detect_suspicious_deltas` roda em toda criação de
  snapshot (`services/snapshot.py:477`) e rebaixa CLOSED→IN_REVIEW; o PendencyPanel
  exibe o detail cru dessas pendencies. Sem o cleanup, Ago/26 cria pendencies com
  JSON cru no painel.
- [ ] `[user]` `[claude]` **Spec 66 em Draft — retomar entrevista/implementação.**
  66 = crypto rewards pagos em cripto (in-kind). (Spec 64 saiu Done em 2026-09-05.)

- [ ] `[user]` `[claude]` **Spec nova: resgate em modo valor deve reduzir o custo
  proporcionalmente.** É a única causa de invested negativo que sobrou. Hoje o SELL subtrai
  o `gross` inteiro do invested — mas o resgate leva principal E rendimento, então resgatar
  o que rendeu derruba o custo abaixo de zero. Casos vivos:
  - `Tesouro Selic 2029` (−R$ 14.323,49 · mai–ago/26): histórico completo — aportes de
    R$ 179.830,65 (abr/23, abr/24, set/24), resgates de R$ 144.000 (10/07/25) e
    R$ 50.154,14 (19/05/26), ainda R$ 43.087,70 em carteira.
  - `FGTS - Carrefour` (−R$ 1.390,46 · jun–ago/26): resíduo pós saldo de abertura, do saque
    aniversário de R$ 4.466,45 sobre um saldo de ~R$ 4.550.
  Regra proposta: `basis -= basis × (gross_resgate / MV_na_data_do_resgate)`, com o MV vindo
  do último fechamento antes do resgate. É o que o Notion legado fazia (LFT mar/2028:
  resgate de ~10% do saldo → 4.838,535 × 0,9 = 4.354,68). Simulação com essa regra:
  Selic 2029 → 144.000/225.000 = 64% ⇒ basis 64.739,03; depois 50.154,14/91.037,98 = 55,1%
  ⇒ **basis 29.074,26** contra valor de R$ 43.087,70. Carrefour → **~R$ 58** contra
  valor R$ 86,17. Casa com o item "SELL parcial deve reduzir basis proporcionalmente" logo
  acima — provavelmente é UMA spec só, cobrindo cotado e modo valor.

- [x] ~~**Saldo de abertura de FGTS e Wise.**~~ FEITO em 2026-09-05 por decisão do user:
  BUY de abertura no 1º dia do primeiro mês acompanhado, com o valor do fechamento desse
  mês (investido == valor no primeiro fechamento, rentabilidade começa do zero).
  FGTS - Carrefour R$ 35.172,00 (01/12/2024) · FGTS - Meli R$ 504.635,36 (01/12/2024) ·
  Saldo em Conta (Wise) R$ 6.050,00 (01/12/2025). A decisão está anotada no campo `notes`
  de cada ativo. Meli (R$ 523.205,02) e Wise (R$ 1.450,00) ficaram positivos; Carrefour
  ainda −R$ 1.390,46, que só o resgate proporcional resolve.
  Backup `numis_geek.db.bak-before-opening-balances-20260905-152132`.

- [ ] `[user]` **"Saldo em Conta não tem aporte por design" — revisar.** O Wise mostrou que
  conta com câmbio tem sim aportes. A regra atual (CASH sempre presente no fechamento,
  saldo digitado, invested 0) foi mantida, mas com saldo de abertura por cima. Rever quando
  a trilha de câmbio for tratada.
- [ ] `[user]` **Nubank — conta reativada, não está no sistema.** A instituição financeira
  `Nubank` existe e está ativa, mas **não tem nenhuma conta cadastrada** — logo, nenhum
  ativo, logo nada no fechamento de 2026. Não é bug: o cadastro nunca foi feito. Pra
  incluir: criar a(s) conta(s) (investimento e/ou corrente) e os ativos — 2 investimentos
  + saldo em conta —, e lançar o saldo de abertura no mesmo padrão de FGTS/Wise.
  Faltam do user: nome/tipo da conta, nome e classe dos 2 investimentos, e os valores.

- [ ] `[user]` `[claude]` **`Terreno Paranapanema` em set/25 — item incoerente.** Único item
  pulado pela correção ampla: o terreno foi vendido em 2025-09-30 (SELL R$ 50.000, basis
  R$ 15 de um BONUS de 2004), mas o fechamento de set/25 ainda carrega o item com
  quantidade 0 e valor de mercado R$ 20.000. Recomputar daria qty 1 e invested
  −R$ 49.985,00 — ou seja, o item está errado de outro jeito e precisa de decisão: sai do
  fechamento de set/25 ou fica com que valor?
- [ ] `[user]` `[claude]` **Specs 68/69 — deltas do Done a decidir (audit 2026-08-18):**
  4 páginas sem `.test.tsx` próprio (CreditCards, CreditCardDetail — incl. fluxo
  "Fechar fatura" —, Categories, Parties) apesar de os deliverables prometerem testes;
  + badge de contagem no sidebar (spec 69) nunca feito; + spec 68 não reflete 4b014a6
  (badge de tipo em todas as subs). Entregar os gaps ou anotá-los como delta declarado
  no status das specs.

## Import / extração

- [ ] `[claude]` **Proventos sub-capturados (ITSA4/TAEE11/PETR4/BOVA11/IVV/AAPL).**
  Distribuições não vieram no bulk extract dos custodiantes — ITSA4 R$ 121k de posição
  rendeu R$ 350/ano (~95% faltando); TAEE11 idem. Plano: re-import CSV/PDF de proventos
  dos últimos 12m via BROKER_INCOME, validar extrator Avenue de proventos, e feature
  "Expected vs Actual dividends" por YOC histórico pra detectar sub-captura automática.
- [ ] `[claude]` **Matcher bulk-extract — 3 gaps** (detalhe na memory
  `matcher_bulk_extract_improvements`; código em `services/extraction.py:814`
  `_resolve_asset_by_ticker_or_name`): (1) cash accounts sem match — agregar linhas
  cash/saldo/banking no asset CASH único da FI; (2) tie-breaker quando dois bonds vencem
  na mesma data — keyword do issuer; (3) validação name×ticker na criação/edição de
  asset quando as datas divergem.
- [ ] `[claude]` **Spec 38 — prompts placeholder roteáveis em produção.**
  `services/extraction_templates/__init__.py:167` e `:304` têm prompts marcados
  "TODO Spec 38 — produção exige prompt validado", mas o serviço roteia pra eles.
  Validar os prompts ou bloquear o roteamento; spec está Done escondendo o gap.

## Segurança / produção

- [ ] `[claude]` **Encriptar `IntegrationCredential.secret_value` at rest.** TODO no
  código (`models/integration_credential.py:65`) com gate "before VPS deploy" — gate
  já vencido: prod roda no VPS desde 2026-06. Escrever a spec de segurança (memory
  `pending_security_spec`: encryption + rotation + rate limit) e implementar. Achado
  de maior impacto do audit 2026-08-18.

## Integridade de dados (prod)

- [ ] `[claude]` **3 `extraction_job` órfãos apontam pra `portfolio_snapshot`
  inexistente.** `PRAGMA foreign_key_check` no DB de produção acusa
  `extraction_job|1|portfolio_snapshot|2`, `|2|` e `|3|`. Pré-existente (já
  aparece no backup `.bak-before-cd-ticker-fix-20260905-122703`), não veio da
  faxina de 2026-09-05. Provável snapshot deletado sem limpar os jobs. Decidir
  entre `snapshot_id = NULL` ou apagar os jobs, e cobrir o caminho de deleção
  de snapshot pra não recriar órfãos.

## Higiene barata (lote único)

- [ ] `[claude]` Hints ComingSoon do `App.tsx` com numeração legada de spec (:57
  "Spec 23"→70, :61 "Specs 19+23", :66 "Spec 22"→76) · spec 67 sem `## ` no Status ·
  corpo da spec 73 defasado (97 subs e não 92, fluxo MCP+snapshot abandonado, nome do
  script diverge do deliverable) e Status omite o deliverable de testes ausente ·
  `snapshot.py:1465` referencia "spec 62.1" que não existe (fica moot se a spec 65
  deletar o legado).
