"""Indexação em tempo real: avisar os motores de busca do que mudou (IndexNow).

O IndexNow é um protocolo partilhado por Bing, Yandex, Seznam e Naver: publica-se
a lista de endereços que mudaram e o motor confirma que os **recebeu**. Recebido
não é indexado — o protocolo não promete indexação e nada aqui é apresentado como
se prometesse; o que se registra é o pedido feito e a resposta do motor.

Quem decide o que é público são os **sitemaps que a plataforma já gera**:
`cms_render.render_sitemap` (site), `shop_render.render_sitemap` (loja) e o
`sitemap-app.xml` das rotas da aplicação. Não existe aqui um mapa de endereços
paralelo — um tipo de página novo entra sozinho por já estar no sitemap, e o
`lastmod` de cada entrada distingue «página nova» de «página editada».

Sem chave configurada — ou com `INDEXNOW_ENABLED` por ligar — o módulo fica
**inerte**: não anuncia nada. A chave lê-se como as restantes integrações
(`service_keys.resolver`: índice do Elasticsearch → ambiente → `.env`), o que
permite ligá-la na administração sem reiniciar o backend; o interruptor
(`INDEXNOW_ENABLED`) vive nos composes, porque o `.env` do PC é copiado para a VM
e um valor lá dentro valeria o mesmo em desenvolvimento e em produção.

O `lastmod` dos sitemaps tem granularidade de **dia**: uma página editada no
mesmo dia em que já foi anunciada não volta a sê-lo até a data mudar. Para
forçar, `sincronizar(forcar=True)` reenvia tudo o que é público agora.
"""
from __future__ import annotations

import html
import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
INDEXNOW_DIR = ROOT / "data" / "indexnow"
ESTADO_PATH = INDEXNOW_DIR / "estado.json"
REGISTO_PATH = INDEXNOW_DIR / "submissoes.jsonl"

#: Sitemap da aplicação. O `dist/` é o que o nginx serve; o `public/` é a origem
#: (usado em desenvolvimento, antes de haver build).
SITEMAPS_DA_APP = (
    ROOT / "chat-ui" / "dist" / "sitemap-app.xml",
    ROOT / "chat-ui" / "public" / "sitemap-app.xml",
)

#: Chave da administração/`.env` que liga este módulo.
CHAVE_ID = "indexnow_key"

#: Endpoint partilhado por Bing, Yandex, Seznam e Naver. `INDEXNOW_ENDPOINT`
#: permite apontar a outro (ou a um servidor de testes).
ENDPOINT = "https://api.indexnow.org/indexnow"

#: O protocolo aceita 10 000 endereços por pedido.
LOTE_MAXIMO = 10000

#: Segundos de espera pelo motor. O pedido corre sempre fora do caminho de quem
#: publica (ou, quando é manual, num pedido de administração).
TIMEOUT = 15.0

#: Quantos endereços do lote ficam no registo (o resto é contagem).
REGISTO_AMOSTRA = 50

_CHAVE_VALIDA = re.compile(r"^[A-Za-z0-9-]{8,128}$")
_ENTRADA = re.compile(r"<url>(.*?)</url>", re.S)
_LOC = re.compile(r"<loc>(.*?)</loc>", re.S)
_LASTMOD = re.compile(r"<lastmod>(.*?)</lastmod>", re.S)

_local = threading.local()
_lock = threading.Lock()
_a_sincronizar = False
_pendente = False

#: `INDEXNOW_KEY` pode vir do índice da administração, do ambiente ou do `.env`.
NOMES_DA_CHAVE = ("INDEXNOW_KEY",)

#: A chave é consultada a cada escrita no CMS/loja. Uma cache curta evita
#: transformar cada publicação numa ida ao Elasticsearch e, ao mesmo tempo,
#: deixa o efeito de a ligar na administração aparecer em segundos.
TTL_DA_CHAVE = 10.0
_cache_chave: Tuple[float, Tuple[str, str]] = (0.0, ("", ""))

_ENV_FILES = (ROOT / ".env", ROOT.parent / ".env")


# ---------------------------------------------------------------------------
# Chave e host
# ---------------------------------------------------------------------------
def _da_administracao() -> Optional[str]:
    """Chave gravada em `Administração → Chaves e integrações` (índice do ES)."""
    from api import service_keys  # noqa: PLC0415 - import tardio: evita ciclos

    try:
        return (service_keys.valores_guardados() or {}).get(CHAVE_ID) or None
    except Exception:  # noqa: BLE001 - sem Elasticsearch ainda há ambiente/`.env`
        logger.debug("IndexNow: índice das chaves indisponível", exc_info=True)
        return None


def _do_ambiente() -> Tuple[Optional[str], str]:
    """(chave, origem) da variável de ambiente ou do `.env` do projeto."""
    for nome in NOMES_DA_CHAVE:
        valor = (os.environ.get(nome) or "").strip()
        if valor:
            return valor, f"ambiente:{nome}"
    for caminho in _ENV_FILES:
        try:
            if not caminho.is_file():
                continue
            for linha in caminho.read_text(encoding="utf-8", errors="ignore").splitlines():
                limpa = linha.strip()
                if not limpa or limpa.startswith("#") or "=" not in limpa:
                    continue
                nome, _, valor = limpa.partition("=")
                if nome.strip() in NOMES_DA_CHAVE:
                    valor = valor.strip().strip("'\"")
                    if valor:
                        return valor, f"env_file:{caminho.name}"
        except OSError:  # pragma: no cover - ficheiro ilegível não pode travar
            continue
    return None, "ausente"


def chave_e_origem(*, fresco: bool = False) -> Tuple[str, str]:
    """(chave válida, onde está). Chave inválida conta como ausente."""
    global _cache_chave
    agora = time.monotonic()
    if not fresco and (agora - _cache_chave[0]) < TTL_DA_CHAVE:
        return _cache_chave[1]
    valor, origem = _da_administracao(), "indice"
    if not valor:
        valor, origem = _do_ambiente()
    valor = (valor or "").strip()
    if valor and not _CHAVE_VALIDA.match(valor):
        logger.warning(
            "IndexNow: chave inválida em %s (só letras, dígitos e hífen, 8 a 128 caracteres); anúncios desligados",
            origem,
        )
        valor, origem = "", f"{origem}:invalida"
    elif not valor:
        valor, origem = "", "ausente"
    _cache_chave = (agora, (valor, origem))
    return valor, origem


def chave(*, fresco: bool = False) -> str:
    """Chave do IndexNow (8-128 caracteres `A-Za-z0-9-`), ou `""` se não houver."""
    return chave_e_origem(fresco=fresco)[0]


def ativo() -> bool:
    """Só se anuncia com o interruptor ligado **e** chave válida."""
    return ligado() and bool(chave())


#: Interruptor explícito da indexação em tempo real. Vive nos composes, e não no
#: `.env`, por uma razão prática: o `.env` do PC é copiado para a VM pelo
#: `14-servico-vm.ps1`, pelo que um interruptor lá dentro valeria o mesmo nas
#: duas instalações — e o que se quer é o contrário, falar pelo domínio público
#: a partir de produção e calar-se em desenvolvimento (onde o conteúdo não é o
#: que está publicado).
LIGADO = frozenset({"1", "true", "sim", "yes", "on"})


def ligado() -> bool:
    """`INDEXNOW_ENABLED` (nos composes): por omissão desligado."""
    return (os.environ.get("INDEXNOW_ENABLED") or "").strip().lower() in LIGADO


def endpoint() -> str:
    return (os.environ.get("INDEXNOW_ENDPOINT") or "").strip() or ENDPOINT


def base_url() -> str:
    """Origem absoluta do site público — a mesma que os sitemaps usam nos `<loc>`."""
    from api import cms_render, cms_store  # noqa: PLC0415

    try:
        settings = cms_store.get_settings()
    except Exception:  # noqa: BLE001
        settings = {}
    return str(settings.get("base_url") or cms_render.DEFAULT_BASE_URL).rstrip("/")


def host_atual() -> str:
    """Só o host (`sabemos.studio`), que é o que o protocolo exige no pedido."""
    return urlparse(base_url()).netloc


def key_location() -> str:
    """Endereço do ficheiro da chave, na raiz do domínio."""
    chave_atual = chave()
    return f"{base_url()}/{chave_atual}.txt" if chave_atual else ""


def ficheiro_chave(nome: str) -> Optional[str]:
    """Conteúdo do ficheiro `{chave}.txt`, ou `None` se o nome não for a nossa chave.

    É o que prova ao motor que o domínio é de quem submete: o ficheiro tem de
    estar na **raiz** do host. Serve-se sempre que exista chave (mesmo com a
    indexação desligada) — é um ficheiro público por natureza, e assim pode
    verificar-se antes de ligar o interruptor.
    """
    chave_atual = chave()
    if chave_atual and nome == chave_atual:
        return chave_atual
    return None


def _mascarar(valor: str) -> str:
    if len(valor) <= 6:
        return "•" * len(valor)
    return f"{valor[:4]}…{valor[-4:]} ({len(valor)} caracteres)"


# ---------------------------------------------------------------------------
# Inventário de endereços públicos
# ---------------------------------------------------------------------------
def _entradas_do_sitemap(xml: str) -> Dict[str, str]:
    """`endereço → lastmod` de um sitemap (o `lastmod` fica vazio quando não existe)."""
    entradas: Dict[str, str] = {}
    for bloco in _ENTRADA.findall(xml or ""):
        loc = _LOC.search(bloco)
        if not loc:
            continue
        lastmod = _LASTMOD.search(bloco)
        entradas[html.unescape(loc.group(1).strip())] = lastmod.group(1).strip() if lastmod else ""
    return entradas


def _sitemap_da_app() -> str:
    for caminho in SITEMAPS_DA_APP:
        try:
            if caminho.is_file():
                return caminho.read_text(encoding="utf-8", errors="ignore")
        except OSError:  # pragma: no cover - ficheiro ilegível não pode travar
            continue
    return ""


def _fontes() -> Dict[str, str]:
    """Os três sitemaps públicos, em XML. Uma fonte que falhe não esconde as outras."""
    from api import cms_render, shop_render  # noqa: PLC0415 - import tardio: evita ciclos

    fontes: Dict[str, str] = {}
    try:
        fontes["site"] = cms_render.render_sitemap()
    except Exception:  # noqa: BLE001 - o inventário não pode cair por causa do site
        logger.warning("IndexNow: sitemap do site indisponível", exc_info=True)
    try:
        fontes["loja"] = shop_render.render_sitemap()
    except Exception:  # noqa: BLE001 - idem para a loja
        logger.warning("IndexNow: sitemap da loja indisponível", exc_info=True)
    try:
        fontes["app"] = _sitemap_da_app()
    except Exception:  # noqa: BLE001
        logger.warning("IndexNow: sitemap da aplicação indisponível", exc_info=True)
    return fontes


def inventario() -> Dict[str, Any]:
    """Endereços públicos, com a proveniência de cada um.

    Só entram endereços do host público: o `sitemap-app.xml` é um ficheiro
    estático do build e traz o domínio escrito à mão, que pode não ser o domínio
    configurado no CMS. Submeter um endereço de outro host é recusado pelo motor
    (422) e recusaria o lote inteiro.
    """
    host = host_atual()
    urls: Dict[str, str] = {}
    por_fonte: Dict[str, int] = {}
    fora_do_host: List[str] = []
    for nome, xml in _fontes().items():
        entradas = _entradas_do_sitemap(xml)
        dentro = {url: lastmod for url, lastmod in entradas.items() if not host or urlparse(url).netloc == host}
        por_fonte[nome] = len(dentro)
        fora_do_host.extend(sorted(set(entradas) - set(dentro))[:5])
        urls.update(dentro)
    return {"urls": urls, "por_fonte": por_fonte, "fora_do_host": fora_do_host, "host": host}


def urls_publicas() -> Dict[str, str]:
    return inventario()["urls"]


# ---------------------------------------------------------------------------
# Estado do que já foi anunciado
# ---------------------------------------------------------------------------
def _ler_estado() -> Dict[str, Any]:
    try:
        with ESTADO_PATH.open("r", encoding="utf-8") as ficheiro:
            dados = json.load(ficheiro)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):  # pragma: no cover - estado ilegível recomeça
        logger.warning("IndexNow: estado ilegível em %s; a recomeçar", ESTADO_PATH, exc_info=True)
        return {}
    return dados if isinstance(dados, dict) else {}


def _gravar_estado(dados: Dict[str, Any]) -> None:
    INDEXNOW_DIR.mkdir(parents=True, exist_ok=True)
    tmp = ESTADO_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(ESTADO_PATH)


def _registar(linha: Dict[str, Any]) -> None:
    """Uma linha JSON por submissão — o que se pediu e o que o motor respondeu."""
    try:
        INDEXNOW_DIR.mkdir(parents=True, exist_ok=True)
        with REGISTO_PATH.open("a", encoding="utf-8") as ficheiro:
            ficheiro.write(json.dumps(linha, ensure_ascii=False, default=str) + "\n")
    except OSError:  # pragma: no cover - o registo não pode travar o anúncio
        logger.warning("IndexNow: não foi possível escrever o registo", exc_info=True)


def registos(limite: int = 5) -> List[Dict[str, Any]]:
    """Últimas submissões (mais recente primeiro)."""
    try:
        linhas = REGISTO_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()
    except FileNotFoundError:
        return []
    except OSError:  # pragma: no cover
        return []
    resultado: List[Dict[str, Any]] = []
    for linha in reversed(linhas[-200:]):
        try:
            resultado.append(json.loads(linha))
        except ValueError:
            continue
        if len(resultado) >= limite:
            break
    return resultado


def _comparar(atual: Dict[str, str], enviados: Dict[str, str]) -> Tuple[List[str], List[str], List[str]]:
    """(novos, alterados, desaparecidos) desde o último anúncio."""
    novos = [url for url in atual if url not in enviados]
    alterados = [url for url, lastmod in atual.items() if url in enviados and enviados[url] != lastmod]
    removidos = [url for url in enviados if url not in atual]
    return sorted(novos), sorted(alterados), sorted(removidos)


def pendentes() -> Dict[str, List[str]]:
    """O que o motor ainda não sabe, segundo o último anúncio registado."""
    with _lock:
        enviados = dict((_ler_estado().get("urls") or {}))
    novos, alterados, removidos = _comparar(urls_publicas(), enviados)
    return {"novos": novos, "alterados": alterados, "removidos": removidos}


# ---------------------------------------------------------------------------
# Submissão
# ---------------------------------------------------------------------------
def _pedido(urls: Sequence[str]) -> Dict[str, Any]:
    """Envia um lote. Nunca levanta: a resposta do motor (ou a falha) é o resultado."""
    corpo = json.dumps(
        {"host": host_atual(), "key": chave(), "keyLocation": key_location(), "urlList": list(urls)},
        ensure_ascii=False,
    ).encode("utf-8")
    pedido = urllib.request.Request(  # noqa: S310 - endereço fixo do protocolo
        endpoint(),
        data=corpo,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(pedido, timeout=TIMEOUT) as resposta:  # noqa: S310
            return {"estado": int(getattr(resposta, "status", 200)), "resposta": _texto(resposta.read())}
    except urllib.error.HTTPError as erro:
        # 403/422 vêm com explicação em texto simples, e é ela que diz o que está
        # mal (chave não encontrada no host, `host` diferente do dos endereços).
        return {"estado": int(erro.code), "resposta": _texto(erro.read()), "motivo": str(erro.reason or "")}
    except Exception as exc:  # noqa: BLE001 - rede em baixo não pode cair no publicador
        return {"estado": 0, "resposta": "", "motivo": str(exc)}


def _texto(dados: Any) -> str:
    if not dados:
        return ""
    if isinstance(dados, bytes):
        return dados.decode("utf-8", "replace")[:400]
    return str(dados)[:400]


def _submeter_lotes(alvo: Dict[str, str], motivo: str) -> Dict[str, Any]:
    """Envia (em lotes de 10 000) e só dá por anunciado o que o motor aceitou."""
    urls = sorted(alvo)
    aceites: List[str] = []
    respostas: List[Dict[str, Any]] = []
    for inicio in range(0, len(urls), LOTE_MAXIMO):
        lote = urls[inicio : inicio + LOTE_MAXIMO]
        resposta = _pedido(lote)
        estado = int(resposta.get("estado") or 0)
        aceite = estado in (200, 202)
        respostas.append(
            {
                "estado": estado,
                "urls": len(lote),
                "resposta": resposta.get("resposta") or "",
                "motivo": resposta.get("motivo") or "",
            }
        )
        if aceite:
            aceites.extend(lote)
        if not aceite:
            # Um lote recusado (chave em falta no host, endereços de outro host)
            # não é dado como anunciado: fica pendente para a próxima tentativa.
            logger.warning(
                "IndexNow: lote de %s endereços recusado com %s — %s",
                len(lote),
                estado,
                resposta.get("motivo") or resposta.get("resposta") or "sem resposta",
            )
        linha = {
            "em": _agora(),
            "motivo": motivo,
            "endpoint": endpoint(),
            "estado": estado,
            "urls": len(lote),
            "resposta": resposta.get("resposta") or "",
            "motivo_do_erro": resposta.get("motivo") or "",
            "amostra": lote[:REGISTO_AMOSTRA],
        }
        _registar(linha)
    return {"aceites": aceites, "respostas": respostas}


def sincronizar(*, motivo: str = "manual", forcar: bool = False) -> Dict[str, Any]:
    """Anuncia o que mudou desde o último anúncio. Seguro de chamar a qualquer hora."""
    if not ativo():
        return {
            "ativo": False,
            "ligado": ligado(),
            "motivo": motivo,
            "submetidos": 0,
            "detalhe": (
                "Indexação em tempo real desligada."
                if not ligado()
                else "Sem chave configurada (Administração → Chaves e integrações, ou INDEXNOW_KEY)."
            ),
        }
    with _lock:
        enviados = dict(_ler_estado().get("urls") or {})
    atual = urls_publicas()
    if forcar:
        alvo = dict(atual)
        novos, alterados, removidos = _comparar({}, enviados)
    else:
        novos, alterados, removidos = _comparar(atual, enviados)
        alvo = {**{url: atual[url] for url in novos + alterados}, **{url: "" for url in removidos}}
    if not alvo:
        return {
            "ativo": True,
            "motivo": motivo,
            "submetidos": 0,
            "pendentes": 0,
            "detalhe": "Nada mudou desde o último anúncio.",
        }
    resultado = _submeter_lotes(alvo, motivo)
    aceites = resultado["aceites"]
    if aceites:
        with _lock:
            estado_atual = _ler_estado()
            enviados = dict(estado_atual.get("urls") or {})
            for url in aceites:
                enviados[url] = alvo[url]
            for url in removidos:
                # Desapareceu do sitemap: o endereço deixa de ser público e o
                # motor é avisado disso mesmo.
                enviados.pop(url, None)
            estado_atual["urls"] = enviados
            estado_atual["atualizado_em"] = _agora()
            estado_atual["submissoes"] = int(estado_atual.get("submissoes") or 0) + 1
            estado_atual["ultima_submissao"] = {
                "em": _agora(),
                "motivo": motivo,
                "urls": len(aceites),
                "novos": len(novos),
                "alterados": len(alterados),
                "removidos": len(removidos),
                "respostas": resultado["respostas"],
            }
            _gravar_estado(estado_atual)
    return {
        "ativo": True,
        "motivo": motivo,
        "submetidos": len(aceites),
        "novos": len(novos),
        "alterados": len(alterados),
        "removidos": len(removidos),
        "respostas": resultado["respostas"],
    }


def anunciar_em_fundo(motivo: str) -> None:
    """Pede um anúncio e volta logo: quem publica não espera pela rede nem por falhas.

    Um anúncio já em curso não se atropela — marca-se outro para depois, para que
    uma publicação feita a meio não se perca.
    """
    global _a_sincronizar, _pendente
    if not ativo() or getattr(_local, "dentro", False):
        return
    with _lock:
        if _a_sincronizar:
            _pendente = True
            return
        _a_sincronizar = True
    threading.Thread(target=_trabalhar, args=(motivo,), name="indexnow", daemon=True).start()


def _trabalhar(motivo: str) -> None:
    global _a_sincronizar, _pendente
    _local.dentro = True
    try:
        while True:
            with _lock:
                _pendente = False
            sincronizar(motivo=motivo)
            with _lock:
                if not _pendente:
                    break
    except Exception:  # noqa: BLE001 - o anúncio nunca pode derrubar quem publicou
        logger.warning("IndexNow: anúncio falhou (%s)", motivo, exc_info=True)
    finally:
        _local.dentro = False
        with _lock:
            _a_sincronizar = False
            repetir = _pendente
            _pendente = False
        if repetir:
            anunciar_em_fundo(f"{motivo} (repetição)")


def estado() -> Dict[str, Any]:
    """Retrato para a administração: o que está ligado, o que falta anunciar, o que se enviou."""
    chave_atual, origem = chave_e_origem(fresco=True)
    dados = inventario()
    with _lock:
        guardado = _ler_estado()
    enviados = dict(guardado.get("urls") or {})
    novos, alterados, removidos = _comparar(dados["urls"], enviados)
    return {
        "ligado": ligado(),
        "ativo": bool(chave_atual) and ligado(),
        "endpoint": endpoint(),
        "base_url": base_url(),
        "host": dados["host"],
        "key_location": key_location(),
        "chave_mascarada": _mascarar(chave_atual) if chave_atual else None,
        "chave_origem": origem,
        "publicos": {
            "total": len(dados["urls"]),
            "por_fonte": dados["por_fonte"],
            "fora_do_host": dados["fora_do_host"],
        },
        "pendentes": {
            "total": len(novos) + len(alterados) + len(removidos),
            "novos": novos[:20],
            "alterados": alterados[:20],
            "removidos": removidos[:20],
        },
        "anunciados": len(enviados),
        "submissoes": int(guardado.get("submissoes") or 0),
        "ultimo_anuncio": guardado.get("ultima_submissao"),
        "registos": registos(5),
    }


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


