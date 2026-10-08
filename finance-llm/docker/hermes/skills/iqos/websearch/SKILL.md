---
name: websearch
description: "Pesquisa e leitura na web aberta a partir do ambiente do agente: usa o metasearch interno (SearXNG) da plataforma em JSON, lê as páginas que interessam e devolve respostas com os URL citados."
version: 1.0.0
author: IQ OS
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Web, Pesquisa, Notícias, Fontes, Citações]
    category: web
    related_skills: [pesquisa-total, grounded-citations]
---

# Pesquisa na web

Para tudo o que não está na base do IQ OS: notícias de hoje, sites de
instituições, legislação, páginas de empresa, documentação. Usa a **skill
`pesquisa-total`** primeiro quando a pergunta for sobre Portugal; usa esta quando
for sobre a web em geral.

## 1. Procurar

Ordem de preferência:

1. **Ferramenta `web_search`** do agente, se estiver disponível e devolver
   resultados. Se falhar ou vier vazia, passar ao ponto 2 — não insistir.
2. **SearXNG da plataforma** (self-hosted, sem chave, `limiter` desligado, JSON
   ligado — ver `docker/searxng/settings.yml`). `curl` está instalado:

```bash
curl -s --get 'http://searxng:8080/search' \
  --data-urlencode 'q=consulta' --data-urlencode 'format=json' \
  --data-urlencode 'language=pt' --data-urlencode 'safesearch=0' \
  --data-urlencode 'time_range=' | head -c 20000
```

Resposta: `{"query": …, "results": [{"title","url","content","engine","publishedDate"}, …]}`.
Ler `results[]`; `content` é o resumo do motor e serve para triar, não para citar
em definitivo.

Parâmetros úteis: `language=pt` (ou `en`), `time_range=day|week|month|year` para
notícias, `categories=news|general|it|science`, `pageno=2` para a página seguinte.

## 2. Ler a fonte

Para as 2–4 páginas que interessam:

1. **`web_extract`** do agente, se existir.
2. Senão, `curl` e limpar o HTML antes de ler:

```bash
curl -sL -A 'Mozilla/5.0' -m 30 '<url>' \
  | python3 -c "import sys,re,html; t=sys.stdin.read(); \
t=re.sub(r'(?is)<(script|style|nav|footer|header)[^>]*>.*?</\1>',' ',t); \
t=re.sub(r'(?s)<[^>]+>',' ',t); print(html.unescape(re.sub(r'\s+',' ',t))[:12000])"
```

## 3. Responder

- **Citar sempre**: `[n] título — url`, numerado, a seguir a cada facto. Sem URL
  não é fonte.
- Preferir **fontes primárias** (diário da república, regulador, site oficial da
  empresa, comunicado) a agregadores e a blogs.
- Marcar o que é **data de publicação** quando a pergunta é «quando» ou «o mais
  recente»: notícia sem data não serve para responder «ontem».
- Dizer explicitamente quando **só há uma fonte** ou quando os motores discordam.

## Verificações

- **Nunca inventar URL nem título.** Se não está em `results[]`, não existe para
  efeitos da resposta.
- **Nunca analisar o HTML do SearXNG**: usar sempre `format=json`. Se vier HTML,
  o parâmetro `format=json` não chegou (verificar aspas/codificação do URL) —
  voltar a pedir em JSON.
- Pesquisa com **0 resultados**: reformular (sinónimos, inglês, sem aspas, sem
  ano) antes de concluir que não há nada. Duas reformulações é o mínimo.
- Páginas com *paywall* ou só `403`: dizê-lo e procurar alternativa (arquivo,
  comunicado, outra fonte).
- Confirmar a data de hoje quando a resposta depende de «hoje/ontem/esta semana»
  — usar as notícias com `publishedDate`, não a ordem dos resultados.
