# Relatórios a pedido (com pagamento por MB Way) e Estúdio de relatórios

A plataforma vende **relatórios**. Há duas formas de os produzir:

1. **à mão** — o cliente pede na página **Relatórios**, paga por **MB Way** para
   o número configurado na administração e, quando o relatório fica pronto, o
   ficheiro é anexado ao pedido e fica disponível para descarregar com o estado
   **Gerado**;
2. no **Estúdio** (ver abaixo) — a equipa monta o relatório a partir das fontes
   de dados da plataforma, gera o PDF e publica-o no catálogo ou na loja; quem
   compra recebe o PDF **automaticamente** depois do pagamento.

- Página do cliente: `/reports` (aplicação **Relatórios** no menu lateral). Quem tem
  acesso de backoffice vê aí um separador **Backoffice**; o Estúdio tem página
  própria (`/report-studio`) — a área de Administração é restrita ao papel `admin`,
  por isso é este o caminho das contas de equipa.
- Backoffice: **Administração → Relatórios** (`/admin`, separador «Relatórios»).
- Configuração: o mesmo separador, sub-separador **Definições** (e **Catálogo**).

## Catálogo por omissão

| Pacote | Preço | Empresas | Entrega | Inclui |
| --- | --- | --- | --- | --- |
| Relatório Corporativo | **Grátis** (era 7 €) | 1 | 1 dia | Eventos, marcas, tribunal/insolvência, estado de atividade, dívida fiscal, subsidiárias, empresas relacionadas, contratos públicos |
| Relatório Financeiro Resumido | **18 €** | 1 | 2 dias | Dados estruturais + saúde financeira, vendas, resultados, custos, importações/exportações, colaboradores |
| Relatório Financeiro Detalhado | **24 €** (recomendado) | 1 | 2 dias | Tudo do resumido + demonstração de resultados, balanço, anexo, fluxos de caixa, rácios, informação por estabelecimento |
| Relatório Concorrência | **130 €** | até 6 | 5 dias | Tudo o anterior + balanço 3 anos, rating, setores, quota de mercado, ~50 rácios comparados |

Os preços são **finais** (IVA incluído à taxa configurada, 23 % por omissão) e
podem ser editados em *Definições → Catálogo* (título, subtítulo, etiqueta,
preço, preço antigo, dias de entrega, nº de empresas, itens e estado).

## MB Way

O número de destino é configurável em *Definições → Número MB Way* (valor inicial
**919520386**). Há dois modos:

1. **Manual (por omissão, sem chaves)** — o cliente vê o número e a referência do
   pedido, transfere pelo MB Way, carrega em **«Já paguei — informar»** e o pedido
   fica `aguarda confirmação`; o backoffice confirma (ou rejeita) na ficha.
2. **Automático (IFTThenPay)** — com a **Chave de API (MbWayKey)** preenchida, o
   cliente indica o telemóvel, o backoffice recebe o valor por MB Way e a
   plataforma envia-lhe um **pedido de pagamento** para o telemóvel. O pagamento
   pode confirmar-se sozinho (consulta de estado em
   `GET /reports/requests/{id}/payment/status`, ou confirmação automática na
   resposta da API).

   - URL por omissão: `https://mbway.ifthenpay.com/ifthenpaymbw.ashx`
     (`MbWayKey`, `canal=03`, `Referencia`, `Valor`, `NroTelefone` no formato
     `351#9XXXXXXXX`, `Descricao`).
   - Estados tratados: `000` pendente · `020` pago · `014` expirado ·
     `016` cancelado · outros → erro.
   - A chave pode ficar no `.env` (`MBWAY_API_KEY` ou `IFTHENPAY_MBWAY_KEY`) em
     vez de ser escrita pela interface — útil em instalações em contentor.

   Nenhuma falha da API do MB Way trava o fluxo: o erro é mostrado ao cliente e o
   pedido segue no modo manual.

## Estúdio de relatórios (administradores e gestores de relatórios)

O **Estúdio** é a oficina onde a equipa monta os relatórios que a plataforma
vende. Tem **página própria** — `/report-studio`, com entrada no menu lateral
(*Relatórios → Estúdio de relatórios*) e um atalho no cabeçalho de `/reports` —
e a API vive em `/reports/studio/*`.

**Quem entra:** papel `admin`, papel `manager` (gestor de plataforma) ou qualquer
conta da lista *Definições → Gestores de relatórios* (`settings.report_managers`).
A lista existe para dar acesso a quem produz relatórios sem lhe dar papel de
gestão; a escrita dessas contas em `/reports/studio/*` é autorizada no middleware
de permissões (`main.py`), sem alargar o resto do módulo.

**Como se monta um relatório:**

1. **Modelo** — há 10 modelos prontos (`executivo`, `mercado-cpv`, `evolucao`,
   `geografia`, `entidades`, `mercados`, `dossie`, `concorrencia`, `area-cae` e
   uma folha em branco). Cada modelo traz blocos já ligados às fontes; os blocos
   que não se aplicam às fontes de agora são retirados com aviso (`warnings`) em
   vez de darem gráficos vazios.
2. **Parâmetros** — os modelos de empresa (`concorrencia`, `area-cae`) pedem a
   **empresa** (`vars.empresa`: NIF de 9 dígitos ou nome no cadastro) e aceitam o
   nome a usar (`vars.nome`). Os blocos escrevem `{{empresa}}`, `{{nif}}`,
   `{{nome}}`, `{{cae}}`, `{{cpv}}` e `{{site}}` nos títulos, filtros e pesquisas;
   o estúdio resolve-os em cada execução — `{{nif}}`, `{{nome}}`, `{{cae}}`,
   `{{cpv}}` e `{{site}}` são **calculados da ficha da empresa**, pelo que um bloco
   de mercado segue o CAE e o CPV principal sem trabalho manual. Para produzir o
   mesmo relatório para outra empresa, **duplicar e mudar o NIF**: os parâmetros
   herdam-se na cópia e nenhum filtro fica preso a uma empresa.
3. **Blocos** — `heading`, `text`, `note`, `ai`, `kpi`, `chart`, `table`,
   `graph`, `empresa` e `web`. Os blocos de dados guardam `source` (dataset do
   Visualizador), `dimensions`, `measures`, `filters`, `limit`, `top_n` e `width`
   (12/6/4). Os ids são validados contra o catálogo **ao gravar** (o que a fonte não
   tem sai do bloco).
   - **`empresa` (ficha 360)** — junta o que não se agrega: cadastro e **CAE**,
     situação e site, órgãos sociais (**sócios e gerentes**) e restantes pessoas
     com cargos, **atos societários**, **riscos** (CIRE: insolvências e menções
     como credor, devedores das Finanças e Segurança Social, pontuação de risco),
     marcas (INPI), firmas (RNPC), subvenções, imprensa e o **mercado** da empresa
     (clientes, dependência/HHI, evolução, contratos sem concurso, famílias de
     CPV) — mais os contratos por CPV, por ano e por cliente, agregações **exatas**
     pedidas ao Visualizador. Vem do serviço de descoberta
     (`descoberta_service.recolher`), o mesmo do painel de empresa; a ficha em
     memória é reutilizada 10 minutos, e diz sempre quantas fontes responderam e
     quais ficaram sem dados.
   - **`web` (produtos e serviços)** — pesquisa na web (`tools.web_search`:
     SearXNG da plataforma, Brave/SerpAPI ou DuckDuckGo, conforme o que estiver
     configurado) os produtos e serviços da empresa e apresenta os **excertos com
     a fonte**. Com modelo de IA configurado, escreve também um resumo de 3 a 5
     frases só com o que os excertos dizem; sem modelo, ficam os excertos (e o
     bloco di-lo).
4. **Fontes** — as mesmas do **Visualizador** (`/visualizador/*`): contratos,
   CPV, regiões, marcas, firmas, notícias, instrumentos, cotações, CRM, dossiês e
   documentos. Não há uma segunda implementação dos números: a pré-visualização e
   o PDF usam `visualizador_service.run_query` com o âmbito da sessão.
5. **Grafos** — um bloco `graph` usa **duas** dimensões (origem e destino) e
   devolve nós e arestas (ex.: adjudicante ↔ adjudicatário, pelo valor). A
   interface desenha-o em SVG; o PDF desenha o mesmo grafo e lista as relações.
6. **IA** — o separador *Assistente* escreve o sumário executivo, o texto de uma
   secção, os destaques dos dados e sugere blocos. Usa o modelo configurado da
   plataforma (`ontology_ai.ask_model` + `people_360.resolve_backend`); **sem
   modelo configurado devolve o texto factual** montado a partir dos indicadores
   e das primeiras linhas de cada bloco, e di-lo nas notas. O texto gerado só
   entra no PDF depois de estar escrito num bloco.
7. **PDF** — gerado no servidor com `reportlab` (o mesmo renderizador da casa:
   logótipo, cores da marca, rodapé com o email de apoio e a página). Gráficos de
   barras, linhas e circulares são desenhados nativamente, com os rótulos em
   forma curta (`23,7 mM €`) para não se sobreporem; as tabelas repetem o
   cabeçalho; as listas saem como pontos; os indicadores que não cabem na célula
   reduzem a letra em vez de partir o número. Fica em
   `data/reports/studio/<relatório>/<id>-<nome>.pdf` e é substituído quando se
   volta a gerar.
8. **Email de apoio** — o contacto que sai no rodapé de todas as páginas e na
   nota final é configurável em *Definições → Email de apoio*
   (`settings.support_email`); sem valor configurado usa-se
   `suporte@sabemos.studio` (`DEFAULT_SUPPORT_EMAIL`). É também para este
   endereço que vai o aviso de cada pedido do formulário de contacto do site.

**Os dois modelos de empresa:**

| Modelo | Para que serve | O que traz |
| --- | --- | --- |
| `concorrencia` — *Concorrência (uma empresa)* | Perceber onde a empresa ganha e com quem compete nas mesmas categorias | Ficha 360 (CPV, CAE, sócios e gerentes, pessoas, riscos, marcas, firmas, subvenções), indicadores e evolução dos contratos da empresa, CPV onde ganha, como contrata (procedimento), grafo de quem lhe compra, **concorrentes no CPV principal**, regiões onde esse CPV se compra, **empresas do mesmo CAE** e leitura com IA |
| `area-cae` — *Área de CAE e da empresa* | Olhar para a **área de atividade** antes da empresa: dimensão, território e situação registal do setor | Ficha 360, setor do CAE (empresas, score médio), CAE com mais empresas, situação registal, concelhos, empresas do mesmo CAE, contratos da empresa por tipo e procedimento, CPV da empresa e **produtos e serviços** (pesquisa web) |

Cada bloco de um modelo de empresa filtra-se pela variável (`{{nif}}`, `{{cae}}`,
`{{cpv}}`); se uma variável não se resolve (sem empresa, por exemplo), o filtro
desaparece e o bloco mostra o mercado todo em vez de falhar.

**Publicar e vender** (`POST /reports/studio/reports/{id}/publish`):

| Canal | O que acontece | Entrega |
| --- | --- | --- |
| `site` | Cria/atualiza o pacote `estudio-<slug>` no catálogo (`/reports`), com preço, preço antigo, etiqueta, dias e itens | `auto = estudio:<id>` |
| `loja` | Cria/atualiza o produto digital na loja, com preço, preço antigo, IVA e descrição | `auto_report = estudio:<id>` |
| `todos` | Os dois | — |

- A chave `estudio:<id>` é a **entrega automática**: no pedido do catálogo
  (`reports_store._gerar_automatico`) e na encomenda da loja
  (`shop_store._gerar_pdf`) o PDF é montado a partir do relatório publicado, com
  a referência do pedido e o nome de quem pediu. O cliente não espera pela equipa.
- `unpublish` desativa o pacote (fica no catálogo como inativo, para o histórico
  dos pedidos não perder o preço) e devolve o produto da loja a `rascunho`.
- Um relatório **sem blocos** não pode ser publicado.
- Publicar outra vez **atualiza** o pacote/produto (não duplica) — o preço do
  pacote é o que o cliente passa a ver; os pedidos antigos mantêm o seu.

## Área pública de relatórios gratuitos (`/site/relatorios-gratuitos`)

A montra dos relatórios no site do CMS: junta os **pacotes gratuitos do
catálogo** e os **documentos já gerados no Estúdio**, agrupados por **área de
trabalho**. Quem produz relatórios não tem de mexer nesta página — ela lê os dois
documentos (`reports.json`) a cada visita, por isso publicar um relatório no
Estúdio ou mudar um preço no catálogo aparece logo ali.

| Peça | Onde vive | O que faz |
| --- | --- | --- |
| `api/reports_library.py` | — | Lê o catálogo e o Estúdio, decide a **área** de cada documento e a **fronteira do download** |
| Bloco `relatorios` | `cms_store.BLOCK_TYPES` + `cms_render._render_library_block` | Desenha a secção (áreas, cartões, etiquetas de preço, botões) |
| Modelo `tpl_biblioteca` | `cms_store.TEMPLATE_BIBLIOTECA` | «Biblioteca de relatórios»: hero, números, o bloco e chamada à ação |
| Página `pag_relatorios` | `cms_editorial.paginas_do_site` | A página publicada, com hero, texto, o bloco, passos, FAQ e chamada à ação; entra no menu (cabeçalho e rodapé) |
| Submenus do cabeçalho | `reports_library.areas_for_menu` + `cms_store._acrescentar_submenus_dos_relatorios` | O item de menu que abre esta página ganha um submenu por área de trabalho, com os documentos publicados lá dentro |
| `GET /site/documento/{id}` | `cms_routes` | Descarrega o PDF **só** dos documentos gratuitos e publicados (resposta `attachment`, com o nome do documento) |

**O que entra na montra:**

- **pacotes do catálogo** ativos — os de preço 0 aparecem como «Grátis» e
  encaminham para o pedido na plataforma (um pacote automático e grátis é
  produzido logo, sem passar pelo pagamento);
- **relatórios do Estúdio** com `publication.site.published` **e** PDF gerado —
  aparecem como «Documento»; o gratuitos têm botão **Descarregar PDF**, os que
  têm preço encaminham para o catálogo;
- o pacote que a publicação cria no catálogo (`auto = estudio:<id>`) **não
  duplica** o documento: fica o documento, que é o que tem o ficheiro.

**No menu do site**, o item do cabeçalho que abre esta página ganha um **submenu
por área de trabalho**, com um título de relatório por entrada (gratuito
descarrega, pago vai para o catálogo — os mesmos destinos dos cartões). É
derivado a cada leitura, não fica guardado no menu: publicar um relatório no
Estúdio muda o cabeçalho sem ninguém voltar ao editor de menus e os relatórios já
publicados não precisam de ser republicados. Fronteiras do que é automático:

- entram **documentos** (relatórios publicados no site e com PDF), como na
  montra — os pacotes do catálogo pedem-se na plataforma e ficam na página;
- uma área sem documentos publicados não aparece no menu;
- submenus escritos à mão no editor ficam à frente dos automáticos;
- só o cabeçalho: no rodapé os submenus são uma fila de links
  (`cms_render._footer_links`) e o rodapé inteiro ficava com os títulos todos.

**A área** vem, por esta ordem: do campo `area` do pacote (editável no
backoffice), da **primeira etiqueta conhecida** do relatório (nos modelos do
Estúdio a primeira etiqueta é a matéria principal — `empresa`, `cae`, `cpv`…), do
identificador do pacote e, em último recurso, da área com que o pacote nasceu no
catálogo. O que não se conhece fica em **«Outros documentos»** — nunca
desaparece. As áreas são: *Contratação pública*, *Empresas e risco*, *Mercados e
notícias*, *Setor público* e *Documentos e dossiês*.

**A fronteira do download** é `reports_library.document_for_download`: documento
inexistente, não publicado, sem PDF ou **com preço** responde **404**. É o que
separa a montra do que é de clientes — um relatório pago nunca sai por aqui.
O PDF sai como **descarregamento** (`Content-Disposition: attachment`, com o nome
do documento) e o botão da página leva `download`: um PDF navegado abria — ou
ficava em branco, em webviews — em vez de ser guardado.

Para uma instalação já em uso (produção incluída) faltam duas coisas que o
deploy de código não leva, porque não envia a pasta `data/`: o **modelo** e a
**página**. Resolvem-se com o instalador do site, que é idempotente:

```powershell
python _atualizar_site_sabemos.py     # acrescenta o modelo e publica/atualiza a página
```

## Ciclo de vida

```
aguarda_pagamento → pagamento_confirmado → em_producao → gerado → entregue
                                   (a qualquer momento) cancelado | reembolsado
```

- O relatório **gratuito** salta o pagamento e entra logo em `em_producao`.
- `gerado` é atribuído automaticamente quando o backoffice **anexa o ficheiro**
  (pode ser anexado sem mudar o estado, com `mark_generated=false`).
- O cliente pode cancelar enquanto está `aguarda_pagamento` ou
  `pagamento_confirmado`; depois disso só o backoffice mexe.
- O **download** pelo cliente marca o pedido como `entregue`.

Pagamento (documento dentro do pedido):

```
method: mbway | transferencia | referencia | manual
status: pendente | aguarda_confirmacao | confirmado | rejeitado | reembolsado
```

## Notificações

Cada acontecimento gera uma notificação para quem interessa, visível no **sino**
das duas páginas (sondagem a cada 30 s):

- pedido novo → **contas de backoffice** (e administradores) + emails extra;
- pagamento declarado → backoffice;
- pagamento confirmado/rejeitado → cliente;
- `em_producao`, `gerado`, `entregue`, `cancelado`, `reembolsado` → cliente.

As contas de backoffice são geridas em *Definições → Contas de backoffice*
(uma por linha); o papel `admin` tem sempre acesso.

## Ficheiros

- Pedidos: guardados em `data/reports/files/<pedido>/<id>-<nome>` (volume `./data`).
- Estúdio: PDFs em `data/reports/studio/<relatório>/<id>-<nome>`.
- Limites: 25 MB por ficheiro, 12 ficheiros por pedido, extensões
  `pdf, doc, docx, xls, xlsx, csv, txt, md, json, zip, png, jpg, jpeg`.
- O download exige sessão (o dono do pedido ou o backoffice). No estúdio, o
  download exige acesso ao estúdio. Na interface é
  feito por `fetch` + `blob` — um `<a href>` direto não levava o `Authorization`.

## Dados

`data/reports/reports.json` (um documento, escrita atómica): `settings`
(inclui `backoffice_users` e `report_managers`), `catalogue`, `requests`,
`studio_reports`, `notifications`, `activity`.

Cada relatório do estúdio guarda os blocos, a publicação por canal
(`publication.site` com `package_id`, `publication.loja` com `product_id`), os
preços e os ficheiros gerados.

## API

| Método | Caminho | Quem |
| --- | --- | --- |
| GET | `/reports/catalogue` | sessão |
| GET | `/reports/summary` | sessão |
| POST | `/reports/requests` | sessão |
| GET | `/reports/requests` · `/reports/requests/{id}` | sessão (só os seus) |
| POST | `/reports/requests/{id}/payment` | sessão (só os seus) |
| GET | `/reports/requests/{id}/payment/status` | sessão (só os seus) |
| POST | `/reports/requests/{id}/cancel` | sessão (só os seus) |
| GET | `/reports/requests/{id}/files/{file}` | sessão (só os seus) |
| GET | `/reports/notifications` · POST `/reports/notifications/read` | sessão |
| GET | `/reports/backoffice/me` · `/reports/backoffice/inbox` | backoffice |
| GET/PATCH | `/reports/backoffice/requests/{id}` | backoffice |
| POST | `/reports/backoffice/requests/{id}/payment` | backoffice |
| POST | `/reports/backoffice/requests/{id}/files` (multipart) e `/files/base64` | backoffice |
| DELETE | `/reports/backoffice/requests/{id}/files/{file}` | backoffice |
| POST | `/reports/backoffice/requests/{id}/note` | backoffice |
| GET | `/reports/backoffice/export.csv` | backoffice |
| GET/PUT | `/reports/admin/settings` | admin |
| POST | `/reports/admin/catalogue` · DELETE `/reports/admin/catalogue/{id}` | admin |
| GET | `/reports/admin/overview` · `/reports/admin/export.csv` | admin |

Configuração relevante para os PDF: `support_email` (email de apoio no rodapé,
por omissão `suporte@sabemos.studio`) e `vat_rate` (preços finais).

Estúdio de relatórios (**admin, gestor de plataforma ou gestor de relatórios**):

| Método | Caminho | O que faz |
| --- | --- | --- |
| GET | `/reports/studio/me` | Confirma o acesso (papel, lista, canais) |
| GET | `/reports/studio/state` | Estado: fontes, modelos, limites, PDF e IA |
| GET | `/reports/studio/sources` | Fontes com dimensões, medidas e sugestões |
| GET | `/reports/studio/templates` · `/templates/{id}` | Modelos prontos (já validados) |
| GET | `/reports/studio/reports` | Relatórios do estúdio (procura, estado, canal) |
| POST | `/reports/studio/reports` | Cria a partir de um modelo ou do zero |
| GET/PUT/DELETE | `/reports/studio/reports/{id}` | Ficha, gravação e remoção |
| POST | `/reports/studio/reports/{id}/duplicate` | Duplica |
| POST | `/reports/studio/query` | Corre blocos de um rascunho (pré-visualização); aceita `report.vars` |
| POST | `/reports/studio/reports/{id}/run` | Corre o relatório gravado (devolve `vars` resolvidas) |
| POST | `/reports/studio/reports/{id}/pdf` | Gera e guarda o PDF |
| GET/DELETE | `/reports/studio/reports/{id}/files/{file}` | Descarrega/remove um PDF |
| POST | `/reports/studio/reports/{id}/publish` · `/unpublish` | Publica/retira (`site`, `loja`, `todos`) |
| POST | `/reports/studio/ai` · `/reports/studio/reports/{id}/ai` | Ajuda da IA (sumário, texto, destaques, blocos) |

Área pública do site (sem sessão): `GET /site/documento/{id}` descarrega o PDF de
um documento **gratuito e publicado** — resposta `attachment`, para o browser
guardar o ficheiro em vez de o abrir (404 em qualquer outro caso — ver
*Área pública de relatórios gratuitos*, acima).

## Testes

- `tests/test_reports.py` — domínio (26 verificações): catálogo, totais com IVA,
  fluxo de pagamento, notificações dos dois lados, limites de alvos, ficheiros,
  visibilidade das notas internas, indicadores e CSV.
- `tests/test_reports_studio.py` — estúdio (55 verificações): acessos (admin,
  gestor, lista de gestores), modelos validados contra as fontes, validação e
  limites dos blocos, **parâmetros do relatório e substituição de variáveis**,
  **ficha 360 da empresa** (cadastro e CAE, contratos por CPV, clientes, mercado,
  sócios e gerentes, pessoas, CIRE e devedores, marcas, firmas, subvenções,
  imprensa) e **pesquisa web de produtos e serviços** (com e sem IA, com a
  pesquisa em baixo e sem resultados), ciclo de vida do relatório, execução dos
  blocos (incluindo grafo), PDF real (com o email de apoio, os rótulos compactos e
  as secções da ficha e da web), publicação no catálogo e na loja, entrega
  automática do pedido pago, IA (com e sem modelo) e as rotas HTTP de ponta a
  ponta.
- `tests/test_biblioteca_publica.py` — área pública de relatórios gratuitos (12
  verificações): agrupamento por área (incluindo instalações antigas sem o campo
  gravado), gratuitos vs pagos, **fronteira do download** (gratuito e publicado
  descarrega; pago, não publicado e inexistente dão 404), desenho do bloco do CMS
  (com e sem dados, filtro por área, só gratuitos), modelo e página editorial e
  as rotas públicas `/site/documento/{id}` e `/site/relatorios-gratuitos`.
- `_probe_reports_asgi.py` — rotas completas em processo (42 verificações), sem
  servidor nem Elasticsearch (sessões falsas e `TestClient` sem lifespan).
- `_probe_reports_api.py` — o mesmo ciclo contra a API a correr (precisa de
  Elasticsearch para emitir sessões).

## Armadilhas conhecidas

- **`require_backoffice` também aceita administradores**: se o backoffice parecer
  «vazio» é porque ainda não há contas na lista *nem* pedidos criados.
- O aviso de pedido novo vai para as **contas de backoffice + administradores**;
  se o Elasticsearch estiver em baixo a lista de administradores fica em cache
  (60 s) e os últimos valores conhecidos são reutilizados — nunca se perde o
  aviso para a equipa configurada.
- O ficheiro do relatório é servido por `FileResponse` a partir de `data/reports`;
  em Docker, `./data` é um volume, tal como o resto da plataforma.
- A pasta `data/reports/` é **partilhada**: este módulo usa `reports.json`,
  `files/<pedido>/` e `studio/<relatório>/`, mas há geradores de PDF da plataforma
  (ex.: recolha Racius) que escrevem ficheiros soltos na mesma pasta
  (`entity_*.pdf`). Não colidem — não reutilizar `reports.json` para outra coisa.
- **Publicar não gera o PDF na hora**: o ficheiro é produzido quando o cliente
  paga (ou quando o backoffice repete em `produzir_pendentes`). Se o
  Elasticsearch estiver em baixo, o pedido pago fica sem ficheiro, com nota
  interna — a repetição gera-o sem o cliente pagar outra vez.
- **Um relatório publicado fica ligado pelo id**: se o relatório for apagado do
  estúdio, o pacote/produto continua a existir mas a geração falha (nota interna
  no pedido). Retire-o do canal antes de apagar.
- A lista *Gestores de relatórios* dá acesso ao **estúdio**, não ao backoffice nem
  à administração: são três listas/papéis diferentes (`report_managers`,
  `backoffice_users` e o papel `admin`).
- O catálogo de fontes do estúdio fica em cache 60 s e é o do Visualizador: se
  uma fonte nova não aparecer, aguarde esse tempo (ou reabra a página).
