# Correio da plataforma

Página **Correio da plataforma** (`/admin/correio`) — o gestor do correio do
domínio da solução, **só para contas com o papel `admin`**: as caixas do
domínio (a que envia o email transacional, o `postmaster@`, o `dmarc@` e as que
a administração acrescentar), a lista e a leitura das mensagens, a pesquisa
sobre o índice, as conversas e o envio com editor e anexos.

Não se confunde com a aplicação **Email** (`/email`), que é a caixa pessoal de
cada utilizador e liga contas externas (Gmail, Outlook…): aqui gere-se o correio
**do domínio da plataforma**, lido por IMAP do servidor da solução.

## O que faz

- **Caixas** — a caixa do email transacional é derivada da configuração SMTP
  (`SMTP_*`) e é só de leitura nessa parte; as restantes são ligadas aqui, com
  IMAP/SMTP, pastas a sincronizar e assinatura. A palavra-passe nunca é
  devolvida pela API (as respostas trazem apenas `has_password`).
- **Pastas** — contagens do servidor (mensagens e por ler) e quantas estão já
  arquivadas no índice.
- **Lista** — pesquisa (assunto, corpo, remetente), filtros (por ler,
  destacadas, com anexos), ordenação e paginação, tudo servido pelo
  Elasticsearch; as contagens que a barra lateral mostra vêm das agregações.
- **Leitura** — corpo em texto ou **HTML isolado num `iframe` com sandbox**
  (o HTML do correio não corre no contexto da plataforma), anexos para
  descarregar, e a **conversa** da mensagem. Ações: responder, responder a
  todos, reencaminhar, destacar, marcar lida/não lida, mover e apagar.
- **Compor** — editor de texto formatado (negrito, itálico, sublinhado, listas,
  citação, links) com alternância para **HTML**, CC/BCC, assinatura da caixa,
  anexos e encadeamento (`In-Reply-To`/`References`). A cópia enviada é
  arquivada na pasta **Sent** por `APPEND` e entra logo no índice.
- **Agenda** — de quanto em quanto tempo o correio novo é trazido (`auto_sync`,
  `sync_seconds`; **0 desliga**). A sincronização manual («Sincronizar» e
  «Reindexar tudo») funciona mesmo sem APScheduler.

## Índices

| Índice | Conteúdo |
| --- | --- |
| `finance_mail_accounts` | Caixas (`kind: account`), preferências da caixa da plataforma (sem credenciais) e o estado da sincronização (`kind: sync`, documento `sync::<caixa>`). |
| `finance_mail_messages` | Uma entrada por mensagem sincronizada: `_id = caixa::uid::pasta`. É o que serve lista, pesquisa, contagens e conversas. |

O fio da conversa (`thread_key`) é a **raiz da cadeia de `References`**; sem
cabeçalhos, cai para a própria mensagem ou para o assunto sem `Re:`/`Fwd:`
(normalizado), o que agrupa as respostas mesmo quando o cliente do outro lado
não escreve referências.

## Sincronização

Incremental por pasta, com o marcador `UID <último+1>:*` guardado em
`finance_mail_accounts`:

1. **Primeira passagem** de uma pasta: traz as `INITIAL_BATCH = 200` mensagens
   mais recentes (sincronizar anos de correio na primeira abertura demoraria
   minutos e não serve para nada).
2. **Passagens seguintes**: as `SYNC_BATCH = 60` novas, da mais antiga para a
   mais nova, para o marcador avançar sem buracos.
3. **`full=true`** («Reindexar tudo»): relê a pasta desde o início até ao teto
   `FULL_SYNC_CAP = 2000` e, no fim, tira do índice o que já não existe na
   pasta.

Uma passagem só corre de cada vez (tranca própria): pedir outra devolve `409`.
Mensagens acima de `MAX_MESSAGE_BYTES = 20 MB` são ignoradas com uma linha no
log — não podem parar a sincronização nem inchar o índice.

## Backend

`api/platform_mail_routes.py` (prefixo `/admin/mail`, dependência `require_admin`):

| Rota | Descrição |
| --- | --- |
| `GET /admin/mail/meta` | Servidores por omissão, pastas a sincronizar, limites e estado do índice. |
| `GET /admin/mail/stats` | Panorama: totais, por pasta, por ler, destaques, remetentes, série diária e estado por caixa. |
| `GET /admin/mail/settings` | Agenda da sincronização automática. |
| `PUT /admin/mail/settings` | Altera essa agenda (`sync_seconds`, `auto_sync`) e recarrega o agendador sem reiniciar a API. |
| `GET /admin/mail/accounts` | Caixas (sem segredos, com `has_password`). |
| `POST /admin/mail/accounts` | Cria/altere uma caixa (servidores herdados da plataforma quando omitidos). |
| `POST /admin/mail/accounts/test` | Testa IMAP e SMTP sem guardar. |
| `DELETE /admin/mail/accounts/{id}` | Remove uma caixa (a da plataforma é derivada do SMTP e não se apaga). |
| `GET /admin/mail/accounts/{id}/folders` | Pastas, contagens do servidor e o que está indexado. |
| `POST /admin/mail/sync` | Sincroniza uma caixa (ou todas) — `{ "full": true }` relê tudo. |
| `GET /admin/mail/messages` | Lista/pesquisa: `account`, `folder`, `q`, `sender`, `thread`, `direction`, `unseen`, `flagged`, `attachments`, `date_from`, `date_to`, `sort`, `limit`, `offset`. |
| `GET /admin/mail/messages/{id}` | Mensagem completa (corpo, HTML e anexos) lida do IMAP. |
| `GET /admin/mail/messages/{id}/attachments/{index}` | Descarrega um anexo. |
| `POST /admin/mail/messages/{id}/flags` | `read`, `unread`, `flag`, `unflag`. |
| `POST /admin/mail/messages/{id}/move` | Move para outra pasta (reindexa no destino pelo `Message-ID`). |
| `DELETE /admin/mail/messages/{id}` | Apaga na caixa e no índice. |
| `POST /admin/mail/send` | Envia (texto e/ou HTML, anexos, encadeamento) e arquiva em *Sent*. |

O identificador de uma mensagem é `caixa::uid::pasta` — as rotas usam o
conversor `path` porque as pastas podem ter `/` (a rota do anexo é registada
**antes** da que abre a mensagem, para o `path` não a engolir).

Todas as ações ficam registadas como **eventos de auditoria** (`source: admin`,
`data.module = "mail"`): mexer no correio da plataforma é operação sensível.

### Serviço

`api/platform_mail_service.py` reutiliza a camada IMAP/SMTP do webmail
(`api/email_service.py`: ligação, descodificação, sinalizadores, envio), pelo
que não há duas implementações de correio no projeto.

**Sem Elasticsearch a aplicação não pára**: a lista cai para o IMAP de uma caixa
escolhida (mais lenta, sem pesquisa global nem contagens), a leitura usa a cópia
arquivada quando o servidor não responde (`stale: true`) e o envio continua a
funcionar. Cada resposta diz de onde veio (`source: elasticsearch | imap`).

## Configuração

A caixa do email transacional precisa apenas do SMTP já configurado
(`SMTP_HOST`/`SMTP_USER`/`SMTP_PASSWORD`): o IMAP assume o **mesmo servidor**, na
porta `993` com `ssl` — é a mesma máquina, o Docker Mailserver serve SMTP e IMAP.
Para apontar para outro servidor, há três chaves em
**Administração → Chaves e integrações** (ou as variáveis `MAIL_IMAP_*`):

| Chave | Variáveis | Padrão |
| --- | --- | --- |
| `mail_imap_host` | `MAIL_IMAP_HOST`, `PLATFORM_MAIL_IMAP_HOST` | o mesmo do SMTP |
| `mail_imap_port` | `MAIL_IMAP_PORT`, `PLATFORM_MAIL_IMAP_PORT` | `993` |
| `mail_imap_security` | `MAIL_IMAP_SECURITY`, `PLATFORM_MAIL_IMAP_SECURITY` | `ssl` |

Duas variáveis de ambiente controlam a agenda por omissão (a interface pode
sobrepor-se-lhes): `PLATFORM_MAIL_SYNC_SECONDS` (padrão `300`) e
`PLATFORM_MAIL_AUTO_SYNC` (padrão ligada).

Novas caixas criam-se no servidor de correio — `deploy/kamatera` →
`14-servico-vm.ps1 -Nome mailserver` — e depois ligam-se na aplicação
(botão de engrenagem → «Ligar nova caixa»).

## Frontend

- `src/pages/PlatformMailPage.tsx` — a página: três colunas (caixas e pastas,
  lista, leitura), janela de composição com o editor e janela de caixas/agenda.
- `src/platformMailApi.ts` — cliente das rotas.
- Registo: entrada `admin-mail` no `DOCK_CATALOG` (`src/dock.ts`), nas
  ferramentas (`TOOL_APP_IDS`) e em `RESERVED_MODULES`
  (`src/sidebarCatalog.ts`), `adminOnly` no `src/components/AppNav.tsx` e as
  rotas de `App.tsx` (`/admin/correio`, vista `admin-mail`).

## Armadilhas

- **Portas do correio**: 25, 993 e 587 estão publicadas na VM (leitura e envio
  autenticados, para o stack do PC e para clientes de correio; a 465 fica no
  loopback). O backend continua a usar o FQDN (`mail.sabemos.studio`) na
  `iqos-net` — não depende das publicações. Sem as regras de firewall para a 993
  e a 587, só a rede da VM alcança o correio.
- **`mynetworks` vazio no DMS**: não há relay interno; o envio é sempre
  autenticado com a conta da caixa.
- **A caixa da plataforma não guarda credenciais**: se o SMTP mudar, o IMAP
  acompanha sem tocar no índice.
- **Anexos vêm do IMAP**: o índice guarda só nome, tipo e tamanho (o HTML do
  corpo é guardado mas não indexado — procurar dentro de marcação só traz
  ruído).
