# BloombergGPT + RAG com PDF → Markdown — Arquitetura

## 1. Visão geral

Este módulo adiciona ao IQ OS:

- Um **modelo estilo BloombergGPT** (decoder-only, domínio financeiro) treinável a partir do corpus existente + documentos markdown provenientes de PDFs.
- Uma **pipeline de ingestão de PDFs** que converte cada documento para Markdown estruturado (texto + metadados).
- Um **motor RAG** (Retrieval-Augmented Generation) sobre os documentos markdown: segmentação, embeddings, vector store, rerank simples e geração condicionada.
- **Endpoints FastAPI** para upload de PDFs, listar documentos, fazer perguntas ao RAG e treinar o modelo BloombergGPT-style.
- Uma **nova página no frontend** para gestão de documentos, upload drag-and-drop e chat RAG.

## 2. Componentes

```
rag/
├── ingestion/
│   ├── __init__.py
│   ├── pdf_to_markdown.py      # Extrai texto/tabelas de PDF para .md
│   └── chunker.py              # Segmenta markdown em chunks semanticamente coerentes
├── storage/
│   ├── __init__.py
│   ├── document_store.py       # Índice JSON dos documentos convertidos
│   └── vector_store.py         # FAISS/Chroma/annoy + embeddings locais (sentence-transformers)
├── models/
│   ├── __init__.py
│   ├── bloomberg_gpt.py        # Configuração e criação do modelo BloombergGPT-style
│   └── train_bloomberg.py      # Fine-tuning contínuo (from scratch ou sobre gpt2/mistral)
├── chat/
│   ├── __init__.py
│   ├── rag_engine.py           # Recupera chunks e constrói prompt enriquecido
│   └── explain_predictions.py  # Análise/justificação de previsões ARIMA/LLM
data/documents/
├── uploads/                    # PDFs originais
├── markdown/                   # .md extraídos (um por documento)
└── chunks/                     # chunks serializados (JSONL)
```

## 3. Fluxo de dados

1. **Upload** → PDF guardado em `data/documents/uploads/`.
2. **Ingestão** → `pdf_to_markdown.py` converte para `data/documents/markdown/<id>.md` e extrai metadados (título, páginas, hash).
3. **Chunking** → `chunker.py` quebra o markdown em parágrafos/tabelas com overlap controlado e guarda em `data/documents/chunks/<id>.jsonl`.
4. **Indexação** → `vector_store.py` gera embeddings (modelo local `all-MiniLM-L6-v2`) e constrói índice FAISS/Chroma em `data/vectors/`.
5. **Query RAG** → recupera top-k chunks, opcional rerank por data/fonte, e invoca modelo BloombergGPT-style ou Mistral/GPT-2 local.
6. **Resposta** → inclui resumo gerado + citações (trechos markdown + página/origem).

## 4. Modelo BloombergGPT-style

Opções implementadas:

- **Opção A (lightweight)**: configuração tipo GPT-2/Mistral com vocabulário financeiro expandido e prompt formatado como "Contexto: ...\nPergunta: ...\nResposta:".
- **Opção B (avarida)**: arquitetura específica baseada no paper BloombergGPT (50B params não é viável local); por isso usamos uma **receita mini inspirada**: RoPE, camadas aumentadas (16), hidden 768, intermediate 1536, contexto 2048, tokenizer BPE treinado sobre corpus financeiro + documentos.

O treino pode ser:

- **From-scratch** com `model/bloomberg-finance/`.
- **Continual pre-training** a partir dos pesos do Mistral-finance existente (`model/mistral-finance/final`) para aproveitar o que já foi treinado.

## 5. Integração com agente existente

- Novo backend disponível: `bloomberg`.
- Quando o utilizador seleciona "BloombergGPT" no chat, o agente utiliza o modelo RAG caso existam documentos indexados; caso contrário cai para o modelo base financeiro.
- O RAG pode ser invocado explicitamente através de `/rag/query` ou via `/chat?backend=bloomberg` quando a pergunta deteta intenção de consulta documental.

## 6. Segurança e limites

- Upload limitado a 50 MB por ficheiro, apenas PDFs.
- Processamento assíncrono para PDFs grandes; endpoint de status.
- Não são enviados dados para APIs externas: embeddings e LLM correm localmente.
- Hash SHA-256 do PDF para evitar duplicados.

## 7. Endpoints previstos

- `GET /rag/health`
- `POST /rag/documents` multipart upload de PDF
- `GET /rag/documents` listar documentos
- `DELETE /rag/documents/{doc_id}`
- `POST /rag/query` perguntar aos documentos
- `POST /rag/ingest/{doc_id}` forçar re-ingestão
- `POST /models/bloomberg/train` iniciar treino (async)
- `GET /models/bloomberg/status` estado do treino
- `GET /models/bloomberg/explain/{ticker}` explicar previsão de ticker
