#!/usr/bin/env python3
"""Mini portal de monitorizacao do servidor do IQ OS.

Porque e que isto existe **fora da solucao**
--------------------------------------------
Um monitor que dependa da aplicacao nao serve para diagnosticar a aplicacao. Se
este painel precisasse do backend, do frontend ou do Elasticsearch para
desenhar-se, ele ficaria em branco exatamente quando mais faz falta -- e o
sintoma confundir-se-ia com o problema.

Por isso vive ao lado do `landing`, no edge, com tres capacidades que a
aplicacao nao tem:

  * fala com o **socket do Docker** (`/var/run/docker.sock`) para saber o estado
    real dos contentores e das imagens, sem passar por nenhum servico da solucao;
  * le as metricas da maquina de `/proc` (que num contentor **nao** e isolado:
    `meminfo` e `loadavg` sao os do anfitriao);
  * corre com `network_mode: host`, para poder sondar os servicos no
    `127.0.0.1:<porta>` onde eles estao publicados.

O que ele mostra
----------------
  * **Servicos** -- por contentor: imagem, estado, saude, quando arrancou,
    reinicios, portas publicadas e uma sonda HTTP real a cada porta;
  * **Imagens** -- repositorio:tag, tamanho, quando foi criada, e se esta presa a
    algum contentor;
  * **Maquina** -- carga, memoria, swap, disco e tempo no ar.

O login de admin e obrigatorio para tudo menos o `healthz` e os ficheiros
estaticos. A password vem de `MONITOR_PASSWORD`; nao ha base de dados de
utilizadores de proposito -- seria mais uma peca para falhar.

Sem dependencias externas: so a biblioteca padrao, como o `landing`.
"""
from __future__ import annotations

import hmac
import http.client
import json
import os
import secrets
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

APP_DIR = Path(__file__).resolve().parent

PORT = int(os.environ.get("PORT", "8091"))
# O Caddy encaminha `/monitor*` para aqui preservando o caminho, por isso o
# servidor tem de o esperar. Ver `handle /monitor*` no Caddyfile.
BASE_PATH = "/" + os.environ.get("BASE_PATH", "/monitor").strip("/")
PASSWORD = os.environ.get("MONITOR_PASSWORD", "")
SESSAO_TTL = int(os.environ.get("MONITOR_SESSION_TTL", str(12 * 3600)))
DOCKER_SOCK = os.environ.get("DOCKER_SOCK", "/var/run/docker.sock")

# Endereco de escuta. **127.0.0.1 por omissao**, e isso e obrigatorio aqui: este
# servico corre com `network_mode: host`, logo o `ports:` do compose nao se
# aplica e quem decide o que fica exposto e este bind. Esta VM **nao tem
# firewall** -- um `0.0.0.0` ficaria acessivel a Internet inteira, com o socket
# do Docker atras. Quem chega de fora passa sempre pelo Caddy.
#
# O `landing` nao precisa disto porque esta em rede bridge e publica
# `127.0.0.1:8090:8090`, que ja o prende ao loopback.
BIND = os.environ.get("MONITOR_BIND", "127.0.0.1")

# Tentativas de entrada por IP, para nao deixar a password a ceu aberto a quem
# queira forca-la.
TENTATIVAS_MAX = 8
TENTATIVAS_JANELA = 900

# Sondas HTTP: curtas, porque uma porta que nao responde nao deve atrasar o
# painel. Em paralelo, senao N portas mortas somavam N x timeout.
SONDA_TIMEOUT = 2.0


# --------------------------------------------------------------------------
# Cliente do socket do Docker
# --------------------------------------------------------------------------
class _SocketDocker(http.client.HTTPConnection):
    """Liga a API do Docker pelo socket unix.

    `http.client` so fala TCP por omissao; trocar o `connect` e o suficiente e
    evita trazer o SDK do Docker para dentro da imagem.
    """

    def __init__(self, caminho: str) -> None:
        super().__init__("localhost")
        self._caminho = caminho

    def connect(self) -> None:  # type: ignore[override]
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(8)
        self.sock.connect(self._caminho)


def docker_get(caminho: str):
    """GET a API do Docker. Levanta se nao responder ou nao for 200."""
    conn = _SocketDocker(DOCKER_SOCK)
    try:
        conn.request("GET", caminho)
        resp = conn.getresponse()
        corpo = resp.read()
        if resp.status != 200:
            raise RuntimeError(f"Docker {resp.status}: {corpo[:120]!r}")
        return json.loads(corpo or b"null")
    finally:
        conn.close()


def _portas(detalhe: dict) -> list[dict]:
    """Portas do anfitriao publicadas por um contentor."""
    saida = []
    mapa = ((detalhe.get("NetworkSettings") or {}).get("Ports") or {})
    for interna, ligacoes in mapa.items():
        for lig in (ligacoes or []):
            porta = lig.get("HostPort")
            if porta:
                saida.append({
                    "interna": interna,
                    "host": int(porta),
                    "ip": lig.get("HostIp") or "",
                })
    return sorted(saida, key=lambda p: p["host"])


def _sonda(porta: int) -> dict:
    """Uma sonda HTTP a `127.0.0.1:<porta>`.

    Qualquer resposta HTTP conta como "responde" -- um 401 ou um 404 provam que
    ha algo vivo do outro lado. So a ausencia de resposta e que e falha, e e
    isso que interessa distinguir.
    """
    t = time.time()
    conn = http.client.HTTPConnection("127.0.0.1", porta, timeout=SONDA_TIMEOUT)
    try:
        conn.request("GET", "/")
        resp = conn.getresponse()
        resp.read(2048)
        return {"porta": porta, "ok": True, "codigo": resp.status,
                "ms": round((time.time() - t) * 1000)}
    except Exception as exc:  # noqa: BLE001
        return {"porta": porta, "ok": False, "erro": type(exc).__name__,
                "ms": round((time.time() - t) * 1000)}
    finally:
        conn.close()


# --------------------------------------------------------------------------
# Recolha de estado
# --------------------------------------------------------------------------
def _ler_proc(caminho: str) -> str:
    try:
        return Path(caminho).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def maquina() -> dict:
    """Metricas do anfitriao.

    `/proc/meminfo` e `/proc/loadavg` **nao** sao isolados por contentor: mesmo
    numa imagem normal mostram os valores do anfitriao. Como este servico corre
    com `network_mode: host`, tambem nao ha desvio pelo lado da rede.
    """
    info: dict = {}

    campos = {}
    for linha in _ler_proc("/proc/meminfo").splitlines():
        if ":" in linha:
            chave, _, resto = linha.partition(":")
            campos[chave.strip()] = resto.strip()

    def kb(nome: str) -> int:
        try:
            return int(campos.get(nome, "0 kB").split()[0])
        except (ValueError, IndexError):
            return 0

    total = kb("MemTotal")
    disponivel = kb("MemAvailable")
    swap_total = kb("SwapTotal")
    swap_livre = kb("SwapFree")
    info["memoria"] = {
        "total_mb": total // 1024,
        "usada_mb": (total - disponivel) // 1024,
        "disponivel_mb": disponivel // 1024,
        "percentagem": round(100 * (total - disponivel) / total, 1) if total else 0,
    }
    # O swap merece destaque proprio: apareceu a 1,3 GB num dos incidentes de
    # hoje e explica lentidao que de outra forma parece misteriosa.
    info["swap"] = {
        "total_mb": swap_total // 1024,
        "usado_mb": (swap_total - swap_livre) // 1024,
        "percentagem": round(100 * (swap_total - swap_livre) / swap_total, 1) if swap_total else 0,
    }

    try:
        carga = _ler_proc("/proc/loadavg").split()
        info["carga"] = [float(x) for x in carga[:3]]
        info["processos"] = carga[3] if len(carga) > 3 else None
    except (ValueError, IndexError):
        info["carga"] = [0.0, 0.0, 0.0]

    try:
        info["cpu_nucleos"] = os.cpu_count()
    except Exception:  # noqa: BLE001
        info["cpu_nucleos"] = None

    try:
        segundos = float(_ler_proc("/proc/uptime").split()[0])
        info["uptime_h"] = round(segundos / 3600, 1)
    except (ValueError, IndexError):
        info["uptime_h"] = None

    try:
        st = os.statvfs("/")
        total_d = st.f_blocks * st.f_frsize
        livre_d = st.f_bavail * st.f_frsize
        info["disco"] = {
            "total_gb": round(total_d / 1024 ** 3, 1),
            "livre_gb": round(livre_d / 1024 ** 3, 1),
            "percentagem": round(100 * (total_d - livre_d) / total_d, 1) if total_d else 0,
        }
    except OSError:
        info["disco"] = None

    return info


def contentores() -> list[dict]:
    """Servicos: um registo por contentor, com saude e portas."""
    try:
        lista = docker_get("/containers/json?all=1")
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"nao consegui falar com o Docker: {exc}") from exc

    saida = []
    for resumo in lista:
        nome = (resumo.get("Names") or ["?"])[0].lstrip("/")
        detalhe: dict = {}
        try:
            detalhe = docker_get(f"/containers/{resumo['Id']}/json")
        except Exception:  # noqa: BLE001
            pass
        estado = detalhe.get("State") or {}
        saude = ((estado.get("Health") or {}).get("Status")) or None
        saida.append({
            "nome": nome,
            "imagem": resumo.get("Image"),
            "estado": estado.get("Status") or resumo.get("State"),
            "saude": saude,
            "iniciado": estado.get("StartedAt"),
            "reinicios": detalhe.get("RestartCount"),
            "portas": _portas(detalhe),
            "comando": (resumo.get("Command") or "")[:80],
        })

    saida.sort(key=lambda c: c["nome"])

    # Sondar as portas publicadas dos contentores que estao a correr: e a
    # diferenca entre "o contentor esta de pe" e "o servico responde".
    portas: list[int] = []
    for c in saida:
        if c["estado"] == "running":
            portas.extend(p["host"] for p in c["portas"] if p["ip"] in ("127.0.0.1", ""))
    portas = sorted(set(portas))
    if portas:
        with ThreadPoolExecutor(max_workers=min(12, len(portas))) as pool:
            resultados = {r["porta"]: r for r in pool.map(_sonda, portas)}
        for c in saida:
            c["sondas"] = [resultados[p["host"]] for p in c["portas"] if p["host"] in resultados]

    return saida


def imagens() -> list[dict]:
    """Imagens da solucao, com o tamanho e se estao presas a algum contentor."""
    lista = docker_get("/images/json?all=1")
    saida = []
    for img in lista:
        tags = [t for t in (img.get("RepoTags") or []) if t != "<none>:<none>"]
        saida.append({
            "tags": tags or ["<sem tag>"],
            "sem_tag": not tags,
            "tamanho_mb": round((img.get("Size") or 0) / 1024 ** 2),
            "criada": img.get("Created"),
            "contentores": img.get("Containers") or 0,
            "partilhada_mb": round((img.get("SharedSize") or 0) / 1024 ** 2),
        })
    saida.sort(key=lambda i: i["tamanho_mb"], reverse=True)
    return saida


# --------------------------------------------------------------------------
# Sessoes
# --------------------------------------------------------------------------
_sessoes: dict[str, float] = {}
_tentativas: dict[str, list[float]] = {}
_lock = threading.Lock()


def criar_sessao() -> str:
    token = secrets.token_urlsafe(32)
    with _lock:
        _sessoes[token] = time.time() + SESSAO_TTL
    return token


def sessao_valida(token: str | None) -> bool:
    if not token:
        return False
    with _lock:
        expira = _sessoes.get(token)
        if not expira:
            return False
        if expira < time.time():
            _sessoes.pop(token, None)
            return False
        return True


def terminar_sessao(token: str | None) -> None:
    if token:
        with _lock:
            _sessoes.pop(token, None)


def pode_tentar(ip: str) -> bool:
    agora = time.time()
    with _lock:
        marcas = [t for t in _tentativas.get(ip, []) if agora - t < TENTATIVAS_JANELA]
        if len(marcas) >= TENTATIVAS_MAX:
            _tentativas[ip] = marcas
            return False
        marcas.append(agora)
        _tentativas[ip] = marcas
        return True


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
ESTATICOS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
}


class Handler(BaseHTTPRequestHandler):
    server_version = "iqos-monitor"

    # --- utilitarios ------------------------------------------------------
    def _cabecalhos(self, tipo: str, extra: dict | None = None) -> None:
        self.send_header("Content-Type", tipo)
        # O painel mostra estado interno: nada disto deve ficar em cache, nem
        # ser embutido noutro sitio.
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        for chave, valor in (extra or {}).items():
            self.send_header(chave, valor)

    def _responder(self, codigo: int, corpo: bytes, tipo: str, extra: dict | None = None) -> None:
        self.send_response(codigo)
        self._cabecalhos(tipo, extra)
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(corpo)

    def _json(self, codigo: int, dados: dict, extra: dict | None = None) -> None:
        corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
        self._responder(codigo, corpo, "application/json; charset=utf-8", extra)

    def _cookies(self) -> dict[str, str]:
        cru = self.headers.get("Cookie") or ""
        saida = {}
        for parte in cru.split(";"):
            if "=" in parte:
                k, _, v = parte.partition("=")
                saida[k.strip()] = v.strip()
        return saida

    def _token(self) -> str | None:
        return self._cookies().get("iqos_monitor")

    def _ip(self) -> str:
        # Atras do Caddy, o IP real vem no X-Forwarded-For.
        encaminhado = (self.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
        return encaminhado or (self.client_address[0] if self.client_address else "?")

    def _corpo(self, limite: int = 4096) -> dict:
        try:
            tamanho = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return {}
        if tamanho <= 0 or tamanho > limite:
            return {}
        try:
            return json.loads(self.rfile.read(tamanho) or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    def _caminho(self) -> str:
        """Caminho ja sem o prefixo publico (`/monitor`)."""
        caminho = urlparse(self.path).path
        if BASE_PATH != "/" and caminho.startswith(BASE_PATH):
            caminho = caminho[len(BASE_PATH):]
        elif BASE_PATH != "/" and caminho == BASE_PATH.rstrip("/"):
            caminho = ""
        return caminho or "/"

    def log_message(self, formato: str, *args) -> None:  # noqa: A003
        # Sem isto o contentor enchia o log com uma linha por pedido do painel,
        # que se atualiza sozinho a cada poucos segundos.
        return

    # --- rotas ------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        caminho = urlparse(self.path).path

        # `/monitor` sem barra final: os caminhos relativos do HTML
        # (`app.css`) resolveriam para `/app.css`, fora do prefixo. Redirecionar
        # e o que mantem tudo sob `/monitor/`.
        if BASE_PATH != "/" and caminho == BASE_PATH:
            self.send_response(301)
            self.send_header("Location", BASE_PATH + "/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        interno = self._caminho()

        if interno == "/healthz":
            self._responder(200, b"ok", "text/plain; charset=utf-8")
            return

        if interno == "/api/sessao":
            self._json(200, {"autenticado": sessao_valida(self._token())})
            return

        if interno == "/api/estado":
            if not sessao_valida(self._token()):
                self._json(401, {"erro": "sessao invalida"})
                return
            self._json(200, self._estado())
            return

        estatico = ESTATICOS.get(interno)
        if estatico:
            ficheiro, tipo = estatico
            caminho_disco = APP_DIR / ficheiro
            if not caminho_disco.is_file():
                self._responder(404, b"nao encontrado", "text/plain; charset=utf-8")
                return
            self._responder(200, caminho_disco.read_bytes(), tipo)
            return

        self._responder(404, b"nao encontrado", "text/plain; charset=utf-8")

    def do_POST(self) -> None:  # noqa: N802
        interno = self._caminho()

        if interno == "/api/login":
            if not PASSWORD:
                self._json(503, {"erro": "MONITOR_PASSWORD nao esta definida no servidor"})
                return
            if not pode_tentar(self._ip()):
                self._json(429, {"erro": "demasiadas tentativas; tente dentro de alguns minutos"})
                return
            dados = self._corpo()
            enviada = str(dados.get("password") or "")
            if not hmac.compare_digest(enviada, PASSWORD):
                self._json(401, {"erro": "password incorreta"})
                return
            token = criar_sessao()
            cookie = (f"iqos_monitor={token}; Path={BASE_PATH or '/'}; HttpOnly; "
                      f"Secure; SameSite=Strict; Max-Age={SESSAO_TTL}")
            self._json(200, {"ok": True}, {"Set-Cookie": cookie})
            return

        if interno == "/api/logout":
            terminar_sessao(self._token())
            cookie = f"iqos_monitor=; Path={BASE_PATH or '/'}; HttpOnly; Secure; SameSite=Strict; Max-Age=0"
            self._json(200, {"ok": True}, {"Set-Cookie": cookie})
            return

        self._json(404, {"erro": "nao encontrado"})

    # --- estado -----------------------------------------------------------
    def _estado(self) -> dict:
        estado: dict = {"hora": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
        try:
            info = docker_get("/info")
            estado["docker"] = {
                "versao": info.get("ServerVersion"),
                "contentores": info.get("Containers"),
                "em_execucao": info.get("ContainersRunning"),
                "parados": info.get("ContainersStopped"),
                "imagens": info.get("Images"),
                "nucleos": info.get("NCPU"),
                "memoria_mb": (info.get("MemTotal") or 0) // 1024 ** 2,
            }
        except Exception as exc:  # noqa: BLE001
            estado["docker"] = {"erro": str(exc)}

        for chave, funcao in (("servicos", contentores), ("imagens", imagens)):
            try:
                estado[chave] = funcao()
            except Exception as exc:  # noqa: BLE001
                estado[chave] = []
                estado[f"erro_{chave}"] = str(exc)

        estado["maquina"] = maquina()
        return estado


def main() -> None:
    if not PASSWORD:
        # Nao vale a pena arrancar sem password: o painel ficaria publico e
        # mostraria o estado interno do servidor a quem passasse.
        raise SystemExit(
            "MONITOR_PASSWORD nao esta definida -- o painel nao arranca sem ela. "
            "Defina-a no `.env` do edge (ver edge/.env.example)."
        )
    servidor = ThreadingHTTPServer((BIND, PORT), Handler)
    servidor.daemon_threads = True
    print(f"monitor a escutar em {BIND}:{PORT} sob {BASE_PATH}/", flush=True)
    servidor.serve_forever()


if __name__ == "__main__":
    main()
