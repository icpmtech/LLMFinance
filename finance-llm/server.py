"""Servidor de desenvolvimento simples para evitar conflitos de uvicorn."""
import uvicorn

if __name__ == "__main__":
    uvicorn.run("api.main:app", host="127.0.0.1", port=8002, app_dir="C:/LLMFinance/finance-llm", reload=False)
