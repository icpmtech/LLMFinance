"""Sites oficiais e logótipos das empresas (ficha visual do IQ OS).

O IQ OS sabe o **nome** e o **NIF/SIRET** de cada empresa que aparece nos
contratos públicos, mas não tem a **marca** dela. Este módulo resolve, para cada
identificador, duas coisas:

1. **site oficial** — a partir de candidatos (pesquisa web no SearXNG da
   plataforma + heurística de domínio a partir do nome), todos validados por
   HTTP e **pontuados** pelo texto da página (o NIF na página é prova forte, o
   nome no título é prova média). Quando há mais de um candidato plausível, a
   **IA** escolhe o mais provável e diz porquê.
2. **logótipo** — extraído do site escolhido (`apple-touch-icon`, `rel=icon`,
   `<img>` com «logo» no caminho/classe, `og:image` e, em último recurso, o
   `favicon.ico`), normalizado com o Pillow para PNG quadrado 256×256 e guardado
   em `data/empresas/logos/<chave>.png`. Um SVG é guardado como está (escala
   melhor).

Os resultados ficam em `data/empresas/perfil.json`, com **validade** (por
omissão 120 dias), para a segunda visita ser instantânea — é o que permite ao
grafo do comprador mostrar a marca de cada fornecedor sem repetir o trabalho.

Nada aqui é obrigatório para o resto do sistema: sem rede, sem chave de IA ou
sem site encontrado, a entrada fica com `site: None` e o frontend mostra as
iniciais da empresa.
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import re
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests

logger = logging.getLogger(__name__)

#: Raiz do projeto (`finance-llm/`).
ROOT = Path(__file__).resolve().parent.parent
EMPRESAS_DIR = ROOT / "data" / "empresas"
PERFIL_FILE = EMPRESAS_DIR / "perfil.json"
LOGOS_DIR = EMPRESAS_DIR / "logos"
CONFIG_FILE = EMPRESAS_DIR / "config.json"

PERFIL_VERSION = 1

#: User-agent de browser: muitos sites devolvem 403 a clientes que se
#: identificam como robô (e o que queremos é o HTML público normal).
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 IQOS/1.0 (+contacto: administrador local)"
)

TIMEOUT_PAGINA = 9.0
TIMEOUT_IMAGEM = 9.0
TIMEOUT_PESQUISA = 12.0
#: Só se lê esta parte do HTML (uma home page é quase sempre menor).
MAX_BYTES_HTML = 700_000
MAX_BYTES_IMAGEM = 3_000_000

DIAS_VALIDADE = 120
#: Quantas empresas resolver em paralelo (a pesquisa web e os sites aguentam).
PARALELO = 4
#: Teto de tempo para a arbitragem por IA. Um modelo local lento não pode
#: atrasar a identificação do site: passado este tempo, segue-se com a pontuação
#: calculada por HTTP.
IA_TIMEOUT = 20.0
#: Depois de uma falha, a IA fica de lado este tempo (evita repetir a espera em
#: cada empresa do grafo).
IA_COOLDOWN = 600.0
#: Teto de empresas por pedido — mantém a resposta dentro de um tempo razoável.
MAX_LOTE = 12

PAISES: Dict[str, Dict[str, str]] = {
    "pt": {"label": "Portugal", "tld": "pt", "idioma": "pt"},
    "es": {"label": "Espanha", "tld": "es", "idioma": "es"},
    "fr": {"label": "França", "tld": "fr", "idioma": "fr"},
}

DEFAULTS: Dict[str, Any] = {
    "usar_pesquisa": True,
    "usar_ia": True,
    "dias_validade": DIAS_VALIDADE,
    "paralelo": PARALELO,
    "max_lote": MAX_LOTE,
    "ia_timeout": IA_TIMEOUT,
    "descricoes": True,
}

#: Domínios que **não** são o site da empresa: diretórios, agregadores,
#: redes sociais e marketplaces. Servem de pista (têm o NIF e a morada), mas
#: nunca podem ser escolhidos como site oficial.
_AGREGADORES = (
    "racius.",
    "einforma",
    "empresite",
    "infoempresa",
    "axesor",
    "einforma",
    "linkedin.",
    "facebook.",
    "instagram.",
    "twitter.",
    "x.com",
    "youtube.",
    "tiktok.",
    "wikipedia.",
    "wikidata.",
    "google.",
    "bing.",
    "bloomberg.",
    "europages",
    "paginasamarelas",
    "portugalio",
    "sapo.pt",
    "expresso.pt",
    "publico.pt",
    "jn.pt",
    "dn.pt",
    "jornaleconomico",
    "eco.sapo",
    "dinheirovivo",
    "idealista",
    "olx.",
    "custojusto",
    "amazon.",
    "aliexpress",
    "ebay.",
    "basesetorial",
    "guiaempresas",
    "informa.es",
    "empresia.es",
    "expansion.com",
    "societe.com",
    "pappers.fr",
    "infogreffe",
    "bodacc",
    "annuaire-entreprises",
    "verif.com",
    "kompass",
    "dnb.com",
    "glassdoor",
    "indeed.",
    "justdial",
    "yumpu",
    "scribd",
    "slideshare",
    "issuu",
    "trustpilot",
)

#: Palavras que não identificam uma empresa (formas sociais, atividades
#: genéricas) e que por isso não contam para a semelhança de nomes.
_STOPWORDS = {
    "lda",
    "lda.",
    "sa",
    "s.a",
    "s.a.",
    "unipessoal",
    "unip",
    "sociedade",
    "soc",
    "empresa",
    "grupo",
    "company",
    "co",
    "sl",
    "s.l",
    "s.l.",
    "slu",
    "s.a.u",
    "sas",
    "sasu",
    "sarl",
    "sarlu",
    "eurl",
    "sci",
    "scp",
    "eirl",
    "the",
    "and",
    "of",
    "de",
    "da",
    "do",
    "das",
    "dos",
    "e",
    "y",
    "el",
    "la",
    "los",
    "las",
    "et",
    "des",
    "du",
    "portugal",
    "espanha",
    "spain",
    "france",
    "franca",
    "internacional",
    "nacional",
    "servicos",
    "serviços",
    "comercio",
    "comércio",
    "industria",
    "indústria",
    "gestao",
    "gestão",
    "consultores",
    "consultoria",
    "atividades",
    "atividade",
    "representacoes",
    "representações",
    "distribuicao",
    "distribuição",
    "produtos",
    "equipamentos",
    "tecnologia",
    "tecnologias",
    "solucoes",
    "soluções",
    "sistemas",
    "servicios",
    "gestion",
    "groupe",
    "farmaceutica",
    "farmacêutica",
    "healthcare",
    "installations",
    "travaux",
    "batiment",
    "bâtiment",
}

_ESPACOS = re.compile(r"\s+")
_NAO_ALNUM = re.compile(r"[^a-z0-9]+")
_SO_DIGITOS = re.compile(r"\D+")
_LINK_HREF = re.compile(r"""<link\b[^>]*>""", re.IGNORECASE)
_META_TAG = re.compile(r"""<meta\b[^>]*>""", re.IGNORECASE)
_IMG_TAG = re.compile(r"""<img\b[^>]*>""", re.IGNORECASE)
_ATRIBUTO = re.compile(r"""([a-zA-Z:\-]+)\s*=\s*("([^"]*)"|'([^']*)'|([^\s>]+))""")
_TAG_SCRIPT = re.compile(r"<(script|style)\b.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG_QUALQUER = re.compile(r"<[^>]+>")

_lock = threading.RLock()
_em_curso: Dict[str, threading.Event] = {}
#: Cópia em memória do `perfil.json` (evita re-ler o ficheiro em cada nó do grafo).
_cache_perfis: Dict[str, Any] = {"marca": None, "dados": None}
#: Configuração lida do disco, com a marca de modificação.
_cache_config: Dict[str, Any] = {"marca": None, "valores": None}
#: Instante (monotónico) até ao qual a IA fica de fora, por ser demasiado lenta.
_ia_bloqueada_ate: float = 0.0
#: Instante (monotónico) até ao qual a pesquisa web fica de fora, por não responder.
_pesquisa_bloqueada_ate: float = 0.0
#: Quanto tempo se fica sem tentar a pesquisa depois de uma falha.
PESQUISA_COOLDOWN = 300.0


# ---------------------------------------------------------------------------
# Persistência
# ---------------------------------------------------------------------------
def _ensure_dirs() -> None:
    EMPRESAS_DIR.mkdir(parents=True, exist_ok=True)
    LOGOS_DIR.mkdir(parents=True, exist_ok=True)


def _carregar() -> Dict[str, Any]:
    """Lê o ficheiro de perfis (nunca rebenta por estar corrompido)."""
    with _lock:
        if not PERFIL_FILE.exists():
            return {"version": PERFIL_VERSION, "perfis": {}}
        try:
            marca = PERFIL_FILE.stat().st_mtime_ns
        except OSError:
            marca = 0
        if _cache_perfis["marca"] == marca and _cache_perfis["dados"] is not None:
            return _cache_perfis["dados"]
        try:
            dados = json.loads(PERFIL_FILE.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - cache ilegível não pode parar nada
            logger.warning("perfil.json ilegível (%s); a recomeçar.", exc)
            return {"version": PERFIL_VERSION, "perfis": {}}
        if not isinstance(dados, dict):
            dados = {"version": PERFIL_VERSION, "perfis": {}}
        dados.setdefault("version", PERFIL_VERSION)
        if not isinstance(dados.get("perfis"), dict):
            dados["perfis"] = {}
        _cache_perfis["marca"] = marca
        _cache_perfis["dados"] = dados
        return dados


def _gravar(dados: Dict[str, Any]) -> None:
    _ensure_dirs()
    temporario = PERFIL_FILE.with_suffix(".tmp")
    temporario.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    temporario.replace(PERFIL_FILE)
    try:
        _cache_perfis["marca"] = PERFIL_FILE.stat().st_mtime_ns
    except OSError:
        _cache_perfis["marca"] = 0
    _cache_perfis["dados"] = dados


def config() -> Dict[str, Any]:
    """Configuração do módulo (com os valores por omissão preenchidos)."""
    valores = dict(DEFAULTS)
    marca: Any = None
    if CONFIG_FILE.exists():
        try:
            marca = CONFIG_FILE.stat().st_mtime_ns
        except OSError:
            marca = None
        if _cache_config["marca"] == marca and _cache_config["valores"]:
            return dict(_cache_config["valores"])
        try:
            lido = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(lido, dict):
                valores.update({chave: lido[chave] for chave in DEFAULTS if chave in lido})
        except Exception as exc:  # noqa: BLE001
            logger.warning("config de perfis ilegível: %s", exc)
    _cache_config["marca"] = marca
    _cache_config["valores"] = valores
    return dict(valores)


def guardar_config(novos: Dict[str, Any]) -> Dict[str, Any]:
    """Actualiza a configuração (só as chaves conhecidas)."""
    valores = config()
    for chave in DEFAULTS:
        if chave in novos and novos[chave] is not None:
            valores[chave] = novos[chave]
    valores["dias_validade"] = max(1, int(valores.get("dias_validade") or DIAS_VALIDADE))
    valores["paralelo"] = max(1, min(8, int(valores.get("paralelo") or PARALELO)))
    valores["max_lote"] = max(1, min(40, int(valores.get("max_lote") or MAX_LOTE)))
    valores["ia_timeout"] = max(3.0, min(120.0, float(valores.get("ia_timeout") or IA_TIMEOUT)))
    _ensure_dirs()
    CONFIG_FILE.write_text(json.dumps(valores, ensure_ascii=False, indent=1), encoding="utf-8")
    try:
        _cache_config["marca"] = CONFIG_FILE.stat().st_mtime_ns
    except OSError:
        _cache_config["marca"] = None
    _cache_config["valores"] = valores
    return valores


# ---------------------------------------------------------------------------
# Chaves e nomes
# ---------------------------------------------------------------------------
def chave(nif: Optional[str], nome: Optional[str]) -> str:
    """Chave do perfil: o NIF (só dígitos) ou, sem ele, o nome normalizado."""
    digitos = _SO_DIGITOS.sub("", str(nif or ""))
    if len(digitos) >= 6:
        return digitos
    return f"n:{slug(nome or '')[:60]}" if nome else ""


def _sem_acentos(valor: str) -> str:
    decomposto = unicodedata.normalize("NFKD", valor or "")
    return "".join(c for c in decomposto if not unicodedata.combining(c))


def slug(valor: str) -> str:
    """Texto em minúsculas, sem acentos nem pontuação (espaços simples)."""
    return _ESPACOS.sub(" ", _NAO_ALNUM.sub(" ", _sem_acentos(valor or "").lower())).strip()


def palavras_chave(nome: str) -> List[str]:
    """Palavras que identificam a empresa (sem formas sociais nem genéricas)."""
    vistas: List[str] = []
    for palavra in slug(nome).split(" "):
        if len(palavra) < 3 or palavra in _STOPWORDS:
            continue
        if palavra not in vistas:
            vistas.append(palavra)
    return vistas


def _marca(nome: str) -> str:
    """`JOHNSON & JOHNSON` → `johnsonjohnson` (para comparar com domínios)."""
    return "".join(palavras_chave(nome)) or _NAO_ALNUM.sub("", slug(nome))


def _dominio(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower().removeprefix("www.")
    except Exception:  # noqa: BLE001
        return ""


def _base_do_dominio(url: str) -> str:
    """Domínio sem subdomínio nem sufixo (`www.grupo-foo.pt` → `grupo-foo`)."""
    host = _dominio(url)
    partes = host.split(".")
    if len(partes) >= 2:
        return partes[-2]
    return host


def _e_agregador(url: str) -> bool:
    host = _dominio(url)
    return any(brinde in host for brinde in _AGREGADORES)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def _cabecalhos() -> Dict[str, str]:
    return {
        "User-Agent": BROWSER_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8,es;q=0.7,fr;q=0.6",
    }


def _normalizar_url(url: Optional[str]) -> Optional[str]:
    """URL absoluto e limpo (sem fragmento, sem parâmetros de campanha)."""
    if not url:
        return None
    bruto = str(url).strip()
    if not bruto or bruto.startswith(("data:", "javascript:", "mailto:", "#")):
        return None
    if "//" not in bruto:
        bruto = f"https://{bruto.lstrip('/')}"
    partes = urlsplit(bruto)
    if partes.scheme not in ("http", "https") or not partes.hostname:
        return None
    host = partes.hostname.lower()
    if not re.match(r"^[a-z0-9.\-]+$", host) or "." not in host:
        return None
    if partes.port and partes.port not in (80, 443):
        return urlunsplit((partes.scheme, f"{host}:{partes.port}", partes.path or "/", partes.query, ""))
    return urlunsplit(("https", host, partes.path or "/", partes.query, ""))


def _abrir(url: str, *, timeout: float = TIMEOUT_PAGINA) -> Optional[requests.Response]:
    """GET que segue redirecionamentos e valida o esquema final."""
    try:
        resposta = requests.get(url, headers=_cabecalhos(), timeout=timeout, allow_redirects=True, stream=True)
        if resposta.status_code >= 400:
            resposta.close()
            return None
        return resposta
    except Exception:  # noqa: BLE001 - rede instável é o caso normal
        return None


def _ler_bytes(resposta: requests.Response, maximo: int = MAX_BYTES_HTML) -> bytes:
    pedacos: List[bytes] = []
    total = 0
    try:
        for pedaco in resposta.iter_content(16384):
            if not pedaco:
                continue
            pedacos.append(pedaco)
            total += len(pedaco)
            if total >= maximo:
                break
    except Exception as exc:  # noqa: BLE001 - ligações que caem a meio
        logger.debug("Leitura interrompida: %s", exc)
    return b"".join(pedacos)


def _descodificar(bruto: bytes, cabecalho: str) -> str:
    """Texto do HTML: usa o charset do cabeçalho e, na dúvida, testa latin-1."""
    cabecalho = (cabecalho or "").lower()
    tentativas: List[str] = []
    achado = re.search(r"charset=([\w\-]+)", cabecalho)
    if achado:
        tentativas.append(achado.group(1))
    achado_html = re.search(rb"charset=['\"]?([\w\-]+)", bruto[:4096], re.IGNORECASE)
    if achado_html:
        tentativas.append(achado_html.group(1).decode("ascii", errors="ignore"))
    tentativas += ["utf-8", "cp1252", "latin-1"]
    for codificacao in tentativas:
        try:
            texto = bruto.decode(codificacao)
        except (LookupError, UnicodeDecodeError):
            continue
        if texto.count("\ufffd") <= max(2, len(texto) // 2000):
            return texto
    return bruto.decode("utf-8", errors="replace")


def _ler_texto(resposta: requests.Response, maximo: int = MAX_BYTES_HTML) -> str:
    return _descodificar(_ler_bytes(resposta, maximo), resposta.headers.get("content-type") or "")


def _texto_visivel(html: str) -> str:
    return _TAG_QUALQUER.sub(" ", _TAG_SCRIPT.sub(" ", html or ""))


def _atributos(tag: str) -> Dict[str, str]:
    saida: Dict[str, str] = {}
    for achado in _ATRIBUTO.finditer(tag):
        valor = achado.group(3) or achado.group(4) or achado.group(5) or ""
        saida[achado.group(1).lower()] = valor.strip()
    return saida


# ---------------------------------------------------------------------------
# Candidatos: pesquisa web e heurística
# ---------------------------------------------------------------------------
def _pesquisa_web(pergunta: str, quantos: int = 8) -> List[Dict[str, str]]:
    """Pesquisa no mécânico web da plataforma (SearXNG e afins).

    Se o motor não responder, fica de fora uns minutos: sem isto, cada empresa
    pagava três consultas a expirar (45 s) antes de se perceber que a pesquisa
    estava em baixo.
    """
    global _pesquisa_bloqueada_ate
    if time.monotonic() < _pesquisa_bloqueada_ate:
        return []
    try:
        from api.tools import web_search
    except Exception:  # noqa: BLE001
        return []
    try:
        resultados = web_search(pergunta, max_results=quantos) or []
    except Exception as exc:  # noqa: BLE001
        logger.info("Pesquisa web falhou (%s): %s", pergunta, exc)
        _pesquisa_bloqueada_ate = time.monotonic() + PESQUISA_COOLDOWN
        return []
    limpos: List[Dict[str, str]] = []
    for item in resultados:
        if not isinstance(item, dict) or item.get("error"):
            continue
        url = _normalizar_url(item.get("href") or item.get("url"))
        if not url:
            continue
        limpos.append(
            {
                "url": url,
                "titulo": str(item.get("title") or "").strip(),
                "resumo": str(item.get("body") or item.get("snippet") or "").strip(),
                "origem": "pesquisa",
            }
        )
    return limpos


def _dominios_da_pesquisa(nome: str, pais: str, nif: Optional[str]) -> List[Dict[str, str]]:
    """Resultados da pesquisa colapsados por domínio (o melhor de cada site)."""
    idioma = (PAISES.get(pais) or {}).get("idioma", "pt")
    perguntas = [f'"{nome}" site oficial', f'{nome} {idioma} site oficial empresa']
    vistos: Dict[str, Dict[str, str]] = {}
    for indice, pergunta in enumerate(perguntas):
        if indice and len(vistos) >= 5:
            break
        for item in _pesquisa_web(pergunta, 8):
            host = _dominio(item["url"])
            if not host:
                continue
            raiz = f"{urlsplit(item['url']).scheme}://{host}"
            anterior = vistos.get(host)
            if anterior is None:
                vistos[host] = {**item, "url": raiz, "url_completo": item["url"]}
            elif nif and nif in (item["resumo"] + item["titulo"]) and nif not in (
                anterior["resumo"] + anterior["titulo"]
            ):
                vistos[host] = {**item, "url": raiz, "url_completo": item["url"]}
        if len(vistos) >= 8:
            break
    # Agregadores ficam no fim: ainda servem de pista para o NIF.
    ordenados = sorted(vistos.values(), key=lambda item: _e_agregador(item["url"]))
    return ordenados[:10]


def _candidatos_heuristica(nome: str, pais: str) -> List[Dict[str, str]]:
    """Domínios prováveis a partir do nome.

    A ordem importa: a primeira palavra é, de longe, o melhor palpite
    (`ROCHE FARMACÊUTICA E QUÍMICA` → `roche.pt`), seguida do nome todo sem
    espaços e com hífenes, e por fim as iniciais (`MERCK SHARP & DOHME` → `msd`).
    O domínio sem `www` vem primeiro porque é o que os sites institucionais
    costumam usar (o `www` pode nem existir).
    """
    palavras = palavras_chave(nome)
    if not palavras:
        return []
    bases: List[str] = [palavras[0]]
    if len(palavras) >= 2:
        bases.append("".join(palavras[:3]))
        bases.append("-".join(palavras[:3]))
    if len(palavras) >= 3:
        bases.append("".join(p[0] for p in palavras[:4]))
    tld = (PAISES.get(pais) or {}).get("tld", "pt")
    sufixos = [tld] if tld == "com" else [tld, "com"]
    saida: List[Dict[str, str]] = []
    vistos: set[str] = set()
    for base in bases:
        base = base.strip("-")
        if len(base) < 3 or base in vistos:
            continue
        vistos.add(base)
        for sufixo in sufixos:
            saida.append({"url": f"https://{base}.{sufixo}", "titulo": "", "resumo": "", "origem": "heuristica"})
        for sufixo in sufixos:
            saida.append({"url": f"https://www.{base}.{sufixo}", "titulo": "", "resumo": "", "origem": "heuristica"})
    return saida[:8]


# ---------------------------------------------------------------------------
# Pontuação de um candidato
# ---------------------------------------------------------------------------
#: Códigos de idioma/país que aparecem em caminhos de site (`/pt-pt/`, `/br/`).
_SEGMENTOS_IDIOMA = {
    "pt",
    "pt-pt",
    "ptpt",
    "portugal",
    "es",
    "es-es",
    "espana",
    "esp",
    "br",
    "brasil",
    "pt-br",
    "en",
    "en-us",
    "en-gb",
    "uk",
    "fr",
    "fr-fr",
    "france",
    "de",
    "it",
    "nl",
    "mx",
    "ar",
    "cl",
    "co",
    "us",
}


def _sinal_pais(url: str, html: str, pais: str) -> float:
    """Bónus/penalização por o site estar na variante do país pedido.

    Sem isto, um hub brasileiro (`…/pt-br`) empatava com a página portuguesa da
    mesma empresa.
    """
    info = PAISES.get(pais) or PAISES["pt"]
    tld = info["tld"]
    idioma = info["idioma"]
    host = _dominio(url)
    caminho = urlsplit(url).path.lower()
    segmentos = {s for s in re.split(r"[/_\-.]+", caminho) if s}
    pontos = 0.0
    if host.endswith(f".{tld}"):
        pontos += 0.12
    if "portugal" in caminho:
        pontos += 0.1
    elif f"{idioma}-{idioma}" in caminho:
        pontos += 0.1
    elif idioma in segmentos:
        pontos += 0.05
    # Variante de outro país (ex.: `/pt-br`, `/br`, `/es`) desconta.
    alheios = (_SEGMENTOS_IDIOMA - {idioma, f"{idioma}-{idioma}", tld}) & segmentos
    if alheios:
        pontos -= 0.14
    achado_lang = re.search(r"<html[^>]*lang=[\"']?([\w\-]+)", html or "", re.IGNORECASE)
    if achado_lang:
        lang = achado_lang.group(1).lower()
        if lang.startswith(idioma) and len(lang) <= 5:
            pontos += 0.08
        elif lang.startswith(idioma):
            pontos += 0.02
        elif not lang.startswith(idioma):
            pontos -= 0.06
    return pontos


#: Sinais de que o domínio não tem site em funcionamento (hospedagem suspensa,
#: domínio à venda, parqueado). Sem isto, `unidade.pt/cgi-sys/suspendedpage.cgi`
#: foi aceite como site de uma unidade de saúde.
_SINAIS_PAGINA_MORTA = (
    "suspendedpage",
    "cgi-sys",
    "account suspended",
    "conta suspensa",
    "this site is temporarily unavailable",
    "site em manutencao",
    "domain for sale",
    "this domain is for sale",
    "dominio a venda",
    "domain parking",
    "parked by",
    "buy this domain",
    "default web site page",
    "apache2 debian default page",
    "welcome to nginx",
    "index of /",
    "under construction",
    "em construcao",
)


def _pagina_morta(url: str, html: str, texto: str) -> bool:
    """A página existe mas não tem site lá dentro (domínio parqueado/suspenso)."""
    alvo = f"{url.lower()} {texto[:1500]}"
    if any(sinal in alvo for sinal in _SINAIS_PAGINA_MORTA):
        return True
    # Páginas de hospedagem costumam ser minúsculas e não ter marca nenhuma.
    return len(texto) < 400 and not re.search(r"<h1", html or "", re.IGNORECASE)


def _pontuar(url: str, html: str, nome: str, nif: Optional[str], *, origem: str, pais: str = "pt") -> float:
    """Confiança (0 a 1) de que `url` é o site oficial da empresa.

    A evidência mais forte é o **NIF na página**; a seguir vem o **nome no
    domínio/título**. O nome que aparece só no corpo da página vale pouco: é o
    caso típico das associações, diretórios e notícias que falam da empresa —
    foi assim que o site de uma associação (`apecs.pt`) ganhou à Janssen e um
    site brasileiro (`axyo.com.br`) ganhou à Roche. Sem uma segunda prova (título
    ou domínio), o nome no texto não conta.
    """
    if not html:
        return 0.0
    texto = slug(_texto_visivel(html))
    titulo = slug(_titulo_do_html(html))
    pontos = 0.0
    digitos_nif = _SO_DIGITOS.sub("", str(nif or ""))
    nif_na_pagina = False
    if len(digitos_nif) >= 6:
        compacto = _SO_DIGITOS.sub(" ", html)
        if digitos_nif in compacto:
            pontos += 0.55
            nif_na_pagina = True
        elif digitos_nif[:6] in compacto:
            pontos += 0.15
    palavras = palavras_chave(nome)
    no_titulo = 0
    base = _base_do_dominio(url)
    marca = _marca(nome)
    # Quanto o domínio se parece com o nome (0 a 1) — a prova estrutural.
    parecenca = _parecenca(base, palavras)
    if palavras:
        no_titulo = sum(1 for p in palavras if p in titulo)
        no_texto = sum(1 for p in palavras if p in texto)
        if no_titulo >= max(1, len(palavras) - 1):
            pontos += 0.35
        elif no_titulo >= 1:
            pontos += 0.22
        elif no_texto == len(palavras):
            # Nome todo no texto, mas fora do título e do domínio: só conta se o
            # domínio der alguma confirmação (senão seria um terceiro a falar da
            # empresa).
            pontos += 0.22 if parecenca else 0.02
        elif no_texto >= max(1, len(palavras) // 2):
            pontos += 0.12 if parecenca else 0.0
        if no_titulo == 0 and not parecenca:
            # Página de terceiros que apenas menciona a empresa.
            pontos -= 0.12
    if base and marca:
        if base == marca:
            pontos += 0.35
        elif marca.startswith(base) or base.startswith(marca) or marca in base or base in marca:
            pontos += 0.24
        else:
            pontos += 0.22 * parecenca
    if _e_agregador(url):
        pontos -= 0.6
    if _pagina_morta(url, html, texto):
        # Domínio estacionado, conta suspensa ou página de venda de domínio.
        pontos -= 0.9
    pontos += _sinal_pais(url, html, pais)
    if origem == "heuristica":
        pontos -= 0.03
    # Um site que só tem "resultados 1 de 10" ou está em construção não serve.
    if len(texto) < 120:
        pontos -= 0.15
    # Um site que só tem "resultados 1 de 10" ou está em construção não serve.
    if len(texto) < 120:
        pontos -= 0.15
    # Prova estrutural: o domínio tem de vir do nome, ou o nome completo tem de
    # estar no título, ou o NIF tem de estar na página. Sem nenhuma das três, o
    # teto fica abaixo do limiar de aceitação — é o que trava as páginas de
    # terceiros que apenas mencionam a empresa (associações, notícias,
    # diretórios que não estão na lista de agregadores).
    corroborado = bool(parecenca) or (bool(palavras) and no_titulo >= len(palavras)) or nif_na_pagina
    if not corroborado:
        pontos = min(pontos, 0.25)
    return max(0.0, min(1.0, pontos))


def _parecenca(base: str, palavras: Sequence[str]) -> float:
    """0 a 1: quanto do domínio (sem hífens) vem das palavras do nome.

    Um nome inteiro dentro do domínio (`roche`, `gilead`) ou as **iniciais** das
    palavras (`Merck Sharp & Dohme` → `msd`) são prova forte; só o arranque do
    nome é prova fraca.
    """
    if not base or not palavras:
        return 0.0
    marca = "".join(palavras)
    iniciais = "".join(p[0] for p in palavras if p)
    if base == iniciais:
        return 1.0
    if len(iniciais) >= 2 and base.startswith(iniciais):
        # `MSD` dentro de `msdsaude`, `EDP` dentro de `edpcomercial`.
        return 0.8
    for palavra in palavras:
        if len(palavra) >= 4 and palavra in base:
            return 1.0
    if marca[:3] and marca[:3] in base:
        return 0.35
    return 0.0


def _titulo_do_html(html: str) -> str:
    achado = re.search(r"<title[^>]*>(.*?)</title>", html or "", re.IGNORECASE | re.DOTALL)
    return achado.group(1) if achado else ""


# ---------------------------------------------------------------------------
# IA: escolher entre candidatos
# ---------------------------------------------------------------------------
def _pedir_ia(
    nome: str,
    nif: Optional[str],
    pais: str,
    candidatos: Sequence[Dict[str, Any]],
    *,
    user_id: Optional[str] = None,
    provider: Optional[str] = None,
    modelo: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Pede ao modelo da plataforma o site mais provável (e a confiança)."""
    global _ia_bloqueada_ate
    if time.monotonic() < _ia_bloqueada_ate:
        return None
    try:
        from api import scraper_ai

        provider_id, spec, modelo_id, chave = scraper_ai.pick_provider(user_id, provider, modelo)
    except Exception as exc:  # noqa: BLE001
        logger.info("Sem fornecedor de IA para identificar o site: %s", exc)
        return None
    if not provider_id or not spec:
        return None
    # Um modelo local pode estar configurado mas não instalado: sem isto, o
    # pedido era gasto a descobrir que o modelo não existe.
    if provider_id == "ollama":
        especifico = getattr(scraper_ai, "_resolve_model", None)
        if callable(especifico):
            try:
                modelo_id = especifico(modelo_id or "") or modelo_id
            except Exception:  # noqa: BLE001
                pass

    rotulo = (PAISES.get(pais) or {}).get("label", "Portugal")
    linhas = []
    for indice, item in enumerate(candidatos, start=1):
        linhas.append(
            f"{indice}. {item.get('url')}\n"
            f"   título: {item.get('titulo') or '—'}\n"
            f"   resumo: {(item.get('resumo') or '—')[:220]}\n"
            f"   sinal interno: {item.get('motivo') or 'sem sinal'}"
        )
    prompt = (
        "Identifica o SITE OFICIAL de uma empresa a partir dos candidatos abaixo.\n\n"
        f"Empresa: {nome}\n"
        f"Identificador fiscal: {nif or 'desconhecido'}\n"
        f"País: {rotulo}\n\n"
        "Candidatos (por ordem de plausibilidade calculada):\n" + "\n".join(linhas) + "\n\n"
        "Regras:\n"
        "- O site oficial é o da própria empresa, não diretórios (Racius, eInforma, Pappers…), "
        "redes sociais, imprensa ou marketplaces.\n"
        "- Se nenhum candidato for credível, usa `null`.\n"
        "- Podes indicar um URL diferente dos candidatos se tiveres a certeza.\n\n"
        'Responde APENAS com JSON: {"site": "<url ou null>", "confianca": 0.0, "motivo": "curto"}'
    )

    try:
        resposta = _perguntar_modelo(
            provider_id,
            spec,
            modelo_id or spec.get("default_model") or "",
            prompt,
            chave,
        )
    except FuturesTimeout as exc:
        _ia_bloqueada_ate = time.monotonic() + IA_COOLDOWN
        logger.info("IA lenta (%s); a IA fica de lado durante %.0f min.", exc, IA_COOLDOWN / 60)
        return None
    except TimeoutError as exc:
        _ia_bloqueada_ate = time.monotonic() + IA_COOLDOWN
        logger.info("IA excedeu o tempo para %s (%s); a IA fica de lado %.0f min.", nome, exc, IA_COOLDOWN / 60)
        return None
    except Exception as exc:  # noqa: BLE001
        _ia_bloqueada_ate = time.monotonic() + IA_COOLDOWN
        logger.info("IA não respondeu para %s: %s", nome, exc)
        return None

    dados = _json_da_resposta(resposta)
    if not dados:
        return None
    site = _normalizar_url(dados.get("site")) if dados.get("site") else None
    try:
        confianca = float(dados.get("confianca") or 0.0)
    except (TypeError, ValueError):
        confianca = 0.0
    return {
        "site": site,
        "confianca": max(0.0, min(1.0, confianca)),
        "motivo": str(dados.get("motivo") or "").strip()[:300],
        "provider": provider_id,
        "modelo": modelo_id,
    }


def _perguntar_modelo(provider: str, spec: Dict[str, Any], modelo: str, prompt: str, chave: Optional[str]) -> str:
    """Chamada síncrona a um modelo (`cloud_chat` é assíncrono), com teto de tempo.

    O `ThreadPoolExecutor` é criado **fora** de um `with` de propósito: um
    `with` esperaria pelo fim da chamada e o teto de tempo não serviria para
    nada. Assim, um modelo local lento é abandonado e a resolução continua com a
    pontuação calculada por HTTP.
    """
    from api import cloud_chat

    async def correr() -> str:
        return await cloud_chat.complete_answer(
            provider=provider,
            spec=spec,
            model=modelo,
            messages=[{"role": "user", "content": prompt}],
            api_key=chave,
            temperature=0.0,
            max_tokens=400,
        )

    def executar() -> str:
        return asyncio.run(correr())

    limite = float(config().get("ia_timeout") or IA_TIMEOUT)
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="perfil-ia")
    futuro = executor.submit(executar)
    try:
        return futuro.result(timeout=limite)
    except FuturesTimeout as exc:
        futuro.cancel()
        raise TimeoutError(f"o modelo não respondeu em {limite:.0f}s") from exc
    finally:
        executor.shutdown(wait=False)


def _json_da_resposta(texto: str) -> Optional[Dict[str, Any]]:
    if not texto:
        return None
    bruto = texto.strip()
    if bruto.startswith("```"):
        bruto = re.sub(r"^```[a-zA-Z]*\s*", "", bruto)
        bruto = re.sub(r"```\s*$", "", bruto).strip()
    try:
        dados = json.loads(bruto)
        return dados if isinstance(dados, dict) else None
    except Exception:  # noqa: BLE001
        achado = re.search(r"\{.*\}", bruto, re.DOTALL)
        if not achado:
            return None
        try:
            dados = json.loads(achado.group(0))
            return dados if isinstance(dados, dict) else None
        except Exception:  # noqa: BLE001
            return None


# ---------------------------------------------------------------------------
# Logótipo
# ---------------------------------------------------------------------------
def _candidatos_logo(html: str, base_url: str) -> List[Tuple[str, int]]:
    """URLs de imagem plausíveis, ordenados por preferência (e o porquê)."""
    itens: List[Tuple[str, int, str]] = []

    def juntar(valor: Optional[str], prioridade: int, motivo: str) -> None:
        url = _normalizar_url(urljoin(base_url, str(valor or "").strip()))
        if url:
            itens.append((url, prioridade, motivo))

    for tag in _LINK_HREF.findall(html or ""):
        atributos = _atributos(tag)
        rel = (atributos.get("rel") or "").lower()
        tipo = (atributos.get("type") or "").lower()
        href = atributos.get("href") or ""
        if "icon" not in rel:
            continue
        prioridade = 70
        if "apple-touch-icon" in rel:
            prioridade = 85
        if "logo" in href.lower():
            prioridade += 12
        if "svg" in tipo or href.lower().endswith(".svg"):
            prioridade += 8
        tamanho = atributos.get("sizes") or ""
        maior = max([int(numero) for numero in re.findall(r"(\d+)", tamanho)] or [0])
        if maior:
            prioridade += min(20, maior // 10)
        juntar(href, prioridade, f"rel={rel}")

    for tag in _META_TAG.findall(html or ""):
        atributos = _atributos(tag)
        chave = (atributos.get("property") or atributos.get("name") or "").lower()
        conteudo = atributos.get("content") or ""
        if chave in ("og:image", "og:image:secure_url", "twitter:image", "twitter:image:src"):
            prioridade = 55 if "logo" in conteudo.lower() else 40
            juntar(conteudo, prioridade, chave)
        if chave in ("og:logo", "logo"):
            juntar(conteudo, 80, chave)

    corpo = html or ""
    corte = max(0, int(len(corpo) * 0.35))
    for achado in _IMG_TAG.finditer(corpo):
        tag = achado.group(0)
        atributos = _atributos(tag)
        fonte = atributos.get("src") or atributos.get("data-src") or atributos.get("data-lazy-src") or ""
        pista = " ".join(
            [
                fonte,
                atributos.get("class") or "",
                atributos.get("id") or "",
                atributos.get("alt") or "",
            ]
        ).lower()
        if not any(termo in pista for termo in ("logo", "brand", "marca")):
            continue
        if any(termo in pista for termo in ("sprite", "banner", "placeholder")):
            continue
        prioridade = 75
        if achado.start() <= corte:
            prioridade += 8
        if "footer" in pista:
            prioridade -= 20
        if not atributos.get("class") and not atributos.get("id"):
            prioridade -= 6
        juntar(fonte, prioridade, "img com logo na descrição")

    juntar(urljoin(base_url, "/favicon.ico"), 25, "favicon.ico")

    # Ordena por prioridade e remove repetições.
    vistos: set[str] = set()
    saida: List[Tuple[str, int]] = []
    for url, prioridade, _motivo in sorted(itens, key=lambda item: -item[1]):
        if url in vistos:
            continue
        vistos.add(url)
        saida.append((url, prioridade))
    return saida[:12]


def _normalizar_logo(dados: bytes) -> Optional[bytes]:
    """Converte qualquer imagem num PNG quadrado 256×256 (fundo transparente)."""
    try:
        from PIL import Image

        imagem = Image.open(io.BytesIO(dados))
        imagem.load()
        imagem = imagem.convert("RGBA")
    except Exception:  # noqa: BLE001 - formato exótico ou corrompido
        return None
    if imagem.width < 24 or imagem.height < 24:
        return None
    caixa = imagem.getbbox()
    if caixa:
        imagem = imagem.crop(caixa)
    if imagem.width < 16 or imagem.height < 16:
        return None
    lado = 256
    escala = lado / max(imagem.width, imagem.height)
    if escala < 1:
        reamostragem = getattr(Image, "Resampling", Image).LANCZOS
        imagem = imagem.resize((max(1, round(imagem.width * escala)), max(1, round(imagem.height * escala))), reamostragem)
    tela = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
    tela.paste(imagem, ((lado - imagem.width) // 2, (lado - imagem.height) // 2), imagem)
    memoria = io.BytesIO()
    tela.save(memoria, "PNG", optimize=True)
    return memoria.getvalue()


def _guardar_logo(chave_perfil: str, dados: bytes, url: str) -> Dict[str, Any]:
    """Guarda o logótipo (PNG normalizado ou SVG cru) e devolve os metadados."""
    _ensure_dirs()
    extensao = "png"
    conteudo = dados
    if dados.lstrip()[:5].lower() in (b"<?xml", b"<svg ") or b"<svg" in dados[:400].lower():
        extensao = "svg"
    else:
        normalizado = _normalizar_logo(dados)
        if not normalizado:
            return {}
        conteudo = normalizado
    for antigo in LOGOS_DIR.glob(f"{chave_perfil}.*"):
        try:
            antigo.unlink()
        except OSError:
            pass
    caminho = LOGOS_DIR / f"{chave_perfil}.{extensao}"
    caminho.write_bytes(conteudo)
    return {
        "logo": f"{chave_perfil}.{extensao}",
        "logo_fonte": url,
        "logo_bytes": len(conteudo),
        "logo_tipo": extensao,
    }


def caminho_logo(chave_perfil: str) -> Optional[Path]:
    """Ficheiro de logótipo existente para esta chave, se houver."""
    if not chave_perfil:
        return None
    for extensao in ("png", "svg", "webp", "jpg", "jpeg", "gif", "ico"):
        caminho = LOGOS_DIR / f"{chave_perfil}.{extensao}"
        if caminho.exists() and caminho.stat().st_size > 64:
            return caminho
    return None


def _obter_logo(site: str, chave_perfil: str, *, html: Optional[str] = None) -> Dict[str, Any]:
    """Descarrega e guarda o melhor logótipo encontrado na home page.

    `html` permite reutilizar a página já lida na validação do candidato —
    poupa um pedido por empresa.
    """
    if html is None:
        resposta = _abrir(site)
        if not resposta:
            return {}
        try:
            html = _ler_texto(resposta)
        finally:
            try:
                resposta.close()
            except Exception:  # noqa: BLE001
                pass
    if not html:
        return {}
    for url, _prioridade in _candidatos_logo(html, site):
        imagem = _abrir(url, timeout=TIMEOUT_IMAGEM)
        if not imagem:
            continue
        try:
            tipo = (imagem.headers.get("content-type") or "").lower()
            if tipo and not (tipo.startswith("image/") or "svg" in tipo or "octet-stream" in tipo):
                continue
            dados = _ler_bytes(imagem, MAX_BYTES_IMAGEM)
        except Exception:  # noqa: BLE001
            dados = b""
        finally:
            try:
                imagem.close()
            except Exception:  # noqa: BLE001
                pass
        if not dados or len(dados) < 200:
            continue
        guardado = _guardar_logo(chave_perfil, dados, url)
        if guardado:
            return guardado
    return {}


# ---------------------------------------------------------------------------
# Resolução completa
# ---------------------------------------------------------------------------
def _avaliar_um(candidato: Dict[str, str], nome: str, nif: Optional[str], pais: str = "pt") -> Optional[Dict[str, Any]]:
    """Abre um candidato, pontua-o e devolve o resultado (ou `None`)."""
    resposta = _abrir(candidato["url"])
    if not resposta:
        return None
    try:
        tipo = (resposta.headers.get("content-type") or "").lower()
        if tipo and "html" not in tipo and "xml" not in tipo:
            return None
        html = _ler_texto(resposta)
        final = _normalizar_url(resposta.url) or candidato["url"]
    finally:
        try:
            resposta.close()
        except Exception:  # noqa: BLE001
            pass
    if len(html) < 200:
        return None
    pontos = _pontuar(final, html, nome, nif, origem=candidato.get("origem") or "pesquisa", pais=pais)
    return {
        **candidato,
        "url": final,
        "titulo": candidato.get("titulo") or _titulo_do_html(html)[:140],
        "pontos": round(pontos, 3),
        "motivo": _explicar(final, html, nome, nif),
        # Guardado só para reaproveitar a página na hora de tirar o logótipo;
        # nunca é escrito no ficheiro de perfis.
        "_html": html,
    }


def _avaliar_candidatos(
    candidatos: Sequence[Dict[str, str]],
    nome: str,
    nif: Optional[str],
    *,
    limite: int = 5,
    paralelo: int = 3,
    pais: str = "pt",
) -> List[Dict[str, Any]]:
    """Abre os candidatos **em paralelo**, pontua-os e devolve os viáveis por ordem."""
    alvo = [item for item in candidatos[:limite] if item.get("url")]
    if not alvo:
        return []
    trabalhadores = max(1, min(paralelo, len(alvo)))
    if trabalhadores == 1:
        avaliados = [resultado for item in alvo if (resultado := _avaliar_um(item, nome, nif, pais))]
    else:
        with ThreadPoolExecutor(max_workers=trabalhadores) as executor:
            futuros = [executor.submit(_avaliar_um, item, nome, nif, pais) for item in alvo]
            avaliados = [resultado for futuro in futuros if (resultado := futuro.result())]
    avaliados.sort(key=lambda item: -item["pontos"])
    return avaliados


def _explicar(url: str, html: str, nome: str, nif: Optional[str]) -> str:
    """Razões legíveis para a pontuação (aparece na interface do admin)."""
    razoes: List[str] = []
    compacto = _SO_DIGITOS.sub(" ", html or "")
    digitos = _SO_DIGITOS.sub("", str(nif or ""))
    if len(digitos) >= 6 and digitos in compacto:
        razoes.append("NIF na página")
    titulo = slug(_titulo_do_html(html))
    palavras = palavras_chave(nome)
    encontradas = [p for p in palavras if p in titulo]
    if encontradas:
        razoes.append("nome no título: " + ", ".join(encontradas[:3]))
    elif palavras:
        texto = slug(_texto_visivel(html))
        no_texto = [p for p in palavras if p in texto]
        if no_texto:
            razoes.append("nome no texto: " + ", ".join(no_texto[:3]))
    base = _base_do_dominio(url)
    if base and any(p in base for p in palavras):
        razoes.append("domínio com o nome")
    if _e_agregador(url):
        razoes.append("diretório/agregador")
    return "; ".join(razoes) or "sem sinais"


def _processar(
    nome: str,
    nif: Optional[str],
    pais: str,
    *,
    usar_ia: bool,
    usar_pesquisa: bool,
    forcar: bool,
    user_id: Optional[str],
    provider: Optional[str],
    modelo: Optional[str],
    com_logo: bool,
) -> Dict[str, Any]:
    """Resolve site e logótipo de **uma** empresa (sem cache)."""
    cfg = config()
    da_pesquisa: List[Dict[str, str]] = []
    if usar_pesquisa and cfg.get("usar_pesquisa", True):
        da_pesquisa = _dominios_da_pesquisa(nome, pais, nif)
    # A heurística do nome entra **sempre** e com dois lugares reservados: os
    # resultados da pesquisa podem ser todos de terceiros que falam da empresa
    # (associações, notícias, diretórios que não estão na lista de agregadores)
    # e, sem isto, nunca chegava a ser testado o domínio óbvio — foi assim que a
    # Roche ficou com um site brasileiro que a menciona. O total de páginas
    # abertas por empresa mantém-se.
    candidatos = [
        *[item for item in da_pesquisa if not _e_agregador(item["url"])][:2],
        *_candidatos_heuristica(nome, pais)[:3],
        *da_pesquisa[:3],
    ]
    unicos: List[Dict[str, str]] = []
    vistos: set[str] = set()
    for item in candidatos:
        if item["url"] in vistos:
            continue
        vistos.add(item["url"])
        unicos.append(item)
    candidatos = unicos

    avaliados = _avaliar_candidatos(candidatos, nome, nif, pais=pais)

    escolhido: Optional[Dict[str, Any]] = avaliados[0] if avaliados else None
    ia: Optional[Dict[str, Any]] = None
    # A IA entra quando a decisão não é óbvia (mais do que um candidato viável
    # ou o melhor ainda é fraco) — não vale a pena gastar tokens no caso fácil.
    plausiveis = [item for item in avaliados if item["pontos"] >= 0.3]
    precisa_ia = (not escolhido) or (escolhido["pontos"] < 0.55) or (len(plausiveis) >= 2)
    if usar_ia and cfg.get("usar_ia", True) and precisa_ia and (avaliados or candidatos):
        ia = _pedir_ia(nome, nif, pais, avaliados[:5] or candidatos[:5], user_id=user_id, provider=provider, modelo=modelo)
        if ia and ia.get("site"):
            iguais = next((item for item in avaliados if item["url"] == ia["site"]), None)
            if iguais:
                ia["pontos"] = iguais["pontos"]
            if ia["confianca"] >= 0.5 and (not escolhido or escolhido["pontos"] < 0.75 or iguais is None):
                if iguais is None:
                    # O modelo propôs outro URL: valida-o como qualquer candidato.
                    extra = _avaliar_candidatos(
                        [{"url": ia["site"], "titulo": "", "resumo": "", "origem": "ia"}], nome, nif, limite=1, pais=pais
                    )
                    if extra and extra[0]["pontos"] >= 0.2:
                        escolhido = extra[0]
                        escolhido["origem"] = "ia"
                    elif escolhido is None:
                        escolhido = {"url": ia["site"], "titulo": "", "resumo": "", "pontos": 0.0, "origem": "ia", "motivo": "proposta da IA"}
                else:
                    escolhido = iguais
                    escolhido["origem"] = "ia"

    # Só se aceita um site com alguma evidência: evitamos marcar o site errado.
    if escolhido and escolhido["pontos"] < 0.3 and not (ia and ia.get("confianca", 0) >= 0.7):
        escolhido = None

    perfil: Dict[str, Any] = {
        "nome": nome,
        "nif": nif,
        "pais": pais,
        "site": escolhido["url"] if escolhido else None,
        "dominio": _dominio(escolhido["url"]) if escolhido else None,
        "confianca": round(escolhido["pontos"], 3) if escolhido else 0.0,
        "motivo": escolhido.get("motivo") if escolhido else (ia.get("motivo") if ia else ""),
        "origem": escolhido.get("origem") if escolhido else ("pesquisa" if candidatos else "sem_candidatos"),
        "candidatos": [
            {"url": item["url"], "titulo": item.get("titulo", "")[:120], "pontos": item["pontos"], "motivo": item.get("motivo", "")}
            for item in avaliados[:5]
        ],
        "ia": ({"provider": ia["provider"], "modelo": ia["modelo"], "confianca": ia["confianca"], "motivo": ia["motivo"]} if ia else None),
        "atualizado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if escolhido and com_logo:
        # Reaproveita a página já lida na validação: poupa um pedido por empresa.
        perfil.update(_obter_logo(escolhido["url"], chave(nif, nome), html=escolhido.get("_html")))
    perfil.pop("_html", None)
    return perfil


def _valido(perfil: Dict[str, Any]) -> bool:
    """O perfil em cache ainda serve? (site ok e dentro da validade)"""
    if not perfil:
        return False
    if not perfil.get("atualizado"):
        return False
    dias = int(config().get("dias_validade") or DIAS_VALIDADE)
    try:
        quando = datetime.fromisoformat(str(perfil["atualizado"]).replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001
        return False
    if quando.tzinfo is None:
        quando = quando.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) - quando > timedelta(days=dias):
        return False
    if not perfil.get("site"):
        return False
    # Sem logótipo guardado, ainda vale a pena tentar outra vez mais tarde.
    if not perfil.get("logo") and not caminho_logo(chave(perfil.get("nif"), perfil.get("nome"))):
        try:
            quando_falha = datetime.fromisoformat(str(perfil.get("logo_tentado") or perfil["atualizado"]))
            if datetime.now(timezone.utc) - quando_falha < timedelta(days=7):
                return True
        except Exception:  # noqa: BLE001
            return True
        return False
    return True


def guardar_perfil(perfil: Dict[str, Any]) -> Dict[str, Any]:
    """Escreve um perfil no ficheiro de cache."""
    if not perfil:
        return {}
    chave_perfil = chave(perfil.get("nif"), perfil.get("nome"))
    if not chave_perfil:
        return perfil
    with _lock:
        dados = _carregar()
        anterior = dados["perfis"].get(chave_perfil) or {}
        if anterior.get("site") and anterior.get("site") != perfil.get("site"):
            # Mudou de site: o logótipo antigo deixou de fazer sentido.
            for antigo in LOGOS_DIR.glob(f"{chave_perfil}.*"):
                try:
                    antigo.unlink()
                except OSError:
                    pass
        elif not perfil.get("logo") and anterior.get("logo"):
            perfil.setdefault("logo", anterior["logo"])
        dados["perfis"][chave_perfil] = perfil
        _gravar(dados)
    return perfil


def obter(nif: Optional[str], nome: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Perfil em cache (sem tocar na rede)."""
    chave_perfil = chave(nif, nome)
    if not chave_perfil:
        return None
    with _lock:
        perfil = (_carregar()["perfis"] or {}).get(chave_perfil)
    if perfil is None and not chave_perfil.startswith("n:") and nome:
        # Guardado pelo nome mas pedido pelo NIF (ou o contrário).
        with _lock:
            perfil = (_carregar()["perfis"] or {}).get(chave(None, nome))
    if not perfil:
        return None
    return _publico(perfil, chave_perfil)


def _publico(perfil: Dict[str, Any], chave_perfil: str) -> Dict[str, Any]:
    """Forma devolvida à interface (sem caminhos de ficheiro internos)."""
    tem_logo = bool(caminho_logo(chave_perfil))
    return {
        "nif": perfil.get("nif"),
        "nome": perfil.get("nome"),
        "pais": perfil.get("pais"),
        "site": perfil.get("site"),
        "dominio": perfil.get("dominio"),
        "confianca": perfil.get("confianca") or 0.0,
        "origem": perfil.get("origem"),
        "motivo": perfil.get("motivo"),
        "tem_logo": tem_logo,
        "logo_url": f"/api/empresas/perfil/{chave_perfil}/logo" if tem_logo else None,
        "atualizado": perfil.get("atualizado"),
        "candidatos": perfil.get("candidatos") or [],
        "ia": perfil.get("ia"),
        "em_cache": True,
    }


def resolver(
    nome: str,
    nif: Optional[str] = None,
    pais: str = "pt",
    *,
    usar_ia: bool = True,
    forcar: bool = False,
    user_id: Optional[str] = None,
    provider: Optional[str] = None,
    modelo: Optional[str] = None,
    com_logo: bool = True,
) -> Dict[str, Any]:
    """Resolve (ou lê da cache) o site e o logótipo de uma empresa."""
    pais = (pais or "pt").lower()[:2]
    if pais not in PAISES:
        pais = "pt"
    chave_perfil = chave(nif, nome)
    if not chave_perfil:
        return {"nif": nif, "nome": nome, "pais": pais, "site": None, "logo_url": None, "motivo": "sem nome nem NIF"}

    if not forcar:
        guardado = (_carregar()["perfis"] or {}).get(chave_perfil)
        if guardado is None and not chave_perfil.startswith("n:") and nome:
            guardado = (_carregar()["perfis"] or {}).get(chave(None, nome))
        if guardado and _valido(guardado):
            return _publico(guardado, chave_perfil)

    # Um pedido de cada vez por empresa (o grafo pede vários em paralelo).
    with _lock:
        a_esperar = _em_curso.get(chave_perfil)
        if a_esperar is None:
            _em_curso[chave_perfil] = threading.Event()
            dono = True
        else:
            dono = False
    if not dono:
        a_esperar.wait(timeout=90)
        return obter(nif, nome) or {"nif": nif, "nome": nome, "pais": pais, "site": None, "logo_url": None}

    try:
        perfil = _processar(
            nome,
            nif,
            pais,
            usar_ia=usar_ia,
            usar_pesquisa=True,
            forcar=forcar,
            user_id=user_id,
            provider=provider,
            modelo=modelo,
            com_logo=com_logo,
        )
        if not perfil.get("logo"):
            perfil["logo_tentado"] = perfil.get("atualizado")
        else:
            perfil.pop("logo_tentado", None)
        guardar_perfil(perfil)
        return _publico(perfil, chave_perfil)
    except Exception as exc:  # noqa: BLE001 - nunca deve rebentar o pedido do grafo
        logger.warning("Falha a resolver o perfil de %s (%s): %s", nome, nif, exc)
        return {"nif": nif, "nome": nome, "pais": pais, "site": None, "logo_url": None, "erro": str(exc)[:200]}
    finally:
        with _lock:
            evento = _em_curso.pop(chave_perfil, None)
        if evento:
            evento.set()


def resolver_varios(
    itens: Sequence[Dict[str, Any]],
    *,
    pais: str = "pt",
    usar_ia: bool = True,
    forcar: bool = False,
    user_id: Optional[str] = None,
    provider: Optional[str] = None,
    modelo: Optional[str] = None,
    com_logo: bool = True,
) -> List[Dict[str, Any]]:
    """Resolve vários perfis em paralelo (máx. `MAX_LOTE` por pedido)."""
    cfg = config()
    limite = max(1, min(int(cfg.get("max_lote") or MAX_LOTE), MAX_LOTE))
    alvo = [item for item in itens if isinstance(item, dict) and (item.get("nif") or item.get("nome"))][:limite]
    if not alvo:
        return []
    paralelo = max(1, min(int(cfg.get("paralelo") or PARALELO), 8, len(alvo)))
    if paralelo == 1:
        return [
            resolver(
                item.get("nome") or "",
                item.get("nif"),
                item.get("pais") or pais,
                usar_ia=usar_ia,
                forcar=forcar,
                user_id=user_id,
                provider=provider,
                modelo=modelo,
                com_logo=com_logo,
            )
            for item in alvo
        ]
    with ThreadPoolExecutor(max_workers=paralelo) as executor:
        futuros = [
            executor.submit(
                resolver,
                item.get("nome") or "",
                item.get("nif"),
                item.get("pais") or pais,
                usar_ia=usar_ia,
                forcar=forcar,
                user_id=user_id,
                provider=provider,
                modelo=modelo,
                com_logo=com_logo,
            )
            for item in alvo
        ]
        return [futuro.result() for futuro in futuros]


def definir_site(nome: str, nif: Optional[str], site: str, *, com_logo: bool = True) -> Dict[str, Any]:
    """Correcção manual do site (backoffice): recolhe o logótipo desse site."""
    url = _normalizar_url(site)
    chave_perfil = chave(nif, nome)
    if not url:
        raise ValueError("URL inválido")
    anterior = obter(nif, nome) or {}
    perfil: Dict[str, Any] = {
        "nome": nome,
        "nif": nif,
        "pais": anterior.get("pais") or "pt",
        "site": url,
        "dominio": _dominio(url),
        "confianca": 1.0,
        "origem": "manual",
        "motivo": "site definido manualmente",
        "candidatos": [],
        "ia": None,
        "atualizado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if com_logo:
        perfil.update(_obter_logo(url, chave_perfil))
    guardar_perfil(perfil)
    return _publico(perfil, chave_perfil)


def limpar(nif: Optional[str], nome: Optional[str] = None, *, com_logo: bool = False) -> bool:
    """Remove o perfil (e, opcionalmente, o logótipo) da cache."""
    chave_perfil = chave(nif, nome)
    if not chave_perfil:
        return False
    with _lock:
        dados = _carregar()
        existia = dados["perfis"].pop(chave_perfil, None) is not None
        if existia:
            _gravar(dados)
    if com_logo:
        for caminho in LOGOS_DIR.glob(f"{chave_perfil}.*"):
            try:
                caminho.unlink()
            except OSError:
                pass
    return existia


def lista(limite: int = 200, so_com_site: bool = False) -> List[Dict[str, Any]]:
    """Lista de perfis conhecidos (backoffice)."""
    with _lock:
        perfis = _carregar()["perfis"]
    saida: List[Dict[str, Any]] = []
    for chave_perfil, perfil in list(perfis.items())[: max(1, limite)]:
        if so_com_site and not perfil.get("site"):
            continue
        saida.append({**_publico(perfil, chave_perfil), "chave": chave_perfil})
    saida.sort(key=lambda item: -(item.get("confianca") or 0))
    return saida


def stats() -> Dict[str, Any]:
    """Números do módulo (para o painel)."""
    with _lock:
        perfis = _carregar()["perfis"]
    total = len(perfis)
    com_site = sum(1 for perfil in perfis.values() if perfil.get("site"))
    com_logo = sum(1 for chave_perfil in perfis if caminho_logo(chave_perfil))
    return {
        "total": total,
        "com_site": com_site,
        "com_logo": com_logo,
        "sem_site": total - com_site,
        "taxa_site": round(100 * com_site / total, 1) if total else 0.0,
        "taxa_logo": round(100 * com_logo / total, 1) if total else 0.0,
        "config": config(),
        "diretorio": str(EMPRESAS_DIR),
    }
