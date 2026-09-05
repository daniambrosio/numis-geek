# TODO — pendências entre sessões

Arquivo vivo de pendências que atravessam sessões de trabalho. Convenções:
`[user]` = ação do Daniel · `[claude]` = ação do Claude na próxima sessão pertinente ·
item concluído ou dropado sai daqui e vai pro `TODO-done.md` (com data).

## Anexos de fechamento sem slot (pós-fix 8875a1e, 2026-09-05)

- [ ] `[user]` **17 anexos de fechamento em prod sem instituição/finalidade** (mai/26: 6,
  jun/26: 3, jul/26: 6, ago/26: 2 — `PosicaoDetalhada (5).xlsx` e `Caixa Screenshot
  2026-09-01 at 10.01.45.png`). Ficam invisíveis em todos os blocos por FI. Decidir:
  (a) bucket "Sem instituição" na página do fechamento com dropdown FI + finalidade
  (Claude implementa; endpoint PATCH /attachments/{id}), ou (b) mandar o mapeamento
  arquivo→FI/finalidade e Claude aplica via SQL cirúrgico. Lista completa: query
  `attachment.source_type='SNAPSHOT' AND institution_id IS NULL`.
- [ ] `[claude]` Após decisão acima, revisar se anexos de meses CLOSED devem aparecer
  no bloco por FI mesmo sem extração (hoje o bloco só existe na página do fechamento).

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

- [x] ~~**Spec 79 — resgate reduz o custo proporcionalmente.**~~ FEITA em 2026-09-05
  (`832d45b`). Modo valor: custo cai pela fração que saiu da posição, com o valor de
  referência vindo do último fechamento CLOSED anterior + os fluxos desde então; piso em 0.
  Modo cotado: SELL reduz `basis_qty`/`basis_cost_*` proporcionalmente — conserta o PM que
  carregava para sempre as ações vendidas no denominador (compra após venda) e o BONUS
  pós-venda-parcial (Klabin). 125 itens congelados em 12 ativos recomputados.
  Validação externa: LFT mar/2028 dá 4.349,30 contra 4.354,68 do Notion legado.
  Backup `numis_geek.db.bak-before-spec79-20260905-154759`.

- [ ] `[user]` **`Tesouro Selic 2031` — o ativo não fecha, independente da spec 79.**
  Σ aportes − Σ resgates = R$ 592.194,64 contra valor de mercado de R$ 277.319,70 em ago/26
  — prejuízo impossível num Selic. **Segurado fora do recompute da spec 79** (daria
  411.408,40) até entender o dado. Dois indícios:
  - o fechamento de jan/26 traz R$ 426.941,23 e não inclui o aporte de R$ 599.840,00 de
    30/01/2026 (o de fev/26 já inclui) — valor do fechamento provavelmente digitado antes
    do aporte;
  - 25/03/2026 tem um par espelhado: BUY gross 407.963,77 / net 408.728,10 e SELL gross
    408.728,10 / net 407.963,77. Parece uma rolagem lançada como duas pernas. Se for,
    provavelmente deveria ser um lançamento só (ou nenhum).

- [ ] `[user]` **`FGTS - Carrefour` — saque com data descompassada do extrato.**
  O saque de R$ 30.660,98 está lançado em 02/06/2025, mas o fechamento de 31/05/2025 já
  mostrava R$ 3.747,92: o saldo caiu antes da data do lançamento. Pela regra da spec 79 a
  fração dá > 100% e zera o custo, então **segurei fora do recompute** (ficou em
  −R$ 1.390,46, o único invested negativo que sobrou). Decidir: corrigir a data do saque
  para maio/2025, ou corrigir o valor do fechamento de maio.

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
- [x] ~~**Nubank — conta reativada.**~~ Cadastrado em 2026-09-05 (spec 80): conta
  investimento + conta corrente, `Tesouro IPCA+ 2032 (Nubank)`, `Caixinha Nubank` e
  `Saldo em Conta (Nubank)`, com os lançamentos de 05–07/08 e os itens no fechamento
  de ago/26.

- [ ] `[claude]` **Spec 80 fase 2 — junto com a spec 70.** Com `transaction` no ar, o
  fechamento passa a puxar o saldo derivado (`opening_balance` + Σ transactions) dos 5
  ativos CASH que hoje têm `linked_account_id`, em vez do valor digitado. E os 3 fluxos
  de caixa desativados na fase 1 viram `transaction`:
  `Saldo em Conta (Wise)` BUY R$ 6.050,00 (01/12/2025) e SELL R$ 4.600,00 (10/07/2026);
  `Saldo em Conta Nomad` BUY US$ 1.007,38 (27/06/2026). A UI pra gerenciar o vínculo
  também entra aí (hoje são 5 ativos e o vínculo não muda).

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
