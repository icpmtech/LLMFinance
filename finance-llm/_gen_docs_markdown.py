"""Gera o markdown do CAE-Rev.4 a partir do PDF em `data/docs`.

O quadro «2 – ESTRUTURA» do PDF (páginas 53–90) tem uma tabela com as colunas
SECÇÃO · DIVISÃO · GRUPO · CLASSE · SUBCLASSE · DESIGNAÇÃO. Este script lê as
posições das palavras na página (`get_text("words")`), reconstrói as linhas da
tabela e escreve uma árvore markdown em `data/docs/CAE-Rev.4.md`.

Uso:
    python _gen_docs_markdown.py [--pdf CAMINHO] [--out CAMINHO]
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

import pymupdf

ROOT = Path(__file__).resolve().parent
DOCS_DIR = ROOT / "data" / "docs"

# Colunas do quadro (a ordem do cabeçalho na página).
COLUNAS = ["SECCAO", "DIVISAO", "GRUPO", "CLASSE", "SUBCLASSE", "DESIGNACAO"]
CABECALHOS = {
    "SECÇÃO": "SECCAO",
    "SECCAO": "SECCAO",
    "DIVISÃO": "DIVISAO",
    "DIVISAO": "DIVISAO",
    "GRUPO": "GRUPO",
    "CLASSE": "CLASSE",
    "SUBCLASSE": "SUBCLASSE",
    "DESIGNAÇÃO": "DESIGNACAO",
    "DESIGNAÇAO": "DESIGNACAO",
    "DESIGNACAO": "DESIGNACAO",
}

# Linhas corridas (cabeçalho/rodapé) que não fazem parte da tabela.
RUIDO = (
    "CLASSIFICAÇÃO PORTUGUESA DAS ATIVIDADES ECONÓMICAS",
    "2 – ESTRUTURA",
    "2-ESTRUTURA",
)


def _normalizar(texto: str) -> str:
    return re.sub(r"\s+", " ", texto).strip()


def _cabecalho_da_pagina(page: Any) -> tuple[list[tuple[str, float, float, float]], float] | None:
    """Cabeçalho do quadro: (nome da coluna, x0, x1, centro) + topo da tabela.

    O cabeçalho é o conjunto de rótulos (`SECÇÃO … DESIGNAÇÃO`) no **topo** da
    página, pela ordem das colunas. Exigir essa ordem e essa localização evita
    confundir as páginas de metodologia (que mencionam os nomes dos níveis no
    meio do texto corrido) com a tabela.
    """
    candidatos = [
        w for w in page.get_text("words") if _normalizar(w[4]).upper() in CABECALHOS
    ]
    if len(candidatos) < 5:
        return None
    limite_topo = page.rect.height * 0.35
    candidatos = [w for w in candidatos if w[1] <= limite_topo]
    if len(candidatos) < 5:
        return None
    candidatos.sort(key=lambda w: w[0])
    indices = [COLUNAS.index(CABECALHOS[_normalizar(w[4]).upper()]) for w in candidatos]
    for a, b in zip(indices, indices[1:]):
        if b <= a:
            return None
    caixas = [
        (COLUNAS[i], w[0], w[2], (w[0] + w[2]) / 2) for i, w in zip(indices, candidatos)
    ]
    topo = max(w[3] for w in candidatos)
    return caixas, topo


def _limites_das_colunas(caixas: list[tuple[str, float, float, float]]) -> list[float]:
    """Limites-x esquerdos de cada coluna.

    Nas colunas de códigos o limite é o ponto médio entre rótulos vizinhos. A
    coluna **DESIGNAÇÃO** ocupa todo o espaço à direita da coluna SUBCLASSE (o
    seu rótulo está centrado na mancha, não à esquerda), por isso o limite é o
    fim da coluna anterior.
    """
    limites: list[float] = []
    for i, (nome, _x0, _x1, centro) in enumerate(caixas):
        if i == 0:
            limites.append(-1e6)
        elif nome == "DESIGNACAO":
            limites.append(caixas[i - 1][2] + 6)
        else:
            limites.append((caixas[i - 1][3] + centro) / 2)
    return limites


def _linhas_da_pagina(page: Any) -> list[dict[str, str]]:
    """Reconstrói as linhas da tabela de uma página, por coluna."""
    info = _cabecalho_da_pagina(page)
    if info is None:
        return []
    caixas, topo = info
    limites = _limites_das_colunas(caixas)
    colunas = [c[0] for c in caixas]
    altura = page.rect.height

    def _coluna(centro: float) -> str:
        idx = 0
        for i, limite in enumerate(limites):
            if centro >= limite:
                idx = i
        return colunas[idx]

    palavras = []
    for x0, y0, x1, y1, texto, *_ in page.get_text("words"):
        if y0 <= topo + 1:
            continue
        limpo = _normalizar(texto)
        if not limpo:
            continue
        # Rodapé: título corrido e número de página.
        if any(limpo.upper().startswith(r) for r in RUIDO):
            continue
        if re.fullmatch(r"\d{1,3}", limpo) and y0 > altura - 60:
            continue
        if y0 > altura - 30:
            continue
        centro = (x0 + x1) / 2
        palavras.append({"y": y0, "x": x0, "t": limpo, "col": _coluna(centro)})
    palavras.sort(key=lambda p: (round(p["y"]), p["x"]))

    # Agrupa por linha física (tolerância de 3 px).
    linhas: list[list[dict[str, Any]]] = []
    for p in palavras:
        if linhas and abs(p["y"] - linhas[-1][0]["y"]) <= 3:
            linhas[-1].append(p)
        else:
            linhas.append([p])

    resultado: list[dict[str, Any]] = []
    for linha in linhas:
        celulas: dict[str, list[str]] = {}
        for p in sorted(linha, key=lambda p: p["x"]):
            celulas.setdefault(p["col"], []).append(p["t"])
        registo: dict[str, Any] = {c: _normalizar(" ".join(v)) for c, v in celulas.items()}
        if registo:
            registo["_y"] = sum(p["y"] for p in linha) / len(linha)
            resultado.append(registo)
    return resultado


PADRAO_COLUNA = {
    "SECCAO": r"[A-Za-z]",
    "DIVISAO": r"\d{2}",
    "GRUPO": r"\d{3}",
    "CLASSE": r"\d{4}",
    "SUBCLASSE": r"\d{5}",
}


def _designacao_extra(registo: dict[str, str]) -> str:
    """Texto que, nas colunas de códigos, **não** é um código.

    Nas células fundidas (designações longas de secção/divisão) o texto começa
    nas colunas da esquerda; sem isto perdia-se o princípio do nome (ex.: a
    Secção E ficava só com «e despoluição»).
    """
    partes: list[str] = []
    for coluna, padrao in PADRAO_COLUNA.items():
        valor = registo.get(coluna) or ""
        for token in valor.split():
            if not re.fullmatch(padrao, token):
                partes.append(token)
    return _normalizar(" ".join(partes))


def _e_codigo(valor: str, digitos: int) -> bool:
    return bool(re.fullmatch(rf"\d{{{digitos}}}", valor.strip()))


def _primeiro(padrao: str, valor: str) -> str:
    """Primeiro token da célula que respeita o padrão (as células multilinha do
    PDF podem trazer vários códigos colados)."""
    for token in re.split(r"[\s,;]+", valor or ""):
        if re.fullmatch(padrao, token):
            return token
    return ""


def _limpar_designacao(texto: str) -> str:
    """Tira marcadores de asterisco e notas de rodapé do quadro."""
    texto = re.sub(r"[*/]+\s*Níveis idênticos[^*/]*(?:Rev\.[\d.]+)?", " ", texto, flags=re.I)
    texto = re.sub(r"\s*/\s*\*+\s*", " ", texto)
    texto = texto.replace("*", " ")
    return _normalizar(texto)


def extrair_estrutura(pdf: Path) -> list[dict[str, str]]:
    """Lê o quadro da estrutura (todas as páginas que o contêm).

    As linhas **com código** tornam-se itens; as linhas só de texto (designações
    que rebentam em várias linhas físicas, por exemplo nas secções) são coladas
    ao item **mais próximo na vertical** — é o que reconstitui nomes longos como
    «Captação, tratamento e distribuição de água; … e despoluição».
    """
    doc = pymupdf.open(pdf)
    itens: list[dict[str, str]] = []
    for page in doc:
        linhas = _linhas_da_pagina(page)
        codigos: list[tuple[float, dict[str, str]]] = []
        pendentes: list[tuple[float, str]] = []
        for linha in linhas:
            secao = _primeiro(r"[A-Za-z]", _normalizar(linha.get("SECCAO") or ""))
            divisao = _primeiro(r"\d{2}", linha.get("DIVISAO") or "")
            grupo = _primeiro(r"\d{3}", linha.get("GRUPO") or "")
            classe = _primeiro(r"\d{4}", linha.get("CLASSE") or "")
            subclasse = _primeiro(r"\d{5}", linha.get("SUBCLASSE") or "")
            designacao = _designacao_extra(linha)
            resto = _normalizar(linha.get("DESIGNACAO") or "")
            if resto:
                designacao = (designacao + " " + resto).strip()
            designacao = _limpar_designacao(designacao)
            y = float(linha.get("_y") or 0.0)
            if not (secao or divisao or grupo or classe or subclasse):
                if designacao:
                    pendentes.append((y, designacao))
                continue
            item = {
                "secao": secao.upper(),
                "divisao": divisao,
                "grupo": grupo,
                "classe": classe,
                "subclasse": subclasse,
                "designacao": designacao,
                "pagina": str(page.number + 1),
            }
            itens.append(item)
            codigos.append((y, item))
        for y, texto in pendentes:
            if not codigos:
                break
            _, item = min(codigos, key=lambda par: abs(par[0] - y))
            item["designacao"] = _normalizar(f"{item['designacao']} {texto}")
    doc.close()
    return itens


def construir_markdown(itens: list[dict[str, str]], origem: str) -> str:
    """Constrói a árvore markdown (secção → divisão → grupo → classe → subclasse)."""
    linhas: list[str] = []
    linhas.append("# CAE-Rev.4 — Classificação Portuguesa das Atividades Económicas")
    linhas.append("")
    linhas.append(
        "Quadro **2 – Estrutura** da _Classificação Portuguesa das Atividades Económicas "
        f"(Revisão 4)_ do INE, convertido para markdown a partir de `{origem}`."
    )
    linhas.append("")
    linhas.append("Níveis: **Secção** (letra) › **Divisão** (2 dígitos) › **Grupo** (3) › "
                  "**Classe** (4) › **Subclasse** (5).")
    linhas.append("")

    secao_atual = divisao_atual = grupo_atual = classe_atual = None

    def emitir(item: dict[str, str]) -> None:
        nonlocal secao_atual, divisao_atual, grupo_atual, classe_atual
        secao = (item.get("secao") or "").strip()
        divisao = (item.get("divisao") or "").strip()
        grupo = (item.get("grupo") or "").strip()
        classe = (item.get("classe") or "").strip()
        subclasse = (item.get("subclasse") or "").strip()
        desig = item.get("designacao") or ""
        if secao:
            secao_atual, divisao_atual, grupo_atual, classe_atual = secao, None, None, None
            linhas.append(f"## Secção {secao} — {desig}")
            linhas.append("")
            return
        if divisao:
            divisao_atual, grupo_atual, classe_atual = divisao, None, None
            linhas.append(f"### Divisão {divisao} — {desig}")
            linhas.append("")
            return
        if grupo:
            grupo_atual, classe_atual = grupo, None
            linhas.append(f"#### Grupo {grupo} — {desig}")
            linhas.append("")
            return
        if classe and subclasse:
            classe_atual = classe
            # Classe com uma única subclasse (código = classe + «0») e a mesma
            # designação: uma linha só, sem repetir o texto.
            if subclasse == classe + "0":
                linhas.append(f"##### Classe {classe} (subclasse {subclasse}) — {desig}")
            else:
                linhas.append(f"##### Classe {classe} — {desig}")
                linhas.append(f"- **{subclasse}** — {desig}")
            linhas.append("")
            return
        if classe:
            classe_atual = classe
            linhas.append(f"##### Classe {classe} — {desig}")
            linhas.append("")
            return
        if subclasse:
            linhas.append(f"- **{subclasse}** — {desig}")
            return
    for item in itens:
        emitir(item)
    linhas.append("")
    return "\n".join(linhas)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", default=str(DOCS_DIR / "CAE-Rev.4.pdf"))
    parser.add_argument("--out", default=str(DOCS_DIR / "CAE-Rev.4.md"))
    args = parser.parse_args()
    pdf = Path(args.pdf)
    itens = extrair_estrutura(pdf)
    markdown = construir_markdown(itens, pdf.name)
    out = Path(args.out)
    out.write_text(markdown, encoding="utf-8")
    print(f"{len(itens)} linhas -> {out} ({len(markdown)} caracteres)")


if __name__ == "__main__":
    main()
