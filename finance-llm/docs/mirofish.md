# MiroFish — simulações de previsão com os dados do sistema

O [MiroFish](https://github.com/666ghj/MiroFish) é um motor de **previsão por
enxame de agentes**: recebe material-semente (relatórios, notícias, fichas) e um
pedido de previsão em linguagem natural, constrói um grafo de conhecimento
(Zep), gera *personas*, corre a simulação em duas plataformas paralelas
(OASIS) e escreve um relatório com um agente próprio.

O módulo `/mirofish/*` liga essa máquina aos **dados do IQ OS**: em vez de
carregar ficheiros à mão, escolhe-se uma fonte de dados da plataforma — a
plataforma compõe o documento-semente e conduz a simulação.

## Como usar (plataforma)

1. `docker compose --profile mirofish up -d` (perfil `mirofish` do compose) e as
   chaves no `.env` (ver *Chaves* abaixo).
2. Abrir a página **Simulador IQ OS** (dock → *Simulador IQ OS*, rota
   `/simulador`) — é a interface nativa: lança simulações com os dados do
   sistema e **apresenta os resultados**.
3. Escolher a **fonte de dados**, confirmar/ajustar o **pedido de previsão** e
   premir **Simular com estes dados**.
4. Acompanhar o progresso na aba *Nova simulação* (progresso + registo) e, no
   fim, ver os resultados: **Resumo** (rondas, ações, plataformas, ontologia),
   **Ações** (o que cada agente publicou/comentou), **Elenco** (personas, quem
   representam, quantas ações fizeram) e **Relatório** (escrito pelo MiroFish,
   com conversa sobre o grafo).
5. A aba **Estúdio MiroFish** (e a página iframe «Simulador IQ OS · Estúdio»,
   `http://<host>:8893`) abre a app do MiroFish **completa** — é a mesma máquina,
   para quem quiser conduzir tudo à mão.

O motor continua disponível sem a integração: qualquer dado pode ser carregado
à mão no estúdio do MiroFish (aba *Estúdio MiroFish* ou página iframe).

## Fontes de dados (`GET /mirofish/meta`)

| Fonte | O que recolhe | Fonte de verdade |
|-------|---------------|------------------|
| `empresa` | Ficha da empresa: contratos, sinais, cargos sociais, insolvências, notícias | `padroes_service.entity_dossier` (Portal BASE, CIRE, registo societário) |
| `tema` | Dossiê de um tema com evidências citadas e indicadores | Pesquisa 360 (`search360_service.topic` + `search360_store.dossier_markdown`) |
| `noticias` | Digest das notícias seguidas na plataforma | Leitor RSS (`rss_store.all_articles` + `digest_markdown`) |
| `documento` | Um documento já guardado no Office | `office_store.get_document`/`export_document` |
| `sistema` | Panorama global: volumetria dos índices, contratação pública por ano, maiores contratos, insolvências recentes, éditos por comarca | Elasticsearch (`contratos`, `finance_cire`, `finance_citacoes_edital`, …) |

Cada fonte devolve um **Markdown** (o documento-semente), o **pedido de
previsão sugerido** e um resumo (`stats`) — `POST /mirofish/seed`.

## Endpoints

| Método | Rota | Para que serve |
|--------|------|----------------|
| `GET` | `/mirofish/meta` | Estado do serviço, catálogo de fontes e valores por omissão |
| `GET` | `/mirofish/status` | Serviço + projetos/simulações já existentes no MiroFish |
| `POST` | `/mirofish/seed` | Compõe a semente (pré-visualização, sem simular) |
| `POST` | `/mirofish/seed/office` | Guarda a semente como documento do Office |
| `POST` | `/mirofish/simulations` | Arranca a simulação (trabalho em segundo plano) |
| `GET` | `/mirofish/settings` | Estado das chaves (fornecedores com chave, `.env`, comandos) |
| `PUT` | `/mirofish/settings` | Guarda as chaves e, a pedido, escreve o `.env` e recria o contentor |
| `POST` | `/mirofish/settings/apply` | Escreve as chaves no `.env` e recria o contentor do MiroFish |
| `GET` | `/mirofish/diagnose` | Serviço, chaves esperadas, comandos e último erro traduzido |
| `GET` | `/mirofish/jobs` | Trabalhos recentes |
| `GET` | `/mirofish/jobs/{job_id}` | Progresso e registo de um trabalho |
| `GET` | `/mirofish/runs` | Catálogo de simulações (estado ao vivo das mais recentes) |
| `GET` | `/mirofish/runs/{sim}` | Retrato de uma execução: rondas, ações, elenco, ontologia e relatório |
| `GET` | `/mirofish/runs/{sim}/actions` | Feed de ações (filtros `platform`, `agent_id`, `round_num`, paginação) |
| `GET` | `/mirofish/runs/{sim}/agents` | Elenco: personas + configuração + ações de cada agente |
| `GET` | `/mirofish/runs/{sim}/graph` | Grafo de conhecimento (Zep): nós por tipo de entidade, factos e relações (`nodes`, `edges` para limitar o desenho) |
| `POST` | `/mirofish/runs/{sim}/stop` | Interrompe a execução |
| `POST` | `/mirofish/runs/{sim}/interview` | Entrevista um agente (ou todos) sobre o futuro |
| `GET` | `/mirofish/runs/{sim}/report` | Estado do relatório (sem o gerar) |
| `POST` | `/mirofish/runs/{sim}/report` | Pede o relatório ao MiroFish (`{"force": true}` regenera) |
| `POST` | `/mirofish/runs/{sim}/report/chat` | Conversa com o agente de relatório (responde a partir do grafo) |

Todas exigem sessão: a semente contém dados de negócio (contratos, pessoas,
insolvências) e a simulação consome créditos do LLM/Zep configurados no MiroFish.

## O que acontece ao premir «Simular»

`api/mirofish_service.run_simulation` encadeia a API do MiroFish:

1. **Semente** — recolha dos dados e composição do Markdown.
2. **Projeto + ontologia** — `POST /api/graph/ontology/generate` (multipart com o
   Markdown + o pedido de previsão). O LLM propõe os tipos de entidade/relação.
3. **Grafo** — `POST /api/graph/build` e consulta de progresso em
   `/api/graph/task/{task_id}` (o Zep extrai entidades, relações e memória temporal).
4. **Simulação** — `POST /api/simulation/create` + `/api/simulation/prepare`
   (personas e configuração do mundo; é o passo mais caro em LLM).
5. **Execução** — `POST /api/simulation/start` (`max_rounds`, `platform`).
6. **Relatório** (opcional) — `POST /api/report/generate` e espera do estado.

Os passos são configuráveis por pedido (`steps: {graph, prepare, run, report}`),
para se poder parar depois do grafo ou só preparar o ambiente.

Cada passo é registado no *job* (`log`, `step`, `progress`), que o frontend
consulta a cada 4 s. Falhas devolvem a mensagem do MiroFish tal e qual (por
exemplo, um 401 do fornecedor de LLM) — sem simular nada por cima.

## Chaves e variáveis de ambiente

| Variável | Onde | Para que serve |
|----------|------|----------------|
| `MIROFISH_URL` | backend IQ OS | Endereço da API do MiroFish visto de dentro do container (`http://mirofish:5001` no compose; `http://127.0.0.1:5001` fora do Docker) |
| `MIROFISH_PUBLIC_URL` | backend IQ OS | Endereço público da UI para os links do frontend (vazio = host do browser + `8893`) |
| `MIROFISH_LLM_API_KEY` / `_BASE_URL` / `_MODEL_NAME` | `.env` do projeto | LLM do MiroFish — **gerida pela página** (ver abaixo) |
| `MIROFISH_ZEP_API_KEY` | `.env` do projeto | Zep Cloud — grafo de conhecimento e memória dos agentes — **gerida pela página** |
| `MIROFISH_LLM_BOOST_*` | `.env` do projeto | Previsões/gerações de volume num segundo modelo (opcional) |
| `MIROFISH_MAX_ROUNDS` | `.env` do projeto | Rondas de simulação por omissão (`OASIS_DEFAULT_MAX_ROUNDS`) |
| `MIROFISH_REPLY_LANGUAGE` | `.env` do projeto | Idioma das respostas do LLM — **prompts do upstream são em chinês**, portanto sem isto as personas e as publicações saem em chinês (`pt-PT` por omissão; vazio = desligado) |
| `MIROFISH_HTTP_TIMEOUT`, `MIROFISH_STEP_TIMEOUT`, `MIROFISH_POLL_INTERVAL` | backend IQ OS | Tempos limite da condução da simulação |

### Idioma (português)

A tradução do MiroFish tem três camadas, porque só traduzir a interface não chegava:

1. **Interface** — `locales/pt.json` (635 chaves) substitui o `zh.json` por omissão no
   vue-i18n e nas mensagens da API (`Accept-Language: pt`).
2. **Textos gerados pelo LLM** — os *prompts* do upstream estão em chinês e o modelo
   respondia no idioma do prompt: personas, justificações e publicações saíam em chinês.
   A imagem instala uma **diretiva de idioma** no único ponto por onde passam todos os
   pedidos (`LLMClient._create_completion`), em português **e** em chinês, a pedir que
   não se mexam em nomes de campos JSON nem em valores de enumeração (senão o
   `chat_json` deixa de validar). Fica ativa por `MIROFISH_REPLY_LANGUAGE`
   (`pt-PT` por omissão no compose) — `docker/mirofish/pt_language.py`.
3. **Mensagens do backend** — progresso e erros construídos em código
   («已完成 4/32: …», «模拟不存在: sim_x») são substituídos por português na build:
   `docker/mirofish/pt_backend_strings.py`.

As simulações criadas **antes** desta alteração mantêm os textos em chinês (o que está
no Zep e nos ficheiros da simulação não é reescrito) — para as ver em português, corra uma
nova simulação.

### Chaves pela página (LLM do sistema + Zep)

O contentor do MiroFish lê as chaves do **ambiente** (`.env` do projeto via compose),
portanto não se mudam a quente. A secção **«Chaves do motor»** da página MiroFish resolve isso:

1. **LLM a partir do sistema** — escolhe-se um fornecedor já configurado na plataforma
   (OpenAI, DeepSeek, xAI, Groq, Mistral, OpenRouter, Ollama…), a chave é resolvida em
   `providers_service.resolve_key()` (chave do utilizador ou variável de ambiente) e escrita como
   `MIROFISH_LLM_API_KEY` + `_BASE_URL` + `_MODEL_NAME`. Também aceita uma chave personalizada.
2. **Zep** — campo próprio (guardado nas definições da plataforma, `finance_settings`, id
   `mirofish`) e atualizável a qualquer momento.
3. **«Guardar e recriar o serviço»** — escreve o `.env` (só as chaves geridas, preservando o resto
   do ficheiro) e corre `docker compose --profile mirofish up -d --force-recreate mirofish`.

As chaves **nunca** são devolvidas pela API: as respostas trazem apenas máscaras (`sk-…4f2a`).
O `.env` está no `.gitignore`.

⚠️ **Sem `MIROFISH_LLM_API_KEY` e `MIROFISH_ZEP_API_KEY` o MiroFish não arranca**
(`run.py` valida a configuração e sai com código 1 — a lista do que falta sai no log do
contentor). É por isso que o serviço vive num perfil do compose: um `docker compose up` do
núcleo nunca fica num ciclo de reinícios por falta de chaves.

## Diagnóstico (chaves em falta)

Como a falha típica não é óbvia — o MiroFish devolve o erro do fornecedor tal e qual, por
exemplo `HTTP 502 — LLM provider request failed (HTTP 401)` — a plataforma traduz o erro na
causa e diz **que chave** falta:

- `GET /mirofish/diagnose` — serviço, chaves esperadas (nome, alternativa, papel, onde se
definem), comandos (`start`, `recreate`, `logs`, `health`), o que a plataforma vê no seu
próprio ambiente (`OPENAI_*`) e o último erro de simulação já traduzido.
- A tradução vive em `mirofish_service.explain_error()`: um 401/403 do fornecedor vira
  «a chave do LLM (ou do Zep Cloud) está em falta ou é inválida», com o comando para recriar
  o contentor. Jobs falhados guardam o campo `hint` com essa instrução (a página mostra-o).
- Verificação direta, dentro da imagem (mostra exatamente o que falta):

```bash
docker compose --profile mirofish logs mirofish      # o arranque imprime as chaves em falta
docker run --rm -e LLM_API_KEY= -e ZEP_API_KEY= -w /app/backend iq-os-mirofish:latest \
  uv run python -c "from app.config import Config; print(Config.validate())"
```

Se o contentor `mirofish` não estiver a correr, o proxy de incorporação (`:8893`) não devolve
um `502` cru: serve uma página que explica o que falta (e a API responde em JSON com a mesma
informação). A página **Simulador IQ OS** (e a página **MiroFish**, dedicada às chaves e aos
trabalhos) mostra o mesmo diagnóstico.

## Simulador IQ OS (resultados)

A página `/simulador` (`chat-ui/src/pages/SimuladorPage.tsx`) é a interface nativa de
simulação e de leitura dos resultados. Cinco abas:

| Aba | O que mostra / faz |
|-----|--------------------|
| **Resumo** | Estado, progresso por ronda, plataformas (twitter/reddit), tipos de entidade do grafo e ontologia (entidades/relações) do projeto |
| **Grafo** | Grafo de conhecimento do Zep igual ao do MiroFish: rede de forças com nós coloridos por tipo de entidade (formas diferentes por tipo), zoom/arrastar, filtros por tipo, pesquisa, layouts rede/hierarquia/circular, factos na dica e painel do nó escolhido (resumo, atributos, etiquetas, uuid e todos os factos que o ligam ao resto) |
| **Ações** | Feed do que os agentes publicaram e comentaram, com filtros por plataforma/agente e paginação |
| **Elenco** | Personas: nome, tipo de entidade, influência, horários ativos, bio/persona e ações de cada agente, com entrevista («o que esperas que aconteça?») |
| **Relatório** | Escreve/lê o relatório do MiroFish (Markdown + secções), descarrega-o e permite conversar com o agente de relatório |
| **Nova simulação** | Fonte de dados do sistema, pedido, plataforma, rondas, passos e pré-visualização da semente |

Há ainda a aba **Estúdio MiroFish**, que incorpora a app completa (`:8893`) — a interface
«igual ao Miro», para conduzir o motor à mão.

Notas de funcionamento:

- O **relatório só pode ser pedido depois de a simulação terminar** (concluída ou
  interrompida): o MiroFish recusa com `409` enquanto houver execução ou ingestão no grafo
  ativa. A página traduz essa recusa e sugere esperar ou parar; o botão *Parar execução*
  liberta o relatório com o que já foi simulado.
- O **grafo** só é pedido quando a aba é aberta (é a leitura mais pesada: inclui os resumos de
  todos os nós) e, em projetos grandes, desenha os nós **mais ligados** — o que ficou de fora
  é indicado por baixo do desenho.
- **Entrevistas** exigem o ambiente em execução (o MiroFish responde «ambiente não está em
  execução» quando o processo já terminou).
- A página só procura as simulações mais recentes em detalhe (parâmetro `enrich`) para não
  multiplicar pedidos ao motor.

## Custo e dimensão das simulações

Cada ronda chama o LLM para **cada** agente e cada persona é gerada com LLM.
Comece com poucas rondas (`max_rounds` 5–10) e com materiais-semente pequenos:
o panorama do sistema tem ~5 000 caracteres; uma ficha de empresa grande pode
chegar a dezenas de milhares. O relatório final volta a consumir o LLM.

O MiroFish só aparece no perfil `mirofish` e não faz parte do arranque normal —
é uma ferramenta de análise, não um serviço de sempre.

## Implementação

- `api/mirofish_service.py` — recolha de dados, composição das sementes,
  cliente da API do MiroFish e condução da simulação (trabalhos em *threads*),
  mais a leitura dos resultados (estado, ações, elenco, relatório, entrevistas).
- `api/mirofish_settings.py` — chaves: resolução do LLM a partir dos fornecedores da plataforma,
  escrita do `.env` e recriação do contentor.
- `api/mirofish_routes.py` — rotas `/mirofish/*` (sessão obrigatória), incluindo `/mirofish/runs/*`.
- `chat-ui/src/mirofishApi.ts` — cliente do frontend.
- `chat-ui/src/pages/SimuladorPage.tsx` — página **Simulador IQ OS** (resultados, ações,
  elenco, relatório e nova simulação).
- `chat-ui/src/pages/MiroFishPage.tsx` — página do motor (fontes, semente, trabalhos e chaves).
- `docker/mirofish/Dockerfile` + `pt_language.py` + `pt_backend_strings.py` + serviço
  `mirofish` no `docker-compose.yml` — a imagem do motor em português
  (ver [docker-setup.md](docs/docker-setup.md#8-mirofish-motor-de-previsão-por-enxame-de-agentes)).
- Testes: `tests/test_mirofish.py` (sementes, envelope de respostas, registo dos trabalhos,
  leitura de resultados e relatório) e `tests/test_mirofish_settings.py` (chaves).
