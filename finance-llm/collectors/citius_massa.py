"""Coletor da Publicidade da Composição da Massa Insolvente (CITIUS).

Fonte: https://www.citius.mj.pt/portal/consultas/PublicidadeMassaInsolvente.aspx
       (Ministério da Justiça / CITIUS — «Consulte os anúncios da publicidade da
       composição da massa insolvente, publicados pelo Administrador Judicial,
       nos termos do art.º 152.º do CIRE»)

O portal utiliza ASP.NET WebForms com ``ScriptManager1`` a devolver *deltas*
parciais para a pesquisa e paginação, tal como o CIRE. O painel de resultados
é ``pnlUpdResults`` e cada anúncio é um ``fieldset#DetailViewer`` com:

- **Processo** (número + espécie), **Tribunal**, **Insolvente(s)**,
  **Área de negócio**, **Valor da avaliação** e **Data da última atualização**;
- a **Descrição da massa insolvente** (as verbas, em texto);
- a **Composição** — lista de ativos, cada um com tipo, descrição, quantidade
  e localização.

Filtros do formulário: tipo de ativo, localização (concelho), área de negócio
(CAE) e data de atualização (últimos 15 dias ou intervalo livre).
"""
from __future__ import annotations

import hashlib
import logging
import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import requests

from collectors import tls_chain
from collectors.citius_cire import parse_delta

logger = logging.getLogger(__name__)

BASE = "https://www.citius.mj.pt/portal/consultas/"
PAGE = BASE + "PublicidadeMassaInsolvente.aspx"

FIELD_PREFIX = "ctl00$ContentPlaceHolder1$"
BTN_SEARCH = FIELD_PREFIX + "btnSearch"
PAGER_NEXT = FIELD_PREFIX + "Pager1$lnkNext"
PANEL_UPDATE = FIELD_PREFIX + "pnlUpdResults"
SCRIPT_MANAGER = FIELD_PREFIX + "ScriptManager1"

PAGE_SIZE = 10
MIN_REQUEST_INTERVAL = 1.2

# Intervalos rápidos do formulário (rbtDatas): true = últimos 15 dias.
DIAS_OPCOES: Dict[str, str] = {"15": "Últimos 15 dias"}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8",
    "X-MicrosoftAjax": "Delta=true",
    "X-Requested-With": "XMLHttpRequest",
}


class MassaError(RuntimeError):
    """Erro na comunicação com a Publicidade da Composição da Massa Insolvente."""


# ------------------------------------------------------------------ utilidades
def _fold(value: str) -> str:
    """Minúsculas sem acentos (para comparar rótulos do formulário)."""
    text = unicodedata.normalize("NFKD", (value or "").strip().lower())
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def _flat(value: str) -> str:
    """Texto numa linha, sem ``( ... )`` do «ver mais» nem o próprio «ver mais»."""
    text = (value or "").replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s*\(\s*\.\.\.\s*\)\s*", " ", text)
    text = re.sub(r"\s+ver mais\s*$", "", text, flags=re.IGNORECASE)
    return text.strip()


def _lines(value: str) -> List[str]:
    """Linhas não vazias, com espaços normalizados e a marca «( … )» removida."""
    text = (value or "").replace("\xa0", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\s*\(\s*\.\.\.\s*\)\s*", " ", text)
    out: List[str] = []
    for line in text.splitlines():
        line = re.sub(r"\s+ver mais\s*$", "", line, flags=re.IGNORECASE).strip()
        if line:
            out.append(line)
    return out


def _iso_date(value: Optional[str]) -> Optional[str]:
    """Converte ``dd/mm/aaaa`` (ou ``dd/mm/aaaa HH:MM:SS``) em ISO 8601."""
    value = (value or "").strip()
    if not value:
        return None
    m = re.match(
        r"^(\d{2})[/-](\d{2})[/-](\d{4})(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?)?",
        value,
    )
    if not m:
        return value
    dia, mes, ano, hora, minuto, segundo = m.groups()
    if hora:
        return f"{ano}-{mes}-{dia}T{hora}:{minuto}:{segundo or '00'}"
    return f"{ano}-{mes}-{dia}"


def _br_date(value: Optional[str]) -> Optional[str]:
    """Converte ISO 8601 (ou ``dd/mm/aaaa``) no formato do formulário."""
    value = (value or "").strip()
    if not value:
        return None
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", value)
    if m:
        return f"{m.group(3)}/{m.group(2)}/{m.group(1)}"
    return value


def _parse_valor(value: Optional[str]) -> Optional[float]:
    """Converte ``30 000,01 €`` em ``30000.01``."""
    text = re.sub(r"[^\d.,-]", "", value or "")
    if not text:
        return None
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _especie_tipo(especie: Optional[str]) -> Optional[str]:
    """Classifica a espécie do processo (Insolvência, PER, PEAP ou PEVE)."""
    text = _fold(especie or "")
    if not text:
        return None
    if "insolv" in text:
        return "Insolvência"
    if "peap" in text or "acordo de pagamento" in text:
        return "PEAP"
    if "peve" in text or "viabiliza" in text:
        return "PEVE"
    if "per" in text.split() or "revitaliza" in text:
        return "PER"
    return None


def _option_value(options: List[Dict[str, str]], wanted: Optional[str]) -> Optional[str]:
    """Valor da opção cujo rótulo corresponde a ``wanted`` (exato e depois parcial)."""
    wanted_fold = _fold(wanted or "")
    if not wanted_fold:
        return None
    exact = [o for o in options if _fold(o.get("label", "")) == wanted_fold]
    if exact:
        return exact[0]["value"]
    partial = [o for o in options if wanted_fold in _fold(o.get("label", ""))]
    return partial[0]["value"] if partial else None


# ------------------------------------------------------------------ formulário
def parse_options(html: str, select_id: str) -> List[Dict[str, str]]:
    """Opções de um ``<select>`` (``value`` + ``label``), preservando a ordem."""
    m = re.search(
        r'<select[^>]*id="' + re.escape(select_id) + r'"(.*?)</select>', html or "", re.S | re.I
    )
    if not m:
        return []
    out: List[Dict[str, str]] = []
    for opt in re.finditer(r'<option[^>]*value="([^"]*)"[^>]*>(.*?)</option>', m.group(1), re.S | re.I):
        from html import unescape

        label = re.sub(r"<[^>]+>", " ", opt.group(2))
        label = unescape(label).replace("\xa0", " ")
        out.append({"value": opt.group(1), "label": re.sub(r"\s+", " ", label).strip()})
    return out


def form_payload(html: str) -> Dict[str, str]:
    """Todos os campos do formulário com os valores correntes (para o POST)."""
    import lxml.html

    doc = lxml.html.fromstring(html or "<form id='aspnetForm'></form>")
    data: Dict[str, str] = {}
    for el in doc.xpath('//form[@id="aspnetForm"]//input'):
        name = el.get("name")
        if not name:
            continue
        kind = (el.get("type") or "text").lower()
        if kind in ("submit", "button", "image", "reset", "file"):
            continue
        if kind in ("radio", "checkbox"):
            if el.get("checked") is None:
                continue
            data[name] = el.get("value") or "on"
        else:
            data[name] = el.get("value") or ""
    for sel in doc.xpath('//form[@id="aspnetForm"]//select'):
        name = sel.get("name")
        if not name:
            continue
        opts = [o for o in sel.xpath("./option") if isinstance(o.tag, str)]
        chosen = next((o for o in opts if o.get("selected") is not None), opts[0] if opts else None)
        if chosen is not None:
            data[name] = chosen.get("value") or ""
    return data


def result_panel(html: str) -> str:
    """HTML do painel de resultados (``pnlUpdResults``).

    Aceita tanto a página completa como o *delta* do ``ScriptManager1``.
    """
    if not html:
        return ""
    # 1) delta do ScriptManager
    if html.strip().startswith("|"):
        delta = parse_delta(html)
        panel = delta.get("ctl00_ContentPlaceHolder1_pnlUpdResults")
        if panel:
            return panel
    # 2) página completa
    m = re.search(
        r'<div id="ctl00_ContentPlaceHolder1_pnlUpdResults">(.*?)(?:<div id="ctl00_ContentPlaceHolder1_Pager2_panel"|</form>)',
        html,
        re.S | re.I,
    )
    if m:
        return m.group(1)
    return html


# ------------------------------------------------------------------ modelo
@dataclass
class Ativo:
    """Um bem da composição da massa insolvente."""

    tipo: Optional[str] = None
    descricao: Optional[str] = None
    quantidade: Optional[str] = None
    localizacao: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tipo": self.tipo,
            "descricao": self.descricao,
            "quantidade": self.quantidade,
            "localizacao": self.localizacao,
        }


@dataclass
class AnuncioMassa:
    """Um anúncio da composição da massa insolvente (art.º 152.º do CIRE)."""

    titulo: str = "Anúncio da composição da massa insolvente"
    processo: Optional[str] = None
    processo_numero: Optional[str] = None
    especie: Optional[str] = None
    tipo: Optional[str] = None
    tribunal: Optional[str] = None
    tribunal_comarca: Optional[str] = None
    juizo: Optional[str] = None
    insolventes: List[str] = field(default_factory=list)
    area_negocio: Optional[str] = None
    valor_avaliacao: Optional[float] = None
    valor_texto: Optional[str] = None
    data_atualizacao: Optional[str] = None
    descricao: Optional[str] = None
    ativos: List[Ativo] = field(default_factory=list)
    source: str = "citius_massa_insolvente"

    @property
    def pub_id(self) -> str:
        """Identificador estável do anúncio (idempotência das reimportações)."""
        key = "|".join(
            [
                str(self.processo or ""),
                str(self.data_atualizacao or ""),
                str(self.tribunal or ""),
                str((self.descricao or "")[:200]),
            ]
        )
        return hashlib.sha1(key.encode("utf-8")).hexdigest()

    @property
    def insolvente(self) -> Optional[str]:
        """Designação do(s) insolvente(s), numa única string."""
        return "; ".join(self.insolventes) if self.insolventes else None

    @property
    def ativo_tipos(self) -> List[str]:
        return sorted({a.tipo for a in self.ativos if a.tipo})

    @property
    def localizacoes(self) -> List[str]:
        return sorted({a.localizacao for a in self.ativos if a.localizacao})

    @property
    def texto(self) -> str:
        """Texto integral do anúncio (pesquisa livre)."""
        partes = [
            self.titulo,
            self.processo,
            self.especie,
            self.tribunal,
            self.insolvente,
            self.area_negocio,
            self.descricao,
            *(a.descricao for a in self.ativos),
        ]
        return _flat(" ".join(p for p in partes if p))

    def to_dict(self) -> Dict[str, Any]:
        """Documento pronto para o índice Elasticsearch (sem valores nulos)."""
        data = {
            "pub_id": self.pub_id,
            "titulo": self.titulo,
            "processo": self.processo,
            "processo_numero": self.processo_numero,
            "especie": self.especie,
            "tipo": self.tipo,
            "tribunal": self.tribunal,
            "tribunal_comarca": self.tribunal_comarca,
            "juizo": self.juizo,
            "insolventes": self.insolventes,
            "insolvente": self.insolvente,
            "area_negocio": self.area_negocio,
            "valor_avaliacao": self.valor_avaliacao,
            "valor_texto": self.valor_texto,
            "data_atualizacao": self.data_atualizacao,
            "descricao": self.descricao,
            "ativos": [a.to_dict() for a in self.ativos],
            "ativo_tipos": self.ativo_tipos,
            "localizacoes": self.localizacoes,
            "texto": self.texto,
            "source": self.source,
        }
        return {k: v for k, v in data.items() if v not in (None, "", [], {})}


def _field_values(fieldset: Any) -> Dict[str, str]:
    """Pares ``rótulo → valor`` dos ``<strong>`` diretos do anúncio."""
    out: Dict[str, str] = {}
    for strong in fieldset.xpath("./strong"):
        label = _fold(_flat(strong.text_content())).rstrip(":")
        value = _flat(strong.tail or "")
        if label and value:
            out[label] = value
    return out


def _ativos_from(fieldset: Any) -> List[Ativo]:
    """Ativos da secção «Composição» (tipo, descrição, quantidade e localização)."""
    ativos: List[Ativo] = []
    for node in fieldset.xpath('.//span[contains(@id, "AtivosDataList")]/span'):
        lines = _lines(node.text_content())
        if not lines:
            continue
        ativo = Ativo()
        first = lines[0]
        m = re.match(r"Ativo:\s*(.*)$", first, re.I)
        if m:
            ativo.tipo = m.group(1).strip() or None
            body = lines[1:]
        else:
            body = lines
        descricao: List[str] = []
        for line in body:
            mq = re.match(r"Quantidade:\s*(.*)$", line, re.I)
            ml = re.match(r"Localização:\s*(.*)$", line, re.I)
            if mq:
                ativo.quantidade = mq.group(1).strip() or None
            elif ml:
                ativo.localizacao = ml.group(1).strip() or None
            else:
                descricao.append(line)
        ativo.descricao = " ".join(descricao).strip() or None
        ativos.append(ativo)
    return ativos


def _item_from_fieldset(fieldset: Any) -> Optional[AnuncioMassa]:
    """Converte um ``fieldset#DetailViewer`` num ``AnuncioMassa``."""
    campos = _field_values(fieldset)
    processo = campos.get("processo")
    if not processo:
        return None

    anuncio = AnuncioMassa(processo=processo)
    legenda = fieldset.xpath("./legend")
    if legenda:
        anuncio.titulo = _flat(legenda[0].text_content()) or anuncio.titulo

    m = re.match(r"^(.*?)\s+-\s+(.*)$", processo)
    if m:
        anuncio.processo_numero = m.group(1).strip()
        anuncio.especie = m.group(2).strip()
    else:
        anuncio.processo_numero = processo
    anuncio.tipo = _especie_tipo(anuncio.especie)

    anuncio.tribunal = campos.get("tribunal")
    if anuncio.tribunal:
        partes = [p.strip() for p in anuncio.tribunal.split(" - ") if p.strip()]
        if partes:
            mc = re.search(
                r"Comarca\s+(?:de\s+|da\s+|do\s+|dos\s+|das\s+)?(.+)$", partes[0], re.I
            )
            anuncio.tribunal_comarca = (mc.group(1).strip() if mc else partes[0]) or None
            anuncio.juizo = " - ".join(partes[1:]) or None

    for span in fieldset.xpath('.//span[contains(@id, "InsolventeDataList")]/span'):
        nome = re.sub(r"^\s*Insolvente:\s*", "", _flat(span.text_content()), flags=re.I).strip()
        if nome and nome not in anuncio.insolventes:
            anuncio.insolventes.append(nome)

    anuncio.area_negocio = campos.get("area de negocio") or campos.get("área de negócio")
    anuncio.valor_texto = campos.get("valor da avaliacao") or campos.get("valor da avaliação")
    anuncio.valor_avaliacao = _parse_valor(anuncio.valor_texto)
    data = campos.get("data da ultima atualizacao") or campos.get("data da última atualização")
    anuncio.data_atualizacao = _iso_date(data)

    blocos = [
        div
        for div in fieldset.xpath('./div[contains(@class, "collapsiblecontent")]')
        if isinstance(div.tag, str)
    ]
    if blocos:
        anuncio.descricao = "\n".join(_lines(blocos[0].text_content())) or None

    anuncio.ativos = _ativos_from(fieldset)
    return anuncio


def parse_items(results_html: str) -> List[AnuncioMassa]:
    """Extrai os anúncios do HTML do painel de resultados."""
    import lxml.html

    if not results_html:
        return []
    try:
        doc = lxml.html.fromstring(results_html)
    except Exception:  # noqa: BLE001 — fragmento inválido
        return []
    out: List[AnuncioMassa] = []
    for fieldset in doc.xpath('//fieldset[@id="DetailViewer"]'):
        anuncio = _item_from_fieldset(fieldset)
        if anuncio:
            out.append(anuncio)
    return out


def result_count(results_html: str) -> int:
    """Número total de registos indicado pelo portal."""
    m = re.search(r"N[uú]mero de Registos:\s*([\d.\s]+)", results_html or "", re.I)
    if not m:
        return 0
    digits = re.sub(r"\D", "", m.group(1))
    return int(digits) if digits else 0


def current_page(results_html: str) -> int:
    """Página atual do paginador superior.

    O título do ``lblPageNumber`` usa entidades HTML (``Página actual``), pelo
    que também procuramos pela *span* seleccionada diretamente.
    """
    if not results_html:
        return 1
    m = re.search(
        r'id="ctl00_ContentPlaceHolder1_Pager1_lblPageNumber"[^\u003e]*title="[^"]*?\s*(\d+)"[^\u003e]*\u003e\s*(\d+)',
        results_html,
        re.S | re.I,
    )
    if m:
        return int(m.group(2))
    m = re.search(r"P[áa]gina\s+actual[^\u003e]*\u003e\s*(\d+)", results_html, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"P[áa]gina\s+atual:\s*(\d+)", results_html, re.I)
    return int(m.group(1)) if m else 1


def has_next_page(results_html: str) -> bool:
    """Indica se o paginador superior tem ligação para a página seguinte."""
    return bool(re.search(r"Pager1_lnkNext", results_html or ""))


def _blocked(html: str) -> bool:
    """Deteta a página de bloqueio do WAF do CITIUS."""
    return "Something Went Wrong" in (html or "")[:4000]


# ------------------------------------------------------------------ cliente
class MassaInsolventeClient:
    """Cliente da Publicidade da Composição da Massa Insolvente (pesquisa e paginação).

    Uso::

        with MassaInsolventeClient(min_interval=1.5) as client:
            page = client.search(dias="15")
            for anuncio in page.items:
                ...
    """

    def __init__(
        self,
        *,
        min_interval: float = MIN_REQUEST_INTERVAL,
        timeout: float = 60.0,
        proxy: Optional[str] = None,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.min_interval = max(0.0, float(min_interval))
        self.timeout = timeout
        self.proxy = proxy
        self.session = session or requests.Session()
        self.session.headers.update(HEADERS)
        if proxy:
            self.session.proxies.update({"http": proxy, "https": proxy})
        self.verify: Any = True
        self._form_html = ""
        self._current_html = ""
        self._state: Dict[str, str] = {}
        self._options: Dict[str, List[Dict[str, str]]] = {}
        self._last_request = 0.0
        self.pages_fetched = 0

    # --- ciclo de vida -------------------------------------------------
    def __enter__(self) -> "MassaInsolventeClient":
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
            url, timeout=min(self.timeout, tls_chain.DEFAULT_TIMEOUT), proxy=self.proxy
        )
        if not bundle or bundle == self.verify:
            return False
        logger.warning("Cadeia TLS de %s incompleta; a validar com %s", url, bundle)
        self.verify = bundle
        return True

    def _get(self, url: str = PAGE, *, retries: int = 3) -> str:
        last: Optional[Exception] = None
        for attempt in range(retries):
            self._throttle()
            try:
                resp = self.session.get(
                    url, timeout=self.timeout, headers={"Referer": PAGE}, verify=self.verify
                )
                self._last_request = time.monotonic()
                resp.raise_for_status()
                return resp.content.decode("utf-8", errors="replace")
            except requests.exceptions.SSLError as exc:
                last = exc
                if self._tls_retry(url, exc):
                    continue
                time.sleep(1.5 * (attempt + 1))
            except Exception as exc:  # noqa: BLE001
                last = exc
                time.sleep(1.5 * (attempt + 1))
        raise MassaError(f"Falha a obter {url}: {last}")

    def _post(self, data: Dict[str, str], *, retries: int = 3) -> str:
        last: Optional[Exception] = None
        headers = dict(self.session.headers)
        # Se é postback parcial, o portal requer os cabeçalhos ASP.NET Ajax.
        is_async = data.get("__ASYNCPOST") == "true" or data.get(SCRIPT_MANAGER)
        if is_async:
            headers.update({"X-MicrosoftAjax": "Delta=true", "X-Requested-With": "XMLHttpRequest"})
        for attempt in range(retries):
            self._throttle()
            try:
                resp = self.session.post(
                    PAGE,
                    data=data,
                    timeout=self.timeout,
                    headers={"Referer": PAGE, **headers},
                    verify=self.verify,
                )
                self._last_request = time.monotonic()
                resp.raise_for_status()
                text = resp.content.decode("utf-8", errors="replace")
                if _blocked(text):
                    raise MassaError("Pedido bloqueado pelo portal (WAF).")
                self.pages_fetched += 1
                return text
            except requests.exceptions.SSLError as exc:
                last = exc
                if self._tls_retry(PAGE, exc):
                    continue
                time.sleep(2.0 * (attempt + 1))
            except Exception as exc:  # noqa: BLE001
                last = exc
                time.sleep(2.0 * (attempt + 1))
        raise MassaError(f"Falha no pedido ao portal: {last}")

    # --- formulário ----------------------------------------------------
    def fetch_form(self) -> str:
        """Obtém o formulário e memoriza o estado e as opções dos selects."""
        html = self._get(PAGE)
        self._form_html = html
        self._current_html = html
        self._options = {
            "tipos_ativo": parse_options(html, "ctl00_ContentPlaceHolder1_ddlTiposAtivo"),
            "localizacoes": parse_options(html, "ctl00_ContentPlaceHolder1_ddlLocalizacao"),
            "areas_negocio": parse_options(html, "ctl00_ContentPlaceHolder1_ddlCaes"),
        }
        self.pages_fetched = 0
        return html

    @property
    def options(self) -> Dict[str, List[Dict[str, str]]]:
        """Opções dos selects (tipos de ativo, localizações e áreas de negócio)."""
        return self._options

    def tipos_ativo(self) -> List[Dict[str, str]]:
        return list(self._options.get("tipos_ativo", []))

    def localizacoes(self) -> List[Dict[str, str]]:
        return list(self._options.get("localizacoes", []))

    def areas_negocio(self) -> List[Dict[str, str]]:
        return list(self._options.get("areas_negocio", []))

    # --- pesquisa ------------------------------------------------------
    def search(
        self,
        *,
        desde: Optional[str] = None,
        ate: Optional[str] = None,
        dias: Optional[str] = None,
        tipo_ativo: Optional[str] = None,
        localizacao: Optional[str] = None,
        area_negocio: Optional[str] = None,
        fetch_options: bool = True,
    ) -> "MassaPage":
        """Pesquisa anúncios e devolve a primeira página de resultados.

        ``desde``/``ate`` aceitam ISO 8601 ou ``dd/mm/aaaa`` e têm de ser
        indicados os dois. Sem datas usa-se o atalho ``dias="15"`` (últimos 15
        dias). ``tipo_ativo``, ``localizacao`` e ``area_negocio`` são comparados
        pelo **rótulo** do select do portal.
        """
        # Validação antes de qualquer pedido (falha depressa, sem tocar no portal).
        if bool(desde) != bool(ate):
            raise ValueError("Indique as duas datas (início e fim) ou nenhuma.")
        if desde and ate:
            dias = None
        else:
            dias = dias or "15"
        if dias and dias not in DIAS_OPCOES:
            raise ValueError("Atalho de dias inválido (use 15).")
        if desde and ate:
            from datetime import date

            if date.fromisoformat(str(_iso_date(ate))[:10]) < date.fromisoformat(str(_iso_date(desde))[:10]):
                raise ValueError("A data final não pode ser anterior à inicial.")

        if fetch_options or not self._form_html:
            self.fetch_form()

        data = form_payload(self._form_html)
        data[FIELD_PREFIX + "rbtDatas"] = "false" if desde and ate else "true"
        data[FIELD_PREFIX + "txtCalendarDesde"] = _br_date(desde) or ""
        data[FIELD_PREFIX + "txtCalendarAte"] = _br_date(ate) or ""
        data[FIELD_PREFIX + "ddlTiposAtivo"] = (
            _option_value(self.tipos_ativo(), tipo_ativo) or ""
        ) if tipo_ativo else ""
        data[FIELD_PREFIX + "ddlLocalizacao"] = (
            _option_value(self.localizacoes(), localizacao) or ""
        ) if localizacao else ""
        data[FIELD_PREFIX + "ddlCaes"] = (
            _option_value(self.areas_negocio(), area_negocio) or ""
        ) if area_negocio else ""
        data[BTN_SEARCH] = "Pesquisar"
        # Sem ``ScriptManager1`` o portal trata como postback normal e perde o
        # contexto dos resultados; o campo é necessário para devolver o delta.
        data[SCRIPT_MANAGER] = f"{PANEL_UPDATE}|{BTN_SEARCH}"
        data["__ASYNCPOST"] = "true"

        html = self._post(data)
        panel = result_panel(html)
        self._current_html = panel
        self._absorb_delta(html)
        return MassaPage(
            items=parse_items(panel),
            total=result_count(panel),
            page=current_page(panel),
            has_next=has_next_page(panel),
            html=panel,
        )

    def _absorb_delta(self, html: str) -> None:
        """Guarda o estado (viewstate/validation) que veio no delta do portal.

        O delta do ASP.NET Ajax começa com um registo de comprimento vazio
        (``1|#||4|…``), de onde se extraem os ``hiddenField``. Sem este estado
        atualizado o pedido da página seguinte é redirecionado para ``erro.htm``.
        """
        if not (html and html.lstrip().startswith(("|", "1|"))):
            return
        delta = parse_delta(html)
        for key in ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION", "__VIEWSTATEENCRYPTED"):
            value = delta.get(f"hiddenField:{key}")
            if value is None:
                continue
            self._state[key] = value
            self._form_html = _patch_state(self._form_html, key, value)
            self._current_html = _patch_state(self._current_html, key, value)

    def next_page(self) -> "MassaPage":
        """Avança para a página seguinte da pesquisa corrente.

        O portal devolve um delta; o ``ScriptManager1`` tem de vir preenchido e o
        ``__VIEWSTATE``/``__EVENTVALIDATION`` são extraídos do delta anterior.
        """
        # Estado base: formulário original (todos os campos) com o último estado.
        data = form_payload(self._form_html)
        data.update(self._state)
        data.update(form_payload(self._current_html))
        data["__EVENTTARGET"] = PAGER_NEXT
        data["__EVENTARGUMENT"] = ""
        data[SCRIPT_MANAGER] = f"{PANEL_UPDATE}|{PAGER_NEXT}"
        data["__ASYNCPOST"] = "true"
        data.pop(BTN_SEARCH, None)

        html = self._post(data)
        panel = result_panel(html)
        self._current_html = panel
        self._absorb_delta(html)
        return MassaPage(
            items=parse_items(panel),
            total=result_count(panel),
            page=current_page(panel),
            has_next=has_next_page(panel),
            html=panel,
        )

    def collect(
        self,
        *,
        max_pages: int = 50,
        max_items: Optional[int] = None,
        on_page: Optional[Any] = None,
        stop: Optional[Any] = None,
        **criteria: Any,
    ) -> Tuple[List[AnuncioMassa], Dict[str, Any]]:
        """Percorre as páginas da pesquisa até ao limite e devolve itens + resumo."""
        page = self.search(**criteria)
        items: List[AnuncioMassa] = []
        seen: set[str] = set()
        total = page.total
        pages_done = 0
        while True:
            new = [i for i in page.items if i.pub_id not in seen]
            for item in new:
                seen.add(item.pub_id)
            items.extend(new)
            pages_done += 1
            if on_page:
                on_page(page, new)
            if stop and stop():
                break
            if max_items and len(items) >= max_items:
                items = items[:max_items]
                break
            if pages_done >= max_pages or not page.has_next:
                break
            page = self.next_page()
            if not page.items:
                break

        return items, {
            "total": total,
            "pages": pages_done,
            "collected": len(items),
            "page_size": PAGE_SIZE,
        }


@dataclass
class MassaPage:
    """Uma página de resultados da composição da massa insolvente."""

    items: List[AnuncioMassa]
    total: int = 0
    page: int = 1
    has_next: bool = False
    html: str = ""

    @property
    def pages_total(self) -> int:
        """Número estimado de páginas (10 anúncios por página)."""
        return (self.total + PAGE_SIZE - 1) // PAGE_SIZE if self.total else 0


def _patch_state(html: str, name: str, value: str) -> str:
    """Atualiza o valor de um campo escondido no HTML do formulário."""
    if not html or not name:
        return html
    pattern = r'id="' + re.escape(name) + r'"[^>]*value="[^"]*"'

    def _replace(match: "re.Match[str]") -> str:
        prefix = match.group(0).split('value="')[0]
        return f'{prefix}value="{value}"'

    return re.sub(pattern, _replace, html, count=1)


def parse_datetime(value: Optional[str]) -> Optional[datetime]:
    """Data/hora ISO do anúncio (útil em scripts e testes)."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
