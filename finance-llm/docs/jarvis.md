# Jarvis — o assistente operacional com voz

O **Jarvis** é o assistente do IQ OS que **fala e ouve**. Em vez de ir buscar os
dados diretamente, fala com o sistema por **gateways** — e é isso que o torna
diferente dos outros assistentes da plataforma: o que ele pode fazer é
exatamente a soma do que os gateways expõem, e cada gateway pode ser testado
(ou substituído) à parte.

| Gateway | O que dá | Como |
| --- | --- | --- |
| **Hermes** | Investigação citada sobre os dados da plataforma | `hermes_service.ask()` |
| **MCP do sistema** | As operações curadas do IQ OS (contratos, empresas, mercado, RAG, ontologia, CRM, …) | `mcp_server.catalog` |
| **Browser** | Pesquisa e leitura de páginas externas | DuckDuckGo + `httpx`/`BeautifulSoup` |

Além disso, o Jarvis segue a **mesma biblioteca de skills** do Hermes, do Chat
IA e do RAG: antes de responder, escolhe (ou cria) o método do pedido.

E não se limita a responder: **propõe ações** — abrir a página certa, ou gravar
um documento, um dossiê ou uma skill **em nome do utilizador**. As de escrita só
correm depois de confirmadas, por clique ou por voz («sim»).

```
pergunta → skill → plano → gateways → resposta + ações propostas → fala
```

Há **duas formas** de o usar, com a mesma conversa:

- a **página** `/jarvis` — a experiência completa (órbita grande, painel de
  gateways, histórico longo);
- o **widget flutuante** — um botão só com o ícone, em qualquer página da
  plataforma, que abre o **Control Center**.

---

## 1. O widget (Control Center)

O widget acompanha toda a plataforma: um botão flutuante no canto inferior
direito com a órbita do Jarvis. **Só o ícone** quando fechado; ao clicar abre um
painel de Control Center com três andares:

1. **Estado do sistema** (colapsável) — o que o Jarvis tem para trabalhar
   *agora*: modelo em uso, número de ferramentas, quantas expõe cada gateway
   (Hermes / MCP / browser) e o estado da voz (`microfone + fala`, `microfone
   (servidor)` ou `só texto`). Vem do `/jarvis/meta`, por isso nunca mente.
2. **Conversa** — quando está vazia, mostra quatro atalhos que traduzem os
   pedidos mais comuns em perguntas reais:
   *Maiores contratos*, *Ficha de empresa*, *Notícias de mercado* e
   *Estado do sistema*. Depois, os turnos com o rasto dos passos, as fontes
   citadas e as sugestões seguintes. Por baixo de cada resposta com ações surge
   **«O Jarvis pode fazer isto por si»**: chips azuis para navegar, violetas
   (com o selo `escreve`) para criar. Um clique executa; para as de escrita, a
   interface sugere «diga *sim* ou *confirmar*».
3. **Compositor** — microfone e caixa de texto, com `Enter` a enviar.

Detalhes de comportamento:

- o botão **arrasta-se** e a posição fica guardada; o ícone pulsa quando o
  Jarvis está a ouvir, a pensar ou a falar, e traz um contador de respostas;
- **voz sempre disponível**: o microfone está no compositor e as respostas são
  lidas em voz alta (o altifalante no cabeçalho liga/desliga), com as mesmas
  preferências da página;
- `Esc` fecha o painel — exceto enquanto o Jarvis está a responder;
- **na página `/jarvis` o widget esconde-se**, porque aí já está a conversa
  toda; o cabeçalho do widget tem um atalho para lá;
- o **histórico é o mesmo** da página: os dois sincronizam-se por um `storage`
  event e por uma publicação interna (`subscribeJarvisHistory`), pelo que abrir
  o widget a meio de um trabalho na página mostra a mesma conversa;
- ao **navegar por uma ação**, o widget fecha-se para se ver o destino; o botão
  volta a aparecer com o contador atualizado.

O código vive em `chat-ui/src/components/jarvis/`:

| Ficheiro | Papel |
| --- | --- |
| `JarvisWidget.tsx` | o botão flutuante e o painel do Control Center |
| `JarvisChat.tsx` | o núcleo partilhado: `useJarvisChat` (streaming), `JarvisThread`, `JarvisComposer`, `Markdownish`, `TraceBlock`, `TurnCard` |
| `JarvisOrb.tsx` | a órbita (canvas, sem dependências) |
| `useJarvisVoice.ts` | ouvir e falar |

A página e o widget são só molduras diferentes à volta do mesmo núcleo — daí se
comportarem exatamente igual.

---

## 2. A página `/jarvis`


Abre-se pelo dock/menu em **Investigação e IA → Jarvis**, ou no endereço
`/jarvis`.

A órbita no centro **é** o estado do Jarvis:

| Estado | Órbita | Quando |
| --- | --- | --- |
| `idle` | respira devagar, azul | à espera |
| `listening` | pulsa com o microfone, âmbar | está a ouvir |
| `thinking` | arcos a orbitar depressa, violeta | a falar com os gateways |
| `speaking` | anéis a expandir-se com a voz, verde-água | a responder em voz alta |

Enquanto o Jarvis trabalha, a resposta é construída **em direto**: aparecem os
passos (skill escolhida, plano, ferramenta a correr, resultado) e não um simples
indicador de espera. No fim ficam a resposta, as **fontes** (Hermes, MCP, web),
as perguntas seguintes sugeridas e o botão **Ouvir**.

### Voz

Três formas de interagir, por ordem de preferência — todas degradam sem partir:

1. **Ouvir (STT).** No Chrome/Edge usa a *Web Speech API* (`SpeechRecognition`):
   transcreve enquanto se fala, sem enviar áudio para o servidor. Nos restantes
   browsers grava com `MediaRecorder` e transcreve em `/jarvis/transcribe`
   (*faster-whisper*). Se nenhum estiver disponível, o microfone fica desativado
   e a página continua a funcionar por texto.
2. **Falar (TTS).** Por omissão usa as vozes do sistema (`speechSynthesis`) —
   instantâneo. Com **Voz do servidor** ligado (e `edge-tts` instalado), a
   resposta vem de `/jarvis/speak` com vozes neurais `pt-PT`.
3. **Painel de controlo**: profundidade da investigação (`rapida`/`profunda`,
   passada ao gateway do Hermes), «Falar» (ler as respostas), escolha da voz e a
   lista de ferramentas disponíveis.

---

## 3. Rotas

Todas em `api/jarvis_routes.py`. A sessão é opcional: sem ela o Jarvis responde,
mas só com dados públicos (os dados de CRM ficam de fora).

| Rota | Para que serve |
| --- | --- |
| `GET /jarvis/meta` | capacidades, gateways, ferramentas, vozes e modelo disponível |
| `GET /jarvis/tools` | catálogo das ferramentas (`?gateway=hermes\|mcp\|web`) |
| `GET /jarvis/actions` | catálogo das **ações** (destinos + criações) |
| `POST /jarvis/actions/run` | executa uma criação em nome do utilizador |
| `GET /jarvis/voice` | estado da voz (STT/TTS) e vozes disponíveis |
| `POST /jarvis/ask` | pergunta → resposta + plano + passos + citações |
| `POST /jarvis/ask/stream` | o mesmo, em SSE |
| `POST /jarvis/transcribe` | áudio (multipart) → texto |
| `POST /jarvis/speak` | texto → áudio (mp3) |

`POST /jarvis/ask` aceita:

```json
{
  "question": "Quais são os maiores contratos públicos de energia em 2025?",
  "depth": "rapida",
  "backend": "openai:gpt-4o-mini",
  "history": [{ "role": "user", "content": "…" }],
  "voice": "pt-PT-RaquelNeural",
  "speak": false
}
```

`speak: true` acrescenta o áudio em base64 na resposta (quando há motor no
servidor); sem motor, vem `audio: null` e a interface usa a voz do sistema.

### Streaming

`POST /jarvis/ask/stream` emite SSE com sete tipos de evento:

```
event: passo      { kind, label, at, tool?, ok?, reason?, source? }
event: plano      { tools: [...], reason, source }
event: ferramenta { tool, label, state: a_correr|ok|falhou, error? }
event: skill      { skill: { id, title, steps, created } }
event: acao       { action: { id, kind, label, description, ... } }
event: resposta   { answer, speech, sources, suggestions, skill, actions, steps, tools_used }
event: fim        { elapsed_seconds }
```

### Ações: o que o Jarvis faz *por nós* (`api/jarvis_actions.py`)

O Jarvis não só responde — **propõe ações**. Cada ação chega à interface como um
chip, e a diferença entre os dois tipos é o que torna isto seguro:

| Tipo | O que é | Quem executa | Confirmação |
| --- | --- | --- | --- |
| `navigate` | levar o utilizador a um sítio (`/contracts/search`, `/office`, …), com ou sem termo de pesquisa | o **cliente**, com um clique | não precisa (não altera nada) |
| `create` | escrever um artefacto: documento no Office, dossiê 360, skill na biblioteca | o **servidor**, em `POST /jarvis/actions/run` | **obrigatória** |

Três regras que a deteção respeita, e que não são óbvias:

1. **Uma pergunta não é um pedido para navegar.** «Quais são os maiores
   contratos de energia?» só propõe abrir a página de contratos se tiver um verbo
   de navegação («abre», «mostra», «leva-me») ou se for uma frase de ≤ 3 palavras
   («insolvências»). Sem isto, qualquer pergunta com a palavra «contratos»
   arrastava o utilizador para fora da conversa.
2. **Quem pede para gravar não quer também navegar.** «Guarda isto no Office»
   propõe a criação, não a criação *mais* a abertura da página do Office.
3. **O modelo nunca escolhe uma escrita.** As operações usadas pelas criações
   (`office_save_document`, `search360_save_dossier`, `skills_save`) **não** estão
   no catálogo curado de ferramentas — de propósito. São invocadas por
   `mcp.call`, e só depois de a ação ter sido confirmada.

#### Confirmação por voz

O ciclo é fechado no cliente (`useJarvisChat`): dito «sim», «confirmar»,
«guarda»… a pergunta **não** vai ao modelo — executa a proposta mais recente por
confirmar. Só quando há exatamente uma, para não adivinhar entre duas. A chave de
cada ação é `turno::ação`, porque o mesmo id de catálogo se repete ao longo da
conversa e confirmar um pedido não pode marcar os outros como feitos.

```json
POST /jarvis/actions/run
{
  "action": "guardar_office",
  "question": "guarda no office o relatório da EDP",
  "answer": "A EDP lidera a distribuição elétrica em Portugal…",
  "params": { "title": "Relatório EDP", "folder_id": "pasta-7" }
}
```

`params` é opcional e limitado a um conjunto conhecido de campos do corpo
(`title`, `markdown`, `kind`, `tags`, `folder_id`, `template`, `term`, `notes`,
`name`, `summary`, `question`, `project_id`): o modelo pode ajustar o título ou
escolher a pasta, mas não introduzir campos arbitrários no pedido. O corpo final
é embrulhado no parâmetro que o catálogo MCP declara para o *body* (`payload`) —
sem isso, o corpo ia parar ao *query string* e o endpoint respondia 422.

Devolve `{ok, action, label, operation, result, error}`; `result` é
`{saved: true, document: {…}}` para o Office. Uma ação de navegação devolve
`422` — essas são do cliente.

### Também por MCP

O Jarvis está exposto no próprio servidor MCP do sistema (`jarvis_meta`,
`jarvis_tools`, `jarvis_voice`, `jarvis_ask`, `jarvis_speak`), pelo que outro
agente pode pedir-lhe uma resposta **com voz incluída**.

---

## 4. Como o Jarvis decide

`api/jarvis_gateway.py` publica o catálogo e resolve as ferramentas;
`api/jarvis_service.py` conduz o ciclo.

### Plano

1. **Com modelo** (`ontology_ai.available_backend` → `cloud`): o modelo recebe a
   lista de ferramentas (id, gateway, descrição) e devolve
   `{"tools": [{"tool": "...", "args": {...}}], "reason": "..."}`. Nunca pode
   inventar ferramentas: as desconhecidas são descartadas.
2. **Sem modelo**: plano por **palavras-chave**. É aqui que está o cuidado
   principal — `gateway.default_args()` só deixa entrar ferramentas para as
   quais se consegue construir um pedido válido a partir da pergunta:

   | Operação | Argumentos inferidos |
   | --- | --- |
   | `hermes.ask` | `{"question": <pergunta>}` |
   | `search_unified`, `empresas_search`, `scraper_search`, … | `{"q": <pergunta>}` |
   | `contratos_search`, `rag_chat`, `sentiment_analyze_text`, … | corpo JSON com o campo conhecido (`q`, `question`, `text`) |
   | `web.open` | o **URL** presente na pergunta (se existir) |
   | `market_history`, `contrato_detail`, `visualizador_query`, … | `None` — exigem um ticker/NIF/`dataset` que não se adivinha |

   Uma ferramenta com `default_args is None` **nunca** entra num plano sem
   modelo, o que evita 422 garantidos. O Hermes é acrescentado quando a pergunta
   é analítica (≥ 5 palavras) — é a espinha dorsal da investigação, mas é caro
   (plano + recolha federada), pelo que não se paga em consultas curtas.

Se mesmo assim faltar um parâmetro obrigatório, a chamada é marcada com `skip` e
não chega a ser feita.

### Gateway MCP

As chamadas às operações do MCP correm **dentro do processo**:
`httpx.ASGITransport` sobre a própria aplicação FastAPI, com o token da sessão
reencaminhado. Sem rede, sem login extra, sem segunda instância do backend. Se a
aplicação não for importável (arranque parcial), cai para HTTP no
`IQOS_API_URL`.

### Gateway web

- `web.search(query, max_results)` — DuckDuckGo (`ddgs`/`duckduckgo-search`);
- `web.open(url)` — `httpx` + `BeautifulSoup`: remove `script/style/nav/…`, lê
  `<main>`/`<article>`/`<body>` e devolve título + texto limpo (máx. 6 000
  caracteres);
- `web.research(query, max_pages)` — pesquisa e abre os melhores resultados,
  juntando-os numa só evidência.

### Resposta

Com modelo, as evidências dos gateways (JSON, até 9 000 caracteres por bloco)
vão no prompt e o Jarvis responde em texto simples para ser lido em voz alta.
Sem modelo, responde em **modo factual**: mostra o que as ferramentas devolveram,
sem interpretação (e, se o Hermes tiver recolhido mas não redigido, lista as
evidências que ele encontrou).

`speech_text()` prepara a versão falada: tira código, títulos, ênfase, tabelas e
réguas, converte `[1]` em «(fonte 1)» e corta a 900 caracteres no fim de uma
frase.

---

## 5. Ficheiros

| Ficheiro | Papel |
| --- | --- |
| `api/jarvis_gateway.py` | catálogo dos gateways, `default_args`, `invoke`, `pick_tools` |
| `api/jarvis_actions.py` | catálogo das ações (destinos e criações), deteção, `render`, `run` |
| `api/jarvis_service.py` | ciclo `ask`/`stream`, skills, voz (STT/TTS), metamodelo |
| `api/jarvis_routes.py` | rotas `/jarvis/*` |
| `mcp_server/catalog.py` | operações `jarvis_*` (o Jarvis também é ferramenta MCP) |
| `chat-ui/src/jarvisApi.ts` | cliente (incluindo o leitor de SSE sobre POST e a sincronização do histórico) |
| `chat-ui/src/pages/JarvisPage.tsx` | a página completa |
| `chat-ui/src/components/jarvis/JarvisWidget.tsx` | o botão flutuante e o Control Center |
| `chat-ui/src/components/jarvis/JarvisChat.tsx` | o núcleo partilhado da conversa (hook + desenho) |
| `chat-ui/src/components/jarvis/JarvisOrb.tsx` | a órbita (canvas, sem dependências) |
| `chat-ui/src/components/jarvis/useJarvisVoice.ts` | ouvir e falar |
| `tests/test_jarvis.py` | 50 testes (catálogo, argumentos, plano, voz, ciclo, streaming) |
| `tests/test_jarvis_actions.py` | 46 testes (deteção, proposta, `render`, execução, catálogo) |

---

## 6. Testar

```powershell
cd c:/LLMFinance/finance-llm
c:/LLMFinance/.venv/Scripts/python.exe -m pytest tests/test_jarvis.py tests/test_jarvis_actions.py -q
```

Verificação manual rápida (com o backend em `:8002`):

```powershell
# o que o Jarvis pode fazer
curl http://127.0.0.1:8002/jarvis/meta

# as ações que pode executar por nós
curl http://127.0.0.1:8002/jarvis/actions

# uma pergunta real
curl -X POST http://127.0.0.1:8002/jarvis/ask -H "Content-Type: application/json" `
  -d '{"question":"Quais os maiores contratos publicos de energia em 2025?","depth":"rapida"}'
```

Dicas:

- `GET /jarvis/tools` é a forma mais rápida de ver o que está publicado em cada
  gateway sem percorrer o código;
- para experimentar uma escrita sem passar pela interface, use
  `POST /jarvis/actions/run` com o token de sessão — é o mesmo caminho que o
  botão do chip usa;
- se um chip ficar em erro com `HTTP 422: body Field required`, é sinal de que o
  corpo não foi embrulhado no parâmetro do catálogo (`_mcp_params`);
- sem chave de modelo configurada o Jarvis responde em modo factual — é o
  comportamento esperado, não uma falha (o `meta.model.kind` diz qual é o caso);
- a primeira investigação do Hermes é lenta de propósito (agregações de
  contratos + índice vetorial a frio); `depth: "rapida"` é o caminho curto.

---

## 7. Voz no servidor (opcional)

```powershell
c:/LLMFinance/.venv/Scripts/pip.exe install edge-tts faster-whisper
```

Com isto, `GET /jarvis/voice` passa a reportar `available: true` nos dois
motores, a interface ganha a opção **Voz do servidor** e o microfone passa a
funcionar em browsers sem `SpeechRecognition` (Firefox). Sem estes pacotes, o
Jarvis não perde funcionalidade — muda só quem sintetiza e transcreve.
