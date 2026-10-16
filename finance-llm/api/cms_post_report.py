"""Relatório PDF de um artigo do blog.

Um artigo do CMS é Markdown **mais** blocos (`numeros`, `grafico`, `tabela`,
`texto`, `aviso`). Este módulo traduz essa estrutura para as **secções** que o
`contribuintes_report.render_pdf` já desenha — não há uma segunda cópia dos
números: o PDF e a página saem do mesmo documento, pelo que um artigo novo (ou
corrigido) passa a ter PDF sem ninguém escrever nada de novo.

Os gráficos do artigo são barras em HTML/CSS; no PDF passam a tabela, com o
nome, o valor e a nota de cada barra. É o mesmo conteúdo numa forma que se
imprime e se cita.

    GET /site/blog/{slug}/pdf
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from api.contribuintes_report import render_pdf, slugify
from api.cms_render import _grafico_rotulo  # mesma formatação da página

#: Rótulo da coluna única das secções de texto corrido.
_LEITURA = "Leitura"

#: Blocos cujo conteúdo é uma lista de pares (título, texto).
_PARES = {
    "destaques": (("title", "text"), ("Título", "Texto")),
    "passos": (("title", "text"), ("Passo", "Texto")),
    "faq": (("question", "answer"), ("Pergunta", "Resposta")),
}


def _sem_markdown(texto: str) -> str:
    """Markdown → texto simples (o PDF não deve mostrar `**` nem `#`)."""
    texto = re.sub(r"```.*?```", " ", texto or "", flags=re.S)
    texto = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", texto)
    texto = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", texto)
    texto = re.sub(r"[*_`>#]", "", texto)
    return re.sub(r"\s+", " ", texto).strip()


def _linhas(texto: str) -> List[str]:
    """Parágrafos, listas e títulos de um corpo em Markdown, linha a linha."""
    limpas = [_sem_markdown(linha) for linha in (texto or "").split("\n")]
    return [linha for linha in limpas if linha]


def _valor(valor: Any, formato: str) -> str:
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return str(valor or "")
    return _grafico_rotulo(numero, formato)


def _seccao(titulo: str, columns: List[str], rows: List[List[str]]) -> Optional[Dict[str, Any]]:
    if not rows:
        return None
    return {"title": titulo, "columns": columns, "rows": rows}


def _do_bloco(bloco: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Uma secção do relatório a partir de um bloco do CMS (ou nada, se não tiver conteúdo)."""
    tipo = str(bloco.get("type") or "")
    data = bloco.get("data") or {}
    titulo = str(data.get("title") or "").strip()

    if tipo == "numeros":
        rows = [
            [str(item.get("label") or ""), str(item.get("value") or ""), str(item.get("note") or "")]
            for item in data.get("items") or []
            if isinstance(item, dict)
        ]
        return _seccao(titulo or "Indicadores", ["Indicador", "Valor", "Nota"], rows)

    if tipo == "texto":
        return _seccao(titulo or "Nota", [_LEITURA], [[linha] for linha in _linhas(str(data.get("markdown") or data.get("body") or ""))])

    if tipo == "grafico":
        formato = str(data.get("format") or "euros").strip().lower()
        series = [item for item in data.get("series") or [] if isinstance(item, dict)]
        legenda = [str(nome) for nome in (data.get("legend") or []) if str(nome or "").strip()]
        segunda = any(item.get("value2") not in (None, "") for item in series)
        colunas = ["Item", legenda[0] if legenda else "Valor"]
        if segunda:
            colunas.append(legenda[1] if len(legenda) > 1 else "2.º valor")
        colunas.append("Nota")
        rows = []
        for item in series:
            linha = [str(item.get("label") or ""), _valor(item.get("value"), formato)]
            if segunda:
                linha.append(_valor(item.get("value2"), formato))
            linha.append(str(item.get("note") or ""))
            rows.append(linha)
        # A nota de leitura do gráfico vai no título da secção: no meio das
        # colunas não caberia, e sem ela o número fica sem contexto.
        nota = str(data.get("note") or "").strip()
        return _seccao(f"{titulo or 'Gráfico'} — {nota}" if nota else (titulo or "Gráfico"), colunas, rows)

    if tipo == "tabela":
        head = [str(celula) for celula in (data.get("head") or [])]
        rows = [[str(celula) for celula in row] for row in (data.get("rows") or []) if isinstance(row, list)]
        return _seccao(titulo or "Tabela", head or ["Valor"], rows)

    if tipo == "aviso":
        return _seccao(titulo or "Nota de método", [_LEITURA], [[linha] for linha in _linhas(str(data.get("text") or ""))])

    if tipo == "citacao":
        rows = [[_sem_markdown(str(data.get("quote") or "")), str(data.get("author") or "")]]
        return _seccao(titulo or "Citação", ["Citação", "Autor"], rows)

    if tipo in _PARES:
        (chave_a, chave_b), (rotulo_a, rotulo_b) = _PARES[tipo]
        rows = [
            [str(item.get(chave_a) or ""), _sem_markdown(str(item.get(chave_b) or ""))]
            for item in data.get("items") or []
            if isinstance(item, dict)
        ]
        return _seccao(titulo or rotulo_a, [rotulo_a, rotulo_b], rows)

    return None


def _data(valor: Any) -> str:
    """Data ISO → `dd/mm/aaaa` (é o que o leitor do relatório espera)."""
    texto = str(valor or "")
    partes = texto[:10].split("-")
    return "/".join(reversed(partes)) if len(partes) == 3 and all(partes) else texto


def _resumo(post: Dict[str, Any], settings: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "title": "Como se lê este relatório",
        "columns": ["Campo", "Valor"],
        "rows": [
            ["Artigo", str(post.get("title") or "")],
            ["Autor", str(post.get("author") or "")],
            ["Publicado em", _data(post.get("published_at"))],
            ["Fonte", "Base de contratos públicos indexada no Sabemos Studio."],
            ["Publicação", str(settings.get("site_name") or "")],
        ],
    }


def artigo_seccoes(post: Dict[str, Any], settings: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Secções do relatório: abertura, corpo do artigo e fontes citadas."""
    settings = settings or {}
    secoes: List[Dict[str, Any]] = [_resumo(post, settings)]

    corpo = _linhas(str(post.get("markdown") or ""))
    if corpo:
        secoes.append(_seccao("Resumo", [_LEITURA], [[linha] for linha in corpo]))

    fontes: List[str] = []
    for bloco in post.get("blocks") or []:
        if not isinstance(bloco, dict):
            continue
        secao = _do_bloco(bloco)
        if secao:
            secoes.append(secao)
        fonte = str((bloco.get("data") or {}).get("source") or "").strip()
        if fonte and fonte not in fontes:
            fontes.append(fonte)
    if fontes:
        secoes.append(_seccao("Fontes", [_LEITURA], [[fonte] for fonte in fontes]))

    return secoes


def artigo_pdf(post: Dict[str, Any], settings: Optional[Dict[str, Any]] = None) -> Tuple[str, bytes, str]:
    """Relatório PDF de um artigo. Devolve `(nome do ficheiro, bytes, tipo MIME)`."""
    settings = settings or {}
    titulo = str(post.get("title") or "Artigo")
    subtitulo = str(post.get("excerpt") or "")
    conteudo = render_pdf(title=titulo, subtitle=subtitulo, sections=artigo_seccoes(post, settings))
    dia = datetime.now(timezone.utc).strftime("%Y%m%d")
    nome = f"iq-os-artigo-{slugify(str(post.get('slug') or titulo), fallback='artigo')}_{dia}.pdf"
    return nome, conteudo, "application/pdf"
