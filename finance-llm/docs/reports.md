# Relatórios a pedido (com pagamento por MB Way)

A plataforma vende **relatórios** que são produzidos à mão pela equipa: o cliente
pede na página **Relatórios**, paga por **MB Way** para o número configurado na
administração e, quando o relatório fica pronto, o ficheiro é anexado ao pedido e
fica disponível para descarregar com o estado **Gerado**.

- Página do cliente: `/reports` (aplicação **Relatórios** no menu lateral). Quem tem
  acesso de backoffice vê aí um separador **Backoffice** — a área de Administração
  é restrita ao papel `admin`, por isso é este o caminho das contas de equipa.
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

- Guardados em `data/reports/files/<pedido>/<id>-<nome>` (volume `./data`).
- Limites: 25 MB por ficheiro, 12 ficheiros por pedido, extensões
  `pdf, doc, docx, xls, xlsx, csv, txt, md, json, zip, png, jpg, jpeg`.
- O download exige sessão (o dono do pedido ou o backoffice). Na interface é
  feito por `fetch` + `blob` — um `<a href>` direto não levava o `Authorization`.

## Dados

`data/reports/reports.json` (um documento, escrita atómica): `settings`,
`catalogue`, `requests`, `notifications`, `activity`.

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

## Testes

- `tests/test_reports.py` — domínio (26 verificações): catálogo, totais com IVA,
  fluxo de pagamento, notificações dos dois lados, limites de alvos, ficheiros,
  visibilidade das notas internas, indicadores e CSV.
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
- A pasta `data/reports/` é **partilhada**: este módulo usa `reports.json` e
  `files/<pedido>/`, mas há geradores de PDF da plataforma (ex.: recolha Racius)
  que escrevem ficheiros soltos na mesma pasta (`entity_*.pdf`). Não colidem — não
  reutilizar `reports.json` para outra coisa.
