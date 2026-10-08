---
name: pesquisa-total
description: "Pesquisa total do IQ OS: procura um termo em todos os âmbitos da plataforma (recolha, redes sociais, contratos de Portugal e de Espanha, entidades, pessoas, políticos, Wikipédia, marcas, firmas, notícias, imprensa, mercado e CRM) numa só chamada e devolve resultados agrupados com contagens."
version: 1.0.0
author: IQ OS
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [IQ OS, Pesquisa, Contratos, Empresas, Pessoas, Notícias, Dados]
    category: research
    related_skills: [websearch, grounded-citations]
---

# Pesquisa total (IQ OS)

O IQ OS tem uma pesquisa unificada que varre **todos** os âmbitos da plataforma
em paralelo e devolve resultados agrupados, com a contagem de cada grupo. É o
primeiro sítio a ir quando a pergunta é sobre Portugal: contratos públicos,
empresas, pessoas, políticos, imprensa, mercado.

## Endpoint

```
GET http://backend:8000/search/unified?q=<termo>&scope=<âmbito>&size=<n>
```

- `q` — o termo (nome, NIF, marca, ticker, órgão, tema).
- `scope` — `all` (por omissão) ou um âmbito concreto (ver abaixo).
- `size` — resultados **por âmbito** (1–50, por omissão 8).
- `offset` — saltos dentro do âmbito escolhido (para paginar).
- `filters` — facetas em JSON, por exemplo `{"partido":"PS"}`.

O `curl` já existe no ambiente — é o caminho mais curto:

```bash
curl -s --get 'http://backend:8000/search/unified' \
  --data-urlencode 'q=EDP' --data-urlencode 'scope=all' --data-urlencode 'size=5'
```

Sem credenciais devolve **dados públicos**. Se o utilizador lhe der um token da
plataforma, junte `-H "Authorization: Bearer <token>"` para ver também o que é
privado (CRM, dossiês).

## Âmbitos (`scope`)

| Âmbito | O que traz |
| --- | --- |
| `all` | todos os de baixo, em paralelo |
| `scraped` | recolha própria (editais, diários, portais) |
| `social` | redes sociais recolhidas |
| `contracts` | contratos públicos de Portugal |
| `contracts_es` | contratos de Espanha (PLACSP) |
| `entities` / `entities_es` | entidades e empresas (PT/ES) |
| `pessoas` | pessoas (perfis societários) |
| `politicos` | políticos |
| `wikipedia` | Wikipédia (PT) |
| `trademarks` | marcas |
| `firmas` | firmas |
| `news` | notícias indexadas |
| `imprensa` | imprensa |
| `market` | mercado (tickers, cotações) |
| `crm` | CRM da conta (precisa de sessão) |

## Como fazer

1. **Uma chamada primeiro, `scope=all`, `size=5`.** Dá o panorama e as contagens —
   quase sempre é isso que responde («quantos», «o que existe sobre»).
2. **Ler as contagens antes do texto.** Cada grupo traz `total` (universo) e
   `items` (amostra). Dizer «7658 resultados, dos quais 35 na recolha e 2331 na
   Wikipédia» vale mais do que despejar cinco títulos.
3. **Aprofundar só no âmbito que interessa**: repetir a chamada com
   `scope=contracts`, `scope=news`, … e `size=20`, e paginar com `offset`.
4. **Citar sempre o que se usa**: `title` + `url` do item (quando existir) e o
   âmbito. Quem lê tem de conseguir ir ver.
5. **Nome → identidade:** para confirmar que «EDP» é a entidade certa, use
   `GET /search/suggest?q=EDP` (empresas, recolha, tickers) e só depois pesquise
   pelo NIF/nome completo.

## Verificações

- Nunca inventar números: `total` vem da resposta. Se `total` for 0, reformular o
  termo (mais curto, sem acentos, outra grafia) antes de dizer que não existe.
- O mesmo item aparece em vários grupos com pontuações diferentes — não contar a
  mesma coisa duas vezes ao somar.
- `took_ms` é o tempo do servidor; se a resposta demorar, reduzir `size` ou
  escolher um `scope` concreto.
- Isto é dados **portugueses e espanhóis da plataforma**; para o que está fora
  (legislação estrangeira, sites de terceiros) usar a skill `websearch` e citar
  o URL original.
