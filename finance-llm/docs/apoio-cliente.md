# Apoio ao cliente (substitui o Tawk.to)

Chat de apoio em tempo real entre **visitantes** das páginas públicas (site do
CMS, loja e SPA) e **operadores** com papel `admin` no backoffice. Substitui o
Tawk.to em todas as superfícies do portal.

## Superfícies

| Superfície | Como entra |
| --- | --- |
| Site do CMS (`/site/...`) | `support_widget.SUPPORT_SNIPPET` no `<head>` (fora da pré-visualização do editor) |
| Loja (`/loja/...`) | o mesmo snippet |
| SPA (`/`, `/login`, `/register`) | `chat-ui/src/components/SupportChat.tsx` instala o mesmo `support_widget.js` |
| Backoffice | Administração → **Suporte** (`AdminPage` + `AdminSupportPanel.tsx`) |

O widget é um único JavaScript autocontido (`api/support_widget.js`, servido em
`/support/widget.js`) que desenha num **Shadow DOM** para não colidir com o CSS
de cada site. A base da API é configurável (`data-api-base`; por omissão
`/api`), pelo que funciona em `localhost:4180`, num túnel ou no domínio público.

## Fluxo

1. O widget pede `POST /support/visitors` e recebe um **token de visitante**
   assinado (30 dias). A ficha do visitante guarda perfil, primeira/última
   página e contexto do browser.
2. Ao iniciar a conversa, `POST /support/sessions` cria (ou retoma, durante
   12 h) a sessão: estado `waiting`, perfil, página, referrer, idioma, fuso,
   ecrã, IP e histórico de páginas.
3. O widget liga-se a `/support/ws?role=visitor&token=…&session_id=…`.
4. Os operadores ligam-se a `/support/ws?role=operator&token=…` (token da
   sessão de administração). Cada evento atualiza a fila, a transcrição e o
   dossiê em tempo real.
5. Um operador assume a conversa, responde (ou escreve uma nota interna) e pode
   abrir tickets. O visitante vê a resposta no widget e pode abrir os seus
   próprios tickets.
6. No fecho, o visitante pode avaliar de 1 a 5. Tudo fica registado em
   `finance_support_events`.

Se o WebSocket falhar, o widget continua a funcionar por REST e volta a tentar
o socket com recuo exponencial; a consola do operador faz o mesmo.

## Dados (Elasticsearch)

| Índice | Conteúdo |
| --- | --- |
| `finance_support_visitors` | ficha acumulada do visitante (perfil, páginas, nº de conversas) |
| `finance_support_sessions` | conversa: estado, operador, não lidos, contexto, páginas, avaliação |
| `finance_support_messages` | mensagens (`visitor`, `operator`, `system` e notas `note`) |
| `finance_support_tickets` | tickets: assunto, descrição, estado, prioridade, categoria e notas |
| `finance_support_form_responses` | respostas aos formulários enviados pelo operador (valores, autor, data) |
| `finance_support_events` | registo de auditoria (aberta, assumida, mensagem, ticket, formulário, fecho, avaliação) |
| `finance_support_operators` | presença dos operadores (online/ausente/offline) |

As *mappings* vivem em `api/es/support_mappings.py`; o serviço garante apenas
estes seis índices no primeiro pedido (`ensure_support_indices`), sem esperar
pela verificação de todos os índices da plataforma.

## API

### Público (`/support`)

| Método | Caminho | Descrição |
| --- | --- | --- |
| `GET` | `/support/config` | título, saudação, respostas rápidas, categorias, disponibilidade |
| `GET` | `/support/widget.js` | JavaScript do widget |
| `POST` | `/support/visitors` | token de visitante + atualização do perfil/contexto |
| `POST` | `/support/sessions` | abre/retoma a conversa |
| `GET` | `/support/sessions/{id}` | sessão + mensagens + tickets |
| `POST` | `/support/sessions/{id}/messages` | mensagem do visitante (fallback REST) |
| `POST` | `/support/sessions/{id}/context` | página atual (navegação interna) |
| `POST` | `/support/sessions/{id}/ticket` | abre ticket |
| `POST` | `/support/sessions/{id}/forms/{message_id}` | resposta do visitante a um formulário |
| `POST` | `/support/sessions/{id}/rate` | avaliação 1–5 |
| `POST` | `/support/sessions/{id}/close` | fecha a conversa |

O token de visitante vai no cabeçalho `X-Support-Token`. Se houver sessão da
plataforma (`Authorization: Bearer …`), a ficha do visitante é enriquecida com
nome, email, organização, papel, estado da conta e plano.

### Operador (`/admin/support`, só `admin`)

`GET /overview`, `GET /sessions`, `GET /sessions/{id}`, `POST
/sessions/{id}/claim|release|close|read|messages|ticket`, `PATCH
/tickets/{id}`, `GET /tickets`, `GET /events`, `GET /operators`, `POST
/operators/me` (online/ausente), `GET /reports` (relatórios publicados que
podem ser enviados) e `GET /forms` (modelos de formulário e tipos de campo).

### Cartões ricos e formulários

O operador pode enviar, além de texto:

- **link** — título, endereço (http/https ou caminho interno) e descrição;
- **relatório** — escolhido da biblioteca pública (`/site/documento/…` para
  documentos gratuitos publicados ou `/reports` para o catálogo); guarda
  `report_id`, título, resumo, área e se é gratuito;
- **formulário** — modelo pronto (Contacto, Empresa, Faturação) ou campos
  personalizados (texto, email, telefone, área de texto, seleção, número e
  data), com campos obrigatórios.

As respostas dos formulários ficam em `finance_support_form_responses` e a
própria mensagem do formulário é marcada com `form_response` (valores e data),
pelo que o histórico nunca perde o que o visitante respondeu. Tudo — conversas,
cartões, respostas, tickets e registos — fica no Elasticsearch.

### WebSocket (`/support/ws`)

Eventos enviados pelo servidor: `ready`, `message.created`, `session.updated`,
`session.closed`, `operator.joined`, `ticket.created`, `typing`, `presence`,
`error`, `pong`.

Eventos aceites: `message`, `typing`, `context`, `read`, `close` (visitante);
`message`, `typing`, `read`, `claim`, `release`, `close`, `status`, `ping`
(operador).

O *hub* é em memória do processo. O backend corre com **um** worker
(`uvicorn --workers 1`); com mais processos seria necessário um pub/sub externo.

## Operação

- **Assumir**: qualquer operador pode assumir uma conversa em espera; a partir
  daí as respostas ficam associadas a si. O botão **Libertar** devolve-a à fila.
- **Nota interna**: mensagem visível só no backoffice, guardada com
  `author_type = note`.
- **Tickets**: podem ser abertos pelo visitante no widget ou pelo operador, e
  geridos no separador **Tickets** do dossiê.
- **Contexto**: página atual (com link), título, referrer, IP, dispositivo,
  ecrã, idioma, fuso, UTM, browser e histórico de páginas; se o visitante tiver
  sessão na plataforma, também os dados da conta.
- **Disponibilidade**: calculada pelos operadores ligados em tempo real; fora
  do horário (dias úteis, 9h–19h, hora local) mostra a mensagem de ausência.

## Deploy

- **nginx**: o `location /api/` tem de encaminhar o handshake WebSocket
  (`proxy_set_header Upgrade`, `Connection $api_connection_upgrade`). Está em
  `docker/nginx.conf` (mapa `$api_connection_upgrade`, que mantém o keep-alive
  nos pedidos normais e SSE).
- **Vite**: o proxy `/api` tem `ws: true` (desenvolvimento/preview).
- **Docker**: `api/support_widget.js` viaja com a pasta `api/`; o frontend é
  reconstruído a partir de `chat-ui/`.

## Segurança e privacidade

- O token de visitante é assinado com o segredo de autenticação da plataforma;
  não dá acesso a mais nada.
- Cada endpoint público valida que a conversa pertence ao visitante do token.
- Os endpoints de operador exigem papel `admin` (REST e WebSocket).
- Limites de taxa por IP/visitante (bootstrap, criação de conversas e
  mensagens) e limites de tamanho de texto.
- Não há geolocalização por IP nem envio de dados para terceiros: guarda-se o
  que o browser fornece (página, idioma, fuso, ecrã, user-agent) e o IP do
  pedido.
- As mensagens são sempre escritas com `textContent` (widget) ou pelo React
  (consola), pelo que não há injeção de HTML.

## Limitações conhecidas

- Anexos de ficheiros ainda não estão implementados (o Tawk.to permitia). Os
  relatórios são enviados como cartão com ligação pública, não como PDF anexado.
- Os formulários são definidos no envio (modelo ou campos personalizados); não
  há ainda uma biblioteca de formulários reutilizáveis gravada à parte.
- A presença (online/ausente) vive no processo; reiniciar o backend marca todos
  como offline até reconectarem.
- Notificações fora da aplicação (email/push) não estão incluídas; os eventos
  ficam disponíveis em `finance_events` e na consola.

## Testes

- `tests/test_support_publico.py` — snippet no site/loja, widget na SPA, aba de
  suporte e ausência de resíduos do Tawk.to.
- `tests/test_support_chat.py` — ciclo completo de conversa (mensagens, notas,
  links, relatórios, formulários e respostas, tickets, avaliação, fecho),
  WebSocket do visitante e configuração.
