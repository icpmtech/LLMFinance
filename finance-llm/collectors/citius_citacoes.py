"""Coletor da «Citação e Notificação Edital» do CITIUS (Ministério da Justiça).

Fonte: https://www.citius.mj.pt/portal/consultas/ConsultasCitEdital.aspx
       (Citações e Notificações Editais Eletrónicas de Executados, Réus,
       Requeridos e Sujeitos Processuais — artigos 11.º e 12.º da Portaria
       n.º 282/2013, artigo 24.º da Portaria n.º 280/2013 e artigo 113.º, n.º 13,
       do Código de Processo Penal)

É a fonte oficial onde os tribunais publicam as **citações e notificações
editais** (aquelas em que o citando/notificado não foi encontrado e é chamado
por édito). Cada édito traz o **tribunal**, o **ato**, a **referência**, o
**processo** (número e juízo), a **espécie**, a **data** e os **intervenientes**
com o respetivo papel (exequente, executado, réu, requerido, agente de execução,
…), além do **documento** em PDF.

Fluxo do site (ASP.NET WebForms, **sem** UpdatePanel e **sem captcha**)
---------------------------------------------------------------------
1. ``GET ConsultasCitEdital.aspx`` → formulário com ``__VIEWSTATE``,
   ``__EVENTVALIDATION``, ``ddlTribunais`` (257 serviços/tribunais),
   ``txtNome`` (nome do interveniente, **obrigatório**) e ``rblDias``
   (``15`` | ``30`` | ``todos``).
2. ``POST`` normal (não assíncrono) com ``<prefixo>btnSearch`` → a página
   inteira volta com a lista ``DataList`` (10 éditos por página), o total
   («N editais encontrados para a pesquisa efectuada») e os paginadores
   ``Pager1``/``Pager2``.
3. ``POST`` com ``__EVENTTARGET=<prefixo>Pager1$lnkNext`` → página seguinte
   (o ``__VIEWSTATE``/``__EVENTVALIDATION`` são os que vieram da resposta
   anterior).

Notas
-----
- Os resultados vêm **ordenados pela data (mais recentes primeiro)**, o que
  permite parar a recolha logo que se passa um limite de datas (ver
  ``desde``/``cutoff``).
- A pesquisa é **por nome** (o portal não aceita NIF/NIPC nem intervalo de
  datas livre nesta consulta) e, opcionalmente, por **tribunal/serviço**.
- O documento PDF (``ConsultasCitEditalPDF.ashx?q=<token>``) está ligado à
  sessão, pelo que só é acessível com os cookies da pesquisa.
- A página é **UTF-8** (ao contrário das publicações societárias, que são
  Windows-1252).
"""
from __future__ import annotations

import hashlib
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html import unescape
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

BASE = "https://www.citius.mj.pt/portal/consultas/"
PAGE = BASE + "ConsultasCitEdital.aspx"
DOCUMENTO_PAGE = BASE + "ConsultasCitEditalPDF.ashx"

FIELD_PREFIX = "ctl00$ContentPlaceHolder1$"
BUTTON_SEARCH = FIELD_PREFIX + "btnSearch"
FIELD_NOME = FIELD_PREFIX + "txtNome"
FIELD_DIAS = FIELD_PREFIX + "rblDias"
FIELD_TRIBUNAL = FIELD_PREFIX + "ddlTribunais"
SELECT_TRIBUNAL_ID = "ctl00_ContentPlaceHolder1_ddlTribunais"
PAGER_NEXT = FIELD_PREFIX + "Pager1$lnkNext"
PAGER_PREV = FIELD_PREFIX + "Pager1$btnPreviousPage"

PAGE_SIZE = 10
MIN_REQUEST_INTERVAL = 1.2

# Atalhos de datas do formulário (rblDias).
DIAS_OPCOES: Dict[str, str] = {
    "15": "Últimos 15 dias",
    "30": "Últimos 30 dias",
    "todos": "Todos",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8",
}


class CitacoesError(RuntimeError):
    """Erro na comunicação com a consulta de citações editais."""


# --------------------------------------------------------------- utilidades
def _clean(fragment: str) -> str:
    """Remove tags, entidades HTML e espaços repetidos de um fragmento."""
    text = re.sub(r"<[^>]+>", " ", fragment or "")
    text = unescape(text).replace("\xa0", " ")
    return re.sub(r"\s+", " ", text).strip()


def _fold(value: str) -> str:
    """Minúsculas sem acentos (comparar rótulos de ``select``)."""
    import unicodedata

    text = unicodedata.normalize("NFKD", (value or "").strip().lower())
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def _iso_date(value: str) -> Optional[str]:
    """Converte ``dd/mm/aaaa`` (formato do portal) em ISO 8601."""
    value = (value or "").strip()
    if not value:
        return None
    m = re.match(r"^(\d{2})[/-](\d{2})[/-](\d{4})$", value)
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else value


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


def _option_value(options: List[Dict[str, str]], wanted: str) -> Optional[str]:
    """Valor da opção cujo rótulo corresponde a ``wanted`` (exato e depois parcial)."""
    wanted_fold = _fold(wanted)
    if not wanted_fold:
        return None
    exact = [o for o in options if _fold(o.get("label", "")) == wanted_fold]
    if exact:
        return exact[0]["value"]
    if wanted_fold in ("todos", "- todos os servicos -", "todos os servicos"):
        return options[0]["value"] if options and _fold(options[0].get("label", "")).startswith("- todos") else None
    partial = [o for o in options if wanted_fold in _fold(o.get("label", ""))]
    return partial[0]["value"] if partial else None


def _split_processo(processo: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Separa «6438/19.2T8LSB, Juízo de Execução de Lisboa - Juiz 1»."""
    if not processo:
        return None, None
    partes = [p.strip() for p in processo.split(",", 1)]
    numero = partes[0] or None
    juizo = partes[1] if len(partes) > 1 and partes[1] else None
    return numero, juizo


def _split_tribunal(tribunal: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Separa «Lisboa - Tribunal Judicial da Comarca de Lisboa» em comarca e sede.

    O primeiro segmento é a **sede do tribunal** (a terra onde o processo corre,
    ex.: «Entroncamento») e o segundo o serviço («Tribunal Judicial da Comarca de
    Santarém»). Devolve ``(sede, serviço)``.
    """
    if not tribunal:
        return None, None
    partes = [p.strip() for p in tribunal.split(" - ", 1)]
    return (partes[0] or None), (partes[1] if len(partes) > 1 and partes[1] else None)


def comarca_judicial(tribunal: Optional[str], sede: Optional[str] = None) -> Optional[str]:
    """Comarca judicial de um édito («… da Comarca de Santarém» → «Santarém»).

    Onde o serviço não diz a comarca (tribunais administrativos e fiscais,
    tribunais de execução das penas, ministérios públicos), usa-se a **sede**
    (o primeiro segmento do tribunal), que é sempre uma terra geocodificável.
    """
    texto = f"{tribunal or ''} | {sede or ''}"
    m = re.search(r"Comarca\s+d(?:e|a|o)\s+([^,|]+)", texto, re.I)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()
    partes = [p.strip() for p in (tribunal or "").split(" - ", 1)]
    return partes[0] or None


_LABELS = {
    "tribunal": "Tribunal",
    "acto": "Acto",
    "referencia": "Referência",
    "processo": "Processo",
    "especie": "Espécie",
    "data": "Data",
}


@dataclass
class EditalCitacao:
    """Um édito de citação/notificação (uma linha da lista ``DataList``)."""

    referencia: str
    data_publicacao: Optional[str] = None
    tribunal: Optional[str] = None
    #: Sede do tribunal (terra onde corre o processo, ex.: «Entroncamento»).
    tribunal_comarca: Optional[str] = None
    tribunal_sede: Optional[str] = None
    #: Comarca judicial («… da Comarca de Santarém» → «Santarém»).
    comarca_judicial: Optional[str] = None
    ato: Optional[str] = None
    tipo: Optional[str] = None
    processo: Optional[str] = None
    processo_numero: Optional[str] = None
    juizo: Optional[str] = None
    especie: Optional[str] = None
    intervenientes: List[Dict[str, Any]] = field(default_factory=list)
    doc_token: Optional[str] = None
    texto: Optional[str] = None
    #: Dados extraídos do PDF: análise (`analyze_documento`) + texto e tamanho.
    documento: Dict[str, Any] = field(default_factory=dict)
    extra: Dict[str, Any] = field(default_factory=dict)
    source: str = "citius_citacoes"

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

    @classmethod
    def from_dict(cls, doc: Dict[str, Any]) -> "EditalCitacao":
        """Reconstrói um édito a partir do documento gravado (JSON/Elasticsearch).

        Serve para reabrir recolhas antigas e lhes acrescentar o que veio do PDF
        (texto, análise, NIF) sem repetir a leitura da lista.
        """
        documento = {
            k: v for k, v in doc.items() if k.startswith("documento_") or k == "documento_partes"
        }
        return cls(
            referencia=str(doc.get("referencia") or ""),
            data_publicacao=doc.get("data_publicacao"),
            tribunal=doc.get("tribunal"),
            tribunal_comarca=doc.get("tribunal_comarca"),
            tribunal_sede=doc.get("tribunal_sede"),
            comarca_judicial=doc.get("comarca_judicial"),
            ato=doc.get("ato"),
            tipo=doc.get("tipo"),
            processo=doc.get("processo"),
            processo_numero=doc.get("processo_numero"),
            juizo=doc.get("juizo"),
            especie=doc.get("especie"),
            intervenientes=list(doc.get("intervenientes") or []),
            doc_token=None,
            texto=doc.get("texto"),
            documento=documento,
            extra=dict(doc.get("extra") or {}),
        )

    @property
    def citado(self) -> Optional[str]:
        """Nome do primeiro interveniente com papel de citado/réu/executado."""
        for item in self.intervenientes:
            papel = _fold(str(item.get("papel") or ""))
            if any(chave in papel for chave in ("executad", "reu", "requerid", "citad", "arguid", "notificad")):
                return item.get("nome")
        return self.intervenientes[0].get("nome") if self.intervenientes else None

    @property
    def papeis(self) -> List[str]:
        """Papéis distintos do édito (para facetas de pesquisa)."""
        vistos: List[str] = []
        for item in self.intervenientes:
            papel = str(item.get("papel") or "").strip()
            if papel and papel not in vistos:
                vistos.append(papel)
        return vistos

    def enriquecer_intervenientes(self) -> None:
        """Preenche o NIF dos intervenientes com o que o PDF do édito revela.

        A lista do portal **não publica NIF/NIPC**, mas o PDF traz
        «Nome - NIF: 123456789» por executado/réu. Aqui esse NIF é colado ao
        interveniente correspondente (por nome normalizado); os nomes que não
        constam da lista ficam em ``documento_partes``.
        """
        partes = self.documento.get("documento_partes") or []
        if not partes or not self.intervenientes:
            return
        por_nome = {_fold(str(p["nome"])): p["nif"] for p in partes if p.get("nome") and p.get("nif")}
        for item in self.intervenientes:
            if item.get("nif"):
                continue
            nome = _fold(str(item.get("nome") or ""))
            if not nome:
                continue
            if nome in por_nome:
                item["nif"] = por_nome[nome]
                continue
            # O PDF pode abreviar («… da Silva e outros») ou acrescentar apelidos:
            # aceita-se quando um dos nomes contém o outro (mínimo 12 caracteres).
            for chave, nif in por_nome.items():
                if len(chave) >= 12 and (chave in nome or nome in chave):
                    item["nif"] = nif
                    break

    def to_dict(self) -> Dict[str, Any]:
        """Documento pronto para o índice Elasticsearch (sem valores nulos)."""
        data = {
            "pub_id": self.pub_id,
            "referencia": self.referencia,
            "data_publicacao": self.data_publicacao,
            "tribunal": self.tribunal,
            "tribunal_comarca": self.tribunal_comarca,
            "tribunal_sede": self.tribunal_sede,
            "comarca_judicial": self.comarca_judicial,
            "ato": self.ato,
            "tipo": self.tipo,
            "processo": self.processo,
            "processo_numero": self.processo_numero,
            "juizo": self.juizo,
            "especie": self.especie,
            "intervenientes": self.intervenientes,
            "citado": self.citado,
            "papeis": self.papeis,
            "has_documento": bool(self.doc_token),
            "documento_url": self.documento_url(),
            "texto": self.texto,
            "has_texto": bool(self.texto),
            **self.documento,
            "source": self.source,
        }
        if self.extra:
            data["extra"] = self.extra
        return {k: v for k, v in data.items() if v not in (None, "", [], {})}


    def documento_url(self) -> Optional[str]:
        """URL do documento (PDF) do édito — requer os cookies da sessão."""
        if not self.doc_token:
            return None
        return f"{DOCUMENTO_PAGE}?q={self.doc_token}"


def _classificar(ato: Optional[str], especie: Optional[str]) -> Optional[str]:
    """Classifica o édito (Citação | Notificação | Anúncio) a partir do ato/espécie."""
    texto = _fold(f"{ato or ''} {especie or ''}")
    if not texto:
        return None
    if "notifica" in texto:
        return "Notificação"
    if "citac" in texto or "citaç" in texto:
        return "Citação"
    if "anuncio" in texto or "publicacao" in texto:
        # Anúncios do portal que não são (só) citações nem notificações
        # (ex.: «Publicação de Anúncio (AE)», «Anúncio - Decretado Acompanhamento»).
        return "Anúncio"
    return None


# ------------------------------------------------------- texto do documento
#
# Cada édito tem um PDF (`ConsultasCitEditalPDF.ashx?q=<token>`) que traz muito
# mais do que a lista: o **NIF** de cada executado/réu, o **valor da execução**,
# o modelo do formulário, a referência interna do processo e o prazo para
# pagar/opor. Como o token está ligado à sessão da pesquisa (uma ligação antiga
# devolve a página «Erro»), a extração faz-se **durante a recolha**.

#: Limite por omissão do texto guardado por documento (caracteres).
MAX_TEXT_CHARS = 20_000

_VALOR_RE = re.compile(r"Valor:\s*([\d][\d\s.,]*)\s*(?:Euros|EUR|€)", re.I)
_NIF_RE = re.compile(r"NIF:\s*(\d{9})", re.I)
_NIF_NOME_RE = re.compile(r"(?P<nome>[^\n:]{4,120}?)\s*[-–]\s*NIF:\s*(?P<nif>\d{9})", re.I)
_MODELO_RE = re.compile(r"Modelo:\s*([\d.,/]+)", re.I)
_REF_INTERNA_RE = re.compile(r"Refer[êe]ncia interna do processo:\s*(.+)", re.I)
_DOC_CODIGO_RE = re.compile(r"\bDocumento:\s*([A-Za-z0-9]+)")
_PRAZO_RE = re.compile(r"prazo de\s+([A-ZÀ-Ú][A-ZÀ-Ú\s]{2,30}?)\s*(?:\*|,|\.|$)", re.M)


def _pt_number(value: str) -> Optional[float]:
    """Converte «44.563,46» (formato português) em ``44563.46``."""
    digits = re.sub(r"[^\d.,]", "", value or "")
    if not digits:
        return None
    if "," in digits and "." in digits:
        digits = digits.replace(".", "").replace(",", ".")
    elif "," in digits:
        digits = digits.replace(",", ".")
    try:
        return round(float(digits), 2)
    except ValueError:
        return None


def analyze_documento(texto: Optional[str]) -> Dict[str, Any]:
    """Extrai os dados estruturados do texto do PDF de um édito.

    Devolve o que a lista do portal não traz: título/assunto do édito, modelo do
    formulário, referência interna do processo, valor da execução, prazo e os
    **nomes com NIF** (executados, réus, exequentes, …).
    """
    if not texto:
        return {}

    linhas = [linha.strip() for linha in texto.splitlines()]
    normalizado = re.sub(r"[ \t]+", " ", texto)

    # Títulos: linhas em maiúsculas, sem rótulo («Processo: …»). O cabeçalho traz
    # nomes de pessoas em maiúsculas (ex.: o agente de execução), por isso o
    # título é escolhido pelo **conteúdo** (Citação/Notificação/Venda/…) e, em
    # alternativa, pela linha a seguir a «Página N de M».
    candidatos: List[Tuple[int, str]] = []
    for indice, linha in enumerate(linhas):
        if not linha or ":" in linha or len(linha) < 10 or len(linha) > 120:
            continue
        letras = [c for c in linha if c.isalpha()]
        if len(letras) < 8 or any(c.islower() for c in letras):
            continue
        candidatos.append((indice, re.sub(r"\s+", " ", linha)))

    fortes = ("citac", "notifica", "edital", "venda", "anuncio", "publicacao", "penhora", "insolve")
    depois_da_pagina = {
        indice + 1
        for indice, linha in enumerate(linhas)
        if re.match(r"^P[áa]gina\s+\d+\s+de\s+\d+", linha, re.I)
    }

    def _peso(item: Tuple[int, str]) -> Tuple[int, int]:
        indice, linha = item
        alvo = _fold(linha)
        peso = 3 if any(p in alvo for p in fortes) else 0
        if indice in depois_da_pagina:
            peso += 2
        return (-peso, indice)

    titulos: List[str] = []
    if candidatos:
        escolhido = sorted(candidatos, key=_peso)[0]
        titulos.append(escolhido[1])
        seguintes = [linha for indice, linha in candidatos if indice > escolhido[0]]
        if seguintes:
            titulos.append(seguintes[0])

    partes: List[Dict[str, str]] = []
    vistos: set[str] = set()
    for m in _NIF_NOME_RE.finditer(normalizado):
        nome = re.sub(r"\s+", " ", m.group("nome")).strip(" ,.;-")
        nif = m.group("nif")
        chave = f"{_fold(nome)}|{nif}"
        if chave in vistos:
            continue
        vistos.add(chave)
        partes.append({"nome": nome, "nif": nif})

    dados: Dict[str, Any] = {
        "documento_titulo": titulos[0] if titulos else None,
        "documento_assunto": titulos[1] if len(titulos) > 1 else None,
        "documento_modelo": (m.group(1) if (m := _MODELO_RE.search(normalizado)) else None),
        "documento_referencia_interna": (
            m.group(1).strip() if (m := _REF_INTERNA_RE.search(normalizado)) else None
        ),
        "documento_codigo": (m.group(1) if (m := _DOC_CODIGO_RE.search(normalizado)) else None),
        "documento_valor": (lambda m: _pt_number(m.group(1)) if m else None)(_VALOR_RE.search(normalizado)),
        "documento_prazo": (
            re.sub(r"\s+", " ", m.group(1)).strip().title() if (m := _PRAZO_RE.search(texto)) else None
        ),
        "documento_partes": partes,
        "documento_nifs": sorted({p["nif"] for p in partes} | set(_NIF_RE.findall(normalizado))),
    }
    return {k: v for k, v in dados.items() if v not in (None, "", [], {})}


def extract_pdf_text(pdf_bytes: bytes, *, max_chars: int = MAX_TEXT_CHARS) -> Dict[str, Any]:
    """Extrai o texto de um PDF de édito (PyMuPDF, com alternativa em `pypdf`).

    Devolve ``{texto, paginas, caracteres, truncado}`` ou ``{erro}`` quando a
    extração falha — a recolha continua, guardando o motivo no item.
    """
    if not pdf_bytes:
        return {"erro": "documento vazio"}
    if pdf_bytes[:4] != b"%PDF":
        return {"erro": "o portal não devolveu um PDF (sessão expirada?)"}

    paginas: List[str] = []
    total_paginas = 0
    try:
        try:
            import pymupdf as fitz  # PyMuPDF ≥ 1.24
        except Exception:  # noqa: BLE001
            import fitz  # type: ignore # PyMuPDF antigo
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            total_paginas = len(doc)
            for page in doc:
                paginas.append(page.get_text("text") or "")
    except ImportError:
        try:
            from io import BytesIO

            from pypdf import PdfReader  # type: ignore

            reader = PdfReader(BytesIO(pdf_bytes))
            total_paginas = len(reader.pages)
            for page in reader.pages:
                paginas.append(page.extract_text() or "")
        except Exception as exc:  # noqa: BLE001
            return {"erro": f"sem extrator de PDF disponível: {exc}"}
    except Exception as exc:  # noqa: BLE001
        return {"erro": f"falha a ler o PDF: {exc}"}

    texto = "\n".join(paginas)
    texto = re.sub(r"[ \t]+", " ", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto).strip()
    truncado = len(texto) > max_chars
    if truncado:
        texto = texto[:max_chars]
    return {
        "texto": texto,
        "paginas": total_paginas,
        "caracteres": len(texto),
        "truncado": truncado,
    }



# --------------------------------------------------------------- parsing
def parse_items(html: str) -> List[EditalCitacao]:
    """Extrai os éditos de uma página de resultados.

    Cada édito é um ``div.resultadocdital`` com pares ``<strong>Rótulo:</strong>
    valor``, seguido dos intervenientes (um ``span`` por pessoa, dentro do
    ``span`` ``…_DataList``) e do painel do documento (``…_pnlPDF``).
    """
    import lxml.html

    if not html:
        return []

    doc = lxml.html.fromstring(html)
    out: List[EditalCitacao] = []
    for node in doc.xpath('//div[contains(concat(" ", normalize-space(@class), " "), " resultadocdital ")]'):
        item = _item_from_node(node)
        if item and item.referencia:
            out.append(item)
    return out


def _item_from_node(node: Any) -> Optional[EditalCitacao]:
    """Converte um ``div.resultadocdital`` num ``EditalCitacao``."""
    import lxml.html

    # Intervenientes: um <span> por pessoa dentro do span «…DataList».
    intervenientes: List[Dict[str, Any]] = []
    blocos = node.xpath('.//span[contains(@id, "DataList")]')
    for outer in blocos:
        inner_spans = [s for s in outer.xpath("./span") if isinstance(s.tag, str)]
        for inner in inner_spans or [outer]:
            text = _clean(inner.text_content())
            m = re.match(
                r"^(?P<papel>[^:]+):\s*(?P<nome>.*?)(?:\s*NIF/NIPC:\s*(?P<nif>[\w\-/]+))?$",
                text,
            )
            if not m or not m.group("nome"):
                continue
            intervenientes.append(
                {
                    "papel": m.group("papel").strip(),
                    "nome": m.group("nome").strip(),
                    "nif": (m.group("nif") or None),
                }
            )

    documento = node.xpath('.//input[contains(@id, "queryString")]/@value')
    token = unescape(documento[0]) if documento else None

    # Campos simples: retirar os blocos já tratados e ler «Rótulo: valor».
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
    ato = fields.get("Acto")

    known = set(_LABELS.values()) | {"Referencia", "Especie"}
    extra = {k: v for k, v in fields.items() if k not in known and v}

    return EditalCitacao(
        referencia=referencia,
        data_publicacao=_iso_date(fields.get(_LABELS["data"], "")),
        tribunal=tribunal,
        tribunal_comarca=comarca,
        tribunal_sede=sede,
        comarca_judicial=comarca_judicial(tribunal, sede),
        ato=ato,
        tipo=_classificar(ato, especie),
        processo=processo,
        processo_numero=processo_numero,
        juizo=juizo,
        especie=especie,
        intervenientes=intervenientes,
        doc_token=token,
        extra=extra,
    )


def result_count(html: str) -> int:
    """Total de éditos declarado pelo portal («N editais encontrados»)."""
    m = re.search(r"([\d\.\s]+)\s+editais encontrados", _clean(html or ""))
    if not m:
        return 0
    digits = re.sub(r"\D", "", m.group(1))
    return int(digits) if digits else 0


def current_page(html: str) -> int:
    """Número da página atual do paginador (1 se não encontrar)."""
    m = re.search(r'Pager1_lblPageNumber"[^>]*>\s*(\d+)\s*<', html or "")
    return int(m.group(1)) if m else 1


def has_next_page(html: str) -> bool:
    """Indica se o paginador superior tem ligação para a página seguinte."""
    return bool(re.search(r'Pager1_lnkNext"\s+title="Página seguinte', html or "")) or bool(
        re.search(r'id="ctl00_ContentPlaceHolder1_Pager1_lnkNext"', html or "")
    )


def total_pages(html: str, stated_total: Optional[int] = None) -> int:
    """Número estimado de páginas (10 éditos por página)."""
    total = stated_total if stated_total is not None else result_count(html)
    return (total + PAGE_SIZE - 1) // PAGE_SIZE if total else 0


def _blocked(html: str) -> bool:
    """Deteta a página de bloqueio do WAF do CITIUS."""
    return "Something Went Wrong" in (html or "")[:4000]


@dataclass
class CitacoesPage:
    """Uma página de resultados da consulta de citações editais."""

    items: List[EditalCitacao]
    total: int = 0
    page: int = 1
    has_next: bool = False
    html: str = ""

    @property
    def pages_total(self) -> int:
        """Número estimado de páginas (10 éditos por página)."""
        return (self.total + PAGE_SIZE - 1) // PAGE_SIZE if self.total else 0


# --------------------------------------------------------------- cliente
class CitacoesEditalClient:
    """Cliente da consulta de citações e notificações editais do CITIUS.

    Uso::

        with CitacoesEditalClient(min_interval=1.5) as client:
            page = client.search(nome="SILVA", dias="todos")
            for edito in page.items:
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
    def __enter__(self) -> "CitacoesEditalClient":
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
                text = resp.content.decode("utf-8", errors="replace")
                if _blocked(text):
                    raise CitacoesError("Pedido bloqueado pelo portal (WAF).")
                return text
            except Exception as exc:  # noqa: BLE001
                last = exc
                time.sleep(1.5 * (attempt + 1))
        raise CitacoesError(f"Falha a obter {url}: {last}")

    def _post(self, data: Dict[str, str], *, retries: int = 3) -> str:
        last: Optional[Exception] = None
        for attempt in range(retries):
            self._throttle()
            try:
                resp = self.session.post(
                    PAGE, data=data, timeout=self.timeout, headers={"Referer": PAGE}
                )
                self._last_request = time.monotonic()
                resp.raise_for_status()
                text = resp.content.decode("utf-8", errors="replace")
                if _blocked(text):
                    raise CitacoesError("Pedido bloqueado pelo portal (WAF).")
                self.pages_fetched += 1
                return text
            except Exception as exc:  # noqa: BLE001
                last = exc
                time.sleep(2.0 * (attempt + 1))
        raise CitacoesError(f"Falha no postback: {last}")

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
        """Obtém o formulário e memoriza o estado (viewstate + serviços)."""
        html = self._get(PAGE)
        self._state = form_state(html)
        self._state.setdefault("__VIEWSTATEENCRYPTED", "")
        self._options = {"ddlTribunais": parse_options(html, SELECT_TRIBUNAL_ID)}
        self.pages_fetched = 0
        return html

    @property
    def options(self) -> Dict[str, List[Dict[str, str]]]:
        """Opções dos ``select`` (serviços/tribunais)."""
        return self._options

    def tribunais(self) -> List[Dict[str, str]]:
        """Serviços/tribunais disponíveis (``value`` legível, sem cifra)."""
        return list(self._options.get("ddlTribunais", []))

    # --- pesquisa ------------------------------------------------------
    def search(
        self,
        *,
        nome: Optional[str] = None,
        tribunal: Optional[str] = None,
        dias: Optional[str] = None,
        fetch_options: bool = True,
    ) -> CitacoesPage:
        """Pesquisa éditos por nome do interveniente (obrigatório no portal).

        ``tribunal`` é comparado pelo **rótulo** (ex.: «Porto - Tribunal Judicial
        da Comarca do Porto») e ``dias`` usa os atalhos do formulário
        (``"15"``, ``"30"``, ``"todos"``).
        """
        nome = (nome or "").strip()
        if not nome:
            raise ValueError("A consulta exige o nome do interveniente a pesquisar.")
        if dias and dias not in DIAS_OPCOES:
            raise ValueError("Atalho de dias inválido (use 15, 30 ou todos).")

        if fetch_options or not self._state:
            self.fetch_form()

        fields: Dict[str, Any] = {
            FIELD_NOME: nome,
            FIELD_DIAS: dias or "todos",
        }
        if tribunal:
            value = _option_value(self._options.get("ddlTribunais", []), tribunal)
            if value is None:
                raise ValueError(f"Tribunal «{tribunal}» não encontrado no formulário.")
            fields[FIELD_TRIBUNAL] = value
        else:
            opcoes = self._options.get("ddlTribunais", [])
            if opcoes:
                fields[FIELD_TRIBUNAL] = opcoes[0]["value"]

        html = self._post(self._payload(BUTTON_SEARCH, **fields))
        self._absorb(html)
        return CitacoesPage(
            items=parse_items(html),
            total=result_count(html),
            page=current_page(html),
            has_next=has_next_page(html),
            html=html,
        )

    def next_page(self) -> CitacoesPage:
        """Avança para a página seguinte da pesquisa corrente."""
        html = self._post(self._payload(PAGER_NEXT))
        self._absorb(html)
        return CitacoesPage(
            items=parse_items(html),
            total=result_count(html),
            page=current_page(html),
            has_next=has_next_page(html),
            html=html,
        )

    def collect(
        self,
        *,
        max_pages: int = 50,
        max_items: Optional[int] = None,
        desde: Optional[str] = None,
        on_page: Optional[Callable[[CitacoesPage, List[EditalCitacao]], None]] = None,
        stop: Optional[Callable[[], bool]] = None,
        **criteria: Any,
    ) -> Tuple[List[EditalCitacao], Dict[str, Any]]:
        """Percorre as páginas da pesquisa até ao limite e devolve itens + resumo.

        ``desde`` (ISO 8601) corta os éditos anteriores a essa data. Como o portal
        devolve os resultados **por data descendente**, a recolha **para** assim
        que uma página inteira ficar anterior ao corte (deixa de haver novidades).
        ``on_page(page, items)`` é chamado a cada página (progresso) e ``stop()``
        (se devolver ``True``) interrompe a recolha.
        """
        page = self.search(**criteria)
        items: List[EditalCitacao] = []
        seen: set[str] = set()
        total = page.total
        pages_done = 0
        antigos = 0
        while True:
            novos: List[EditalCitacao] = []
            for item in page.items:
                if item.pub_id in seen:
                    continue
                seen.add(item.pub_id)
                if desde and item.data_publicacao and item.data_publicacao < desde:
                    antigos += 1
                    continue
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
            # A página só tinha éditos anteriores ao corte: as seguintes também
            # (ordem por data descendente) — não vale a pena continuar.
            if desde and page.items and not novos:
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
            "oldest_skipped": antigos,
            "page_size": PAGE_SIZE,
        }
        return items, summary

    # --- documento -----------------------------------------------------
    def fetch_documento(self, token: str) -> bytes:
        """Descarrega o PDF de um édito (usa a sessão onde a pesquisa foi feita)."""
        url = f"{DOCUMENTO_PAGE}?q={token}"
        self._throttle()
        resp = self.session.get(url, timeout=self.timeout, headers={"Referer": PAGE})
        self._last_request = time.monotonic()
        resp.raise_for_status()
        return resp.content

    def extrair_documentos(
        self,
        items: List[EditalCitacao],
        *,
        max_documentos: int = 200,
        max_text_chars: int = MAX_TEXT_CHARS,
        on_document: Optional[Callable[[int, int, EditalCitacao, bool, Optional[str]], None]] = None,
        stop: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, Any]:
        """Descarrega e extrai o texto do PDF de cada édito (na **mesma sessão**).

        O token do documento está ligado à sessão da pesquisa: uma ligação antiga
        devolve a página «Erro», por isso a extração tem de acontecer ainda dentro
        da recolha. Para cada édito ficam gravados o texto, o número de páginas e
        a **análise** do documento (título, modelo, valor da execução, prazo e os
        NIF dos intervenientes). Devolve o resumo da operação.
        """
        alvos = [item for item in items if item.doc_token and not item.texto]
        if max_documentos and max_documentos > 0:
            alvos = alvos[:max_documentos]

        pedidos = extraidos = falhados = 0
        caracteres = 0
        parado = False
        for indice, item in enumerate(alvos, start=1):
            if stop and stop():
                parado = True
                break
            pedidos += 1
            erro: Optional[str] = None
            try:
                pdf = self.fetch_documento(str(item.doc_token))
                extraido = extract_pdf_text(pdf, max_chars=max_text_chars)
                if extraido.get("erro"):
                    erro = str(extraido["erro"])
                else:
                    item.texto = extraido.get("texto")
                    item.documento = {
                        **(item.documento or {}),
                        **analyze_documento(item.texto),
                        "documento_paginas": extraido.get("paginas"),
                        "documento_caracteres": extraido.get("caracteres"),
                        "documento_bytes": len(pdf),
                        "documento_extraido_em": datetime.now(timezone.utc).isoformat(),
                    }
                    if extraido.get("truncado"):
                        item.documento["documento_truncado"] = True
                    item.enriquecer_intervenientes()
                    extraidos += 1
                    caracteres += int(extraido.get("caracteres") or 0)
            except Exception as exc:  # noqa: BLE001 — um documento falhado não trava a recolha
                erro = str(exc)
            if erro:
                falhados += 1
                item.documento = {**(item.documento or {}), "documento_erro": erro[:300]}
                logger.warning("Documento do édito %s falhou: %s", item.referencia, erro)
            if on_document:
                on_document(indice, len(alvos), item, erro is None, erro)

        return {
            "pedidos": pedidos,
            "extraidos": extraidos,
            "falhados": falhados,
            "caracteres": caracteres,
            "parado": parado,
            "total_com_documento": len([item for item in items if item.doc_token]),
        }
