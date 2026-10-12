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
  Segurança Social.

Com **duas ou mais** empresas, a leitura que só aí existe é *quem as liga*: quem se senta nas duas,
quem gere várias, quem só aparece numa. É o cruzamento do painel de conjunto das empresas, mas do
lado das pessoas.

## Rotas

| Rota | O que devolve |
|---|---|
| `GET /descoberta/pessoas/meta` | fontes, classes de cargo, órgãos de gestão e limites |
| `GET /descoberta/pessoas/resolver?q=` | a empresa principal e candidatos alternativos (nome ou NIF) |
| `GET /descoberta/pessoas/descobrir?nifs=&nomes=` | o painel: pessoas, KPIs, ligações, grafo, atenção e fontes |
| `POST /descoberta/pessoas/descobrir` | igual, com as empresas no corpo (`empresas`/`nifs`, `nomes`) |
| `GET /descoberta/pessoas/pessoa/{nif}?empresas=` | ficha da pessoa em todo o universo, marcando as empresas do pedido |

`descobrir` aceita `pais` (`PT`, `ES`), `max_empresas` (2–6), `fontes` (lista de ids separada por
vírgulas), `incluir_grafo` e `incluir_devedores`. Uma empresa que falhe não derruba o painel: fica
marcada como `erro` no estado das fontes e nas empresas do pedido, e aparece nos avisos.

## Fontes (5)

| Fonte | Grupo | O que recolhe | Índice |
|---|---|---|---|
| `cargos` | governo | cargos societários: órgão social, data, ato e publicação | `finance_people` |
| `quotas` | governo | titulares de capital com quota registada | `finance_people` |
| `universo` | rede | todas as empresas onde cada pessoa tem cargos (rede para fora do pedido) | `finance_people` |
| `cire` | risco | pessoas com NIF nos processos em que as empresas são parte | `finance_cire` |
| `devedores` | risco | titulares nas listas de devedores (amostra dos mais relevantes) | `finance_devedores` |

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
| `kpis` | quantas pessoas, quantas ligam empresas, quantos órgãos sociais, qual o cargo mais frequente, que profundidade de cargos, quantos processos e quantos devedores |
| `pessoas` | a lista ordenada por relevância, com cargo atual, empresas do pedido, cargos, universo, datas e evidência |
| `ligacoes` | quem tem cargo em duas ou mais empresas do pedido — o que as liga |
| `cargos` | distribuição por cargo (pessoas e empresas que toca) |
| `grafo` | empresas do pedido ligadas às pessoas (duas dimensões: `empresa` e `pessoa`) |
| `atencao` | o que verificar primeiro, por severidade (`alerta`, `aviso`, `info`) |
| `fontes` | estado de cada fonte: `ok`, `vazio`, `erro` ou `tempo`, com total e tempo |
| `leitura` | frase de síntese determinística, escrita a partir dos números acima |

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
processos do CIRE por empresa (40); titulares verificados nas listas de devedores (12); empresas por
pedido (6). Quando uma lista é truncada, o painel di-lo em vez de a apresentar como completa.
