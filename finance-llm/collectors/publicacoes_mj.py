"""Coletor das Publicações de Atos Societários (Ministério da Justiça).

Fonte: https://publicacoes.mj.pt/Pesquisa.aspx

O portal publica os atos de registo comercial das entidades portuguesas
(constituição, alterações, prestação de contas, nomeações, dissoluções, …).
É a fonte oficial desde 2007 — substituiu a 3.ª série do Diário da República.

Fluxo do site (ASP.NET WebForms)
--------------------------------
1. ``GET  Pesquisa.aspx`` → formulário com ``__VIEWSTATE``/``__EVENTVALIDATION``.
2. ``POST Pesquisa.aspx`` (``btSearch``) → grelha ``gvSearchResult``.
3. ``POST Pesquisa.aspx`` (``__EVENTTARGET=gvSearchResult``, ``Page$Next``) → paginação.
4. ``POST Pesquisa.aspx`` (``__EVENTTARGET=gvSearchResult``, ``Conteudo$N``) → o
   servidor guarda a publicação escolhida na sessão e responde com
   ``popitup('./DetalhePublicacao.aspx', 'detalhe')``.
5. ``GET  DetalhePublicacao.aspx`` → dados societários completos da publicação.

**A pesquisa exige reCAPTCHA v2 validado no servidor** (widget
``6LfWfwkTAAAAAF_tbbsmS54u0N7kpwdWF_kxp3Ks``). Sem um token válido o servidor
devolve ``lbNoResult`` = «Por favor, efetue a Validação» e nenhuma grelha. Por
isso este coletor é usado em **recolha assistida**: a pesquisa é feita por uma
pessoa (que resolve o captcha) e o coletor trata da paginação, do detalhe e da
ingestão — que não voltam a ser protegidos.

Dois modos de entrada
---------------------
- ``collect_from_result_html(html, cookies)`` — continua a partir do HTML da
  página de resultados já pesquisada no browser (preferido; não requer token).
- ``search(..., recaptcha_token=...)`` — faz a pesquisa diretamente (precisa de
  um token acabado de resolver, válido ~2 minutos).

Notas
-----
- As páginas são **Windows-1252** (não UTF-8); os acentos da grelha vêm em
  entidades numéricas, os dos rótulos em bytes simples.
- A grelha mostra 20 linhas por página; o rodapé traz ``(1-20 de 200)``.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import time
from dataclasses import dataclass, field
from html import unescape
from typing import Any, Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

PAGE = "https://publicacoes.mj.pt/Pesquisa.aspx"
DETALHE_PAGE = "https://publicacoes.mj.pt/DetalhePublicacao.aspx"
FIELD_PREFIX = "ctl00$ContentPlaceHolderMain$"
# `id` no HTML (o `name` usa `$`, o `id` usa `_`).
GRID_CLIENT_ID = "ctl00_ContentPlaceHolderMain_gvSearchResult"

RECAPTCHA_SITEKEY = "6LfWfwkTAAAAAF_tbbsmS54u0N7kpwdWF_kxp3Ks"

MIN_REQUEST_INTERVAL = 3.5
PAGE_SIZE = 20

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-PT,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": PAGE,
}

# Tipos de publicação (rblTipoPub em Pesquisa.aspx).
TIPOS_PUBLICACAO: Dict[str, str] = {
    "0": "Todos os actos",
    "1": "Publicação de Atos de Registo Comercial e de Registo de Fundações",
    "3": "Outras Publicações",
    "4": "Associações e Fundações",
    "5": "Associações e Fundações de Solidariedade Social",
    "6": "Associações de Pais",
    "8": "Notificações de Fundações",
}

# Distritos disponíveis em comboDadosPubDistrito.
DISTRITOS: Dict[str, str] = {
    "01": "Aveiro", "02": "Beja", "03": "Braga", "04": "Bragança",
    "05": "Castelo Branco", "06": "Coimbra", "07": "Évora", "08": "Faro",
    "09": "Guarda", "10": "Leiria", "11": "Lisboa", "12": "Portalegre",
    "13": "Porto", "14": "Santarém", "15": "Setúbal", "16": "Viana do Castelo",
    "17": "Vila Real", "18": "Viseu", "21": "Ilha da Madeira",
    "22": "Ilha de Porto Santo", "41": "Ilha de Santa Maria",
    "42": "Ilha de São Miguel", "43": "Ilha Terceira", "44": "Graciosa",
    "45": "Ilha de São Jorge", "46": "Ilha do Pico", "47": "Ilha do Faial",
    "48": "Ilha das Flores", "49": "Ilha do Corvo",
}


def _clean(fragment: str) -> str:
    """Remove tags HTML, entidades e espaços repetidos."""
    text = re.sub(r"<[^>]+>", " ", fragment or "")
    text = unescape(text).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def _decode(resp: requests.Response) -> str:
    """Descodifica uma resposta do portal.

    O portal tanto devolve páginas com ``charset`` declarado (Windows-1252) como
    páginas sem declaração que estão, na realidade, em **UTF-8**. Descodificar
    estas últimas como CP1252 produz mojibake (``FARMACÃŠUTICA``). Por isso
    testamos primeiro o charset declarado; se for uma variante ``latin-1`` e os
    bytes forem UTF-8 válidos, preferimos UTF-8.
    """
    raw = resp.content
    head = raw[:4000].decode("latin-1", errors="ignore")
    match = re.search(r'charset=["\']?([\w-]+)', head, re.I)
    declared = (match.group(1) if match else "").lower()

    latin_variants = {"cp1252", "windows-1252", "latin-1", "iso-8859-1", "latin1", ""}
    if declared in latin_variants:
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            pass

    encoding = declared or "cp1252"
    try:
        return raw.decode(encoding, errors="replace")
    except (LookupError, UnicodeDecodeError):
        return raw.decode("cp1252", errors="replace")


def _fix_mojibake(text: str) -> str:
    """Corrige texto UTF-8 que foi descodificado como CP1252 (``FARMACÃŠUTICA``)."""
    if not text or "Ã" not in text:
        return text
    try:
        return text.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


@dataclass
class PublicacaoMJ:
    """Uma publicação de atos societários (linha da grelha + detalhe)."""

    data_publicacao: Optional[str] = None
    nif: Optional[str] = None
    entidade: Optional[str] = None
    concelho: Optional[str] = None
    acto: Optional[str] = None
    tipo: Optional[str] = None
    # Campos do detalhe (DetalhePublicacao.aspx)
    firma: Optional[str] = None
    natureza_juridica: Optional[str] = None
    sede: Optional[str] = None
    distrito: Optional[str] = None
    freguesia: Optional[str] = None
    codigo_postal: Optional[str] = None
    conservatoria: Optional[str] = None
    matricula_nipc: Optional[str] = None
    pedido: Optional[str] = None
    referencia_registo: Optional[str] = None
    requerente: Optional[str] = None
    ano_contas: Optional[str] = None
    texto: Optional[str] = None
    has_documento: bool = False
    documento_url: Optional[str] = None
    source: str = "publicacoes_mj"
    search_nif: Optional[str] = None
    search_term: Optional[str] = None
    detail_fetched: bool = False
    # Índice da linha na página de resultados (para o postback «Conteudo$N»).
    _index: Optional[int] = field(default=None, repr=False)

    @property
    def pub_id(self) -> str:
        """Identificador estável (idempotente em reingestões).

        Inclui o número de apresentação/pedido sempre que existir no detalhe,
        para distinguir vários actos distintos publicados no mesmo dia.
        """
        basis = "|".join(
            str(x or "") for x in (
                self.nif,
                self.data_publicacao,
                self.acto,
                self.firma or self.entidade,
                self.pedido,
            )
        )
        return hashlib.sha1(basis.encode("utf-8")).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "pub_id": self.pub_id,
            "data_publicacao": self.data_publicacao,
            "nif": self.nif,
            "entidade": self.entidade,
            "concelho": self.concelho,
            "acto": self.acto,
            "tipo": self.tipo,
            "firma": self.firma,
            "natureza_juridica": self.natureza_juridica,
            "sede": self.sede,
            "distrito": self.distrito,
            "freguesia": self.freguesia,
            "codigo_postal": self.codigo_postal,
            "conservatoria": self.conservatoria,
            "matricula_nipc": self.matricula_nipc,
            "pedido": self.pedido,
            "referencia_registo": self.referencia_registo,
            "requerente": self.requerente,
            "ano_contas": self.ano_contas,
            "texto": self.texto,
            "has_documento": self.has_documento,
            "documento_url": self.documento_url,
            "source": self.source,
            "search_nif": self.search_nif,
            "search_term": self.search_term,
            "detail_fetched": self.detail_fetched,
        }
        return {k: v for k, v in data.items() if v is not None}


class CaptchaRequiredError(RuntimeError):
    """A pesquisa foi recusada por falta de reCAPTCHA válido."""


class RateLimitedError(RuntimeError):
    """O portal continuou a limitar os pedidos após todas as tentativas.

    Antes, `_post_with_retry` devolvia a página de throttling e a pesquisa parecia
    não ter resultados (0 publicações, sem erro) — numa recolha massiva isso era
    indistinguível de uma entidade sem publicações.
    """


def _debug_dir() -> str:
    """Diretório base para guardar páginas de debug da recolha MJ."""
    base = os.environ.get("MJ_DEBUG_DIR") or os.path.join(os.getcwd(), "debug_mj")
    os.makedirs(base, exist_ok=True)
    return base


def _save_debug_page(kind: str, nif: Optional[str], index: int, html: str) -> None:
    """Persiste o HTML de uma página de debug (form, result, detalhe, etc.)."""
    if not os.environ.get("MJ_DEBUG"):
        return
    folder = _debug_dir()
    if nif:
        folder = os.path.join(folder, nif)
    os.makedirs(folder, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    fname = f"{kind}_{index:03d}_{ts}.html"
    path = os.path.join(folder, fname)
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(html)
        logger.info("Página de debug guardada: %s", path)
    except Exception as exc:
        logger.warning("Não foi possível guardar página de debug %s: %s", path, exc)


class PublicacoesMjClient:
    """Cliente do portal de publicações do MJ (recolha assistida)."""

    def __init__(
        self,
        cookies: Optional[Dict[str, str]] = None,
        min_interval: float = MIN_REQUEST_INTERVAL,
        timeout: int = 60,
        proxy: Optional[str] = None,
    ):
        self.timeout = timeout
        self.min_interval = max(0.0, min_interval)
        self._last_request_at = 0.0
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        if cookies:
            self.session.cookies.update(cookies)
        # Suporte a proxy explícito ou via variáveis de ambiente padrão.
        proxies = self._build_proxies(proxy)
        if proxies:
            self.session.proxies.update(proxies)
        self._debug_nif: Optional[str] = None
        self._debug_counter: Dict[str, int] = {}

    def _set_debug_nif(self, nif: Optional[str]) -> None:
        self._debug_nif = nif
        self._debug_counter.clear()

    def _set_debug_enabled(self, enabled: bool = True) -> None:
        """Ativa/desativa debug dinamicamente (sem depender só do env var)."""
        if enabled:
            os.environ["MJ_DEBUG"] = "1"
        elif os.environ.get("MJ_DEBUG") == "1":
            del os.environ["MJ_DEBUG"]

    def _debug_key(self, kind: str) -> int:
        self._debug_counter[kind] = self._debug_counter.get(kind, 0) + 1
        return self._debug_counter[kind]

    def _save(self, kind: str, html: str) -> None:
        if not os.environ.get("MJ_DEBUG"):
            return
        _save_debug_page(kind, self._debug_nif, self._debug_key(kind), html)

    @staticmethod
    def _build_proxies(proxy: Optional[str] = None) -> Dict[str, str]:
        if proxy:
            return {"http": proxy, "https": proxy}
        env_http = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
        env_https = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
        proxies: Dict[str, str] = {}
        if env_http:
            proxies["http"] = env_http
        if env_https:
            proxies["https"] = env_https
        return proxies

    # --- infraestrutura -------------------------------------------------

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_request_at = time.monotonic()

    def _get(self, url: str, *, allow_retry: bool = True) -> str:
        self._throttle()
        try:
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()
            return _decode(resp)
        except requests.exceptions.ConnectionError as exc:
            if allow_retry:
                logger.warning("Connection reset no GET %s: tentar uma vez", url)
                time.sleep(2.0)
                self._throttle()
                resp = self.session.get(url, timeout=self.timeout)
                resp.raise_for_status()
                return _decode(resp)
            raise

    def _post(self, html_state: str, fields: Dict[str, str], event_target: str = "", event_argument: str = "", *, allow_retry: bool = True) -> str:
        """Faz um postback usando o estado (ViewState/EventValidation) de ``html_state``."""
        state = form_state(html_state)
        payload: Dict[str, str] = {
            "__EVENTTARGET": event_target,
            "__EVENTARGUMENT": event_argument,
            "__LASTFOCUS": state.get("__LASTFOCUS", ""),
            "__VIEWSTATE": state.get("__VIEWSTATE", ""),
            "__EVENTVALIDATION": state.get("__EVENTVALIDATION", ""),
        }
        if "__VIEWSTATEGENERATOR" in state:
            payload["__VIEWSTATEGENERATOR"] = state["__VIEWSTATEGENERATOR"]
        payload.update(fields)
        self._throttle()
        try:
            resp = self.session.post(PAGE, data=payload, timeout=self.timeout)
            resp.raise_for_status()
            return _decode(resp)
        except requests.exceptions.ConnectionError as exc:
            if allow_retry:
                logger.warning("Connection reset no POST: tentar uma vez")
                time.sleep(2.0)
                self._throttle()
                resp = self.session.post(PAGE, data=payload, timeout=self.timeout)
                resp.raise_for_status()
                return _decode(resp)
            raise

    def _post_with_retry(self, html_state: str, fields: Dict[str, str], *, retries: int = 5, base_delay: float = 15.0, event_target: str = "", event_argument: str = "") -> str:
        """Envia POST e espera se o portal devolver throttling.

        Se o rate-limit persistir, levanta `RateLimitedError` (em vez de devolver a
        página de throttling, que se confundia com «sem resultados»).
        """
        last_html = ""
        for attempt in range(retries):
            try:
                html = self._post(html_state, fields, event_target=event_target, event_argument=event_argument)
            except requests.exceptions.ConnectionError as exc:
                logger.warning("Connection reset no postback (%s/%s): aguardar e repetir", attempt + 1, retries)
                time.sleep(base_delay + attempt * 4.0)
                try:
                    html_state = self.fetch_form()
                except requests.exceptions.ConnectionError:
                    pass
                continue
            last_html = html
            if not _rate_limited(html):
                return html
            delay = base_delay + attempt * 8.0
            logger.warning("Rate-limit do MJ (%s/%s): aguardar %.1fs e tentar de novo", attempt + 1, retries, delay)
            time.sleep(delay)
            html_state = self.fetch_form()
        logger.error("Rate-limit do MJ persistiu após %s tentativas", retries)
        if last_html:
            self._save("rate_limit", last_html)
        raise RateLimitedError(
            f"O portal do Ministério da Justiça está a limitar os pedidos "
            f"(rate-limit persistente após {retries} tentativas). Tente mais tarde "
            f"ou aumente o intervalo entre pedidos."
        )

    def _search_fields(self, html_state: Optional[str] = None, **kwargs: Any) -> Dict[str, str]:
        """Campos do formulário (sem o botão), reenviados em todos os postbacks."""
        return {
            f"{FIELD_PREFIX}txtDadosPubNif": (kwargs.get("nif") or ""),
            f"{FIELD_PREFIX}txtDadosPubEntidade": (kwargs.get("entidade") or ""),
            f"{FIELD_PREFIX}comboDadosPubDistrito": (kwargs.get("distrito") or "null"),
            f"{FIELD_PREFIX}comboDadosPubConcelho": (kwargs.get("concelho") or "null"),
            f"{FIELD_PREFIX}txtDataInit": (kwargs.get("data_ini") or ""),
            f"{FIELD_PREFIX}txtDataFim": (kwargs.get("data_fim") or ""),
            f"{FIELD_PREFIX}rblTipoPub": str(kwargs.get("tipo") or "0"),
            f"{FIELD_PREFIX}NoBot1$NoBot1_NoBotExtender_ClientState": _nobot_clientstate(html_state),
        }

    # --- pesquisa -------------------------------------------------------

    def fetch_form(self) -> str:
        """Obtém a página inicial do formulário de pesquisa."""
        html = self._get(PAGE)
        self._save("form", html)
        return html

    def search(
        self,
        html_form: str,
        *,
        recaptcha_token: str,
        nif: Optional[str] = None,
        entidade: Optional[str] = None,
        distrito: Optional[str] = None,
        concelho: Optional[str] = None,
        data_ini: Optional[str] = None,
        data_fim: Optional[str] = None,
        tipo: str = "0",
    ) -> Tuple[List[PublicacaoMJ], str]:
        """Executa a pesquisa. Devolve ``(linhas, html_dos_resultados)``.

        Requer um ``recaptcha_token`` válido (resolvido por uma pessoa); sem ele o
        portal responde com «Por favor, efetue a Validação».
        """
        self._set_debug_nif(nif)
        fields = self._search_fields(
            html_state=html_form,
            nif=nif, entidade=entidade, distrito=distrito, concelho=concelho,
            data_ini=data_ini, data_fim=data_fim, tipo=tipo,
        )
        fields["g-recaptcha-response"] = recaptcha_token
        fields[f"{FIELD_PREFIX}btSearch"] = "Pesquisar"
        html = self._post_with_retry(html_form, fields)
        self._save("search", html)
        if _captcha_rejected(html):
            raise CaptchaRequiredError(
                "O portal recusou a pesquisa: é necessário um reCAPTCHA válido "
                "(lbNoResult = «Por favor, efetue a Validação»)."
            )
        rows = self.parse_results(html, search_nif=nif, search_term=entidade, tipo=tipo)
        return rows, html

    def parse_results(
        self,
        html: str,
        *,
        search_nif: Optional[str] = None,
        search_term: Optional[str] = None,
        tipo: Optional[str] = None,
    ) -> List[PublicacaoMJ]:
        """Extrai as linhas da grelha ``gvSearchResult``."""
        grid = _grid_html(html)
        if not grid:
            return []
        rows: List[PublicacaoMJ] = []
        pattern = re.compile(r"<tr class=[\"'](?:normal|alternate)Row[\"'][^>]*>(.*?)</tr>", re.I | re.S)
        for index, match in enumerate(pattern.finditer(grid)):
            cells = re.findall(r"<td[^>]*>(.*?)</td>", match.group(1), re.I | re.S)
            if len(cells) < 5:
                continue
            data_pub = _clean(cells[0])
            rows.append(
                PublicacaoMJ(
                    data_publicacao=_as_iso_date(data_pub),
                    nif=_clean(cells[1]) or None,
                    entidade=_clean(cells[2]) or None,
                    concelho=_clean(cells[3]) or None,
                    acto=_clean(cells[4]) or None,
                    tipo=tipo,
                    has_documento=bool(re.search(r"Documento\$\d+", cells[6], re.I)) if len(cells) > 6 else False,
                    source="publicacoes_mj",
                    search_nif=search_nif,
                    search_term=search_term,
                    _index=index,
                )
            )
        return rows

    @staticmethod
    def result_range(html: str) -> Dict[str, int]:
        """Interpreta o rodapé «Resultado da pesquisa (1-20 de 200)».

        O rodapé fica em ``divSearchResult``, fora da grelha, pelo que se procura
        no HTML completo.
        """
        text = _clean(html)
        match = re.search(r"\(\s*(\d+)\s*-\s*(\d+)\s+de\s+(\d+)\s*\)", text)
        if not match:
            return {"start": 0, "end": 0, "total": 0}
        return {"start": int(match.group(1)), "end": int(match.group(2)), "total": int(match.group(3))}

    @staticmethod
    def has_next_page(html: str) -> bool:
        """Indica se existe a ligação «Próximos >»."""
        return bool(re.search(r"Page\$Next", html, re.I))

    def next_page(
        self,
        html_results: str,
        *,
        nif: Optional[str] = None,
        entidade: Optional[str] = None,
        distrito: Optional[str] = None,
        concelho: Optional[str] = None,
        data_ini: Optional[str] = None,
        data_fim: Optional[str] = None,
        tipo: str = "0",
    ) -> Tuple[List[PublicacaoMJ], str]:
        """Avança para a página seguinte da grelha (postback ``Page$Next``)."""
        fields = self._search_fields(
            html_state=html_results,
            nif=nif, entidade=entidade, distrito=distrito, concelho=concelho,
            data_ini=data_ini, data_fim=data_fim, tipo=tipo,
        )
        html = self._post_with_retry(html_results, fields, event_target=f"{FIELD_PREFIX}gvSearchResult", event_argument="Page$Next")
        self._save("next_page", html)
        return self.parse_results(html, search_nif=nif, search_term=entidade, tipo=tipo), html

    # --- detalhe --------------------------------------------------------

    def open_detalhe(
        self,
        html_results: str,
        index: int,
        *,
        nif: Optional[str] = None,
        entidade: Optional[str] = None,
        distrito: Optional[str] = None,
        concelho: Optional[str] = None,
        data_ini: Optional[str] = None,
        data_fim: Optional[str] = None,
        tipo: str = "0",
    ) -> Tuple[str, str]:
        """Seleciona a linha ``index`` e descarrega ``DetalhePublicacao.aspx``.

        Devolve ``(html_do_detalhe, html_da_grelha_atualizada)``.
        """
        fields = self._search_fields(
            html_state=html_results,
            nif=nif, entidade=entidade, distrito=distrito, concelho=concelho,
            data_ini=data_ini, data_fim=data_fim, tipo=tipo,
        )
        grid_html = self._post_with_retry(
            html_results, fields,
            event_target=f"{FIELD_PREFIX}gvSearchResult", event_argument=f"Conteudo${index}",
        )
        self._save("grid_click", grid_html)
        detalhe_html = self._get(DETALHE_PAGE)
        self._save("detalhe", detalhe_html)
        return detalhe_html, grid_html

    def documento_url(
        self,
        html_results: str,
        index: int,
        *,
        nif: Optional[str] = None,
        entidade: Optional[str] = None,
        tipo: str = "0",
    ) -> Optional[str]:
        """Descobre o URL do documento (PDF) associado a uma linha, se existir."""
        fields = self._search_fields(html_state=html_results, nif=nif, entidade=entidade, tipo=tipo)
        html = self._post_with_retry(
            html_results, fields,
            event_target=f"{FIELD_PREFIX}gvSearchResult", event_argument=f"Documento${index}",
        )
        match = re.search(r"popitup\(\s*'([^']*\.aspx[^']*)'", html, re.I)
        if not match:
            return None
        from urllib.parse import urljoin

        return urljoin(PAGE, match.group(1))

    def collect(
        self,
        *,
        recaptcha_token: Optional[str] = None,
        form_html: Optional[str] = None,
        result_html: Optional[str] = None,
        with_details: bool = True,
        max_pages: int = 50,
        **criteria: Any,
    ) -> List[PublicacaoMJ]:
        """Recolhe todas as publicações de um critério (ex.: ``nif="500273170"``).

        Pode partir de um token de captcha (``recaptcha_token`` + ``form_html``) ou
        de uma página de resultados já pesquisada (``result_html``).
        """
        nif = criteria.get("nif")
        entidade = criteria.get("entidade")
        tipo = str(criteria.get("tipo") or "0")

        # Cada página da grelha é guardada com o respetivo HTML: os postbacks
        # «Conteudo$N» referem-se a uma linha *daquela* página.
        page_rows: List[List[PublicacaoMJ]] = []
        page_states: List[str] = []

        if result_html is not None:
            current = result_html
            page_rows.append(self.parse_results(current, search_nif=nif, search_term=entidade, tipo=tipo))
        elif recaptcha_token:
            rows, current = self.search(
                form_html or self.fetch_form(), recaptcha_token=recaptcha_token, **criteria
            )
            page_rows.append(rows)
        else:
            raise ValueError("Indique `recaptcha_token` (com `form_html`) ou `result_html`.")
        page_states.append(current)

        # --- paginação ---
        pages = 1
        while self.has_next_page(current) and pages < max_pages:
            rows, current = self.next_page(current, **criteria)
            if not rows:
                break
            page_rows.append(rows)
            page_states.append(current)
            pages += 1

        collected: List[PublicacaoMJ] = [row for page in page_rows for row in page]
        if not with_details:
            return collected

        # --- detalhe de cada publicação ---
        for page_index, rows in enumerate(page_rows):
            state = page_states[page_index]
            for row in rows:
                try:
                    detalhe_html, state = self.open_detalhe(state, row._index or 0, **criteria)
                    for key, value in parse_detalhe(detalhe_html).items():
                        if value:
                            setattr(row, key, value)
                    row.detail_fetched = True
                except Exception as exc:  # o detalhe é opcional
                    logger.warning("Falha no detalhe da publicação %s: %s", row.pub_id, exc)
        return collected


# --- parsing ----------------------------------------------------------


def form_state(html: str) -> Dict[str, str]:
    """Recolhe todos os inputs/selects (incluindo hidden) de um HTML WebForms."""
    state: Dict[str, str] = {}
    for match in re.finditer(r"<input([^>]*)>", html, re.I):
        attrs = match.group(1)
        name = re.search(r'name=["\']([^"\']+)["\']', attrs, re.I)
        if not name:
            continue
        value = re.search(r'value=["\']([^"\']*)["\']', attrs, re.I)
        state[name.group(1)] = unescape(value.group(1)) if value else ""
    for match in re.finditer(r"<select[^>]*name=[\"']([^\"']+)[\"'][^>]*>(.*?)</select>", html, re.I | re.S):
        selected = re.search(r'<option[^>]*value=["\']([^"\']*)["\'][^>]*selected', match.group(2), re.I)
        state[match.group(1)] = unescape(selected.group(1)) if selected else "null"
    return state


def _captcha_rejected(html: str) -> bool:
    """Deteta a recusa por captcha inválido (sem grelha de resultados)."""
    if _grid_html(html):
        return False
    match = re.search(r'id="ctl00_ContentPlaceHolderMain_lbNoResult"[^>]*>(.*?)<', html, re.I | re.S)
    if match and "valida" in _clean(match.group(1)).lower():
        return True
    return False

def _rate_limited(html: str) -> bool:
    """Deteta a mensagem de throttling do NoBot."""
    match = re.search(r'id="ctl00_ContentPlaceHolderMain_lbNoResult"[^\u003e]*\u003e(.*?)\u003c', html, re.I | re.S)
    if match:
        text = _clean(match.group(1)).lower()
        return "volte a tentar" in text or "alguns segundos" in text
    return False


def _nobot_clientstate(html: Optional[str] = None) -> str:
    """Calcula o ClientState do NoBot a partir do challenge visível no HTML.

    O NoBot da AJAX Control Toolkit publica um challenge tipo ``eval('35+84')``;
    o campo oculto é preenchido com o resultado. Resolvemos localmente.
    """
    if html:
        match = re.search(
            r'"ChallengeScript"\s*:\s*"eval\(([\'\"]?)\\u0027(.+?)\\u0027\1\)"',
            html, re.S,
        )
        if match:
            expr = match.group(2).replace("\\u0027", "'")
            try:
                return str(eval(expr, {"__builtins__": {}}, {}))
            except Exception:
                pass
    return ""

def _grid_html(html: str) -> str:
    """Devolve o HTML interno da grelha de resultados, se existir."""
    match = re.search(
        rf'<table[^>]*id=["\']{GRID_CLIENT_ID}["\'][^>]*>(.*?)</table>',
        html, re.I | re.S,
    )
    return match.group(1) if match else ""


def _as_iso_date(value: str) -> Optional[str]:
    """Normaliza ``2026-07-21`` (a grelha já vem em ISO 8601)."""
    value = (value or "").strip()
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", value)
    return f"{match.group(1)}-{match.group(2)}-{match.group(3)}" if match else (value or None)


# Rótulos do corpo da publicação, pela ordem em que aparecem.
_DETAIL_FIELDS: List[Tuple[str, str]] = [
    ("matricula_nipc", r"N[ºo°]\s*de\s*Matr[íi]cula/NIPC"),
    ("firma", r"Firma"),
    ("natureza_juridica", r"Natureza\s*Jur[íi]dica"),
    ("sede", r"Sede"),
    ("distrito", r"Distrito"),
    ("concelho", r"Concelho"),
    ("freguesia", r"Freguesia"),
    ("conservatoria", r"Matriculada\s*na"),
]

# Marcadores que delimitam o corpo da publicação dentro da página de detalhe.
_BODY_START = "Publica-se"
_BODY_END_MARKERS = ("Desenvolvimento:", "Help Desk", "Imprimir", "Ajuda", "Fechar")


def _publication_body(html: str) -> str:
    """Extrai o texto integral da publicação, isolando-o da moldura da página."""
    text = re.sub(r"<script.*?</script>", " ", html, flags=re.I | re.S)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.I)
    text = _clean(text)
    start = text.find(_BODY_START)
    if start < 0:
        start = text.find("Matrícula/NIPC")
    if start < 0:
        return ""
    body = text[start:]
    end = min(
        (index for index in (body.find(marker) for marker in _BODY_END_MARKERS) if index > 0),
        default=-1,
    )
    return _clean(body[:end]) if end > 0 else _clean(body)


def parse_detalhe(html: str) -> Dict[str, Any]:
    """Extrai os dados societários de ``DetalhePublicacao.aspx``.

    A página traz um cabeçalho (NIF/NIPC, Entidade, Data Publicação) e o texto
    integral da publicação, com os campos «Firma», «Natureza Jurídica», «Sede»,
    «Distrito», «Concelho», «Freguesia» e «Matriculada na».
    """
    out: Dict[str, Any] = {}

    # Cabeçalho: pares label/valor em linhas de tabela.
    for row in re.finditer(r"<tr[^>]*>(.*?)</tr>", html, re.I | re.S):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row.group(1), re.I | re.S)
        if len(cells) != 2:
            continue
        label = _clean(cells[0]).rstrip(":").lower()
        value = _clean(cells[1])
        if not label or not value:
            continue
        if "nif/nipc" in label or "matrícula" in label or "matricula" in label:
            out["nif_detalhe"] = value
        elif label == "entidade":
            out["entidade_detalhe"] = value
        elif "data publicação" in label:
            out["data_publicacao_detalhe"] = _as_iso_date(value)

    # Corpo: o texto integral da publicação (a página tem botões e rodapé à volta,
    # pelo que o corpo é delimitado pelos marcadores conhecidos).
    body = _publication_body(html)
    if not body:
        return out

    out["texto"] = body

    # Campos etiquetados (o texto vem achatado num só parágrafo).
    labels = [label for _, label in _DETAIL_FIELDS]
    for i, (key, label) in enumerate(_DETAIL_FIELDS):
        other = "|".join(labels[i + 1 :] + [r"pelo\s*pedido", r"foi\s*efectuado", r"Ano\s*da"])
        match = re.search(rf"{label}\s*:\s*(.*?)\s*(?={other}\s*:|$)", body, re.I | re.S)
        if match:
            value = _clean(match.group(1))
            if value:
                out[key] = value

    # Número de matrícula/NIPC no corpo (mais fiável que o cabeçalho).
    match = re.search(r"Matr[íi]cula/NIPC\s*:\s*([0-9A-Za-z]+)", body, re.I)
    if match:
        out["nif_detalhe"] = match.group(1)
        out["matricula_nipc"] = match.group(1)

    # Código postal no fim da freguesia (ex.: «Cidade da Maia 4470 MAIA»).
    freguesia = out.get("freguesia")
    if freguesia:
        # O portal cola a referência do registo à freguesia:
        # «Porto Salvo 2740 - 262 Porto Salvo pela Apresentação AP. 62/20260805 ,
        #  referente ao averbamento 1 à inscrição 13,».
        match = re.search(
            r"\s*(?P<ref>(?:pela|pelo)\s+Apresenta[çc][ãa]o\s+.*|"
            r"Matriculada\s+na\s*:?\s*.*)$",
            freguesia,
            re.I,
        )
        if match:
            out["referencia_registo"] = _clean(match.group("ref"))
            freguesia = _clean(freguesia[: match.start()])
            out["freguesia"] = freguesia or None
        match = re.search(
            r"\b(\d{4})\s*(?:-\s*(\d{3}))?\s+([A-Za-zÀ-Úà-ú][A-Za-zÀ-Úà-ú\s]*)$",
            freguesia or "",
        )
        if match:
            codigo = match.group(1) + (f"-{match.group(2)}" if match.group(2) else "")
            out["codigo_postal"] = f"{codigo} {_clean(match.group(3))}"
            out["freguesia"] = _clean(freguesia[: match.start()]) or None

    # Pedido e ato de registo.
    match = re.search(r"pelo\s*pedido\s+(.*?),\s*foi\s*efectuado\s*o\s*seguinte\s*acto", body, re.I | re.S)
    if match:
        out["pedido"] = _clean(match.group(1))
    match = re.search(r"acto\s*de\s*registo\s*:\s*(.*?)(?=Ano\s*da|Requerente|Men[çc][ãa]o|Os\s*dados|$)", body, re.I | re.S)
    if match:
        out["acto_detalhe"] = _clean(match.group(1))
    match = re.search(r"Ano\s*da\s*Presta[çc][ãa]o\s*de\s*Contas\s*:\s*(.*?)(?=Requerente|Men[çc][ãa]o|Os\s*dados|$)", body, re.I | re.S)
    if match:
        out["ano_contas"] = _clean(match.group(1))
    match = re.search(r"Requerente[^:]*:\s*(.*?)(?=Men[çc][ãa]o|Os\s*dados|$)", body, re.I | re.S)
    if match:
        out["requerente"] = _clean(match.group(1))
    return out
