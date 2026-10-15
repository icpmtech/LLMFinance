"""Vista de mercado financeiro: os tickers da plataforma agrupados por **país**.

O painel responde a uma pergunta que o resto da plataforma não respondia: *de que
países são os instrumentos que seguimos, e como se está a comportar cada um?* Não
inventa um universo novo — usa os tickers que a plataforma já conhece (a lista
`data/tickers_extended.json`, a carteira seguida no Sentimento e a lista de
`/tickers` do Elasticsearch) e mostra-os por país.

Duas fontes, com papéis distintos:

* **País** — o campo `country` do Yahoo Finance (é o mesmo que a ficha do ticker
  mostra). Quando o Yahoo não responde, o sufixo do mercado (`.LS` → Portugal,
  `.DE` → Alemanha…) dá a resposta, e cada linha diz **de onde veio**
  (`country_source`: `yahoo`, `mercado` ou `desconhecido`). Nada é adivinhado em
  silêncio. A resolução é guardada em `data/market_view/countries.json`, para que
  o custo (uma leitura ao Yahoo por ticker) se pague **uma vez** por símbolo.
* **Cotação** — `sentiment_market.live_quote`, a variação **do dia**
  (`lastPrice / previousClose − 1`), lida em paralelo. Uma falha fica com `error`
  à vista e o ticker não é preenchido com um valor suposto.

A leitura é simultânea nas duas frentes (o mesmo par de operações por ticker, num
só conjunto de threads), e o resultado fica em cache de memória durante
`CACHE_TTL_SECONDS` — sem isso, cada navegação dentro da SPA pagaria dezenas de
pedidos ao Yahoo outra vez.
"""
from __future__ import annotations

import concurrent.futures
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from api import sentiment_market as market

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]

#: Universo de tickers da plataforma, pela ordem em que é apresentado.
EXTENDED_PATH = ROOT / "data" / "tickers_extended.json"
#: Cache em disco do país de cada ticker (`data/` é volume: sobrevive ao deploy).
CACHE_DIR = ROOT / "data" / "market_view"
COUNTRY_CACHE_PATH = CACHE_DIR / "countries.json"

#: Quantos tickers a vista lê por pedido. O universo tem ~90; ler tudo de uma vez
#: são dezenas de pedidos ao Yahoo, e a página não fica melhor por isso.
MAX_TICKERS = 120
DEFAULT_TICKERS = 40
DEFAULT_WORKERS = 6

#: Tempo de vida da resposta em memória (o Yahoo não serve dados em menos de um
#: minuto; repetir a leitura dentro deste intervalo não traria nada de novo).
CACHE_TTL_SECONDS = 60.0

#: Sufixo do símbolo → país, quando o Yahoo não responde. Cobre os mercados a que
#: esta plataforma vai buscar cotações (Euronext Lisboa em primeiro lugar).
SUFIXOS: Dict[str, Tuple[str, str]] = {
    "LS": ("PT", "Portugal"),
    "DE": ("DE", "Alemanha"),
    "F": ("DE", "Alemanha"),
    "PA": ("FR", "França"),
    "L": ("GB", "Reino Unido"),
    "MC": ("ES", "Espanha"),
    "AS": ("NL", "Países Baixos"),
    "MI": ("IT", "Itália"),
    "SW": ("CH", "Suíça"),
    "ST": ("SE", "Suécia"),
    "OL": ("NO", "Noruega"),
    "CO": ("DK", "Dinamarca"),
    "HE": ("FI", "Finlândia"),
    "IR": ("IE", "Irlanda"),
    "BR": ("BE", "Bélgica"),
    "VI": ("AT", "Áustria"),
    "LS.PT": ("PT", "Portugal"),
    "TO": ("CA", "Canadá"),
    "V": ("CA", "Canadá"),
    "AX": ("AU", "Austrália"),
    "HK": ("HK", "Hong Kong"),
    "T": ("JP", "Japão"),
    "SS": ("CN", "China"),
    "SZ": ("CN", "China"),
    "SA": ("BR", "Brasil"),
    "MX": ("MX", "México"),
    "JO": ("ZA", "África do Sul"),
    "KS": ("KR", "Coreia do Sul"),
    "SI": ("SG", "Singapura"),
    "NS": ("IN", "Índia"),
    "BO": ("IN", "Índia"),
}

#: Códigos ISO 3166-1 alfa-2 → nome em português. O Yahoo devolve o nome em
#: inglês; sem isto a vista misturava «United States» com «Portugal».
PAISES: Dict[str, str] = {
    "AE": "Emirados Árabes Unidos",
    "AR": "Argentina",
    "AT": "Áustria",
    "AU": "Austrália",
    "BE": "Bélgica",
    "BR": "Brasil",
    "CA": "Canadá",
    "CH": "Suíça",
    "CL": "Chile",
    "CN": "China",
    "CO": "Colômbia",
    "CZ": "Chéquia",
    "DE": "Alemanha",
    "DK": "Dinamarca",
    "EE": "Estónia",
    "EG": "Egito",
    "ES": "Espanha",
    "FI": "Finlândia",
    "FR": "França",
    "GB": "Reino Unido",
    "GR": "Grécia",
    "HK": "Hong Kong",
    "HU": "Hungria",
    "ID": "Indonésia",
    "IE": "Irlanda",
    "IL": "Israel",
    "IN": "Índia",
    "IS": "Islândia",
    "IT": "Itália",
    "JP": "Japão",
    "KR": "Coreia do Sul",
    "KW": "Kuwait",
    "LU": "Luxemburgo",
    "MA": "Marrocos",
    "MX": "México",
    "MY": "Malásia",
    "NL": "Países Baixos",
    "NO": "Noruega",
    "NZ": "Nova Zelândia",
    "PE": "Peru",
    "PH": "Filipinas",
    "PL": "Polónia",
    "PT": "Portugal",
    "QA": "Catar",
    "RO": "Roménia",
    "RU": "Rússia",
    "SA": "Arábia Saudita",
    "SE": "Suécia",
    "SG": "Singapura",
    "TH": "Tailândia",
    "TR": "Turquia",
    "TW": "Taiwan",
    "US": "Estados Unidos",
    "ZA": "África do Sul",
}

#: Nome do Yahoo (em inglês) → código ISO. O `country` do Yahoo é um nome e não
#: um código, pelo que a tradução passa por aqui.
NOMES_PARA_CODIGO: Dict[str, str] = {
    "united states": "US",
    "usa": "US",
    "united kingdom": "GB",
    "great britain": "GB",
    "portugal": "PT",
    "spain": "ES",
    "germany": "DE",
    "france": "FR",
    "italy": "IT",
    "netherlands": "NL",
    "the netherlands": "NL",
    "belgium": "BE",
    "switzerland": "CH",
    "ireland": "IE",
    "sweden": "SE",
    "norway": "NO",
    "denmark": "DK",
    "finland": "FI",
    "austria": "AT",
    "greece": "GR",
    "poland": "PL",
    "canada": "CA",
    "brazil": "BR",
    "mexico": "MX",
    "argentina": "AR",
    "chile": "CL",
    "china": "CN",
    "hong kong": "HK",
    "japan": "JP",
    "south korea": "KR",
    "korea": "KR",
    "india": "IN",
    "australia": "AU",
    "new zealand": "NZ",
    "singapore": "SG",
    "taiwan": "TW",
    "israel": "IL",
    "turkey": "TR",
    "south africa": "ZA",
    "russia": "RU",
}

#: Ressalva própria desta vista. **Não** se reutiliza `sentiment_market.PRICE_CAVEAT`:
#: essa fala da correlação entre tom e preço, que não é o que aqui se mostra.
#: Escrita em texto simples — a página mostra-a como texto, sem Markdown.
CAVEAT = (
    "Cotações do Yahoo Finance, na variação do dia (lastPrice ÷ previousClose − 1). "
    "Podem chegar com atraso face ao mercado, e o valor é o da leitura indicada — um ticker "
    "sem resposta fica identificado com o motivo, nunca preenchido com um valor suposto."
)

#: Grupo de quem não tem país identificado. Existe para o ticker **não
#: desaparecer** da vista só porque a origem do país falhou.
UNKNOWN_CODE = "ZZ"
UNKNOWN_LABEL = "Sem país identificado"

_CURRENCY_SYMBOLS: Dict[str, str] = {
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "BRL": "R$",
    "JPY": "¥",
    "CHF": "CHF",
}

_cache: Optional[Tuple[float, str, Dict[str, Any]]] = None
_cache_lock = threading.Lock()
_countries_lock = threading.Lock()


# --------------------------------------------------------------------------
# Universo de tickers
# --------------------------------------------------------------------------
def _extended_tickers() -> List[str]:
    """Tickers de `data/tickers_extended.json` (a lista da plataforma)."""
    if not EXTENDED_PATH.exists():
        return []
    try:
        raw = json.loads(EXTENDED_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Lista de tickers ilegível (%s); a usar só a carteira seguida.", exc)
        return []
    if isinstance(raw, dict):
        raw = raw.get("tickers") or []
    if not isinstance(raw, list):
        return []
    return [str(item).strip().upper() for item in raw if str(item).strip()]


def universe() -> List[str]:
    """Tickers conhecidos: seguidos primeiro, depois a lista alargada.

    A carteira seguida vem à frente de propósito — é o que o utilizador escolheu
    ver, e é o que aparece quando o pedido é cortado pelo limite.
    """
    codes: List[str] = []
    for candidate in [*market.watchlist(), *_extended_tickers()]:
        try:
            code = market.normalise_ticker(candidate)
        except KeyError:
            continue
        if code not in codes:
            codes.append(code)
    return codes


# --------------------------------------------------------------------------
# País
# --------------------------------------------------------------------------
def _read_country_cache() -> Dict[str, Any]:
    if not COUNTRY_CACHE_PATH.exists():
        return {}
    try:
        raw = json.loads(COUNTRY_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Cache de países ilegível (%s); a recomeçar.", exc)
        return {}
    if not isinstance(raw, dict):
        return {}
    return {str(key).upper(): value for key, value in raw.items() if isinstance(value, dict)}


def _write_country_cache(entries: Dict[str, Any]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = COUNTRY_CACHE_PATH.with_suffix(".json.tmp")
    payload = json.dumps(entries, ensure_ascii=False, indent=2, sort_keys=True, default=str)
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(COUNTRY_CACHE_PATH)


def _suffix_country(ticker: str) -> Optional[Tuple[str, str]]:
    """País pelo sufixo do mercado (`EDP.LS` → Portugal); `None` se não souber."""
    if "." not in ticker:
        return None
    sufixo = ticker.rsplit(".", 1)[1].upper()
    return SUFIXOS.get(sufixo)


def _code_from_name(name: str) -> str:
    """Nome de país do Yahoo (em inglês) → código ISO."""
    return NOMES_PARA_CODIGO.get(str(name or "").strip().lower(), "")


def _profile_from_yahoo(ticker: str) -> Optional[Dict[str, Any]]:
    """País, nome e setor do Yahoo Finance (a mesma fonte da ficha do ticker).

    Uma só leitura serve os três campos: pedir `country` e `name` em chamadas
    separadas duplicava os pedidos ao Yahoo sem trazer nada de novo.
    """
    from api.tools import get_stock_info

    try:
        info = get_stock_info(ticker)
    except Exception as exc:  # pragma: no cover - depende da rede
        logger.debug("Perfil de %s não obtido (%s)", ticker, exc)
        return None
    if info.get("error"):
        return None
    nome_yahoo = str(info.get("country") or "").strip()
    codigo = _code_from_name(nome_yahoo)
    return {
        "country": codigo or None,
        "country_label": PAISES.get(codigo, nome_yahoo) if codigo else None,
        "country_source": "yahoo" if codigo else None,
        "name": _texto(info.get("name")),
        "sector": _texto(info.get("sector")),
        "exchange": _texto(info.get("exchange")),
        "currency": _texto(info.get("currency")),
    }


def _texto(value: Any) -> Optional[str]:
    texto = " ".join(str(value or "").split())
    return texto or None


def resolve_profile(
    ticker: str,
    cache: Dict[str, Any],
    *,
    consultar_yahoo: bool = True,
) -> Dict[str, Any]:
    """País (e nome) de um ticker: cache em disco → Yahoo → sufixo do mercado.

    Devolve sempre `country`, `country_label` e `country_source`; quando nada
    resolve o país, fica `desconhecido` — em vez de um palpite.
    """
    guardado = cache.get(ticker) or {}
    perfil: Dict[str, Any] = {
        "name": _texto(guardado.get("name")),
        "sector": _texto(guardado.get("sector")),
        "exchange": _texto(guardado.get("exchange")),
        "currency": _texto(guardado.get("currency")),
    }
    codigo_cache = _texto(guardado.get("country"))
    if codigo_cache:
        return {
            **perfil,
            "country": codigo_cache,
            "country_label": _texto(guardado.get("country_label")) or country_label(codigo_cache),
            # Um código gravado veio do Yahoo quando foi resolvido; dizê-lo agora
            # («cache») perderia a informação de onde o país nasceu.
            "country_source": _texto(guardado.get("country_source")) or "yahoo",
        }

    if consultar_yahoo:
        obtido = _profile_from_yahoo(ticker)
        if obtido:
            perfil.update({chave: valor for chave, valor in obtido.items() if valor})
            if obtido.get("country"):
                return {**perfil, "country": obtido["country"], "country_label": obtido["country_label"], "country_source": "yahoo"}

    por_sufixo = _suffix_country(ticker)
    if por_sufixo:
        codigo, rotulo = por_sufixo
        return {**perfil, "country": codigo, "country_label": rotulo, "country_source": "mercado"}
    return {**perfil, "country": UNKNOWN_CODE, "country_label": UNKNOWN_LABEL, "country_source": "desconhecido"}


# --------------------------------------------------------------------------
# Agregação
# --------------------------------------------------------------------------
def country_label(code: str) -> str:
    if code == UNKNOWN_CODE:
        return UNKNOWN_LABEL
    return PAISES.get(code, code)


def _erro(row: Dict[str, Any]) -> Optional[str]:
    """Mensagem de uma linha sem cotação.

    O Yahoo responde a um símbolo descontinuado sem levantar erro (devolve
    `fast_info` sem preço), pelo que «sem erro» não quer dizer «sem problema»:
    sem isto a linha aparecia sem cotação e sem explicação nenhuma.
    """
    if row.get("price") is not None:
        return None
    explicito = _texto(row.get("error")) or _texto(row.get("message"))
    return explicito or "Sem cotação no Yahoo Finance (símbolo descontinuado ou sem dados)."


def _stats(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Agregados de um país. Sem valores supostos: só conta o que foi lido."""
    cotados = [row for row in rows if row.get("price") is not None]
    variacoes = [float(row["change_pct"]) for row in cotados if row.get("change_pct") is not None]
    mercados = [float(row["market_cap"]) for row in cotados if row.get("market_cap")]
    return {
        "tickers": len(rows),
        "quoted": len(cotados),
        "without_quote": len(rows) - len(cotados),
        "advancers": sum(1 for valor in variacoes if valor > 0),
        "decliners": sum(1 for valor in variacoes if valor < 0),
        "flat": sum(1 for valor in variacoes if valor == 0),
        "average_change_pct": round(sum(variacoes) / len(variacoes), 4) if variacoes else None,
        "market_cap": sum(mercados) if mercados else None,
        "market_cap_count": len(mercados),
    }


def _extremos(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Melhor e pior variação do país (para o cabeçalho do grupo).

    Só faz sentido com **dois** tickers cotados: num país com um só, «melhor» e
    «pior» seriam o mesmo número repetido duas vezes.
    """
    cotados = [row for row in rows if row.get("change_pct") is not None]
    if len(cotados) < 2:
        return {"best": None, "worst": None}
    melhor = max(cotados, key=lambda row: float(row["change_pct"]))
    pior = min(cotados, key=lambda row: float(row["change_pct"]))

    def simples(row: Dict[str, Any]) -> Dict[str, Any]:
        return {"ticker": row["ticker"], "name": row.get("name"), "change_pct": row["change_pct"]}

    return {"best": simples(melhor), "worst": simples(pior)}


def group_by_country(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Agrupa as linhas por país e ordena os grupos (mais tickers primeiro).

    Puro: recebe as linhas já resolvidas e não vai a nenhuma fonte. É o que os
    testes verificam sem rede.
    """
    grupos: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        grupos.setdefault(str(row.get("country") or UNKNOWN_CODE), []).append(row)

    countries: List[Dict[str, Any]] = []
    for codigo, membros in grupos.items():
        membros.sort(
            key=lambda row: (
                # Sem cotação para o fim: um erro de leitura não deve esconder os
                # números que existem.
                row.get("price") is None,
                -abs(float(row["change_pct"])) if row.get("change_pct") is not None else 0.0,
                str(row.get("ticker") or ""),
            )
        )
        stats = _stats(membros)
        countries.append(
            {
                "country": codigo,
                "country_label": country_label(codigo),
                "unknown": codigo == UNKNOWN_CODE,
                "tickers": membros,
                "stats": stats,
                "rank": _rank_summary(stats["average_change_pct"]),
                **_extremos(membros),
            }
        )

    # Ordem estável: os maiores mercados primeiro, o grupo dos desconhecidos no
    # fim (é um resto, não um país). Ordenar pela variação do dia faria os grupos
    # mudar de lugar a cada leitura, e quem procura um país fá-lo pela posição.
    countries.sort(
        key=lambda grupo: (
            bool(grupo["unknown"]),
            -grupo["stats"]["quoted"],
            -grupo["stats"]["tickers"],
            grupo["country_label"],
        )
    )
    return {
        "countries": countries,
        "totals": _stats(rows),
    }


def _rank_summary(variacao: Optional[float]) -> Dict[str, Any]:
    """Leitura curta da variação média do país (o mesmo critério em toda a vista)."""
    if variacao is None:
        return {"id": "sem-cotacao", "label": "Sem cotação"}
    if variacao > 0.5:
        return {"id": "em-alta", "label": "Em alta"}
    if variacao < -0.5:
        return {"id": "em-baixa", "label": "Em baixa"}
    return {"id": "estavel", "label": "Estável"}


# --------------------------------------------------------------------------
# Leitura
# --------------------------------------------------------------------------
def _quote_row(ticker: str, cache: Dict[str, Any]) -> Dict[str, Any]:
    """Cotação do dia + país/nome, para um ticker (o trabalho de cada thread)."""
    row = dict(market.live_quote(ticker))
    perfil = resolve_profile(ticker, cache)
    # O nome vem do perfil quando a cotação não traz nenhum.
    row.update({chave: valor for chave, valor in perfil.items() if valor is not None or chave.startswith("country")})
    row["market_cap_label"] = _market_cap(row.get("market_cap"))
    row["price_label"] = _price(row.get("price"), row.get("currency"))
    row["change_label"] = _change(row.get("change_pct"))
    row["url"] = f"/tickers/{ticker}"
    # Uma linha sem cotação tem de dizer porquê — na própria linha e não só no
    # resumo, senão o ticker aparece mudo na lista.
    if row.get("price") is None:
        row["error"] = _erro(row)
    return row


def _market_cap(value: Any) -> Optional[str]:
    """Capitalização em forma curta (ex.: `1,24 b` = 1,24 × 10⁹)."""
    try:
        numero = float(value)
    except (TypeError, ValueError):
        return None
    if numero <= 0:
        return None
    for limite, escala in ((1e12, "t"), (1e9, "b"), (1e6, "m"), (1e3, "k")):
        if numero >= limite:
            return f"{numero / limite:,.2f} {escala}".replace(",", " ")
    return f"{numero:,.0f}"


def _price(value: Any, currency: Any) -> Optional[str]:
    try:
        numero = float(value)
    except (TypeError, ValueError):
        return None
    simbolo = _CURRENCY_SYMBOLS.get(str(currency or "").upper(), str(currency or "") or "")
    return f"{simbolo} {numero:,.2f}".strip() if simbolo else f"{numero:,.2f}"


def _change(value: Any) -> Optional[str]:
    try:
        numero = float(value)
    except (TypeError, ValueError):
        return None
    sinal = "+" if numero > 0 else ""
    return f"{sinal}{numero:.2f} %"


def by_country(
    *,
    tickers: Optional[Sequence[str]] = None,
    limit: int = DEFAULT_TICKERS,
    workers: int = DEFAULT_WORKERS,
    refresh: bool = False,
) -> Dict[str, Any]:
    """Vista por país: cada ticker com a cotação do dia e o país resolvido."""
    global _cache

    pedidos: List[str] = []
    for candidato in tickers or universe():
        try:
            code = market.normalise_ticker(candidato)
        except KeyError:
            continue
        if code not in pedidos:
            pedidos.append(code)
    if not pedidos:
        pedidos = list(market.LIVE_DEFAULT_TICKERS)
    cortados = len(pedidos) - min(len(pedidos), max(1, min(MAX_TICKERS, int(limit or DEFAULT_TICKERS))))
    pedidos = pedidos[: max(1, min(MAX_TICKERS, int(limit or DEFAULT_TICKERS)))]

    chave = ",".join(pedidos)
    with _cache_lock:
        if not refresh and _cache and _cache[1] == chave and (time.time() - _cache[0]) < CACHE_TTL_SECONDS:
            return dict(_cache[2])

    cache_paises = _read_country_cache()

    def trabalho(code: str) -> Dict[str, Any]:
        try:
            return _quote_row(code, cache_paises)
        except Exception as exc:  # pragma: no cover - depende da rede
            logger.debug("Leitura de %s falhou: %s", code, exc)
            return {
                "ticker": code,
                "error": str(exc),
                **resolve_profile(code, cache_paises),
                "url": f"/tickers/{code}",
            }

    # O mesmo conjunto de threads faz as duas leituras de cada ticker (cotação e
    # país): abrir um segundo pool só somava espera.
    pool_size = max(1, min(12, int(workers or DEFAULT_WORKERS), len(pedidos)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=pool_size) as pool:
        rows = list(pool.map(trabalho, pedidos))

    # Guardar o que se aprendeu sobre os tickers (uma vez por símbolo, não por pedido).
    novos = {}
    for row in rows:
        anterior = cache_paises.get(row["ticker"]) or {}
        if row.get("country_source") != "yahoo":
            continue
        perfil = {
            "country": row.get("country"),
            "country_label": row.get("country_label"),
            "country_source": "yahoo",
            "name": row.get("name"),
            "sector": row.get("sector"),
            "exchange": row.get("exchange"),
            "currency": row.get("currency"),
        }
        if all(anterior.get(chave) == valor for chave, valor in perfil.items()):
            continue
        novos[row["ticker"]] = perfil
    if novos:
        try:
            with _countries_lock:
                atual = _read_country_cache()
                atual.update(novos)
                _write_country_cache(atual)
        except OSError as exc:  # pragma: no cover - disco cheio / sem permissão
            logger.warning("Cache de países não gravado (%s).", exc)
    agrupado = group_by_country(rows)
    payload: Dict[str, Any] = {
        "source": market.LIVE_SOURCE,
        "generated_at": _now(),
        "caveat": CAVEAT,
        "universe": {
            "requested": len(rows),
            "available": len(universe()),
            "truncated": cortados,
            "errors": [
                {"ticker": row["ticker"], "error": _erro(row), "country": row.get("country"), "country_label": row.get("country_label")}
                for row in rows
                if row.get("price") is None
            ],
        },
        **agrupado,
    }
    with _cache_lock:
        _cache = (time.time(), chave, payload)
    return dict(payload)


def _now() -> str:
    """Marca de tempo da leitura (UTC, ISO), igual à do resto da plataforma."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def meta() -> Dict[str, Any]:
    """O que a página precisa de saber sobre a fonte, sem ir buscá-la."""
    return {
        "source": market.LIVE_SOURCE,
        "caveat": CAVEAT,
        "universe": len(universe()),
        "default_limit": DEFAULT_TICKERS,
        "max_limit": MAX_TICKERS,
        "cache_seconds": CACHE_TTL_SECONDS,
        "country_sources": {
            "yahoo": "campo country do Yahoo Finance",
            "mercado": "sufixo do mercado (ex.: .LS → Portugal)",
            "desconhecido": "sem país identificado",
        },
        "country_cache": str(COUNTRY_CACHE_PATH.relative_to(ROOT)) if COUNTRY_CACHE_PATH.exists() else None,
    }
