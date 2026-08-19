# TODO — pendências entre sessões

Arquivo vivo de pendências que atravessam sessões de trabalho. Convenções:
`[user]` = ação do Daniel · `[claude]` = ação do Claude na próxima sessão pertinente ·
riscar (`~~item~~`) quando concluído, com data.

## Pós-fix bonificação/FMV (sessão 2026-08-10 → 2026-08-18)

- [ ] `[claude]` **Fechamento Ago/26 — validar degrau de PM/invested.** O fix `d2b14f6`
  (BONUS entra no basis) + data fix ITUB4 (gross 7.820 + 3.240) mudam o PM de todos os
  ativos com bonificação (ITUB4 31,33→35,26 e +R$ 11.060 invested; ITSA4/KLBN11/AURE3/
  EGIE3/BHIA3/WBD/BTHF11/Terreno diluem). Snapshots frozen ≤ Jul/26 NÃO recomputam —
  o degrau no fechamento de Ago/26 é esperado e correto; apenas confirmar que os números
  batem e explicar a variação no review do snapshot.
- [ ] `[user]` **Notion legado — bonificações ITUB4 com Preço Unit. = 0.** O Notion nunca
  teve o valor de incorporação (R$ 34,00 mar/2025 · R$ 40,00 dez/2025). Corrigir lá só
  se quiser consistência do histórico legado; o numis-geek já está correto.
- [ ] `[claude]` **Revisar convenção "SELL não reduz basis_qty".** Audit adversarial do
  d2b14f6 apontou: SELL parcial seguido de BONUS infla `total_invested`
  (ex.: BUY 100@30, SELL 50, BONUS 50 → invested 2.000 vs fiscal 1.500). Pré-existente
  e ficou MENOR com o fix, mas merece spec própria (basis-reduction proporcional em
  SELL parcial — impacto em IR de ganho de capital).

## Fila anterior (pós-Fase 2 / fechamento Jul-26)

- [ ] `[claude]` **Proventos sub-capturados** — item 4 da fila pós-Fase 2; investigar
  distribuições que o sync do Notion não capturou.
- [ ] `[claude]` **UX indicator de price source** — item 5 da fila; mostrar na UI a origem
  do preço do ativo (brapi/Finnhub/manual/snapshot).
- [ ] `[claude]` **Matcher bulk-extract — 3 gaps**: agregação de cash, tie-breaker de data,
  validação name×ticker do asset.
- [ ] `[user]` `[claude]` **Specs 64/65/66 em Draft** — retomar entrevista/implementação.
