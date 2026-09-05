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

- [ ] `[claude]` **Spec nova: modo valor — `quantity` puramente informativa.** Proposta
  do user (2026-09-05), e concordo: em ativo de modo valor a quantidade pode existir como
  informação (nº de cotas do extrato), mas NADA de cálculo pode depender dela. Hoje ainda
  vaza: `compute_position` acumula `running_qty` (= nº de aportes, ex.: PGBL Flexprev
  qty=23, Tesouro Selic 2031 qty=5) e `asset_has_position` lê `qty != 0 or invested != 0`.
  Ninguém quebra hoje, mas um ativo de modo valor com invested=0 e nº de aportes ≠ nº de
  resgates fica preso no fechamento pra sempre. Fix: em modo valor, presença = `invested
  != 0` (ou classe CASH), e `quantity_held` vira campo informativo, nunca base de decisão.

- [ ] `[claude]` **Spec nova: resgate em modo valor deve reduzir o custo proporcionalmente.**
  Hoje SELL subtrai o `gross` inteiro do invested — mas o resgate carrega rendimento além
  do principal, então um resgate total deixa invested NEGATIVO. Caso limpo: `Tesouro Selic
  2029` tem histórico completo (aportes R$ 179.830,65 em 2023-04/2024-04/2024-09), resgates
  de R$ 144.000 + R$ 50.154,14 e ainda R$ 43.087,70 em carteira → invested −R$ 14.323,49.
  O Notion legado fazia proporcional (LFT mar/2028: resgate de ~10% do saldo → basis
  4.838,535 × 0,9 = 4.354,68). Regra proposta: `basis -= basis × (gross_resgate / MV_na_data)`,
  com o MV vindo do último snapshot fechado. Casa com o item "SELL parcial deve reduzir
  basis proporcionalmente" logo acima — provavelmente é UMA spec só, cobrindo cotado e
  modo valor.

- [ ] `[user]` **Saldo de abertura de FGTS.** `FGTS - Carrefour` (−R$ 36.562,46 em 14 meses)
  e `FGTS - Meli` (−R$ 1.083,91 em jun/26) ficam negativos porque o saldo que já existia
  quando o acompanhamento começou nunca foi lançamento — nem aqui, nem no Notion (lá o
  FGTS era saldo mensal, não aporte). Evidência: Meli tinha MV R$ 504.635,36 em dez/24 e o
  primeiro lançamento é um BUY de R$ 11.711,36 em set/25; Carrefour tinha MV R$ 35.172,00
  em dez/24 e o primeiro lançamento é um SELL. Não é falha do import. Fix: lançar um BUY
  de saldo de abertura na data de início do acompanhamento (dez/2024), com o valor do
  extrato do FGTS. Só o user tem esse número.

- [ ] `[user]` **`Saldo em Conta (Wise)` — SELL de R$ 4.600 (2026-07-10) num ativo CASH.**
  Ativos "Saldo em Conta" não têm aportes por design (o saldo é digitado a cada
  fechamento); os outros 5 têm invested = 0. Esse SELL deixa invested −R$ 4.600 em jul e
  ago/26. Provavelmente era uma transferência, que deveria ser Transaction e não
  AssetMovement. Confirmar e remover/reclassificar o lançamento.

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
