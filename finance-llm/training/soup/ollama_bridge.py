"""Ponte OpenAI -> Ollama para a página *Model Chat* do painel do Soup.

Dois problemas, uma peça:

1. A página só aceita `http://localhost` como endpoint do chat (protecção SSRF em
   `soup_cli/ui/app.py`), e o Ollama corre no *host*, fora do Docker. O serviço
   `soup-ollama-bridge` partilha a rede do `soup-ui` (`network_mode:
   service:soup-ui`), e este processo abre lá dentro o `localhost:11434`.
2. O painel fala o dialeto da OpenAI (`POST /v1/chat/completions`, SSE com
   `choices[0].delta.content`) e, nesse dialeto, o Ollama **ignora** o `think`:
   com um modelo que pensa, os tokens são todos gastos no campo `reasoning` e o
   `content` volta vazio — no painel, o chat fica sem resposta. Aqui o pedido é
   traduzido para a API nativa (`/api/chat`), onde `think: false` funciona: o
   mesmo Gemma passou de «nenhuma resposta» a responder em português em ~12 s.

O `max_tokens` é limitado por `OLLAMA_BRIDGE_MAX_TOKENS` (por omissão 256): o
proxy do painel corta aos 120 s (`httpx.stream(timeout=120.0)`) e, a ~4 tokens/s
nesta CPU, 256 tokens ficam por volta de um minuto.

Variáveis:
    OLLAMA_BRIDGE_UPSTREAM    Ollama (por omissão http://host.docker.internal:11434)
    OLLAMA_BRIDGE_MODEL       Modelo quando o pedido não traz `model` (gemma4:e4b)
    OLLAMA_BRIDGE_THINK       false (por omissão) | true | auto (não envia o campo)
    OLLAMA_BRIDGE_MAX_TOKENS  Tecto de tokens gerados (256)
    OLLAMA_BRIDGE_HOST/PORT   Onde escutar (127.0.0.1:11434)
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM = os.environ.get("OLLAMA_BRIDGE_UPSTREAM", "http://host.docker.internal:11434").rstrip("/")
DEFAULT_MODEL = os.environ.get("OLLAMA_BRIDGE_MODEL", "gemma4:e4b")
THINK = os.environ.get("OLLAMA_BRIDGE_THINK", "false").strip().lower()
MAX_TOKENS_CAP = int(os.environ.get("OLLAMA_BRIDGE_MAX_TOKENS", "256"))
LISTEN_HOST = os.environ.get("OLLAMA_BRIDGE_HOST", "127.0.0.1")
LISTEN_PORT = int(os.environ.get("OLLAMA_BRIDGE_PORT", "11434"))
TIMEOUT = float(os.environ.get("OLLAMA_BRIDGE_TIMEOUT", "115"))


def _log(*args) -> None:
    print("[ponte]", *args, flush=True)


def _upstream_json(path: str, *, timeout: float | None = None):
    """Pedido simples (sem streaming) ao Ollama. Devolve (status, corpo)."""
    request = urllib.request.Request(f"{UPSTREAM}{path}", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout or TIMEOUT) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        detalhe = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(detalhe)
        except ValueError:
            return exc.code, {"error": detalhe}


def _ollama_body(payload: dict, *, com_think: bool) -> dict:
    options = {}
    try:
        pedido = int(payload.get("max_tokens") or MAX_TOKENS_CAP)
    except (TypeError, ValueError):
        pedido = MAX_TOKENS_CAP
    options["num_predict"] = max(1, min(pedido, MAX_TOKENS_CAP))
    for chave in ("temperature", "top_p"):
        valor = payload.get(chave)
        if valor is not None:
            try:
                options[chave] = float(valor)
            except (TypeError, ValueError):
                pass
    body = {
        "model": (payload.get("model") or DEFAULT_MODEL).strip() or DEFAULT_MODEL,
        "messages": payload.get("messages") or [],
        "stream": True,
        "options": options,
    }
    if com_think:
        body["think"] = THINK == "true"
    return body


def _abrir_upstream(body: dict):
    """Abre o stream do Ollama; se ele recusar o `think`, repete sem esse campo."""

    def _abrir(corpo: dict):
        request = urllib.request.Request(
            f"{UPSTREAM}/api/chat",
            data=json.dumps(corpo).encode(),
            headers={"Content-Type": "application/json"},
        )
        return urllib.request.urlopen(request, timeout=TIMEOUT)

    try:
        return _abrir(body)
    except urllib.error.HTTPError as exc:
        if "think" not in exc.read().decode("utf-8", "replace").lower() or "think" not in body:
            raise
        _log("o modelo recusou `think`; a repetir sem esse campo")
        body.pop("think", None)
        return _abrir(body)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "soup-ollama-bridge"

    def log_message(self, formato: str, *args) -> None:
        _log(formato % args)

    def _json(self, status: int, corpo: dict) -> None:
        dados = json.dumps(corpo).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def do_GET(self) -> None:  # noqa: N802 — API do http.server
        if self.path.startswith("/health"):
            return self._json(200, {"status": "ok"})
        if self.path.startswith("/api/tags"):
            status, corpo = _upstream_json("/api/tags", timeout=20)
            return self._json(status, corpo)
        if self.path.startswith("/v1/models"):
            status, corpo = _upstream_json("/api/tags", timeout=20)
            modelos = [
                {"id": m.get("name", ""), "object": "model", "owned_by": "ollama"}
                for m in corpo.get("models", [])
            ]
            return self._json(status, {"object": "list", "data": modelos})
        self._json(404, {"error": "só /v1/chat/completions, /v1/models e /health"})

    def do_POST(self) -> None:  # noqa: N802
        if not self.path.startswith("/v1/chat/completions"):
            return self._json(404, {"error": "só /v1/chat/completions"})
        try:
            tamanho = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(tamanho) or b"{}")
        except (ValueError, OSError) as exc:
            return self._json(400, {"error": f"pedido inválido: {exc}"})

        # SSE sem Content-Length: a resposta acaba quando a ligação fechar.
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

        def sse(dados: dict) -> None:
            self.wfile.write(f"data: {json.dumps(dados)}\n\n".encode())
            self.wfile.flush()

        try:
            with _abrir_upstream(_ollama_body(payload, com_think=THINK != "auto")) as upstream:
                for linha in upstream:
                    linha = linha.strip()
                    if not linha:
                        continue
                    try:
                        pedaco = json.loads(linha)
                    except ValueError:
                        continue
                    # O `thinking` fica de fora de propósito: o painel só mostra `content`.
                    texto = (pedaco.get("message") or {}).get("content") or ""
                    if texto:
                        sse({"choices": [{"delta": {"content": texto}}]})
                    if pedaco.get("done"):
                        break
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except Exception as exc:  # rede, timeout, modelo inexistente
            _log(f"falha a falar com o Ollama: {exc}")
            sse({"error": f"ponte: {exc}"})
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()


def main() -> int:
    with ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), _Handler) as server:
        _log(
            f"OpenAI-compatível em http://{LISTEN_HOST}:{LISTEN_PORT} -> {UPSTREAM}"
            f" | modelo={DEFAULT_MODEL} think={THINK} max_tokens<={MAX_TOKENS_CAP}"
        )
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
