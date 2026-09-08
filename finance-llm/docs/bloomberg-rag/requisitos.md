# Requisitos do BloombergGPT + RAG

## Python

Adicionar ao `requirements.txt`:

```text
pymupdf>=1.23.0
sentence-transformers>=2.2.0
faiss-cpu>=1.7.4
python-multipart>=0.0.9
markdown>=3.5.0
```

Notas:

- `pymupdf` é rápido e extrai texto/tabelas de PDFs.
- `faiss-cpu` foi escolhido por ser local e eficiente para CPU. Se a máquina tiver GPU, pode substituir por `faiss-gpu`.
- `sentence-transformers` fornece embeddings sem necessidade de API externa.
- `python-multipart` é necessário para upload de ficheiros no FastAPI.

## Node / frontend

Nenhuma dependência nova obrigatória. Usa React nativo para drag-and-drop e Tailwind.

## Modelo de embeddings

Por defeito:

```python
"sentence-transformers/all-MiniLM-L6-v2"
```

O primeiro download pode demorar; modelo é pequeno (~80 MB) e corre localmente.

## Modelo BloombergGPT-style

Opções de implementação:

1. **Continual pre-training** a partir de `model/mistral-finance/final` — recomendado para reaproveitar o trabalho já feito.
2. **From-scratch** com `model/bloomberg-finance/` — se quiser arquitetura inspirada no paper com configuração custom.
