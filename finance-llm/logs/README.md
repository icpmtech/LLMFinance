# Backfill de embeddings dos contratos

Preenche o campo `embedding` (`dense_vector`, 384 dimensões) nos documentos do
índice `contratos` do Elasticsearch, para que a **Pesquisa profunda**
(`/deep-search`) possa usar **kNN** nesse âmbito e não apenas BM25.

## Porque é que isto é preciso

| Índice | Documentos | Com `embedding` |
|---|---:|---:|
| `finance_entities` | 214 123 | **100 %** |
| `contratos` | 2 250 969 | ~0,8 % → este backfill |

O `api/deep_search_service.py` só entra em kNN num âmbito com cobertura
suficiente (`MIN_VECTOR_PERCENT = 1.0`, ou seja **≥ 22 510** vectores em
`contratos`, e no mínimo `MIN_VECTOR_DOCS = 100`). Enquanto não chegar lá, o
âmbito dos contratos aparece em `vector_skipped` com o motivo, visível na nota
de recuperação da página.

**Com o ritmo atual (~19 docs/s), faltam ~5 mil documentos para passar o
limiar — cerca de 5 minutos de execução.** A partir daí os contratos começam a
contribuir para a parte semântica, mesmo com o backfill a meio.

## Ficheiros

Todos em `finance-llm/logs/`:

| Ficheiro | Para que serve |
|---|---|
| **`backfill.ps1`** | Controlador: `estado`, `iniciar`, `pausar`, `continuar`, `parar`, `reiniciar`. Também corre a mesma ação numa máquina remota por SSH. |
| **`_backfill_contratos_v2.py`** | O trabalho a sério: backfill paralelo, retomável e pausável. |
| `_backfill_launch.cmd` | Arrancador gerado pelo controlador (é o que o WMI executa). Não editar à mão. |
| `_backfill_contratos.log` | Log do backfill (progresso de cada processo). |
| `_backfill_run.log` | Log de execução (arranques, fim, código de saída). |
| `_backfill.pausa` | Ficheiro-sinalizador: existe ⇒ foi pedida pausa. |
| `_backfill_estado.json` | Amostra anterior (hora + cobertura) para calcular o ritmo. |
| `_backfill_contratos.py` | Versão antiga, de um só processo. Mantida para referência; faz ~15 docs/s contra ~19 desta. |

Ficheiros de medição (não fazem parte da execução normal):
`_bench_embed.py`, `_bench_threads.py`, `_bench_mp.py`, `_qa_pesquisa_profunda.py`.

## Utilização

```powershell
cd C:\LLMFinance\finance-llm\logs

# progresso, ritmo e estimativa (só lê, não altera nada)
.\backfill.ps1 -Acao estado

# arranca em segundo plano, desacoplado do terminal
.\backfill.ps1 -Acao iniciar -Workers 6 -Threads 2

# pausa: cada processo acaba o lote em curso (~1-4 min) e sai
.\backfill.ps1 -Acao pausar

# continua: tira a pausa e, se não estiver a correr, volta a arrancar
.\backfill.ps1 -Acao continuar

# mata já os processos (retomável, sem repetir trabalho)
.\backfill.ps1 -Acao parar

# parar + arrancar
.\backfill.ps1 -Acao reiniciar
```

Aceita as formas curtas em inglês: `status`, `start`, `pause`, `resume`, `stop`.

### Parâmetros

| Parâmetro | Omissão | Descrição |
|---|---|---|
| `-Workers` | `6` | Processos de codificação. |
| `-Threads` | `2` | Threads do PyTorch **por processo**. |
| `-Anos` | `''` | Anos a preencher, ex. `-Anos "2025,2026"`. Vazio = do mais recente para o mais antigo (2026 → 2012). |
| `-EsUrl` | `http://127.0.0.1:9200` | Endereço do Elasticsearch. |

### Remoto (por SSH)

A mesma ação noutra máquina Windows com o mesmo caminho do projeto:

```powershell
.\backfill.ps1 -Acao estado   -SshTarget pedro@10.0.0.5
.\backfill.ps1 -Acao iniciar  -SshTarget pedro@10.0.0.5 -Workers 8 -Threads 2
.\backfill.ps1 -Acao pausar   -SshTarget pedro@10.0.0.5
.\backfill.ps1 -Acao continuar -SshTarget pedro@10.0.0.5
```

O `-SshTarget` reconstrói a linha de comando e executa-a do outro lado com
`powershell -NoProfile -ExecutionPolicy Bypass -File`. Requer chave SSH
instalada (sem password) e PowerShell na máquina de destino.

## Como funciona por dentro

**É sempre retomável.** Cada processo só pede documentos **sem** `embedding`
(`{"bool": {"must_not": {"exists": {"field": "embedding"}}}}`), por isso parar a
meio, pausar ou reiniciar **nunca repete trabalho já feito**.

- **Fatias**: cada processo trata de uma fatia do índice
  (`slice: {id, max: workers}`), logo não se cruzam nem precisam de coordenação.
- **Lotes ordenados por comprimento** antes de codificar: o `model.encode`
  preenche o lote inteiro até ao texto mais longo, e os contratos vão de ~450 a
  ~3500 caracteres. Ordenar evita pagar o texto longo por causa de um contrato
  curto no mesmo lote.
- **Pausa cooperativa**: o `pausar` **não** mata nada — cria o ficheiro
  `_backfill.pausa`. Cada processo verifica-o entre lotes, acaba o que tem em
  mãos e sai a bem. Por isso a pausa demora entre 1 e 4 minutos.
- **Anos, do mais recente para o mais antigo** (`--por-ano`): o que interessa
  para pesquisa fica indexado primeiro, e o histórico vai sendo preenchido
  depois.
- Só grava com `es.bulk(..., refresh=False)`; faz `refresh` no fim.

## Desempenho (medido nesta máquina)

Repartição do tempo por documento: **codificação 89 %**, `bulk` 6 %, leitura 5 %.
O Elasticsearch **não** é o gargalo (`bulk` a 229 docs/s); a codificação é.

A codificação **quase não escala com threads** — é limitada por largura de
banda de memória, não por núcleos (textos curtos, p50 = 144 caracteres):

| Threads | docs/s | Por thread |
|---:|---:|---:|
| 1 | 14,9 | 14,9 |
| 2 | 26,3 | 13,2 |
| 4 | 28,1 | 7,0 |
| 6 | 33,1 | 5,5 |
| 12 | 36,0 | 3,0 |
| 14 | 31,1 | 2,2 |

Daí a escolha **6 processos × 2 threads** em vez de 1 processo × 12 threads.
Isoladamente, 2 threads rendem **13,2 docs/s por thread** contra **3,0** de 12
threads.

Com textos reais (p50 = 682 caracteres, média ~850) um processo com 12 threads
faz apenas **15 docs/s** — 40 horas para o conjunto completo.

> **Honestidade sobre o ganho:** na prática, com a máquina carregada, o
> paralelismo rendeu só ~1,3× (15 → 19 docs/s), porque as duas configurações
> acabam por usar as mesmas ~12 threads e o limite é a **largura de banda de
> memória**, não o número de núcleos. O ganho é maior numa máquina com núcleos
> livres — e foi isso que a tabela acima mede.

Números observados durante a execução real (máquina também ocupada com
contentores Docker e builds):

- **768 documentos por lote**, ~660–680 mil caracteres, **~4,0 min por lote por
  processo** → **3,2 docs/s por processo**
- **~19 docs/s no total** com `6 × 2` → **~33 h** para os 2,25 M documentos

As medições foram feitas com a máquina a **~85 % de CPU** (builds do Docker e
Elasticsearch a competir); cada processo recebia ~0,8 núcleos em vez dos 2 que
pediu. Numa máquina livre, o ritmo deve ser bastante melhor.

> A estimativa do `-Acao estado` pode parecer muito melhor de vez em quando
> (chegou a marcar 130 docs/s): as gravações saem todas juntas no fim de cada
> lote e criam picos. O valor a ter em conta é a média dos lotes completos, não
> uma amostra de 30 s.

### Se for preciso acelerar

1. **`onnxruntime` com quantização int8.** O `onnxruntime 1.20.1` já está
   instalado no `.venv`; converter o modelo para ONNX int8 costuma dar 2–4×.
   Exige mexer no `_get_embedding_model` do `api/vector_service.py`.
2. **Mais processos, menos threads** (a tabela acima é clara), desde que haja
   núcleos livres.
3. **Menos texto por contrato**: hoje o texto inclui `objectoContrato`,
   `descContrato`, `fundamentacao` **e** `search_text` (este último é longo e
   repete informação). Encurtar muda o resultado da pesquisa — decisão de
   produto, não só de desempenho.
4. **Correr com a máquina livre**: os números acima foram medidos com as builds
   do Docker e o Elasticsearch a competir pelos mesmos núcleos.

## Monitorizar

```powershell
.\backfill.ps1 -Acao estado          # cobertura, processos, pausa, ritmo, estimativa

# contagem direta no Elasticsearch
curl.exe -s "http://127.0.0.1:9200/contratos/_count?q=embedding:*"

# progresso detalhado (por processo)
Get-Content .\_backfill_contratos.log -Tail 20 -Encoding UTF8
```

Ler os logs com `read_file`/`Get-Content -Encoding UTF8` — **`Get-Content` sem
`-Encoding UTF8`** mostra acentos partidos (`máx` → `mÃ¡x`).

## Verificar que passou a ser usado

Quando a cobertura de `contratos` chegar a 1 %:

```powershell
curl.exe -s "http://127.0.0.1:8002/deep-search/search?q=contratos%20de%20saude&mode=vector&max_sources=20"
```

`vector_skipped` deixa de mencionar `contracts`, `vector_lists` passa a contar
as listas semânticas desse âmbito e os resultados passam a incluir contratos
escolhidos por semelhança e não só por palavras-chave.

## Armadilhas conhecidas

- **A build do Docker é o gargalo do ambiente**: o *builder* processa builds em
  série, por isso um `docker compose build` fica **na fila, sem output nenhum**,
  enquanto houver um `docker compose ... up --build` a correr (aconteceu com o
  deploy `deploy/kamatera/origin`). Confirmar com
  `Get-CimInstance Win32_Process -Filter "Name='docker.exe'"`.
- **O `parar` não pode filtrar só pela linha de comando**: os trabalhadores do
  `multiprocessing` arrancam com `python -c "from multiprocessing.spawn ..."` e
  não trazem o nome do script. É preciso descer a **árvore de processos** — o
  `backfill.ps1` já o faz.
- **O `cmd.exe` lançador pode sobreviver uns segundos** depois de o python sair.
  Se `continuar`/`iniciar` só olhasse para a árvore, respondia «Já está a correr»
  sem nada a correr; por isso o controlador distingue **trabalhadores ativos**
  (processos `python.exe` na árvore) de **restos**, e limpa os restos sozinho.
- **`run_in_terminal` pode remover o `cd` inicial** do comando — usar sempre
  caminhos absolutos.
- **`Select-Object -Last N` acumula** o output: nada aparece até o comando
  terminar. Para acompanhar em tempo real, escrever para ficheiro com
  `Tee-Object` ou registar em log.
- **Container com código assado**: para o backfill isto é irrelevante (corre no
  `.venv` do anfitrião), mas alterações ao `api/` exigem
  `docker compose build backend` + `up -d --no-deps --force-recreate backend`.

## Alternativa oficial

Existe também o end-point `POST /elastic/vectors/index`
(`api/vector_routes.py` → `api/vector_service.py::index_missing_embeddings`).
Faz o mesmo, mas num **único processo** e sem pausa/retoma — foi medido a
~15 docs/s. Serve para preencher casos pontuais (uma entidade, um punhado de
documentos) ou para disparar a partir da UI; para os 2,25 M o caminho é este
controlador.
