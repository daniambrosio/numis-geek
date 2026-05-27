# Code session prompt — Specs 36 + 37 + 38

**Histórico** — esse prompt foi usado na sessão de design 2026-05-24
pra disparar a implementação de:

- **Spec 36** — Compound Asset Creation (Options Entry Points) ✅ Done 2026-05-26
- **Spec 37** — Composer Attachments & Edit Mode ✅ Done 2026-05-26
- **Spec 38** — Snapshot Upload Extraction (LLM) ✅ Done (V1) 2026-05-26

Salvo retroativamente como registro do método.

---

```
Olá Claude Code. Vou disparar 3 specs em sequência:
**Spec 36** (Compound Asset Creation — Options Entry Points),
**Spec 37** (Composer Attachments & Edit Mode), e
**Spec 38** (Snapshot Upload Extraction via LLM).

Antes de tocar uma linha de código, **entra em plan mode**.

## REGRA INEGOCIÁVEL — leia spec E protótipo

Para CADA uma das 3 specs, antes de propor plano:

1. **Leia a spec inteira** em `specs/{NN}. ....md` — escopo, AC,
   fases, perguntas de interview.
2. **Abra o protótipo** em `prototypes/index.html` no browser e
   navegue pela UX correspondente:
   - Spec 36: TopBar `+ Novo → Opção` (modal compound), página de
     um ativo (ex: ITUB4) com card "Opções abertas" + botão "+ Nova
     opção", e `/lançamentos` com asset = opção (type picker fica
     dinâmico com SELL_TO_CLOSE/BUY_TO_CLOSE/EXERCISED/EXPIRED).
   - Spec 37: `/lançamentos` → `+ Novo Lançamento` (área de anexos
     no fim do modal) e click numa linha → painel com botão Editar
     → modal "Editar Lançamento" pré-populado. Mesmo em
     `/proventos`. Componente `<NotesAttachmentsField>` no proto
     em ~4193.
   - Spec 38: `/fechamentos/2026-04` → painel de pendências →
     "Upload extrato" em qualquer pendência → modal com 4 estágios
     (pick → uploading → review com confidence pills → applied).
3. **O protótipo é a referência visual e de fluxo.** Use ele
   para resolver dúvidas de UX antes de me perguntar. Se a spec
   diverge do protótipo, **o protótipo ganha** — atualiza a spec.
4. **Não invente UX** que não esteja no protótipo ou na spec.

## Leia primeiro, nessa ordem

1. `CLAUDE.md` — methodology, Multi-Agent SDLC, naming em English,
   migration obrigatória, testes verdes
2. `specs/35. Monthly Closing Workflow.md` — base já implementada
   (Spec 38 depende dela; Spec 37 vive em qualquer composer)
3. `specs/36. Compound Asset Creation (Options Entry Points).md`
4. `specs/37. Composer Attachments and Edit Mode.md`
5. `specs/38. Snapshot Upload Extraction (LLM).md`
6. `specs/17. Opções B3.md` — foundation que Spec 36 estende
   (OptionModal, parser de ticker, POST /options)
7. `specs/19. Attachments and FI country.md` — sistema de anexos
   que Spec 37 e Spec 38 consomem
8. `specs/11. PTAX and Integration Credentials.md` — Spec 38
   armazena a Anthropic API key aqui
9. `prototypes/index.html` — abre no browser e navega pelos 3
   fluxos acima

## Plan mode — o que quero AGORA

Para cada spec, NESTA ORDEM (37 → 36 → 38, do mais simples ao
mais complexo):

1. **Audite o estado atual** do código real correspondente
   (composers, OptionModal, FechamentoDetailPage, attachments).
2. **Conduza a interview** das questions no rodapé da spec
   comigo, uma por uma, com sua recomendação + razão.
3. **Devolva plano em fases** (cada spec tem 3-5 fases mapeadas).
4. **Atualize a spec** com as respostas (seção "Alignment
   decisions" — mesmo padrão da Spec 35).
5. **Aprovação minha** antes de codar.

Sugestão de ordem por dependência:
- **Spec 37 primeiro** — base de UX (anexos + edit) que melhora
  toda criação/edição de registros. Mais simples, valida o pattern
  `composer.edit()` que outras specs vão reusar.
- **Spec 36 depois** — estende NovoButton e MovementComposer com
  os patterns que a 37 acabou de polir.
- **Spec 38 por último** — mais complexa, depende de Spec 19 e
  da PendencyPanel da Spec 35.

## Não faça

- **Não pule o protótipo.** Toda dúvida de "como isso deveria
  ficar visualmente" se resolve abrindo `prototypes/index.html`
  e navegando.
- **Não pule a plan mode interview** — cada spec tem 7-10
  questões abertas no rodapé que precisam fechar antes de codar.
- Não comece pela Spec 38 — depende de 37 e 35.
- Não use "lançamento" em código novo (entidade é AssetMovement;
  label PT no UI continua "Lançamento").
- Não invente novo design surface fora do que está no protótipo.
- Não toque o protótipo (ele é referência, não destino).

## Critério de done (para cada spec)

- pytest verde + npm test verde + npm build limpo
- Spec atualizada com "Alignment decisions" inline + status
  "✅ Done — YYYY-MM-DD"
- Cada fase = 1 PR separado com mensagem "Spec NN Phase X — <desc>"
- Audit log entries pra todas as operações que mudam estado
- Atualizar `docs/conceptual-model.md` se schema mudar

## Critério de done (consolidado das 3)

Quando as 3 specs estiverem mergeadas, atualizar a tabela em
`docs/session-2026-05-24-report.md` (ou criar
`docs/spec-36-37-38-summary.md`) mostrando o que ficou no app vs
o que ficou pra spec futura (ex: composer dedicado de Renda Fixa
é out-of-scope da 36, Spec 39 quando vier).

Vamos lá — primeira tarefa: lê tudo da lista de "Leia primeiro"
e me devolve a auditoria + ordem proposta de implementação.
```

## Resultado pós-execução

O dev executou e atualizou as 3 specs com "Alignment decisions"
inline. Decisões-chave que ficaram:

**Spec 36:**
- Ícone do item "Opção": `Sigma` (lucide-react)
- ETF entra como underlying válido (STOCK/REIT/ETF)
- "Salvar e abrir outra" mantém underlying + optionType
- EXERCISED submit direto (sem confirm dialog — backend já atômico)

**Spec 37:**
- Escopo aplicado só Movement + Distribution composers (CardTx/Transaction
  ainda não existem no app real)
- Submit chain: parcial com aviso (não rollback)
- Anexos persistidos DELETE soft imediato no edit
- Audit diff helper genérico em `utils/audit_diff.py`

**Spec 38:**
- Sync em V1 (chamada inline no POST)
- Modelo: claude-sonnet-4-5 default
- 2 hints com prompt produção (SCREENSHOT_PRICE, BROKER_POSITION);
  outros 3 com schema + prompt placeholder
- Skip + report pra tickers não resolvidos
- PII: V1 manda como veio (Anthropic API não treina), risco documentado
