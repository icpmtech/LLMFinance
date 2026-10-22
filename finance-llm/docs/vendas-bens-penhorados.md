# Venda de bens penhorados em processos executivos

Módulo que recolhe e pesquisa os **bens penhorados em processos executivos em
relação aos quais foi determinada a venda**. Junta duas fontes oficiais, ambas
públicas e sem captcha:

| Fonte | Endereço | O que traz |
|---|---|---|
| **CITIUS** (Ministério da Justiça) | https://www.citius.mj.pt/portal/consultas/ConsultasVenda.aspx | tribunal, datas, tipo de bem, estado, valor base, modalidade, descrição e processo |
| **e-leiloes.pt** (agentes de execução) | https://www.e-leiloes.pt | processo, comarca, executados com NIF, agente de execução, GPS, fotografias e ónus |

Cada bem fica num documento único (mesmo esquema para as duas fontes), com o
tribunal/comarca, o processo (número e juízo), o tipo e subtipo de bem, a
modalidade, o estado, as datas da venda, os valores (base, mínimo, abertura,
lance atual), a descrição, a localização (distrito/concelho/freguesia, morada,
código postal e coordenadas) e os intervenientes.

## Fluxo do CITIUS (ASP.NET WebForms com `UpdatePanel`, sem captcha)

| Passo | Pedido | Resultado |
|---|---|---|
| 1 | `GET ConsultasVenda.aspx` | formulário com `__VIEWSTATE`, `__EVENTVALIDATION`, `ddlTribunais` (214 serviços), `txtCalendarDesde`/`txtCalendarAte` (`dd-mm-aaaa`), `ddlTiposBem`, `ddlModalidades` e `ddlEstados` |
| 2 | `POST` assíncrono (`X-MicrosoftAjax: Delta=true`, `__ASYNCPOST=true`) com `ctl00$ContentPlaceHolder1$btnSearch` | resposta *delta* com o painel `pnlUpdResults` (10 bens por página) e o paginador `Pager1` |
| 3 | `POST` com `__EVENTTARGET=ctl00$ContentPlaceHolder1$Pager1$lnkNext` | página seguinte (usa o `__VIEWSTATE`/`__EVENTVALIDATION` da resposta anterior) |
| 4 | `POST ConsultasVenda.aspx/GetHtmlDetails` com `{"htmlId": <id>}` | HTML com a **descrição completa** e os **intervenientes** (a lista trunca a descrição e não mostra as partes) |

Detalhes que custaram a descobrir:

- Ao contrário da consulta de citações editais, esta usa **`UpdatePanel`**: a
  resposta do `btnSearch` é um **delta** (`updatePanel|…|pnlUpdResults|…`), não a
  página inteira. É preciso `__ASYNCPOST=true` e o `ScriptManager1`.
- A **data da venda é obrigatória** (validação do servidor: «Indique o
  tribunal.»/datas). A janela aceite é a que o portal publica no calendário —
  cerca de **um mês atrás e dois à frente** (`default_window()`); é por isso que
  o módulo tem `DEFAULT_WINDOW_DIAS_ATRAS`/`DEFAULT_WINDOW_DIAS_FRENTE`.
- A **data tem de ir em `dd-mm-aaaa`** (`_portal_date`), não em ISO.
- A página é **UTF-8** (as publicações societárias é que são Windows-1252).
- Cada bem tem um `htmlId` (o `Viewer.Abrir(this, <id>, 'ConsultasVenda.aspx/GetHtmlDetails', …)`),
  usado como `referencia` e como chave do pedido de detalhe.
- O certificado TLS do `citius.mj.pt` chega **sem o intermédio correto**; o
  cliente repara a cadeia pelo AIA (`collectors/tls_chain.py`) em vez de desligar
  a verificação — ver [insolvencias-cire.md](./insolvencias-cire.md#certificado-tls-incompleto-cadeia).

## Fluxo do e-leiloes.pt (API pública em JSON)

O frontend é uma SPA Vue; os dados vêm de `/api/` (sem autenticação para a
listagem e o detalhe dos eventos):

| Passo | Pedido | Resultado |
|---|---|---|
| 1 | `GET /api/Param/VerbasTipos/`, `/Param/VerbasSubtipos/`, `/Param/ModalidadesVenda/`, `/Param/VendasEstados/` | dicionários de tipos, subtipos, modalidades e estados |
| 2 | `GET /api/Eventos/?tableParams={"first":N,"rows":12,"filters":{}}` | 12 eventos e o paginador (`pagination.total`, ex.: 2 735) |
| 3 | `GET /api/Eventos/<referencia>/` | detalhe: processo, comarca, tribunal/juízo, executados (string JSON com NIF), agente de execução, coordenadas, fotografias, ónus e descrição predial |

Notas: o parâmetro `rows` é ignorado pelo servidor (devolve sempre **12** por
página) — a paginação avança com `first` em passos de 12. Os `executados` vêm
como **texto JSON** dentro do campo (`"[{\"nif\":…}]"`), que é descodificado em
`_eleiloes_executados`. As datas já vêm em ISO (`AAAA-MM-DDTHH:MM:SS`).

## Recolha, ficheiros e índice

1. **Recolha** (`POST /vendas/collect`) — percorre as fontes escolhidas e grava
   tudo em **JSON** (`data/vendas_penhorados/runs/<run_id>.json` + `.meta.json`).
   Corre em segundo plano; o progresso vê-se em `GET /vendas/jobs/{id}`.
2. **Importação** (`POST /vendas/ingest`) — lê o JSON gravado e indexa em
   `finance_vendas_penhorados`. É **idempotente**: o `_id` é o `venda_id`
   (`citius:<htmlId>` ou `eleiloes:<id>`), pelo que reimportar não duplica
   (`skipped_existing` conta os que já existiam).
3. **Pesquisa** (`GET /vendas/search`) — texto livre (título, descrição,
   processo, tribunal, morada, nomes dos intervenientes/executados), fonte,
   referência, processo, tribunal, comarca, tipo de bem, modalidade, estado,
   distrito, concelho, morada, executado (nome/NIF), datas da venda e intervalo
   de valor base; devolve facetas e a soma/média/máximo dos valores.

## Interface

- `/vendas` — página **Vendas Penhorados** (grupo «Dados públicos» da barra
  lateral e do dock), com as secções *Pesquisa*, *Recolha*, *Execuções* e
  *Estado*.
- A pesquisa mostra cartões com o valor base, estado, modalidade, localização,
  intervenientes e fotografias (e-leiloes.pt), com ligação ao portal.
- A recolha permite escolher as fontes, o tribunal do CITIUS (214 serviços), a
  janela de datas, o tipo/modalidade/estado, os limites de páginas/detalhes e se
  importa logo para o Elasticsearch.

## API

| Método | Rota | Descrição |
|---|---|---|
| GET | `/vendas/meta` | metadados do módulo (fontes, índice, pasta e limites) |
| GET | `/vendas/options` | opções do formulário do CITIUS (cache de 1 h) |
| GET | `/vendas/status` | volumetria do índice (documentos, datas, valores, distribuições) |
| GET | `/vendas/search` | pesquisa dos bens indexados (facetas + valores) |
| GET | `/vendas/runs` | recolhas gravadas em `data/vendas_penhorados/runs` |
| GET | `/vendas/runs/{run_id}` | resumo de uma recolha (opcionalmente com os itens) |
| GET | `/vendas/jobs`, `/vendas/jobs/{id}` | recolhas em curso e recentes |
| POST | `/vendas/collect` | arranca uma recolha (grava JSON e, se `index`, importa) |
| POST | `/vendas/jobs/{id}/stop` | sinaliza a recolha para parar |
| POST | `/vendas/ingest` | importa uma recolha (ou itens avulsos) para o Elasticsearch |
| DELETE | `/vendas/runs/{run_id}` | apaga os ficheiros (e, com `drop_index`, os documentos) |

Os endpoints de escrita exigem sessão; a leitura é pública (como nos restantes
módulos de dados públicos).

## Testes

`tests/test_vendas_penhorados.py` cobre o que não depende da rede nem do
Elasticsearch: conversão de datas (`dd/mm/aaaa` → ISO), números em formato
português («220 000,00 €»), separação do processo/juízo, leitura dos pares
`<strong>Rótulo:</strong> valor` da lista e do painel «Detalhes do bem»
(incluindo os **intervenientes**), criação do `venda_id` e do `pub_id` estável.
