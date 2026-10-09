#!/usr/bin/env python3
"""Pagina de apresentacao / offline do sabemos.studio + registo de interessados.

Corre no VM do edge (ao lado do Caddy) e serve:

- `GET  /`                     -> landing page (apresentacao do IQ OS)
- `GET  /healthz`              -> `ok`
- `POST /api/public/registo`   -> guarda um registo em JSON local
- `GET  /api/public/estatisticas` -> quantos registos existem
- `GET  /api/public/registo`   -> lista (so com `?token=` = REGISTOS_TOKEN)
- ficheiros estaticos (`/img/...`, `/app.css`, `/app.js`)

Porque existe: quando a origem (o PC) esta em baixo, o Caddy serve esta pagina
em vez de um 502 cru (era o que o Cloudflare mostrava, como Error 1033). Assim
quem chega ao dominio ve a apresentacao e pode deixar contacto — os registos
ficam guardados no proprio VM, em `REGISTOS_PATH`.

Sem dependencias externas: so a biblioteca padrao, para a imagem ser minima e
nao precisar de atualizacoes de seguranca frequentes.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

APP_DIR = Path(__file__).resolve().parent
REGISTOS_PATH = Path(os.environ.get("REGISTOS_PATH", "/data/registos.json"))
REGISTOS_TOKEN = os.environ.get("REGISTOS_TOKEN", "")
PORT = int(os.environ.get("PORT", "8090"))

# Limites: o formulario e publico, por isso o corpo e o ritmo sao apertados.
MAX_BODY = 8 * 1024
RATE_MAX = 6           # registos por IP ...
RATE_WINDOW = 3600     # ... por hora

EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s.]+(\.[^@\s.]+)+$")
CAMPOS_TEXTO = {"nome": 120, "organizacao": 160, "cargo": 120, "telefone": 40, "mensagem": 1200}

_lock = threading.Lock()
_vistos: dict[str, list[float]] = {}


def _ler() -> list[dict]:
    if not REGISTOS_PATH.exists():
        return []
    try:
        dados = json.loads(REGISTOS_PATH.read_text(encoding="utf-8"))
        return dados if isinstance(dados, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _gravar(linhas: list[dict]) -> None:
    REGISTOS_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Escrita atomica: um corte a meio deixaria o ficheiro invalido.
    tmp = REGISTOS_PATH.with_name(REGISTOS_PATH.name + ".tmp")
    tmp.write_text(json.dumps(linhas, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(REGISTOS_PATH)


def _ritmo_ok(ip: str) -> bool:
    agora = time.time()
    with _lock:
        marcas = [t for t in _vistos.get(ip, []) if agora - t < RATE_WINDOW]
        if len(marcas) >= RATE_MAX:
            _vistos[ip] = marcas
            return False
        marcas.append(agora)
        _vistos[ip] = marcas
        return True


def _limpar(valor: object, limite: int) -> str:
    if not isinstance(valor, str):
        return ""
    return " ".join(valor.split())[:limite]


def _validar(payload: dict) -> tuple[dict | None, str | None]:
    nome = _limpar(payload.get("nome"), CAMPOS_TEXTO["nome"])
    email = _limpar(payload.get("email"), 160).lower()
    if len(nome) < 2:
        return None, "Indique o seu nome."
    if not EMAIL_RE.match(email):
        return None, "Indique um email valido."

    registo = {"nome": nome, "email": email}
    for campo, limite in CAMPOS_TEXTO.items():
        if campo in ("nome",):
            continue
        valor = _limpar(payload.get(campo), limite)
        if valor:
            registo[campo] = valor

    interesse = payload.get("interesse")
    if isinstance(interesse, list):
        limpos = [_limpar(i, 40) for i in interesse[:8]]
        registo["interesse"] = [i for i in limpos if i]

    # Consentimento explicito: sem isto nao guardamos nada (RGPD).
    if payload.get("consentimento") is not True:
        return None, "E preciso aceitar o contacto para enviar o pedido."
    registo["consentimento"] = True
    return registo, None


class Handler(BaseHTTPRequestHandler):
    server_version = "iqos-landing"

    # ---------------------------------------------------------------- utils
    def _json(self, codigo: int, corpo: dict) -> None:
        dados = json.dumps(corpo, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(dados)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(dados)

    def _ficheiro(self, caminho: Path, tipo: str, cache: str = "no-cache") -> None:
        try:
            dados = caminho.read_bytes()
        except OSError:
            self._json(404, {"erro": "nao encontrado"})
            return
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(dados)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(dados)

    def log_message(self, fmt: str, *args) -> None:  # ruido: so erros interessam
        if args and str(args[1]).startswith(("4", "5")):
            super().log_message(fmt, *args)

    @property
    def _ip(self) -> str:
        # O Caddy põe o cliente real em X-Forwarded-For.
        encaminhado = self.headers.get("X-Forwarded-For", "")
        return encaminhado.split(",")[0].strip() or self.client_address[0]

    # ------------------------------------------------------------------ GET
    def do_GET(self) -> None:  # noqa: N802 (nome imposto por BaseHTTPRequestHandler)
        caminho = urlparse(self.path)
        rota = caminho.path.rstrip("/") or "/"

        if rota == "/healthz":
            self._json(200, {"estado": "ok", "servico": "landing"})
            return

        if rota == "/api/public/estatisticas":
            self._json(200, {"total": len(_ler())})
            return

        if rota == "/api/public/registo":
            token = parse_qs(caminho.query).get("token", [""])[0]
            if not REGISTOS_TOKEN or token != REGISTOS_TOKEN:
                self._json(403, {"erro": "token invalido"})
                return
            self._json(200, {"total": len(_ler()), "registos": _ler()})
            return

        # Os assets vivem sob `/lp/` para nao colidirem com a SPA (que ocupa
        # `/` e `/assets/`): assim a mesma pagina funciona no endereco proprio
        # (`/landing`) e como pagina de erro, seja qual for o caminho pedido.
        estaticos = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/landing": ("index.html", "text/html; charset=utf-8"),
            "/landing/": ("index.html", "text/html; charset=utf-8"),
            "/index.html": ("index.html", "text/html; charset=utf-8"),
            "/lp/app.css": ("app.css", "text/css; charset=utf-8"),
            "/lp/app.js": ("app.js", "application/javascript; charset=utf-8"),
        }
        if rota in estaticos:
            nome, tipo = estaticos[rota]
            self._ficheiro(APP_DIR / nome, tipo)
            return

        # Imagens dos prints (podem ser cacheadas: o nome nao muda).
        if rota.startswith("/lp/img/"):
            nome = os.path.basename(rota)
            if not nome or not nome.endswith(".png"):
                self._json(404, {"erro": "nao encontrado"})
                return
            self._ficheiro(APP_DIR / "img" / nome, "image/png", "public, max-age=86400")
            return

        self._json(404, {"erro": "nao encontrado"})

    # ----------------------------------------------------------------- POST
    def do_POST(self) -> None:  # noqa: N802
        if urlparse(self.path).path.rstrip("/") != "/api/public/registo":
            self._json(404, {"erro": "nao encontrado"})
            return

        try:
            tamanho = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            tamanho = 0
        if tamanho <= 0 or tamanho > MAX_BODY:
            self._json(413, {"erro": "pedido invalido"})
            return

        try:
            payload = json.loads(self.rfile.read(tamanho).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._json(400, {"erro": "JSON invalido"})
            return
        if not isinstance(payload, dict):
            self._json(400, {"erro": "JSON invalido"})
            return

        if not _ritmo_ok(self._ip):
            self._json(429, {"erro": "Demasiados pedidos. Tente mais tarde."})
            return

        registo, erro = _validar(payload)
        if erro or registo is None:
            self._json(400, {"erro": erro})
            return

        with _lock:
            linhas = _ler()
            existente = next((l for l in linhas if l.get("email") == registo["email"]), None)
            if existente:
                # Repetir o formulario atualiza o pedido em vez de duplicar.
                existente.update(registo)
                existente["atualizado_em"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                criado = False
            else:
                registo["pedido_em"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                registo["ip"] = self._ip
                linhas.append(registo)
                criado = True
            _gravar(linhas)
            total = len(linhas)

        self._json(201 if criado else 200, {
            "ok": True,
            "novo": criado,
            "total": total,
            "mensagem": "Pedido registado." if criado else "Pedido atualizado.",
        })


if __name__ == "__main__":
    servidor = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"[landing] a servir em 0.0.0.0:{PORT} (registos: {REGISTOS_PATH})", flush=True)
    servidor.serve_forever()
