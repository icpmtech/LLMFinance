# Integração do BloombergGPT + RAG no IQ OS

## 1. Onde encaixa

O módulo adiciona uma terceira dimensão ao IQ OS, sem alterar as funcionalidades existentes:

- **Chat financeiro** (GPT-2/Mistral) — mantém-se.
- **Previsão ARIMA** — mantém-se; agora o modelo BloombergGPT pode explicar/justificar previsões.
- **RAG de documentos** — novo: upload de PDFs, Markdown, vector store e respostas com fontes.

## 2. Alterações no backend

### Novos ficheiros

- `rag/ingestion/pdf_to_markdown.py`
- `rag/ingestion/chunker.py`
- `rag/storage/document_store.py`
- `rag/storage/vector_store.py`
- `rag/models/bloomberg_gpt.py`
- `rag/models/train_bloomberg.py`
- `rag/chat/rag_engine.py`
- `rag/chat/explain_predictions.py`

### Ficheiros alterados

- `api/models.py`: adicionar `RagQueryRequest`, `RagQueryResponse`, `DocumentEntry`, `DocumentListResponse`, `TrainingStatusResponse`.
- `api/agent.py`: reconhecer backend `"bloomberg"`; delegar perguntas documentais ao RAG.
- `api/main.py`: registar routers/endpoints de upload, query, documentos e treino.
- `requirements.txt`: adicionar `pymupdf`, `sentence-transformers`, `faiss-cpu`/`chromadb`, `markdown`, `python-multipart`.

## 3. Alterações no frontend

### Novos ficheiros

- `chat-ui/src/pages/RagPage.tsx` — página de documentos + chat RAG.
- `chat-ui/src/components/RagSidebar.tsx` — lista de documentos.
- `chat-ui/src/components/RagChat.tsx` — chat com fontes.
- `chat-ui/src/components/PdfUploader.tsx` — drag-and-drop.

### Ficheiros alterados

- `chat-ui/src/App.tsx`: adicionar view `"rag"`.
- `chat-ui/src/types.ts`: tipos `Document`, `RagQuery`, `RagResponse`, `TrainingStatus`.
- `chat-ui/src/api.ts`: funções `uploadDocument`, `listDocuments`, `deleteDocument`, `queryRag`, `trainBloomberg`, `getTrainingStatus`.
- `chat-ui/src/components/Sidebar.tsx`: botão "Documentos/RAG".
- `chat-ui/src/components/ChatInput.tsx`: adicionar backend "BloombergGPT".

## 4. Modelo de dados de documentos

```json
{
  "id": "sha256_hash",
  "filename": "relatorio_2024.pdf",
  "title": "Relatório Anual 2024",
  "pages": 42,
  "uploaded_at": "2026-09-07T10:00:00Z",
  "status": "indexed",
  "size_bytes": 1234567,
  "md_path": "data/documents/markdown/<id>.md",
  "chunks_count": 128
}
```

## 5. Modelo de chunks

```jsonl
{"doc_id": "...", "chunk_id": "..._0", "text": "...", "source": "relatorio_2024.pdf p.3", "page": 3}
```

## 6. Prompt RAG

```
Contexto extraído de documentos financeiros:
---
[chunk 1]
---
[chunk 2]
---

Com base no contexto acima, responde de forma breve e clara em português.
Se não houver informação suficiente, diz "Não encontrei essa informação nos documentos carregados".

Pergunta: {pergunta}
Resposta:
```

## 7. Treino BloombergGPT-style

### Configuração padrão (CPU/GPU pequeno)

- Base: `model/mistral-finance/final` (continual pre-training) ou `model/bloomberg-finance` (from-scratch).
- Dataset: corpus `data/final/train.jsonl` + chunks dos documentos markdown convertidos para instruções `Contexto/Resposta`.
- Hiperparâmetros:
  - lr: 5e-5
  - batch: 2/4 com gradient accumulation 4
  - epochs: 1–3
  - max_length: 512
  - warmup 100 steps

### Saídas

- Checkpoints em `model/bloomberg-finance/checkpoints/`.
- Modelo final em `model/bloomberg-finance/final/`.
- Estado de treino em `training/bloomberg_state.pt`.
- Logs em `training/bloomberg_train.log`.

## 8. Fluxo de utilização típico

1. Utilizador carrega PDFs na página "Documentos/RAG".
2. Backend converte para Markdown e indexa.
3. Utilizador faz perguntas no chat RAG; respostas incluem fontes.
4. Opcionalmente inicia treino do BloombergGPT com documentos + corpus.
5. Seleciona "BloombergGPT" no chat geral para obter respostas enriquecidas com RAG.
