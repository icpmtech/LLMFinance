# Notícias (índice `finance_news`)

Módulo de notícias do **IQ OS** (rota `/noticias`): recolhe notícias para o
Elasticsearch, pesquisa-as com filtros e facetas e **publica-as no blog** quando
uma delas merece artigo. Tudo vive no índice `finance_news` — o mesmo que o
sentimento de mercado, a Pesquisa total e o RAG leem.

## Peças

| Peça | Papel |
| --- | --- |
| `api/news_routes.py` | Router `/news/*` (estado, pesquisa, temas, recolha, publicação) |
| `api/news_themes.py` | Catálogo **curado** dos temas da plataforma e do seu vocabulário |
| `api/news_nlp.py` | Análise de cada notícia (sentimento, tradução PT, tópicos e entidades) |
| `api/elasticsearch_client.py` | Índice `finance_news`: escrita, pesquisa, facetas e leitura de um documento |
| `api/tools.py` | `search_news_terms`, a pesquisa de notícias do Yahoo usada pela recolha por tema |
| `chat-ui/src/newsApi.ts` | Cliente tipado (`/news/*`) |
| `chat-ui/src/pages/NewsPage.tsx` | Ecrã do módulo: recolha, filtros, facetas e botões de publicação |

## Recolha

- **Por ticker** (`POST /news/collect` com `tickers`): a notícia leva o NLP
  completo — sentimento, tradução PT, tópicos e entidades. É lento (traduz os
  títulos).
- **Por tema** (`topics`): usa o léxico bilingue imediato (`news_nlp.keyword_sentiment`)
  e o **tema exato** fica gravado no campo `topic` — é o que faz uma notícia
  recolhida por «contratação pública» aparecer na pesquisa mesmo quando o título
  não repete as palavras.
- Sem `tickers` nem `topics`, a recolha usa os **favoritos** guardados no painel
  de mercado.

## Temas da plataforma

O módulo cobre o mercado (tickers) e a **atividade da plataforma**: contratação
pública, contratos e adjudicações, fundos europeus e PRR, subvenções,
insolvências, Administração Pública, empresas e fiscalidade.

O catálogo é fixo e vive em `api/news_themes.py` (`THEMES`): cada tema tem um
`id`, um rótulo, uma descrição, as **expressões** que o definem, as etiquetas de
blog sugeridas e a categoria de blog sugerida. Não há configuração na base de
dados — mudar um tema é mudar o código, com revisão à vista.

Como funciona o filtro:

- `GET /news/themes` devolve o catálogo (é o que a interface mostra em botões);
- `GET /news/search?theme=<id>` limita a pesquisa às expressões do tema
  (`multi_match` com `operator: and` sobre os campos de pesquisa) **e** ao tema
  exato com que a notícia foi recolhida (`term` sobre `topic`);
- cada expressão é procurada também **sem acentos** (`news_themes.term_variants`):
  o `standard analyzer` do Elasticsearch não remove acentos, pelo que
  «contratação» e «contratacao» são termos diferentes;
- as facetas passam a incluir `themes`: a contagem de **todos** os temas,
  calculada **fora** do tema ativo (senão os restantes apareceriam a zero), mas
  dentro dos outros filtros que o utilizador tenha ligado.

Para acrescentar um tema novo basta juntar uma entrada a `THEMES` — aparece na
interface e na pesquisa sem mais nenhuma alteração.

## Publicar uma notícia como artigo de blog

`POST /news/publish` cria no **CMS** um artigo **rascunho** a partir da notícia
(o mesmo ciclo de vida de qualquer artigo: rascunho → agendado → publicado).

| Campo do pedido | Efeito |
| --- | --- |
| `id` | Identificador da notícia no índice (é o que o cartão da lista traz). Sem ele, o artigo faz-se só com o que o pedido trouxer |
| `theme` | Tema da plataforma: sugere as etiquetas e a categoria do artigo |
| `title`, `excerpt` | Substituem o título e o resumo da notícia |
| `markdown` | Corpo escrito à mão (por omissão é gerado: resumo, crédito da fonte e ligação para o original) |
| `tags`, `category_ids` | Etiquetas e categorias explícitas |

O que o servidor escreve, quando o editor não escreve: título **em português**
(`translated_title` quando existe), resumo (`summary_pt` → `translated_summary` →
`summary`), o crédito `**Fonte:** <publicador> · <dia> — [ler a notícia original](<url>)`
e uma nota de rascunho com o rasto da plataforma (tema, tom e ticker).

Duas regras que evitam estragos:

- **A mesma notícia não dá dois artigos.** O artigo guarda o `news_id` da notícia
  de origem; a segunda tentativa devolve `duplicado: true` com o artigo que já
  existe, e a interface liga para lá em vez de criar outro. A ligação é um campo
  do artigo (e não uma etiqueta): uma etiqueta interna acabaria publicada na
  página, nas palavras-chave e nos índices de etiquetas.
- **O `<title>` não passa dos 70 caracteres** (`api/cms_render.py`): o artigo
  guarda o título completo (é o `<h1>` da página) e o `seo.title` já sai cortado
  em palavras, para o sufixo da marca não empurrar o título para além do que os
  motores de busca mostram.
- **Escrever exige sessão.** A publicação é uma escrita no CMS: sem sessão, a
  rota responde 401.

## Rotas

| Método | Rota | Quem | O que faz |
| --- | --- | --- | --- |
| GET | `/news/stats` | público | Volume, tickers, fontes, janela temporal e análise |
| GET | `/news/search` | público | Pesquisa com filtros e facetas (tickers, fontes, temas, sentimentos, dias) |
| GET | `/news/themes` | público | Temas da plataforma e o seu vocabulário |
| POST | `/news/collect` | sessão | Recolhe notícias do Yahoo (tickers e/ou temas) para o índice |
| POST | `/news/publish` | sessão | Cria o artigo rascunho no blog a partir de uma notícia |

## Limitações

- A notícia **não traz o texto integral**: o índice guarda título, resumo,
  fonte, data, ligação, tópicos e entidades. O artigo nasce desse material — quem
  publica acrescenta a análise.
- A pesquisa por tema é **lexical**: depende das expressões do catálogo. Se um
  tema trouxer ruído ou faltar, é em `api/news_themes.py` que se corrige.
- As contagens por tema são calculadas em cada pesquisa (uma agregação `filters`
  com um balde por tema). Num índice muito maior vale a pena passá-las para
  agregação própria com cache.
