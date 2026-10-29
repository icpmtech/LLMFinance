# Fine-tuning com o Soup

> Como treinar os modelos do IQ OS com os dados que já estão no Elasticsearch,
> usando o [Soup](https://github.com/MakazhanAlpamys/Soup) (`soup-cli`) num
> contentor.

> Para o modelo de contratos treinado **em CPU, com pausa/retoma e avaliado num
> conjunto held-out**, ver [modelo-contratos.md](modelo-contratos.md): é o
> caminho actual (`training/train_lora_contratos.py`), e o Soup continua a ser o
> atalho para um treino de uma só tacada numa máquina com GPU.

O treino do projecto era feito à mão, com dois loops PyTorch próprios
(`training/train.py` para o GPT-2 e `training/train_mistral.py` para o Mistral).
Esses loops continuam a ser o que treina os modelos pequenos em CPU, mas não têm
LoRA, quantização, `val_split` nem retoma de checkpoints fiável — tudo o que o
Soup trata a partir de um ficheiro YAML. O Soup entra como o caminho de
**fine-tuning**: pega nos mesmos dados do Elasticsearch, transforma-os em pares
instrução/resposta e treina em cima do modelo que já existe.

## 1. Como está montado

```
   Elasticsearch (índices do IQ OS)
              │
              │  training/export_es_dataset.py   ← passo 1: dados → dataset
              ▼
   data/final/<receita>.jsonl      (formato Alpaca: instruction / input / output)
              │
              │  docker compose --profile train run --rm soup train -y --config …
              ▼
   model/soup-*                    (adaptador LoRA ou modelo treinado)
```

- **Passo 1 — exporter** ([training/export_es_dataset.py](../training/export_es_dataset.py)):
  lê os índices e escreve JSONL no formato Alpaca, o mesmo de
  `data/final/contratos_train.jsonl`. Não precisa do Soup: corre no venv do
  projecto ou dentro do contentor.
- **Passo 2 — treino** ([training/soup/soup-mistral.yaml](../training/soup/soup-mistral.yaml)):
  o Soup carrega o dataset, aplica LoRA e escreve o resultado em `model/`.

O serviço `soup` do [docker-compose.yml](../docker-compose.yml) usa a imagem
oficial do Soup (`ghcr.io/makazhanalpamys/soup`, que já traz CUDA e
`soup-cli[train,serve,data,eval]`) com o cliente do Elasticsearch por cima —
[Dockerfile.soup](../Dockerfile.soup). O directório do projecto é montado em
`/workspace`, tal como no compose do próprio Soup: os caminhos dentro dos
configs (`./data/final/...`, `./model/...`) são os mesmos quer corra no host quer
no contentor.

## 2. Passo 1 — exportar os dados

```bash
# ver as receitas disponíveis
python training/export_es_dataset.py --list

# contratos portugueses (índice `contratos`) → data/final/contratos.jsonl
# (o `--tokenizer`/`--max-tokens` medem cada par — ver «Porquê medir os tokens»)
python training/export_es_dataset.py --dataset contratos --max-records 200000 \
    --tokenizer model/mistral-finance/final --max-tokens 950
```

| Receita | Índice | Documentos | Instrução gerada |
|---------|--------|-----------:|------------------|
| `contratos` | `contratos` | ~2,27 M | Descreve este contrato público português. |
| `contratos-es` | `contratos_es` | ~4,05 M | Descreve este contrato público espanhol. |
| `contratos-fr` | `contratos_fr` | ~61 mil | Descreve este contrato público francês. |
| `empresas` | `finance_entities` | ~214 mil | Descreve esta entidade no cadastro de contratos públicos. |
| `noticias` | `finance_news` | ~272 | Classifica o sentimento desta notícia financeira. |
| `subvencoes` | `finance_subvencoes` | ~415 mil | Descreve este subsídio público português. |

> As contagens são de documentos de topo (`_count`). O `docs.count` do
> `_cat/indices` é maior — o `contratos`, por exemplo, mostra 15,6 M porque conta
> também os documentos aninhados.

O `contratos` segue a mesma redação de
`collectors/contratos.py::build_training_corpus`, por isso o que sai daqui é
intercambiável com o corpus que já existia em `data/final/contratos_train.jsonl`.

Opções que valem a pena conhecer:

| Opção | Para que serve |
|-------|----------------|
| `--max-records N` | Teto de documentos lidos (`0` = todos). Por omissão 50 000 — o `contratos` tem 2,27 M e o ficheiro inteiro são vários GB. |
| `--dataset A --dataset B` | Várias fontes no **mesmo** ficheiro (ver «Juntar várias fontes no mesmo dataset»). O `--max-records` passa a contar **por fonte**. |
| `--query '<json>'` | Filtro Elasticsearch, ex.: `--query '{"term": {"Ano": 2025}}'`. |
| `--out <ficheiro>` | Destino (por omissão `data/final/<receita>.jsonl`). |
| `--max-chars N` | Corte por campo (`0` = sem corte). Por omissão 4 000. |
| `--tokenizer <dir>` | Tokenizer do modelo de destino, para medir os pares (ex.: `model/mistral-finance/final`). |
| `--max-tokens N` | Orçamento de tokens por par (prompt + resposta). Exige `--tokenizer`. |
| `--seed N` | Amostra **dispersa** pelo índice (ver «Porquê usar `--seed`»). Sem ele, a ordem é a do índice. |
| `--dry-run` | Só conta os documentos que o filtro apanha. |

### Porquê usar `--seed`

Um índice não está baralhado: os primeiros N documentos vêm quase sempre do mesmo
ficheiro de origem. Exportar 800 subsídios sem `--seed` deu **um** organismo e
**um** ano (todos do IGFSS, todos de 2025) — o modelo aprendia uma fatia, não a
fonte. Com `--seed 42`, os mesmos 800 deram 138 organismos, 734 beneficiários e os
dois anos:

```bash
python training/export_es_dataset.py --dataset subvencoes --max-records 800 --seed 42
```

Por dentro é um `random_score` com semente do próprio Elasticsearch (`_seq_no`),
por isso a amostra é reproduzível: a mesma semente dá o mesmo dataset.

### Porquê medir os tokens

O `soup train` **não salta** as linhas que ficam sem resposta depois da
truncagem (`data.max_length`) — aborta a corrida com
`no causal-loss target remains after tokenization/truncation`. Em 300 contratos
exportados, 4 não cabiam nos 950 tokens; sem os medir, a corrida morria por causa
deles.

O corte por caracteres não resolve o problema: o tokenizer do sistema (vocabulário
de 3 000) gasta ~1,7 caracteres por token em português e muito menos em números e
identificadores, por isso o tamanho em tokens não é proporcional ao número de
caracteres. Medir com o tokenizer certo é a única forma de garantir que passa:

```bash
# --max-tokens = janela do modelo (1024) com margem para o molde do chat
python training/export_es_dataset.py --dataset contratos --max-records 200000 \
    --tokenizer model/mistral-finance/final --max-tokens 950
```

As linhas deixadas de fora aparecem na contagem `dropped` do resumo.

### Juntar várias fontes no mesmo dataset

O `--dataset` pode repetir-se: as fontes vão todas para o **mesmo** ficheiro, e o
modelo treina com as duas. É o que faz o
[`soup-empresas-contratos.yaml`](../training/soup/soup-empresas-contratos.yaml) —
contratos (dinheiro a sair) e entidades (quem contrata e quem é contratado) na
mesma cabeça, porque a resposta a «quanto custou este contrato ao Município de
Chaves?» precisa das duas:

```bash
python training/export_es_dataset.py --dataset contratos --dataset empresas \
    --max-records 400 --seed 42 --tokenizer model/mistral-finance/final \
    --max-tokens 950 --out data/final/iqos_contratos_empresas.jsonl
```

O que muda com várias fontes:

* cada linha leva a instrução da **sua** receita e um `metadata.fonte` com o nome
  dela — quem consome o dataset sabe de onde vem cada exemplo;
* o `--max-records` conta **por fonte** (400 contratos *e* 400 entidades, não 400
  ao todo);
* o resumo passa a trazer os totais agregados e o detalhe por fonte;
* o `--query` deixa de fazer sentido e o comando recusa-o — um filtro serve uma
  fonte, não várias.

O export de referência (400 leituras de cada índice) deu 794 exemplos: 394
contratos (15 anos distintos, 2012–2026, 394 contratos diferentes) e 400
entidades (211 NIF distintos); 6 linhas ficaram de fora pelo orçamento de 950
tokens.

Índices que não têm receita própria continuam a poder ser exportados com
moldes:

```bash
python training/export_es_dataset.py --index finance_news \
  --instruction "Resume esta notícia." \
  --input-template "{title}" --output-template "{summary_pt}" \
  --fields title,summary_pt --out data/final/noticias_resumo.jsonl
```

O ficheiro só substitui o destino no fim — nunca fica um dataset truncado a
meio. A validar:

```bash
docker compose --profile train run --rm --entrypoint soup soup data validate ./data/final/contratos.jsonl
```

## 3. Passo 2 — treinar

| Config | Modelo de partida | Onde corre | Resultado |
|--------|-------------------|------------|-----------|
| [soup-mistral.yaml](../training/soup/soup-mistral.yaml) | `model/mistral-finance/final` (modelo do sistema, 512×8, vocabulário de 3 000) | CPU ou GPU | `model/soup-mistral` |
| [soup-subvencoes.yaml](../training/soup/soup-subvencoes.yaml) | `model/mistral-finance/final`, só com a fonte dos subsídios | CPU ou GPU | `model/soup-subvencoes` |
| [soup-empresas-contratos.yaml](../training/soup/soup-empresas-contratos.yaml) | `model/mistral-finance/final`, com os contratos **e** as entidades no mesmo dataset | CPU ou GPU | `model/soup-empresas-contratos` |
| [soup-qwen05-empresas-contratos.yaml](../training/soup/soup-qwen05-empresas-contratos.yaml) | `Qwen/Qwen2.5-0.5B-Instruct` (já fala português, ~1 GB) com o mesmo dataset misto | CPU (≈75 min para 195 pares) | `model/soup-qwen05-empresas-contratos` |
| [soup-mistral-instruct.yaml](../training/soup/soup-mistral-instruct.yaml) | `mistralai/Mistral-7B-Instruct-v0.3` | GPU com ≥ 8 GB de VRAM | `model/soup-mistral-7b-lora` |

Há um config por objectivo: o `soup-mistral.yaml` treina o modelo do sistema com
os contratos, o `soup-subvencoes.yaml` treina-o com **uma só fonte** (os subsídios
de `finance_subvencoes` — dinheiro público a entrar, o espelho dos contratos), o
`soup-empresas-contratos.yaml` treina-o com **duas fontes no mesmo dataset**
(contratos e o cadastro de entidades, ver «Juntar várias fontes no mesmo
dataset») e o `soup-mistral-instruct.yaml` é o caminho com GPU.

O primeiro continua o modelo que o IQ OS já usa para descrever contratos; o
segundo parte de um modelo que já conversa e ensina-lhe o domínio — é o caminho
para **melhorar as respostas**, porque o modelo do sistema tem 512 de dimensão
escondida e 3 000 tokens de vocabulário (dá para classificar e descrever, não
para dialogar).

```bash
# construir a imagem (uma vez)
docker compose --profile train build soup

# exportar e treinar (`-y` porque o `train` pede confirmação e o `run` não tem
# terminal interactivo)
docker compose --profile train run --rm --entrypoint python soup \
  training/export_es_dataset.py --dataset contratos --max-records 200000 \
  --tokenizer model/mistral-finance/final --max-tokens 950
docker compose --profile train run --rm soup train -y \
  --config training/soup/soup-mistral.yaml
```

Numa máquina com GPU há um override para isso — sem ele o Docker recusa dar a GPU
ao contentor, e sem GPU o `docker-compose.yml` principal tem de continuar a servir
quem treina em CPU:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile train run --rm soup \
  train -y --config training/soup/soup-mistral-instruct.yaml
```

Se a máquina com GPU for uma VM (ou não for esta), o caminho completo — dimensionar,
levantar, levar os dados e trazer o modelo de volta — está em
[docs/soup-vm.md](soup-vm.md), com um `training/soup/vm_setup.sh` que prepara uma
Ubuntu de raiz.

Antes de treinar, os dois passos podem ser validados sem gastar tempo: o
`--dry-run` do Soup carrega o config e o dataset sem treinar, e o exporter tem o
seu próprio `--dry-run`.

```bash
docker compose --profile train run --rm soup train --dry-run \
  --config training/soup/soup-mistral.yaml
```

Fora do Docker, no venv do projecto (o `requirements.txt` não é versionado —
ver a nota no `Dockerfile.backend` —, por isso a instalação é à mão):

```powershell
.venv\Scripts\pip install "soup-cli[train]"
.venv\Scripts\soup.exe train -y --config training/soup/soup-mistral.yaml
```

Antes de gastar horas de GPU, vale a pena perguntar ao Soup o que ele acha:

```bash
soup profile --config training/soup/soup-mistral.yaml   # memória e velocidade esperadas
soup advise ./data/final/contratos.jsonl --goal "descrever contratos públicos"
```

### Ajustar um config

O config tem poucos campos, mas são os que decidem o treino. O que se mexe
primeiro:

```yaml
data:
  train: ./data/final/contratos.jsonl   # a receita exportada no passo 1
  val_split: 0.05                       # 5% para validação

training:
  epochs: 3
  lr: 2e-5
  lora:
    r: 16                               # capacidade do adaptador (8, 16, 32, 64)
  quantization: none                    # '4bit' em GPU (precisa de CUDA)
```

Chaves desconhecidas são **recusadas** pelo Soup desde a v0.75 — um erro de
escrita não passa em silêncio, o config não carrega. Se acrescentar campos,
confirme com `soup profile --config <ficheiro>` que ele ainda carrega.

### O `chat_template` do modelo do sistema

O modelo do IQ OS é um modelo de **continuação**, não de conversa: o
`inference/generate_mistral.py` dá-lhe texto simples e o tokenizer não traz
`chat_template`. Sem isso o Soup não arranca — e sem o `{% generation %}` a perda
não sabe onde começa a resposta:

```yaml
chat_template: "{% for message in messages %}{% if message['role'] == 'assistant' %}{% generation %}### Resposta:\n{{ message['content'] }}{% endgeneration %}\n\n{% else %}### Instrução:\n{{ message['content'] }}\n\n{% endif %}{% endfor %}"
```

O molde reproduz o formato com que o modelo já foi afinado
(`training/train_mistral_contracts.py`) — treino e inferência falam a mesma
língua. O `soup-mistral-instruct.yaml` não precisa dele: o Mistral-7B-Instruct
traz o seu próprio.

Depois do treino, o Soup grava o molde no `tokenizer_config.json` do adaptador
(o próprio `soup train` avisa), e o `soup merge` herda-o.

### Quanto tempo leva

Treinar o modelo do sistema (`soup-mistral.yaml`) corre em **CPU**: numa máquina
sem GPU, 266 exemplos a 1 024 tokens deram 34 passos em ~7 minutos (~9 s por
passo). Para o corpus inteiro isto são horas, não minutos — comece por um
`--max-records` pequeno para confirmar que o fluxo corre ponta a ponta, e só
depois alargue.

O dataset misto (`soup-empresas-contratos.yaml`, 794 pares, 1 época = 189 passos)
levou **1h07** nesta máquina — 20 s por passo **em média**, mas o passo variou
entre 3 s e 33 s: o Docker Desktop deste portátil está limitado a 16,4 GB e
qualquer outro contentor a trabalhar ao mesmo tempo rouba núcleos ao treino. Com
a máquina livre, os mesmos passos correram a ~3 s. Foi por isso que a perda
demorou tanto a descer: `7,9337 → 7,5601` (validação 7,5226).

### Quando o modelo de partida já fala português

O modelo do sistema não conversa — é um *toy* de 22 M treinado de raiz. Para o
chat responder a sério há duas hipóteses: um 7B numa GPU (ver
[soup-vm.md](soup-vm.md)) ou, em CPU, um modelo **pequeno mas já pré-treinado**
(`Qwen/Qwen2.5-0.5B-Instruct`, 495 M, ~1 GB). O
[soup-qwen05-empresas-contratos.yaml](../training/soup/soup-qwen05-empresas-contratos.yaml)
faz a segunda.

O que muda na conta é que o custo passa a ser **linear em linhas × tokens**, e
este CPU tem um teto baixo. Medido aqui, com `torch.get_num_threads() = 7`:

| Operação | Tempo |
|---|---|
| forward + backward, 128 tokens | 6,6 s |
| forward + backward, 512 tokens | 11,3 s |

São ~125 GFLOP/s — o limite real desta máquina, que não tem GPU e para quem o
`quantization: 4bit` não existe (é CUDA). Só que o `soup train` em CPU ficou
**muito** abaixo disso: **4 micro-lotes em 80 minutos** (~20 min cada), com o
contentor sem qualquer limite de CPU (`cgroup cpu.max = max`, 14 núcleos
visíveis). O travão está, portanto, no caminho de treino em CPU do próprio Soup,
não no hardware nem no Docker — os 22 M mostram o mesmo padrão (189 passos em
1h07, 20 s por passo, para um modelo que devia ser submilisegundo de compute).

Daí a conclusão prática: **nesta máquina, treinar com o Soup paga-se ao minuto e
só serve para provas de mecanismo** — foi o que os 22 M deram (perda a descer,
held-out a melhorar, chat degenerado). O config do Qwen 0,5 B fica pronto e
validado (`Data OK: 185 train samples`), à espera de GPU: numa L4 são minutos.

> **Atenção ao aviso `chat template does not contain {% generation %}`.** O Qwen
> traz o molde dele, mas sem esse marcador o Soup calcula a perda sobre o texto
> todo — o prompt incluído. O treino corre, mas gasta capacidade a reaprender a
> ler o prompt. A correção é dar um `chat_template` explícito com
> `{% generation %}` à volta da resposta (como o `soup-mistral.yaml` faz para o
> modelo do sistema).

Para o chat responder **hoje**, o que funciona é a rota do Gemma local (secção
seguinte): o modelo tem a fluência e o Elasticsearch dá-lhe os dados.

Três motores, as mesmas duas linhas do dataset (`iqos_contratos_empresas_200`),
medido:

| Pergunta | Modelo do sistema afinado (22 M) | gemma4 via Ollama |
|---|---|---|
| Contrato 4338759 — CHUC / INDAS, 29 846,32 € | `--day-day-day 5-day-day…` (2,3 s) | lista correcta dos 7 campos do contrato (25,8 s) |
| Entidade «Ilídio da Silva Oliveira», 1 contrato, 3 810,00 € | `--,-day-day-04-day…` (2,0 s) | campos correctos, com «1 contrato» no singular (11,2 s) |

É a tabela que fecha a discussão: o fine-tune do modelo do sistema mexe nos
números (perda, perplexidade) mas não produz português; o modelo pré-treinado
produz — e o que lhe falta do domínio vem do Elasticsearch, no prompt.

O modelo grande (`soup-mistral-instruct.yaml`, 7B em QLoRA) sem GPU não é
praticável: use a máquina com GPU e o `--gpus all`.

> **E a receita do `soup init --template chat`** (`base:
> meta-llama/Llama-3.1-8B-Instruct`, `quantization: 4bit`)? Está **certa** — é a
> mesma forma dos configs de GPU daqui, com outro modelo de partida — e não é a
> receita que falta, é o hardware: `4bit` é QLoRA, QLoRA precisa de CUDA, e aqui
> `torch.cuda.is_available()` é `False`. O próprio Soup diz o que falta:
>
> ```
> soup profile --config <receita>
> ? No GPU detected: would fit in an assumed 24 GB (need ~14 GB)
> Compatible GPUs: RTX4060TI (16 GB), RTX4080 (16 GB), ...
> ```
>
> Em CPU, um 8B são dezenas de segundos por passo (a estimativa de velocidade do
> `profile` assume uma A100); numa época de 800 exemplos isso são centenas de
> horas. **Numa GPU a receita corre tal e qual** — só tem de apontar
> `data.train` para `./data/final/contratos.jsonl` (ou outro dataset exportado) e
> manter `format: alpaca`.

## 4. O painel de treinos (Web UI)

A mesma imagem traz um painel — *Dashboard* (corridas e curvas de perda),
*New Training*, *Data Explorer* e *Model Chat*:

```bash
docker compose --profile train up -d soup-ui
docker compose --profile train logs soup-ui     # o endereço e o token saem aqui
```

Abre em `http://127.0.0.1:7860/?token=<token>` (a porta muda-se com
`SOUP_UI_PORT`). O token é gerado a cada arranque; para um endereço fixo,
acrescente `"--auth-token", "<16-128 caracteres urlsafe>"` ao `command` do serviço.

O `soup-ui` partilha com o `soup` o volume `soup-state` (`~/.soup`), por isso as
corridas lançadas no serviço `soup` aparecem no *Dashboard*. O `--public` do
`command` é o que faz a porta publicada funcionar (o encaminhamento do Docker não
chega ao loopback do contentor); o token é o que fecha o painel a quem esteja na
mesma rede.

O *Data Explorer* lê os ficheiros do contentor: `./data/final/contratos.jsonl`
aparece com as chaves `instruction`/`input`/`output` detetadas como `alpaca`. Ele
conta as linhas todas, por isso abrir o corpus de 2,2 GB
(`contratos_train.jsonl`, 2,1 M linhas) demora — para explorar, aponte aos
datasets exportados (`--max-records`) em vez do corpus inteiro.

## 5. Depois do treino

```bash
# juntar o adaptador LoRA ao modelo base, num modelo só
docker compose --profile train run --rm soup merge \
  --adapter ./model/soup-mistral-7b-lora --output ./model/soup-mistral-7b-merged

# exportar para GGUF (dá para o Ollama, que o compose já aponta em OLLAMA_URL);
# o quantizador do llama.cpp é clonado no primeiro uso
docker compose --profile train run --rm soup export \
  --model ./model/soup-mistral-7b-lora --format gguf --quant q4_k_m

# servidor com API compatível com a OpenAI (porta 8000)
docker compose --profile train run --rm -p 8000:8000 soup serve \
  --model ./model/soup-mistral-7b-lora --host 0.0.0.0 --tool-auth-token <token>
```

O `serve` fica em `127.0.0.1:8000` por omissão; dentro do contentor é preciso
`--host 0.0.0.0` (e, fora do loopback, um `--tool-auth-token`, que só é exigido
nas rotas de ferramentas).

## 6. Testar o modelo num chat

Depois do treino, o adaptador fica em `model/<nome>` **com o `chat_template` que
lhe demos** — e é isso que o torna conversável: o modelo de partida do IQ OS é um
modelo de continuação e, sem molde, o servidor recusa mensagens de chat (responde
`HTTP 400`, mesmo com o modelo carregado).

```bash
# servidor com API compatível com a OpenAI
docker compose --profile train run --rm -p 8000:8000 soup serve \
  --model ./model/soup-subvencoes --host 0.0.0.0 --port 8000

curl http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "soup-subvencoes",
       "messages": [{"role": "user", "content": "Beneficiário: ...\nMontante: 1341.85\nFinalidade: Bolsas"}],
       "max_tokens": 120, "temperature": 0.2}'
```

No painel (secção 4), a página **Model Chat** fala com esse servidor — mas com uma
restrição que se descobre à primeira tentativa: o endpoint do painel só aceita
`http://localhost` (protecção SSRF de quem faz de proxy, `soup_cli/ui/app.py`),
e `localhost` **dentro do contentor do painel** é o próprio contentor. O
`http://host.docker.internal:8000` é recusado com `400`. A volta é pôr o servidor
na rede do painel:

```bash
docker run --rm --name soup-serve-ui --network container:finance-llm-soup-ui \
  -v "$PWD:/workspace" -w /workspace iq-os-soup:latest \
  serve --model ./model/soup-subvencoes --host 127.0.0.1 --port 8000
```

No painel, o *server URL* passa a ser `http://localhost:8000`.

### Alternativa: o Gemma local (Ollama) em vez de um modelo treinado

O painel aceita qualquer servidor compatível com a OpenAI — o Ollama do *host*
incluído. Dois detalhes obrigam a uma peça extra (o serviço
`soup-ollama-bridge`):

- o painel só aceita `http://localhost`, e o Ollama não está no Docker;
- no dialeto da OpenAI o Ollama **ignora** o `think`: um modelo que pensa gasta
  todos os tokens no campo `reasoning` e devolve `content` vazio — no painel, o
  chat ficava sem resposta (era o `[Error: Connection failed]`). A ponte traduz o
  pedido para a API nativa (`/api/chat`), onde `think: false` pega.

```bash
docker compose --profile train up -d soup-ollama-bridge
```

No painel: *server URL* `http://localhost:11434`, *Adapter* `gemma4:e4b` (é esse
campo que o proxy manda como `model`) e `max_tokens` até 256 — o proxy do painel
corta aos 120 s e, a ~4 tokens/s nesta CPU, 256 tokens são cerca de um minuto.

O mesmo registo de subsídio que o modelo pequeno respondia com «`day-day-day`»
passa a ter resposta, em ~30 s:

> *O subsídio atribuído foi de 1341.85 EUR, concedido pela FUNDACAO PARA A CIENCIA
> E A TECNOLOGIA, I. P., em 27/01/2024, com a finalidade de Bolsas.*

E com os dados das **duas** fontes do dataset misto (contratos e entidades), em
~30 s cada:

> **Contrato 7414596 – Leite Escolar**, adjudicante *Agrupamento de Escolas de
> Oliveira de Frades*, adjudicatário *LACTOGAL*, 8 940 € → *«Quem contratou foi o
> Agrupamento de Escolas de Oliveira de Frades, para a Aquisição de bens móveis
> (especificamente, Leite Escolar), e o valor do preço contratual foi de 8940.0
> EUR.»*
>
> **Entidade Bruno Miguel Costa da Silva Parente Vilela**, 5 contratos, 372 400 €
> → *«Esta entidade é adjudicatário (ou seja, é contratada). Número de contratos:
> 5 contratos. Valor total: 372 400,00 EUR.»*

Com o registo do Elasticsearch passado no *system prompt*, o modelo responde
**com os nossos dados**; sem contexto, responde do que sabe — é a diferença entre
ter fluência e ter conhecimento do domínio (o domínio vem do RAG, ou de um
fine-tune num modelo com capacidade para o aprender).

### O Gemma4 na própria plataforma (RAG) — o que foi preciso ligar

O painel do Soup é uma coisa; a plataforma é outra. Para o **IQ OS** responder com
o Ollama do host foram precisos dois arranjos, ambos com causa medida:

1. **API nativa em vez do dialecto OpenAI.** O fornecedor `ollama` do catálogo
   ([api/providers_service.py](../api/providers_service.py)) falava
   `/v1/chat/completions` — e nesse dialecto o Ollama **ignora** o `think`: um
   modelo que pensa devolve tudo em `reasoning` e o `content` vem vazio (resposta
   em branco na plataforma). Passou a `kind: "ollama"` (`/api/chat`), e o
   `_ollama_body` do [api/cloud_chat.py](../api/cloud_chat.py) manda
   `think: false`. O `OLLAMA_BASE_URL` do compose traz `/v1`, que o
   `_ollama_root()` retira antes de compor o URL nativo.
2. **Um modelo predefinido.** Sem escolha em Definições → Fornecedores de IA, a
   plataforma caía no `gpt2` local. `AI_DEFAULT_BACKEND=ollama:gemma4:e4b` (no
   `.env` local, passado ao backend pelo compose) decide quando a conta não tem
   predefinição. Vazio, o comportamento antigo mantém-se.

Resultado medido (`POST /hermes/ask`, **sem** indicar modelo — ele resolve
sozinho):

| Pergunta | Tempo | Resposta |
|---|---|---|
| «Que contratos públicos tem a INDAS?» | 107 s | citada, com 564 contratos / 9,36 M€ e os CPV do Elasticsearch |
| «Quem é a Ilídio da Silva Oliveira…» | 303 s | citada, mas com números do corpus inteiro |

> **Antes da correção da recolha**, a segunda linha respondia «72 685 contratos —
> 7,39 M€» para quem tem 1. O modelo relatou fielmente o que a recolha lhe deu; o
> erro estava na recolha, não no modelo.

#### A recolha: dois erros concretos

1. **«nos» não é a NOS.** O [api/search360_service.py](../api/search360_service.py)
   convertia qualquer «nos» minúsculo no *ticker* **NOS** (o dicionário de alcunhas
   incluía «nos», que é palavra da língua). Uma pergunta sobre uma pessoa que
   dissesse «*nos* contratos públicos» era respondida sobre a operadora de
   telecomunicações. Agora as alcunhas que são palavras comuns (`STOPWORDS`) não
   são convertidas — e um nome resolvido no cadastro manda sobre um *ticker*
   adivinhado.
2. **Nome próprio ia para texto livre.** `_resolve_entity`
   (em [api/hermes_service.py](../api/hermes_service.py)) procura o nome no
   cadastro de entidades (`search_entities`), que responde por nome e traz os
   totais já calculados, e aceita o candidato cujas palavras estão **quase todas**
   na pergunta — o inverso de extrair o nome da frase, o que o torna robusto a
   partículas («da», «de»), pontuação e ordem. Resolvido o nome, a ficha entra
   como facto; se a entidade **não tiver NIF**, a agregação por semelhança de nome
   é proibida (era ela que somava 72 685) e o prompt di-lo explicitamente.

Resultado medido depois das duas correções:

| Pergunta | Resposta |
|---|---|
| «Quem é a Ilídio da Silva Oliveira… e que valores tem?» | **1 contrato, 3,8 mil€** — e a nota de que não há NIF no cadastro, pelo que não se somam contratos por semelhança de nome |
| «Que contratos públicos tem a INDAS?» | 564 contratos, 9,36 M€ (por NIF 503505196) — inalterado |

A latência (1–5 min) é desta máquina: o gemma4 gera ~4 tokens/s em CPU e o prompt
leva 18 evidências. Numa GPU, ou com menos evidências, desce a segundos.

### A pergunta que o `soup train` não responde

A perda do treino diz que o modelo se ajustou aos dados; não diz se aprendeu ou
decorou. O [training/soup/eval_holdout.py](../training/soup/eval_holdout.py)
compara o modelo de partida com o adaptador nos pares que **nunca** entraram no
treino, montados com o mesmo molde:

```bash
docker run --rm -v "$PWD:/workspace" -w /workspace --entrypoint python iq-os-soup:latest \
  training/soup/eval_holdout.py --pairs ./data/final/subvencoes_holdout.jsonl \
  --base ./model/mistral-finance/final --adapter ./model/soup-subvencoes
```

No treino dos subsídios (794 pares, 1 época em CPU) deu:

| | Perda/token | Perplexidade | Exactidão por token |
|---|---:|---:|---:|
| Modelo de partida | 7,786 | 2 406,7 | 1,59 % |
| Adaptador treinado | 7,295 | **1 473,3** | **2,17 %** |
| *azar (3 000 tokens de vocabulário)* | *8,006* | *3 000* | *0,03 %* |

Ou seja: o fine-tune **generalizou** (a perda no held-out caiu tanto como no
treino, 7,79 → 7,30 contra 7,80 → 7,31) — não decorou. Mas a qualidade absoluta
continua fraca: perplexidade 1 473 significa que o modelo está longe de escrever
português corrente, porque o modelo do sistema é um *toy* de 22 M parâmetros
(512 de escondido) treinado de raiz em linhas de cotações. Para respostas a sério
é o `soup-mistral-instruct.yaml` numa GPU — a maquinaria é a mesma, muda o modelo
de partida.

O mesmo teste no dataset misto (contratos **e** entidades, 800 exportados, 98 de
holdout):

| | Perda/token | Perplexidade | Exactidão por token |
|---|---:|---:|---:|
| Modelo de partida | 7,918 | 2 745,4 | 1,03 % |
| Adaptador treinado | 7,561 | **1 922,5** | **2,20 %** |
| *azar (3 000 tokens de vocabulário)* | *8,006* | *3 000* | *0,03 %* |

A conclusão repete-se, e com a prova crua ao lado: servido pelo `serve`, com um
contrato que **nunca** viu, o adaptador responde

```
--day-day-day,-day-day,,-day-day-day, 2022-day, 2022-day-day ...
```

— texto degenerado, apesar de a perplexidade ter caído 30 % e a exactidão por
token ter duplicado. Duas leituras, ambas verdadeiras: o mecanismo funciona (o
treino mexe no modelo e o efeito vê-se no holdout) e a capacidade não chega (22 M
de parâmetros não escrevem português). É este o número que decide a altura de ir
para uma GPU — ver [soup-vm.md](soup-vm.md).

Para ter a prova de que o fine-tune acrescentou alguma coisa, compare com o modelo
de partida pelo `infer` — que não usa molde nenhum, por isso funciona nos dois:

```bash
# um ficheiro de perguntas em formato {"prompt": "..."} por linha
docker compose --profile train run --rm soup infer \
  --model ./model/mistral-finance/final --input ./probes_in.jsonl --output ./depois_base.jsonl
docker compose --profile train run --rm soup infer \
  --model ./model/soup-subvencoes --input ./probes_in.jsonl --output ./depois_ft.jsonl
```

Escolha as perguntas **fora** do conjunto de treino (exporte com um
`--max-records` maior e use as linhas que sobraram) — perguntar o que já está no
treino só mostra memorização.

## 7. Motor Soup na página de retreino

A partir de `/modelo/retreino` o Soup deixou de ser só linha de comandos: o
separador **motor** tem duas opções — `incremental (CPU)`, o loop da plataforma,
e `Soup (CLI)`. O segundo lê os YAMLs de `training/soup/` e mostra, por config, o
modelo base, o dataset, o número de pares e a pasta de saída.

O que acontece de cada vez:

| Ação | O que corre | Onde |
|------|-------------|------|
| listar configs | `training/soup/*.yaml` lidos pela API | `api/llm_contratos_soup.py` |
| **validar config** | `soup train -c <yaml> --dry-run` | processo filho da API |
| **treinar com Soup** | `soup train -y --config <yaml>` | subprocesso, morto por **parar** |

O progresso vem da própria saída do CLI (`step N/M`, `loss=…`), linha a linha,
para o mesmo painel que já mostra a adaptação incremental; o canal em direto
(`/llm/modelo/retreinar/ws`) transporta também `soup.passo` e `soup.a_correr`.

Duas notas que a interface assume por si:

- **A imagem do backend traz `soup-cli` sem o extra `[train]`.** Chega para
  listar e validar; para treinar, o painel mostra o comando do contentor
  (`docker compose --profile train run --rm soup train -y --config …`). Instalar
  o extra no backend traria `trl`/`accelerate` e podia subir o `transformers` —
  exactamente o que o `Dockerfile.backend.incremental` evita.
- **Um treino de cada vez.** Lançar o Soup com a adaptação incremental a correr
  (ou o contrário) é recusado: os dois querem o mesmo CPU e a mesma RAM.

Os YAMLs entram na imagem do backend apesar de `training/` estar no
`.dockerignore` — o `!training/soup` do ficheiro mantém só essa pasta (alguns KB).

## 8. Notas

- O dataset exportado (`data/final/*.jsonl`) e os modelos (`model/soup-*`) estão
  no `.gitignore` — são artefactos de dados, geram-se outra vez com os comandos
  acima.
- O serviço `soup` está no profile `train`: `docker compose up` não o arranca,
  nem o `build` do núcleo da solução o constrói.
- A versão da imagem base fixa-se com `SOUP_IMAGE=ghcr.io/makazhanalpamys/soup:<tag>`
  (por omissão `latest`), para reproduzir um treino feito numa versão antiga.
- Os pesos descarregados da HuggingFace ficam no volume `soup-cache`; sem ele, o
  Mistral-7B (~15 GB) era descarregado em cada `run`.
- O `ELASTICSEARCH_URL` do contentor aponta para o serviço `elasticsearch` do
  compose. A correr no host, o valor por omissão do código
  (`http://127.0.0.1:9200`) já serve.
