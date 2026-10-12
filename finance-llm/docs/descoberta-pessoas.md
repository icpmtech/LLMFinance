# Descoberta de pessoas (`/descoberta-pessoas`, API `/descoberta/pessoas/*`)

Responde à pergunta ao contrário da descoberta de empresas: em vez de «o que é que a plataforma
sabe sobre esta empresa?», **quem está por trás destas empresas?**

Dão-se **uma ou várias** empresas (NIF ou nome) e o painel devolve, numa só chamada, quem nelas
tem cargos registados, com a evidência de cada cargo:

- **cargos societários** — órgãos sociais das publicações de registo comercial (`finance_people`),
  com data, ato e publicação;
- **capital** — os mesmos registos dizem quem tem quota;
- **universo da pessoa** — onde mais essa pessoa tem cargos, dentro e fora das empresas pedidas;
- **processos do CIRE** — administradores de insolvência, credores pessoa e insolventes nos
  processos em que as empresas são parte;
- **listas de devedores** — se os titulares mais relevantes figuram nas listas das Finanças e da
  Segurança Social;
- **contratos** — quem contrata com quem, para cruzar os titulares dos dois lados de um contrato.

Com **duas ou mais** empresas, a leitura que só aí existe é *quem as liga*: quem se senta nas duas,
quem gere várias, quem só aparece numa. É o cruzamento do painel de conjunto das empresas, mas do
lado das pessoas.

Além da lista, cada pessoa sai com o **título** do cargo (limpo do ruído da publicação, ex.
`Vogal`), uma pontuação de **risco** de 0 a 100 e os **conflitos de interesse** em que aparece.

## Rotas

| Rota | O que devolve |
|---|---|
| `GET /descoberta/pessoas/meta` | fontes, classes de cargo, órgãos de gestão, método de risco e limites |
| `GET /descoberta/pessoas/resolver?q=` | a empresa principal e candidatos alternativos (nome ou NIF) |
| `GET /descoberta/pessoas/descobrir?nifs=&nomes=` | o painel: pessoas, KPIs, ligações, conflitos, risco, grafos, atenção e fontes |
| `POST /descoberta/pessoas/descobrir` | igual, com as empresas no corpo (`empresas`/`nifs`, `nomes`) |
| `POST /descoberta/pessoas/analise` | análise citada do conjunto pelo Hermes |
| `GET /descoberta/pessoas/pessoa/{nif}?empresas=` | ficha da pessoa em todo o universo, marcando as empresas do pedido |

`descobrir` aceita `pais` (`PT`, `ES`), `max_empresas` (2–6), `fontes` (lista de ids separada por
vírgulas), `incluir_grafo`, `incluir_devedores` e `incluir_conflitos`. Uma empresa que falhe não
derruba o painel: fica marcada como `erro` no estado das fontes e nas empresas do pedido, e aparece
nos avisos.

`analise` aceita `empresas`/`nifs`, `pergunta` (por omissão, a pergunta padrão ancorada nos números
do painel), `profundidade`, `fontes`, `backend` e `skill_id` — sem skill é o Hermes que escolhe o
método. O painel envia os nomes e os títulos dos titulares mais relevantes na pergunta, para a
resposta não ficar só em contagens.

## Fontes (6)

| Fonte | Grupo | O que recolhe | Índice |
|---|---|---|---|
| `cargos` | governo | cargos societários: órgão social, data, ato e publicação | `finance_people` |
| `quotas` | governo | titulares de capital com quota registada | `finance_people` |
| `universo` | rede | todas as empresas onde cada pessoa tem cargos (rede para fora do pedido) | `finance_people` |
| `cire` | risco | pessoas com NIF nos processos em que as empresas são parte | `finance_cire` |
| `devedores` | risco | titulares nas listas de devedores (amostra dos mais relevantes) | `finance_devedores` |
| `contratos` | contratação | contrapartes contratuais das empresas, para os conflitos de interesse | `contratos` |

`cargos`, `quotas` e `universo` saem da **mesma** leitura por empresa (`finance_people`): pede-se
uma vez e as três classes derivam-se depois. A fonte `devedores` consulta até
`MAX_DEVEDORES` (12) titulares por pedido — é uma amostra dos mais relevantes, não o universo todo,
e o painel diz isso na nota da fonte.

## Classes de cargo

Cada cargo é classificado, pela ordem que evita falsos laços societários:

| Classe | Quando | Exemplo |
|---|---|---|
| `processo` | papel processual do CIRE | `Credor`, `Insolvente`, `Administrador da insolvência` |
| `capital` | quota registada ou `Sócio` | `Sócia` com quota |
| `gestao` | órgão social (`CARGO_GESTAO_ORGS`) ou título de gestão | `Gerente`, `Vogal`, `Presidente` |
| `outro` | tudo o resto | `Fiscal Único` |

A ordem importa: «Administrador da insolvência» contém «administrador», mas é um papel de processo —
é isso que o painel diz. A classe da pessoa é a mais relevante dos seus cargos (gestão > capital >
processo > outro), e a ordem da lista segue gestão primeiro, depois quem liga empresas, depois o
número de empresas do pedido e de cargos.

## Painel

| Bloco | Pergunta que responde |
|---|---|
| `kpis` | quantas pessoas, quantas ligam empresas, quantos órgãos sociais, quantos titulares com risco alto e quantos conflitos de interesse |
| `pessoas` | a lista ordenada por relevância, com nome, título do cargo, empresas do pedido, cargos, universo, risco, datas e evidência |
| `ligacoes` | quem tem cargo em duas ou mais empresas do pedido — o que as liga |
| `cargos` | distribuição por cargo (pessoas e empresas que toca) |
| `conflitos` | titulares com cargo nos dois lados de um contrato, com valor, contratos e direção |
| `grafo` | empresas do pedido ligadas às pessoas, com o título em cada nó e ligação |
| `grafo_pessoas` | co-titularidade: pessoas ligadas por partilharem uma empresa |
| `atencao` | o que verificar primeiro, por severidade (`alerta`, `aviso`, `info`) |
| `fontes` | estado de cada fonte: `ok`, `vazio`, `erro` ou `tempo`, com total e tempo |
| `leitura` | frase de síntese determinística, escrita a partir dos números acima |

Os títulos vêm limpos do ruído das publicações (ex. `Causa: renúncia Data: …` sai do `role`): é o
título que aparece nos nós do grafo (segunda linha do nó) e nas ligações (`tem como Vogal`), e é ele
que ordena a evidência de cada cargo.

### Risco da pessoa (0–100)

Método próprio, com os mesmos níveis e cores do risco das empresas (`risco_service.nivel_de`):
compõe seis componentes ponderados — acumulação de cargos, processos de insolvência, listas de
devedores, cessações por renúncia, mudança recente de gestão e cargos sem órgão identificado — e
renormaliza pelos componentes com dados. Uma pessoa sem listas de devedores consultadas não é
penalizada por isso: baixa é a cobertura, não o risco. Sem dados nenhuns o score é `null` («sem
dados»), nunca 0. As fórmulas estão publicadas em `GET /descoberta/pessoas/meta` →
`risco.componentes`.

### Conflitos de interesse

Procura-se cada titular nas contrapartes contratuais das empresas do pedido: se a mesma pessoa tem
cargo numa empresa do pedido **e** numa entidade que contrata com ela, o painel diz o valor, o número
de contratos e a direção (quem compra e quem vende). O sinal sobe a `alerta` quando o cargo é de
órgão social ou capital.

Regras dos pontos de atenção: pessoa com cargo em duas ou mais empresas do pedido (alerta quando
é órgão social ou capital, aviso nos restantes casos); empresa sem cargos registados (é ausência de
registo, não de gestão); recolha incompleta ou lista limitada numa empresa; acumulação de cargos no
universo (≥ 5 empresas); titular nas listas de devedores (alerta); pessoa insolvente num processo do
CIRE (alerta); empresa com um só titular de órgão social; pessoas que só aparecem por papéis de
processo; «pessoas» que são sociedades (NIF coletivo); e cargos registados nos últimos 90 dias
(mudança de gestão).

## Ficha da pessoa

`GET /descoberta/pessoas/pessoa/{nif}` devolve **todos** os cargos da pessoa no universo, agrupados
por empresa e ordenados pela mais recente, com as empresas do pedido marcadas (`no_pedido`), as
quotas, as origens (publicações, CIRE, …) e o perfil público quando existe (cargo, partido,
legislatura, biografia). Nasce do mesmo documento de `finance_people` que o PessoasIQ abre, pelo que
o painel e a ficha individual não divergem.

## Limites

Pessoas por empresa (300), pessoas mostradas no painel (120) e pessoas desenhadas no grafo (40);
processos do CIRE por empresa (40); titulares verificados nas listas de devedores (12); contratos
lidos por empresa para os conflitos (200); conflitos mostrados (8); quadros até 12 titulares no grafo
de co-titularidade e 400 ligações pessoa↔pessoa; empresas por pedido (6). Quando uma lista é
truncada, o painel di-lo em vez de a apresentar como completa.

## Ecrã

A página ([DescobertaPessoasPage](descoberta-pessoas.md)) junta tudo isto num só ecrã:

- **KPIs** — empresas, pessoas, ligações entre empresas, órgãos sociais, titulares em listas de
  devedores, conflitos e risco alto;
- **cartões** de conflitos, risco das pessoas, análise do Hermes e fontes;
- **tabela** de pessoas com título, classe, risco (badge) e sinais de conflito;
- **filtros** em memória — todas, órgãos sociais, capital, processos, quem liga empresas, com
  conflitos e risco ≥ 40, mais um filtro de texto — e **exportação** para Excel (XLSX), CSV e
  relatório Markdown;
- **rede** com alternância entre «empresas ↔ pessoas» e «pessoas ↔ pessoas» (com quem não está em
  nenhuma ligação desenhado à parte);
- **ficha** da pessoa, com cargos agrupados, quotas, origens e o detalhe do risco;
- **análise do Hermes** sobre o conjunto, com profundidade, citações e ligação ao PessoasIQ.
