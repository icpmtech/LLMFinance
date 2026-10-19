# site-css — o CSS do site público

O site público (`/site/...`) é HTML gerado pelo `api/cms_render.py`. O aspeto dele
vive aqui, em Tailwind v4, e é **compilado** para `api/site_assets/site.css`, que
vai para o repositório: quem serve o site não precisa de Node, e o container do
backend não tem passo de build.

## Compilar

```powershell
cd site-css
npm install          # só na primeira vez
npm run build        # escreve ../api/site_assets/site.css (minificado)
npm run watch        # o mesmo, a cada gravação
npm run check        # compila para ./build/site.css, sem tocar no que é servido
```

Depois de compilar, **reinicie o backend** (o ficheiro é servido em `/site/site.css`):

```powershell
docker restart finance-llm-backend
```

O `api/site_assets/site.css` é versionado: um clone que não corra `npm run build`
continua com o aspeto certo. Os testes (`tests/test_site_css.py`) leem **o ficheiro
compilado**, por isso uma regra que exista só no `src/` não passa por engano.

## Como está organizado

| Ficheiro | O que tem |
| --- | --- |
| `src/site.css` | Tudo: `@import "tailwindcss"`, os tokens do tema, a camada base e os componentes |
| `../api/site_assets/site.css` | O resultado compilado — é o que o browser descarrega |
| `../api/cms_render.py` (`_css`) | Em linha, nas páginas, só as **variáveis do tema** |

O `cms_render._css()` escreve um bloco `:root{--bg…--accent…--radius…}` com o que
está definido no CMS (tema, cor de destaque e raio dos cantos). É a única parte do
CSS que não pode ser compilada: muda sem recompilar. A folha compilada só usa
`var(--…)`, e o `@theme inline` faz com que os utilitários também saiam em
`var(--…)` em vez de ficarem presos ao valor compilado.

As páginas ligam a folha com `<link rel="stylesheet" href="/site/site.css">`; o
`extra_css` de cada página (as páginas de pesquisa e de remunerações têm o seu)
continua em linha, porque depende dos dados.

## A página inicial

A página com o template `pagina-inicial` recebe a classe `pagina-inicial` no
`.wrap` (`render_page` → `_layout`). É o gancho para o desenho próprio da
abertura: faixa escura com os números sobrepostos, ritmo vertical mais amplo e
cartões compactos no telefone. As páginas interiores não são afetadas.

Cada raiz de bloco leva também `data-bloco="<tipo>"` (`hero`, `numeros`,
`texto`, `imagem`, `destaques`, `passos`, `faq`, `cta`, `blog`, `galeria`…). O
CSS usa esse atributo em vez de uma classe nova, para não alterar as classes que
o CMS e os testes já conhecem.

O cabeçalho passa a usar o painel de menu até **1199px**: com 9-10 entradas a
fila de pastilhas empurrava a página para o lado em ecrãs de 1024px. A partir de
1200px volta a fila de uma linha.

## Regras a manter

**Nenhuma classe do site pode ter o nome de um utilitário do Tailwind.** Os
utilitários são emitidos na camada `utilities`, que ganha à camada `components`
onde vive o resto do site: `.grid`, `.block`, `.flex` ou `.hidden` com regras
próprias ficariam silenciosamente trocadas pelo utilitário. A grelha de cartões
chama-se `.grelha` por isso mesmo, e o `tests/test_site_css.py` falha se aparecer
uma colisão nova. O `@source "../../api"` lê o HTML gerado pelo Python (que é onde
as classes vivem) e, por isso, apanha também palavras soltas do texto — daí o
cuidado com os nomes.

**O que o preflight do Tailwind apaga e o site contava receber do browser tem de
voltar, na camada `base`:** o peso dos títulos (`h1`-`h3` têm tamanho próprio, mas
não peso), os marcadores das listas, a margem delas e os 40px de indentação. Está
lá, comentado. Outras mudanças do preflight são aceites de propósito: os campos de
formulário passam a usar a letra do site (`font: inherit`), as imagens e os SVG
ficam `display: block`, e o atributo `hidden` passa a esconder **mesmo** (tem
`!important`, ao contrário do que o browser fazia — era por isso que a mensagem
«Nenhuma linha corresponde à pesquisa» aparecia nas tabelas de remunerações com as
linhas todas a corresponder).

**O CSS próprio de cada página é em linha e sem camada, por isso ganha sempre ao
CSS do site** — antes decidia a especificidade e a ordem. Uma regra do site que
dependa de ganhar a uma regra da página (`.section + .section` contra
`.grafico { margin: 0 0 26px }`, por exemplo) tem de viver na página, não aqui.

## Verificações

```powershell
cd ..
.\.venv\Scripts\python.exe -m pytest tests/test_site_css.py tests/test_biblioteca_publica.py -q
```

No browser (com o backend a correr em `127.0.0.1:4180`), os e2e do site estão em
`chat-ui/e2e/`: `test_site_paginas_sistema.py`, `test_cms_menu_submenus.py` e
`test_plataforma_cabecalho_publico.py`.
