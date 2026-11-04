"""Coletor da «Lista Pública de Execuções» do CITIUS (Ministério da Justiça).

Fonte: https://www.citius.mj.pt/portal/execucoes/ListaPublicaExecucoes.aspx
       (Lista Pública de Execuções — executados em relação aos quais não se
       conseguiu encontrar bens penhoráveis suficientes para pagar as dívidas.)

É a fonte oficial onde constam os **executados** e as **execuções sem bens
penhoráveis suficientes**. Cada registo traz:

- **Nome do executado** (nome comercial/social ou pessoal);
- **N.º de documento** (NIF, BI, Passaporte ou Licença de Condução);
- **N.º de Processo** da execução;
- **Data** em que foi incluído/atualizado na lista (atalhos de 15/30 dias ou
  todos);
- **Identificação do agente de execução** (quando presente).

Fluxo do site (ASP.NET WebForms, **sem** UpdatePanel e **sem captcha**)
---------------------------------------------------------------------
1. ``GET ListaPublicaExecucoes.aspx`` → formulário com ``__VIEWSTATE``,
   ``__EVENTVALIDATION``, ``ddlAlfabeto`` (letra inicial do nome ou «Nome»),
   ``txtNomeExecutado`` (nome do executado), ``txtDocumento`` (NIF/BI/etc.),
   ``rblTipoDocumento`` (``6531``=NIF, ``1002``=BI, ``1004``=Passaporte,
   ``1005``=Lic. Condução) e ``rblDias`` (``15`` | ``30`` | ``todos``).
2. ``POST`` normal com ``<prefixo>btnSearch`` → a página inteira volta com a
   lista ``DataListExecucoes`` (10 registos por página), o total
   («N registos encontrados») e o paginador ``Pager1``.
3. ``POST`` com ``__EVENTTARGET=<prefixo>Pager1$lnkNext`` → página seguinte.

A recolha completa
------------------
O portal publica o total de registos (ex.: ~109 mil). Para obter a lista completa
sem depender do campo «nome» (que o formulário sugere mas que pode estar vazio),
iteramos por letra do alfabeto usando ``ddlAlfabeto`` (A-Z) e depois fazemos a
pesquisa sem letra (valor ``0``) para apanhar os casos que não começam por
letra, ou vice-versa. Cada letra é uma pesquisa independente com o seu
paginador.

Notas
-----
- A página é **UTF-8**.
- Não há documento PDF nem detalhe adicional por registo: a ficha é só a linha
  da lista. Por isso ``has_documento`` é sempre ``False`` e o scraper não
  extrai/analisa PDFs (a pedido do utilizador, a extração está desativada).
- O ``www.citius.mj.pt`` serve por vezes a cadeia TLS incompleta — o cliente
  trata disso com :mod:`collectors.tls_chain`, tal como os restantes coletores
  do CITIUS.
"""
from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html import unescape
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

from collectors import tls_chain

logger = logging.getLogger(__name__)

BASE = "https://www.citius.mj.pt/portal/execucoes/"
PAGE = BASE + "ListaPublicaExecucoes.aspx"

FIELD_PREFIX = "ctl00$ContentPlaceHolder1$"
BUTTON_SEARCH = FIELD_PREFIX + "btnSearch"
FIELD_ALFABETO = FIELD_PREFIX + "ddlAlfabeto"
FIELD_NOME = FIELD_PREFIX + "txtNomeExecutado"
FIELD_DOCUMENTO = FIELD_PREFIX + "txtDocumento"
FIELD_TIPO_DOCUMENTO = FIELD_PREFIX + "rblTipoDocumento"
FIELD_DIAS = FIELD_PREFIX + "rblDias"
FIELD_PROCESSO = FIELD_PREFIX + "txtNrProcesso"
SELECT_ALFABETO_ID = "ctl00_ContentPlaceHolder1_ddlAlfabeto"
PAGER_NEXT = FIELD_PREFIX + "Pager1$lnkNext"

PAGE_SIZE = 10
MIN_REQUEST_INTERVAL = 1.2

# Atalhos de datas do formulário (rblDias).
DIAS_OPCOES: Dict[str, str] = {
    "15": "Últimos 15 dias",
    "30": "Últimos 30 dias",
    "todos": "Todos",
}

# Tipos de documento do formulário (rblTipoDocumento).
TIPOS_DOCUMENTO: Dict[str, str] = {
    "nif": "6531",
    "bi": "1002",
    "passaporte": "1004",
    "cartaconducao": "1005",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8",
}


class ExecucoesError(RuntimeError):
    """Erro na comunicação com a Lista Pública de Execuções."""


# --------------------------------------------------------------- utilidades
def _clean(fragment: str) -> str:
    """Remove tags, entidades HTML e espaços repetidos de um fragmento."""
    text = re.sub(r"<[^>]+>", " ", fragment or "")
    text = unescape(text).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def _fold(value: str) -> str:
    """Minúsculas sem acentos (comparar rótulos)."""
    text = unicodedata.normalize("NFKD", (value or "").strip().lower())
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def form_state(html: str) -> Dict[str, str]:
    """Campos escondidos do formulário (``__VIEWSTATE`` e companhia)."""

    def _value(name: str) -> str:
        m = re.search(r'id="' + name.replace("$", r"\$") + r'"[^>]*value="([^"]*)"', html or "")
        return m.group(1) if m else ""

    return {
        "__EVENTTARGET": _value("__EVENTTARGET"),
        "__EVENTARGUMENT": _value("__EVENTARGUMENT"),
        "__LASTFOCUS": _value("__LASTFOCUS"),
        "__VIEWSTATE": _value("__VIEWSTATE"),
        "__VIEWSTATEGENERATOR": _value("__VIEWSTATEGENERATOR"),
        "__VIEWSTATEENCRYPTED": _value("__VIEWSTATEENCRYPTED"),
        "__EVENTVALIDATION": _value("__EVENTVALIDATION"),
    }


def parse_options(html: str, select_id: str) -> List[Dict[str, str]]:
    """Opções de um ``<select>`` (``value`` + ``label``), preservando a ordem."""
    m = re.search(
        r'<select[^>]*id="' + re.escape(select_id) + r'"(.*?)</select>', html or "", re.S | re.I
    )
    if not m:
        return []
    out: List[Dict[str, str]] = []
    for opt in re.finditer(r'<option[^>]*value="([^"]*)"[^>]*>(.*?)</option>', m.group(1), re.S | re.I):
        out.append({"value": opt.group(1), "label": _clean(opt.group(2))})
    return out


def result_count(html: str) -> int:
    """Total de registos declarado pelo portal («N registos encontrados»)."""
    m = re.search(r"([\d\.\s]+)\s+registos?\s+encontrados", _clean(html or ""))
    if not m:
        # Fallback para o contador exibido no topo da página.
        m = re.search(r"lblNumRegistos[^>]*>([\d\.\s]+)<", html or "")
    if not m:
        return 0
    digits = re.sub(r"\D", "", m.group(1))
    return int(digits) if digits else 0


def current_page(html: str) -> int:
    """Número da página atual do paginador (1 se não encontrar)."""
    m = re.search(r'Pager1_lblPageNumber"[^>]*>\s*(\d+)\s*<', html or "")
    return int(m.group(1)) if m else 1


def has_next_page(html: str) -> bool:
    """Indica se o paginador tem ligação para a página seguinte."""
    return bool(re.search(r'Pager1_lnkNext"\s+title="P[áa]gina\s+seguinte', html or "")) or bool(
        re.search(r'name="ctl00\$ContentPlaceHolder1\$Pager1\$lnkNext"', html or "")
    )


def _blocked(text: str) -> bool:
    """Heurística para detetar bloqueios do WAF/portal."""
    return "bloqueado" in _fold(text) and ("waf" in _fold(text) or "acesso" in _fold(text))


# ------------------------------------------------------------------ modelo
@dataclass
class RegistoExecucao:
    """Um registo da Lista Pública de Execuções (uma linha da lista)."""

    nome_executado: str
    numero_processo: Optional[str] = None
    data_entrada: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)
    source: str = "citius_execucoes"

    @property
    def pub_id(self) -> str:
        """Identificador estável (idempotência das reingestões)."""
        key = "|".join(
            [
                str(self.nome_executado or ""),
                str(self.numero_processo or ""),
                str(self.data_entrada or ""),
            ]
        )
        return hashlib.sha1(key.encode("utf-8")).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        """Documento pronto para o índice Elasticsearch (sem valores nulos)."""
        data = {
            "pub_id": self.pub_id,
            "nome_executado": self.nome_executado,
            "numero_processo": self.numero_processo,
            "data_entrada": self.data_entrada,
            "source": self.source,
        }
        if self.extra:
            data["extra"] = self.extra
        return {k: v for k, v in data.items() if v not in (None, "", [], {})}


# ------------------------------------------------------------------ parsing
def parse_items(html: str) -> List[RegistoExecucao]:
    """Extrai os registos da Lista Pública de Execuções do HTML de resultados."""
    if not html:
        return []

    out: List[RegistoExecucao] = []

    # A lista vem numa tabela ``ctl00_ContentPlaceHolder1_grdView`` com 5 colunas:
    # Nome do executado | Valor da Execução | Processo/Tribunal | Datas | Estado
    table_match = re.search(
        r'<table[^>]*id="ctl00_ContentPlaceHolder1_grdView"[^>]*>(.*?)</table>',
        html,
        re.S | re.I,
    )
    if table_match:
        body = table_match.group(1)
        for row in re.finditer(r"<tr[^>]*>(.*?)</tr>", body, re.S | re.I):
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row.group(1), re.S | re.I)
            if not cells:
                continue
            item = _item_from_cells(cells)
            if item:
                out.append(item)
        return out

    return out


def _pt_number(value: Optional[str]) -> Optional[float]:
    """Converte ``7 485,91 €`` (formato português) em ``7485.91``."""
    if not value:
        return None
    digits = re.sub(r"[^\d.,]", "", str(value))
    if not digits:
        return None
    if "," in digits and "." in digits:
        digits = digits.replace(".", "").replace(",", ".")
    elif "," in digits:
        digits = digits.replace(",", ".")
    elif digits.count(".") > 1:
        digits = digits.replace(".", "")
    try:
        return round(float(digits), 2)
    except ValueError:
        return None


def _item_from_cells(cells: List[str]) -> Optional[RegistoExecucao]:
    """Converte uma linha de células <td> num RegistoExecucao."""
    if not cells:
        return None
    cleaned = [_clean(c) for c in cells]
    if not any(cleaned):
        return None

    # Colunas: Nome | Valor | Processo/Tribunal | Data(s) | Estado
    nome = cleaned[0] if len(cleaned) > 0 else None
    if not nome:
        return None

    valor = _pt_number(cleaned[1]) if len(cleaned) > 1 else None

    # Coluna 3 tem Processo, Tribunal, Un. Org. e Agente Execução.
    processo_text = cleaned[2] if len(cleaned) > 2 else ""
    numero_processo = None
    tribunal = None
    comarca = None
    unidade_organica = None
    agente_execucao = None
    if processo_text:
        # O portal junta tudo numa única linha: "Processo: X Tribunal: Y Un. Org.: Z Agente Execução: W"
        m_proc = re.search(r"Processo:\s*([^\r\n]+?)\s*(?=Tribunal:|Un\.\s*Org\.:|Agente\s*Execução:|$)", processo_text, re.I)
        numero_processo = m_proc.group(1).strip() if m_proc else None
        m_trib = re.search(r"Tribunal:\s*([^\r\n]+?)\s*(?=Un\.\s*Org\.:|Agente\s*Execução:|$)", processo_text, re.I)
        tribunal = m_trib.group(1).strip() if m_trib else None
        m_uo = re.search(r"Un\.\s*Org\.:\s*([^\r\n]+?)\s*(?=Agente\s*Execução:|$)", processo_text, re.I)
        unidade_organica = m_uo.group(1).strip() if m_uo else None
        m_ag = re.search(r"Agente\s*Execução:\s*([^\r\n]+)", processo_text, re.I)
        agente_execucao = m_ag.group(1).strip() if m_ag else None
        if tribunal:
            m_com = re.search(r"Comarca\s+d[eo]\s+(.+?)(?:\s+Un\.\s*Org\.:|$)", tribunal, re.I)
            comarca = m_com.group(1).strip() if m_com else None

    # Coluna 4 tem data(s). Usamos a primeira data encontrada.
    data_text = cleaned[3] if len(cleaned) > 3 else ""
    data_entrada = None
    if data_text:
        m_date = re.search(r"(\d{2})[-/](\d{2})[-/](\d{4})", data_text)
        data_entrada = f"{m_date.group(3)}-{m_date.group(2)}-{m_date.group(1)}" if m_date else None

    estado = cleaned[4] if len(cleaned) > 4 else None

    extra: Dict[str, Any] = {}
    if valor is not None:
        extra["valor_execucao"] = valor
    if comarca:
        extra["comarca"] = comarca
    if tribunal:
        extra["tribunal"] = tribunal
    if unidade_organica:
        extra["unidade_organica"] = unidade_organica
    if agente_execucao:
        extra["agente_execucao"] = agente_execucao
    if estado:
        extra["estado"] = estado

    return RegistoExecucao(
        nome_executado=nome,
        numero_processo=numero_processo,
        data_entrada=data_entrada,
        extra=extra,
    )


# ------------------------------------------------------------------ cliente
class ExecucoesClient:
    """Cliente da Lista Pública de Execuções do CITIUS.

    Uso::

        with ExecucoesClient(min_interval=1.5) as client:
            page = client.search(nome="SILVA", dias="todos")
            for registo in page.items:
                ...
    """

    def __init__(
        self,
        *,
        min_interval: float = MIN_REQUEST_INTERVAL,
        timeout: float = 60.0,
        connect_timeout: float = 15.0,
        deadline: float = 45.0,
        proxy: Optional[str] = None,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.min_interval = max(0.0, float(min_interval))
        self.timeout = timeout
        self.connect_timeout = connect_timeout
        #: Prazo máximo por pedido — o portal já ficou a «pingar» durante minutos.
        self.deadline = deadline
        self.stalled = False
        self.proxy = proxy
        self.session = session or requests.Session()
        self.session.headers.update(HEADERS)
        if proxy:
            self.session.proxies.update({"http": proxy, "https": proxy})
        self.verify: Any = True
        self._state: Dict[str, str] = {}
        self._options: Dict[str, List[Dict[str, str]]] = {}
        self._last_request = 0.0
        self.pages_fetched = 0

    # --- ciclo de vida -------------------------------------------------
    def __enter__(self) -> "ExecucoesClient":
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
        """Repara a cadeia TLS do portal (AIA) e pede para repetir o pedido."""
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

    def _request(self, metodo: str, *, data: Optional[Dict[str, str]] = None, url: str = PAGE) -> requests.Response:
        """Pedido HTTP com prazo máximo (watchdog)."""
        caixa: Dict[str, Any] = {"data": data}

        def correr() -> None:
            try:
                if metodo == "GET":
                    caixa["resp"] = self.session.get(
                        url,
                        timeout=(self.connect_timeout, self.timeout),
                        headers={"Referer": PAGE},
                        verify=self.verify,
                    )
                else:
                    caixa["resp"] = self.session.post(
                        PAGE,
                        data=data,
                        timeout=(self.connect_timeout, self.timeout),
                        headers={"Referer": PAGE},
                        verify=self.verify,
                    )
            except Exception as exc:  # noqa: BLE001
                caixa["erro"] = exc

        thread = threading.Thread(target=correr, name="citius-execucoes", daemon=True)
        thread.start()
        thread.join(self.deadline)
        if thread.is_alive():
            self.stalled = True
            self.close()
            raise ExecucoesError(
                f"Pedido sem resposta em {self.deadline:.0f}s (o portal não respondeu: a recolha "
                "para aqui e guarda o que já tem)."
            )
        if caixa.get("erro") is not None:
            raise caixa["erro"]
        resp: requests.Response = caixa["resp"]
        resp.raise_for_status()
        return resp

    def _get(self, url: str = PAGE, *, retries: int = 3) -> str:
        last: Optional[Exception] = None
        for attempt in range(retries):
            self._throttle()
            try:
                resp = self._request("GET", url=url)
                self._last_request = time.monotonic()
                text = resp.content.decode("utf-8", errors="replace")
                if _blocked(text):
                    raise ExecucoesError("Pedido bloqueado pelo portal (WAF).")
                return text
            except requests.exceptions.SSLError as exc:
                last = exc
                if self._tls_retry(url, exc):
                    continue
                time.sleep(1.5 * (attempt + 1))
            except Exception as exc:  # noqa: BLE001
                last = exc
                if self.stalled:
                    break
                time.sleep(1.5 * (attempt + 1))
        raise ExecucoesError(f"Falha a obter {url}: {last}")

    def _post(self, data: Dict[str, str], *, retries: int = 3) -> str:
        last: Optional[Exception] = None
        for attempt in range(retries):
            self._throttle()
            try:
                resp = self._request("POST", data=data)
                self._last_request = time.monotonic()
                text = resp.content.decode("utf-8", errors="replace")
                if _blocked(text):
                    raise ExecucoesError("Pedido bloqueado pelo portal (WAF).")
                self.pages_fetched += 1
                return text
            except requests.exceptions.SSLError as exc:
                last = exc
                if self._tls_retry(PAGE, exc):
                    continue
                if self.stalled:
                    break
                time.sleep(2.0 * (attempt + 1))
            except Exception as exc:  # noqa: BLE001
                last = exc
                if self.stalled:
                    break
                time.sleep(2.0 * (attempt + 1))
        raise ExecucoesError(f"Falha no postback: {last}")

    def _payload(self, target: str = "", **fields: Any) -> Dict[str, str]:
        """Corpo do postback, com o estado corrente do formulário."""
        data = dict(self._state)
        data["__EVENTTARGET"] = target
        data["__EVENTARGUMENT"] = ""
        data.setdefault("__LASTFOCUS", "")
        data.setdefault("__VIEWSTATEENCRYPTED", "")
        for key, value in fields.items():
            if value is not None:
                data[key] = value
        return data

    def _absorb(self, html: str) -> None:
        """Atualiza o estado do formulário com os campos escondidos da resposta."""
        new_state = form_state(html)
        for name in ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION", "__VIEWSTATEENCRYPTED"):
            if new_state.get(name):
                self._state[name] = new_state[name]

    # --- formulário ----------------------------------------------------
    def fetch_form(self) -> str:
        """Obtém o formulário e memoriza o estado (viewstate + opções)."""
        html = self._get(PAGE)
        self._state = form_state(html)
        self._state.setdefault("__VIEWSTATEENCRYPTED", "")
        self._options = {"ddlAlfabeto": parse_options(html, SELECT_ALFABETO_ID)}
        self.pages_fetched = 0
        return html

    @property
    def options(self) -> Dict[str, List[Dict[str, str]]]:
        """Opções do ``select`` (alfabeto)."""
        return self._options

    def alfabeto(self) -> List[Dict[str, str]]:
        """Opções do alfabeto disponíveis (``0`` = Nome, depois A-Z)."""
        return list(self._options.get("ddlAlfabeto", []))

    # --- pesquisa ------------------------------------------------------
    def search(
        self,
        *,
        nome: Optional[str] = None,
        documento: Optional[str] = None,
        tipo_documento: Optional[str] = None,
        numero_processo: Optional[str] = None,
        dias: Optional[str] = None,
        letra: Optional[str] = None,
        fetch_options: bool = True,
    ) -> "ExecucoesPage":
        """Pesquisa registos da Lista Pública de Execuções.

        ``letra`` usa o dropdown ``ddlAlfabeto`` (A-Z ou "0" para todos). Os
        restantes campos são do formulário normal.
        """
        if dias and dias not in DIAS_OPCOES:
            raise ValueError("Atalho de dias inválido (use 15, 30 ou todos).")
        tipo = None
        if tipo_documento:
            tipo = TIPOS_DOCUMENTO.get(tipo_documento.lower())
            if tipo is None:
                raise ValueError(f"Tipo de documento inválido: {tipo_documento}")

        if fetch_options or not self._state:
            self.fetch_form()

        fields: Dict[str, Any] = {
            FIELD_NOME: (nome or "").strip(),
            FIELD_DOCUMENTO: (documento or "").strip(),
            FIELD_DIAS: dias or "todos",
            FIELD_PROCESSO: (numero_processo or "").strip(),
        }
        if tipo:
            fields[FIELD_TIPO_DOCUMENTO] = tipo
        if letra is not None:
            # Validar letra contra opções disponíveis (ou "0" para nome)
            opcoes = self._options.get("ddlAlfabeto", [])
            valores = {o["value"] for o in opcoes}
            if letra not in valores and letra != "0":
                # tentar converter A-Z para maiúscula
                letra = letra.upper()
                if letra not in valores:
                    letra = "0"
            fields[FIELD_ALFABETO] = letra

        html = self._post(self._payload(BUTTON_SEARCH, **fields))
        self._absorb(html)
        return ExecucoesPage(
            items=parse_items(html),
            total=result_count(html),
            page=current_page(html),
            has_next=has_next_page(html),
            html=html,
        )

    def next_page(self) -> "ExecucoesPage":
        """Avança para a página seguinte da pesquisa corrente."""
        html = self._post(self._payload(PAGER_NEXT))
        self._absorb(html)
        return ExecucoesPage(
            items=parse_items(html),
            total=result_count(html),
            page=current_page(html),
            has_next=has_next_page(html),
            html=html,
        )

    def collect(
        self,
        *,
        nome: Optional[str] = None,
        documento: Optional[str] = None,
        tipo_documento: Optional[str] = None,
        numero_processo: Optional[str] = None,
        dias: Optional[str] = None,
        max_pages: int = 50,
        max_items: Optional[int] = None,
        letras: Optional[List[str]] = None,
        on_page: Optional[Callable[["ExecucoesPage", List[RegistoExecucao]], None]] = None,
        stop: Optional[Callable[[], bool]] = None,
    ) -> Tuple[List[RegistoExecucao], Dict[str, Any]]:
        """Percorre as páginas da pesquisa até ao limite e devolve itens + resumo.

        Se ``letras`` for fornecido, faz uma pesquisa independente por cada
        letra do alfabeto (útil para recolha completa). Quando ``letras`` é
        omitido, usa a pesquisa simples com os critérios dados.
        """
        if letras:
            return self._collect_por_letra(
                letras=letras,
                dias=dias,
                max_pages=max_pages,
                max_items=max_items,
                on_page=on_page,
                stop=stop,
            )

        page = self.search(
            nome=nome,
            documento=documento,
            tipo_documento=tipo_documento,
            numero_processo=numero_processo,
            dias=dias,
        )
        return self._percorre(
            page,
            max_pages=max_pages,
            max_items=max_items,
            on_page=on_page,
            stop=stop,
        )

    def _collect_por_letra(
        self,
        *,
        letras: List[str],
        dias: Optional[str] = None,
        max_pages: int = 50,
        max_items: Optional[int] = None,
        on_page: Optional[Callable[["ExecucoesPage", List[RegistoExecucao]], None]] = None,
        stop: Optional[Callable[[], bool]] = None,
    ) -> Tuple[List[RegistoExecucao], Dict[str, Any]]:
        """Recolhe registos iterando por letra do alfabeto."""
        items: List[RegistoExecucao] = []
        seen: set[str] = set()
        total_declared = 0
        pages_done = 0
        letras_feitas = 0
        erros: List[str] = []

        for letra in letras:
            if stop and stop():
                break
            try:
                page = self.search(letra=letra, dias=dias, fetch_options=False)
            except Exception as exc:  # noqa: BLE001
                erros.append(f"letra {letra}: {exc}")
                logger.warning("Execuções: falha na letra %s: %s", letra, exc)
                continue
            total_declared += page.total
            letras_feitas += 1
            novos, resumo = self._percorre_pagina(
                page,
                seen,
                max_pages=max_pages,
                max_items=max_items,
                on_page=on_page,
                stop=stop,
                context={"letra": letra},
            )
            items.extend(novos)
            pages_done += resumo.get("pages", 0)
            if max_items and len(items) >= max_items:
                items = items[:max_items]
                break

        return items, {
            "total": total_declared,
            "pages": pages_done,
            "collected": len(items),
            "letras": letras_feitas,
            "page_size": PAGE_SIZE,
            "errors": erros,
        }

    def _percorre(
        self,
        page: "ExecucoesPage",
        max_pages: int = 50,
        max_items: Optional[int] = None,
        on_page: Optional[Callable[["ExecucoesPage", List[RegistoExecucao]], None]] = None,
        stop: Optional[Callable[[], bool]] = None,
    ) -> Tuple[List[RegistoExecucao], Dict[str, Any]]:
        """Percorre uma pesquisa já iniciada."""
        seen: set[str] = set()
        novos, resumo = self._percorre_pagina(
            page, seen, max_pages=max_pages, max_items=max_items, on_page=on_page, stop=stop
        )
        return novos, {
            "total": page.total,
            **resumo,
            "page_size": PAGE_SIZE,
        }

    def _percorre_pagina(
        self,
        page: "ExecucoesPage",
        seen: set[str],
        max_pages: int = 50,
        max_items: Optional[int] = None,
        on_page: Optional[Callable[["ExecucoesPage", List[RegistoExecucao]], None]] = None,
        stop: Optional[Callable[[], bool]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[RegistoExecucao], Dict[str, Any]]:
        """Percorre páginas de uma pesquisa já iniciada."""
        items: List[RegistoExecucao] = []
        pages_done = 0
        while True:
            novos: List[RegistoExecucao] = []
            for item in page.items:
                if item.pub_id in seen:
                    continue
                seen.add(item.pub_id)
                novos.append(item)
            items.extend(novos)
            pages_done += 1
            if on_page:
                on_page(page, novos)
            if stop and stop():
                break
            if max_items and len(items) >= max_items:
                items = items[:max_items]
                break
            if pages_done >= max_pages or not page.has_next or not page.items:
                break
            try:
                page = self.next_page()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Execuções: paginação falhou %s: %s", context, exc)
                break
        return items, {"pages": pages_done}


@dataclass
class ExecucoesPage:
    """Uma página de resultados da Lista Pública de Execuções."""

    items: List[RegistoExecucao]
    total: int = 0
    page: int = 1
    has_next: bool = False
    html: str = ""


# -------------------------------------------------------------- funções aux

def letras_alfabeto() -> List[str]:
    """Letras A-Z mais a opção "0" (todos/nome) para a recolha completa."""
    return ["0"] + [chr(ord("A") + i) for i in range(26)]


def coletar(
    *,
    nome: Optional[str] = None,
    documento: Optional[str] = None,
    tipo_documento: Optional[str] = None,
    numero_processo: Optional[str] = None,
    dias: Optional[str] = "todos",
    todos: bool = False,
    max_pages: int = 50,
    max_items: Optional[int] = None,
    letras: Optional[List[str]] = None,
    min_interval: float = MIN_REQUEST_INTERVAL,
    proxy: Optional[str] = None,
    on_page: Optional[Callable[[ExecucoesPage, List[RegistoExecucao]], None]] = None,
    stop: Optional[Callable[[], bool]] = None,
) -> Tuple[List[RegistoExecucao], Dict[str, Any]]:
    """Função de alto nível: abre cliente, recolhe e devolve itens + resumo.

    Com ``todos=True`` usa a recolha por letras do alfabeto (A-Z + "0"), que é
    a forma de obter a lista completa sem depender do campo nome.
    """
    if todos and not letras:
        letras = letras_alfabeto()
    with ExecucoesClient(min_interval=min_interval, proxy=proxy) as client:
        return client.collect(
            nome=nome,
            documento=documento,
            tipo_documento=tipo_documento,
            numero_processo=numero_processo,
            dias=dias,
            max_pages=max_pages,
            max_items=max_items,
            letras=letras,
            on_page=on_page,
            stop=stop,
        )
