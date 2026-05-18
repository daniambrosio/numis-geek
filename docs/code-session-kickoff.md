# Kickoff prompt — Claude Code session

Cole o conteúdo abaixo na primeira mensagem da sessão. Mantenha numa pasta
de docs pra reusar se um dia precisar reiniciar.

---

Olá Claude Code. Acabei uma sessão de Design (Claude Design) onde validamos
visualmente o modelo conceitual e a IA do app via um protótipo de alta
fidelidade. **Antes de tocar qualquer linha de código, preciso que você se
contextualize e me devolva um plano** — não comece a editar nada ainda.

## Contexto

**Numis-Geek** é meu sistema pessoal de finanças (vide `CLAUDE.md`).
Já existe código backend (`src/numis_geek/models/`) e frontend implementados,
MAS:

- O **frontend evoluiu de forma independente** durante a sessão de Design.
  Algumas seções foram removidas, sobreposições de boxes foram corrigidas,
  etc. **Não considere o estado atual do frontend como source of truth.**
- O **backend** tem modelos SQLAlchemy que precisam de várias mudanças
  documentadas em `docs/conceptual-model.md` §3 (renames, splits, novas
  entidades, FK changes).
- O **protótipo em `prototypes/index.html`** é a referência visual e de IA.
  **Não é código de produção** — é HTML single-file com React via CDN,
  throwaway. Você abre no browser pra navegar; não precisa ler o JSX.

## Leia primeiro, nessa ordem

1. `CLAUDE.md` — methodology + tech stack + conventions (Multi-Agent SDLC,
   specs numerados em `./specs/`, interview em plan mode, testes verdes
   antes de considerar feito)
2. `DESIGN-BRIEF.md` — brief original do produto
3. `docs/conceptual-model.md` — **schema alvo** (mudou bastante; §3 lista
   os deltas vs código atual; §2.9 explica notes & attachments; §2.8 explica
   Variação / Rentabilidade)
4. `prototypes/README.md` — guia do protótipo (rotas, padrões, mock data)
5. **Abra `prototypes/index.html` no browser** pra ver como cada tela ficou.
   Click em volta, abra slide-overs, teste os composers, troca temas e
   privacy mode. Isso é a referência visual.
6. `src/numis_geek/models/` — modelos atuais (vão precisar refator)
7. Dê uma olhada no frontend atual (`frontend/` ou wherever ele tá) pra
   mapear o que existe — mas **não assuma como correto**, ele tá numa
   trajetória paralela ao protótipo

## Resumo do que mudou (detalhes em `docs/conceptual-model.md` §3)

**Workspace fica.** Sem multi-user v1, mas `User` e `AuditLog` persistem
porque sysadmin existe e auditoria é não-negociável.

**Renames:**
- `Lancamento` → `AssetMovement` (table `asset_movement`)
- `COMPRA`→`BUY`, `VENDA`→`SELL`, `BONIFICACAO`→`BONUS`,
  `SUBSCRICAO`→`SUBSCRIPTION`, `RESGATE_TOTAL`→`FULL_REDEMPTION`,
  `COME_COTAS` mantém

**Splits:**
- `DIVIDENDO`, `JUROS`, `JCP` saem do AssetMovement → entram em
  nova entidade `Distribution`
- Novo tipo `SECURITIES_LENDING` ("Aluguel" / "BTC") em Distribution
- **`Distribution.asset_id` é nullable** (Avenue manda aluguel genérico
  sem ticker)
- `CreditCard` vira entidade própria, separada de Account
- Account types: só `checking | investment`

**Asset refactor:**
- `Asset.financial_institution_id` vira `Asset.account_id` (FK pra
  investment account)
- Classes: 14 → 11 (STOCK_BR+STOCK_US→STOCK; FII+REIT→REIT;
  BOND+FIXED_INCOME→FIXED_INCOME)
- Novos campos: `country` (ISO-2), `current_price`, `price_updated_at`

**Novas entidades:**
- `CreditCard`, `Distribution`, `Transaction` (polimorfia
  account_id|credit_card_id), `Invoice`, `Budget`, `BudgetCategory`,
  `PTAXRate`, `StatementFile`, `TradeNote`, `InvoiceFile`, `Attachment`
- Coluna `notes` (text) em AssetMovement, Distribution, Transaction, Asset

**IA / sidebar bifurcada:**
- WORKSPACE: Dashboard
- INVESTIMENTOS: Patrimônio · Ativos · Lançamentos · Proventos
- CAIXA & CARTÕES: Movimentações · Cartões · Faturas · Orçamento
- ESTRUTURA: Instituições · Contas
- ADMIN: Audit log
- SISTEMA: (sysadmin only)

Reconciliação é **botão** em Conta/Cartão detail, não item de sidebar.

## O que eu quero de você AGORA

Não escreva código. Em vez disso:

1. **Audite o estado atual.** Leia os models em `src/numis_geek/models/`,
   dê uma olhada no frontend atual sem julgar, e me diga o que tem hoje vs
   o que precisa ter conforme a conceptual-model.md.
2. **Liste os deltas concretos** — qual model precisa mudar, quais
   migrations Alembic vão precisar, quais entidades novas criar, qual a
   ordem segura de aplicar.
3. **Proponha um plano em fases.** Backend primeiro (schema + migrations +
   testes), frontend rebuild depois. Use o método Multi-Agent SDLC do
   CLAUDE.md (Planner / Coder / Reviewer / Security agents).
4. **Identifique riscos de migração de dados.** Onde tem dados existentes
   que precisam remapear:
   - `Lancamento` rows com type DIVIDENDO/JUROS/JCP → migrar pra `Distribution`
   - `Asset` rows: `financial_institution_id` precisa virar `account_id`
     via join na investment account daquela FI naquele workspace
   - `Asset` rows com classes antigas precisam ser remapeadas (STOCK_BR →
     STOCK + country=BR, etc.)
5. **Faça perguntas se algo estiver ambíguo** — não chuta nada.

Quando você tiver o plano, eu aprovo (ou ajusto) e aí partimos pra
implementação spec-by-spec conforme o CLAUDE.md.

## Não faça

- Não comece refatorando direto sem aprovação do plano
- Não confie no estado atual do frontend como source of truth
- Não invente schema novo — qualquer mudança que sair do
  `conceptual-model.md` precisa atualizar a doc na mesma PR
- Não use `lançamento` em código novo (a entidade é `AssetMovement`; a
  label PT no UI continua "Lançamento")
- Não tente reproduzir o CSS do protótipo HTML como código de produção —
  use o protótipo como referência *visual*, mas implemente em React +
  Tailwind v4 + componentes próprios (talvez shadcn/ui se fizer sentido)

Vamos lá.
