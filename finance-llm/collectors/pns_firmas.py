"""Coletor do serviço PNS — Pesquisa de Nomes Existentes (RNPC / Portal da Empresa).

Fonte: https://www2.gov.pt/empresas/Services/Online/Pedidos.aspx?service=PNS
Formulário real (ASP.NET WebForms):
    https://www2.gov.pt/RegistoOnline/Services/PesquisaSICONF/PesquisaSICONF.aspx

O serviço pesquisa a confundibilidade de firmas e nomes comerciais registados na
Base de Dados do Registo Nacional de Pessoas Colectivas (RNPC). Devolve até 20
resultados ("20 mais confundíveis") com:

- NIPC (número de identificação de pessoa colectiva)
- Número de certificado de admissibilidade
- Nome da firma
- Concelho
- Situação (Deferido / Definitiva / ...)
- Score (percentagem de semelhança com o nome pesquisado)

Cada linha pode ser aberta em detalhe, devolvendo também o C.A.E. Principal e o
Concelho da sede.

Notas de implementação:
- É um formulário WebForms, pelo que é necessário encadear __VIEWSTATE e
  __EVENTVALIDATION entre pedidos na mesma sessão.
- Os nomes dos campos são prefixados com ``ctl00$phBody$``.
- A resposta é UTF-8 (apesar de o terminal Windows poder mostrar mojibake).
- Não existe paginação: o serviço devolve sempre no máximo 20 linhas.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from html import unescape
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

PNS_PAGE = "https://www2.gov.pt/RegistoOnline/Services/PesquisaSICONF/PesquisaSICONF.aspx"
PNS_ENTRY = "https://www2.gov.pt/empresas/Services/Online/Pedidos.aspx?service=PNS"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-PT,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": PNS_PAGE,
}

FIELD_PREFIX = "ctl00$phBody$"
MAX_RESULTS = 20  # limite imposto pelo serviço
MIN_REQUEST_INTERVAL = 0.3


@dataclass
class PnsFirma:
    """Firma/nome comercial devolvido pela Pesquisa de Nomes Existentes."""

    nome: str
    nipc: Optional[str] = None
    numero_certificado: Optional[str] = None
    concelho: Optional[str] = None
    situacao: Optional[str] = None
    score: Optional[float] = None
    cae_principal: Optional[str] = None
    concelho_sede: Optional[str] = None
    situacao_detalhe: Optional[str] = None
    certificado_admissibilidade: Optional[str] = None
    search_query: Optional[str] = None
    source: str = "pns_rnpc"
    # Preenchido no enriquecimento: semelhança entre o nome da firma e o da empresa.
    name_similarity: Optional[float] = None
    # campo interno: nome do botão de postback que abre o detalhe
    _detail_button: Optional[str] = field(default=None, repr=False)
    _detail_value: Optional[str] = field(default=None, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "nome": self.nome,
            "nipc": self.nipc,
            "numero_certificado": self.numero_certificado,
            "concelho": self.concelho,
            "situacao": self.situacao,
            "score": self.score,
            "cae_principal": self.cae_principal,
            "concelho_sede": self.concelho_sede,
            "situacao_detalhe": self.situacao_detalhe,
            "certificado_admissibilidade": self.certificado_admissibilidade,
            "search_query": self.search_query,
            "source": self.source,
            "name_similarity": self.name_similarity,
        }


def _clean(fragment: str) -> str:
    """Remove tags HTML e normaliza espaços/entidades."""
    text = re.sub(r"<[^>]+>", " ", fragment or "")
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_score(raw: str) -> Optional[float]:
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*%", raw or "")
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "."))
    except ValueError:
        return None


class PnsFirmasClient:
    """Cliente para a Pesquisa de Nomes Existentes (confundibilidade de firmas)."""

    def __init__(self, min_interval: float = MIN_REQUEST_INTERVAL, timeout: int = 60):
        self.timeout = timeout
        self.min_interval = max(0.0, min_interval)
        self._last_request_at = 0.0
        self._session = requests.Session()
        self._session.headers.update(HEADERS)

    # --- infraestrutura ---

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_request_at = time.monotonic()

    def _get(self, url: str = PNS_PAGE) -> str:
        self._throttle()
        resp = self._session.get(url, timeout=self.timeout)
        resp.raise_for_status()
        return resp.content.decode("utf-8", errors="replace")

    def _post(self, html_state_source: str, fields: Dict[str, str]) -> str:
        state = self._form_state(html_state_source)
        payload = {
            "__EVENTTARGET": fields.pop("__EVENTTARGET", ""),
            "__EVENTARGUMENT": "",
            "__LASTFOCUS": "",
            "__VIEWSTATE": state.get("__VIEWSTATE", ""),
            "__EVENTVALIDATION": state.get("__EVENTVALIDATION", ""),
        }
        payload.update(fields)
        self._throttle()
        resp = self._session.post(PNS_PAGE, data=payload, timeout=self.timeout)
        resp.raise_for_status()
        return resp.content.decode("utf-8", errors="replace")

    @staticmethod
    def _form_state(html: str) -> Dict[str, str]:
        """Recolhe todos os inputs (incluindo hidden) de um HTML WebForms."""
        state: Dict[str, str] = {}
        for m in re.finditer(r"<input([^>]*)>", html, re.I):
            attrs = m.group(1)
            name_m = re.search(r"name=[\"']([^\"']+)[\"']", attrs, re.I)
            if not name_m:
                continue
            value_m = re.search(r"value=[\"']([^\"']*)[\"']", attrs, re.I)
            state[name_m.group(1)] = unescape(value_m.group(1)) if value_m else ""
        return state

    # --- operações ---

    def search_page(
        self,
        nome: str,
        cae: Optional[str] = None,
        concelho: Optional[str] = None,
        html_page: Optional[str] = None,
    ) -> tuple:
        """Pesquisa firmas e devolve ``(firmas, html_dos_resultados)``.

        O HTML dos resultados é necessário para encadear os postbacks de detalhe.
        """
        page = html_page if html_page is not None else self._get()
        html = self._post(page, {
            f"{FIELD_PREFIX}txtbxNome": nome or "",
            f"{FIELD_PREFIX}txtbxCAE": cae or "",
            f"{FIELD_PREFIX}comboConcelho": concelho or "-1",
            f"{FIELD_PREFIX}btnPesquisar": "Pesquisar",
        })
        return self._parse_results(html, search_query=nome), html

    def search(
        self,
        nome: str,
        cae: Optional[str] = None,
        concelho: Optional[str] = None,
        html_page: Optional[str] = None,
    ) -> List[PnsFirma]:
        """Pesquisa firmas por nome (obrigatório), C.A.E. e/ou concelho."""
        firmas, _ = self.search_page(nome, cae=cae, concelho=concelho, html_page=html_page)
        return firmas

    @staticmethod
    def _parse_results(html: str, search_query: Optional[str] = None) -> List[PnsFirma]:
        """Extrai as linhas da grelha ``dataGridResultado``."""
        grid = re.search(
            r"id=[\"']dataGridResultado[\"'][^>]*>(.*?)</table>", html, re.I | re.S
        )
        if not grid:
            return []

        firmas: List[PnsFirma] = []
        for row in re.findall(r"<tr class=[\"']text[\"']>(.*?)</tr>", grid.group(1), re.I | re.S):
            tds = re.findall(r"<td[^>]*>(.*?)</td>", row, re.I | re.S)
            if len(tds) < 6:
                continue
            nipc_m = re.search(
                r"name=[\"']([^\"']*?\$btnNIPC)[\"'][^>]*value=[\"']([^\"']*)[\"']", tds[0], re.I
            )
            cert_m = re.search(
                r"name=[\"']([^\"']*?\$btnNumeroCertificado)[\"'][^>]*value=[\"']([^\"']*)[\"']",
                tds[1],
                re.I,
            )
            firmas.append(
                PnsFirma(
                    nome=_clean(tds[2]),
                    nipc=(nipc_m.group(2) or None) if nipc_m else None,
                    numero_certificado=(cert_m.group(2) or None) if cert_m else None,
                    concelho=_clean(tds[3]) or None,
                    situacao=_clean(tds[4]) or None,
                    score=_parse_score(_clean(tds[5])),
                    search_query=search_query,
                    _detail_button=nipc_m.group(1) if nipc_m else (cert_m.group(1) if cert_m else None),
                    _detail_value=(nipc_m.group(2) or cert_m.group(2)) if (nipc_m or cert_m) else None,
                )
            )
        return firmas

    def get_detail(self, firma: PnsFirma, html_page: str) -> PnsFirma:
        """Abre a ficha de detalhe de uma firma e completa o objeto em lugar."""
        if not firma._detail_button or not firma._detail_value:
            return firma
        html = self._post(html_page, {
            f"{FIELD_PREFIX}txtbxNome": firma.search_query or "",
            f"{FIELD_PREFIX}txtbxCAE": "",
            f"{FIELD_PREFIX}comboConcelho": "-1",
            firma._detail_button: firma._detail_value,
        })
        detail = self._parse_detail(html)
        if not detail:
            return firma
        firma.nome = detail.get("Nome") or firma.nome
        firma.nipc = detail.get("NIPC") or firma.nipc
        firma.numero_certificado = firma.numero_certificado
        firma.certificado_admissibilidade = detail.get("Nº de Certificado de Admissibilidade") or None
        firma.concelho_sede = detail.get("Concelho da sede") or None
        firma.cae_principal = detail.get("C.A.E. Principal") or None
        firma.situacao_detalhe = detail.get("Situação") or None
        if not firma.concelho:
            firma.concelho = firma.concelho_sede
        return firma

    @staticmethod
    def _parse_detail(html: str) -> Dict[str, str]:
        """Extrai pares label/valor da página de detalhe."""
        pairs: Dict[str, str] = {}
        for row in re.finditer(r"<tr[^>]*>(.*?)</tr>", html, re.I | re.S):
            tds = re.findall(r"<td[^>]*>(.*?)</td>", row.group(1), re.I | re.S)
            if len(tds) < 2:
                continue
            label = _clean(tds[0]).rstrip(":")
            value = _clean(tds[1])
            if label:
                pairs[label] = value
        return pairs

    def search_with_details(
        self,
        nome: str,
        cae: Optional[str] = None,
        concelho: Optional[str] = None,
        max_results: Optional[int] = None,
    ) -> List[PnsFirma]:
        """Pesquisa firmas e abre a ficha de detalhe de cada resultado."""
        page = self._get()
        firmas, results_html = self.search_page(nome, cae=cae, concelho=concelho, html_page=page)
        if max_results is not None:
            firmas = firmas[:max_results]
        for firma in firmas:
            if not firma._detail_value:
                continue
            try:
                # O postback de detalhe tem de usar o estado do formulário dos resultados.
                self.get_detail(firma, results_html)
            except Exception as exc:  # o detalhe é opcional
                logger.warning("Falha ao obter detalhe PNS de %s: %s", firma.nome, exc)
        return firmas

    def lookup_by_nif(self, nipc: str, name_hint: Optional[str] = None) -> Optional[PnsFirma]:
        """Procura uma firma pelo NIPC usando o nome como pista de pesquisa."""
        if not name_hint:
            return None
        for firma in self.search_with_details(name_hint):
            if firma.nipc and firma.nipc.strip() == str(nipc).strip():
                return firma
        return None


def fetch_firmas_for_company(
    company_name: str,
    cae: Optional[str] = None,
    concelho: Optional[str] = None,
    include_detail: bool = True,
    max_results: Optional[int] = None,
    min_interval: float = MIN_REQUEST_INTERVAL,
) -> Dict[str, Any]:
    """API de alto nível: obtém firmas/nomes comerciais do RNPC para uma empresa.

    A pesquisa do RNPC falha com pontuação e sufixos societários (ex.:
    ``"CEGID-PRIMAVERA - ..., SA"`` devolve 0 resultados), pelo que se testam
    variantes derivadas do nome até haver resultados.
    """
    from collectors.name_utils import name_search_candidates

    client = PnsFirmasClient(min_interval=min_interval)
    candidates = name_search_candidates(company_name) or [company_name]
    tried: List[Dict[str, Any]] = []

    for term in candidates:
        if include_detail:
            firmas = client.search_with_details(term, cae=cae, concelho=concelho, max_results=max_results)
        else:
            firmas = client.search(term, cae=cae, concelho=concelho)
            if max_results is not None:
                firmas = firmas[:max_results]
        tried.append({"term": term, "found": len(firmas)})
        if firmas:
            return {
                "company_name": company_name,
                "matched_term": term,
                "tried": tried,
                "total": len(firmas),
                "firmas": [f.to_dict() for f in firmas],
            }

    return {
        "company_name": company_name,
        "matched_term": None,
        "tried": tried,
        "total": 0,
        "firmas": [],
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    out = fetch_firmas_for_company("PRIMAVERA", include_detail=True, max_results=3)
    print(json.dumps(out, ensure_ascii=False, indent=2))
