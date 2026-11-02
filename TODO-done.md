# TODO — concluídos e dropados

Arquivo de destino dos itens que saíram do `TODO.md`. Registro histórico, não fila.

## Novembro 2026

- [x] **2026-11-02 — Spec 83 (Pagar e receber com ativos) em produção + backfill.**
  `fc5974c` deployado; Coinbase One (19/05/2026, R$ 239,98) vinculado ao SELL de
  47,537572 USDC em *Apps e Serviços Online › Loyalty / Clube* / COINBASE BR.
  Backup `numis_geek.db.bak-before-spec83-backfill-20261102-223248`.

## Outubro 2026

- [x] **2026-10-31 — Coinbase: recompensas USDC→BTC de ago/set lançadas + julho deduplicado.**
  8 pares (INTEREST USDC + BUY BTC, `coinbase-reward:*`) a partir dos prints do app.
  BTC set/26 via `apply_recompute_to_snapshot` (IN_REVIEW); ago/26 CLOSED por UPDATE
  cirúrgico (qty/mv/invested/PM + header). `total_received_brl` +766,19 (ago) e
  +1.529,02 (set). Julho: 5 INTEREST duplicados da extração (`coinbase:*:INTEREST:*`,
  job anotado "avenue proventos") desativados; −944,83 no recebido de jul/ago/set.
  Backups `.bak-before-jul-usdc-dup-20261031-001006` e
  `.bak-before-coinbase-rewards-ago-set-20261031-001315`.
- [x] **2026-10-30 — Spec 65 Fase 1 (cleanup backend do SUSPICIOUS_DELTA).** Detector,
  endpoints `mom-deltas`/`recheck-deltas`/`confirm-delta`, enum e testes removidos;
  migration `spec65_drop_susp_delta` apaga as rows. Gatilho: BHIA3 (+109% em set/26)
  preso no painel com JSON cru — resolvido antes via SQL (backup
  `.bak-before-bhia3-delta-20261030-234026`).
- [x] **2026-10-30 — CDB Vai Brasil removido do fechamento set/26.** Resgate total de 01/09
  lançado em 03/10, depois do snapshot; `delete_snapshot_item` (−R$ 2.041,27). Backup
  `.bak-before-cdb-vaibrasil-20261030-234303`.

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
