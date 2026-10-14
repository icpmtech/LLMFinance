"""Modelo de **remunerações da Administração Pública** (DGAEP).

A DGAEP publica, em PDF por ano, o *Sistema Remuneratório da Administração
Pública* — a peça que consolida tudo o que se pode pagar a quem trabalha em
funções públicas:

* a **Tabela Remuneratória Única (TRU)** — do nível 5 ao 115, o valor mensal de
  cada nível (o nível 5 é a Base Remuneratória da Administração Pública, BRAP);
* as **carreiras e categorias** (gerais, especiais, subsistentes, não revistas),
  cada uma com as suas posições remuneratórias e o nível da TRU que lhes
  corresponde;
* os **cargos dirigentes** e os cargos equiparados, com índice, nível e
  remuneração;
* as **notas** de cada secção e a **base legal** (estrutura da carreira,
  estrutura remuneratória e outras componentes).

Este serviço lê esses PDFs, reconstrói as tabelas com as coordenadas das
palavras (os PDF não têm linhas de grelha em todas as páginas) e guarda um
**modelo** por ano em ``data/remuneracoes-ap/<ano>.json``: níveis da TRU,
carreiras, dirigentes, base legal e notas. É esse modelo que a plataforma
mostra e que o simulador usa para responder «quanto vale esta posição?».

A leitura é **verificável**: cada valor fica com a secção, a carreira/categoria
(e, nos dirigentes, o âmbito e o cargo) de onde saiu, e o simulador só usa o que
está na tabela — nunca estima componentes que a fonte não publica.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
PASTA = ROOT / "data" / "remuneracoes-ap"

FONTE = "DGAEP · Sistema Remuneratório da Administração Pública"
FONTE_URL = "https://www.dgaep.gov.pt/index.cfm?OBJID=2509248D-289A-4B8D-8E44-034CE9B38C22"
URL_BASE = "https://www.dgaep.gov.pt/upload/catalogo/"

#: Os PDF que a DGAEP publica, por ano (o nome muda de ano para ano).
FICHEIROS: Dict[int, str] = {
    2026: "SRAP_2026.pdf",
    2025: "SRAP_2025_V25_06_05_jun.pdf",
    2024: "SRAP_2024_V24_06_05_jun.pdf",
    2023: "SRAP__2023_V1_nov.pdf",
    2022: "SRAP_2022_V3.pdf",
    2021: "SRAP_2021.pdf",
    2020: "SR_AP_2020.pdf",
}

#: Secções do documento, pela ordem em que aparecem. O título de cada uma
#: aparece numa página própria (a «capa» da secção) e é isso que diz a que
#: secção pertencem as páginas seguintes.
SECOES: Tuple[str, ...] = (
    "Tabela Remuneratória Única",
    "Cargos Dirigentes",
    "Carreiras Gerais",
    "Carreiras Especiais",
    "Carreiras Especiais sem Aplicação da Tabela Remuneratória Única (TRU)",
    "Carreiras/Categorias Subsistentes de Regime Geral",
    "Carreiras/Categorias Subsistentes de Regime Especial",
    "Carreiras/Categorias Subsistentes de Corpos Especiais",
    "Carreiras/Categorias Não Revistas de Regime Geral",
    "Carreiras/Categorias Não Revistas de Regime Especial",
    "Carreiras/Categorias Não Revistas de Corpos Especiais",
)

#: As secções que trazem posições remuneratórias (as páginas com `p)/n)/r)`).
SECOES_CARREIRAS: Tuple[str, ...] = tuple(seccao for seccao in SECOES if "Carreiras" in seccao)

#: Nota da TRU que fixa a BRAP — o nível 5 é o valor de referência da AP.
NOTA_BRAP = "a)"

_LOCK = threading.Lock()
_CACHE: Dict[int, Dict[str, Any]] = {}

#: Quatro caracteres que se repetem dentro de uma célula quando o PDF não tem
#: colunas de texto (2020/2021): aí o `get_text("blocks")` junta linhas inteiras
#: da tabela num só parágrafo e esse parágrafo não pode servir de nome.
_INDICIO_MARCADOR = re.compile(r"[pnri]\)")

_MARCADOR = re.compile(r"^(p|n|r|i)\)$")
_SEPARADOR = re.compile(r"^[/|\\-]+$")
_EURO = re.compile(r"^(\d[\d\s.]*)(?:,(\d{2}))?$")
_NIVEL_SIMPLES = re.compile(r"^\d{1,3}$")
_NIVEL_ENTRE = re.compile(r"^\[?\s*(\d{1,3})\s*e\s*(\d{1,3})\s*\]?$")
_NIVEL_MAIOR = re.compile(r"^>\s*(\d{1,3})$")


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sem_acentos(texto: str) -> str:
    base = unicodedata.normalize("NFKD", str(texto or ""))
    return "".join(caractere for caractere in base if not unicodedata.combining(caractere))


def _chave(texto: str) -> str:
    return re.sub(r"\s+", " ", _sem_acentos(texto).lower()).strip()


def _limpar(texto: Any) -> str:
    return re.sub(r"\s+", " ", str(texto or "")).strip()


def _euros(texto: str) -> Optional[float]:
    """Valor em euros a partir do texto de uma célula («1 442,57», «878,41 €»)."""
    limpo = _limpar(texto).replace("€", "").strip().replace("\u00a0", " ")
    achado = _EURO.match(limpo)
    if not achado:
        return None
    inteiro = re.sub(r"[\s.]", "", achado.group(1))
    decimal = achado.group(2) or "00"
    try:
        return round(float(f"{inteiro}.{decimal}"), 2)
    except ValueError:
        return None


def _niveis(texto: str) -> Tuple[List[int], str]:
    """Níveis da TRU a partir da célula da linha `n)`.

    A célula pode trazer um nível («16»), dois, delimitando um intervalo
    («[64 e 65]»), um mínimo («> 115») ou nada («-»). Devolve a lista de níveis e
    o texto original, para nada se perder na conversão.
    """
    limpo = _limpar(texto)
    if not limpo:
        return [], ""
    if _NIVEL_SIMPLES.match(limpo):
        return [int(limpo)], limpo
    achado = _NIVEL_ENTRE.match(limpo)
    if achado:
        return [int(achado.group(1)), int(achado.group(2))], limpo
    achado = _NIVEL_MAIOR.match(limpo)
    if achado:
        return [int(achado.group(1))], limpo
    return [], limpo


# --------------------------------------------------------------------------
# Leitura do PDF: as tabelas são reconstruídas pelas coordenadas das palavras
# --------------------------------------------------------------------------
def _paginas_em_linhas(page: Any) -> List[Dict[str, Any]]:
    """Agrupa as palavras da página em linhas (a tabela não tem grelha)."""
    palavras = sorted(page.get_text("words"), key=lambda w: (round(w[1] / 2) * 2, w[0]))
    linhas: List[Dict[str, Any]] = []
    for palavra in palavras:
        alvo = next((linha for linha in linhas if abs(linha["y"] - palavra[1]) <= 3.5), None)
        if alvo is None:
            alvo = {"y": palavra[1], "palavras": []}
            linhas.append(alvo)
        alvo["palavras"].append(palavra)
    for linha in linhas:
        linha["palavras"].sort(key=lambda w: w[0])
        linha["texto"] = _limpar(" ".join(w[4] for w in linha["palavras"]))
        linha["x0"] = min(w[0] for w in linha["palavras"])
        linha["x1"] = max(w[2] for w in linha["palavras"])
    linhas.sort(key=lambda linha: linha["y"])
    return linhas


def _celulas(linha: Dict[str, Any], *, a_partir_de: float, intervalo: float = 5.0) -> List[Dict[str, Any]]:
    """Células de uma linha: palavras agrupadas por proximidade horizontal.

    O agrupamento pela distância separa bem as células: dentro de um número
    («1 442,57» ou «3 803,29 €») as palavras estão a 2-3 pt, entre células
    vizinhas estão a ~7 pt, por isso o limite fica em 5 pt. Os marcadores
    (`p)`, `n)`, `r)`, `i)`) não são células: são a etiqueta da linha.
    """
    palavras = [w for w in linha["palavras"] if w[0] >= a_partir_de and not _MARCADOR.match(w[4])]
    celulas: List[Dict[str, Any]] = []
    for palavra in palavras:
        if celulas and palavra[0] - celulas[-1]["x1"] < intervalo:
            celulas[-1]["palavras"].append(palavra)
            celulas[-1]["x1"] = max(celulas[-1]["x1"], palavra[2])
        else:
            celulas.append({"x0": palavra[0], "x1": palavra[2], "palavras": [palavra]})
    for celula in celulas:
        celula["texto"] = _limpar(" ".join(w[4] for w in celula["palavras"]))
        celula["centro"] = (celula["x0"] + celula["x1"]) / 2
    return [celula for celula in celulas if celula["texto"]]


def _paragrafos_da_coluna(page: Any, *, limite: float = 150.0) -> List[Dict[str, Any]]:
    """Nomes e títulos da coluna da esquerda, agrupados como o PDF os escreveu.

    A leitura por **parágrafos** (e não linha a linha) é o que permite juntar os
    nomes que o quadro parte em duas linhas («Especialista de sistemas e» /
    «tecnologias de informação» são um só nome) sem juntar nomes diferentes.
    """
    paragrafos: List[Dict[str, Any]] = []
    for bloco in page.get_text("blocks"):
        x0, y0, x1, y1, texto, _, _ = bloco
        # O título pode transbordar da coluna («ADMINISTRADOR HOSPITAL» continua
        # em «DA TOXICODEPENDÊNCIA», fora da coluna): vale pela **origem**.
        if x0 > limite or not _limpar(texto):
            continue
        if y0 < 55 or y0 > 800:
            continue
        limpo = _limpar(texto)
        if y1 - y0 > 34 or len(limpo) > 140 or _INDICIO_MARCADOR.search(limpo):
            continue
        paragrafos.append({"y0": y0, "y1": y1, "texto": limpo})
    paragrafos.sort(key=lambda item: item["y0"])
    return paragrafos



def _marcador(linha: Dict[str, Any], zona: Tuple[float, float] = (140.0, 400.0)) -> Optional[str]:
    """Marcador (`p)`, `n)`, `r)`, `i)`) da linha, quando é uma linha de marcador."""
    for palavra in linha["palavras"]:
        if zona[0] <= palavra[0] <= zona[1] and _MARCADOR.match(palavra[4]):
            return palavra[4][0]
    return None


def _ler_tru(page: Any) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Níveis e valores da Tabela Remuneratória Única (duas tabelas lado a lado)."""
    niveis: List[Dict[str, Any]] = []
    notas: List[str] = []
    for linha in _paginas_em_linhas(page):
        celulas = _celulas(linha, a_partir_de=120.0)
        esquerda = [celula for celula in celulas if celula["x0"] < 300]
        direita = [celula for celula in celulas if celula["x0"] >= 300]
        for coluna in (esquerda, direita):
            if len(coluna) < 2 or not _NIVEL_SIMPLES.match(coluna[0]["texto"]):
                continue
            valor = _euros(coluna[1]["texto"])
            nota = None if valor is not None else coluna[1]["texto"]
            niveis.append(
                {
                    "nivel": int(coluna[0]["texto"]),
                    "valor": valor,
                    "nota": nota,
                }
            )
        if linha["texto"].startswith("Notas:") or linha["x0"] < 140 and "a)" in linha["texto"]:
            notas.append(linha["texto"])
    niveis.sort(key=lambda item: item["nivel"])
    return niveis, notas


def _nome_do_paragrafo(paragrafos: List[Dict[str, Any]], y: float) -> Optional[str]:
    """Parágrafo que é o nome da linha (carreira, categoria ou cargo).

    O nome de uma linha é escrito a par do marcador (`p)`, `i)`), por isso entre
    os parágrafos que cobrem essa altura escolhe-se o que **começa** mais perto
    dela: o parágrafo de cima pode ser o nome da linha anterior, que o PDF
    agrupou no mesmo bloco de texto.
    """
    candidatos = [
        paragrafo
        for paragrafo in paragrafos
        if paragrafo["y0"] - 14 <= y <= paragrafo["y1"] + 4
    ]
    if not candidatos:
        return None
    melhor = min(candidatos, key=lambda paragrafo: abs(paragrafo["y0"] - y))
    return melhor["texto"]


def _blocos(
    linhas: List[Dict[str, Any]],
    zona: Tuple[float, float],
    paragrafos: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Blocos de marcadores consecutivos (`p)/n)/r)` ou `i)/n)/r)`).

    Cada bloco é uma posição/cargo: a linha do primeiro marcador traz as posições
    ou o índice e as linhas seguintes os níveis da TRU e as remunerações. O nome
    da linha e o título acima vêm dos parágrafos da coluna da esquerda.
    """
    paragrafos = paragrafos or []
    blocos: List[Dict[str, Any]] = []
    atual: Optional[Dict[str, Any]] = None
    fim_anterior = 0.0
    for linha in linhas:
        marca = _marcador(linha, zona)
        if marca:
            if atual is None or marca in ("p", "i") or marca in atual["linhas"]:
                if atual is not None:
                    blocos.append(atual)
                    fim_anterior = max(
                        linha_bloco["y"] for linha_bloco in atual["linhas"].values()
                    )
                atual = {"y": linha["y"], "primeiro": marca, "linhas": {}}
            atual["linhas"][marca] = linha
            continue
        if atual is not None and linha["y"] > atual["y"] - 6:
            continue
        if atual is not None:
            blocos.append(atual)
            fim_anterior = max(linha_bloco["y"] for linha_bloco in atual["linhas"].values())
            atual = None
    if atual is not None:
        blocos.append(atual)
        fim_anterior = max(linha_bloco["y"] for linha_bloco in atual["linhas"].values())

    # Nome (o parágrafo que cobre a linha do primeiro marcador) e título acima
    # (os parágrafos entre o fim do bloco anterior e esta linha).
    anterior: Optional[Dict[str, Any]] = None
    for bloco in blocos:
        y = bloco["y"]
        fim = max(linha["y"] for linha in bloco["linhas"].values())
        inicio_anterior = 0.0 if anterior is None else max(
            linha["y"] for linha in anterior["linhas"].values()
        )
        bloco["nome"] = _nome_do_paragrafo(paragrafos, y)
        bloco["titulos"] = [
            paragrafo["texto"]
            for paragrafo in paragrafos
            if paragrafo["y0"] > inicio_anterior + 2 and paragrafo["y1"] < y - 2
        ]
        anterior = bloco
        bloco["fim"] = fim
    return blocos


def _carreira_do_bloco(nome: Optional[str], titulos: List[str], anterior: Optional[Dict[str, Any]]) -> Tuple[str, Optional[str], Optional[str]]:
    """Carreira, variante e título do bloco.

    O título acima do bloco pode ser a **carreira** (quando o nome da linha é uma
    categoria dentro dela, «Assistente técnico» → «Coordenador técnico») ou uma
    **variante** da mesma designação («Técnico superior (posições remuneratórias
    transitórias)»). Sem título novo, o bloco continua a carreira anterior.
    """
    titulo = titulos[-1] if titulos else None
    if not titulo:
        heranca = (anterior or {}).get("carreira")
        return (nome or heranca or ""), None, None
    if nome and _chave(titulo).startswith(_chave(nome)):
        return nome, titulo, titulo
    return titulo, None, titulo



def _nome_da_coluna(linha: Dict[str, Any], limite: float = 140.0) -> str:
    """Nome (carreira/categoria/cargo) na coluna da esquerda da linha."""
    return _limpar(" ".join(w[4] for w in linha["palavras"] if w[2] <= limite))




def _ler_carreiras(page: Any, seccao: str, anterior: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Carreiras/categorias de uma página: posição → nível da TRU → remuneração.

    Os quadros partem uma carreira por várias páginas: quando a página começa a
    meio de uma carreira (sem nome no bloco), o nome vem do último registo lido,
    para as posições não ficarem órfãs.
    """
    linhas = [linha for linha in _paginas_em_linhas(page) if 55 < linha["y"] < 800]
    paragrafos = _paragrafos_da_coluna(page)
    registos: List[Dict[str, Any]] = []
    for bloco in _blocos(linhas, (140.0, 400.0), paragrafos):
        linha_posicoes = bloco["linhas"].get("p") or bloco["linhas"].get("i")
        if linha_posicoes is None:
            continue
        nome = bloco.get("nome") or _nome_da_coluna(linha_posicoes) or (anterior or {}).get("categoria")
        carreira, variante, titulo = _carreira_do_bloco(nome, bloco.get("titulos") or [], anterior)
        posicoes = [
            celula["texto"]
            for celula in _celulas(linha_posicoes, a_partir_de=140.0)
            if not _SEPARADOR.match(celula["texto"])
        ]
        niveis = [
            celula["texto"]
            for celula in _celulas(bloco["linhas"].get("n", linha_posicoes), a_partir_de=140.0)
        ]
        valores = [
            celula["texto"]
            for celula in _celulas(bloco["linhas"].get("r", linha_posicoes), a_partir_de=140.0)
        ]
        itens: List[Dict[str, Any]] = []
        for indice, posicao in enumerate(posicoes):
            lista_niveis, niveis_texto = _niveis(niveis[indice] if indice < len(niveis) else "")
            itens.append(
                {
                    "posicao": posicao,
                    "nivel": lista_niveis[0] if lista_niveis else None,
                    "niveis": lista_niveis,
                    "niveis_texto": niveis_texto,
                    "remuneracao": _euros(valores[indice]) if indice < len(valores) else None,
                }
            )
        if not itens:
            continue
        registo = {
            "seccao": seccao,
            "carreira": carreira or "",
            "categoria": nome or "",
            "variante": variante,
            "titulo": titulo,
            "posicoes": itens,
            "minimo": min((item["remuneracao"] or 0) for item in itens) or None,
            "maximo": max((item["remuneracao"] or 0) for item in itens) or None,
        }
        registos.append(registo)
        anterior = registo
    return registos


def _etiquetas_de_dirigentes(titulos: List[str]) -> List[str]:
    """Títulos do quadro dos dirigentes, sem os cabeçalhos das colunas.

    A coluna da esquerda traz também o título do quadro e as etiquetas das
    colunas («Cargos Dirigentes», «Dirigentes», «ESCALÃO / ÍNDICE / NÍVEL
    REMUNERATÓRIO / REMUNERAÇÃO»); o âmbito e o serviço são o resto.
    """
    ruido = {
        "cargos dirigentes",
        "dirigentes",
        "escalao indice nivel remuneratorio remuneracao",
    }
    limpos: List[str] = []
    for titulo in titulos:
        chave = _chave(titulo)
        if not chave or chave in ruido or "escalao" in chave or "remuneracao" in chave:
            continue
        limpos.append(titulo)
    return limpos


def _ler_dirigentes(
    page: Any,
    seccao: str,
    anterior: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Cargos dirigentes: âmbito, cargo, índice, nível da TRU e remuneração.

    O quadro agrupa os cargos por âmbito («UNIVERSIDADES», «DIRIGENTES –
    ADMINISTRAÇÃO LOCAL») e por serviço; o cabeçalho só aparece antes do primeiro
    cargo do grupo, por isso os cargos seguintes herdam-no.
    """
    linhas = [linha for linha in _paginas_em_linhas(page) if 55 < linha["y"] < 800]
    paragrafos = _paragrafos_da_coluna(page)
    registos: List[Dict[str, Any]] = []
    for bloco in _blocos(linhas, (140.0, 400.0), paragrafos):
        linha_cargo = bloco["linhas"].get("i")
        if linha_cargo is None:
            continue
        cargo = bloco.get("nome") or _nome_da_coluna(linha_cargo) or ""
        etiquetas = _etiquetas_de_dirigentes(list(bloco.get("titulos") or []))
        if not etiquetas and anterior:
            etiquetas = list(anterior.get("etiquetas") or [])
        indices = [celula["texto"] for celula in _celulas(linha_cargo, a_partir_de=140.0)]
        niveis = [
            celula["texto"] for celula in _celulas(bloco["linhas"].get("n", linha_cargo), a_partir_de=140.0)
        ]
        valores = [
            celula["texto"] for celula in _celulas(bloco["linhas"].get("r", linha_cargo), a_partir_de=140.0)
        ]
        if not valores:
            continue
        lista_niveis, niveis_texto = _niveis(niveis[0] if niveis else "")
        indice_texto = indices[0] if indices else ""
        registos.append(
            {
                "seccao": seccao,
                "ambito": etiquetas[0] if etiquetas else None,
                "grupo": etiquetas[-1] if len(etiquetas) > 1 else None,
                "cargo": cargo,
                "etiquetas": etiquetas,
                "indice": int(indice_texto) if _NIVEL_SIMPLES.match(indice_texto) else None,
                "indice_texto": indice_texto,
                "nivel": lista_niveis[0] if lista_niveis else None,
                "niveis": lista_niveis,
                "niveis_texto": niveis_texto,
                "remuneracao": _euros(valores[0]),
            }
        )
        anterior = registos[-1]
    return registos


def _tem_titulo_dirigentes(page: Any) -> bool:
    """A página abre com o título «Dirigentes» na coluna da esquerda?

    Em 2020 e 2021 o quadro dos cargos dirigentes não tem página de capa própria
    e vem depois de outro título; o que o identifica é o **cabeçalho** da tabela
    (a primeira linha da coluna), não a palavra solta no meio de outro quadro.
    """
    paragrafos = [paragrafo for paragrafo in _paragrafos_da_coluna(page) if paragrafo["y0"] < 130]
    return bool(paragrafos) and _chave(paragrafos[0]["texto"]) == "dirigentes"


def _ler_base_legal(page: Any, seccao: str) -> List[Dict[str, Any]]:
    """Tabela de base legal das notas (carreira, grau e os diplomas)."""
    tabelas: List[Dict[str, Any]] = []
    try:
        encontradas = page.find_tables().tables
    except Exception as exc:  # pragma: no cover - depende da versão do pymupdf
        logger.debug("Tabelas da base legal indisponíveis: %s", exc)
        return tabelas
    for tabela in encontradas:
        linhas = tabela.extract()
        if not linhas:
            continue
        cabecalho = [_limpar(celula) for celula in linhas[0]]
        if not any("Legisla" in celula for celula in cabecalho):
            continue
        corpo = []
        for linha in linhas[1:]:
            celulas = [_limpar(celula) for celula in linha]
            if not any(celulas):
                continue
            #  A última célula pode trazer notas de rodapé («(1) Mantida…»).
            if celulas[0] and not celulas[0][0].isalnum():
                corpo.append({"nota": celulas[0]})
                continue
            corpo.append(dict(zip(cabecalho, celulas)))
        if corpo:
            tabelas.append({"seccao": seccao, "cabecalho": cabecalho, "linhas": corpo})
    return tabelas


def _ler_notas(paginas: List[Tuple[int, Any]], seccao: str) -> Dict[str, Any]:
    """Texto das páginas de notas de uma secção (e a respetiva base legal)."""
    texto: List[str] = []
    base_legal: List[Dict[str, Any]] = []
    for _, page in paginas:
        for linha in _paginas_em_linhas(page):
            if 55 < linha["y"] < 800:
                texto.append(linha["texto"])
        base_legal += _ler_base_legal(page, seccao)
    return {"seccao": seccao, "texto": texto, "base_legal": base_legal}


def _seccao_do_titulo(texto: str) -> Optional[str]:
    """Secção a que uma «capa» de secção corresponde."""
    chave = _chave(texto)
    for seccao in SECOES:
        if chave == _chave(seccao):
            return seccao
    return None


def _e_capa(texto: str) -> Optional[str]:
    """A página é a capa de uma secção?"""
    for linha in texto.splitlines():
        seccao = _seccao_do_titulo(linha)
        if seccao:
            return seccao
    return None


def _e_indice(texto: str) -> bool:
    return "Índice Geral" in texto or "Indice Geral" in texto


def _notas_da_seccao(texto: str) -> Optional[str]:
    """Secção a que um título «Notas sobre …» se refere.

    O título pode não ser a primeira linha da página (a caixa do título vem
    antes), por isso procura-se em todas as linhas; o artigo inicial cai, para o
    nome coincidir com o das secções do documento («Notas sobre as Carreiras
    Gerais» → «Carreiras Gerais»).
    """
    for linha in texto.splitlines():
        limpo = _limpar(linha)
        if _chave(limpo).startswith("notas sobre"):
            resto = _limpar(limpo[len("Notas sobre ") :]) or limpo
            resto = re.sub(r"^(os|as|o|a)\s+", "", resto, flags=re.IGNORECASE)
            candidatas = [seccao for seccao in SECOES if _chave(seccao) in _chave(resto)]
            if candidatas:
                return max(candidatas, key=len)
            return resto
    return None


def ler_pdf(caminho: Path, ano: int) -> Dict[str, Any]:
    """Constrói o modelo de um ano a partir do PDF da DGAEP."""
    import pymupdf

    doc = pymupdf.open(str(caminho))
    modelo: Dict[str, Any] = {
        "ano": ano,
        "fonte": {
            "documento": FONTE,
            "url": f"{URL_BASE}{FICHEIROS.get(ano, '')}",
            "catalogo": FONTE_URL,
            "ficheiro": caminho.name,
            "recolhido_em": _agora(),
        },
        "versao": None,
        "niveis": [],
        "tru_notas": [],
        "carreiras": [],
        "dirigentes": [],
        "notas": [],
        "base_legal": [],
    }
    secao_atual: Optional[str] = None
    notas_por_seccao: Dict[str, List[Tuple[int, Any]]] = {}
    ultimo_carreira: Optional[Dict[str, Any]] = None
    ultimo_dirigente: Optional[Dict[str, Any]] = None
    paginas = list(enumerate(doc))
    for numero, page in paginas:
        texto = page.get_text()
        if numero < 3:
            for linha in texto.splitlines():
                if re.match(r"^\d{2}\.\w{3}\.\d{4}$", _limpar(linha)):
                    modelo["versao"] = _limpar(linha)
            continue
        if _e_indice(texto):
            continue
        capa = _e_capa(texto)
        if capa:
            secao_atual = capa
        notas = _notas_da_seccao(texto)
        if notas:
            notas_por_seccao.setdefault(notas, []).append((numero, page))
            continue
        linhas = [linha for linha in _paginas_em_linhas(page) if 55 < linha["y"] < 800]
        marcadores = {_marcador(linha) for linha in linhas}
        marcadores.discard(None)
        if (
            secao_atual not in (None, "Cargos Dirigentes")
            and "i" in marcadores
            and "p" not in marcadores
            and _tem_titulo_dirigentes(page)
        ):
            secao_atual = "Cargos Dirigentes"
        if secao_atual == "Tabela Remuneratória Única" and "REMUNERA" in _sem_acentos(texto).upper():
            niveis, tru_notas = _ler_tru(page)
            chaves = {item["nivel"] for item in modelo["niveis"]}
            modelo["niveis"] += [item for item in niveis if item["nivel"] not in chaves]
            modelo["tru_notas"] += tru_notas
            if niveis:
                continue
        if not any(_marcador(linha) for linha in linhas):
            continue
        if secao_atual == "Cargos Dirigentes":
            pagina_dirigentes = _ler_dirigentes(page, secao_atual, ultimo_dirigente)
            modelo["dirigentes"] += pagina_dirigentes
            if pagina_dirigentes:
                ultimo_dirigente = pagina_dirigentes[-1]
        elif secao_atual and secao_atual in SECOES_CARREIRAS:
            pagina_carreiras = _ler_carreiras(page, secao_atual, ultimo_carreira)
            modelo["carreiras"] += pagina_carreiras
            if pagina_carreiras:
                ultimo_carreira = pagina_carreiras[-1]

    for seccao, paginas_seccao in notas_por_seccao.items():
        dados = _ler_notas(paginas_seccao, seccao)
        modelo["notas"].append({"seccao": seccao, "titulo": f"Notas sobre {seccao}", "texto": dados["texto"]})
        modelo["base_legal"] += dados["base_legal"]

    modelo["niveis"].sort(key=lambda item: item["nivel"])
    modelo["contagens"] = {
        "niveis": len(modelo["niveis"]),
        "carreiras": len(modelo["carreiras"]),
        "posicoes": sum(len(item["posicoes"]) for item in modelo["carreiras"]),
        "dirigentes": len(modelo["dirigentes"]),
        "notas": len(modelo["notas"]),
        "base_legal": len(modelo["base_legal"]),
    }
    doc.close()
    return modelo


# --------------------------------------------------------------------------
# Recolha e persistência
# --------------------------------------------------------------------------
def caminho_do_ano(ano: int) -> Path:
    return PASTA / f"{int(ano)}.json"


def recolher(anos: Optional[Iterable[int]] = None, *, forcar: bool = False) -> Dict[str, Any]:
    """Descarrega e lê os PDF da DGAEP, gravando o modelo de cada ano.

    O PDF de cada ano é guardado em ``data/remuneracoes-ap/pdf`` e o modelo em
    ``data/remuneracoes-ap/<ano>.json``. Com ``forcar`` volta a descarregar.
    """
    lista = sorted({int(ano) for ano in (anos or FICHEIROS)}, reverse=True)
    PASTA.mkdir(parents=True, exist_ok=True)
    (PASTA / "pdf").mkdir(parents=True, exist_ok=True)
    resultado: Dict[str, Any] = {"anos": [], "erros": [], "recolhido_em": _agora()}
    for ano in lista:
        try:
            modelo = recolher_ano(ano, forcar=forcar)
        except Exception as exc:
            logger.warning("Recolha do ano %s falhou: %s", ano, exc)
            resultado["erros"].append({"ano": ano, "erro": str(exc)})
            continue
        resultado["anos"].append({"ano": ano, "contagens": modelo["contagens"], "versao": modelo.get("versao")})
    _escrever_indice(resultado)
    return resultado


def recolher_ano(ano: int, *, forcar: bool = False) -> Dict[str, Any]:
    """Recolhe (descarregando se preciso) e grava o modelo de um ano."""
    destino = caminho_do_ano(ano)
    if destino.exists() and not forcar:
        return ler_modelo(ano) or {}
    nome = FICHEIROS.get(int(ano))
    if not nome:
        raise ValueError(f"Ano sem PDF publicado: {ano}")
    pdf = PASTA / "pdf" / nome
    if forcar or not pdf.exists():
        with httpx.Client(timeout=180.0, follow_redirects=True) as cliente:
            resposta = cliente.get(
                f"{URL_BASE}{nome}",
                headers={"User-Agent": "IQOS/1.0 (analise de financas publicas; contacto@icpm.tech)"},
            )
            resposta.raise_for_status()
            pdf.write_bytes(resposta.content)
    modelo = ler_pdf(pdf, int(ano))
    destino.write_text(json.dumps(modelo, ensure_ascii=False, indent=1), encoding="utf-8")
    with _LOCK:
        _CACHE[int(ano)] = modelo
    return modelo


def ler_modelo(ano: int) -> Optional[Dict[str, Any]]:
    """Modelo de um ano (memória → disco)."""
    ano = int(ano)
    with _LOCK:
        if ano in _CACHE:
            return _CACHE[ano]
    caminho = caminho_do_ano(ano)
    if not caminho.exists():
        return None
    try:
        modelo = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Modelo de %s ilegível: %s", ano, exc)
        return None
    with _LOCK:
        _CACHE[ano] = modelo
    return modelo


def _escrever_indice(resultado: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    indice = {
        "gerado_em": _agora(),
        "anos": anos_disponiveis(),
        "recolha": resultado,
    }
    (PASTA / "indice.json").write_text(json.dumps(indice, ensure_ascii=False, indent=1), encoding="utf-8")
    return indice


def anos_disponiveis() -> List[int]:
    """Anos com modelo em disco."""
    if not PASTA.exists():
        return []
    return sorted(
        (int(caminho.stem) for caminho in PASTA.glob("*.json") if caminho.stem.isdigit()),
        reverse=True,
    )


def ano_de_referencia(ano: Optional[int] = None) -> Optional[int]:
    """Ano pedido, ou o mais recente com modelo."""
    if ano:
        return int(ano) if caminho_do_ano(int(ano)).exists() else None
    anos = anos_disponiveis()
    return anos[0] if anos else None


def modelo(ano: Optional[int] = None) -> Dict[str, Any]:
    """Modelo de um ano (por omissão, o mais recente)."""
    alvo = ano_de_referencia(ano)
    if not alvo:
        return {
            "error": "Ainda não há nenhum ano recolhido. Corra a recolha (`POST /remuneracoes-ap/refresh`).",
            "anos": [],
        }
    dados = ler_modelo(alvo)
    if not dados:
        return {"error": f"Modelo de {alvo} ilegível.", "anos": anos_disponiveis()}
    return dados


def niveis(ano: Optional[int] = None, *, com_valor: bool = False) -> List[Dict[str, Any]]:
    """Tabela Remuneratória Única do ano (nível → valor mensal)."""
    lista = list((modelo(ano) or {}).get("niveis") or [])
    if com_valor:
        lista = [item for item in lista if item.get("valor") is not None]
    return lista


def nivel_valor(ano: Optional[int], nivel: int) -> Optional[float]:
    """Valor mensal de um nível da TRU."""
    for item in niveis(ano):
        if item.get("nivel") == int(nivel):
            return item.get("valor")
    return None


def carreiras(
    ano: Optional[int] = None,
    *,
    q: Optional[str] = None,
    seccao: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Carreiras/categorias do ano, com as posições remuneratórias."""
    lista = list((modelo(ano) or {}).get("carreiras") or [])
    if seccao:
        alvo_seccao = _chave(seccao)
        lista = [item for item in lista if _chave(item.get("seccao") or "") == alvo_seccao]
    if q:
        alvo = _chave(q)
        lista = [
            item
            for item in lista
            if alvo in _chave(f"{item.get('carreira')} {item.get('categoria')} {item.get('seccao')}")
        ]
    return lista


def secao_carreiras(ano: Optional[int] = None) -> List[str]:
    """Secções de carreiras presentes no modelo do ano."""
    return sorted({str(item.get("seccao")) for item in carreiras(ano) if item.get("seccao")})


def dirigentes(
    ano: Optional[int] = None,
    *,
    q: Optional[str] = None,
    ambito: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Cargos dirigentes e equiparados do ano."""
    lista = list((modelo(ano) or {}).get("dirigentes") or [])
    if ambito:
        alvo_ambito = _chave(ambito)
        lista = [item for item in lista if alvo_ambito in _chave(item.get("ambito") or "")]
    if q:
        alvo = _chave(q)
        lista = [
            item
            for item in lista
            if alvo in _chave(f"{item.get('ambito')} {item.get('grupo')} {item.get('cargo')} {item.get('etiquetas')}")
        ]
    return lista


def base_legal(ano: Optional[int] = None, *, q: Optional[str] = None) -> List[Dict[str, Any]]:
    """Base legal por carreira (estrutura da carreira, remuneratória e outras)."""
    tabelas = list((modelo(ano) or {}).get("base_legal") or [])
    if not q:
        return tabelas
    alvo = _chave(q)
    saida: List[Dict[str, Any]] = []
    for tabela in tabelas:
        linhas = [
            linha
            for linha in (tabela.get("linhas") or [])
            if alvo in _chave(" ".join(str(valor) for valor in linha.values()))
        ]
        if linhas:
            saida.append({**tabela, "linhas": linhas})
    return saida


def notas_da_seccao(ano: Optional[int] = None, seccao: Optional[str] = None) -> List[Dict[str, Any]]:
    """Notas do documento (por secção, quando indicada)."""
    lista = list((modelo(ano) or {}).get("notas") or [])
    if not seccao:
        return lista
    alvo = _chave(seccao)
    return [item for item in lista if alvo in _chave(item.get("seccao") or "")]


def serie_dos_niveis(inicio: int = 5, fim: Optional[int] = None) -> List[Dict[str, Any]]:
    """A TRU ano a ano, para se ver a evolução de cada nível."""
    anos = anos_disponiveis()
    linhas: Dict[int, Dict[str, Any]] = {}
    for ano in sorted(anos):
        for item in niveis(ano):
            nivel = item.get("nivel")
            if nivel is None or nivel < inicio or (fim is not None and nivel > fim):
                continue
            linha = linhas.setdefault(nivel, {"nivel": nivel, "valores": {}})
            linha["valores"][str(ano)] = item.get("valor")
    return [linhas[nivel] for nivel in sorted(linhas)]


def parametros_do_ano(ano: Optional[int] = None) -> Dict[str, Any]:
    """Parâmetros de referência do ano: BRAP (nível 5) e a nota que a fixa."""
    alvo = ano_de_referencia(ano)
    if not alvo:
        return {}
    dados = modelo(alvo) or {}
    brap = nivel_valor(alvo, 5)
    notas = [texto for texto in (dados.get("tru_notas") or []) if "Base Remunerat" in texto or "BRAP" in texto]
    ultimo = max((item["nivel"] for item in dados.get("niveis") or [] if item.get("nivel")), default=None)
    return {
        "ano": alvo,
        "brap": brap,
        "brap_nota": _limpar(notas[0]) if notas else None,
        "nivel_minimo": 5,
        "nivel_maximo": ultimo,
        "versao": dados.get("versao"),
    }


# --------------------------------------------------------------------------
# Simulação
# --------------------------------------------------------------------------
#: Pagamentos anuais por omissão: 12 mensalidades + subsídio de férias +
#: subsídio de Natal (Lei n.º 35/2014, LTFP, artigos 149.º a 152.º).
PAGAMENTOS_POR_ANO = 14


def simular(
    *,
    ano: Optional[int] = None,
    nivel: Optional[int] = None,
    carreira: Optional[str] = None,
    categoria: Optional[str] = None,
    posicao: Optional[str] = None,
    cargo: Optional[str] = None,
    ambito: Optional[str] = None,
    grupo: Optional[str] = None,
    indice: Optional[int] = None,
    pagamentos: int = PAGAMENTOS_POR_ANO,
) -> Dict[str, Any]:
    """Quanto vale uma posição: a remuneração base mensal e o ano.

    Aceita três caminhos: o **nível da TRU**, a **posição remuneratória de uma
    carreira/categoria** ou um **cargo dirigente** (pelo cargo, filtrado por
    âmbito/grupo/índice).

    A conta usa **só** o que a tabela da DGAEP publica — o valor mensal do nível
    da TRU (ou da posição/cargo escolhido). As componentes que não estão na
    tabela (suplementos, ajudas de custo, subsídio de refeição) não entram: a
    resposta di-lo, em vez de as estimar.
    """
    alvo = ano_de_referencia(ano)
    if not alvo:
        return {"error": "Sem modelo recolhido para este ano.", "anos": anos_disponiveis()}
    dados = modelo(alvo) or {}
    mensal: Optional[float] = None
    origem: Dict[str, Any] = {"ano": alvo}
    posicoes: List[Dict[str, Any]] = []
    cargos: List[Dict[str, Any]] = []
    pediu_cargo = bool(cargo) or indice is not None

    if pediu_cargo:
        alvo_cargo = _chave(cargo or "")
        alvo_ambito = _chave(ambito or "")
        alvo_grupo = _chave(grupo or "")
        for registo in dados.get("dirigentes") or []:
            if alvo_cargo and alvo_cargo not in _chave(registo.get("cargo") or ""):
                continue
            if alvo_ambito and alvo_ambito != _chave(registo.get("ambito") or ""):
                continue
            if alvo_grupo and alvo_grupo != _chave(registo.get("grupo") or ""):
                continue
            if indice is not None and str(registo.get("indice")) != str(indice):
                continue
            cargos.append(registo)
        if cargos:
            exatos = [registo for registo in cargos if _chave(registo.get("cargo") or "") == alvo_cargo]
            escolhido = (exatos or cargos)[0]
            mensal = escolhido.get("remuneracao")
            origem.update(
                {
                    "seccao": escolhido.get("seccao"),
                    "ambito": escolhido.get("ambito"),
                    "grupo": escolhido.get("grupo"),
                    "cargo": escolhido.get("cargo"),
                    "indice": escolhido.get("indice"),
                    "nivel": escolhido.get("nivel"),
                    "niveis": escolhido.get("niveis_texto"),
                    "via": "Cargo dirigente e equiparado",
                }
            )
            if mensal is None and escolhido.get("nivel"):
                mensal = nivel_valor(alvo, int(escolhido["nivel"]))
                origem["via"] = "Nível da TRU do cargo dirigente"
    elif nivel:
        mensal = nivel_valor(alvo, int(nivel))
        origem["nivel"] = int(nivel)
        origem["via"] = "Tabela Remuneratória Única"
        item_nivel = next((item for item in dados.get("niveis") or [] if item["nivel"] == int(nivel)), None)
        if item_nivel and item_nivel.get("nota") and mensal is None:
            origem["nota"] = item_nivel["nota"]
    else:
        alvo_carreira = _chave(carreira or "")
        alvo_categoria = _chave(categoria or "")
        for registo in dados.get("carreiras") or []:
            if alvo_carreira and alvo_carreira not in _chave(registo.get("carreira") or ""):
                continue
            if alvo_categoria and alvo_categoria != _chave(registo.get("categoria") or ""):
                continue
            posicoes += [
                {**linha, "carreira": registo.get("carreira"), "categoria": registo.get("categoria"), "seccao": registo.get("seccao")}
                for linha in registo.get("posicoes") or []
            ]
        if posicao:
            posicoes = [linha for linha in posicoes if str(linha.get("posicao")) == str(posicao)]
        if posicoes:
            escolhida = posicoes[0] if posicao else max(posicoes, key=lambda linha: linha.get("remuneracao") or 0)
            mensal = escolhida.get("remuneracao")
            origem.update(
                {
                    "carreira": escolhida.get("carreira"),
                    "categoria": escolhida.get("categoria"),
                    "posicao": escolhida.get("posicao"),
                    "nivel": escolhida.get("nivel"),
                    "seccao": escolhida.get("seccao"),
                    "via": "Posição remuneratória da carreira",
                }
            )
            if mensal is None and escolhida.get("nivel"):
                mensal = nivel_valor(alvo, int(escolhida["nivel"]))
                origem["via"] = "Nível da TRU da posição escolhida"
                origem["nivel_origem"] = escolhida.get("niveis_texto")
    if mensal is None:
        if pediu_cargo:
            erro = (
                "Esse cargo dirigente não tem remuneração publicada no quadro deste ano."
                if cargos
                else "Não encontrei esse cargo dirigente na tabela deste ano."
            )
        else:
            erro = "Não encontrei essa posição na tabela deste ano."
        return {
            "error": erro,
            "ano": alvo,
            "origem": origem,
            "posicoes_disponiveis": posicoes[:20],
            "cargos_disponiveis": _cargos_para_simulacao(cargos or (dados.get("dirigentes") or [])),
        }
    mensal = float(mensal)
    duodecimos = False
    return {
        "ano": alvo,
        "origem": origem,
        "remuneracao_base_mensal": round(mensal, 2),
        "pagamentos_por_ano": int(pagamentos),
        "remuneracao_base_anual": round(mensal * int(pagamentos), 2),
        "duodecimos": duodecimos,
        "posicoes_disponiveis": [
            {
                "posicao": linha.get("posicao"),
                "nivel": linha.get("nivel"),
                "remuneracao": linha.get("remuneracao"),
                "carreira": linha.get("carreira"),
                "categoria": linha.get("categoria"),
            }
            for linha in posicoes[:20]
        ],
        "cargos_disponiveis": _cargos_para_simulacao(cargos),
        "notas": [
            "remuneração base mensal lida da tabela da DGAEP para este ano",
            f"{int(pagamentos)} pagamentos por ano (12 mensalidades + subsídio de férias + subsídio de Natal)",
            "suplementos, subsídio de refeição e outras componentes não fazem parte desta tabela",
        ],
    }


def _cargos_para_simulacao(cargos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Alternativas de cargos dirigentes devolvidas com o resultado (até 20)."""
    return [
        {
            "ambito": registo.get("ambito"),
            "grupo": registo.get("grupo"),
            "cargo": registo.get("cargo"),
            "indice": registo.get("indice"),
            "nivel": registo.get("nivel"),
            "niveis_texto": registo.get("niveis_texto"),
            "remuneracao": registo.get("remuneracao"),
        }
        for registo in cargos[:20]
    ]


# --------------------------------------------------------------------------
# Metamodelo e indexação
# --------------------------------------------------------------------------
def stats(ano: Optional[int] = None) -> Dict[str, Any]:
    """Volumetria do que está recolhido."""
    alvo = ano_de_referencia(ano)
    dados = modelo(alvo) if alvo else {}
    contagens = (dados or {}).get("contagens") or {}
    return {
        "anos": anos_disponiveis(),
        "ano": alvo,
        "versao": (dados or {}).get("versao"),
        "contagens": contagens,
        "nivel_minimo": min((item["nivel"] for item in (dados or {}).get("niveis") or []), default=None),
        "nivel_maximo": max((item["nivel"] for item in (dados or {}).get("niveis") or []), default=None),
        "parametros": parametros_do_ano(alvo),
    }


def meta() -> Dict[str, Any]:
    """Proveniência e metamodelo do módulo."""
    return {
        "fonte": FONTE,
        "fonte_url": FONTE_URL,
        "catalogo": FONTE_URL,
        "url_base": URL_BASE,
        "ficheiros": {str(ano): nome for ano, nome in sorted(FICHEIROS.items(), reverse=True)},
        "anos": anos_disponiveis(),
        "ano": ano_de_referencia(),
        "secoes": list(SECOES),
        "secoes_carreiras": list(SECOES_CARREIRAS),
        "parametros": parametros_do_ano(),
        "stats": stats(),
        "pagamentos_por_ano": PAGAMENTOS_POR_ANO,
        "unidade": "euros por mês (remuneração base)",
        "nota": (
            "O documento é o quadro consolidado da DGAEP: TRU, carreiras e categorias, "
            "cargos dirigentes e a base legal de cada carreira. As componentes que não "
            "constam da tabela (suplementos, subsídio de refeição) não são estimadas."
        ),
    }


def _docs_para_indice() -> List[Dict[str, Any]]:
    """Um documento por nível, por carreira e por cargo dirigente (todos os anos)."""
    documentos: List[Dict[str, Any]] = []
    for ano in anos_disponiveis():
        dados = ler_modelo(ano) or {}
        for item in dados.get("niveis") or []:
            documentos.append(
                {
                    "doc_id": f"nivel-{ano}-{item['nivel']}",
                    "tipo": "nivel",
                    "ano": ano,
                    "nivel": item["nivel"],
                    "remuneracao": item.get("valor"),
                    "nota": item.get("nota"),
                    "texto": f"TRU {ano} nível {item['nivel']}",
                }
            )
        for item in dados.get("carreiras") or []:
            for posicao in item.get("posicoes") or []:
                documentos.append(
                    {
                        "doc_id": f"posicao-{ano}-{_chave(item.get('carreira'))}-{_chave(item.get('categoria'))}-{posicao.get('posicao')}",
                        "tipo": "posicao",
                        "ano": ano,
                        "seccao": item.get("seccao"),
                        "carreira": item.get("carreira"),
                        "categoria": item.get("categoria"),
                        "posicao": posicao.get("posicao"),
                        "nivel": posicao.get("nivel"),
                        "niveis": posicao.get("niveis"),
                        "niveis_texto": posicao.get("niveis_texto"),
                        "remuneracao": posicao.get("remuneracao"),
                        "texto": f"{item.get('carreira')} {item.get('categoria')} posição {posicao.get('posicao')}",
                    }
                )
        for item in dados.get("dirigentes") or []:
            documentos.append(
                {
                    "doc_id": f"dirigente-{ano}-{_chave(item.get('ambito'))}-{_chave(item.get('cargo'))}-{item.get('indice')}",
                    "tipo": "dirigente",
                    "ano": ano,
                    "ambito": item.get("ambito"),
                    "grupo": item.get("grupo"),
                    "cargo": item.get("cargo"),
                    "indice": item.get("indice"),
                    "nivel": item.get("nivel"),
                    "niveis": item.get("niveis"),
                    "niveis_texto": item.get("niveis_texto"),
                    "remuneracao": item.get("remuneracao"),
                    "texto": f"{item.get('ambito')} {item.get('cargo')}",
                }
            )
    return documentos


def indexar() -> Dict[str, Any]:
    """Indexa o modelo no Elasticsearch (um documento por linha de tabela)."""
    from api.elasticsearch_client import get_es_client, index_remuneracoes_ap_bulk

    cliente = get_es_client()
    if not cliente:
        return {"error": "Elasticsearch indisponível", "indexed": 0}
    return index_remuneracoes_ap_bulk(_docs_para_indice(), es=cliente)
