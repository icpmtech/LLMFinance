"""**Mapa Oficial dos resultados das autárquicas** (CNE) — leitura dos ficheiros.

O Mapa Oficial n.º 2-B/2025 da Comissão Nacional de Eleições é a publicação que
*legalmente* fixa os eleitos: é o único documento oficial que traz os **nomes de
todos os eleitos** (presidentes de câmara, vereadores, assembleias municipais e
de freguesia). O site do MAI publica só quem encabeça cada câmara.

A CNE publica-o em folha de cálculo — um ZIP com três mapas, cada um em `.xlsx`
e `.ods`:

| Ficheiro | O que traz |
| --- | --- |
| `mapa_1_resultados` | Votos por candidatura, por órgão e território |
| `mapa_2_perc_mandatos` | Percentagem de votos e **mandatos** por candidatura |
| `mapa_3_eleitos` | **Os nomes dos eleitos**, por sigla de candidatura |

O `mapa_3_eleitos` não é uma tabela, é um conjunto de blocos: uma linha com
`CÓD | CONC | FREG | ÓRG` abre um bloco, a linha seguinte tem as siglas das
candidaturas (uma por coluna) e as linhas seguintes têm os nomes — cada nome na
coluna da sua candidatura. Os eleitos de uma câmara são, por isso, a soma das
colunas do seu bloco `CM`.

Este módulo lê só isso: descarrega, extrai e devolve os blocos já em listas. Quem
casa os nomes com os territórios (e com os presidentes do MAI) é o serviço das
remunerações — a chave de casamento é dele, não está no ficheiro.
"""
from __future__ import annotations

import logging
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

CNE_BASE = "https://www.cne.pt/sites/default/files/dl/eleicoes/2025_al/docs_geral"
# A versão **retificada** é a que está em vigor: houve retificações publicadas
# depois (a última em agosto de 2026), pelo que é esta que se lê.
CNE_ZIP_URL = f"{CNE_BASE}/2025al-mapa-oficial_retificado.zip"
CNE_PAGINA = "https://www.cne.pt/content/eleicoes-autarquicas-2025"

MAPAS = {
    "mapa_1_resultados": "mapa_1_resultados_retificado.xlsx",
    "mapa_2_mandatos": "mapa_2_perc_mandatos_retificado.xlsx",
    "mapa_3_eleitos": "mapa_3_eleitos_retificado.xlsx",
    "mapa_anexo": "mapa_anexo.xlsx",
}

# Órgãos, tal como o mapa os abrevia.
ORGAO_CAMARA = "CM"
ORGAO_ASSEMBLEIA_MUNICIPAL = "AM"
ORGAO_ASSEMBLEIA_FREGUESIA = "AF"

NOMES_ORGAO = {
    ORGAO_CAMARA: "Câmara Municipal",
    ORGAO_ASSEMBLEIA_MUNICIPAL: "Assembleia Municipal",
    ORGAO_ASSEMBLEIA_FREGUESIA: "Assembleia de Freguesia",
}

CABECALHOS = {"User-Agent": "IQOS/1.0 (analise de financas publicas; contacto@icpm.tech)"}


class ErroCNE(RuntimeError):
    """A CNE não devolveu o mapa, ou o mapa veio noutra forma."""


def _vazio(valor: Any) -> bool:
    return valor is None or str(valor).strip() == ""


def _codigo(valor: Any) -> str:
    """Código do território, sempre com 6 dígitos.

    O `mapa_1` guarda-o como texto (`010100`) e o `mapa_3` como número (`10100`):
    sem o alinhar, os votos de um território não voltavam a encontrar-se com os
    nomes do mesmo território.
    """
    texto = str(valor).strip()
    if texto.isdigit():
        return texto.zfill(6)
    try:
        # O Excel devolve o código tanto como número inteiro como em vírgula
        # flutuante (`10100.0`), e o mapa tem de dar o mesmo nos dois casos.
        return f"{int(float(texto)):06d}"
    except ValueError:
        return texto


def _eh_codigo(valor: Any) -> bool:
    """O CÓD do mapa vem como número (`10100`), às vezes em vírgula flutuante."""
    texto = str(valor).strip()
    if not texto or len(texto) > 8:
        return False
    try:
        float(texto)
    except ValueError:
        return False
    return True


def _sigla_like(valor: str) -> bool:
    """Distingue uma sigla de candidatura de um nome de pessoa.

    O mapa abre grupos novos de candidaturas conforme as colunas acabam — uma
    linha com `IL` a seguir a três nomes abre um grupo para a quinta lista. A
    diferença entre essa linha e uma linha de nomes: uma sigla é curta — tem um
    dígito, um ponto, uma barra ou um hífen, ou é uma ou duas palavras curtas
    (`PS`, `CH`, `GRUPO CIDADÃOS`, `Jonet`) — enquanto um nome de pessoa é um nome
    completo, por norma com três ou mais palavras.
    """
    texto = (valor or "").strip()
    if not texto or len(texto) > 30:
        return False
    if any(caracter in texto for caracter in "0123456789./-"):
        return True
    palavras = texto.split()
    if len(palavras) == 1:
        return True
    return len(palavras) == 2 and texto.isupper()


def ler_blocos(caminho: Path) -> List[Dict[str, Any]]:
    """Lê o `mapa_3_eleitos` e devolve um bloco por território e órgão.

    Um bloco é:

    ```python
    {"cod": "010100", "concelho": "ÁGUEDA", "freguesia": None, "org": "CM",
     "listas": [{"sigla": "PPD/PSD.MPT", "nomes": ["JORGE …", "EDSON …"]}, …]}
    ```

    Quando as candidaturas de um território não cabem nas colunas do mapa, o
    bloco tem **vários grupos** — uma nova linha de siglas reabre a contagem das
    colunas —, pelo que os nomes são distribuídos pelo grupo em vigor.
    """
    import openpyxl

    livro = openpyxl.load_workbook(caminho, read_only=True, data_only=True)
    folha = livro[livro.sheetnames[0]]

    blocos: List[Dict[str, Any]] = []
    atual: Optional[Dict[str, Any]] = None
    listas: List[Dict[str, Any]] = []
    tem_nomes = False

    def fechar_grupo() -> None:
        nonlocal listas, tem_nomes
        if listas:
            atual["listas"].extend(listas)
        listas = []
        tem_nomes = False

    for linha in folha.iter_rows(values_only=True):
        colunas = list(linha)
        if not colunas:
            continue
        primeira = "" if _vazio(colunas[0]) else str(colunas[0]).strip()
        # O cabeçalho do bloco é a linha cujo CÓD é numérico.
        if _eh_codigo(primeira) and len(colunas) > 3:
            if atual:
                fechar_grupo()
                blocos.append(atual)
            atual = {
                "cod": _codigo(primeira),
                "concelho": str(colunas[1]).strip() if not _vazio(colunas[1]) else "",
                "freguesia": str(colunas[2]).strip() if not _vazio(colunas[2]) else None,
                "org": str(colunas[3]).strip() if not _vazio(colunas[3]) else "",
                "listas": [],
            }
            listas = []
            tem_nomes = False
            continue
        if atual is None:
            continue

        preenchidas = [valor for valor in colunas if not _vazio(valor)]
        eh_sigla = bool(preenchidas) and all(
            _sigla_like(str(valor)) for valor in preenchidas
        )
        # A primeira linha de conteúdo do bloco são sempre as siglas; a seguir, só
        # se reabre um grupo depois de já haver nomes.
        if not listas or (eh_sigla and tem_nomes):
            fechar_grupo()
            listas = [
                {"sigla": str(valor).strip(), "nomes": []}
                for valor in colunas
                if not _vazio(valor)
            ]
            continue
        for indice, valor in enumerate(colunas):
            if indice < len(listas) and not _vazio(valor):
                listas[indice]["nomes"].append(str(valor).strip())
                tem_nomes = True

    if atual:
        fechar_grupo()
        blocos.append(atual)
    return blocos


def ler_resultados(caminho: Path) -> Dict[str, Dict[str, Any]]:
    """Votos por candidatura, do `mapa_1_resultados`.

    Devolve, por `(código, órgão)`:

    ```python
    {"inscritos": 41567, "votantes": 23815,
     "votos": [{"sigla": "PPD/PSD.MPT", "votos": 13718}, …]}
    ```

    As colunas de partidos são fixas; as coligações e os grupos de cidadãos
    eleitores vêm em colunas `[A]`…`[G]`, com as siglas dadas à parte — na mesma
    ordem das colunas preenchidas.
    """
    import openpyxl

    livro = openpyxl.load_workbook(caminho, read_only=True, data_only=True)
    folha = livro[livro.sheetnames[0]]
    linhas = [list(linha) for linha in folha.iter_rows(values_only=True)]
    if len(linhas) < 5:
        raise ErroCNE("O mapa dos resultados está vazio.")

    cabecalho = [str(valor).strip() if valor else "" for valor in linhas[3]]
    partidos = {
        indice: nome
        for indice, nome in enumerate(cabecalho)
        if nome and indice >= 8 and not nome.startswith("[")
    }
    colunas_coligacoes = [i for i, nome in enumerate(cabecalho) if nome.startswith("[") and nome not in ("[SIGLA COL]", "[SIGLA GCE]")]
    indice_col = cabecalho.index("[SIGLA COL]") if "[SIGLA COL]" in cabecalho else None
    indice_gce = cabecalho.index("[SIGLA GCE]") if "[SIGLA GCE]" in cabecalho else None

    resultados: Dict[str, Dict[str, Any]] = {}
    for linha in linhas:
        if len(linha) < 4:
            continue
        cod = _codigo(linha[0]) if linha[0] is not None else ""
        org = str(linha[3]).strip() if linha[3] else ""
        if not cod.isdigit() or not org or len(linha) < 8:
            continue
        votos: List[Dict[str, Any]] = []
        for indice, sigla in partidos.items():
            if indice < len(linha) and isinstance(linha[indice], (int, float)) and linha[indice]:
                votos.append({"sigla": sigla, "votos": int(linha[indice])})
        siglas_coligacoes: List[str] = []
        if indice_col is not None and indice_col < len(linha) and linha[indice_col]:
            siglas_coligacoes = [
                parte.strip().strip("[]")
                for parte in str(linha[indice_col]).split(",")
                if parte.strip()
            ]
        siglas_gce: List[str] = []
        if indice_gce is not None and indice_gce < len(linha) and linha[indice_gce]:
            siglas_gce = [
                parte.strip().strip("[]")
                for parte in str(linha[indice_gce]).split(",")
                if parte.strip()
            ]
        restantes = list(siglas_gce)
        for posicao, indice in enumerate(colunas_coligacoes):
            if indice >= len(linha) or not linha[indice]:
                continue
            if posicao < len(siglas_coligacoes):
                sigla = siglas_coligacoes[posicao]
            elif restantes:
                sigla = restantes.pop(0)
            else:
                sigla = f"[{chr(ord('A') + posicao)}]"
            votos.append({"sigla": sigla, "votos": int(linha[indice])})
        resultados[f"{cod}|{org}"] = {
            "cod": cod,
            "org": org,
            "concelho": str(linha[1]).strip() if linha[1] else "",
            "freguesia": str(linha[2]).strip() if linha[2] and str(linha[2]).strip() else None,
            "inscritos": int(linha[4]) if isinstance(linha[4], (int, float)) and linha[4] else None,
            "votantes": int(linha[5]) if isinstance(linha[5], (int, float)) and linha[5] else None,
            "votos": sorted(votos, key=lambda v: -v["votos"]),
        }
    return resultados


def descarregar(destino: Path, forcar: bool = False) -> Path:
    """Descarrega (uma vez) o ZIP do mapa oficial para `destino`."""
    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.exists() and not forcar and destino.stat().st_size > 1_000_000:
        return destino

    resposta = httpx.get(CNE_ZIP_URL, headers=CABECALHOS, timeout=300.0, follow_redirects=True)
    resposta.raise_for_status()
    conteudo = resposta.content
    if len(conteudo) < 1_000_000 or conteudo[:2] != b"PK":
        raise ErroCNE(
            f"A CNE devolveu algo que não é o mapa oficial ({len(conteudo)} bytes). "
            "Nada foi substituído."
        )
    destino.write_bytes(conteudo)
    return destino


def extrair_mapa(zip_path: Path, nome: str, pasta: Path) -> Path:
    """Extrai um dos mapas do ZIP (o `.xlsx`) e devolve o caminho."""
    if nome not in MAPAS:
        raise ErroCNE(f"Mapa desconhecido: {nome}")
    alvo = pasta / MAPAS[nome]
    if alvo.exists() and alvo.stat().st_size > 10_000:
        return alvo
    pasta.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as ficheiro:
        candidatos = [n for n in ficheiro.namelist() if n.endswith(MAPAS[nome])]
        if not candidatos:
            raise ErroCNE(f"O ZIP não traz {MAPAS[nome]}")
        with ficheiro.open(candidatos[0]) as origem:
            alvo.write_bytes(origem.read())
    return alvo


def coletar(pasta: Path, forcar: bool = False) -> Dict[str, Any]:
    """Descarrega, extrai e lê o mapa dos eleitos.

    Devolve os blocos da câmara municipal (as câmaras são o que interessa às
    remunerações) mais as contagens dos outros órgãos, que servem de conferência
    da leitura: Portugal tem 308 câmaras, 308 assembleias municipais e 3241
    assembleias de freguesia (as uniões de freguesia contam como uma).
    """
    zip_path = descarregar(pasta / "cne_mapa_oficial.zip", forcar=forcar)
    ficheiro = extrair_mapa(zip_path, "mapa_3_eleitos", pasta)
    blocos = ler_blocos(ficheiro)
    resultados = ler_resultados(extrair_mapa(zip_path, "mapa_1_resultados", pasta))

    camaras = [b for b in blocos if b["org"] == ORGAO_CAMARA]
    if len(camaras) < 300:
        raise ErroCNE(
            f"O mapa dos eleitos trouxe só {len(camaras)} câmaras; deve estar truncado. "
            "Nada foi substituído."
        )
    contagens: Dict[str, int] = {}
    for bloco in blocos:
        contagens[bloco["org"]] = contagens.get(bloco["org"], 0) + 1

    return {
        "fonte": "Mapa Oficial n.º 2-B/2025 — Comissão Nacional de Eleições",
        "fonte_url": CNE_ZIP_URL,
        "pagina": CNE_PAGINA,
        "eleicao": "Autárquicas 2025",
        "totais_por_orgao": contagens,
        "total_camaras": len(camaras),
        "camaras": camaras,
        "assembleias_municipais": [b for b in blocos if b["org"] == ORGAO_ASSEMBLEIA_MUNICIPAL],
        "assembleias_freguesia": [b for b in blocos if b["org"] == ORGAO_ASSEMBLEIA_FREGUESIA],
        "resultados": resultados,
    }
