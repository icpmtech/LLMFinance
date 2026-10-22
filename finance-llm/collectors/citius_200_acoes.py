"""Recolha da «Lista de Sociedades com mais de 200 acções» (Portal CITIUS).

A lista é publicada anualmente pela DGAJ, em colaboração com o IGFEJ, nos termos
do n.º 3 do artigo 13.º do Regulamento das Custas Processuais e da
**Portaria n.º 200/2011, de 20 de maio**. Serve para aplicar a taxa de justiça
agravada das **tabelas I-C e II-B** às sociedades que, no ano civil anterior,
intentaram **mais de 200 ações, procedimentos ou execuções**.

A consulta vive em::

    https://www.citius.mj.pt/portal/consultas/Custas/Portaria200-2011.aspx

e é uma aplicação **ASP.NET WebForms**: o formulário tem o campo livre
(`txtPesquisa`) e o tipo de pesquisa (`rblTipo` → ``nipc`` | ``nome``); carregar
em «Pesquisar» com o campo vazio devolve a **lista completa**, paginada a 30
linhas, numa grelha ``ctl00_ContentPlaceHolder1_grdView`` com quatro colunas:

| # | Coluna |
|---|--------|
| 0 | `NIPC` (pode ter letras: sociedades estrangeiras, ex. ``LU 31006073``) |
| 1 | `Denominação` |
| 2 | `Acções, procedimentos ou execuções` (``Entre 201 e 500`` ou ``501 ou superior``) |
| 3 | `Ano` (o ano civil a que a lista respeita) |

O botão «Exportar para PDF» existe no formulário, mas responde com uma página de
erro genérica do portal («Ocorreu um erro inesperado»); por isso a recolha é
feita **página a página** pelo *postback* do paginador
(``Pager1$lnkNext``).

O ``www.citius.mj.pt`` serve o certificado do servidor com a cadeia incompleta —
o cliente trata disso com :mod:`collectors.tls_chain`, como os restantes
coletores do CITIUS.
"""
from __future__ import annotations

import logging
import re
import threading
import time
import unicodedata
from html import unescape
from typing import Any, Dict, List, Optional

import requests

from collectors import tls_chain

logger = logging.getLogger(__name__)

PAGE = "https://www.citius.mj.pt/portal/consultas/Custas/Portaria200-2011.aspx"
FIELD_PREFIX = "ctl00$ContentPlaceHolder1$"
BUTTON_SEARCH = FIELD_PREFIX + "btnSearch"
FIELD_TERMO = FIELD_PREFIX + "txtPesquisa"
FIELD_TIPO = FIELD_PREFIX + "rblTipo"
PAGER_NEXT = FIELD_PREFIX + "Pager1$lnkNext"

#: Tipos de pesquisa aceites pelo formulário.
TIPOS = {"nipc": "NIPC", "nome": "Denominação"}

#: Linhas por página na grelha do portal.
PAGE_SIZE = 30
MAX_PAGINAS = 200
MIN_REQUEST_INTERVAL = 1.2

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8",
}


class Portaria200Error(RuntimeError):
    """Erro na comunicação com a consulta da lista (Portaria 200/2011)."""


# --------------------------------------------------------------- utilidades
def _clean(fragment: str) -> str:
    """Remove tags, entidades HTML e espaços repetidos de um fragmento."""
    text = re.sub(r"<[^>]+>", " ", fragment or "")
    text = unescape(text).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def fold(value: str) -> str:
    """Minúsculas sem acentos (comparação e ordenação de designações)."""
    text = unicodedata.normalize("NFKD", (value or "").strip().lower())
    return "".join(ch for ch in text if not unicodedata.combining(ch))


#: Faixas de processos do artigo 13.º do RCP.
FAIXAS: Dict[str, Dict[str, Any]] = {
    "201-500": {"faixa": "201-500", "label": "Entre 201 e 500", "acoes_min": 201},
    "501+": {"faixa": "501+", "label": "501 ou superior", "acoes_min": 501},
}


def faixa_de(texto: str) -> Dict[str, Any]:
    """Converte o texto da coluna «Acções, procedimentos ou execuções» na faixa.

    O portal publica apenas as duas faixas da notificação do artigo 13.º (entre
    200 e 500, ou mais de 500), nunca o número exato por sociedade.
    """
    normalizado = fold(texto)
    m = re.search(r"\d+", normalizado)
    numero = int(m.group(0)) if m else 0
    chave = "501+" if numero >= 501 else "201-500"
    return {**FAIXAS[chave], "texto": (texto or "").strip(), "numero": numero or None}


def form_state(html: str) -> Dict[str, str]:
    """Campos escondidos do formulário (``__VIEWSTATE`` e companhia)."""

    def _value(name: str) -> str:
        m = re.search(r'id="' + re.escape(name) + r'"[^>]*value="([^"]*)"', html or "")
        return m.group(1) if m else ""

    return {
        "__EVENTTARGET": _value("__EVENTTARGET"),
        "__EVENTARGUMENT": _value("__EVENTARGUMENT"),
        "__VIEWSTATE": _value("__VIEWSTATE"),
        "__VIEWSTATEGENERATOR": _value("__VIEWSTATEGENERATOR"),
        "__VIEWSTATEENCRYPTED": _value("__VIEWSTATEENCRYPTED"),
        "__EVENTVALIDATION": _value("__EVENTVALIDATION"),
    }


def text_value(html: str, name: str) -> str:
    """Valor atual de um ``<input type="text">`` (para o postback o preservar)."""
    m = re.search(r'name="' + re.escape(name) + r'"[^>]*value="([^"]*)"', html or "")
    return unescape(m.group(1)) if m else ""


def parse_total(html: str) -> Optional[int]:
    """Total de entidades que o portal anuncia («82 entidades encontradas»)."""
    m = re.search(r"(\d+)\s*entidades?\s+encontradas?", _clean(html))
    return int(m.group(1)) if m else None


def page_number(html: str) -> Optional[int]:
    """Página atual do paginador."""
    m = re.search(r'lblPageNumber"[^>]*>(\d+)<', html or "")
    return int(m.group(1)) if m else None


def has_next_page(html: str) -> bool:
    """Há página seguinte (o paginador só desenha o ``lnkNext`` se houver)."""
    return "Pager1$lnkNext" in (html or "") or "Pager1_lnkNext" in (html or "")


def parse_rows(html: str) -> List[Dict[str, Any]]:
    """Extrai os registos da grelha (NIPC, Designação, Faixa, Ano).

    A grelha é uma ``<table>`` com uma linha de cabeçalho (``<th>``) e uma linha
    por sociedade, cada uma com quatro ``<td class="cellGridDistrib">``.
    """
    registos: List[Dict[str, Any]] = []
    for linha in re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", html or ""):
        celulas = [
            _clean(celula)
            for celula in re.findall(r'(?is)<td[^>]*class="cellGridDistrib"[^>]*>(.*?)</td>', linha)
        ]
        if len(celulas) < 4:
            continue
        nipc, denominacao, acoes, ano = celulas[0], celulas[1], celulas[2], celulas[3]
        if not nipc and not denominacao:
            continue
        faixa = faixa_de(acoes)
        ano_limpo = re.search(r"\d{4}", ano)
        registos.append(
            {
                "nipc": nipc,
                "denominacao": denominacao,
                "acoes_texto": acoes,
                "acoes_min": faixa["acoes_min"],
                "faixa": faixa["faixa"],
                "faixa_label": faixa["label"],
                "ano": int(ano_limpo.group(0)) if ano_limpo else None,
            }
        )
    return registos


def _blocked(html: str) -> bool:
    """O WAF do portal responde com uma página mínima de bloqueio."""
    baixo = (html or "")[:2000].lower()
    return "access denied" in baixo or "request rejected" in baixo


# ------------------------------------------------------------------ cliente
class Portaria200Client:
    """Cliente ASP.NET da lista de sociedades com mais de 200 ações.

    Uso::

        with Portaria200Client() as client:
            lista = client.recolher()
            lista["registos"]  # [{nipc, denominacao, acoes_texto, ano, …}]
    """

    def __init__(
        self,
        *,
        min_interval: float = MIN_REQUEST_INTERVAL,
        timeout: float = 60.0,
        connect_timeout: float = 15.0,
        deadline: float = 60.0,
        proxy: Optional[str] = None,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.min_interval = max(0.0, float(min_interval))
        self.timeout = timeout
        self.connect_timeout = connect_timeout
        #: Prazo máximo por pedido (o portal já ficou a «pingar» sem fechar o socket).
        self.deadline = deadline
        self.stalled = False
        self.proxy = proxy
        self.session = session or requests.Session()
        self.session.headers.update(HEADERS)
        if proxy:
            self.session.proxies.update({"http": proxy, "https": proxy})
        #: Bundle de CAs, só trocado quando a cadeia TLS vier incompleta.
        self.verify: Any = True
        self.pages_fetched = 0
        self._last_request = 0.0

    # --- ciclo de vida -------------------------------------------------
    def __enter__(self) -> "Portaria200Client":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:
        try:
            self.session.close()
        except Exception:  # noqa: BLE001
            pass

    # --- HTTP ----------------------------------------------------------
    def _throttle(self) -> None:
        wait = self.min_interval - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)

    def _tls_retry(self, url: str, exc: Exception) -> bool:
        if not tls_chain.is_chain_failure(exc):
            return False
        bundle = tls_chain.verify_for(
            url, timeout=min(self.connect_timeout, tls_chain.DEFAULT_TIMEOUT), proxy=self.proxy
        )
        if not bundle or bundle == self.verify:
            return False
        logger.warning("Cadeia TLS de %s incompleta; a validar com %s", url, bundle)
        self.verify = bundle
        return True

    def _request(self, metodo: str, *, data: Optional[Dict[str, str]] = None) -> requests.Response:
        """Pedido com prazo máximo (watchdog), devolvendo a resposta validada."""
        caixa: Dict[str, Any] = {}

        def correr() -> None:
            try:
                kwargs = {
                    "timeout": (self.connect_timeout, self.timeout),
                    "headers": {"Referer": PAGE},
                    "verify": self.verify,
                }
                if metodo == "GET":
                    caixa["resp"] = self.session.get(PAGE, **kwargs)
                else:
                    caixa["resp"] = self.session.post(PAGE, data=data, **kwargs)
            except Exception as exc:  # noqa: BLE001
                caixa["erro"] = exc

        thread = threading.Thread(target=correr, name="portaria200-request", daemon=True)
        thread.start()
        thread.join(self.deadline)
        if thread.is_alive():
            self.stalled = True
            self.close()
            raise Portaria200Error(
                f"Pedido sem resposta em {self.deadline:.0f}s (o portal não respondeu: a recolha para aqui)."
            )
        if caixa.get("erro") is not None:
            raise caixa["erro"]
        resp: requests.Response = caixa["resp"]
        resp.raise_for_status()
        return resp

    def _call(self, metodo: str, *, data: Optional[Dict[str, str]] = None, retries: int = 3) -> str:
        ultimo: Optional[Exception] = None
        for tentativa in range(retries):
            self._throttle()
            try:
                resp = self._request(metodo, data=data)
                self._last_request = time.monotonic()
                texto = resp.content.decode("utf-8", errors="replace")
                if _blocked(texto):
                    raise Portaria200Error("Pedido bloqueado pelo portal (WAF).")
                self.pages_fetched += 1
                return texto
            except requests.exceptions.SSLError as exc:
                ultimo = exc
                if self._tls_retry(PAGE, exc):
                    continue
                time.sleep(1.5 * (tentativa + 1))
            except Exception as exc:  # noqa: BLE001
                ultimo = exc
                if self.stalled:
                    break
                time.sleep(1.5 * (tentativa + 1))
        raise Portaria200Error(f"Falha a comunicar com {PAGE}: {ultimo}")

    # --- operações ------------------------------------------------------
    def abrir(self) -> str:
        """Página inicial (formulário vazio)."""
        return self._call("GET")

    def pesquisar(self, *, termo: str = "", tipo: str = "nipc", html: Optional[str] = None) -> str:
        """Submete a pesquisa; com ``termo`` vazio devolve a **lista completa**."""
        base = html if html is not None else self.abrir()
        dados = form_state(base)
        dados[FIELD_TERMO] = termo or ""
        dados[FIELD_TIPO] = tipo if tipo in TIPOS else "nipc"
        dados[BUTTON_SEARCH] = "Pesquisar"
        return self._call("POST", data=dados)

    def proxima_pagina(self, html: str) -> Optional[str]:
        """Avança uma página; ``None`` quando já não há página seguinte."""
        if not has_next_page(html):
            return None
        dados = form_state(html)
        dados["__EVENTTARGET"] = PAGER_NEXT
        dados["__EVENTARGUMENT"] = ""
        dados[FIELD_TERMO] = text_value(html, FIELD_TERMO)
        return self._call("POST", data=dados)

    def recolher(
        self,
        *,
        termo: str = "",
        tipo: str = "nipc",
        max_paginas: int = MAX_PAGINAS,
        on_page: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Percorre a lista completa (ou o resultado da pesquisa) página a página."""
        html = self.pesquisar(termo=termo, tipo=tipo)
        total = parse_total(html)
        registos: List[Dict[str, Any]] = []
        vistos: set = set()
        pagina = page_number(html) or 1
        paginas = 0

        while html and paginas < max_paginas:
            paginas += 1
            novos = 0
            for registo in parse_rows(html):
                chave = (registo.get("ano"), registo.get("nipc"), registo.get("denominacao"))
                if chave in vistos:
                    continue
                vistos.add(chave)
                registos.append({**registo, "pagina": pagina})
                novos += 1
            if on_page is not None:
                try:
                    on_page(pagina, len(registos), total)
                except Exception:  # noqa: BLE001 - progresso nunca trava a recolha
                    logger.debug("Callback de progresso falhou", exc_info=True)
            if total is not None and len(registos) >= total:
                break
            seguinte = self.proxima_pagina(html)
            if not seguinte:
                break
            numero = page_number(seguinte)
            if numero is not None and pagina is not None and numero <= pagina:
                break  # paginador devolveu a mesma página: evita ciclo infinito
            html = seguinte
            pagina = numero or ((pagina or 0) + 1)

        anos = sorted({int(r["ano"]) for r in registos if r.get("ano")})
        return {
            "fonte": "citius_portaria_200_2011",
            "fonte_label": "Portal CITIUS — Lista de Sociedades com mais de 200 acções",
            "source_url": PAGE,
            "termo": termo or None,
            "tipo": tipo,
            "total_portal": total,
            "paginas": paginas,
            "registos": registos,
            "anos": anos,
        }
