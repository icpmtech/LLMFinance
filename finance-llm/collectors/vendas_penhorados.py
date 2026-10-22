"""Coletor de **Venda de Bens Penhorados em Processos Executivos**.

Duas fontes oficiais, ambas públicas e sem captcha:

1. **CITIUS** — https://www.citius.mj.pt/portal/consultas/ConsultasVenda.aspx
   («Venda de Bens Penhorados em Processos Executivos»). Lista as vendas
   determinadas nos processos executivos, por **tribunal** e **intervalo de
   datas da venda**, com o tipo de bem, o estado (em venda, vendido, anulada,
   suspensa), o valor base, a modalidade (leilão eletrónico, carta fechada,
   negociação particular, …), a descrição, o processo, a espécie e os
   intervenientes (executados, com morada e telefone). O portal só deixa
   pesquisar uma janela de cerca de três meses em torno do dia de hoje.
2. **e-leiloes.pt** — https://www.e-leiloes.pt (vendas promovidas pelos agentes
   de execução). Tem uma API pública em ``/api/`` que devolve os eventos em
   JSON, com o processo, a comarca, o agente de execução, os executados (com
   NIF), a geolocalização, as fotografias e os ónus.

Fluxo do CITIUS (ASP.NET WebForms com ``UpdatePanel``, sem captcha)
------------------------------------------------------------------
1. ``GET ConsultasVenda.aspx`` → formulário com ``__VIEWSTATE``,
   ``__EVENTVALIDATION``, ``ddlTribunais`` (214 tribunais), os campos de data
   ``txtCalendarDesde``/``txtCalendarAte`` (``dd-mm-aaaa``), ``ddlTiposBem``,
   ``ddlModalidades`` e ``ddlEstados``.
2. ``POST`` assíncrono (``X-MicrosoftAjax: Delta=true``, ``__ASYNCPOST=true``)
   com ``<prefixo>btnSearch`` → resposta *delta* com o painel
   ``pnlUpdResults`` (10 bens por página) e o paginador ``Pager1``.
3. ``POST`` com ``__EVENTTARGET=<prefixo>Pager1$lnkNext`` → página seguinte
   (o ``__VIEWSTATE``/``__EVENTVALIDATION`` são os da resposta anterior).
4. ``POST ConsultasVenda.aspx/GetHtmlDetails`` com ``{"htmlId": <id>}`` → HTML
   com a descrição completa e os intervenientes (a lista trunca a descrição).

Notas
-----
- A **data da venda é obrigatória** no formulário (validação do servidor); a
  janela aceite é a que o próprio portal publica no calendário (cerca de um mês
  atrás e dois à frente).
- A página é UTF-8 (ao contrário das publicações societárias, que são
  Windows-1252) e o CITIUS serve por vezes a cadeia TLS **incompleta** — a
  reparação está em `collectors/tls_chain.py` e é usada neste cliente.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from html import unescape
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote

import requests

from collectors import tls_chain

logger = logging.getLogger(__name__)

# --------------------------------------------------------------- CITIUS
CITIUS_BASE = "https://www.citius.mj.pt/portal/consultas/"
CITIUS_PAGE = CITIUS_BASE + "ConsultasVenda.aspx"
CITIUS_DETAILS = CITIUS_PAGE + "/GetHtmlDetails"

FIELD_PREFIX = "ctl00$ContentPlaceHolder1$"
BUTTON_SEARCH = FIELD_PREFIX + "btnSearch"
FIELD_TRIBUNAL = FIELD_PREFIX + "ddlTribunais"
FIELD_DESDE = FIELD_PREFIX + "txtCalendarDesde"
FIELD_ATE = FIELD_PREFIX + "txtCalendarAte"
FIELD_IGNORAR_DATAS = FIELD_PREFIX + "chkDatas"
FIELD_TIPO = FIELD_PREFIX + "ddlTiposBem"
FIELD_MODALIDADE = FIELD_PREFIX + "ddlModalidades"
FIELD_ESTADO = FIELD_PREFIX + "ddlEstados"
PAGER_NEXT = FIELD_PREFIX + "Pager1$lnkNext"

CITIUS_PAGE_SIZE = 10
CITIUS_MIN_INTERVAL = 1.2

CITIUS_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8",
}

#: Estados do formulário do CITIUS (``ddlEstados``).
CITIUS_ESTADOS: Dict[str, str] = {
    "em_venda": "927",
    "vendido": "928",
    "suspensa": "929",
    "anulada": "930",
}

#: Tipos de bem do formulário (``ddlTiposBem``).
CITIUS_TIPOS_BEM: Dict[str, str] = {
    "imovel": "1",
    "veiculo": "2",
    "bem_movel": "3",
    "quota_sociedade": "4",
    "titulo_nao_depositado": "7",
    "outro_direito": "9",
    "aeronave": "10",
    "navio_embarcacao": "11",
    "valor_mobiliario_depositado": "14",
    "estabelecimento_comercial": "15",
}

# --------------------------------------------------------------- e-leiloes
ELEILOES_BASE = "https://www.e-leiloes.pt"
ELEILOES_PAGE = ELEILOES_BASE + "/index.aspx"
ELEILOES_API = ELEILOES_BASE + "/api/"
ELEILOES_PAGE_SIZE = 12
ELEILOES_MIN_INTERVAL = 0.8

ELEILOES_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8",
}


class VendasError(RuntimeError):
    """Erro na comunicação com um dos portais de vendas."""


# ------------------------------------------------------------------ utilidades
def _clean(fragment: str) -> str:
    """Remove tags/entidades HTML e normaliza espaços."""
    text = re.sub(r"<[^>]+>", " ", fragment or "")
    text = unescape(text).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def _fold(value: str) -> str:
    """Minúsculas sem acentos (comparar rótulos das opções)."""
    import unicodedata

    text = unicodedata.normalize("NFKD", (value or "").strip().lower())
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def _pt_number(value: Optional[str]) -> Optional[float]:
    """Converte «220 000,00 €» (formato português) em ``220000.0``."""
    if value is None:
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


def _iso_from_ddmmyyyy(value: Optional[str], *, with_time: bool = False) -> Optional[str]:
    """Converte «22/10/2026» ou «22/10/2026 13:45:00» em ISO 8601."""
    text = (value or "").strip()
    if not text:
        return None
    match = re.match(
        r"^(\d{2})[/-](\d{2})[/-](\d{4})(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?)?$", text
    )
    if not match:
        return text
    dia, mes, ano, hora, minuto, segundo = match.groups()
    if with_time and hora:
        return f"{ano}-{mes}-{dia}T{hora}:{minuto}:{segundo or '00'}"
    return f"{ano}-{mes}-{dia}"


def _portal_date(value: Optional[str]) -> str:
    """Data ISO (``AAAA-MM-DD`` ou ``AAAA-MM-DDTHH:MM:SS``) → ``dd-mm-aaaa``."""
    text = (value or "").strip()
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})", text)
    if not match:
        return text
    return f"{match.group(3)}-{match.group(2)}-{match.group(1)}"


def _split_processo(processo: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Separa «7150/24.6T8PRT, Juízo de Execução do Porto - Juiz 5»."""
    if not processo:
        return None, None
    parte = str(processo)
    for separador in (",", " - ", " – "):
        if separador in parte:
            numero, resto = parte.split(separador, 1)
            return numero.strip() or None, resto.strip() or None
    return parte.strip() or None, None


def _split_tribunal(tribunal: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Separa «Porto - Tribunal Judicial da Comarca do Porto» em (sede, serviço)."""
    if not tribunal:
        return None, None
    partes = [item.strip() for item in str(tribunal).split(" - ", 1)]
    return (partes[0] or None), (partes[1] if len(partes) > 1 and partes[1] else None)


def comarca_judicial(tribunal: Optional[str], sede: Optional[str] = None) -> Optional[str]:
    """Comarca judicial a partir do serviço («… da Comarca de Santarém» → «Santarém»)."""
    texto = f"{tribunal or ''} | {sede or ''}"
    match = re.search(r"Comarca\s+d(?:e|a|o)\s+([^,|]+)", texto, re.I)
    if match:
        return re.sub(r"\s+", " ", match.group(1)).strip()
    partes = [item.strip() for item in (tribunal or "").split(" - ", 1)]
    return partes[0] or None


def default_window(dias_atras: int = 30, dias_frente: int = 62) -> Tuple[str, str]:
    """Janela de datas por omissão (a que o calendário do CITIUS aceita)."""
    hoje = date.today()
    return (
        (hoje - timedelta(days=dias_atras)).isoformat(),
        (hoje + timedelta(days=dias_frente)).isoformat(),
    )


def json_date(value: Optional[str]) -> Optional[str]:
    """Data/hora da API do e-leiloes (``2026-10-22T14:30:00``) → ISO."""
    if not value:
        return None
    text = str(value).strip()
    return text if re.match(r"^\d{4}-\d{2}-\d{2}", text) else None


# --------------------------------------------------------------------- modelo
@dataclass
class VendaPenhorada:
    """Um bem penhorado com venda determinada (documento unificado das duas fontes)."""

    venda_id: str
    fonte: str
    referencia: Optional[str] = None
    tribunal: Optional[str] = None
    tribunal_sede: Optional[str] = None
    comarca_judicial: Optional[str] = None
    processo: Optional[str] = None
    processo_numero: Optional[str] = None
    juizo: Optional[str] = None
    especie: Optional[str] = None
    tipo_bem: Optional[str] = None
    subtipo_bem: Optional[str] = None
    modalidade: Optional[str] = None
    estado: Optional[str] = None
    titulo: Optional[str] = None
    descricao: Optional[str] = None
    valor_base: Optional[float] = None
    valor_minimo: Optional[float] = None
    valor_abertura: Optional[float] = None
    lance_atual: Optional[float] = None
    data_venda: Optional[str] = None
    data_inicio: Optional[str] = None
    data_fim: Optional[str] = None
    distrito: Optional[str] = None
    concelho: Optional[str] = None
    freguesia: Optional[str] = None
    morada: Optional[str] = None
    codigo_postal: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    intervenientes: List[Dict[str, Any]] = field(default_factory=list)
    executados: List[Dict[str, Any]] = field(default_factory=list)
    gestor: Dict[str, Any] = field(default_factory=dict)
    fotos: List[str] = field(default_factory=list)
    onus: List[Any] = field(default_factory=list)
    detalhe_url: Optional[str] = None
    url: Optional[str] = None
    data_atualizacao: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)
    source: str = "vendas_penhorados"

    def to_dict(self) -> Dict[str, Any]:
        """Documento pronto para JSON/Elasticsearch (sem valores vazios)."""
        data: Dict[str, Any] = {
            "venda_id": self.venda_id,
            "fonte": self.fonte,
            "referencia": self.referencia,
            "tribunal": self.tribunal,
            "tribunal_sede": self.tribunal_sede,
            "comarca_judicial": self.comarca_judicial,
            "processo": self.processo,
            "processo_numero": self.processo_numero,
            "juizo": self.juizo,
            "especie": self.especie,
            "tipo_bem": self.tipo_bem,
            "subtipo_bem": self.subtipo_bem,
            "modalidade": self.modalidade,
            "estado": self.estado,
            "titulo": self.titulo,
            "descricao": self.descricao,
            "valor_base": self.valor_base,
            "valor_minimo": self.valor_minimo,
            "valor_abertura": self.valor_abertura,
            "lance_atual": self.lance_atual,
            "data_venda": self.data_venda,
            "data_inicio": self.data_inicio,
            "data_fim": self.data_fim,
            "distrito": self.distrito,
            "concelho": self.concelho,
            "freguesia": self.freguesia,
            "morada": self.morada,
            "codigo_postal": self.codigo_postal,
            "lat": self.lat,
            "lon": self.lon,
            "intervenientes": self.intervenientes,
            "executados": self.executados,
            "gestor": self.gestor,
            "fotos": self.fotos,
            "onus": self.onus,
            "detalhe_url": self.detalhe_url,
            "url": self.url,
            "data_atualizacao": self.data_atualizacao,
            "extra": self.extra,
            "source": self.source,
        }
        return {key: value for key, value in data.items() if value not in (None, "", [], {})}

    @property
    def pub_id(self) -> str:
        """Identificador estável (idempotência das reindexações)."""
        if self.venda_id:
            return self.venda_id
        chave = "|".join(
            [
                str(self.fonte or ""),
                str(self.referencia or ""),
                str(self.processo or ""),
                str(self.data_venda or ""),
                str(self.titulo or ""),
            ]
        )
        return hashlib.sha1(chave.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------ CITIUS util
def form_state(html: str) -> Dict[str, str]:
    """Campos escondidos do formulário (``__VIEWSTATE`` e companhia)."""

    def _value(name: str) -> str:
        match = re.search(r'id="' + re.escape(name) + r'"[^>]*value="([^"]*)"', html or "")
        return match.group(1) if match else ""

    return {
        "__EVENTTARGET": _value("__EVENTTARGET"),
        "__EVENTARGUMENT": _value("__EVENTARGUMENT"),
        "__LASTFOCUS": _value("__LASTFOCUS"),
        "__VIEWSTATE": _value("__VIEWSTATE"),
        "__VIEWSTATEGENERATOR": _value("__VIEWSTATEGENERATOR"),
        "__VIEWSTATEENCRYPTED": _value("__VIEWSTATEENCRYPTED"),
        "__EVENTVALIDATION": _value("__EVENTVALIDATION"),
    }


def delta_state(text: str) -> Dict[str, str]:
    """Campos escondidos devolvidos numa resposta *delta* do ``UpdatePanel``."""
    out: Dict[str, str] = {}
    for name in ("__VIEWSTATE", "__VIEWSTATEGENERATOR", "__VIEWSTATEENCRYPTED", "__EVENTVALIDATION"):
        match = re.search(r"hiddenField\|" + re.escape(name) + r"\|([^|]*)\|", text or "")
        if match and match.group(1):
            out[name] = match.group(1)
    return out


def parse_options(html: str, select_id: str) -> List[Dict[str, str]]:
    """Opções de um ``<select>`` (``value`` + ``label``), pela ordem do HTML."""
    match = re.search(
        r'<select[^>]*id="' + re.escape(select_id) + r'"(.*?)</select>', html or "", re.S | re.I
    )
    if not match:
        return []
    out: List[Dict[str, str]] = []
    for option in re.finditer(
        r'<option[^>]*value="([^"]*)"[^>]*>(.*?)</option>', match.group(1), re.S | re.I
    ):
        out.append({"value": option.group(1), "label": _clean(option.group(2))})
    return out


def delta_panel(text: str) -> str:
    """HTML do painel ``pnlUpdResults`` numa resposta *delta* (ou página inteira)."""
    if not text:
        return ""
    match = re.search(
        r"updatePanel\|ctl00_ContentPlaceHolder1_pnlUpdResults\|(.*?)\|0\|hiddenField", text, re.S
    )
    if match:
        return match.group(1)
    # Resposta de página inteira (o servidor não devolveu *delta*).
    match = re.search(
        r'id="ctl00_ContentPlaceHolder1_pnlResults"(.*?)(?:<div id="ctl00_ContentPlaceHolder1_AjaxLoadingAnimation|</form>)',
        text,
        re.S,
    )
    if match:
        return match.group(0)
    match = re.search(r'id="ctl00_ContentPlaceHolder1_pnlUpdResults"(.*?)</div>\s*<div id="ctl00_ContentPlaceHolder1_AjaxLoadingAnimation', text, re.S)
    return match.group(1) if match else ""


def result_count(panel: str) -> int:
    """«Numero de Registos: N» do painel de resultados."""
    match = re.search(r"Numero de Registos:\s*(\d+)", panel or "")
    return int(match.group(1)) if match else 0


def current_page(panel: str) -> int:
    """Número da página atual (1 se não encontrar)."""
    match = re.search(r'Pager\d_lblPageNumber"[^>]*>\s*(\d+)\s*<', panel or "")
    return int(match.group(1)) if match else 1


def has_next_page(panel: str) -> bool:
    """Indica se o paginador tem ligação para a página seguinte."""
    return bool(re.search(r'Pager\d_lnkNext"', panel or ""))


def _blocked(text: str) -> bool:
    """Deteta a página de bloqueio do WAF do CITIUS."""
    return "Something Went Wrong" in (text or "")[:4000]


def _label_value(fragment: str, label: str) -> Optional[str]:
    """Valor de um par ``<strong>Label:</strong> valor<br/>``."""
    match = re.search(
        r"<strong[^>]*>\s*" + re.escape(label) + r"\s*:?\s*(?:&nbsp;|\s)*</strong>(.*?)<br\s*/?>",
        fragment or "",
        re.S | re.I,
    )
    return _clean(match.group(1)) or None if match else None


def _pairs(fragment: str) -> Dict[str, str]:
    """Todos os pares ``<strong>Rótulo:</strong> valor<br/>`` de um bloco."""
    out: Dict[str, str] = {}
    for match in re.finditer(
        r"<strong[^>]*>(.*?)</strong>(.*?)<br\s*/?>", fragment or "", re.S | re.I
    ):
        rotulo = _clean(match.group(1)).rstrip(":").strip()
        valor = _clean(match.group(2))
        if rotulo and valor and rotulo not in out:
            out[rotulo] = valor
    return out


def parse_details(html: str) -> Dict[str, Any]:
    """Dados do painel «Detalhes do bem» (descrição completa + intervenientes)."""
    if not html:
        return {}
    texto = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    texto = unescape(re.sub(r"<[^>]+>", "", texto)).replace("\xa0", " ")

    linhas = [re.sub(r"[ \t]+", " ", linha).strip() for linha in texto.splitlines()]
    dados: Dict[str, Any] = {}
    mapa = {
        "tribunal": "Tribunal",
        "processo": "Processo",
        "especie": "Espécie",
        "tipo_bem": "Tipo de Bem",
        "valor_base": "Valor Base",
        "descricao": "Descrição do Bem",
        "data_venda": "Data da Venda",
    }
    for linha in linhas:
        if ":" not in linha:
            continue
        rotulo, valor = linha.split(":", 1)
        rotulo = rotulo.strip()
        valor = valor.strip()
        if not valor:
            continue
        for chave, etiqueta in mapa.items():
            if _fold(rotulo) == _fold(etiqueta) and chave not in dados:
                dados[chave] = valor

    intervenientes: List[Dict[str, Any]] = []
    marcador = r"<strong[^>]*>\s*Interveniente\s*:?\s*(?:&#160;|&nbsp;|\s)*</strong>"
    for bloco in re.split(marcador, html, flags=re.I)[1:]:
        # O bloco de um interveniente termina no marcador seguinte ou no fim.
        fim = re.search(marcador, bloco, re.I)
        if fim:
            bloco = bloco[: fim.start()]
        valores = _pairs(bloco)
        papel = None
        # O papel vem imediatamente a seguir ao rótulo «Interveniente», sem
        # `<strong>` próprio: apanha-se o texto antes do primeiro `<strong>`.
        match = re.match(r"(.*?)<strong", bloco, re.S)
        if match:
            papel = _clean(match.group(1)) or None
        nome = valores.get("Nome")
        if not nome and not papel:
            continue
        intervenientes.append(
            {
                "papel": papel,
                "nome": nome,
                "morada": valores.get("Morada"),
                "telefone": valores.get("Telefone"),
                "nif": valores.get("NIF"),
            }
        )

    if "valor_base" in dados:
        dados["valor_base"] = _pt_number(dados["valor_base"])
    if "data_venda" in dados:
        dados["data_venda"] = _iso_from_ddmmyyyy(dados["data_venda"], with_time=True)
    if "processo" in dados:
        numero, juizo = _split_processo(dados["processo"])
        dados.setdefault("processo_numero", numero)
        dados.setdefault("juizo", juizo)
    if intervenientes:
        dados["intervenientes"] = [
            {chave: valor for chave, valor in item.items() if valor} for item in intervenientes
        ]
    return dados


def parse_items(panel: str, *, tribunal: Optional[str] = None) -> List[VendaPenhorada]:
    """Extrai os bens da lista de resultados do CITIUS."""
    if not panel:
        return []
    items: List[VendaPenhorada] = []
    for bloco in re.split(r'<div class="resultadopubvenda">', panel, flags=re.I)[1:]:
        fragmento = bloco.split("</div>", 1)[0]
        valores = _pairs(fragmento)
        if not valores:
            continue
        html_id = None
        match = re.search(r"Viewer\.Abrir\(this,\s*(\d+),", bloco, re.I)
        if match:
            html_id = match.group(1)
        processo = valores.get("Processo")
        numero, juizo = _split_processo(processo)
        data_venda = _iso_from_ddmmyyyy(valores.get("Data da Venda"), with_time=True)
        item = VendaPenhorada(
            venda_id=f"citius:{html_id}" if html_id else "",
            fonte="citius",
            referencia=html_id,
            tribunal=tribunal or None,
            tribunal_sede=_split_tribunal(tribunal)[0],
            comarca_judicial=comarca_judicial(tribunal, _split_tribunal(tribunal)[0]),
            processo=processo,
            processo_numero=numero,
            juizo=juizo,
            especie=valores.get("Espécie"),
            tipo_bem=valores.get("Tipo de Bem"),
            modalidade=valores.get("Modalidade"),
            estado=valores.get("Estado"),
            descricao=valores.get("Descrição do Bem"),
            valor_base=_pt_number(valores.get("Valor Base")),
            data_venda=data_venda,
            detalhe_url=CITIUS_PAGE,
            url=CITIUS_PAGE,
            extra={"html_id": html_id} if html_id else {},
        )
        if not item.venda_id:
            item.venda_id = item.pub_id
        items.append(item)
    return items


# ---------------------------------------------------------------- cliente CITIUS
class CitiusVendasClient:
    """Cliente da consulta «Venda de Bens Penhorados» do CITIUS.

    Uso::

        with CitiusVendasClient() as client:
            client.fetch_form()
            for tribunal in client.tribunais():
                page = client.search(tribunal=tribunal["label"], desde="2026-09-21", ate="2026-12-21")
                for bem in page.items:
                    ...
    """

    def __init__(
        self,
        *,
        min_interval: float = CITIUS_MIN_INTERVAL,
        timeout: float = 60.0,
        connect_timeout: float = 15.0,
        deadline: float = 45.0,
        proxy: Optional[str] = None,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.min_interval = max(0.0, float(min_interval))
        self.timeout = timeout
        self.connect_timeout = connect_timeout
        self.deadline = deadline
        self.stalled = False
        self.proxy = proxy
        self.session = session or requests.Session()
        self.session.headers.update(CITIUS_HEADERS)
        if proxy:
            self.session.proxies.update({"http": proxy, "https": proxy})
        self.verify: Any = True
        self._state: Dict[str, str] = {}
        self._options: Dict[str, List[Dict[str, str]]] = {}
        self._last_request = 0.0
        self.pages_fetched = 0

    # --- ciclo de vida -------------------------------------------------
    def __enter__(self) -> "CitiusVendasClient":
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

    def _request(
        self,
        method: str,
        *,
        data: Optional[Dict[str, str]] = None,
        url: str = CITIUS_PAGE,
        json_body: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        """Pedido HTTP com prazo máximo (o portal já ficou minutos a «pingar»)."""
        caixa: Dict[str, Any] = {}

        def correr() -> None:
            try:
                caixa["resp"] = self.session.request(
                    method,
                    url,
                    data=data,
                    json=json_body,
                    timeout=(self.connect_timeout, self.timeout),
                    headers={"Referer": CITIUS_PAGE, **(headers or {})},
                    verify=self.verify,
                )
            except Exception as exc:  # noqa: BLE001
                caixa["erro"] = exc

        thread = threading.Thread(target=correr, name="citius-vendas", daemon=True)
        thread.start()
        thread.join(self.deadline)
        if thread.is_alive():
            self.stalled = True
            self.close()
            raise VendasError(
                f"Pedido sem resposta em {self.deadline:.0f}s (o portal não respondeu: a recolha para aqui)."
            )
        if caixa.get("erro") is not None:
            raise caixa["erro"]
        resp: requests.Response = caixa["resp"]
        resp.raise_for_status()
        return resp

    def _send(self, method: str, **kwargs: Any) -> str:
        last: Optional[Exception] = None
        for attempt in range(3):
            self._throttle()
            try:
                resp = self._request(method, **kwargs)
                self._last_request = time.monotonic()
                text = resp.content.decode("utf-8", errors="replace")
                if _blocked(text):
                    raise VendasError("Pedido bloqueado pelo portal do CITIUS (WAF).")
                self.pages_fetched += 1
                return text
            except requests.exceptions.SSLError as exc:
                last = exc
                if self._tls_retry(CITIUS_PAGE, exc):
                    continue
                if self.stalled:
                    break
                time.sleep(1.5 * (attempt + 1))
            except Exception as exc:  # noqa: BLE001
                last = exc
                if self.stalled:
                    break
                time.sleep(1.5 * (attempt + 1))
        raise VendasError(f"Falha no pedido ao CITIUS: {last}")

    def _payload(self, target: str = "", **fields: Any) -> Dict[str, str]:
        data = dict(self._state)
        data["__EVENTTARGET"] = target
        data["__EVENTARGUMENT"] = ""
        data.setdefault("__LASTFOCUS", "")
        data.setdefault("__VIEWSTATEENCRYPTED", "")
        data["__ASYNCPOST"] = "true"
        data["ctl00$ContentPlaceHolder1$ScriptManager1"] = (
            "ctl00$ContentPlaceHolder1$ScriptManager1|" + (target or BUTTON_SEARCH)
        )
        for key, value in fields.items():
            if value is not None:
                data[key] = value
        return data

    def _async_post(self, target: str = "", **fields: Any) -> str:
        headers = {
            "X-MicrosoftAjax": "Delta=true",
            "X-Requested-With": "XMLHttpRequest",
            "Cache-Control": "no-cache",
            "Origin": "https://www.citius.mj.pt",
        }
        return self._send("POST", data=self._payload(target, **fields), headers=headers)

    def _absorb(self, text: str) -> None:
        novo = delta_state(text)
        for name, value in novo.items():
            if value:
                self._state[name] = value

    # --- formulário ----------------------------------------------------
    def fetch_form(self) -> str:
        """Obtém o formulário e memoriza o estado e as opções dos ``select``."""
        html = self._send("GET", url=CITIUS_PAGE)
        self._state = form_state(html)
        self._state.setdefault("__VIEWSTATEENCRYPTED", "")
        self._options = {
            "tribunais": parse_options(html, "ctl00_ContentPlaceHolder1_ddlTribunais"),
            "tipos_bem": parse_options(html, "ctl00_ContentPlaceHolder1_ddlTiposBem"),
            "modalidades": parse_options(html, "ctl00_ContentPlaceHolder1_ddlModalidades"),
            "estados": parse_options(html, "ctl00_ContentPlaceHolder1_ddlEstados"),
        }
        self.pages_fetched = 0
        return html

    @property
    def options(self) -> Dict[str, List[Dict[str, str]]]:
        return self._options

    def tribunais(self) -> List[Dict[str, str]]:
        """Tribunais/serviços disponíveis (sem a opção «-Seleccione-»)."""
        return [item for item in self._options.get("tribunais", []) if item.get("value") != "0"]

    def tipos_bem(self) -> List[Dict[str, str]]:
        return list(self._options.get("tipos_bem", []))

    def modalidades(self) -> List[Dict[str, str]]:
        return list(self._options.get("modalidades", []))

    def estados(self) -> List[Dict[str, str]]:
        return list(self._options.get("estados", []))

    def _resolve_tribunal(self, tribunal: str) -> str:
        """Valor do ``select`` a partir do rótulo (exato e depois parcial)."""
        opcoes = self._options.get("tribunais", [])
        alvo = _fold(tribunal or "")
        exatos = [item for item in opcoes if _fold(item.get("label", "")) == alvo]
        if exatos:
            return exatos[0]["value"]
        parciais = [item for item in opcoes if alvo and alvo in _fold(item.get("label", ""))]
        if parciais:
            return parciais[0]["value"]
        if tribunal and tribunal.isdigit():
            return tribunal
        raise ValueError(f"Tribunal «{tribunal}» não encontrado no formulário do CITIUS.")

    def _resolve_option(self, key: str, value: Optional[str], label_field: str) -> str:
        """Traduz um tipo/modalidade/estado (chave ou rótulo) no valor do ``select``."""
        if value in (None, ""):
            return "0"
        texto = str(value).strip()
        if texto == "0":
            return "0"
        opcoes = self._options.get(key, [])
        alvo = _fold(texto)
        for item in opcoes:
            if _fold(item.get("label", "")) == alvo or item.get("value") == texto:
                return item["value"]
        aliases = {
            "tipos_bem": CITIUS_TIPOS_BEM,
            "estados": CITIUS_ESTADOS,
        }
        if key in aliases and alvo in aliases[key]:
            return aliases[key][alvo]
        raise ValueError(f"Valor «{value}» não encontrado em {label_field}.")

    # --- pesquisa ------------------------------------------------------
    def search(
        self,
        *,
        tribunal: str,
        desde: Optional[str] = None,
        ate: Optional[str] = None,
        tipo_bem: Optional[str] = None,
        modalidade: Optional[str] = None,
        estado: Optional[str] = None,
        fetch_options: bool = True,
    ) -> "VendasPage":
        """Pesquisa as vendas de **um tribunal** num intervalo de datas da venda."""
        desde_iso, ate_iso = desde, ate
        if not desde_iso or not ate_iso:
            desde_iso, ate_iso = default_window()
        if fetch_options or not self._state:
            self.fetch_form()
        tribunal_value = self._resolve_tribunal(tribunal)
        self._criteria = {
            "tribunal_value": tribunal_value,
            "tribunal": tribunal,
            "desde": _portal_date(desde_iso),
            "ate": _portal_date(ate_iso),
            "tipo": self._resolve_option("tipos_bem", tipo_bem, "ddlTiposBem"),
            "modalidade": self._resolve_option("modalidades", modalidade, "ddlModalidades"),
            "estado": self._resolve_option("estados", estado, "ddlEstados"),
        }
        text = self._async_post(
            BUTTON_SEARCH,
            **{
                FIELD_TRIBUNAL: self._criteria["tribunal_value"],
                FIELD_DESDE: self._criteria["desde"],
                FIELD_ATE: self._criteria["ate"],
                FIELD_TIPO: self._criteria["tipo"],
                FIELD_MODALIDADE: self._criteria["modalidade"],
                FIELD_ESTADO: self._criteria["estado"],
                BUTTON_SEARCH: "Pesquisar",
            },
        )
        self._absorb(text)
        panel = delta_panel(text)
        return VendasPage(
            items=parse_items(panel, tribunal=tribunal),
            total=result_count(panel),
            page=current_page(panel),
            has_next=has_next_page(panel),
            panel=panel,
        )

    def next_page(self) -> "VendasPage":
        """Avança para a página seguinte da pesquisa corrente."""
        if not getattr(self, "_criteria", None):
            raise VendasError("Não há pesquisa em curso para paginar.")
        text = self._async_post(
            PAGER_NEXT,
            **{
                FIELD_TRIBUNAL: self._criteria["tribunal_value"],
                FIELD_DESDE: self._criteria["desde"],
                FIELD_ATE: self._criteria["ate"],
                FIELD_TIPO: self._criteria["tipo"],
                FIELD_MODALIDADE: self._criteria["modalidade"],
                FIELD_ESTADO: self._criteria["estado"],
            },
        )
        self._absorb(text)
        panel = delta_panel(text)
        return VendasPage(
            items=parse_items(panel, tribunal=self._criteria.get("tribunal")),
            total=result_count(panel),
            page=current_page(panel),
            has_next=has_next_page(panel),
            panel=panel,
        )

    def collect(
        self,
        *,
        tribunais: Optional[List[str]] = None,
        desde: Optional[str] = None,
        ate: Optional[str] = None,
        tipo_bem: Optional[str] = None,
        modalidade: Optional[str] = None,
        estado: Optional[str] = None,
        max_pages_per_tribunal: int = 50,
        max_items: Optional[int] = None,
        with_details: bool = True,
        details_reserve: int = 400,
        concurrency_note: Optional[str] = None,
        on_page: Optional[Callable[["VendasPage", List[VendaPenhorada]], None]] = None,
        stop: Optional[Callable[[], bool]] = None,
    ) -> Tuple[List[VendaPenhorada], Dict[str, Any]]:
        """Percorre os tribunais indicados (ou todos) e devolve bens + resumo.

        ``on_page(page, items)`` é chamado a cada página (progresso) e ``stop()``
        interrompe a recolha. Com ``with_details`` a descrição completa e os
        intervenientes de cada bem são pedidos ao endpoint ``GetHtmlDetails``
        (uma chamada por bem, limitada por ``details_reserve``).
        """
        del concurrency_note  # a recolha é sequencial nesta sessão (o viewstate é uma cadeia)
        desde = desde or default_window()[0]
        ate = ate or default_window()[1]
        alvo = tribunais or [item["label"] for item in self.tribunais()]
        itens: List[VendaPenhorada] = []
        vistos: set[str] = set()
        paginas = 0
        erros: List[str] = []
        por_tribunal: Dict[str, int] = {}
        detalhes = 0

        for tribunal in alvo:
            if stop and stop():
                break
            try:
                page = self.search(
                    tribunal=tribunal,
                    desde=desde,
                    ate=ate,
                    tipo_bem=tipo_bem,
                    modalidade=modalidade,
                    estado=estado,
                    fetch_options=False,
                )
            except Exception as exc:  # noqa: BLE001
                erros.append(f"{tribunal}: {exc}")
                logger.warning("Vendas: falha no tribunal %s: %s", tribunal, exc)
                continue
            while True:
                if stop and stop():
                    break
                novos = [item for item in page.items if item.venda_id not in vistos]
                for item in novos:
                    vistos.add(item.venda_id)
                if novos and with_details and detalhes < details_reserve:
                    for item in novos:
                        if detalhes >= details_reserve:
                            break
                        try:
                            self.enrich(item)
                            detalhes += 1
                        except Exception as exc:  # noqa: BLE001
                            logger.debug("Vendas: detalhe de %s falhou: %s", item.venda_id, exc)
                itens.extend(novos)
                por_tribunal[tribunal] = por_tribunal.get(tribunal, 0) + len(novos)
                paginas += 1
                if on_page:
                    on_page(page, novos)
                if max_items and len(itens) >= max_items:
                    itens = itens[:max_items]
                    return itens, {
                        "tribunais": len(alvo),
                        "pages": paginas,
                        "collected": len(itens),
                        "with_details": detalhes,
                        "by_tribunal": por_tribunal,
                        "errors": erros,
                        "page_size": CITIUS_PAGE_SIZE,
                    }
                if paginas and max_pages_per_tribunal and page.page >= max_pages_per_tribunal:
                    break
                if not page.has_next or not page.items:
                    break
                try:
                    page = self.next_page()
                except Exception as exc:  # noqa: BLE001
                    erros.append(f"{tribunal} (paginação): {exc}")
                    break

        return itens, {
            "tribunais": len(alvo),
            "pages": paginas,
            "collected": len(itens),
            "with_details": detalhes,
            "by_tribunal": por_tribunal,
            "errors": erros,
            "page_size": CITIUS_PAGE_SIZE,
        }

    # --- detalhe -------------------------------------------------------
    def fetch_details(self, html_id: Any) -> Dict[str, Any]:
        """Descarrega o HTML do painel «Detalhes do bem» e extrai os dados."""
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
        }
        text = self._send(
            "POST", url=CITIUS_DETAILS, json_body={"htmlId": html_id}, headers=headers
        )
        try:
            payload = json.loads(text)
        except ValueError as exc:
            raise VendasError(f"Resposta inválida do detalhe do CITIUS: {exc}") from exc
        html = payload.get("d") or payload.get("D") or ""
        return parse_details(html)

    def enrich(self, item: VendaPenhorada) -> VendaPenhorada:
        """Preenche um bem com a descrição completa e os intervenientes."""
        html_id = item.extra.get("html_id") or item.referencia
        if not html_id:
            return item
        dados = self.fetch_details(html_id)
        for chave, valor in dados.items():
            if chave == "intervenientes":
                if valor:
                    item.intervenientes = valor
                    item.executados = [
                        {"papel": entry.get("papel"), "nome": entry.get("nome"), "nif": entry.get("nif")}
                        for entry in valor
                        if entry.get("nome")
                    ]
                continue
            atual = getattr(item, chave, None)
            if valor and not atual:
                setattr(item, chave, valor)
        return item


@dataclass
class VendasPage:
    """Uma página de resultados do CITIUS."""

    items: List[VendaPenhorada]
    total: int = 0
    page: int = 1
    has_next: bool = False
    panel: str = ""

    @property
    def pages_total(self) -> int:
        return (self.total + CITIUS_PAGE_SIZE - 1) // CITIUS_PAGE_SIZE if self.total else 0


# ------------------------------------------------------------- cliente e-leiloes
class EleiloesClient:
    """Cliente da API pública do e-leiloes.pt (vendas dos agentes de execução)."""

    def __init__(
        self,
        *,
        min_interval: float = ELEILOES_MIN_INTERVAL,
        timeout: float = 60.0,
        connect_timeout: float = 15.0,
        proxy: Optional[str] = None,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.min_interval = max(0.0, float(min_interval))
        self.timeout = timeout
        self.connect_timeout = connect_timeout
        self.proxy = proxy
        self.session = session or requests.Session()
        self.session.headers.update(ELEILOES_HEADERS)
        if proxy:
            self.session.proxies.update({"http": proxy, "https": proxy})
        self.verify: Any = True
        self._params: Dict[str, Dict[str, str]] = {}
        self._last_request = 0.0

    def __enter__(self) -> "EleiloesClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:
        try:
            self.session.close()
        except Exception:  # noqa: BLE001
            pass

    def _throttle(self) -> None:
        wait = self.min_interval - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)

    def _get(self, endpoint: str, *, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = endpoint if endpoint.startswith("http") else ELEILOES_API + endpoint.lstrip("/")
        last: Optional[Exception] = None
        for attempt in range(3):
            self._throttle()
            try:
                resp = self.session.get(
                    url, params=params, timeout=(self.connect_timeout, self.timeout), verify=self.verify
                )
                self._last_request = time.monotonic()
                if resp.status_code == 400 and "errorsList" in (resp.text or ""):
                    raise VendasError(_eleiloes_error(resp))
                resp.raise_for_status()
                return resp.json()
            except requests.exceptions.SSLError as exc:
                last = exc
                if tls_chain.is_chain_failure(exc):
                    bundle = tls_chain.verify_for(
                        ELEILOES_BASE,
                        timeout=min(self.connect_timeout, tls_chain.DEFAULT_TIMEOUT),
                        proxy=self.proxy,
                    )
                    if bundle and bundle != self.verify:
                        self.verify = bundle
                        continue
                time.sleep(1.2 * (attempt + 1))
            except Exception as exc:  # noqa: BLE001
                last = exc
                time.sleep(1.2 * (attempt + 1))
        raise VendasError(f"Falha a obter {url}: {last}")

    # --- parâmetros ----------------------------------------------------
    def load_params(self) -> Dict[str, Dict[str, str]]:
        """Carrega os dicionários de tipos, subtipos, modalidades e estados."""
        if self._params:
            return self._params
        mapa = {
            "tipos": "Param/VerbasTipos/",
            "subtipos": "Param/VerbasSubtipos/",
            "modalidades": "Param/ModalidadesVenda/",
            "estados": "Param/VendasEstados/",
        }
        for chave, endpoint in mapa.items():
            try:
                payload = self._get(endpoint)
                self._params[chave] = {
                    str(item.get("id")): str(item.get("descricao") or "") for item in payload.get("list") or []
                }
            except Exception as exc:  # noqa: BLE001
                logger.warning("e-leiloes: parâmetros %s indisponíveis: %s", chave, exc)
                self._params[chave] = {}
        return self._params

    # --- listagem ------------------------------------------------------
    def list_events(
        self,
        *,
        first: int = 0,
        filtros: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Uma página de eventos (12 por página) com o paginador."""
        params = {"filters": filtros or {}}
        payload = {"first": max(0, int(first)), "rows": ELEILOES_PAGE_SIZE, "filters": params["filters"]}
        return self._get("Eventos/", params={"tableParams": json.dumps(payload, ensure_ascii=False)})

    def event(self, referencia: str) -> Dict[str, Any]:
        """Detalhe de um evento (por referência, ex.: ``NP1241042026``)."""
        payload = self._get(f"Eventos/{quote(str(referencia), safe='')}/")
        return payload.get("item") or {}

    def collect(
        self,
        *,
        filtros: Optional[Dict[str, Any]] = None,
        max_pages: int = 100,
        max_items: Optional[int] = None,
        with_details: bool = True,
        on_page: Optional[Callable[[List[VendaPenhorada]], None]] = None,
        stop: Optional[Callable[[], bool]] = None,
    ) -> Tuple[List[VendaPenhorada], Dict[str, Any]]:
        """Percorre a listagem do e-leiloes (mais recentes primeiro)."""
        self.load_params()
        itens: List[VendaPenhorada] = []
        vistos: set[str] = set()
        erros: List[str] = []
        paginas = 0
        first = 0
        total = 0
        while paginas < max_pages:
            if stop and stop():
                break
            try:
                payload = self.list_events(first=first, filtros=filtros)
            except Exception as exc:  # noqa: BLE001
                erros.append(str(exc))
                break
            total = int((payload.get("pagination") or {}).get("total") or 0)
            lista = payload.get("list") or []
            if not lista:
                break
            novos: List[VendaPenhorada] = []
            for bruto in lista:
                item = self._to_item(bruto)
                if not item or item.venda_id in vistos:
                    continue
                vistos.add(item.venda_id)
                if with_details:
                    try:
                        self.enrich(item)
                    except Exception as exc:  # noqa: BLE001
                        logger.debug("e-leiloes: detalhe de %s falhou: %s", item.venda_id, exc)
                novos.append(item)
            itens.extend(novos)
            paginas += 1
            if on_page:
                on_page(novos)
            if max_items and len(itens) >= max_items:
                itens = itens[:max_items]
                break
            if len(itens) >= total:
                break
            first += ELEILOES_PAGE_SIZE
        return itens, {
            "pages": paginas,
            "collected": len(itens),
            "declared_total": total,
            "errors": erros,
            "page_size": ELEILOES_PAGE_SIZE,
        }

    def _to_item(self, bruto: Dict[str, Any]) -> Optional[VendaPenhorada]:
        referencia = bruto.get("referencia")
        if not referencia:
            return None
        params = self._params or self.load_params()
        tipo = params.get("tipos", {}).get(str(bruto.get("tipoId")))
        subtipo = params.get("subtipos", {}).get(str(bruto.get("subtipoId")))
        modalidade = params.get("modalidades", {}).get(str(bruto.get("modalidadeId")))
        estado = "terminado" if bruto.get("terminado") else ("a decorrer" if bruto.get("iniciado") else None)
        if bruto.get("cancelado"):
            estado = "cancelado"
        return VendaPenhorada(
            venda_id=f"eleiloes:{bruto.get('id')}",
            fonte="eleiloes",
            referencia=str(referencia),
            tipo_bem=tipo,
            subtipo_bem=subtipo,
            modalidade=modalidade,
            estado=estado,
            titulo=bruto.get("titulo"),
            valor_base=_float_or_none(bruto.get("valorBase")),
            valor_minimo=_float_or_none(bruto.get("valorMinimo")),
            lance_atual=_float_or_none(bruto.get("lanceAtual")),
            data_inicio=json_date(bruto.get("dataInicio")),
            data_fim=json_date(bruto.get("dataFim")),
            data_venda=json_date(bruto.get("dataFim")),
            distrito=bruto.get("moradaDistrito"),
            concelho=bruto.get("moradaConcelho"),
            freguesia=bruto.get("moradaFreguesia"),
            fotos=[ELEILOES_BASE + "/" + str(bruto.get("capa"))] if bruto.get("capa") else [],
            detalhe_url=f"{ELEILOES_BASE}/api/Eventos/{quote(str(referencia), safe='')}/",
            url=f"{ELEILOES_BASE}/evento/{quote(str(referencia), safe='')}",
        )

    def enrich(self, item: VendaPenhorada) -> VendaPenhorada:
        """Completa o bem com o detalhe do evento (processo, executados, gestor, GPS)."""
        if not item.referencia:
            return item
        dados = self.event(item.referencia)
        if not dados:
            return item
        item.titulo = item.titulo or dados.get("titulo")
        item.descricao = dados.get("descricao") or item.descricao
        item.tipo_bem = item.tipo_bem or dados.get("tipo")
        item.subtipo_bem = item.subtipo_bem or dados.get("subtipo")
        item.modalidade = item.modalidade or dados.get("modalidade")
        item.valor_base = item.valor_base if item.valor_base is not None else _float_or_none(dados.get("valorBase"))
        item.valor_minimo = item.valor_minimo if item.valor_minimo is not None else _float_or_none(dados.get("valorMinimo"))
        item.valor_abertura = _float_or_none(dados.get("valorAbertura"))
        item.lance_atual = item.lance_atual if item.lance_atual is not None else _float_or_none(dados.get("lanceAtual"))
        item.processo = dados.get("processoNumero")
        item.processo_numero = dados.get("processoNumero")
        item.tribunal = dados.get("processoTribunal")
        item.juizo = dados.get("processoTribunal")
        item.comarca_judicial = dados.get("processoComarca")
        item.morada = " ".join(
            item for item in [
                dados.get("morada"), dados.get("moradaNumero"), dados.get("moradaAndar"),
                dados.get("moradaFreguesia"), dados.get("moradaConcelho"),
            ] if item
        ) or None
        item.codigo_postal = dados.get("moradaCP")
        item.lat = _float_or_none(dados.get("coordenadasLAT"))
        item.lon = _float_or_none(dados.get("coordenadasLON"))
        item.data_inicio = item.data_inicio or json_date(dados.get("dataInicio"))
        item.data_fim = item.data_fim or json_date(dados.get("dataFim"))
        item.data_atualizacao = json_date(dados.get("dataAtualizacao"))
        item.gestor = {
            chave: valor
            for chave, valor in {
                "nome": dados.get("gestorNome"),
                "tipo": dados.get("gestorTipo"),
                "cedula": dados.get("gestorCedula"),
                "email": dados.get("gestorEmail"),
                "telefone": dados.get("gestorTelefone"),
                "comarca": dados.get("gestorComarca"),
            }.items()
            if valor
        }
        item.executados = _eleiloes_executados(dados.get("executados"))
        item.intervenientes = [
            {"papel": "Executado", **executado} for executado in item.executados
        ]
        fotos = [ELEILOES_BASE + "/" + str(foto.get("image")) for foto in dados.get("fotos") or [] if foto.get("image")]
        if fotos:
            item.fotos = fotos
        item.onus = dados.get("onus") or []
        item.extra.update(
            {
                "origem": dados.get("origem"),
                "verba_id": dados.get("verbaId"),
                "processo_id": dados.get("processoId"),
                "area_total": _float_or_none(dados.get("areaTotal")),
                "area_util": _float_or_none(dados.get("areaUtilPrivativa")),
                "matricula": dados.get("matricula") or None,
                "iva_percentagem": _float_or_none(dados.get("ivaPercentagem")),
                "desc_predial": dados.get("descPredial") or None,
                "visitas": dados.get("visitas") or None,
                "anexos": dados.get("anexos") or None,
            }
        )
        return item


def _float_or_none(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _eleiloes_executados(value: Any) -> List[Dict[str, Any]]:
    """A API devolve os executados como string JSON (``[{"nif": ..., "nome": ...}]``)."""
    if not value:
        return []
    dados = value
    if isinstance(value, str):
        try:
            dados = json.loads(value)
        except ValueError:
            return []
    if not isinstance(dados, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in dados:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                chave: valor
                for chave, valor in {
                    "nome": item.get("nome"),
                    "nif": item.get("nif"),
                    "requerido": item.get("requerido"),
                }.items()
                if valor not in (None, "", "False", False)
            }
        )
    return out


def _eleiloes_error(resp: requests.Response) -> str:
    try:
        payload = resp.json()
        erros = payload.get("errorsList") or []
        if erros:
            return "; ".join(str(item.get("msg") or item.get("title") or "") for item in erros)
    except ValueError:
        pass
    return resp.text[:300]
