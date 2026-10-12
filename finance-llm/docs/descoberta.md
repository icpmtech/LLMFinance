# Descoberta (`/descoberta`, API `/descoberta/*`)

Responde a uma pergunta simples: **o que é que a plataforma sabe sobre esta empresa?**

Dá-se um **NIF** (ou um nome) e o painel devolve, numa só chamada, tudo o que existe sobre essa
empresa — cadastro, contratos públicos, rede de relações, pessoas e cargos, atos societários,
insolvências (CIRE), risco, marcas (INPI), firmas (RNPC), subvenções, devedores, contribuintes,
mercado, registos LEI e notícias — e, por cima disso, os dois paradigmas da descoberta:

- **grafo de informação** — a empresa no centro e uma camada por família de evidência
  (quem compra, o que se classifica, quem gere, processos, marcas, firmas, subvenções,
  devedores e imprensa);
- **ontologia** — a mesma evidência expressa na gramática do IQ OS: que tipos de objeto foram
  instanciados, que tipos de ligação foram materializados e o que a ontologia ainda não fala.

A análise final é escrita pelo **Hermes**, seguindo a **skill** que a biblioteca da plataforma
escolher (ou a que o painel impuser).

## Rotas

| Rota | O que devolve |
|---|---|
| `GET /descoberta/meta` | fontes disponíveis, grupos, fontes da Pesquisa 360 e limites |
| `GET /descoberta/skills?q=` | biblioteca de skills do Hermes e a que serviria a pergunta `q` |
| `GET /descoberta/resolver?q=` | a empresa principal e candidatos alternativos (nome ou NIF) |
| `GET /descoberta/empresa/{nif}` | recolha completa + grafo + ontologia + decisão |
| `GET /descoberta/empresa/{nif}/grafo` | só o grafo de informação |
| `GET /descoberta/empresa/{nif}/ontologia` | só a projeção sobre a ontologia |
| `GET /descoberta/empresa/{nif}/decisao` | evolução, concentração, preços, perfil e pontos de atenção |
| `POST /descoberta/empresa/{nif}/analise` | análise citada pelo Hermes |
| `GET /descoberta/conjunto?nifs=&nomes=` | comparação de várias empresas (números, cruzamentos e rede) |
| `POST /descoberta/conjunto` | igual, com a lista de empresas no corpo |

`GET /descoberta/empresa/{nif}` aceita `pais` (`PT`, `ES`, `FR`), `nome` (quando já é conhecido),
`fontes` (lista de ids separada por vírgulas) e `incluir_grafo` / `incluir_ontologia` /
`incluir_decisao`.

`POST …/analise` aceita `pergunta`, `profundidade` (`rapida` \| `profunda`), `sources`
(fontes da Pesquisa 360), `backend`, `skill_id`, `pais`, `nome` e `fontes_recolha`.
Sem `pergunta`, o Hermes recebe a pergunta padrão da descoberta, ancorada nos números da recolha.

## Fontes (16)

| Fonte | Grupo | O que recolhe | Tipo na ontologia |
|---|---|---|---|
| `cadastro` | entidade | identificação, CAE, contactos e totais no portal base | `empresa` |
| `contratos` | contratação | contratos da empresa: valores, CPV, procedimento, sinais | `contrato` |
| `rede` | contratação | adjudicantes, órgãos sociais, processos e co-intervenientes | `entidade_publica` |
| `pessoas` | pessoas | quem tem cargos registados (registo societário e CIRE) | `pessoa` |
| `societario` | registos | publicações de atos de registo comercial | — |
| `cire` | risco | insolvências, PER, PEAP e PEVE (CITIUS) | — |
| `risco` | risco | nível de risco, componentes e anomalia face ao mercado | — |
| `marcas` | registos | marcas registadas no INPI | `marca` |
| `firmas` | registos | firmas e nomes comerciais (RNPC) | `firma` |
| `subvencoes` | financiamento | subvenções públicas atribuídas | — |
| `devedores` | financiamento | listas de devedores das Finanças e da Segurança Social | — |
| `contribuintes` | registos | NIF/NIPC no sistema, papéis e valores por fonte | — |
| `mercado` | mercados | posicionamento, dependências e atividade (CAE) | `ticker` |
| `lei` | registos | registos LEI (GLEIF) | — |
| `racius` | registos | ficha comercial (CAE, capital, contactos, administradores) | — |
| `noticias` | media | menções da empresa na imprensa indexada | `noticia` |

As fontes correm **em paralelo** (6 de cada vez) com um teto de tempo por fonte. Uma fonte que
falhe ou demore não impede as outras: cada uma devolve `ok`, `vazio`, `erro` ou `tempo`, e o painel
mostra o que existe e diz o que ficou em falta — nunca se inventa um valor.

## Grafo de informação

O desenho segue a mesma forma do estúdio de grafos (`nodes` / `edges` / `meta`), para ser
desenhado pelo `GraphCanvas` sem conversões:

- **nós** — `id`, `key`, `label`, `dimension` (camada), `type` (taxonomia de cor), `role`,
  `count`, `total_value`;
- **arestas** — `source`, `target`, `count`, `value`, `relation`;
- **meta** — dimensão, métrica, camadas presentes, valor das camadas e limites aplicados.

Limites de desenho: 10 adjudicantes, 8 CPV, 12 pessoas, 8 processos, 8 marcas, 5 firmas,
6 subvenções e 5 notícias. Os totais **exatos** estão nas secções da recolha, não no desenho.

## Ontologia

A projeção confronta a recolha com os `object_types` e `link_types` declarados
(`api/ontology_registry.py`) e devolve:

- **tipos** — instâncias por tipo de objeto, se o tipo é declarado e se a fonte que o instanciou é
  uma das fontes declaradas no respetivo `binding`;
- **ligações** — as relações que a recolha **prova**, casadas com os tipos de ligação declarados
  (`empresa_contratada`, `entidade_publica_adjudica`, `contrato_cpv`, `empresa_marcas`,
  `empresa_firmas`…);
- **cobertura** — quantos tipos e ligações da ontologia a descoberta realmente usou;
- **lacunas** — os tipos e as ligações que a descoberta instancia e a ontologia ainda não declara
  (por exemplo, `pessoa → empresa` para os cargos do registo societário, ou o processo do CIRE).

As lacunas são o resultado mais útil: dizem exatamente onde estender a ontologia.

## Decisão

`GET /descoberta/empresa/{nif}/decisao` (e o campo `decisao` na descoberta completa) transforma a
recolha naquilo que se olha **antes de decidir**. Tudo é cálculo determinístico em
`api/descoberta_decisao.py` — nenhuma conclusão vem de um modelo de IA — e os limiares estão no topo
do módulo, para poderem ser discutidos:

| Bloco | Pergunta que responde | Gráfico na página |
|---|---|---|
| `evolucao` | a carteira cresce, estagna ou perde compradores? | barras de valor + linhas de contratos e compradores novos |
| `concentracao` | de que depende a empresa? | Pareto (barras + acumulada, linha nos 80 %) e top de compradores |
| `cpv` | onde está o valor e com que pares se compara? | barras horizontais por quota |
| `procedimento` | quanto passa por concurso e quanto por ajuste direto? | donut (ajuste direto a vermelho) |
| `escaloes` | vive de muitos contratos pequenos ou de poucos grandes? | barras por escalão de valor |
| `precos` | adjudica acima ou abaixo do preço base? há aditivos? | barras por faixa + mediana e taxa de aditivo |
| `concorrencia` | o preço foi testado pelo mercado? | barras por nº de concorrentes |
| `prazos` | quantos dias até a contratação ficar pública? | barras por fase (decisão → publicação) |
| `perfil` | como se lê a empresa de uma só vez? | radar de 6–7 dimensões (100 = melhor) |
| `risco` | o que puxa o risco para cima? | barras por componente (cor por severidade) + fatores |
| `atencao` | o que verificar primeiro? | lista por severidade, com o que fazer a seguir |
| `leitura` | o resumo de uma frase | cabeçalho do separador |

O `perfil` normaliza escala, diversificação, concorrência, transparência, rapidez de publicação,
alinhamento de preço e risco (invertido) para 0–100, sempre acompanhado do número cru que o originou
— a barra nunca substitui o dado. Os pontos de atenção são regras explícitas (concentração, HHI,
ajuste direto, aditivos, desvio de preço, ausência de concorrência, atraso de publicação, insolvência,
risco alto, queda abrupta de valor) e não repetem os sinais que o motor de padrões já cobre.

## Risco e mercado

No separador **Resumo**, o bloco *Risco e mercado* junta duas fichas que já existiam no servidor e
antes só apareciam como lista de campos: o **risco** (`risco_service.risco_empresa`) e o **mercado**
(`mercado_service.empresa`). Agora lê-se com números e gráficos:

- **Nível de risco** — medidor 0–100 na cor do nível, faixa, cobertura, confiança, método e avisos de
  cobertura baixa.
- **O que puxa o risco** — contributo de cada componente ao score (pontos × peso efetivo), a cor pela
  severidade dos pontos, com a evidência de cada sinal na dica.
- **Componentes do modelo** — tabela com pontos, peso efetivo, contributo e evidência, incluindo os
  sinais sem dados (que não contam para o score).
- **Evolução do valor contratado** — barras por ano com linha, mediana de referência e variação/CAGR.
- **Dependência de compradores** — quota de cada comprador, com o limiar de dependência (50 %) marcado,
  mais maior comprador, HHI e taxa sem concurso.
- **Onde está o valor (CPV)** — top de classes com barra de quota, contratos, valor e valor médio.
- **Alertas de padrão**, perfil, CAE e compatibilidade com o que a empresa vende ao Estado.

## Várias empresas (Conjunto)

O modo **Várias empresas** (2 a 8) responde ao que só existe com duas ou mais: quem é maior, quem
depende mais de um só comprador, o que partilham e o que verificar primeiro. Está em
`api/descoberta_conjunto.py`, com três camadas:

1. **Por empresa** — a mesma recolha e o mesmo motor de decisão do painel individual
   (`descoberta_service.recolher` + `descoberta_decisao.decisao`), para os números do conjunto **não**
   divergirem dos do painel de cada uma.
2. **Comparação** — dez métricas alinhadas (contratos, valor, compradores distintos, maior comprador,
   HHI, ajuste direto, concorrentes, rácio adjudicado/base, dias até publicar e risco), com o melhor e
   o mais exposto de cada linha marcados, mais as séries do mesmo radar de perfil sobrepostas.
3. **Cruzamento** — adjudicantes, pessoas e processos partilhados e a rede do conjunto, calculados por
   `padroes_service.analise_empresas`: as mesmas regras que a página de Padrões usa, para os
   cruzamentos serem os mesmos nas duas páginas.

A resposta traz ainda `atencao` (pontos de atenção de todas as empresas, por gravidade), `totais` e
`leitura` (síntese determinística). Validações: país suportado, pelo menos duas empresas e
`max_empresas` entre 2 e 8 — um pedido inválido devolve 422 com a razão.

O custo é o da recolha de cada empresa (em paralelo, no máximo 4 de cada vez) mais a amostra nacional
do módulo de padrões: ~15–25 s na primeira vez e praticamente instantâneo depois, porque os dois
serviços mantêm cache.

## Grafo de informação — vistas

O separador **Grafo** desenha a mesma malha em cinco vistas: **rede**, **hierarquia** e **circular**
(`GraphCanvas`), **fluxo** (Sankey, para o valor que sai da empresa para cada camada) e **peso**
(treemap, para a área proporcional ao valor). Todas aceitam métrica de valor ou de contagem.

### Ler o grafo

- **Pictogramas em vez de nomes**: cada nó desenha o símbolo do seu tipo (empresa, entidade pública,
  pessoa, CPF/classificação, processo do CIRE, firma, marca, imprensa, subvenção, região) e o nome só
  aparece no nó apontado ou escolhido — um grafo denso lê-se pela forma e pelo tamanho, sem etiquetas
  por cima das ligações. O painel usa `labels="selecao"` do `GraphCanvas`.
- **Ficha do nó**: clicar num nó abre uma modal com identificação, contratos, valor, peso no total,
  ligações (com o sentido e o valor de cada uma) e a **evidência** já recolhida para aquele nó
  (comprador, contratos com esse comprador, cargos da pessoa, processo do CIRE, subvenção, marca,
  firma, notícia). Na ficha pode saltar-se para um nó vizinho.
- **Ações no lado direito**: o cartão *Ações do nó* repete as ações da ficha — abrir ficha, **isolar a
  vizinhança**, **ver só um tipo**, **esconder um tipo**, abrir no módulo (EmpresasIQ, PessoasIQ ou a
  notícia) e limpar a seleção. O cartão *Tipos* mostra as dimensões presentes com contagem e permite
  o mesmo por clique. A vista é filtrada em memória sobre o grafo do servidor, por isso o layout
  recalcula sozinho e há sempre «Ver o grafo completo» para voltar.

## Análise pelo Hermes

`POST /descoberta/empresa/{nif}/analise` compõe uma pergunta ancorada nos números da recolha
(contratos lidos, valor, adjudicantes distintos, concentração no maior adjudicante, nível de risco,
pessoas, insolvências e subvenções) e chama o Hermes com a profundidade escolhida.

As **skills** são a biblioteca partilhada por Hermes, Chat IA e RAG (`api/skills_service.py`):
sem `skill_id`, é o Hermes que escolhe (ou cria) o método do pedido; com `skill_id`, o método da
skill escolhida é injetado no pedido e a pergunta fica inteira (corta-se o bloco, nunca o pedido).

## MCP

As rotas estão expostas no servidor MCP (`mcp_server/catalog.py`) com o grupo `empresas`, pelo que
entram na seleção usada por omissão (`contratos,empresas,deep-search,hermes`):

- `descoberta_resolver` — nome ou NIF → empresa certa (com candidatos);
- `descoberta_empresa` — a descoberta completa (todas as fontes + grafo + ontologia).

Só estes dois: o grafo, a ontologia e a análise vêm na própria descoberta
(`incluir_grafo` / `incluir_ontologia`) ou já existem como `ontology_*` e `hermes_ask`, e o
orçamento de ferramentas do cliente (40 curadas + 4 genéricas) não dá para duplicar rotas.
As restantes rotas `/descoberta/*` continuam acessíveis por HTTP e por `iqos_api_call`.

O prompt `investigar_empresa` começa por `descoberta_resolver` → `descoberta_empresa`.

## Ficheiros

| Ficheiro | Papel |
|---|---|
| `api/descoberta_service.py` | catálogo de fontes, recolha paralela, grafo, ontologia e análise |
| `api/descoberta_decisao.py` | evolução, concentração, preços, perfil e pontos de atenção (cálculo puro) |
| `api/descoberta_conjunto.py` | comparação de várias empresas (métricas alinhadas, cruzamentos e rede) |
| `api/descoberta_routes.py` | rotas `/descoberta/*` |
| `chat-ui/src/pages/DescobertaPage.tsx` | painel (decisão, resumo, grafo, ontologia, fontes e análise) |
| `chat-ui/src/components/descoberta/DescobertaDecisao.tsx` | gráficos de decisão (Recharts) |
| `chat-ui/src/components/descoberta/DescobertaRiscoMercado.tsx` | risco (medidor, contributos, componentes) e mercado (evolução, dependência, CPV) |
| `chat-ui/src/components/descoberta/DescobertaConjunto.tsx` | comparação de várias empresas (tabela, radar sobreposto, cruzamentos e rede) |
| `chat-ui/src/components/descoberta/DescobertaNodeFicha.tsx` | ficha de um nó do grafo (modal) com a evidência do painel |
| `chat-ui/src/components/descoberta/descobertaGrafo.ts` | rótulos das dimensões e vistas do grafo (isolar/ver tipo/esconder) |
| `chat-ui/src/descobertaApi.ts` | cliente tipado das rotas |

A página aceita link direto (`/descoberta/<NIF>`), como o PessoasIQ, e aparece no dock e no menu em
**Empresas**.
