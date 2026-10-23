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

O relatório é **opcional e decide-se no artigo**: a opção «Relatório em PDF» no
editor do artigo (campo `report_pdf` do CMS) mostra ou esconde o botão. Sem ela,
a rota responde 404 — um endereço guardado também não serve o ficheiro. Um
artigo que não traga o campo (a semente, por exemplo) continua com relatório:
foi assim que nasceu o artigo «Contratos públicos em 2026» e não se muda o que
já está publicado.

## Partilha do artigo

Ao lado do relatório, cada artigo publicado tem um botão «Partilhar» que abre o
menu das redes e usa a **Web Share API** do sistema (`navigator.share`) com o
título e o **endereço absoluto** do artigo (o `base_url` das definições do site).
Onde a partilha do sistema não existe, o botão copia o endereço e diz «Ligação
copiada».

As redes vêm de um catálogo único (`api/site_acoes.py`, `REDES`): WhatsApp, X,
Facebook, LinkedIn, Instagram, TikTok, YouTube, Reddit, Telegram, Threads,
Bluesky, Pinterest, Tumblr, GitHub e email, mais «Copiar ligação» e
«Partilhar…». TikTok, Instagram e YouTube não aceitam o endereço num link: nesses
o botão copia a ligação e abre a rede («Ligação copiada — cole no TikTok»).

O botão nasce escondido e é o próprio script do artigo que o mostra, quando há
partilha ou área de transferência para usar: num contexto sem HTTPS não há
nenhuma das duas, e um botão que não faz nada é pior do que nenhum. Como o resto
do site, a partilha é o único elemento que precisa de JavaScript — o artigo
lê-se igual sem ele. Na pré-visualização de um rascunho não entra o botão nem o
script: um rascunho não tem endereço público para partilhar.

## Partilha e favoritos nos cartões do blog

Os cartões de `/site/blog` (e das listas de artigos dentro de páginas do CMS)
trazem a estrela «Guardar» e a partilha do artigo, no rodapé do cartão. O script
das ações entra **uma vez por página** (ver `_layout`), não em cada cartão.

Cada cartão mostra ainda as **hashtags do artigo** (as etiquetas, até quatro;
as restantes ficam num «+N»), cada uma a ligar à lista por etiqueta
(`/site/etiqueta/<tag>`). Saem dos próprios `tags` do artigo — não há uma
segunda lista para manter.

Tudo isto se configura no CMS, em **Aparência → Partilha e favoritos**:

| Campo | Para que serve |
| --- | --- |
| `redes` | Redes do menu «Partilhar» (artigos, cartões e estudos) |
| `cartoes` | Ações nos cartões da lista do blog |
| `cabecalho` | Barra «Partilhar · Guardar» no topo do blog |
| `guardar` | Botão «Guardar» (favoritos no navegador) |
| `redes_cabecalho` | Fila de redes no cabeçalho do site |

A fila do cabeçalho e as ligações do rodapé usam os endereços públicos de
**Ligações** (as mesmas redes do catálogo; vazio = escondido). A configuração
guarda-se com as definições do site (`settings.partilha`).

### Modelos de configuração (só administradores)

Em Aparência há modelos prontos a aplicar — «Completo», «Redes sociais»,
«Profissional», «Mínimo» e «Só favoritos» — e um administrador pode guardar a
configuração atual como modelo novo (ficam em `settings.partilha_modelos`).

O bloco da partilha e os modelos são **só de administradores**, na API
(`PUT /cms/settings` recusa a alteração a um membro, com 403) e no painel (a
secção aparece desativada). Rotas: `GET /cms/partilha`,
`POST /cms/partilha/modelos`, `DELETE /cms/partilha/modelos/{id}` e
`POST /cms/partilha/modelos/{id}/aplicar`.

## A página do blog (blocos no índice)

O índice `/site/blog` pode ser **montado com blocos**, sem perder a lista de
artigos: a página escolhida em **Aparência → Página do blog** (`blog_page_id`)
entra no índice com os seus blocos (abertura, texto, chamada à ação, contactos,
formulário…), pela ordem do editor.

- o bloco **«Últimos artigos»** marca o lugar da lista: é aí que entra a lista
  gerada, com as categorias, as etiquetas, o cartão de cada artigo e a
  **paginação** (`?page=`);
- sem esse bloco, a lista fica **no fim**, depois dos blocos da página;
- só o primeiro bloco «Últimos artigos» recebe a lista — duplicá-lo mostrava os
  mesmos cartões duas vezes;
- os agregados `/site/categoria/<slug>` e `/site/etiqueta/<tag>` continuam a
  ser o índice gerado (os blocos são só do índice principal).

No painel, **Blog → Página do blog** abre o editor de blocos da página em uso
(ou cria uma com a abertura e o bloco «Últimos artigos», já publicada e ligada
nas definições). Sem página escolhida, o índice é o gerado de sempre.
