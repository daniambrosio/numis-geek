# TODO — concluídos e dropados

Arquivo de destino dos itens que saíram do `TODO.md`. Registro histórico, não fila.

## Setembro 2026

- [x] **2026-09-06 — Meli Dólar vira CASH (modo valor).** User decidiu "só anotar o total
  no fechamento". Classe CRYPTO→CASH; 9 fechamentos com valor normalizados pra qtd=1 /
  preço unitário = total (totais em R$ inalterados); ago/26 estava inflado
  (19,34 × R$ 348,31 = R$ 6.736,31) → R$ 348,31, total do fechamento −R$ 6.388,00.
  Backup `data/numis_geek.db.bak-before-meli-dolar-cash-20260906`. Sanity: soma dos itens
  = total do fechamento; compute_position = R$ 348,31 em modo valor.
- [x] **2026-09-05 — 17 anexos de fechamento sem instituição/finalidade em prod.** Triagem
  via artifact (preview + inferência do Claude, confirmada pelo user sem correções) e SQL
  cirúrgico: 59/59 anexos SNAPSHOT com slot, 0 órfãos. Backup
  `data/numis_geek.db.bak-before-orphan-slots-20260905`. Causa raiz corrigida em 8875a1e
  (slot gravado no upload).


## Faxina 2026-08-18

- 🗑️ **UX indicator de price source** — dropado em 2026-07-26 com aval do user: sem caso
  concreto de preço stale mordendo, o indicador é ruído. Estava listado por engano como
  pendente no TODO. Reabrir só se aparecer caso real.
- ✅ **Fila pós-Fase 2, itens 1-3** — concluídos antes do TODO.md existir: spec 62
  MoM/SUSPICIOUS_DELTA (`e6c2f0d`+`5da99eb`, 2026-07-08), Fase 3 polish (`13b76a2`,
  2026-07-22), extraction hardening (`c5e8d97`, 2026-07-22). Histórico completo na
  memory `session_state_2026-07-05`.
