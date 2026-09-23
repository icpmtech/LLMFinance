"""Coletor do CIRE (CITIUS) — publicidade do PER, PEAP, PEVE e da insolvência.

Fonte: https://www.citius.mj.pt/portal/consultas/ConsultasCire.aspx
       (Ministério da Justiça / CITIUS — «Publicidade dos processos especiais de
       revitalização, dos processos especiais para acordo de pagamento, dos
       processos extraordinários de viabilização de empresas e dos processos de
       insolvência»)

É a fonte oficial onde são publicados os anúncios e atos dos processos de
insolvência e de revitalização de empresas (Portugal), com o tribunal, o
processo, a espécie, a data e os **intervenientes com NIF/NIPC** (insolvente,
administrador da insolvência, credores, …).

Fluxo do site (ASP.NET WebForms com ``UpdatePanel``)
----------------------------------------------------
1. ``GET ConsultasCire.aspx`` → formulário (``__VIEWSTATE``, ``__EVENTVALIDATION``,
   ``ddlTribunais``/``ddlGrupoActos``/``ddlActos``, datas e ``rblDias``).
2. ``POST`` (postback assíncrono: ``__ASYNCPOST=true``, ``X-MicrosoftAjax: Delta=true``,
   ``ctl00$ContentPlaceHolder1$ScriptManager1`` = painel|botão) →
   o painel ``upResultados`` volta no *delta* com a lista ``dlResultados``
   (10 itens por página) e os paginadores ``Pager1``/``Pager2``.
3. ``POST`` com ``__EVENTTARGET=ctl00$ContentPlaceHolder1$Pager1$lnkNext`` →
   página seguinte (o ``__VIEWSTATE``/``__EVENTVALIDATION`` a enviar são os que
   vieram no delta da resposta anterior).

**Não há captcha** neste serviço (ao contrário das publicações societárias).
O portal limita os pedidos (daí o ``min_interval``) e o intervalo de datas é
livre — mas cada página traz apenas 10 documentos, pelo que uma recolha de um
mês pode valer centenas de páginas.

Notas
-----
- As datas do formulário usam a máscara ``dd/mm/aaaa`` (não ISO).
- ``ddlTribunais`` traz os valores **cifrados** pelo portal (base64 do .NET);
  por isso a escolha do tribunal faz-se pelo **rótulo** (comparação normalizada).
- Cada item tem um ``queryString`` (token cifrado) que abre o documento PDF em
  ``Viewer/MostraPdf.aspx``. O token está ligado à sessão, pelo que o documento
  só é acessível com os cookies da mesma sessão.
"""
from __future__ import annotations

import hashlib
import logging
import re
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

BASE = "https://www.citius.mj.pt/portal/consultas/"
PAGE = BASE + "ConsultasCire.aspx"
DOCUMENTO_PAGE = BASE + "Viewer/MostraPdf.aspx"

FIELD_PREFIX = "ctl00$ContentPlaceHolder1$"
SCRIPT_MANAGER = FIELD_PREFIX + "ScriptManager1"
PANEL_UPDATE = FIELD_PREFIX + "UpdatePanel1"
PANEL_RESULTS = FIELD_PREFIX + "upResultados"
BUTTON_SEARCH = FIELD_PREFIX + "btnSearch"
PAGER_NEXT = FIELD_PREFIX + "Pager1$lnkNext"

PAGE_SIZE = 10
MIN_REQUEST_INTERVAL = 1.2

# Intervalos rápidos do formulário (rblDias).
DIAS_OPCOES: Dict[str, str] = {
    "15": "Últimos 15 dias",
    "30": "Últimos 30 dias",
    "todos": "Todos",
}

# Grupos de atos (ddlGrupoActos).
GRUPOS_ACTOS: Dict[str, str] = {
    "20": "Publicidade da Insolvência",
    "24": "Anúncios",
    "25": "Atos do Administrador da Insolvência",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8",
    "X-MicrosoftAjax": "Delta=true",
    "X-Requested-With": "XMLHttpRequest",
}

# Tipos de registo dos deltas ASP.NET: ``comprimento|tipo|id|conteúdo|``.
_DELTA_TYPES = (
    "updatePanel|hiddenField|script|arrayDeclaration|asyncPostBackControlIDs|postBackControlIDs|"
    "updatePanelIDs|childUpdatePanelIDs|panelsToRefreshIDs|asyncPostBackTimeout|formAction|pageTitle|"
    "pageRedirect|focus"
)
_DELTA_RECORD = re.compile(r"(\d+)\|(" + _DELTA_TYPES + r")\|([^|]*)\|")


class CireError(RuntimeError):
    """Erro na comunicação com o CIRE."""


def _clean(fragment: str) -> str:
    """Remove tags, entidades e espaços repetidos de um fragmento HTML."""
    from html import unescape

    text = re.sub(r"<[^>]+>", " ", fragment or "")
    text = unescape(text).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def _fold(value: str) -> str:
    """Minúsculas sem acentos (para comparar rótulos de selects)."""
    text = unicodedata.normalize("NFKD", (value or "").strip().lower())
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def _iso_date(value: str) -> Optional[str]:
    """Converte ``dd/mm/aaaa`` (formato do portal) em ISO 8601."""
    value = (value or "").strip()
    if not value:
        return None
    m = re.match(r"^(\d{2})[/-](\d{2})[/-](\d{4})$", value)
    if not m:
        return value
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"


def _br_date(value: str) -> Optional[str]:
    """Converte ISO 8601 (ou ``dd/mm/aaaa``) no formato do formulário."""
    value = (value or "").strip()
    if not value:
        return None
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", value)
    if m:
        return f"{m.group(3)}/{m.group(2)}/{m.group(1)}"
    return value


def parse_delta(text: str) -> Dict[str, str]:
    """Lê o *delta* ASP.NET e devolve ``{id: conteúdo}``.

    Os ids dos painéis vêm com ``_`` (o ``$`` do ``UniqueID`` é substituído),
    por isso também ficam disponíveis sob ``tipo:id``.
    """
    out: Dict[str, str] = {}
    for m in _DELTA_RECORD.finditer(text or ""):
        length = int(m.group(1))
        kind, ident = m.group(2), m.group(3)
        content = text[m.end(): m.end() + length]
        out[ident] = content
        out[f"{kind}:{ident}"] = content
    return out


def panel(delta: Dict[str, str], suffix: str) -> str:
    """Conteúdo do painel cujo id termina em ``suffix``."""
    return next((v for k, v in delta.items() if k.endswith(suffix)), "")


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
    for opt in re.finditer(r"<option[^>]*value=\"([^\"]*)\"[^>]*>(.*?)</option>", m.group(1), re.S | re.I):
        out.append({"value": opt.group(1), "label": _clean(opt.group(2))})
    return out


def _option_value(options: Iterable[Dict[str, str]], wanted: str) -> Optional[str]:
    """Valor da opção cujo rótulo corresponde a ``wanted`` (exato e depois parcial)."""
    wanted_fold = _fold(wanted)
    if not wanted_fold:
        return None
    exact = [o for o in options if _fold(o.get("label", "")) == wanted_fold]
    if exact:
        return exact[0]["value"]
    partial = [o for o in options if wanted_fold in _fold(o.get("label", ""))]
    return partial[0]["value"] if partial else None


def _especie_tipo(especie: str) -> Optional[str]:
    """Classifica a espécie do processo (Insolvência, PER, PEAP, PEVE, …)."""
    text = _fold(especie)
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


@dataclass
class PublicacaoCire:
    """Uma publicação do CIRE (uma linha da lista ``dlResultados``)."""

    referencia: str
    data_publicacao: Optional[str] = None
    tribunal: Optional[str] = None
    tribunal_comarca: Optional[str] = None
    tribunal_sede: Optional[str] = None
    ato: Optional[str] = None
    processo: Optional[str] = None
    processo_numero: Optional[str] = None
    juizo: Optional[str] = None
    especie: Optional[str] = None
    tipo: Optional[str] = None
    data_propositura: Optional[str] = None
    intervenientes: List[Dict[str, Any]] = field(default_factory=list)
    doc_token: Optional[str] = None
    texto: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)
    source: str = "citius_cire"

    @property
    def pub_id(self) -> str:
        """Identificador estável (idempotência das reingestões)."""
        key = "|".join(
            [
                str(self.referencia or ""),
                str(self.processo or self.processo_numero or ""),
                str(self.data_publicacao or ""),
                str(self.ato or ""),
            ]
        )
        return hashlib.sha1(key.encode("utf-8")).hexdigest()

    @property
    def insolvente(self) -> Optional[str]:
        """Nome do primeiro interveniente com papel de insolvente/devedor."""
        for item in self.intervenientes:
            papel = _fold(str(item.get("papel") or ""))
            if papel.startswith("insolvente") or "devedor" in papel:
                return item.get("nome")
        return self.intervenientes[0].get("nome") if self.intervenientes else None

    def nifs(self) -> List[str]:
        seen: List[str] = []
        for item in self.intervenientes:
            nif = str(item.get("nif") or "").strip()
            if nif and nif not in seen:
                seen.append(nif)
        return seen

    def to_dict(self) -> Dict[str, Any]:
        """Documento pronto para o índice Elasticsearch (sem valores nulos)."""
        data = {
            "pub_id": self.pub_id,
            "referencia": self.referencia,
            "data_publicacao": self.data_publicacao,
            "tribunal": self.tribunal,
            "tribunal_comarca": self.tribunal_comarca,
            "tribunal_sede": self.tribunal_sede,
            "ato": self.ato,
            "processo": self.processo,
            "processo_numero": self.processo_numero,
            "juizo": self.juizo,
            "especie": self.especie,
            "tipo": self.tipo,
            "data_propositura": self.data_propositura,
            "intervenientes": self.intervenientes,
            "insolvente": self.insolvente,
            "nifs": self.nifs(),
            "has_documento": bool(self.doc_token),
            "documento_url": self.documento_url(),
            "texto": self.texto,
            "source": self.source,
        }
        if self.extra:
            data["extra"] = self.extra
        return {k: v for k, v in data.items() if v not in (None, "", [], {})}

    def documento_url(self) -> Optional[str]:
        """URL do documento (PDF) da publicação — requer os cookies da sessão."""
        if not self.doc_token:
            return None
        return f"{DOCUMENTO_PAGE}?{self.doc_token}"


LABELS = {
    "tribunal": "Tribunal",
    "ato": "Ato",
    "referencia": "Referência",
    "processo": "Processo",
    "especie": "Espécie",
    "data": "Data",
    "data_propositura": "Data da propositura da ação",
}


def parse_items(results_html: str) -> List[PublicacaoCire]:
    """Extrai as publicações do HTML do painel ``upResultados``.

    Cada publicação é um ``div.resultadocdital`` com pares
    ``<strong>Rótulo:</strong> valor`` seguidos dos intervenientes
    (``span`` com ``..._InterDataList``), cada um com nome e NIF/NIPC.
    """
    import lxml.html

    if not results_html:
        return []

    doc = lxml.html.fromstring(results_html)
    out: List[PublicacaoCire] = []
    for node in doc.xpath('//div[contains(concat(" ", normalize-space(@class), " "), " resultadocdital ")]'):
        pub = _item_from_node(node)
        if pub and pub.referencia:
            out.append(pub)
    return out


def _item_from_node(node: Any) -> Optional[PublicacaoCire]:
    """Converte um ``div.resultadocdital`` numa ``PublicacaoCire``.

    O item é ``<strong>Rótulo:</strong> valor <br /> …`` seguido dos
    intervenientes (``span`` ``…_InterDataList``, um ``span`` por pessoa) e do
    painel do documento (``…_pnlPDF`` com o ``queryString``).
    """
    import lxml.html

    # Intervenientes: span externo ..._InterDataList com um <span> por pessoa.
    intervenientes: List[Dict[str, Any]] = []
    blocos = node.xpath('.//span[contains(@id, "InterDataList")]')
    for outer in blocos:
        inner_spans = [s for s in outer.xpath("./span") if isinstance(s.tag, str)]
        for inner in inner_spans or [outer]:
            text = _clean(inner.text_content())
            nome_match = re.match(
                r"^(?P<papel>[^:]+):\s*(?P<nome>.*?)(?:\s*NIF/NIPC:\s*(?P<nif>[\w\-/]+))?$",
                text,
            )
            if not nome_match or not nome_match.group("nome"):
                continue
            intervenientes.append(
                {
                    "papel": nome_match.group("papel").strip(),
                    "nome": nome_match.group("nome").strip(),
                    "nif": (nome_match.group("nif") or None),
                }
            )

    documento = node.xpath('.//input[contains(@id, "queryString")]/@value')
    token = documento[0].replace("&amp;", "&") if documento else None

    # Campos simples: retirar do HTML os blocos já tratados (intervenientes e
    # documento) e ler «Rótulo: valor» linha a linha.
    for outer in blocos:
        parent = outer.getparent()
        if parent is not None:
            parent.remove(outer)
    for pnl in node.xpath('.//div[contains(@id, "_pnlPDF")]'):
        parent = pnl.getparent()
        if parent is not None:
            parent.remove(pnl)

    flat = lxml.html.tostring(node, encoding="unicode")
    flat = re.sub(r"<br\s*/?>", "\n", flat, flags=re.I)
    flat = re.sub(r"<strong>(.*?)</strong>", r"\n@@\1@@\n", flat, flags=re.S | re.I)
    flat = re.sub(r"<[^>]+>", " ", flat)

    fields: Dict[str, str] = {}
    linhas = [_clean(line) for line in flat.split("\n")]
    for i, linha in enumerate(linhas):
        m = re.match(r"^@@(.*?)@@$", linha)
        if not m:
            continue
        label = m.group(1).replace("&nbsp;", " ").strip().rstrip(":").strip()
        values = [l for l in linhas[i + 1:] if l]
        if label and values:
            fields.setdefault(label, values[0])

    referencia = fields.get("Referência") or fields.get("Referencia")
    if not referencia:
        return None

    processo = fields.get("Processo")
    processo_numero, juizo = _split_processo(processo)
    tribunal = fields.get("Tribunal")
    comarca, sede = _split_tribunal(tribunal)
    especie = fields.get("Espécie") or fields.get("Especie")

    known = set(LABELS.values())
    extra = {k: v for k, v in fields.items() if k not in known and v}

    return PublicacaoCire(
        referencia=referencia,
        data_publicacao=_iso_date(fields.get(LABELS["data"], "")),
        tribunal=tribunal,
        tribunal_comarca=comarca,
        tribunal_sede=sede,
        ato=fields.get(LABELS["ato"]),
        processo=processo,
        processo_numero=processo_numero,
        juizo=juizo,
        especie=especie,
        tipo=_especie_tipo(especie or ""),
        data_propositura=_iso_date(fields.get(LABELS["data_propositura"], "")),
        intervenientes=intervenientes,
        doc_token=token,
        extra=extra,
    )


def _split_processo(processo: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Separa «1401/26.0T8ACB, Juízo de Comércio de Leiria - Juiz 2»."""
    if not processo:
        return None, None
    partes = [p.strip() for p in processo.split(",", 1)]
    numero = partes[0] or None
    juizo = partes[1] if len(partes) > 1 and partes[1] else None
    return numero, juizo


def _split_tribunal(tribunal: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Separa «Comarca de Leiria - Leiria» em comarca e sede."""
    if not tribunal:
        return None, None
    partes = [p.strip() for p in tribunal.split(" - ", 1)]
    comarca = partes[0] or None
    sede = partes[1] if len(partes) > 1 and partes[1] else None
    return comarca, sede


def result_count(results_html: str) -> int:
    """Total de documentos declarado pelo portal (``N documentos encontrados``)."""
    m = re.search(r"([\d\.\s]+)\s+documentos encontrados", _clean(results_html or ""))
    if not m:
        return 0
    digits = re.sub(r"\D", "", m.group(1))
    return int(digits) if digits else 0


def current_page(results_html: str) -> int:
    """Número da página atual do paginador (1 se não encontrar)."""
    m = re.search(r'Pager1_lblPageNumber"[^>]*>\s*(\d+)\s*<', results_html or "")
    return int(m.group(1)) if m else 1


def has_next_page(results_html: str) -> bool:
    """Indica se o paginador superior tem ligação para a página seguinte."""
    return bool(re.search(r'Pager1_lnkNext', results_html or ""))


class CireClient:
    """Cliente do serviço CIRE (pesquisa, paginação e documento).

    Uso::

        with CireClient(min_interval=1.5) as client:
            page = client.search(desde="2026-09-01", ate="2026-09-30")
            for pub in page.items:
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
        self._state: Dict[str, str] = {}
        self._options: Dict[str, List[Dict[str, str]]] = {}
        self._last_request = 0.0
        self.pages_fetched = 0

    # --- ciclo de vida -------------------------------------------------
    def __enter__(self) -> "CireClient":
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

    def _get(self, url: str = PAGE, *, retries: int = 3) -> str:
        last: Optional[Exception] = None
        for attempt in range(retries):
            self._throttle()
            try:
                resp = self.session.get(url, timeout=self.timeout, headers={"Referer": PAGE})
                self._last_request = time.monotonic()
                resp.raise_for_status()
                return resp.content.decode("utf-8", errors="replace")
            except Exception as exc:  # noqa: BLE001
                last = exc
                time.sleep(1.5 * (attempt + 1))
        raise CireError(f"Falha a obter {url}: {last}")

    def _post(self, data: Dict[str, str], *, retries: int = 3, raw: bool = False) -> str:
        last: Optional[Exception] = None
        for attempt in range(retries):
            self._throttle()
            try:
                resp = self.session.post(
                    PAGE, data=data, timeout=self.timeout, headers={"Referer": PAGE}
                )
                self._last_request = time.monotonic()
                resp.raise_for_status()
                if raw:
                    return resp.content.decode("utf-8", errors="replace")
                text = resp.content.decode("utf-8", errors="replace")
                if _blocked(text):
                    raise CireError("Pedido bloqueado pelo portal (WAF).")
                self.pages_fetched += 1
                return text
            except Exception as exc:  # noqa: BLE001
                last = exc
                time.sleep(2.0 * (attempt + 1))
        raise CireError(f"Falha no postback: {last}")

    def _payload(self, target: str, manager: str, **fields: Any) -> Dict[str, str]:
        """Corpo do postback assíncrono, com o estado corrente do formulário."""
        data = dict(self._state)
        data[SCRIPT_MANAGER] = manager
        data["__EVENTTARGET"] = target
        data["__EVENTARGUMENT"] = ""
        data.setdefault("__LASTFOCUS", "")
        data.setdefault("__VIEWSTATEENCRYPTED", "")
        data.update(
            {
                FIELD_PREFIX + "txtPesquisa": "",
                FIELD_PREFIX + "rblTipo": "nif",
                FIELD_PREFIX + "txtNumeroProcesso": "",
                FIELD_PREFIX + "txtCalendarDesde": "",
                FIELD_PREFIX + "txtCalendarAte": "",
                FIELD_PREFIX + "ddlTribunais": "",
                FIELD_PREFIX + "ddlGrupoActos": "",
                FIELD_PREFIX + "ddlActos": "",
                FIELD_PREFIX + "rblDias": "todos",
                "__ASYNCPOST": "true",
            }
        )
        for key, value in fields.items():
            if value is not None:
                data[key] = value
        return data

    def _absorb(self, delta: Dict[str, str], results_html: str) -> None:
        """Atualiza o estado do formulário com o que veio no delta."""
        for name in ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__EVENTVALIDATION", "__VIEWSTATEENCRYPTED"):
            value = delta.get(f"hiddenField:{name}")
            if value is not None:
                self._state[name] = value
        if results_html:
            self._state["__VIEWSTATEENCRYPTED"] = self._state.get("__VIEWSTATEENCRYPTED", "")

    # --- formulário ----------------------------------------------------
    def fetch_form(self) -> str:
        """Obtém o formulário e memoriza o estado (viewstate + opções dos selects)."""
        html = self._get(PAGE)
        self._state = form_state(html)
        self._options = {
            "ddlTribunais": parse_options(html, "ctl00_ContentPlaceHolder1_ddlTribunais"),
            "ddlGrupoActos": parse_options(html, "ctl00_ContentPlaceHolder1_ddlGrupoActos"),
            "ddlActos": parse_options(html, "ctl00_ContentPlaceHolder1_ddlActos"),
        }
        self.pages_fetched = 0
        return html

    @property
    def options(self) -> Dict[str, List[Dict[str, str]]]:
        """Opções dos selects (tribunais, grupos de atos e atos)."""
        return self._options

    def tribunais(self) -> List[Dict[str, str]]:
        """Lista de tribunais (``label`` legível; o ``value`` é cifrado pelo portal)."""
        return list(self._options.get("ddlTribunais", []))

    def actos(self) -> List[Dict[str, str]]:
        """Lista de atos disponíveis."""
        return list(self._options.get("ddlActos", []))

    # --- pesquisa ------------------------------------------------------
    def search(
        self,
        *,
        desde: Optional[str] = None,
        ate: Optional[str] = None,
        dias: Optional[str] = None,
        nif: Optional[str] = None,
        nome: Optional[str] = None,
        numero_processo: Optional[str] = None,
        tribunal: Optional[str] = None,
        grupo_actos: Optional[str] = None,
        acto: Optional[str] = None,
        fetch_options: bool = True,
    ) -> "CirePage":
        """Pesquisa publicações e devolve a primeira página de resultados.

        ``desde``/``ate`` aceitam ISO 8601 ou ``dd/mm/aaaa`` (o portal exige as
        duas datas, ou nenhuma). ``dias`` usa os atalhos do formulário
        (``"15"``, ``"30"``, ``"todos"``). ``tribunal`` e ``acto`` são comparados
        pelo **rótulo** (o valor cifrado é resolvido a partir do formulário).
        """
        if fetch_options or not self._state:
            self.fetch_form()

        if bool(desde) != bool(ate):
            raise ValueError("Indique as duas datas (início e fim) ou nenhuma.")
        if nome and nif:
            raise ValueError("Escolha pesquisa por NIF/NIPC ou por designação, não ambas.")
        if not any([desde, dias, nif, nome, numero_processo, tribunal]):
            # Sem critérios o portal não devolve nada: usar "todos".
            dias = dias or "todos"

        tipo = "nome" if nome else "nif"
        pesquisa = nome or nif or ""
        fields: Dict[str, Any] = {
            FIELD_PREFIX + "txtPesquisa": pesquisa,
            FIELD_PREFIX + "rblTipo": tipo,
            FIELD_PREFIX + "txtNumeroProcesso": numero_processo or "",
            FIELD_PREFIX + "txtCalendarDesde": _br_date(desde) or "",
            FIELD_PREFIX + "txtCalendarAte": _br_date(ate) or "",
            FIELD_PREFIX + "rblDias": dias or "todos",
        }
        if tribunal:
            value = _option_value(self._options.get("ddlTribunais", []), tribunal)
            if value is None:
                raise ValueError(f"Tribunal «{tribunal}» não encontrado no formulário.")
            fields[FIELD_PREFIX + "ddlTribunais"] = value
        if grupo_actos:
            code = str(grupo_actos)
            if code not in GRUPOS_ACTOS:
                raise ValueError("Grupo de atos inválido (use 20, 24 ou 25).")
            fields[FIELD_PREFIX + "ddlGrupoActos"] = code
        if acto:
            value = _option_value(self._options.get("ddlActos", []), acto)
            if value is None:
                raise ValueError(f"Ato «{acto}» não encontrado no formulário.")
            fields[FIELD_PREFIX + "ddlActos"] = value

        data = self._payload(BUTTON_SEARCH, f"{PANEL_UPDATE}|{BUTTON_SEARCH}", **fields)
        raw = self._post(data)
        delta = parse_delta(raw)
        results = panel(delta, "upResultados")
        self._absorb(delta, results)
        # O resultado pode vir vazio quando o postback não foi aceite; tentar de novo
        # com o formulário relido (acontece ocasionalmente com o WAF).
        if not results and not delta:
            self.fetch_form()
            data = self._payload(BUTTON_SEARCH, f"{PANEL_UPDATE}|{BUTTON_SEARCH}", **fields)
            delta = parse_delta(self._post(data))
            results = panel(delta, "upResultados")
            self._absorb(delta, results)
        return CirePage(
            items=parse_items(results),
            total=result_count(results),
            page=current_page(results),
            has_next=has_next_page(results),
            html=results,
        )

    def next_page(self) -> "CirePage":
        """Avança para a página seguinte da pesquisa corrente."""
        data = self._payload(PAGER_NEXT, f"{PANEL_RESULTS}|{PAGER_NEXT}")
        delta = parse_delta(self._post(data))
        results = panel(delta, "upResultados")
        self._absorb(delta, results)
        return CirePage(
            items=parse_items(results),
            total=result_count(results),
            page=current_page(results),
            has_next=has_next_page(results),
            html=results,
        )

    def collect(
        self,
        *,
        max_pages: int = 50,
        max_items: Optional[int] = None,
        on_page: Optional[Any] = None,
        stop: Optional[Any] = None,
        **criteria: Any,
    ) -> Tuple[List[PublicacaoCire], Dict[str, Any]]:
        """Percorre as páginas da pesquisa até ao limite e devolve os itens + resumo.

        ``on_page(page, items)`` é chamado a cada página (progresso) e ``stop()``
        (se devolver ``True``) interrompe a recolha.
        """
        page = self.search(**criteria)
        items: List[PublicacaoCire] = []
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

        summary = {
            "total": total,
            "pages": pages_done,
            "collected": len(items),
            "page_size": PAGE_SIZE,
        }
        return items, summary

    # --- documento -----------------------------------------------------
    def fetch_documento(self, token: str) -> bytes:
        """Descarrega o PDF de uma publicação (usa a sessão onde a pesquisa foi feita)."""
        url = f"{DOCUMENTO_PAGE}?{token}"
        self._throttle()
        resp = self.session.get(url, timeout=self.timeout, headers={"Referer": PAGE})
        resp.raise_for_status()
        return resp.content


@dataclass
class CirePage:
    """Uma página de resultados do CIRE."""

    items: List[PublicacaoCire]
    total: int = 0
    page: int = 1
    has_next: bool = False
    html: str = ""

    @property
    def pages_total(self) -> int:
        """Número estimado de páginas (10 documentos por página)."""
        return (self.total + PAGE_SIZE - 1) // PAGE_SIZE if self.total else 0


def _blocked(html: str) -> bool:
    """Deteta a página de bloqueio do WAF do CITIUS."""
    return "Something Went Wrong" in (html or "")[:4000]
