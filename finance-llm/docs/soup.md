# Fine-tuning com o Soup

> Como treinar os modelos do IQ OS com os dados que já estão no Elasticsearch,
> usando o [Soup](https://github.com/MakazhanAlpamys/Soup) (`soup-cli`) num
> contentor.

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
| `--query '<json>'` | Filtro Elasticsearch, ex.: `--query '{"term": {"Ano": 2025}}'`. |
| `--out <ficheiro>` | Destino (por omissão `data/final/<receita>.jsonl`). |
| `--max-chars N` | Corte por campo (`0` = sem corte). Por omissão 4 000. |
| `--tokenizer <dir>` | Tokenizer do modelo de destino, para medir os pares (ex.: `model/mistral-finance/final`). |
| `--max-tokens N` | Orçamento de tokens por par (prompt + resposta). Exige `--tokenizer`. |
| `--dry-run` | Só conta os documentos que o filtro apanha. |

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
| [soup-mistral-instruct.yaml](../training/soup/soup-mistral-instruct.yaml) | `mistralai/Mistral-7B-Instruct-v0.3` | GPU com ≥ 8 GB de VRAM | `model/soup-mistral-7b-lora` |

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

Numa máquina com GPU, acrescente `--gpus all` ao `run`:

```bash
docker compose --profile train run --rm --gpus all soup train -y \
  --config training/soup/soup-mistral-instruct.yaml
```

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

O modelo grande (`soup-mistral-instruct.yaml`, 7B em QLoRA) sem GPU não é
praticável: use a máquina com GPU e o `--gpus all`.

## 4. Depois do treino

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

## 5. Notas

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
