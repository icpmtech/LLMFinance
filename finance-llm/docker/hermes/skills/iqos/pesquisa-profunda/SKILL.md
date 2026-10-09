---
name: pesquisa-profunda
description: "Pesquisa profunda do IQ OS: responde a uma pergunta em linguagem natural com fontes numeradas [n] dos dados indexados (contratos PT/ES, empresas, pessoas, CIRE/insolvências, atos societários, citações edital, imprensa, recolha, Wikipédia, marcas, firmas, mercado) e cita sempre a fonte de cada afirmação."
version: 1.0.0
author: IQ OS
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [IQ OS, Pesquisa, Resposta, Citações, Contratos, Empresas, Insolvências, Dados]
    category: research
    related_skills: [pesquisa-total, websearch, grounded-citations]
---

# Pesquisa profunda (IQ OS)

A **Pesquisa profunda** é a pesquisa da plataforma que, além de procurar, escreve
uma resposta fundamentada: recupera candidatos dos âmbitos, numera-os como fontes
`[1]`, `[2]`, … e só depois responde **citando** essas fontes. Sem fontes não há
resposta — o motor responde que não encontrou, em vez de inventar.

Usa-a quando a pergunta é uma **pergunta** («qual o estado da insolvência da
Sicasal», «quanto vale a contratação de X») e não apenas uma procura por um termo
(para isso serve a skill `pesquisa-total`).

## Endpoints

```
GET  http://backend:8000/deep-search/meta          # âmbitos, modos e limites
GET  http://backend:8000/deep-search/search?q=…    # só as fontes (sem modelo)
POST http://backend:8000/deep-search/ask           # resposta citada (SSE)
```

`POST /deep-search/ask` recebe um JSON:

```json
{
  "question": "Qual o estado da insolvência da Sicasal?",
  "sources": ["cire", "contribuintes", "contracts"],
  "mode": "hybrid",
  "per_source": 6,
  "max_sources": 12
}
```

A resposta é **SSE**: primeiro o evento `sources` (as fontes numeradas), depois os
tokens da resposta (`token`) e no fim `done`. Com `curl`:

```bash
curl -sN -X POST 'http://backend:8000/deep-search/ask' \
  -H 'Content-Type: application/json' \
  -d '{"question":"Qual o estado da insolvência da Sicasal?","sources":["cire","contribuintes"]}'
```

Quando não é preciso a resposta escrita (só a evidência), usar
`GET /deep-search/search` — é mais rápido e não gasta modelo.

## Âmbitos (`sources`)

Vazio = todos. Os principais:

| Âmbito | O que traz |
| --- | --- |
| `contracts` / `contracts_es` | contratos públicos de Portugal / Espanha |
| `entities` / `entities_es` | empresas e órgãos (PT/ES) |
| `contribuintes` | NIF/NIPC com papéis e valores por fonte (contratos, CIRE, societário…) |
| `cire` | **insolvências e revitalizações** (CIRE/CITIUS) |
| `societario` | atos societários publicados no MJ (registo comercial) |
| `citacoes` | citações e notificações editais (CITIUS) |
| `pessoas` / `politicos` | pessoas com ficha / políticos |
| `imprensa` / `scraped` / `social` / `news` | notícias, recolha própria, redes sociais |
| `wikipedia` | enciclopédia (PT e EN) |
| `trademarks` / `firmas` | marcas (INPI) e firmas (RNPC) |
| `market` | tickers e cotações |

`mode`: `hybrid` (palavras + semântica, recomendado), `text` (termos exatos: NIF,
CPV, nomes) ou `vector` (só vizinhos semânticos).

## Como fazer

1. **Uma pergunta por chamada**, com os nomes próprios completos («Sicasal -
   Indústria e Comércio Carnes, S.A.», não «a Sicasal») — é o que liga a pergunta
   ao processo certo.
2. **Ler primeiro as fontes** (`sources`): cada uma traz `title`, `subtitle`,
   `snippet`, `date`, `meta` (valores, NIFs, processos) e `open`.
3. **Citar no formato `[n]`** a seguir a cada afirmação, exatamente como o motor
   faz. Nunca escrever um valor, data ou processo que não esteja nas fontes.
4. **Se `sources` vier vazio**, reformular (outro âmbito, outra grafia do nome) e
   dizê-lo — não preencher o vazio com conhecimento próprio.
5. **Cruzar âmbitos**: `contribuintes` dá o retrato (quantos contratos, que
   publicações CIRE), `cire` o processo, `contracts` os contratos. Os três juntos
   respondem «quem é esta empresa e como está».

## Verificações

- As fontes são **dados da plataforma**; para o que está fora dela (notícias de
  ontem, sites de terceiros) usar a skill `websearch` e citar o URL original.
- `took_ms` é o tempo de recuperação. `vector_error` preenchido significa que a
  parte semântica falhou e a resposta se baseou só em palavras-chave.
- Cada âmbito só pode ocupar uma parte das fontes: se um resultado importante não
  aparecer, reduza `sources` ao âmbito que interessa.
