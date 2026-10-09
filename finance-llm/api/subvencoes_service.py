"""Subvenções e outros benefícios públicos (Lei n.º 64/2013, de 27/08).

A IGF publica, em `.ods`, a *LISTAGEM DAS SUBVENÇÕES E OUTROS BENEFÍCIOS
PÚBLICOS* de cada ano. Cada ficheiro tem uma folha (`Subv_<ano>`) com **duas
linhas de cabeçalho** (a segunda subdivide «FUNDAMENTO LEGAL» em *tipo de ato*,
*número* e *data*) e uma linha por apoio concedido:

| # | Coluna |
|---|--------|
| 0 | `NIF (EO)` — NIF da entidade obrigada ao reporte |
| 1 | `ENTIDADE OBRIGADA (EO)` |
| 2 | `NIF (B)` — NIF do beneficiário (com a letra «E» quando é estrangeiro) |
| 3 | `BENEFICIÁRIO (B)` |
| 4 | `MONTANTE TRANSFERIDO OU BENEFÍCIO AUFERIDO (euros)` |
| 5 | `DATA DA DECISÃO` |
| 6 | `FINALIDADE` |
| 7 | `TIPO DE ATO` (sob «FUNDAMENTO LEGAL») |
| 8 | `N.º` |
| 9 | `DATA` (do ato) |

O módulo **lê a pasta `data/subvencoes` por ano**:

* o ano vem da subpasta (`data/subvencoes/2024/…`) ou do nome do ficheiro
  (`lista-subvpublicas2025_1.ods`) — nesta pasta convivem os dois casos;
* a leitura é feita em *streaming* (`xml.etree.ElementTree.iterparse`), porque
  cada ficheiro tem ~200 mil linhas e o `content.xml` descomprimido é enorme;
* cada ficheiro é normalizado para **JSONL** em `data/subvencoes/_normalized/`
  e só depois indexado (`finance_subvencoes`), com um documento por ficheiro em
  `finance_subvencoes_lotes`.

O mesmo apoio aparece em **várias listagens** (a de 2025 repete decisões de
2022), pelo que o ano guardado é o da **listagem** e o `doc_id` é
`<ano>:<linha>`: reindexar o mesmo ficheiro sobrepõe-se em vez de duplicar.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import os
import re
import threading
import unicodedata
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pastas e manifesto
# ---------------------------------------------------------------------------

DATA_DIR_ENV = "SUBVENCOES_DATA_DIR"
_DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "subvencoes"
_NORMALIZED_DIRNAME = "_normalized"
_MANIFEST = "_manifest.json"

#: Sufixos lidos da pasta (o `.ods` é o formato oficial da IGF).
SUFIXOS = (".ods", ".csv")

#: Trabalhos (leitura e indexação) em segundo plano.
_JOBS: Dict[str, Dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()
_JOBS_KEEP = 20
_RUNNING = "running"

#: Colunas do ficheiro, por ordem, com o rótulo que as identifica no cabeçalho.
COLUNAS: List[Tuple[str, str]] = [
    ("nif_entidade", "NIF (EO)"),
    ("entidade", "ENTIDADE OBRIGADA"),
    ("nif_beneficiario", "NIF (B)"),
    ("beneficiario", "BENEFICI"),
    ("montante", "MONTANTE"),
    ("data_decisao", "DATA DA DECIS"),
    ("finalidade", "FINALIDADE"),
    ("tipo_ato", "TIPO DE ATO"),
    ("numero_ato", "N.º"),
    ("data_ato", "DATA"),
]

#: Nº de linhas que compõem o cabeçalho do `.ods` da IGF.
LINHAS_CABECALHO = 2

#: Classificação do beneficiário a partir do prefixo do NIF (aproximação
#: documentada — o ficheiro não traz o tipo).
TIPOS_BENEFICIARIO = {
    "pessoa_singular": "Pessoa singular",
    "pessoa_coletiva": "Pessoa coletiva",
    "empresario_individual": "Empresário em nome individual",
    "entidade_publica": "Entidade pública",
    "outro": "Outro",
}

_ORDENACOES = ("relevancia", "montante", "data", "beneficiario", "entidade", "ano")

# Namespaces do ODF (`.ods`).
_T = "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}"
_O = "{urn:oasis:names:tc:opendocument:xmlns:office:1.0}"
_X = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"


# ---------------------------------------------------------------------------
# Pastas
# ---------------------------------------------------------------------------


def data_dir() -> Path:
    """Pasta raiz dos ficheiros de subvenções (criada se não existir)."""
    raw = (os.environ.get(DATA_DIR_ENV) or "").strip()
    path = Path(raw).expanduser() if raw else _DEFAULT_DATA_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def normalized_dir() -> Path:
    """Pasta dos JSONL normalizados."""
    path = data_dir() / _NORMALIZED_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def _manifest_path() -> Path:
    return data_dir() / _MANIFEST


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _slug(valor: str) -> str:
    normalizado = unicodedata.normalize("NFKD", str(valor or ""))
    limpo = "".join(c for c in normalizado if not unicodedata.combining(c))
    limpo = re.sub(r"[^A-Za-z0-9._-]+", "-", limpo).strip("-._")
    return limpo.lower() or "ficheiro"


# ---------------------------------------------------------------------------
# Descoberta dos ficheiros (por ano)
# ---------------------------------------------------------------------------

_ANO_NO_NOME = re.compile(r"(?:^|[^0-9])((?:19|20)\d{2})(?!\d)")


def _ano_no_texto(texto: str) -> Optional[int]:
    """Primeiro ano plausível (19xx/20xx) no texto."""
    achado = _ANO_NO_NOME.search(str(texto or ""))
    return int(achado.group(1)) if achado else None


def _ano_do_caminho(path: Path, base: Path) -> Tuple[Optional[int], str]:
    """Ano de um ficheiro e a origem dessa conclusão.

    1. subpasta numérica (`data/subvencoes/2024/…`) — o mais explícito;
    2. nome do ficheiro (`lista-subvpublicas2025_1.ods`);
    3. nada (fica `None`, e a leitura usa a folha do `.ods`).
    """
    try:
        relativo = path.relative_to(base)
    except ValueError:
        relativo = Path(path.name)
    for parte in reversed(relativo.parts[:-1]):
        if parte.isdigit() and len(parte) == 4:
            return int(parte), "pasta"
    ano = _ano_no_texto(path.stem)
    if ano:
        return ano, "nome"
    return None, ""


def _sha256(path: Path) -> Tuple[str, int]:
    digest = hashlib.sha256()
    tamanho = 0
    with path.open("rb") as fh:
        for bloco in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(bloco)
            tamanho += len(bloco)
    return digest.hexdigest(), tamanho


def ficheiros() -> List[Dict[str, Any]]:
    """Ficheiros de subvenções encontrados na pasta, com o ano atribuído.

    Percorre a pasta (incluindo subpastas por ano) e ignora a pasta interna dos
    JSONL normalizados. Devolve a lista ordenada por ano decrescente.
    """
    base = data_dir()
    itens: List[Dict[str, Any]] = []
    for path in sorted(base.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUFIXOS:
            continue
        relativo = path.relative_to(base)
        if relativo.parts and relativo.parts[0] == _NORMALIZED_DIRNAME:
            continue
        if path.name.startswith("~$") or path.name == _MANIFEST:
            continue
        ano, origem_ano = _ano_do_caminho(path, base)
        try:
            stat = path.stat()
        except OSError:
            continue
        itens.append(
            {
                "rel_path": relativo.as_posix(),
                "path": str(path),
                "ficheiro": path.name,
                "ano": ano,
                "ano_origem": origem_ano,
                "bytes": stat.st_size,
                "modificado_em": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(timespec="seconds"),
                "sufixo": path.suffix.lower().lstrip("."),
            }
        )
    itens.sort(key=lambda item: (-(item.get("ano") or 0), str(item.get("rel_path"))))
    return itens


# ---------------------------------------------------------------------------
# Manifesto (o que já foi lido)
# ---------------------------------------------------------------------------


def read_manifest() -> Dict[str, Any]:
    """Manifesto das leituras (vazio se ainda não houver)."""
    caminho = _manifest_path()
    if not caminho.exists():
        return {"lotes": {}, "atualizado_em": None}
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - um manifesto corrompido não trava o módulo
        logger.warning("Subvenções: manifesto ilegível (%s)", exc)
        return {"lotes": {}, "atualizado_em": None}
    if not isinstance(dados, dict):
        return {"lotes": {}, "atualizado_em": None}
    dados.setdefault("lotes", {})
    return dados


def _write_manifest(manifest: Dict[str, Any]) -> None:
    manifest["atualizado_em"] = _now()
    caminho = _manifest_path()
    temporario = caminho.with_suffix(".tmp")
    temporario.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    temporario.replace(caminho)


def jsonl_path(lote: Dict[str, Any]) -> Optional[Path]:
    """Caminho do JSONL de um lote, ou `None` se o lote não tiver JSONL.

    O manifesto guarda só o **nome do ficheiro** (relativo a `_normalized/`),
    nunca um caminho absoluto: a mesma pasta `data/subvencoes` é lida do
    anfitrião (`C:\\…`) e de dentro do contentor (`/app/…`), e um caminho
    absoluto gravado num dos lados não existe no outro.

    Devolver `None` (e não um `Path` vazio) é deliberado: `Path("")` é o
    diretório atual, pelo que `.exists()` daria `True` para um lote sem JSONL.
    """
    guardado = str(lote.get("jsonl") or lote.get("jsonl_path") or "").strip()
    nome = Path(guardado).name if guardado else ""
    return (normalized_dir() / nome) if nome else None


def tem_jsonl(lote: Dict[str, Any]) -> bool:
    """O lote já tem o JSONL em disco?"""
    caminho = jsonl_path(lote)
    return caminho is not None and caminho.exists()


def listar_lotes() -> Dict[str, Any]:
    """Lotes lidos, agrupados por ano (mais recentes primeiro)."""
    manifest = read_manifest()
    lotes = list((manifest.get("lotes") or {}).values())
    lotes.sort(key=lambda lote: (-(lote.get("ano") or 0), str(lote.get("rel_path"))))
    anos: Dict[int, Dict[str, Any]] = {}
    for lote in lotes:
        ano = lote.get("ano")
        if ano is None:
            continue
        entrada = anos.setdefault(int(ano), {"ano": int(ano), "ficheiros": 0, "registos": 0, "montante": 0.0})
        entrada["ficheiros"] += 1
        entrada["registos"] += int(lote.get("registos") or 0)
        entrada["montante"] += float(lote.get("montante_total") or 0.0)
    return {
        "dir": str(data_dir()),
        "total": len(lotes),
        "registos": sum(int(lote.get("registos") or 0) for lote in lotes),
        "montante": round(sum(float(lote.get("montante_total") or 0.0) for lote in lotes), 2),
        "items": lotes,
        "por_ano": [anos[ano] for ano in sorted(anos, reverse=True)],
        "atualizado_em": manifest.get("atualizado_em"),
    }


# ---------------------------------------------------------------------------
# Leitura dos `.ods` (streaming)
# ---------------------------------------------------------------------------


def _celula_texto(celula) -> str:
    """Valor de uma célula: o valor tipado do ODF ou, na falta dele, o texto."""
    valor = celula.get(_O + "value")
    if valor is None:
        valor = celula.get(_O + "date-value")
    if valor is None:
        valor = celula.get(_O + "time-value")
    if valor is None:
        partes = [t for t in celula.itertext() if t and t.strip()]
        valor = " ".join(partes)
    return " ".join(str(valor or "").split())


def _iter_ods_rows(path: Path) -> Iterator[Tuple[str, List[str]]]:
    """Percorre as linhas de um `.ods` sem carregar o ficheiro para memória.

    Emite `(folha, células)`. Células repetidas (`number-columns-repeated`) são
    expandidas — com um teto, para as linhas com milhares de colunas vazias não
    rebentarem a memória — e as células tapadas por um `span` são contadas como
    vazias, para que a posição das colunas se mantenha.
    """
    import xml.etree.ElementTree as ET

    with zipfile.ZipFile(path) as zf:
        with zf.open("content.xml") as stream:
            folha: Optional[str] = None
            for evento, elem in ET.iterparse(stream, events=("start", "end")):
                if evento == "start":
                    if elem.tag == _T + "table":
                        folha = elem.get(_T + "name") or "?"
                    continue
                if elem.tag == _T + "table":
                    folha = None
                    elem.clear()
                    continue
                if elem.tag != _T + "table-row":
                    continue
                celulas: List[str] = []
                for celula in elem:
                    tag = celula.tag
                    if tag not in (_T + "table-cell", _T + "covered-table-cell"):
                        continue
                    repetidas = min(int(celula.get(_T + "number-columns-repeated") or 1), 64)
                    if tag == _T + "covered-table-cell":
                        celulas.extend([""] * repetidas)
                        continue
                    valor = _celula_texto(celula)
                    celulas.extend([valor] * repetidas)
                    tapadas = int(celula.get(_T + "number-columns-spanned") or 1)
                    if tapadas > 1:
                        celulas.extend([""] * (tapadas - 1))
                while celulas and not celulas[-1]:
                    celulas.pop()
                yield folha or "?", celulas
                elem.clear()


def _e_cabecalho(celulas: Sequence[str]) -> bool:
    """Reconhece a linha de cabeçalho (as notas do topo não contam).

    As notas mencionam «NIF(B)» e «beneficiários», pelo que o critério exige os
    dois rótulos que só existem no cabeçalho a sério.
    """
    texto = " ".join(celulas).upper()
    return "ENTIDADE OBRIGADA" in texto and "MONTANTE" in texto


def _completar_cabecalho(cabecalho: List[str], linha: Sequence[str]) -> None:
    """Junta a 2.ª linha do cabeçalho (subdivide «FUNDAMENTO LEGAL»)."""
    for indice, valor in enumerate(linha):
        if not valor:
            continue
        if indice >= len(cabecalho):
            cabecalho.extend([""] * (indice + 1 - len(cabecalho)))
        cabecalho[indice] = valor


def mapa_colunas(cabecalho: Sequence[str]) -> List[int]:
    """Índice de cada campo em `COLUNAS`, pelo rótulo do cabeçalho.

    Se um rótulo não for encontrado (ficheiro com cabeçalho diferente), o campo
    fica na posição esperada — a leitura nunca falha por causa do cabeçalho.
    """
    rotulos = [(valor or "").upper() for valor in cabecalho]
    usados: set[int] = set()
    indices: List[int] = []
    for posicao, (_campo, rotulo) in enumerate(COLUNAS):
        alvo = rotulo.upper()
        achado = next((i for i, valor in enumerate(rotulos) if i not in usados and alvo in valor), None)
        if achado is None:
            achado = posicao
        usados.add(achado)
        indices.append(achado)
    return indices


def _iter_registos_ods(path: Path) -> Iterator[Dict[str, Any]]:
    """Registos de um `.ods` (o cabeçalho é detetado e consumido aqui)."""
    cabecalho: Optional[List[str]] = None
    indices: List[int] = []
    folha_cabecalho: Optional[str] = None
    faltam = 0
    linha_nº = 0
    for folha, celulas in _iter_ods_rows(path):
        linha_nº += 1
        if not any(celulas):
            continue
        if cabecalho is None:
            if not _e_cabecalho(celulas):
                continue
            cabecalho = list(celulas)
            folha_cabecalho = folha
            # Só há 2.ª linha de cabeçalho quando a 1.ª não traz as 10 colunas.
            faltam = 0 if len([c for c in celulas if c]) >= len(COLUNAS) else LINHAS_CABECALHO - 1
            continue
        if faltam:
            _completar_cabecalho(cabecalho, celulas)
            faltam -= 1
            continue
        if _e_cabecalho(celulas):
            continue  # cabeçalho repetido a meio do ficheiro
        indices = indices or mapa_colunas(cabecalho)
        yield {"folha": folha_cabecalho or folha, "linha": linha_nº, "celulas": list(celulas), "indices": indices}


def _iter_registos_csv(path: Path) -> Iterator[Dict[str, Any]]:
    """Registos de um `.csv` com o mesmo esquema de colunas."""
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        amostra = fh.read(4096)
        fh.seek(0)
        try:
            dialecto = csv.Sniffer().sniff(amostra, delimiters=";,\t")
            delimitador = dialecto.delimiter
        except Exception:  # noqa: BLE001
            delimitador = ";" if amostra.count(";") >= amostra.count(",") else ","
        leitor = csv.reader(fh, delimiter=delimitador)
        cabecalho: Optional[List[str]] = None
        indices: List[int] = []
        falta_segunda = False
        for numero, linha in enumerate(leitor, start=1):
            celulas = [str(c or "").strip() for c in linha]
            while celulas and not celulas[-1]:
                celulas.pop()
            if not any(celulas):
                continue
            if cabecalho is None:
                if not _e_cabecalho(celulas):
                    continue
                cabecalho = list(celulas)
                falta_segunda = len([c for c in celulas if c]) < len(COLUNAS)
                continue
            if falta_segunda:
                _completar_cabecalho(cabecalho, celulas)
                falta_segunda = False
                continue
            indices = indices or mapa_colunas(cabecalho)
            yield {"folha": path.stem, "linha": numero, "celulas": celulas, "indices": indices}


def _iter_registos(path: Path) -> Iterator[Dict[str, Any]]:
    sufixo = path.suffix.lower()
    if sufixo == ".ods":
        yield from _iter_registos_ods(path)
    elif sufixo == ".csv":
        yield from _iter_registos_csv(path)
    else:  # pragma: no cover - a descoberta já filtra os sufixos
        raise ValueError(f"Formato não suportado: {path.name}")


# ---------------------------------------------------------------------------
# Normalização dos valores
# ---------------------------------------------------------------------------


def _limpar_texto(valor: Any) -> str:
    return " ".join(str(valor or "").split())


def limpar_nif(valor: Any) -> str:
    """NIF/NIPC: 9 dígitos (vazio se não tiver essa forma)."""
    digitos = re.sub(r"\D", "", str(valor or ""))
    return digitos if len(digitos) == 9 else ""


def limpar_nif_beneficiario(valor: Any) -> Tuple[str, bool]:
    """NIF do beneficiário e se é estrangeiro.

    A nota b) do ficheiro explica que, aos beneficiários estrangeiros, a IGF
    acrescentou a letra «E» no campo `NIF(B)` — a letra é sinal, não dado.
    """
    texto = _limpar_texto(valor)
    letras = re.sub(r"[^A-Za-z]", "", texto).upper()
    return limpar_nif(texto), bool(letras)


def tipo_beneficiario(nif: str) -> Optional[str]:
    """Classificação do beneficiário pelo prefixo do NIF (aproximação)."""
    if not nif or len(nif) != 9:
        return None
    primeiro = nif[0]
    if primeiro in "123":
        return "pessoa_singular"
    if primeiro == "6":
        return "entidade_publica"
    if primeiro == "8":
        return "empresario_individual"
    if primeiro in "57":
        return "pessoa_coletiva"
    return "outro"


def para_float(valor: Any) -> Optional[float]:
    """Montante em euros (`1.234,56`, `1234.56`, `1 234 €`)."""
    texto = _limpar_texto(valor).replace("€", "").replace("\xa0", "").replace(" ", "")
    if not texto:
        return None
    if "," in texto and "." in texto:
        # O separador decimal é o que estiver mais à direita.
        if texto.rfind(",") > texto.rfind("."):
            texto = texto.replace(".", "").replace(",", ".")
        else:
            texto = texto.replace(",", "")
    elif "," in texto:
        texto = texto.replace(",", ".")
    try:
        return round(float(texto), 2)
    except (TypeError, ValueError):
        return None


def para_data(valor: Any) -> Optional[str]:
    """Data em `AAAA-MM-DD` (aceita ISO, `AAAA-MM-DDThh:mm:ss` e `DD/MM/AAAA`)."""
    texto = _limpar_texto(valor)
    if not texto:
        return None
    iso = re.match(r"^(\d{4})-(\d{2})-(\d{2})", texto)
    if iso:
        return f"{iso.group(1)}-{iso.group(2)}-{iso.group(3)}"
    nacional = re.match(r"^(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})$", texto)
    if nacional:
        return f"{nacional.group(3)}-{int(nacional.group(2)):02d}-{int(nacional.group(1)):02d}"
    # Data em série do ODF (dias desde 1899-12-30).
    if re.fullmatch(r"\d{5}", texto):
        try:
            from datetime import date, timedelta

            return (date(1899, 12, 30) + timedelta(days=int(texto))).isoformat()
        except Exception:  # noqa: BLE001
            return None
    return None


def fundamento_legal(tipo_ato: Optional[str], numero_ato: Optional[str]) -> Optional[str]:
    """Citação legível: `Lei n.º 75`."""
    tipo = _limpar_texto(tipo_ato)
    numero = _limpar_texto(numero_ato)
    if tipo and numero:
        return f"{tipo} n.º {numero}"
    return tipo or numero or None


def registo_de_linha(
    *,
    celulas: Sequence[str],
    indices: Sequence[int],
    ano: Optional[int],
    ficheiro: str,
    folha: str,
    linha: int,
    lido_em: str,
) -> Optional[Dict[str, Any]]:
    """Uma linha do ficheiro → documento (ou `None` se não for um registo válido)."""

    def campo(posicao: int) -> str:
        indice = indices[posicao] if posicao < len(indices) else posicao
        return str(celulas[indice]) if 0 <= indice < len(celulas) else ""

    nif_entidade = limpar_nif(campo(0))
    entidade = _limpar_texto(campo(1))
    nif_beneficiario, estrangeiro = limpar_nif_beneficiario(campo(2))
    beneficiario = _limpar_texto(campo(3))
    montante = para_float(campo(4))
    data_decisao = para_data(campo(5))
    finalidade = _limpar_texto(campo(6))
    tipo_ato = _limpar_texto(campo(7)) or None
    numero_ato = _limpar_texto(campo(8)) or None
    data_ato = para_data(campo(9))

    # Sem contraparte nem entidade, a linha é lixo (rodapé, subtotal, nota).
    if not (beneficiario or nif_beneficiario or entidade):
        return None
    # Linhas de totais/notas: «TOTAL» sem NIF nem data de decisão.
    if not nif_beneficiario and not data_decisao and not montante:
        return None

    doc_id = f"{ano if ano is not None else 'sem-ano'}:{linha}"
    registo: Dict[str, Any] = {
        "doc_id": doc_id,
        "ano": ano,
        "linha": linha,
        "ficheiro": ficheiro,
        "folha": folha,
        "nif_entidade": nif_entidade or None,
        "entidade": entidade or None,
        "nif_beneficiario": nif_beneficiario or None,
        "beneficiario": beneficiario or None,
        "beneficiario_tipo": tipo_beneficiario(nif_beneficiario),
        "beneficiario_estrangeiro": estrangeiro,
        "montante": montante,
        "data_decisao": data_decisao,
        "ano_decisao": int(data_decisao[:4]) if data_decisao else None,
        "finalidade": finalidade or None,
        "tipo_ato": tipo_ato,
        "numero_ato": numero_ato,
        "data_ato": data_ato,
        "fundamento_legal": fundamento_legal(tipo_ato, numero_ato),
        "lido_em": lido_em,
    }
    return registo


# ---------------------------------------------------------------------------
# Ler a pasta (por ano) → JSONL
# ---------------------------------------------------------------------------


def ler_ficheiro(path: Path, ano: Optional[int], *, lido_em: Optional[str] = None) -> Dict[str, Any]:
    """Lê um ficheiro para JSONL e devolve os metadados do lote.

    A folha do `.ods` serve de último recurso para descobrir o ano (é
    `Subv_<ano>`), quando nem a pasta nem o nome do ficheiro o dizem.
    """
    lido_em = lido_em or _now()
    destino = normalized_dir() / f"subv-{_slug(path.stem)}.jsonl"
    temporario = destino.with_suffix(".jsonl.tmp")

    registos = 0
    ignoradas = 0
    montante_total = 0.0
    primeira_decisao: Optional[str] = None
    ultima_decisao: Optional[str] = None
    folha = ""
    ano_detetado = ano

    with temporario.open("w", encoding="utf-8") as saida:
        for bruto in _iter_registos(path):
            folha = bruto["folha"] or folha
            if ano_detetado is None:
                ano_detetado = _ano_no_texto(folha)
            registo = registo_de_linha(
                celulas=bruto["celulas"],
                indices=bruto["indices"],
                ano=ano_detetado,
                ficheiro=path.name,
                folha=bruto["folha"],
                linha=int(bruto["linha"]),
                lido_em=lido_em,
            )
            if registo is None:
                ignoradas += 1
                continue
            # O ano pode ter aparecido a meio (folha), corrige-se aqui.
            if registo.get("ano") is None and ano_detetado is not None:
                registo["ano"] = ano_detetado
                registo["doc_id"] = f"{ano_detetado}:{registo['linha']}"
            valor = registo.get("montante")
            if isinstance(valor, (int, float)):
                montante_total += float(valor)
            decisao = registo.get("data_decisao")
            if decisao:
                primeira_decisao = decisao if primeira_decisao is None or decisao < primeira_decisao else primeira_decisao
                ultima_decisao = decisao if ultima_decisao is None or decisao > ultima_decisao else ultima_decisao
            saida.write(json.dumps(registo, ensure_ascii=False) + "\n")
            registos += 1

    temporario.replace(destino)
    sha, bytes_ficheiro = _sha256(path)
    stat = path.stat()
    try:
        relativo = path.relative_to(data_dir()).as_posix()
    except ValueError:
        relativo = path.name
    return {
        "lote_id": f"{_slug(relativo)}",
        "ano": ano_detetado,
        "ficheiro": path.name,
        "rel_path": relativo,
        "folha": folha,
        "bytes": bytes_ficheiro,
        "sha256": sha,
        "modificado_em": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(timespec="seconds"),
        "registos": registos,
        "ignoradas": ignoradas,
        "montante_total": round(montante_total, 2),
        "primeira_decisao": primeira_decisao,
        "ultima_decisao": ultima_decisao,
        "jsonl": destino.name,
        "lido_em": lido_em,
    }


def ler_pasta(
    anos: Optional[Iterable[int]] = None,
    *,
    forcar: bool = False,
    progresso: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Lê a pasta (por ano) para JSONL, reaproveitando o que já está lido.

    «Já lido» = mesmo `sha256` no manifesto e JSONL presente em disco. Com
    `forcar=True` (ou ficheiro alterado) relê-se tudo.
    """
    filtro = {int(ano) for ano in anos} if anos else None
    encontrados = [item for item in ficheiros() if filtro is None or item.get("ano") in filtro]
    manifesto = read_manifest()
    lotes: Dict[str, Any] = manifesto.get("lotes") or {}
    resultado: Dict[str, Any] = {"lidos": [], "reutilizados": [], "erros": [], "registos": 0, "montante": 0.0}

    if progresso is not None:
        progresso.update({"phase": "a ler a pasta", "ficheiros_total": len(encontrados), "ficheiros_done": 0, "current": None})

    for item in encontrados:
        rel = str(item["rel_path"])
        if progresso is not None:
            progresso["current"] = rel
        anterior = lotes.get(rel) or {}
        if (
            not forcar
            and tem_jsonl(anterior)
            and anterior.get("sha256")
            and anterior.get("sha256") == _sha256(Path(str(item["path"])))[0]
        ):
            resultado["reutilizados"].append({"rel_path": rel, "ano": anterior.get("ano"), "registos": anterior.get("registos")})
            resultado["registos"] += int(anterior.get("registos") or 0)
            resultado["montante"] += float(anterior.get("montante_total") or 0.0)
            if progresso is not None:
                progresso["ficheiros_done"] = progresso.get("ficheiros_done", 0) + 1
            continue
        try:
            lote = ler_ficheiro(Path(str(item["path"])), item.get("ano"))
        except Exception as exc:  # noqa: BLE001 - um ficheiro mau não trava os restantes
            logger.exception("Subvenções: falha a ler %s", rel)
            resultado["erros"].append({"rel_path": rel, "error": f"{type(exc).__name__}: {exc}"})
            if progresso is not None:
                progresso["ficheiros_done"] = progresso.get("ficheiros_done", 0) + 1
            continue
        lote["rel_path"] = rel
        lotes[rel] = lote
        resultado["lidos"].append(lote)
        resultado["registos"] += int(lote.get("registos") or 0)
        resultado["montante"] += float(lote.get("montante_total") or 0.0)
        if progresso is not None:
            progresso["ficheiros_done"] = progresso.get("ficheiros_done", 0) + 1
            progresso["registos"] = resultado["registos"]
        # O manifesto é gravado ficheiro a ficheiro: se a leitura for
        # interrompida, o que já foi lido não se perde.
        manifesto["lotes"] = lotes
        _write_manifest(manifesto)

    manifesto["lotes"] = lotes
    _write_manifest(manifesto)
    resultado["montante"] = round(resultado["montante"], 2)
    resultado["ficheiros"] = len(encontrados)
    resultado["lidos_total"] = len(resultado["lidos"])
    resultado["reutilizados_total"] = len(resultado["reutilizados"])
    if progresso is not None:
        progresso["current"] = None
    return resultado


def preview(ano: int, *, limite: int = 25) -> Dict[str, Any]:
    """Amostra dos registos em disco de um ano (não precisa do Elasticsearch)."""
    manifest = read_manifest()
    lotes = [lote for lote in (manifest.get("lotes") or {}).values() if int(lote.get("ano") or 0) == int(ano)]
    itens: List[Dict[str, Any]] = []
    total = 0
    for lote in lotes:
        caminho = jsonl_path(lote)
        if caminho is None or not caminho.exists():
            continue
        with caminho.open("r", encoding="utf-8") as fh:
            for linha in fh:
                total += 1
                if len(itens) < limite:
                    try:
                        itens.append(json.loads(linha))
                    except Exception:  # noqa: BLE001
                        continue
    return {"ano": int(ano), "total": total, "items": itens, "lotes": len(lotes)}


# ---------------------------------------------------------------------------
# Indexação no Elasticsearch
# ---------------------------------------------------------------------------

_TAMANHO_LOTE_ES = 2000


def _iter_jsonl(caminho: Path) -> Iterator[Dict[str, Any]]:
    with caminho.open("r", encoding="utf-8") as fh:
        for linha in fh:
            linha = linha.strip()
            if not linha:
                continue
            try:
                yield json.loads(linha)
            except Exception:  # noqa: BLE001
                continue


def indexar(
    anos: Optional[Iterable[int]] = None,
    *,
    forcar: bool = False,
    progresso: Optional[Dict[str, Any]] = None,
    es: Any = None,
) -> Dict[str, Any]:
    """Indexa os JSONL já lidos em `finance_subvencoes`.

    Cada lote gera também um documento em `finance_subvencoes_lotes` com o
    `sha256` do ficheiro de origem, para se saber o que está indexado.
    """
    from api import elasticsearch_client as esc

    cliente = es or esc.get_es_client()
    if not cliente:
        return {"error": "Elasticsearch indisponível", "indexados": 0, "ficheiros": 0}
    esc.ensure_indices(cliente)

    from elasticsearch.helpers import bulk

    filtro = {int(ano) for ano in anos} if anos else None
    manifesto = read_manifest()
    lotes: Dict[str, Any] = manifesto.get("lotes") or {}
    selecionados = [
        lote
        for lote in lotes.values()
        if (filtro is None or int(lote.get("ano") or 0) in filtro)
        and (forcar or int(lote.get("indexados") or 0) != int(lote.get("registos") or 0))
    ]
    selecionados.sort(key=lambda lote: (-(lote.get("ano") or 0), str(lote.get("rel_path"))))

    resultado: Dict[str, Any] = {"indexados": 0, "ficheiros": 0, "items": [], "errors": []}
    if progresso is not None:
        progresso.update({"phase": "a indexar", "ficheiros_total": len(selecionados), "ficheiros_done": 0, "current": None})

    for lote in selecionados:
        caminho = jsonl_path(lote)
        rel = str(lote.get("rel_path"))
        if progresso is not None:
            progresso["current"] = rel
        if caminho is None or not caminho.exists():
            resultado["errors"].append({"rel_path": rel, "error": "JSONL não encontrado (leia a pasta de novo)"})
            continue
        acoes: List[Dict[str, Any]] = []
        enviados = 0
        try:
            for registo in _iter_jsonl(caminho):
                documento = dict(registo)
                documento["ingested_at"] = _now()
                acoes.append({"_index": esc.SUBVENCOES_INDEX, "_id": str(documento.get("doc_id")), "_source": documento})
                if len(acoes) >= _TAMANHO_LOTE_ES:
                    bulk(cliente, acoes, refresh=False, raise_on_error=False)
                    enviados += len(acoes)
                    acoes = []
                    if progresso is not None:
                        progresso["registos"] = resultado["indexados"] + enviados
            if acoes:
                bulk(cliente, acoes, refresh=False, raise_on_error=False)
                enviados += len(acoes)
                acoes = []
        except Exception as exc:  # noqa: BLE001 - um lote mau não trava os restantes
            logger.exception("Subvenções: falha a indexar %s", rel)
            resultado["errors"].append({"rel_path": rel, "error": f"{type(exc).__name__}: {exc}"})
            continue

        lote_doc = {
            "lote_id": str(lote.get("lote_id") or _slug(rel)),
            "ano": lote.get("ano"),
            "ficheiro": lote.get("ficheiro"),
            "rel_path": rel,
            "folha": lote.get("folha"),
            "bytes": lote.get("bytes"),
            "sha256": lote.get("sha256"),
            "modificado_em": lote.get("modificado_em"),
            "linhas": int(lote.get("registos") or 0) + int(lote.get("ignoradas") or 0),
            "registos": int(lote.get("registos") or 0),
            "ignoradas": int(lote.get("ignoradas") or 0),
            "montante_total": lote.get("montante_total"),
            "primeira_decisao": lote.get("primeira_decisao"),
            "ultima_decisao": lote.get("ultima_decisao"),
            "jsonl_path": caminho.name if caminho else None,
            "lido_em": lote.get("lido_em"),
            "ingested_at": _now(),
        }
        try:
            cliente.index(
                index=esc.SUBVENCOES_LOTES_INDEX,
                id=lote_doc["lote_id"],
                document=lote_doc,
                refresh=False,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Subvenções: lote %s não registado (%s)", rel, exc)

        lote["indexados"] = enviados
        lote["indexado_em"] = _now()
        resultado["indexados"] += enviados
        resultado["ficheiros"] += 1
        resultado["items"].append({**lote_doc, "indexados": enviados})
        if progresso is not None:
            progresso["ficheiros_done"] = progresso.get("ficheiros_done", 0) + 1
            progresso["registos"] = resultado["indexados"]
        manifesto["lotes"] = lotes
        _write_manifest(manifesto)

    try:
        cliente.indices.refresh(index=esc.SUBVENCOES_INDEX)
    except Exception as exc:  # noqa: BLE001
        logger.debug("refresh de %s ignorado: %s", esc.SUBVENCOES_INDEX, exc)

    manifesto["lotes"] = lotes
    _write_manifest(manifesto)
    if progresso is not None:
        progresso["current"] = None
    return resultado


# ---------------------------------------------------------------------------
# Pesquisa
# ---------------------------------------------------------------------------


def _cliente(es: Any = None) -> Any:
    from api import elasticsearch_client as esc

    return es or esc.get_es_client()


def _filtros_search(
    *,
    ano: Optional[int],
    ano_decisao: Optional[int],
    nif_entidade: Optional[str],
    nif_beneficiario: Optional[str],
    entidade: Optional[str],
    beneficiario: Optional[str],
    tipo_ato: Optional[str],
    beneficiario_tipo: Optional[str],
    fundamento_legal: Optional[str],
    data_from: Optional[str],
    data_to: Optional[str],
    montante_min: Optional[float],
    montante_max: Optional[float],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    filtros: List[Dict[str, Any]] = []
    must: List[Dict[str, Any]] = []

    if ano:
        filtros.append({"term": {"ano": int(ano)}})
    if ano_decisao:
        filtros.append({"term": {"ano_decisao": int(ano_decisao)}})
    nif_eo = limpar_nif(nif_entidade)
    if nif_eo:
        filtros.append({"term": {"nif_entidade": nif_eo}})
    nif_b = limpar_nif(nif_beneficiario)
    if nif_b:
        filtros.append({"term": {"nif_beneficiario": nif_b}})
    if entidade:
        texto = _limpar_texto(entidade)
        if limpar_nif(texto):
            filtros.append({"term": {"nif_entidade": limpar_nif(texto)}})
        else:
            must.append({"match": {"entidade": {"query": texto, "operator": "and"}}})
    if beneficiario:
        texto = _limpar_texto(beneficiario)
        if limpar_nif(texto):
            filtros.append({"term": {"nif_beneficiario": limpar_nif(texto)}})
        else:
            must.append({"match": {"beneficiario": {"query": texto, "operator": "and"}}})
    if tipo_ato:
        filtros.append({"term": {"tipo_ato": tipo_ato}})
    if beneficiario_tipo:
        filtros.append({"term": {"beneficiario_tipo": beneficiario_tipo}})
    if fundamento_legal:
        filtros.append({"term": {"fundamento_legal": fundamento_legal}})
    if data_from or data_to:
        intervalo: Dict[str, Any] = {}
        if data_from:
            intervalo["gte"] = data_from
        if data_to:
            intervalo["lte"] = data_to
        filtros.append({"range": {"data_decisao": intervalo}})
    if montante_min is not None or montante_max is not None:
        intervalo_valor: Dict[str, Any] = {}
        if montante_min is not None:
            intervalo_valor["gte"] = float(montante_min)
        if montante_max is not None:
            intervalo_valor["lte"] = float(montante_max)
        filtros.append({"range": {"montante": intervalo_valor}})
    return filtros, must


def search(
    q: Optional[str] = None,
    *,
    ano: Optional[int] = None,
    ano_decisao: Optional[int] = None,
    nif_entidade: Optional[str] = None,
    nif_beneficiario: Optional[str] = None,
    entidade: Optional[str] = None,
    beneficiario: Optional[str] = None,
    tipo_ato: Optional[str] = None,
    beneficiario_tipo: Optional[str] = None,
    fundamento_legal: Optional[str] = None,
    data_from: Optional[str] = None,
    data_to: Optional[str] = None,
    montante_min: Optional[float] = None,
    montante_max: Optional[float] = None,
    sort: str = "montante",
    order: str = "desc",
    page: int = 1,
    size: int = 25,
    es: Any = None,
) -> Dict[str, Any]:
    """Pesquisa as subvenções, com facetas e indicadores para o painel."""
    from api import elasticsearch_client as esc

    cliente = _cliente(es)
    if not cliente:
        return {
            "error": "Elasticsearch indisponível",
            "total": 0,
            "items": [],
            "facets": {},
            "kpis": {},
        }
    esc.ensure_indices(cliente)

    filtros, must = _filtros_search(
        ano=ano,
        ano_decisao=ano_decisao,
        nif_entidade=nif_entidade,
        nif_beneficiario=nif_beneficiario,
        entidade=entidade,
        beneficiario=beneficiario,
        tipo_ato=tipo_ato,
        beneficiario_tipo=beneficiario_tipo,
        fundamento_legal=fundamento_legal,
        data_from=data_from,
        data_to=data_to,
        montante_min=montante_min,
        montante_max=montante_max,
    )

    termo = _limpar_texto(q)
    if termo:
        if limpar_nif(termo):
            filtros.append(
                {"bool": {"should": [
                    {"term": {"nif_beneficiario": limpar_nif(termo)}},
                    {"term": {"nif_entidade": limpar_nif(termo)}},
                ], "minimum_should_match": 1}}
            )
        else:
            must.append(
                {
                    "multi_match": {
                        "query": termo,
                        "fields": ["beneficiario^3", "entidade^2", "finalidade", "fundamento_legal"],
                        "type": "best_fields",
                        "operator": "and",
                    }
                }
            )

    query: Dict[str, Any] = {"bool": {"must": must or [{"match_all": {}}], "filter": filtros}}
    ordenar = {
        "relevancia": [{"_score": "desc"}, {"montante": "desc"}],
        "montante": [{"montante": order}, {"data_decisao": "desc"}],
        "data": [{"data_decisao": order}, {"montante": "desc"}],
        "beneficiario": [{"beneficiario.keyword": order}],
        "entidade": [{"entidade.keyword": order}, {"montante": "desc"}],
        "ano": [{"ano": order}, {"montante": "desc"}],
    }.get(sort) or [{"montante": "desc"}]

    corpo: Dict[str, Any] = {
        "query": query,
        "from": max(0, (page - 1) * size),
        "size": size,
        "sort": ordenar,
        "track_total_hits": True,
        "aggs": {
            "por_ano": {"terms": {"field": "ano", "size": 30, "order": {"_key": "desc"}}, "aggs": {"montante": {"sum": {"field": "montante"}}}},
            "por_tipo_ato": {"terms": {"field": "tipo_ato", "size": 20}, "aggs": {"montante": {"sum": {"field": "montante"}}}},
            "por_tipo_beneficiario": {"terms": {"field": "beneficiario_tipo", "size": 10}},
            "por_fundamento": {"terms": {"field": "fundamento_legal", "size": 15}},
            "top_entidades": {"terms": {"field": "nif_entidade", "size": 15}, "aggs": {"nome": {"terms": {"field": "entidade.keyword", "size": 1}}, "montante": {"sum": {"field": "montante"}}}},
            "top_beneficiarios": {"terms": {"field": "nif_beneficiario", "size": 15}, "aggs": {"nome": {"terms": {"field": "beneficiario.keyword", "size": 1}}, "montante": {"sum": {"field": "montante"}}}},
            "por_mes": {"date_histogram": {"field": "data_decisao", "calendar_interval": "month", "min_doc_count": 0}, "aggs": {"montante": {"sum": {"field": "montante"}}}},
            "montante_total": {"sum": {"field": "montante"}},
            "beneficiarios_distintos": {"cardinality": {"field": "nif_beneficiario"}},
            "entidades_distintas": {"cardinality": {"field": "nif_entidade"}},
            "com_montante": {"value_count": {"field": "montante"}},
        },
    }

    try:
        resposta = cliente.search(index=esc.SUBVENCOES_INDEX, body=corpo)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Pesquisa de subvenções falhou")
        return {"error": str(exc), "total": 0, "items": [], "facets": {}, "kpis": {}}

    agregacoes = resposta.get("aggregations") or {}

    def _buckets(nome: str) -> List[Dict[str, Any]]:
        return list(((agregacoes.get(nome) or {}).get("buckets") or []))

    def _com_montante(nome: str) -> List[Dict[str, Any]]:
        return [
            {
                "key": bucket.get("key"),
                "count": bucket.get("doc_count"),
                "montante": round(float((bucket.get("montante") or {}).get("value") or 0.0), 2),
            }
            for bucket in _buckets(nome)
        ]

    def _com_nome(nome: str) -> List[Dict[str, Any]]:
        itens = []
        for bucket in _buckets(nome):
            nomes = ((bucket.get("nome") or {}).get("buckets") or [])
            itens.append(
                {
                    "key": bucket.get("key"),
                    "nome": (nomes[0].get("key") if nomes else None),
                    "count": bucket.get("doc_count"),
                    "montante": round(float((bucket.get("montante") or {}).get("value") or 0.0), 2),
                }
            )
        return itens

    itens = [{**(hit.get("_source") or {}), "score": hit.get("_score")} for hit in resposta.get("hits", {}).get("hits", [])]
    total = (resposta.get("hits", {}).get("total") or {}).get("value", 0)

    return {
        "total": total,
        "page": page,
        "size": size,
        "pages": (total + size - 1) // size if size else 0,
        "items": itens,
        "facets": {
            "ano": _com_montante("por_ano"),
            "tipo_ato": _com_montante("por_tipo_ato"),
            "beneficiario_tipo": [
                {"key": bucket.get("key"), "count": bucket.get("doc_count"), "label": TIPOS_BENEFICIARIO.get(str(bucket.get("key")), bucket.get("key"))}
                for bucket in _buckets("por_tipo_beneficiario")
            ],
            "fundamento_legal": [{"key": bucket.get("key"), "count": bucket.get("doc_count")} for bucket in _buckets("por_fundamento")],
            "top_entidades": _com_nome("top_entidades"),
            "top_beneficiarios": _com_nome("top_beneficiarios"),
        },
        "kpis": {
            "registos": total,
            "montante": round(float((agregacoes.get("montante_total") or {}).get("value") or 0.0), 2),
            "beneficiarios_distintos": (agregacoes.get("beneficiarios_distintos") or {}).get("value", 0),
            "entidades_distintas": (agregacoes.get("entidades_distintas") or {}).get("value", 0),
            "com_montante": (agregacoes.get("com_montante") or {}).get("value", 0),
            "por_mes": [
                {
                    "key": bucket.get("key_as_string"),
                    "count": bucket.get("doc_count"),
                    "montante": round(float((bucket.get("montante") or {}).get("value") or 0.0), 2),
                }
                for bucket in _buckets("por_mes")
            ],
        },
    }


def resumo(*, anos: Optional[Iterable[int]] = None, es: Any = None) -> Dict[str, Any]:
    """Painel: totais por ano, top entidades/beneficiários e série mensal."""
    from api import elasticsearch_client as esc

    cliente = _cliente(es)
    if not cliente:
        return {"error": "Elasticsearch indisponível", "por_ano": [], "top_entidades": [], "top_beneficiarios": [], "kpis": {}}
    esc.ensure_indices(cliente)

    filtro = [{"terms": {"ano": [int(ano) for ano in anos]}}] if anos else []
    corpo = {
        "size": 0,
        "query": {"bool": {"filter": filtro}},
        "aggs": {
            "por_ano": {
                "terms": {"field": "ano", "size": 40, "order": {"_key": "desc"}},
                "aggs": {
                    "montante": {"sum": {"field": "montante"}},
                    "beneficiarios": {"cardinality": {"field": "nif_beneficiario"}},
                    "entidades": {"cardinality": {"field": "nif_entidade"}},
                    "tipo_ato": {"terms": {"field": "tipo_ato", "size": 8}},
                },
            },
            "top_entidades": {"terms": {"field": "nif_entidade", "size": 20}, "aggs": {"nome": {"terms": {"field": "entidade.keyword", "size": 1}}, "montante": {"sum": {"field": "montante"}}}},
            "top_beneficiarios": {"terms": {"field": "nif_beneficiario", "size": 20}, "aggs": {"nome": {"terms": {"field": "beneficiario.keyword", "size": 1}}, "montante": {"sum": {"field": "montante"}}}},
            "por_mes": {"date_histogram": {"field": "data_decisao", "calendar_interval": "month", "min_doc_count": 0}, "aggs": {"montante": {"sum": {"field": "montante"}}}},
            "por_tipo_beneficiario": {"terms": {"field": "beneficiario_tipo", "size": 10}},
            "montante_total": {"sum": {"field": "montante"}},
            "registos": {"value_count": {"field": "doc_id"}},
            "beneficiarios": {"cardinality": {"field": "nif_beneficiario"}},
            "entidades": {"cardinality": {"field": "nif_entidade"}},
        },
    }
    try:
        resposta = cliente.search(index=esc.SUBVENCOES_INDEX, body=corpo)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Resumo de subvenções falhou")
        return {"error": str(exc), "por_ano": [], "top_entidades": [], "top_beneficiarios": [], "kpis": {}}

    agregacoes = resposta.get("aggregations") or {}

    def _buckets(nome: str) -> List[Dict[str, Any]]:
        return list(((agregacoes.get(nome) or {}).get("buckets") or []))

    def _top(nome: str) -> List[Dict[str, Any]]:
        itens = []
        for bucket in _buckets(nome):
            nomes = ((bucket.get("nome") or {}).get("buckets") or [])
            itens.append(
                {
                    "key": bucket.get("key"),
                    "nome": (nomes[0].get("key") if nomes else None),
                    "count": bucket.get("doc_count"),
                    "montante": round(float((bucket.get("montante") or {}).get("value") or 0.0), 2),
                }
            )
        return itens

    return {
        "por_ano": [
            {
                "ano": bucket.get("key"),
                "registos": bucket.get("doc_count"),
                "montante": round(float((bucket.get("montante") or {}).get("value") or 0.0), 2),
                "beneficiarios": (bucket.get("beneficiarios") or {}).get("value", 0),
                "entidades": (bucket.get("entidades") or {}).get("value", 0),
                "tipo_ato": [
                    {"key": item.get("key"), "count": item.get("doc_count")}
                    for item in ((bucket.get("tipo_ato") or {}).get("buckets") or [])
                ],
            }
            for bucket in _buckets("por_ano")
        ],
        "top_entidades": _top("top_entidades"),
        "top_beneficiarios": _top("top_beneficiarios"),
        "por_tipo_beneficiario": [
            {
                "key": bucket.get("key"),
                "count": bucket.get("doc_count"),
                "label": TIPOS_BENEFICIARIO.get(str(bucket.get("key")), bucket.get("key")),
            }
            for bucket in _buckets("por_tipo_beneficiario")
        ],
        "por_mes": [
            {"key": bucket.get("key_as_string"), "count": bucket.get("doc_count"), "montante": round(float((bucket.get("montante") or {}).get("value") or 0.0), 2)}
            for bucket in _buckets("por_mes")
        ],
        "kpis": {
            "registos": (agregacoes.get("registos") or {}).get("value", 0),
            "montante": round(float((agregacoes.get("montante_total") or {}).get("value") or 0.0), 2),
            "beneficiarios": (agregacoes.get("beneficiarios") or {}).get("value", 0),
            "entidades": (agregacoes.get("entidades") or {}).get("value", 0),
        },
    }


def por_beneficiario(nif: str, *, size: int = 200, es: Any = None) -> Dict[str, Any]:
    """Subvenções recebidas por um NIF, com totais por ano e por entidade."""
    limpo = limpar_nif(nif)
    if not limpo:
        return {"nif": "", "total": 0, "items": [], "por_ano": [], "entidades": []}
    resposta = search(nif_beneficiario=limpo, sort="data", order="desc", size=size, es=es)
    if resposta.get("error"):
        return {"nif": limpo, "total": 0, "items": [], "por_ano": [], "entidades": [], "error": resposta["error"]}
    itens = resposta.get("items") or []
    por_ano: Dict[int, Dict[str, Any]] = {}
    entidades: Dict[str, Dict[str, Any]] = {}
    for item in itens:
        ano = item.get("ano")
        if ano is not None:
            entrada = por_ano.setdefault(int(ano), {"ano": int(ano), "registos": 0, "montante": 0.0})
            entrada["registos"] += 1
            entrada["montante"] += float(item.get("montante") or 0.0)
        chave = str(item.get("nif_entidade") or item.get("entidade") or "?")
        entrada = entidades.setdefault(chave, {"nif": item.get("nif_entidade"), "nome": item.get("entidade"), "registos": 0, "montante": 0.0})
        entrada["registos"] += 1
        entrada["montante"] += float(item.get("montante") or 0.0)
    return {
        "nif": limpo,
        "nome": next((item.get("beneficiario") for item in itens if item.get("beneficiario")), None),
        "tipo": next((item.get("beneficiario_tipo") for item in itens if item.get("beneficiario_tipo")), None),
        "total": resposta.get("total", 0),
        "montante": round(sum(float(item.get("montante") or 0.0) for item in itens), 2),
        "montante_indexado": resposta.get("kpis", {}).get("montante"),
        "por_ano": [
            {**por_ano[ano], "montante": round(por_ano[ano]["montante"], 2)} for ano in sorted(por_ano, reverse=True)
        ],
        "entidades": sorted(
            ({**valor, "montante": round(valor["montante"], 2)} for valor in entidades.values()),
            key=lambda valor: valor["montante"],
            reverse=True,
        ),
        "items": itens,
        "source": "index",
    }


def por_entidade(nif: str, *, size: int = 200, es: Any = None) -> Dict[str, Any]:
    """Subvenções atribuídas por uma entidade obrigada (NIF)."""
    limpo = limpar_nif(nif)
    if not limpo:
        return {"nif": "", "total": 0, "items": [], "por_ano": [], "beneficiarios": []}
    resposta = search(nif_entidade=limpo, sort="montante", order="desc", size=size, es=es)
    if resposta.get("error"):
        return {"nif": limpo, "total": 0, "items": [], "por_ano": [], "beneficiarios": [], "error": resposta["error"]}
    itens = resposta.get("items") or []
    por_ano: Dict[int, Dict[str, Any]] = {}
    beneficiarios: Dict[str, Dict[str, Any]] = {}
    for item in itens:
        ano = item.get("ano")
        if ano is not None:
            entrada = por_ano.setdefault(int(ano), {"ano": int(ano), "registos": 0, "montante": 0.0})
            entrada["registos"] += 1
            entrada["montante"] += float(item.get("montante") or 0.0)
        chave = str(item.get("nif_beneficiario") or item.get("beneficiario") or "?")
        entrada = beneficiarios.setdefault(
            chave,
            {"nif": item.get("nif_beneficiario"), "nome": item.get("beneficiario"), "registos": 0, "montante": 0.0},
        )
        entrada["registos"] += 1
        entrada["montante"] += float(item.get("montante") or 0.0)
    return {
        "nif": limpo,
        "nome": next((item.get("entidade") for item in itens if item.get("entidade")), None),
        "total": resposta.get("total", 0),
        "montante": round(sum(float(item.get("montante") or 0.0) for item in itens), 2),
        "por_ano": [{**por_ano[ano], "montante": round(por_ano[ano]["montante"], 2)} for ano in sorted(por_ano, reverse=True)],
        "beneficiarios": sorted(
            ({**valor, "montante": round(valor["montante"], 2)} for valor in beneficiarios.values()),
            key=lambda valor: valor["montante"],
            reverse=True,
        ),
        "items": itens,
        "source": "index",
    }


def _iterar_tudo(
    *,
    filtros: List[Dict[str, Any]],
    must: List[Dict[str, Any]],
    maximo: int,
    es: Any,
) -> Iterator[Dict[str, Any]]:
    """Percorre todos os resultados com `search_after` (para exportações)."""
    from api import elasticsearch_client as esc

    cliente = es
    query: Dict[str, Any] = {"bool": {"must": must or [{"match_all": {}}], "filter": filtros}}
    tamanho = min(2000, max(1, maximo))
    enviados = 0
    depois: Optional[List[Any]] = None
    while enviados < maximo:
        corpo: Dict[str, Any] = {
            "query": query,
            "size": tamanho,
            "sort": [{"montante": "desc"}, {"doc_id": "asc"}],
            "_source": False,
        }
        if depois:
            corpo["search_after"] = depois
        resposta = cliente.search(index=esc.SUBVENCOES_INDEX, body=corpo)
        hits = resposta.get("hits", {}).get("hits", [])
        if not hits:
            break
        ids = [str(hit.get("_id")) for hit in hits]
        detalhes = cliente.mget(index=esc.SUBVENCOES_INDEX, body={"ids": ids})
        for doc in detalhes.get("docs") or []:
            if doc.get("found"):
                yield doc.get("_source") or {}
                enviados += 1
        depois = hits[-1].get("sort")
        if len(hits) < tamanho:
            break


CSV_CABECALHO = [
    "ano",
    "linha",
    "nif_entidade",
    "entidade",
    "nif_beneficiario",
    "beneficiario",
    "beneficiario_tipo",
    "beneficiario_estrangeiro",
    "montante",
    "data_decisao",
    "finalidade",
    "tipo_ato",
    "numero_ato",
    "data_ato",
    "fundamento_legal",
    "ficheiro",
]


def csv_bytes(
    *,
    maximo: int = 50000,
    es: Any = None,
    **filtros: Any,
) -> bytes:
    """Exportação CSV da pesquisa (delimitador `;`, para o Excel em pt-PT)."""
    cliente = _cliente(es)
    if not cliente:
        raise RuntimeError("Elasticsearch indisponível")
    filtros_es, must = _filtros_search(
        ano=filtros.get("ano"),
        ano_decisao=filtros.get("ano_decisao"),
        nif_entidade=filtros.get("nif_entidade"),
        nif_beneficiario=filtros.get("nif_beneficiario"),
        entidade=filtros.get("entidade"),
        beneficiario=filtros.get("beneficiario"),
        tipo_ato=filtros.get("tipo_ato"),
        beneficiario_tipo=filtros.get("beneficiario_tipo"),
        fundamento_legal=filtros.get("fundamento_legal"),
        data_from=filtros.get("data_from"),
        data_to=filtros.get("data_to"),
        montante_min=filtros.get("montante_min"),
        montante_max=filtros.get("montante_max"),
    )
    termo = _limpar_texto(filtros.get("q"))
    if termo:
        must.append(
            {
                "multi_match": {
                    "query": termo,
                    "fields": ["beneficiario^3", "entidade^2", "finalidade"],
                    "operator": "and",
                }
            }
        )
    buffer = io.StringIO()
    escritor = csv.writer(buffer, delimiter=";", quoting=csv.QUOTE_MINIMAL)
    escritor.writerow(CSV_CABECALHO)
    for registo in _iterar_tudo(filtros=filtros_es, must=must, maximo=maximo, es=cliente):
        escritor.writerow(["" if registo.get(coluna) is None else registo.get(coluna) for coluna in CSV_CABECALHO])
    return buffer.getvalue().encode("utf-8-sig")


# ---------------------------------------------------------------------------
# Trabalhos (leitura e indexação em segundo plano)
# ---------------------------------------------------------------------------


def _prune_jobs() -> None:
    if len(_JOBS) <= _JOBS_KEEP:
        return
    antigos = sorted(_JOBS.values(), key=lambda job: str(job.get("started_at") or ""))
    for job in antigos[: len(_JOBS) - _JOBS_KEEP]:
        if job.get("status") == _RUNNING:
            continue
        _JOBS.pop(str(job["job_id"]), None)


def start_job(tipo: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Arranca «ler» (pasta → JSONL) ou «indexar» (JSONL → Elasticsearch)."""
    if tipo not in ("ler", "indexar"):
        raise ValueError(f"Tipo de trabalho desconhecido: {tipo}")
    with _JOBS_LOCK:
        for job in _JOBS.values():
            if job.get("status") == _RUNNING and job.get("tipo") == tipo:
                return {
                    "job_id": job["job_id"],
                    "tipo": tipo,
                    "status": _RUNNING,
                    "already_running": True,
                    "message": "Já existe um trabalho deste tipo a correr.",
                }
        job: Dict[str, Any] = {
            "job_id": uuid.uuid4().hex[:12],
            "tipo": tipo,
            "status": _RUNNING,
            "started_at": _now(),
            "finished_at": None,
            "payload": dict(payload or {}),
            "progress": {
                "phase": "a começar",
                "ficheiros_total": 0,
                "ficheiros_done": 0,
                "registos": 0,
                "current": None,
            },
            "result": None,
            "error": None,
        }
        _JOBS[job["job_id"]] = job
        _prune_jobs()
    threading.Thread(target=_run_job, args=(job,), name=f"subvencoes-{tipo}", daemon=True).start()
    return dict(job)


def _run_job(job: Dict[str, Any]) -> None:
    try:
        payload = job["payload"]
        anos = payload.get("anos") or None
        progresso = job["progress"]
        if job["tipo"] == "ler":
            resultado = ler_pasta(anos, forcar=bool(payload.get("forcar")), progresso=progresso)
        else:
            resultado = indexar(anos, forcar=bool(payload.get("forcar")), progresso=progresso)
        job["result"] = resultado
        erros = resultado.get("erros") or resultado.get("errors") or []
        job["status"] = "error" if resultado.get("error") else ("done" if not erros else "done")
        if erros:
            job["error"] = f"{len(erros)} ficheiro(s) com erro"
        job["finished_at"] = _now()
        progresso["phase"] = "concluído"
    except Exception as exc:  # noqa: BLE001 - o trabalho nunca pode morrer em silêncio
        logger.exception("Trabalho de subvenções falhou")
        job["status"] = "error"
        job["finished_at"] = _now()
        job["error"] = f"{type(exc).__name__}: {exc}"
        job["progress"]["phase"] = "erro"
    finally:
        job["progress"]["current"] = None


def list_jobs() -> Dict[str, Any]:
    """Trabalhos de subvenções (mais recentes primeiro)."""
    with _JOBS_LOCK:
        jobs = sorted(_JOBS.values(), key=lambda job: str(job.get("started_at") or ""), reverse=True)
        return {"total": len(jobs), "items": [dict(job) for job in jobs]}


def job_status(job_id: str) -> Optional[Dict[str, Any]]:
    with _JOBS_LOCK:
        job = _JOBS.get(str(job_id))
        return dict(job) if job else None


# ---------------------------------------------------------------------------
# Metadados
# ---------------------------------------------------------------------------


def meta() -> Dict[str, Any]:
    """O que está na pasta, o que está lido e o que está indexado."""
    from api import elasticsearch_client as esc

    encontrados = ficheiros()
    manifest = read_manifest()
    lotes = manifest.get("lotes") or {}
    por_ano: Dict[int, Dict[str, Any]] = {}
    for item in encontrados:
        ano = item.get("ano")
        chave = int(ano) if ano is not None else 0
        entrada = por_ano.setdefault(
            chave,
            {"ano": ano, "ficheiros": 0, "bytes": 0, "ficheiros_disco": [], "lidos": 0, "registos": 0, "montante": 0.0, "pendentes": 0},
        )
        entrada["ficheiros"] += 1
        entrada["bytes"] += int(item.get("bytes") or 0)
        entrada["ficheiros_disco"].append(
            {"rel_path": item["rel_path"], "bytes": item["bytes"], "ano_origem": item["ano_origem"], "modificado_em": item["modificado_em"]}
        )
        lote = lotes.get(str(item["rel_path"]))
        if lote and tem_jsonl(lote):
            entrada["lidos"] += 1
            entrada["registos"] += int(lote.get("registos") or 0)
            entrada["montante"] += float(lote.get("montante_total") or 0.0)
        else:
            entrada["pendentes"] += 1

    indice: Dict[str, Any] = {}
    try:
        cliente = esc.get_es_client()
        if cliente:
            if cliente.indices.exists(index=esc.SUBVENCOES_INDEX):
                contagem = cliente.count(index=esc.SUBVENCOES_INDEX)
                indice = {"index": esc.SUBVENCOES_INDEX, "registos": contagem.get("count", 0), "lotes_index": esc.SUBVENCOES_LOTES_INDEX}
    except Exception as exc:  # noqa: BLE001
        indice = {"error": str(exc)}

    return {
        "module": "subvencoes-publicas",
        "dir": str(data_dir()),
        "dir_env": DATA_DIR_ENV,
        "normalized_dir": str(normalized_dir()),
        "index": esc.SUBVENCOES_INDEX,
        "indice": indice,
        "ficheiros_disco": len(encontrados),
        "anos": [
            {**por_ano[chave], "montante": round(por_ano[chave]["montante"], 2)} for chave in sorted(por_ano, reverse=True)
        ],
        "lidos": len([lote for lote in lotes.values() if tem_jsonl(lote)]),
        "registos_lidos": sum(int(lote.get("registos") or 0) for lote in lotes.values()),
        "atualizado_em": manifest.get("atualizado_em"),
        "colunas": [{"campo": campo, "rotulo": rotulo} for campo, rotulo in COLUNAS],
        "tipos_beneficiario": TIPOS_BENEFICIARIO,
        "notes": (
            "A pasta `data/subvencoes` é lida **por ano**: o ano vem da subpasta "
            "(`2024/…`) ou do nome do ficheiro (`lista-subvpublicas2025_1.ods`). "
            "O ano guardado é o da listagem — o mesmo apoio aparece em listagens "
            "de anos diferentes (o ficheiro de 2025 repete decisões de 2022)."
        ),
    }
