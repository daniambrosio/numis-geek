# Next steps — captured pending items

Items que estão aguardando input do user ou cuja execução é
operacional. Não-blocking — cada um tem dono claro de quando rolar.

## Pendentes — aguarda decisão do user

### 1. Spec 43 §1 — `ATTACHMENTS_ROOT` env var

Status: documentado em `specs/43. Robustez do storage de anexos.md`
linhas 46-122 (incluindo "Tradeoffs em aberto"). §2 e §3 já entregues
em 2026-05-28.

Decisões pra fechar antes de implementar:

- Default da env (`./data/attachments` vs XDG path)
- Comportamento se a env aponta pra diretório inexistente (criar
  recursivo vs abortar)
- App falha ruidosamente em boot se ROOT mudou e tem `storage_key`
  no DB sem arquivo correspondente, ou degrada silencioso (404 caso
  a caso)?
- CLI helper de verificação entra junto ou fica fora?

Recomendação minha: env opcional + sem auto-migração + script
`scripts/audit_attachments.py` (já existe da §3) cobre o caso de
verificação pós-mudança. Implementação 1 PR pequeno depois da
decisão.

### 2. Rate limits brapi/Finnhub — confirmar antes de Opção C

Status: durante review da Spec 44 levantei como concern. Não está
documentado em nenhum lugar do código nem das specs. Public docs
(cutoff jan/2026):

- **Finnhub free**: 60 calls/min. Generoso pros 47 ativos US.
- **brapi.dev free**: histórico de 15 req/min ou 1000/dia.
  Mudou múltiplas vezes — confere o dashboard real.

Pra confirmar:

- https://brapi.dev/dashboard
- https://finnhub.io/dashboard

Quando o user passar os números, adicionar `RATE_LIMIT_RPM` const
em `integrations/brapi.py` + `integrations/finnhub.py`, decidir se
precisa de `time.sleep()` entre calls, e só então avaliar a **Opção
C — symmetric catchup pro cron de preços 18h** (mesmo pattern do
PTAX catchup mas pra `run_daily_price_refresh`).

### 3. Rodar audit_attachments na produção

Status: script entregue na Spec 43 §3 (2026-05-28). Nunca foi
executado contra o DB real ainda.

```bash
python -m scripts.audit_attachments
```

Provavelmente está limpo (storage é recente e usado pouco), mas é
a primeira oportunidade de verificar se já tem orphan files ou
ghost rows escondidos. Exit code 0 = clean, 2 = mismatches a olhar.

## Convenção pra adicionar items aqui

- Cada item começa com `### N. <título curto>` + parágrafo `Status:`
  apontando pra onde está documentado (spec, commit, comentário).
- Inclui Decisões a fechar / Trade-offs / Recomendação minha quando
  aplica.
- Quando o item rolar, **deletar daqui** + atualizar a spec
  correspondente. Este doc é "limbo", não histórico — git tem o
  histórico.
