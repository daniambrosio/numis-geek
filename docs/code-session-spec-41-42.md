# Code session prompt — Specs 41 + 42

Sessão de design: 2026-05-26. Specs criadas:

- **Spec 41 — Dual-currency Hero Views** (📝 ready, com 9 questões
  abertas no rodapé pra plan-mode interview)
- **Spec 42 — CcyPill Cleanup in Tables and Hero Numbers** (📝 ready,
  com 5 alignment decisions já fechadas no topo)

Protótipo de referência já atualizado em `prototypes/index.html`:
Dashboard hero tiles com sub USD · Patrimônio hero+tabela com sub USD ·
Snapshot detail KPIs com sub USD · FechamentosPage tabela com USD stack.

Cole o conteúdo abaixo na primeira mensagem da sessão Claude Code.

---

```
Olá Claude Code. Vou disparar 2 specs em sequência:
**Spec 41** (Dual-currency Hero Views) e
**Spec 42** (CcyPill Cleanup in Tables and Hero Numbers).

As duas são complementares: 41 introduz o dual-display (BRL grande
+ USD em dim) em hero views; 42 limpa as pills redundantes que
sobraram após a regra "nasce sem pill" que a 41 estabeleceu.

**Antes de tocar uma linha de código, entra em plan mode.**

## REGRA INEGOCIÁVEL — leia spec E protótipo

Para CADA uma das 2 specs, antes de propor plano:

1. **Leia a spec inteira** em `specs/{NN}. ....md`. Note: ambas
   já têm "Alignment decisions" no topo — questões importantes
   já fechadas, só executa.
2. **Abra `prototypes/index.html` no browser** e navegue:
   - Spec 41 — `/dashboard` (hero com 3 tiles + sub USD), `/patrimonio`
     (idem + tabela Top 10 com valor 2-linhas), `/fechamentos`
     (tabela coluna Patrimônio 2-linhas), `/fechamentos/2026-04`
     (KPIs com sub USD).
   - Spec 42 — `/lançamentos` (coluna NET sem pill), `/proventos`
     (idem), e os 4 outros alvos (Dashboard hero, Patrimônio hero,
     Activity feed, OndeInvestir Cash) que precisam de pill
     removida. Compare com o estado atual do app real.
3. **Spec diverge do proto = proto ganha.** Atualiza a spec.

## Leia primeiro, nessa ordem

1. `CLAUDE.md` — methodology, naming en, testes verdes
2. `specs/41. Dual-currency Hero Views.md`
3. `specs/42. CcyPill Cleanup in Tables and Hero Numbers.md`
4. `specs/14. Portfolio Snapshot.md` — snapshots já guardam
   total_value_usd + fx_rate_usd_brl da época (custo zero pra
   Snapshot detail da 41)
5. `specs/35. Monthly Closing Workflow.md` — FechamentoDetailPage
   no app real
6. `specs/11. PTAX and Integration Credentials.md` — fonte do PTAX
   pra Dashboard/Patrimônio
7. `prototypes/index.html` — abre no browser e navega pelas
   7 telas acima

## Plan mode AGORA

**Ordem sugerida: Spec 41 primeiro, Spec 42 depois.**

Razão: Spec 41 introduz o dual-display nas hero numbers (já
remove a pill como efeito colateral nos hero), e Spec 42 limpa o
resto (tabelas, activity feed). Inverter ordem cria conflito de
merge porque ambas mexem no Dashboard hero.

Para cada spec:

1. **Audite o estado atual** dos componentes (Dashboard, Patrimonio,
   SnapshotDetail, SnapshotList pra 41; AssetMovements,
   Distributions, ActivityFeed pra 42).
2. **Spec 41 ainda tem 9 questões abertas no rodapé** — conduza
   a interview comigo (com sua recomendação + razão por questão).
   Atenção especial em:
   - Q1: backend estende `/portfolio` com USD ou frontend
     converte usando `ptax_now`?
   - Q5: Δ USD = ΔR$/fx_atual OU snap.total_usd -
     prev.total_usd? (segunda inclui efeito cambial — mais fiel)
3. **Spec 42 já está alinhada** — 5 questões fechadas no topo da
   spec. Não tem interview. Audita só pra confirmar que nada
   mudou no app desde então.
4. **Plano em 2-3 PRs** (Spec 41 backend se necessário + Spec 41
   frontend; Spec 42 frontend único) com arquivos, testes, deps.
5. **Atualize Spec 41** com Alignment decisions inline ao final
   da interview.
6. **Aprovação minha** antes de codar.

## Não faça

- Não pule o protótipo
- Não pule a plan-mode interview da Spec 41
- Spec 42: não remova pills de detail panels nem da linha USD
  de Movimentações (são as exceções que ficam — ver §"Onde a
  pill sobrevive" da spec)
- Não converta valores em tabelas densas (Lançamentos/Proventos)
  — out-of-scope da 41
- Não toque o protótipo

## Critério de done (cada spec)

- npm test verde + npm build limpo + pytest verde (sem regressão)
- Spec atualizada com Alignment decisions inline (já tem na 42;
  fechar na 41) + status "✅ Done — YYYY-MM-DD"
- 1-2 PRs nomeados "Spec NN Phase X — <desc>"
- Spec 41: `docs/design-system.md` ganha parágrafo "When to use
  CcyPill" (vinculante pra telas futuras)
- Spec 42: aplica essa mesma regra retroativamente

Vamos lá. Primeira tarefa: lê a Leia-primeiro acima + me devolve
auditoria do estado atual + respostas pras 9 questões da Spec 41.
```
