"""Entidades do **Setor Institucional das Administrações Públicas** (SEC 2010).

O INE publica, todos os anos, a lista das entidades que integram o setor S.13
(`Entidades que integram o Setor Institucional das Administrações Públicas`).
Este serviço lê esse PDF, constrói um **índice** das entidades da Administração
Central e liga cada uma ao **NIF** com que contrata no portal BASE, para que a
plataforma possa mostrar os contratos e as adjudicatárias de cada uma.

Subsetores indexados (os restantes — municípios, freguesias e administração
regional — já têm módulos próprios na plataforma):

- ``S.13111`` — Estado (serviços integrados e Caixa Geral de Aposentações);
- ``S.13112`` — Serviços e Fundos Autónomos da Administração Central;
- ``S.13113`` — Instituições Sem Fim Lucrativo da Administração Central.

O índice vive em ``data/entidades-sector/servicos-fundos-autonomos.json`` e é
regenerável a partir do PDF + do índice de contratos (``reconstruir``). As
ligações nome→NIF podem ser corrigidas à mão em
``data/entidades-sector/ligacoes-manuais.json`` (``{«nome do PDF»: «NIF»}``),
que tem precedência sobre a ligação automática.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
PASTA = ROOT / "data" / "entidades-sector"
PDF_FONTE = PASTA / "Entidades que integram o Setor Institucional das Administrações Públicas - 2025.pdf"
INDICE = PASTA / "servicos-fundos-autonomos.json"
LIGACOES_MANUAIS = PASTA / "ligacoes-manuais.json"
CADASTRO_PORTAL_BASE = ROOT / "data" / "entidades-gov-portal-base" / "entidades.json"

FONTE = {
    "designacao": "Entidades que integram o Setor Institucional das Administrações Públicas",
    "edicao": 2025,
    "emissor": "INE — Instituto Nacional de Estatística (CTAP)",
    "publicacao": "Setembro de 2026",
    "metodologia": "SEC 2010 (Sistema Europeu de Contas Nacionais e Regionais), setor S.13",
    "contacto": "ctap@ine.pt",
    "ficheiro": PDF_FONTE.name,
}

#: Subsetores indexados: id → (título, linhas de cabeçalho a ignorar).
SECOES: Dict[str, Dict[str, Any]] = {
    "S.13111": {
        "nome": "Estado",
        "cabecalhos": {"Administração Central", "Estado", "Serviços Integrados do Estado"},
    },
    "S.13112": {
        "nome": "Serviços e Fundos Autónomos da Administração Central",
        "cabecalhos": {"Administração Central", "Serviços e Fundos Autónomos da Administração Central"},
    },
    "S.13113": {
        "nome": "Instituições Sem Fim Lucrativo da Administração Central",
        "cabecalhos": {
            "Administração Central",
            "Instituições Sem Fim Lucrativo da Administração Central",
        },
    },
}

SUBSETOR_OMISSAO = "S.13112"

#: Código do subsetor normalizado («S13112») → chave de `SECOES` («S.13112»).
SECOES_POR_CODIGO = {codigo.replace(".", ""): codigo for codigo in SECOES}

#: Nº de páginas do PDF ("88 de 88").
_RE_RODAPE = re.compile(r"^\d+\s+de\s+\d+$")
_RE_CABECALHO = re.compile(r"^S\.\d+\s*[–—-]")
_RE_SIGLA = re.compile(r"^(.{2,12}?)\s+[–—-]\s+")

#: Sufixos societários que não ajudam a distinguir entidades.
_RE_SUFIXOS = re.compile(r"\b(I\.?P\.?|S\.?A\.?|SGPS|E\.?P\.?E\.?|LDA\.?|LDA|UNIPESSOAL|EPE|SA|IP|ACE|A\.C\.E\.?)\b")
#: Palavras que aparecem em quase todos os nomes.
_RUIDO = {
    "DE", "DA", "DO", "DAS", "DOS", "E", "PARA", "A", "O", "EM", "NO", "NA", "AO", "AOS",
    "INSTITUTO", "SERVICO", "SERVICOS", "AGENCIA", "FUNDO", "SOCIEDADE", "EMPRESA",
    "NACIONAL", "GERAL", "PUBLICA", "PUBLICO", "PORTUGAL", "PORTUGUESA", "PORTUGUES",
}


# --------------------------------------------------------------- normalização


def normalizar(valor: Any) -> str:
    """Texto em maiúsculas, sem acentos e sem pontuação (para comparação)."""
    texto = unicodedata.normalize("NFKD", str(valor or ""))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^A-Za-z0-9]+", " ", texto.upper())).strip()


def chave_nome(valor: Any) -> str:
    """Chave de comparação: nome normalizado, sem sufixos societários nem parênteses."""
    limpo = re.sub(r"\([^)]*\)", " ", str(valor or ""))
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]+", " ", _RE_SUFIXOS.sub(" ", normalizar(limpo)))).strip()


def tokens_nome(valor: Any) -> set:
    """Palavras significativas de um nome (fora as de uso comum)."""
    return {t for t in chave_nome(valor).split() if len(t) > 1 and t not in _RUIDO}


def sigla_nome(valor: Any) -> str:
    """Sigla que abre o nome («AdC - Autoridade da Concorrência» → ``ADC``)."""
    encontrado = _RE_SIGLA.match(str(valor or "").strip())
    if not encontrado:
        return ""
    return re.sub(r"[^A-Z0-9]", "", normalizar(encontrado.group(1)))


def nome_sem_sigla(valor: Any) -> str:
    """Nome sem a sigla que o abre («IEFP - Instituto do Emprego…» → «Instituto do Emprego…»)."""
    return _RE_SIGLA.sub("", str(valor or "").strip()).strip()


def tokens_equivalentes(primeiro: str, segundo: str) -> bool:
    """Duas palavras são a mesma quando uma é prefixo da outra (plural, truncagem)."""
    if primeiro == segundo:
        return True
    if len(primeiro) < 5 or len(segundo) < 5:
        return False
    curta, longa = sorted((primeiro, segundo), key=len)
    return longa.startswith(curta)


def pontuar_tokens(alvo: set, palavras: set) -> Tuple[int, float, float]:
    """Compara dois conjuntos de palavras, tolerando plural/truncagem.

    Devolve ``(palavras em comum, Jaccard, cobertura)``. A cobertura usa o menor
    dos conjuntos: é o que permite reconhecer um nome curto do portal BASE
    («Autoridade da Concorrência») como o mesmo que o nome completo do INE.
    """
    if not alvo or not palavras:
        return 0, 0.0, 0.0
    comuns = sum(1 for token in alvo if any(tokens_equivalentes(token, outro) for outro in palavras))
    jaccard = comuns / (len(alvo) + len(palavras) - comuns)
    cobertura = comuns / min(len(alvo), len(palavras))
    return comuns, jaccard, cobertura


def slug(valor: Any) -> str:
    """Identificador legível e estável a partir do nome."""
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", normalizar(valor).lower())).strip("-")


# ------------------------------------------------------------------- parser PDF


def _paginas_do_pdf(caminho: Optional[Path] = None) -> List[List[str]]:
    """Devolve as linhas com texto de cada página do PDF da fonte."""
    alvo = Path(caminho) if caminho else PDF_FONTE
    if not alvo.is_file():
        raise FileNotFoundError(f"PDF da fonte não encontrado: {alvo}")
    import pymupdf  # importação tardia: só é precisa na (re)construção do índice

    documento = pymupdf.open(alvo)
    paginas: List[List[str]] = []
    for pagina in documento:
        linhas = [linha.strip() for linha in pagina.get_text("text").splitlines()]
        paginas.append([linha for linha in linhas if linha and not _RE_RODAPE.match(linha)])
    return paginas


def ler_entidades_do_pdf(caminho: Optional[Path] = None) -> Dict[str, List[str]]:
    """Lê as entidades de cada subsetor indexado, pela ordem em que figuram no PDF.

    O PDF repete, no topo de cada página, o cabeçalho do subsetor
    («S.13112 – Administração Central» + «Serviços e Fundos Autónomos…»), pelo que
    o subsetor corrente é o do último cabeçalho visto.
    """
    resultado: Dict[str, List[str]] = {secao: [] for secao in SECOES}
    subsetor: Optional[str] = None
    for linhas in _paginas_do_pdf(caminho):
        if not linhas:
            continue
        cabecalho = linhas[0]
        if _RE_CABECALHO.match(cabecalho):
            codigo = normalizar(cabecalho.split()[0]).replace(" ", "")
            subsetor = SECOES_POR_CODIGO.get(codigo)
            corpo = linhas[1:] if subsetor else []
        elif subsetor:
            corpo = linhas
        else:
            corpo = []
        ignorar = SECOES[subsetor]["cabecalhos"] if subsetor else set()
        for linha in corpo:
            if linha in ignorar or _RE_CABECALHO.match(linha):
                continue
            resultado[subsetor].append(linha)  # type: ignore[index]
    return resultado


# ------------------------------------------------- ligação nome → NIF (contratos)


def _adjudicantes_do_indice(es=None, tamanho: int = 12000) -> List[Dict[str, Any]]:
    """NIFs que **adjudicam** contratos no índice de contratos, com totais.

    Uma só agregação devolve, para todos os adjudicantes, o nome usado nos
    contratos, o nº de contratos, o valor e o intervalo de anos — é com esta
    lista que se liga cada entidade do INE ao NIF com que contrata.
    """
    from api.elasticsearch_client import CONTRACTS_INDEX, get_es_client

    client = es or get_es_client(request_timeout=300)
    if not client:
        return []
    corpo = {
        "size": 0,
        "aggs": {
            "adjudicantes": {
                "nested": {"path": "adjudicantes.parsed"},
                "aggs": {
                    "nifs": {
                        "terms": {"field": "adjudicantes.parsed.nif", "size": tamanho},
                        "aggs": {
                            "nome": {"top_hits": {"size": 1, "_source": ["adjudicantes.parsed.nome"]}},
                            "valor": {"reverse_nested": {}, "aggs": {"v": {"sum": {"field": "precoContratual"}}}},
                            "ano_min": {"reverse_nested": {}, "aggs": {"v": {"min": {"field": "Ano"}}}},
                            "ano_max": {"reverse_nested": {}, "aggs": {"v": {"max": {"field": "Ano"}}}},
                        },
                    }
                },
            }
        },
    }
    resposta = client.search(index=CONTRACTS_INDEX, body=corpo)
    baldes = resposta["aggregations"]["adjudicantes"]["nifs"]["buckets"]

    candidatos: List[Dict[str, Any]] = []
    for balde in baldes:
        acertos = balde.get("nome", {}).get("hits", {}).get("hits", [])
        candidatos.append(
            {
                "nif": str(balde["key"]),
                "nome": (acertos[0]["_source"].get("nome") if acertos else "") or "",
                "contratos": int(balde.get("doc_count") or 0),
                "valor": round(float((balde.get("valor") or {}).get("v", {}).get("value") or 0), 2),
                "ano_min": (balde.get("ano_min") or {}).get("v", {}).get("value"),
                "ano_max": (balde.get("ano_max") or {}).get("v", {}).get("value"),
            }
        )
    return candidatos


def _indice_invertido(candidatos: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Indexa os candidatos por chave de nome, por chave sem sigla e por palavra.

    A chave «sem sigla» cobre o caso mais frequente: o INE escreve
    «IEFP - Instituto do Emprego e da Formação Profissional» e o portal BASE
    escreve só «Instituto do Emprego e Formação Profissional» (ou o contrário).
    """
    por_chave: Dict[str, List[Dict[str, Any]]] = {}
    por_chave_simples: Dict[str, List[Dict[str, Any]]] = {}
    por_token: Dict[str, set] = {}
    por_prefixo: Dict[str, set] = {}
    for candidato in candidatos:
        nome = candidato.get("nome") or ""
        chave = chave_nome(nome)
        if not chave:
            continue
        por_chave.setdefault(chave, []).append(candidato)
        simples = chave_nome(nome_sem_sigla(nome))
        if simples and simples != chave:
            por_chave_simples.setdefault(simples, []).append(candidato)
        for token in tokens_nome(nome):
            por_token.setdefault(token, set()).add(chave)
            por_prefixo.setdefault(token[:6], set()).add(chave)
    return {
        "por_chave": por_chave,
        "por_chave_simples": por_chave_simples,
        "por_token": por_token,
        "por_prefixo": por_prefixo,
    }


def ligar_nome(nome: str, indice: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], str, float]:
    """Liga o nome oficial do INE a um adjudicante real dos contratos.

    Devolve ``(candidato, tipo, confiança)``. Só se aceitam ligações de confiança
    alta — uma ligação errada atribuiria a uma entidade os contratos de outra:

    - ``exato`` — mesma chave de nome (sem sufixos societários nem parênteses);
    - ``nome`` — coincide com o nome do contrato sem a sigla que o abre;
    - ``prefixo`` — a chave mais curta é prefixo da outra e tem ≥ 18 caracteres
      (o portal BASE trunca nomes longos e muda de versão sem aviso);
    - ``sigla`` — a sigla que abre o nome é igual e as palavras coincidem em ≥ 60 %;
    - ``forte`` — palavras significativas coincidem em ≥ 80 % (Jaccard) ou o nome
      mais curto está contido no outro com ≥ 3 palavras em comum.
    """
    if not nome:
        return None, "nenhuma", 0.0

    por_chave = indice["por_chave"]
    por_chave_simples = indice["por_chave_simples"]
    por_token = indice["por_token"]
    por_prefixo = indice["por_prefixo"]

    chave = chave_nome(nome)
    if chave and chave in por_chave:
        return por_chave[chave][0], "exato", 1.0
    simples = chave_nome(nome_sem_sigla(nome))
    if simples and simples in por_chave:
        return por_chave[simples][0], "nome", 0.97
    if chave and chave in por_chave_simples:
        return por_chave_simples[chave][0], "nome", 0.97

    alvo = tokens_nome(nome)
    if not alvo:
        return None, "nenhuma", 0.0
    contagem: Dict[str, int] = {}
    for token in alvo:
        for candidata in por_token.get(token, ()):
            contagem[candidata] = contagem.get(candidata, 0) + 1
        for candidata in por_prefixo.get(token[:6], ()):
            contagem[candidata] = contagem.get(candidata, 0) + 1

    sigla = sigla_nome(nome)
    melhor: Optional[Dict[str, Any]] = None
    melhor_tipo = "nenhuma"
    melhor_score = 0.0
    for candidata in contagem:
        candidatos_chave = por_chave.get(candidata) or por_chave_simples.get(candidata)
        if not candidatos_chave:
            continue
        nome_candidato = candidatos_chave[0].get("nome") or ""
        palavras = tokens_nome(nome_candidato)
        comuns, jaccard, cobertura = pontuar_tokens(alvo, palavras)
        if comuns == 0:
            continue
        curta, longa = sorted((chave, candidata), key=len)
        prefixo = len(curta) >= 18 and longa.startswith(curta)
        mesma_sigla = bool(sigla) and len(sigla) >= 2 and sigla == sigla_nome(nome_candidato)

        if prefixo and cobertura >= 0.9:
            tipo, score = "prefixo", 0.95
        elif mesma_sigla and cobertura >= 0.6:
            tipo, score = "sigla", 0.9
        elif jaccard >= 0.8:
            tipo, score = "forte", 0.85
        elif cobertura >= 0.9 and comuns >= 3:
            tipo, score = "forte", 0.8
        else:
            continue
        if score > melhor_score:
            melhor, melhor_tipo, melhor_score = candidatos_chave[0], tipo, score

    if melhor is None:
        return None, "nenhuma", 0.0
    return melhor, melhor_tipo, melhor_score


def _ligacoes_manuais() -> Dict[str, str]:
    """Correções manuais da ligação nome→NIF (``{«nome do PDF»: «NIF»}``)."""
    if not LIGACOES_MANUAIS.is_file():
        return {}
    try:
        dados = json.loads(LIGACOES_MANUAIS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Ligações manuais ilegíveis (%s): %s", LIGACOES_MANUAIS, exc)
        return {}
    return {str(k): str(v) for k, v in (dados or {}).items() if v}


def _ids_estaveis(nome: str, subsetor: str) -> Tuple[str, str]:
    """Slug do nome (único dentro do subsetor) e identificador completo."""
    proprio = slug(nome) or hashlib.sha1(nome.encode("utf-8")).hexdigest()[:12]
    return proprio, f"{slug(subsetor)}-{proprio}"


# ---------------------------------------------------------------- construção


def construir(
    caminho_pdf: Optional[Path] = None,
    *,
    es=None,
    usar_contratos: bool = True,
) -> Dict[str, Any]:
    """Constrói o índice a partir do PDF (e, se possível, dos contratos indexados).

    Sem Elasticsearch o índice é construído à mesma — fica só sem as ligações a
    NIF e sem os totais de contrato por entidade.
    """
    nomes_por_secao = ler_entidades_do_pdf(caminho_pdf)
    candidatos = _adjudicantes_do_indice(es) if usar_contratos else []
    indice_invertido = _indice_invertido(candidatos)
    manuais = _ligacoes_manuais()
    candidatos_por_nif = {c["nif"]: c for c in candidatos}

    entidades: List[Dict[str, Any]] = []
    vistos: set = set()
    for subsetor, nomes in nomes_por_secao.items():
        for nome in nomes:
            proprio, identificador = _ids_estaveis(nome, subsetor)
            if identificador in vistos:
                logger.debug("Entidade repetida no subsetor %s: %s", subsetor, nome)
                continue
            vistos.add(identificador)

            nif_manual = ""
            for chave_manual, nif in manuais.items():
                if chave_nome(chave_manual) == chave_nome(nome):
                    nif_manual = nif
                    break

            if nif_manual:
                ligado = candidatos_por_nif.get(nif_manual) or {"nif": nif_manual, "nome": "", "contratos": 0, "valor": 0.0}
                tipo, confianca = "manual", 1.0
            else:
                ligado, tipo, confianca = ligar_nome(nome, indice_invertido)

            entidades.append(
                {
                    "id": identificador,
                    "nome": nome,
                    "slug": proprio,
                    "subsetor": subsetor,
                    "subsetor_nome": SECOES[subsetor]["nome"],
                    "nif": (ligado or {}).get("nif") or None,
                    "nome_contratos": (ligado or {}).get("nome") or None,
                    "ligacao": tipo,
                    "ligacao_confianca": confianca,
                    "contratos": int((ligado or {}).get("contratos") or 0),
                    "valor": float((ligado or {}).get("valor") or 0.0),
                    "ano_min": (ligado or {}).get("ano_min"),
                    "ano_max": (ligado or {}).get("ano_max"),
                }
            )

    entidades.sort(key=lambda item: (item["subsetor"], item["nome"].lower()))
    subsetores = [
        {
            "id": subsetor,
            "nome": SECOES[subsetor]["nome"],
            "total": sum(1 for item in entidades if item["subsetor"] == subsetor),
            "ligadas": sum(1 for item in entidades if item["subsetor"] == subsetor and item["nif"]),
        }
        for subsetor in SECOES
    ]
    return {
        "fonte": FONTE,
        "gerado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "subsetor_omissao": SUBSETOR_OMISSAO,
        "subsetores": subsetores,
        "total": len(entidades),
        "ligadas": sum(1 for item in entidades if item["nif"]),
        "candidatos_contratos": len(candidatos),
        "entidades": entidades,
    }


def gravar(indice: Dict[str, Any], destino: Optional[Path] = None) -> Path:
    """Grava o índice em disco (JSON legível, com fim de linha final)."""
    alvo = Path(destino) if destino else INDICE
    alvo.parent.mkdir(parents=True, exist_ok=True)
    alvo.write_text(json.dumps(indice, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return alvo


def reconstruir(*, es=None, usar_contratos: bool = True, destino: Optional[Path] = None) -> Dict[str, Any]:
    """(Re)constrói e grava o índice; limpa a cache em memória."""
    indice = construir(es=es, usar_contratos=usar_contratos)
    gravar(indice, destino)
    cache_limpar()
    return indice


# -------------------------------------------------------------------- leitura


_cache: Dict[str, Any] = {"assinatura": None, "indice": None}
_trava = threading.Lock()


def cache_limpar() -> None:
    """Esquece o índice carregado (após uma reconstrução ou mudança do ficheiro)."""
    with _trava:
        _cache["assinatura"] = None
        _cache["indice"] = None


def _assinatura(caminho: Path) -> Optional[Tuple[float, int]]:
    try:
        estado = caminho.stat()
    except OSError:
        return None
    return (estado.st_mtime, estado.st_size)


def carregar(caminho: Optional[Path] = None) -> Dict[str, Any]:
    """Índice das entidades, com recarga automática quando o ficheiro muda."""
    alvo = Path(caminho) if caminho else INDICE
    assinatura = _assinatura(alvo)
    with _trava:
        if assinatura and _cache["assinatura"] == assinatura and _cache["indice"] is not None:
            return _cache["indice"]
    dados = {"fonte": FONTE, "subsetores": [], "entidades": [], "total": 0, "ligadas": 0, "indice_em_falta": True}
    if alvo.is_file():
        try:
            dados = json.loads(alvo.read_text(encoding="utf-8"))
            dados["indice_em_falta"] = False
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Índice ilegível (%s): %s", alvo, exc)
            dados["erro"] = str(exc)
    with _trava:
        if assinatura:
            _cache["assinatura"] = assinatura
        _cache["indice"] = dados
    return dados


def entidades(subsetor: Optional[str] = None) -> List[Dict[str, Any]]:
    """Entidades do índice, opcionalmente restritas a um subsetor."""
    dados = carregar()
    itens = dados.get("entidades") or []
    if subsetor and subsetor != "all":
        itens = [item for item in itens if item.get("subsetor") == subsetor]
    return itens


def entidade(identificador: str) -> Optional[Dict[str, Any]]:
    """Uma entidade pelo `id` ou pelo slug do nome."""
    procurado = str(identificador or "").strip().lower()
    for item in carregar().get("entidades") or []:
        if item.get("id") == procurado or item.get("slug") == procurado:
            return item
    return None


def nifs(subsetor: Optional[str] = None) -> List[str]:
    """NIFs ligados às entidades do (sub)setor — o universo dos contratos."""
    return [item["nif"] for item in entidades(subsetor) if item.get("nif")]


def meta() -> Dict[str, Any]:
    """Estado do índice: fonte, subsetores, ligações e ficheiros."""
    dados = carregar()
    itens = dados.get("entidades") or []
    return {
        "fonte": dados.get("fonte") or FONTE,
        "ficheiro_pdf": str(PDF_FONTE),
        "ficheiro_indice": str(INDICE),
        "ligacoes_manuais": str(LIGACOES_MANUAIS),
        "gerado_em": dados.get("gerado_em"),
        "subsetor_omissao": dados.get("subsetor_omissao") or SUBSETOR_OMISSAO,
        "subsetores": dados.get("subsetores") or [],
        "total": dados.get("total") or len(itens),
        "ligadas": dados.get("ligadas") or sum(1 for item in itens if item.get("nif")),
        "com_contratos": sum(1 for item in itens if item.get("contratos")),
        "candidatos_contratos": dados.get("candidatos_contratos"),
        "indice_em_falta": bool(dados.get("indice_em_falta")),
        "erro": dados.get("erro"),
    }


# ------------------------------------------------------------------- pesquisa


def _ordenar(itens: List[Dict[str, Any]], ordenar: str) -> List[Dict[str, Any]]:
    """Ordena a lista de entidades (`nome`, `contratos`, `valor` ou `subsetor`)."""
    if ordenar == "nome_desc":
        return sorted(itens, key=lambda item: normalizar(item.get("nome")), reverse=True)
    if ordenar == "contratos":
        return sorted(itens, key=lambda item: (-int(item.get("contratos") or 0), normalizar(item.get("nome"))))
    if ordenar == "valor":
        return sorted(itens, key=lambda item: (-float(item.get("valor") or 0.0), normalizar(item.get("nome"))))
    if ordenar == "subsetor":
        return sorted(itens, key=lambda item: (item.get("subsetor") or "", normalizar(item.get("nome"))))
    return sorted(itens, key=lambda item: normalizar(item.get("nome")))


def pesquisar(
    q: Optional[str] = None,
    *,
    subsetor: Optional[str] = None,
    ligacao: Optional[str] = None,
    ordenar: str = "valor",
    tamanho: int = 25,
    desde: int = 0,
) -> Dict[str, Any]:
    """Pesquisa as entidades do índice por texto, subsetor e tipo de ligação."""
    termo = normalizar(q)
    palavras = [palavra for palavra in termo.split() if palavra]
    itens: List[Dict[str, Any]] = []
    for item in entidades(subsetor):
        if ligacao == "com_nif" and not item.get("nif"):
            continue
        if ligacao == "sem_nif" and item.get("nif"):
            continue
        if ligacao == "com_contratos" and not item.get("contratos"):
            continue
        if palavras:
            palheiro = normalizar(" ".join(filter(None, [item.get("nome"), item.get("nome_contratos"), item.get("nif")])))
            if not all(palavra in palheiro for palavra in palavras):
                continue
        itens.append(item)

    ordenados = _ordenar(itens, ordenar)
    pagina = ordenados[desde : desde + tamanho]
    return {
        "query": q,
        "subsetor": subsetor or "all",
        "ordenar": ordenar,
        "total": len(ordenados),
        "from": desde,
        "size": tamanho,
        "items": pagina,
    }


def exportar_csv(subsetor: Optional[str] = None, q: Optional[str] = None) -> str:
    """CSV do índice (entidade, subsetor, NIF, contratos e valor)."""
    import csv
    import io

    resultado = pesquisar(q=q, subsetor=subsetor, tamanho=10**6)
    buffer = io.StringIO()
    escritor = csv.writer(buffer, delimiter=";", lineterminator="\n")
    escritor.writerow(["id", "nome", "subsetor", "subsetor_nome", "nif", "nome_nos_contratos", "ligacao", "contratos", "valor", "ano_min", "ano_max"])
    for item in resultado["items"]:
        escritor.writerow(
            [
                item.get("id"),
                item.get("nome"),
                item.get("subsetor"),
                item.get("subsetor_nome"),
                item.get("nif") or "",
                item.get("nome_contratos") or "",
                item.get("ligacao"),
                item.get("contratos") or 0,
                f"{(item.get('valor') or 0):.2f}",
                item.get("ano_min") or "",
                item.get("ano_max") or "",
            ]
        )
    return buffer.getvalue()


# --------------------------------------------------------------- contratos (ES)


#: Cache das agregações do setor: a agregação varre milhões de contratos.
_agregacoes_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_TTL_AGREGACOES = 600.0


def _filtro_setor(nifs_do_setor: Sequence[str], papel: str = "adjudicantes") -> Dict[str, Any]:
    """Filtro dos contratos de um conjunto de NIF num dos papéis."""
    return {
        "nested": {
            "path": f"{papel}.parsed",
            "query": {"terms": {f"{papel}.parsed.nif": list(nifs_do_setor)}},
        }
    }


def _query_contratos(
    *,
    nifs_do_setor: Sequence[str],
    q: Optional[str] = None,
    ano: Optional[int] = None,
    entidade: Optional[str] = None,
    adjudicatario: Optional[str] = None,
    cpv: Optional[str] = None,
    preco_min: Optional[float] = None,
    preco_max: Optional[float] = None,
    data_inicio: Optional[str] = None,
    data_fim: Optional[str] = None,
) -> Dict[str, Any]:
    """Query dos contratos adjudicados pelas entidades do setor."""
    from api.elasticsearch_client import _and_filters, _build_contract_query

    base = _build_contract_query(
        q=q,
        year=ano,
        entity=entidade,
        cpv_code=cpv,
        min_price=preco_min,
        max_price=preco_max,
        start_date=data_inicio,
        end_date=data_fim,
        role="adjudicante",
    )
    filtros = [_filtro_setor(nifs_do_setor)]
    if adjudicatario:
        filtros.append(
            {
                "nested": {
                    "path": "adjudicatarios.parsed",
                    "query": {"match": {"adjudicatarios.parsed.nome": adjudicatario}},
                }
            }
        )
    return _and_filters(base, filtros)


def contratos(
    *,
    subsetor: Optional[str] = None,
    q: Optional[str] = None,
    ano: Optional[int] = None,
    entidade: Optional[str] = None,
    adjudicatario: Optional[str] = None,
    cpv: Optional[str] = None,
    preco_min: Optional[float] = None,
    preco_max: Optional[float] = None,
    tamanho: int = 20,
    desde: int = 0,
    nif: Optional[str] = None,
    es=None,
) -> Dict[str, Any]:
    """Contratos adjudicados pelas entidades do setor (pesquisa paginada)."""
    from api.elasticsearch_client import CONTRACTS_INDEX, get_es_client

    universo = [nif] if nif else nifs(subsetor)
    if not universo:
        return {"total": 0, "items": [], "from": desde, "size": tamanho, "aviso": "Sem entidades ligadas a NIF neste subsetor."}

    client = es or get_es_client()
    if not client:
        return {"total": 0, "items": [], "error": "Elasticsearch indisponível"}

    corpo = {
        "query": _query_contratos(
            nifs_do_setor=universo,
            q=q,
            ano=ano,
            entidade=entidade,
            adjudicatario=adjudicatario,
            cpv=cpv,
            preco_min=preco_min,
            preco_max=preco_max,
        ),
        "from": desde,
        "size": tamanho,
        "track_total_hits": True,
        "sort": [{"dataPublicacao": {"order": "desc", "missing": "_last", "unmapped_type": "date"}}, "_score"],
    }
    try:
        resposta = client.search(index=CONTRACTS_INDEX, body=corpo)
    except Exception as exc:  # noqa: BLE001 — erro de ES devolvido à interface
        logger.warning("Pesquisa de contratos do setor falhou: %s", exc)
        return {"total": 0, "items": [], "error": str(exc)}

    itens = []
    for acerto in resposta["hits"]["hits"]:
        fonte = dict(acerto["_source"])
        fonte["doc_id"] = acerto.get("_id")
        fonte["score"] = acerto.get("_score")
        itens.append(fonte)
    return {"total": resposta["hits"]["total"]["value"], "items": itens, "from": desde, "size": tamanho}


def _nome_do_nif(candidatos: Dict[str, str], nif: str) -> Optional[str]:
    return candidatos.get(nif)


def _linhas_de_baldes(baldes: Sequence[Dict[str, Any]], nomes: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """Normaliza baldes de agregação em linhas ``{key, nome, count, valor}``."""
    linhas = []
    for balde in baldes:
        chave = balde.get("key")
        nome = None
        if nomes:
            nome = nomes.get(str(chave))
        if not nome:
            acertos = ((balde.get("nome") or {}).get("hits") or {}).get("hits") or []
            if acertos:
                fonte = acertos[0].get("_source") or {}
                nome = fonte.get("nome") or fonte.get("adjudicatarios", {}).get("parsed", {}).get("nome")
        linhas.append(
            {
                "key": chave,
                "nome": nome,
                "count": int(balde.get("doc_count") or 0),
                "valor": round(float(((balde.get("valor") or {}).get("v") or {}).get("value") or 0), 2),
            }
        )
    return linhas


def agregacoes(
    subsetor: Optional[str] = None,
    *,
    ano: Optional[int] = None,
    q: Optional[str] = None,
    nif: Optional[str] = None,
    top: int = 20,
    es=None,
    forcar: bool = False,
) -> Dict[str, Any]:
    """Painel do setor: volume, valor, anos, entidades, adjudicatárias e CPV.

    Uma agregação sobre os contratos em que as entidades do setor são
    **adjudicantes**. O resultado é memorizado (TTL de 10 minutos) porque a
    agregação percorre todo o índice de contratos.
    """
    import time

    universo = [nif] if nif else nifs(subsetor)
    if not universo:
        return {
            "total_contratos": 0,
            "total_valor": 0.0,
            "items": [],
            "aviso": "Sem entidades ligadas a NIF neste subsetor.",
        }

    chave = json.dumps([sorted(universo)[:5], len(universo), ano, q, top], ensure_ascii=False)
    agora = time.time()
    if not forcar:
        guardado = _agregacoes_cache.get(chave)
        if guardado and agora - guardado[0] < _TTL_AGREGACOES:
            return guardado[1]

    from api.elasticsearch_client import CONTRACTS_INDEX, _resolve_agg_target, get_es_client

    client = es or get_es_client(request_timeout=120)
    if not client:
        return {"error": "Elasticsearch indisponível"}

    procedimento = _resolve_agg_target(client, "tipoprocedimento")
    contrato = _resolve_agg_target(client, "tipoContrato")
    runtime: Dict[str, Any] = {}
    for resolvido in (procedimento, contrato):
        if resolvido.get("runtime"):
            runtime.update(resolvido["runtime"])

    corpo: Dict[str, Any] = {
        "size": 0,
        "track_total_hits": True,
        "query": _query_contratos(nifs_do_setor=universo, q=q, ano=ano),
        "aggs": {
            "valor_total": {"sum": {"field": "precoContratual"}},
            "valor_medio": {"avg": {"field": "precoContratual"}},
            "valor_maximo": {"max": {"field": "precoContratual"}},
            "por_ano": {
                "terms": {"field": "Ano", "size": 40, "order": {"_key": "desc"}},
                "aggs": {"valor": {"sum": {"field": "precoContratual"}}},
            },
            "por_nif": {
                "nested": {"path": "adjudicantes.parsed"},
                "aggs": {
                    "chaves": {
                        "terms": {"field": "adjudicantes.parsed.nif", "size": max(50, min(1000, len(universo) + 50))},
                        "aggs": {
                            "valor": {"reverse_nested": {}, "aggs": {"v": {"sum": {"field": "precoContratual"}}}},
                        },
                    }
                },
            },
            "top_adjudicatarios": {
                "nested": {"path": "adjudicatarios.parsed"},
                "aggs": {
                    "chaves": {
                        "terms": {"field": "adjudicatarios.parsed.nif", "size": top, "order": {"valor": "desc"}},
                        "aggs": {
                            "nome": {"top_hits": {"size": 1, "_source": ["adjudicatarios.parsed.nome"]}},
                            "valor": {"reverse_nested": {}, "aggs": {"v": {"sum": {"field": "precoContratual"}}}},
                        },
                    }
                },
            },
            "top_cpv": {
                "nested": {"path": "cpv"},
                "aggs": {
                    "chaves": {
                        "terms": {"field": "cpv.code", "size": top, "order": {"_count": "desc"}},
                        "aggs": {
                            "nome": {"top_hits": {"size": 1, "_source": ["cpv"]}},
                            "valor": {"reverse_nested": {}, "aggs": {"v": {"sum": {"field": "precoContratual"}}}},
                        },
                    }
                },
            },
            "tipos_procedimento": {"terms": {"field": procedimento["field"], "size": 20, "missing": "N/A"}},
            "tipos_contrato": {"terms": {"field": contrato["field"], "size": 20, "missing": "N/A"}},
            "adjudicatarias_distintas": {
                "nested": {"path": "adjudicatarios.parsed"},
                "aggs": {"v": {"cardinality": {"field": "adjudicatarios.parsed.nif"}}},
            },
        },
    }
    if runtime:
        corpo["runtime_mappings"] = runtime

    try:
        resposta = client.search(index=CONTRACTS_INDEX, body=corpo)
    except Exception as exc:  # noqa: BLE001 — erro de ES devolvido à interface
        logger.warning("Agregações do setor falharam: %s", exc)
        return {"error": str(exc)}

    agregados = resposta["aggregations"]
    por_nif = {
        str(balde["key"]): {"contratos": int(balde.get("doc_count") or 0), "valor": round(float(((balde.get("valor") or {}).get("v") or {}).get("value") or 0), 2)}
        for balde in ((agregados["por_nif"] or {}).get("chaves") or {}).get("buckets", [])
    }
    catalogo = {item["nif"]: item for item in entidades(subsetor) if item.get("nif")}
    ranking = []
    for nif_entidade, dados in por_nif.items():
        entidade_catalogo = catalogo.get(nif_entidade) or {}
        ranking.append(
            {
                "nif": nif_entidade,
                "id": entidade_catalogo.get("id"),
                "nome": entidade_catalogo.get("nome") or entidade_catalogo.get("nome_contratos") or nif_entidade,
                "nome_contratos": entidade_catalogo.get("nome_contratos"),
                "subsetor": entidade_catalogo.get("subsetor"),
                "contratos": dados["contratos"],
                "valor": dados["valor"],
            }
        )
    ranking.sort(key=lambda linha: -linha["valor"])

    nomes_parte = {}
    for balde in ((agregados["top_adjudicatarios"] or {}).get("chaves") or {}).get("buckets", []):
        acertos = ((balde.get("nome") or {}).get("hits") or {}).get("hits") or []
        if acertos:
            nomes_parte[str(balde["key"])] = (acertos[0].get("_source") or {}).get("nome")

    nomes_cpv = {}
    for balde in ((agregados["top_cpv"] or {}).get("chaves") or {}).get("buckets", []):
        acertos = ((balde.get("nome") or {}).get("hits") or {}).get("hits") or []
        if acertos:
            cpvs = (acertos[0].get("_source") or {}).get("cpv") or []
            if cpvs:
                nomes_cpv[str(balde["key"])] = cpvs[0].get("description")

    resultado = {
        "subsetor": subsetor or "all",
        "ano": ano,
        "total_contratos": resposta["hits"]["total"]["value"],
        "total_valor": round(float(agregados["valor_total"]["value"] or 0), 2),
        "valor_medio": round(float(agregados["valor_medio"]["value"] or 0), 2),
        "valor_maximo": round(float(agregados["valor_maximo"]["value"] or 0), 2),
        "entidades_com_contratos": len(por_nif),
        "adjudicatarias_distintas": int((agregados["adjudicatarias_distintas"] or {}).get("v", {}).get("value") or 0),
        "por_ano": _linhas_de_baldes(agregados["por_ano"]["buckets"]),
        "top_entidades": ranking[:top],
        "top_adjudicatarios": _linhas_de_baldes(((agregados["top_adjudicatarios"] or {}).get("chaves") or {}).get("buckets", []), nomes_parte),
        "top_cpv": _linhas_de_baldes(((agregados["top_cpv"] or {}).get("chaves") or {}).get("buckets", []), nomes_cpv),
        "tipos_procedimento": _linhas_de_baldes(agregados["tipos_procedimento"]["buckets"]),
        "tipos_contrato": _linhas_de_baldes(agregados["tipos_contrato"]["buckets"]),
        "atualizado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    _agregacoes_cache[chave] = (agora, resultado)
    if len(_agregacoes_cache) > 64:
        for chave_antiga in sorted(_agregacoes_cache, key=lambda k: _agregacoes_cache[k][0])[:32]:
            _agregacoes_cache.pop(chave_antiga, None)
    return resultado


def ficha_entidade(identificador: str, *, tamanho: int = 15, es=None) -> Dict[str, Any]:
    """Ficha de uma entidade: catálogo, contratos, adjudicatárias e CPV."""
    item = entidade(identificador)
    if not item:
        return {"error": "Entidade não encontrada", "id": identificador}

    ficha: Dict[str, Any] = {"entidade": item, "ano": None}
    if not item.get("nif"):
        ficha["aviso"] = "Entidade sem NIF ligado nos contratos do portal BASE — não há contratos a atribuir."
        return ficha

    client = es
    if client is None:
        from api.elasticsearch_client import get_es_client

        client = get_es_client(request_timeout=120)
    if not client:
        ficha["error"] = "Elasticsearch indisponível"
        return ficha

    analise = agregacoes(None, nif=item["nif"], top=tamanho, es=client)
    if analise.get("error"):
        ficha["error"] = analise["error"]
        return ficha

    ficha["contratos"] = {
        "total": analise.get("total_contratos", 0),
        "valor": analise.get("total_valor", 0.0),
        "valor_medio": analise.get("valor_medio", 0.0),
        "valor_maximo": analise.get("valor_maximo", 0.0),
        "por_ano": analise.get("por_ano", []),
    }
    ficha["top_adjudicatarios"] = analise.get("top_adjudicatarios", [])
    ficha["top_cpv"] = analise.get("top_cpv", [])
    ficha["tipos_procedimento"] = analise.get("tipos_procedimento", [])
    ficha["ultimos"] = contratos(nif=item["nif"], tamanho=tamanho, es=client).get("items", [])
    return ficha


def atualizar_totais(es=None) -> Dict[str, Any]:
    """Reconstrói apenas as ligações/valores do índice gravado (sem tocar no PDF)."""
    return reconstruir(es=es, usar_contratos=True)
