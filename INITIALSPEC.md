# Objetivo: 
Esse sistema consolida duas visões que tenho implementadas no meu Notion. O Investidor-Geek que cuida dos meus investimentos e o Numis que cuida de minhas despesas. 

# Premissas
- Use python como linguagem de programação e desenvolvimento
- Use sempre ingles na modelagem das tabelas, properties, features
- Banco de Dados: usamos um local simplificado que depois possa ser migrado facilmente para um VPS (consulte antes de decidir e criar)
- Inicialmente o sistema roda na minha máquina, mas a arquitetura deve ser pensada para escalar a um VPS 
- Controle de versão desde o primeiro momento com git 
- Controle de migração de base de dados ao evoluir o sistema
- Vamos usar essa técnica para o desenvolvimento, portanto configure no início o que for necessário. Me entreviste para entender melhor. *Multi-Agent SDLC (the frontier)*: Specialized agents per phase: a planner agent, a coder agent, a reviewer agent, a security agent — each with narrow context and clear handoffs. Frameworks like LangGraph, AutoGen, and CrewAI formalize this. You're the orchestrator, not the implementer.
- Vamos criar testes automatizados para todas as features - se necessários crie um agente específico para isso. Uma feature só está pronta quando tiver todos os testes escritos e passando.
- Crie o CLAUDE.MD com as premissas importantes listadas aqui


# Processo
- Depois de ler essa Initial Spec, planeje quais features vamos ter que criar.
- Cria uma pasta para specs ./specs
- Dentro da pasta de specs crie os arquivos de features com a nomenclatura iniciando com um numero. Por ex. "01. User Authentication"
- Me entreviste em plan mode antes de construir cada spec. 
- Sempre que terminarmos a implementação de uma spec 


# Modelagem

## Instituições Financeiras
Representam os bancos, corretoras e fintechs que eu uso para meus investimentos e despesas. 

## Lançamentos
Representam compras, vendas, come-cotas, bonificações, subscrição e resgate total de um determinado ativo/investimento

## Transacoes
Representam as transações de despesas e entradas de dinheiro (salario, consultorias, vendas)

## Contas Correntes (com e sem rendimento atrelado)
Representam as contas correntes onde eu faço pagamento de contas, recebo dinheiro e pix, pago com pix e transfiro dinheiro. Várias instituições financeiras oferecem contas de investimento e corrente - eu tenho esse caso em várias.

## Contas Investimento
Representam as contas por onde transito o dinheiro para comprar ativos e fazer investimentos, recebo os pagamentos de proventos/dividendos. Várias instituições financeiras oferecem contas de investimento e corrente - eu tenho esse caso em várias.

## Contas Cartão de Crédito
Os cartões de crédito precisam ter também suas transações, e estão atrelados a uma instituição financeira. Acho que faz sentido modelar como uma conta também, mas me entreviste e/ou ofereça sugestões/

## Arquivos de Extratos (bolsa, bancos, fintechs, corretoras)
São arquivos que eu uso para acompanhar detalhes de cada conta que tenho.

## Arquivos de Notas de Operação 
São arquivos que representam operações de compra e venda de ativos. Geralmente enviado pelas corretoras e instituições financeiras para controle e registro das movimentações. 

## Arquivos de Faturas (cartão de crédito)
Representam as despesas, IOF, cambio, feitos nos meus cartões de crédito. Eu tenho cartoes adicionais e eles vem na mesma fatura ao fechamento do mes. Cada cartão tem sua data de fechamento da fatura e data de pagamento da fatura que precisam ser controlados no sistema. 




# Features

1. Multi moeda: O sistema deve ser preperado em dólar (US$ / USD) e real (R$ / BRL). Todas transações e lançamentos tem uma moeda corrente (ou padrão) e devem ter conhecimento do dólar PTAX do dia para fazer a conversão. 
2. Tabela de câmbio do sistema: Replica o valor da PTAX de fechamento do dia em que se faça necessário para calcular a conversão entre moedas de qualquer transação ou lançamento. 
3. Visão da Carteira de Investimentos Dolarizada: como estou no Brasil, a maioria dos meus investimentos está em reais, mas eu quero manter uma visão constante da carteira em dólares
4. Possibilidade de fazer lançamentos manuais
5. Controle de Contas a Pagar e a Receber, com diferentes frequencias
6. Auditoria e log de ações executadas no sistema e por quem foram realizadas
7. Controle de usuarios (autenticacao e autorizacao) com base no email; é possível ter mais de um usuario executando acoes em um Workspace (podemos dar outro nome, mas precisamos de um conceito agrupador de tudo)
8. Dark Mode e Light Mode ou System mode para a interface. 
9. Vamos fazer uma migração de dados (import) do Notion, pois já temos muitos dados lá
10. Transações e Lançamentos precisam ser conciliados contra arquivos importados. Manter o relacionamento para rastreabilidade entre os arquivos usados e a transacao/lancamento conciliado. 
11. Vamos contruir dashboard para os mundos de investimentos e para os despesas
12. KPIs importantes para acompanhamento precisam ser definidos durante o processo de criação.
13. Para desepsas: Quero ter a possibilidade de fazer orçamentos anuais com acompanhamento mensal de atingimento
14. Investimentos: vamos precisar de cálculo de rentabilidade, mensal, por instituicao financeira, por classe de ativos, anual, YoY, MoM, etc.
15. A apuração dos investimentos eu quero fazer mensalmente, registrando uma foto de todos eles no ultimo dia do mes sendo apurado. Alguns serao importados automaticamente usando APIs publicas (o cadastro dos ativos no Notion tem um link determinado para o brasil e outro para EUA)
16. A importação de arquivos para conciliacao pode ter CSV, print de telas, PDF, XLS e vários formatos. Deteção inteligente do conteúdo desses arquivos deve exigir integração com LLMs para um agente 
17. Quero ter objetivos de investimentos a perseguir: proventos no ano / por país. Precisa ter uma certa flexibilidade para a criação desses eventos.
18. Precisamos de uma importação inteligente de proventos com base em arquivos de extratos das corretoras. Talvez também será necessário uma LLM para isso. 
19. Uma ideia apenas/inspiração de como seria o dash para a parte de investimentos esta na pasta de assets/references
20. Que tenha uma atualização do valor atual dos ativos para poder calcular oportunidades de investimento com base na carteira (por calculo de preço teto, bazin, grahan, peter lynch, valuation, valor intrínseco, projetivo etc.)


## Avançados
15. Ter dados de indices para comparacao (CDI, Ibovespa, Nasdaq, S&P, IFIX)
16. Ter dados historicos da inflacao para uso nos calculos historicos
17. Integração com a B3 para importar automaticamente os dados
18. Facilitar a declaracao do imposto de renda IRPF
19. Importar documentos e relatórios do RI de cada ativo para leitura e analise (automatica / batch)
20. 
