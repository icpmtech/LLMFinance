# Documentos (pasta `data/docs`)

Página **Documentos** (`/documentos`) — mostra os documentos de referência da
plataforma que vivem em `finance-llm/data/docs` e a **versão markdown** de cada
um.

## O que faz

- **Ficheiros** — lista a pasta (nome, tipo, tamanho, data da última alteração),
  com etiquetas `markdown` (tem versão markdown) e `gerado` (o `.md` é a versão
  markdown de outro documento da pasta). Abre o markdown do documento, abre o
  original numa janela nova ou descarrega-o.
- **CAE-Rev.4** — a *Classificação Portuguesa das Atividades Económicas*,
  Revisão 4 (INE), convertida do PDF para markdown: índice por secção (A–V) e
  pesquisa por código ou designação (com o caminho hierárquico de cada código).

## Backend (`api/docs_routes.py`, prefixo `/docs`)

| Rota | Descrição |
| --- | --- |
| `GET /docs/documents` | Lista os ficheiros de `data/docs` (mais recentes primeiro). |
| `GET /docs/document/{nome}` | Serve o ficheiro original (`?download=true` força descarga). |
| `GET /docs/markdown/{nome}` | Markdown do documento: `.md` irmão, o próprio `.md` ou conversão de texto (`.txt`, `.csv`, `.json`). |

O nome é validado dentro de `data/docs` (sem travessias de caminho). As rotas são
abertas, como o resto dos catálogos públicos.

## Gerar o markdown do CAE

```powershell
cd c:\LLMFinance\finance-llm
C:\LLMFinance\.venv\Scripts\python.exe _gen_docs_markdown.py
```

O script (`_gen_docs_markdown.py`) lê o quadro **2 – Estrutura** do PDF
(páginas 53–90) com o `pymupdf`, reconstrói a tabela por posições das palavras
(SECÇÃO · DIVISÃO · GRUPO · CLASSE · SUBCLASSE · DESIGNAÇÃO) e escreve
`data/docs/CAE-Rev.4.md` com a árvore:

```
## Secção C — Indústrias transformadoras
### Divisão 10 — Indústrias alimentares
#### Grupo 101 — …
##### Classe 1011 (subclasse 10110) — …
- **10201** — Preparação de produtos da pesca e da aquicultura
```

Números atuais (CAE-Rev.4): 22 secções · 87 divisões · 275 grupos · 508 classes ·
809 subclasses.

Detalhes da extração que importam:

- o cabeçalho do quadro é detetado pelo conjunto de rótulos **no topo e por
  ordem** (as páginas de metodologia mencionam os mesmos nomes no texto corrido
  e eram confundidas com a tabela);
- a coluna **DESIGNAÇÃO** começa logo a seguir à SUBCLASSE (o rótulo está
  centrado na mancha, não à esquerda);
- designações que rebentam em várias linhas físicas (secções E, J, K, U) são
  coladas ao item mais próximo na vertical — senão ficavam truncadas
  («e despoluição»);
- notas de rodapé (`Níveis idênticos à …`) são removidas.

## Frontend

- `src/pages/DocsPage.tsx` — a página (dois separadores, índice e pesquisa CAE).
- `src/docsApi.ts` — cliente das rotas (`listDocs`, `getDocMarkdown`, `docFileUrl`).
- Registo: entrada `docs` no `DOCK_CATALOG` (`src/dock.ts`), no módulo
  «Conhecimento e conteúdos» (`src/sidebarCatalog.ts`) e nas rotas de `App.tsx`
  (`/documentos`).

> **Nota**: `/docs` é a documentação da API (Swagger). A página da plataforma
> vive em **`/documentos`**.
