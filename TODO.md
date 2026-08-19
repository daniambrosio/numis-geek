# TODO — pendências entre sessões

Arquivo vivo de pendências que atravessam sessões de trabalho. Convenções:
`[user]` = ação do Daniel · `[claude]` = ação do Claude na próxima sessão pertinente ·
item concluído ou dropado sai daqui e vai pro `TODO-done.md` (com data).

## Fechamento e cost basis (pós-fix bonificação d2b14f6)

- [ ] `[claude]` **Fechamento Ago/26 — validar degrau de PM/invested.** O fix `d2b14f6`
  (BONUS entra no basis) + data fix ITUB4 (gross 7.820 + 3.240) mudam o PM de todos os
  ativos com bonificação (ITUB4 31,33→35,26 e +R$ 11.060 invested; ITSA4/KLBN11/AURE3/
  EGIE3/BHIA3/WBD/BTHF11/Terreno diluem). Snapshots frozen ≤ Jul/26 NÃO recomputam —
  o degrau no fechamento de Ago/26 é esperado e correto; apenas confirmar que os números
  batem e explicar a variação no review do snapshot.
- [ ] `[user]` **Notion legado — bonificações ITUB4 com Preço Unit. = 0.** O Notion nunca
  teve o valor de incorporação (R$ 34,00 mar/2025 · R$ 40,00 dez/2025). Corrigir lá só
  se quiser consistência do histórico legado; o numis-geek já está correto.
- [ ] `[claude]` **Spec nova: SELL parcial deve reduzir basis proporcionalmente.** Audit
  adversarial do d2b14f6 apontou: convenção "SELL não reduz basis_qty" + BONUS infla
  `total_invested` (ex.: BUY 100@30, SELL 50, BONUS 50 → invested 2.000 vs fiscal 1.500).
  Pré-existente e ficou MENOR com o fix, mas merece spec própria — impacto em IR de
  ganho de capital.

## Specs pausadas / em andamento

- [ ] `[claude]` **Spec 59 (Comparativo) — retomar da Fase 0.1.** Protótipo da 1ª tela
  plantado e funcionando; 3 perguntas de UX em aberto pro user; fila Fases 0.2→6 pendente.
  Contexto completo de retomada na memory `session_state_spec_59_fase_0_1`.
- [ ] `[claude]` **Spec 65 — Fase 1 (cleanup backend).** ~60% entregue (frontend em
  25c7bfd/93c80d2); falta deletar o legado SUSPICIOUS_DELTA — enum,
  `detect_suspicious_deltas`, endpoints e testes. Codepath dormente, sem urgência.
- [ ] `[user]` `[claude]` **Specs 64 e 66 em Draft — retomar entrevista/implementação.**
  64 = value-mode SELL zera posição indevidamente em `compute_position` (caso LFT
  mar/2028; Gap 5 da memory do matcher). 66 = crypto rewards pagos em cripto (in-kind).

## Import / extração

- [ ] `[claude]` **Proventos sub-capturados (ITSA4/TAEE11/PETR4/BOVA11/IVV/AAPL).**
  Distribuições não vieram no bulk extract dos custodiantes — ITSA4 R$ 121k de posição
  rendeu R$ 350/ano (~95% faltando); TAEE11 idem. Plano: re-import CSV/PDF de proventos
  dos últimos 12m via BROKER_INCOME, validar extrator Avenue de proventos, e feature
  "Expected vs Actual dividends" por YOC histórico pra detectar sub-captura automática.
- [ ] `[claude]` **Matcher bulk-extract — 3 gaps** (detalhe na memory
  `matcher_bulk_extract_improvements`): (1) cash accounts sem match — agregar linhas
  cash/saldo/banking no asset CASH único da FI; (2) tie-breaker quando dois bonds vencem
  na mesma data — keyword do issuer; (3) validação name×ticker na criação/edição de
  asset quando as datas divergem.
