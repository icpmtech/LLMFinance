# Blog e artigos do site (CMS)

Os artigos do site vivem no **CMS** (entidade `posts` do `api/cms_store.py`) e
são desenhados pelo `api/cms_render.py` em `/site/blog`, `/site/blog/{slug}`,
`/site/categoria/{slug}` e `/site/etiqueta/{tag}`.

Um artigo tem **duas partes**, desenhadas por esta ordem:

1. o **Markdown** (`markdown`) — a abertura e o texto corrido;
2. os **blocos** (`blocks`) — os mesmos blocos das páginas (`numeros`, `grafico`,
   `tabela`, `texto`, `aviso`, `cta`…), pela ordem da lista.

É por isso que um artigo pode ter gráficos e tabelas sem HTML escrito à mão: o
corpo é Markdown e as peças de dados são blocos.

## Bloco `grafico`

Barras horizontais em **HTML/CSS puro** — sem JavaScript e sem bibliotecas. A
página do site é também o `offline.html` do service worker, por isso um gráfico
que dependesse de script desaparecia offline e no PDF.

| Campo | O que é |
| --- | --- |
| `title` | Título da secção (`h2`) |
| `note` | Linha de leitura, por baixo do título |
| `format` | `euros` (por omissão), `numero` ou `percentagem` |
| `legend` | Nomes das duas séries, quando há segunda (`["Contratos", "Valor"]`) |
| `series` | Lista de `{label, value, value2?, note?}` |
| `source` | Fonte citada no fim do gráfico |
| `max` | Escala fixa (opcional; por omissão é o maior valor) |

Regras que interessam a quem edita:

- o **valor vai sempre escrito** ao lado do nome (não é só a barra): quem usa
  leitor de ecrã, quem imprime e quem abre a página sem CSS lê o número;
- **basta uma linha com `value2`** para todas as barras passarem a ter duas
  séries na mesma escala — é assim que se comparam pesos (número de contratos
  contra valor) sem dois gráficos lado a lado;
- um segundo valor **vazio** (`""`, ausente ou `0`) é ausência de série, não uma
  barra a zero;
- a barra mais pequena tem 2px de largura: um valor residual continua a ver-se.

No **telefone** o nome e o valor partilham a linha e a barra ocupa a largura
toda (o eixo que sobra); a partir de 800px a lista fica com a **medida de leitura
do texto (760px)**, senão o nome e o valor ficavam a um ecrã de distância um do
outro. As tabelas de quatro ou mais colunas rolam dentro do seu contentor
(`.tabela-rolavel`), nunca empurram a página.

O editor do bloco no painel escreve as barras em texto, uma por linha
(`nome | valor | 2.º valor | nota`) — o mesmo idioma das tabelas — e aparece
sozinho ao acrescentar o bloco: a lista de tipos vem do servidor
(`GET /cms/catalogue`).

## Artigo «Contratos públicos em 2026»

O conteúdo vive em `cms_editorial.artigo_contratos_2026()` — resumo, gráficos,
tabelas e a nota de método — e entra:

- na **semente** (`cms_store._seed`), para uma instalação nova;
- pelo **instalador do site** (`_atualizar_site_sabemos.py`), para uma
  instalação já em uso: o deploy de código não leva a pasta `data/`, por isso o
  CMS de produção não recebe conteúdo novo sozinho.

Os números são os da base de contratos indexada, com a **data da leitura escrita
em cada gráfico**. O ano não está fechado, por isso a comparação com 2025 é feita
com o **período homólogo**, nunca com o ano completo.

```powershell
python _atualizar_site_sabemos.py     # publica/atualiza o artigo e o modelo do site
```

## Relatório PDF do artigo

`GET /site/blog/{slug}/pdf` devolve o artigo em PDF (resposta `attachment`), com
o mesmo conteúdo e as mesmas fontes da página. O botão
«Descarregar o relatório (PDF)» aparece no topo do artigo — **não** na
pré-visualização de um rascunho, porque a rota só serve artigos publicados.

As secções do relatório saem dos próprios blocos
(`api/cms_post_report.py` → `contribuintes_report.render_pdf`): não há uma
segunda cópia dos números, e um artigo novo ou corrigido passa a ter PDF sem
ninguém escrever nada de novo. Os gráficos entram como tabela (nome, valor,
nota) — é o mesmo conteúdo numa forma que se imprime e se cita.
