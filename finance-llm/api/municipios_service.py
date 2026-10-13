"""Despesas das câmaras municipais e contratação pública, por município.

Duas fontes independentes são juntas numa ficha por município (308):

1. **Despesa** — o indicador **0013909** do INE (`json_indicador`), que publica,
   por município e ano, a despesa das câmaras municipais pelo classificador
   económico (`D`, `D1`, `D11`, …), em euros, com origem na DGAL.
2. **Contratação** — agregação do índice `contratos` (Portal BASE) por
   **adjudicante**, para os adjudicantes que são o próprio município
   («Município de Lisboa», «Câmara Municipal da Guarda», «Serviços
   Municipalizados … de Abrantes»). A série é anual (2012→2026) e, em cada
   município, destacam-se os `ANOS_RECENTES` mais recentes com contratação.

O resultado é indexado em `finance_municipios_despesas` e guardado em JSON
(`data/municipios/`), para a página «Despesas das câmaras municipais» e para a
área de cada município.
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

#: Endpoint do INE que devolve o indicador em JSON. `lang` tem de ir em
#: minúsculas: com `Lang=PT` a API responde «O código do idioma não é válido».
INE_URL = "https://www.ine.pt/ine/json_indicador/pindica.jsp?op=2&varcd=0013909&lang=PT"
INE_INDICADOR = "0013909"
INE_FONTE = "INE · indicador 0013909 (despesas das câmaras municipais, DGAL)"
INE_URL_HUMANO = "https://www.ine.pt/xurl/indx/0013909/PT"
DADOS_GOV_URL = "https://dados.gov.pt/pt/datasets/despesas-eur-das-camaras-municipais-1"
CONTRATOS_FONTE = "Portal BASE · contratos (adjudicante = município)"

#: O indicador publica o «Euro (€)» com **potência de 10 = 3** (ver a
#: metainformação do INE): os valores vêm em **milhares de euros**. Confirmado
#: pela soma nacional — 11 933 661 para o classificador `D` de 2023 — que só faz
#: sentido como 11,9 mil milhões de euros e não como 11,9 milhões. Tudo o que sai
#: deste serviço está em **euros**, para não haver duas escalas no sistema.
INE_POTENCIA_10 = 3
FATOR_EUROS = 10 ** INE_POTENCIA_10

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "municipios"

#: Classificador económico → (campo no índice, etiqueta legível). A ordem é a da
#: tabela oficial (do total para o detalhe).
CLASSIFICADORES: List[Tuple[str, str, str]] = [
    ("D", "despesas_total", "Total"),
    ("D1", "despesas_correntes", "Despesas correntes"),
    ("D11", "despesas_pessoal", "Despesas com pessoal"),
    ("D12", "despesas_bens_servicos", "Aquisição de bens e serviços"),
    ("D13", "despesas_juros", "Juros e outros encargos"),
    ("D14", "despesas_transferencias_freguesias", "Transferências correntes para freguesias"),
    ("D15", "despesas_outras_correntes", "Outras despesas correntes"),
    ("D2", "despesas_capital", "Despesas de capital"),
    ("D21", "despesas_bens_capital", "Aquisição de bens de capital"),
    ("D22", "despesas_transferencias_capital", "Transferências de capital"),
    ("D221", "despesas_transferencias_capital_freguesias", "Transferências de capital para freguesias"),
    ("D222", "despesas_outras_transferencias_capital", "Outras transferências de capital"),
    ("D23", "despesas_outras_capital", "Outras despesas de capital"),
    ("D24", "despesas_ativos_financeiros", "Ativos financeiros"),
    ("D25", "despesas_passivos_financeiros", "Passivos financeiros"),
]
CLASSIFICADOR_POR_CODIGO = {codigo: (campo, etiqueta) for codigo, campo, etiqueta in CLASSIFICADORES}

#: Nome do adjudicante → município. Apanha «Município de X», «Câmara Municipal
#: de/da/do X» e formas compridas («Serviços Municipalizados … Câmara Municipal
#: Vila Franca de Xira»), porque procura o **último** marcador.
_MUNICIPIO_RE = re.compile(
    r"(?:c[âa]mara\s+municipal|munic[íi]pio)\s*(?:d(?:e|o|a|os|as)\s+)?(?P<nome>.+)$",
    re.IGNORECASE,
)
#: Remates que não fazem parte do nome do município.
_RUIDO_RE = re.compile(r"\s*\((?:r\.?a\.?[am]\.?|s\.?\s*jorge|são jorge)\)\s*$", re.IGNORECASE)

_ABREVIATURAS = (
    (re.compile(r"\bs\.\s*", re.IGNORECASE), "sao "),
    (re.compile(r"\bsta\.\s*", re.IGNORECASE), "santa "),
    (re.compile(r"\bsto\.\s*", re.IGNORECASE), "santo "),
)

_LOCK = threading.Lock()


def _data_dir() -> Path:
    path = DEFAULT_DATA_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cache_path(name: str) -> Path:
    return _data_dir() / name


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write_json(name: str, payload: Any) -> Path:
    path = _cache_path(name)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def _read_json(name: str) -> Optional[Any]:
    path = _cache_path(name)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Cache %s ilegível: %s", name, exc)
        return None


# ------------------------------------------------------------------ texto
def _chave(texto: str) -> str:
    """Normaliza um nome para comparação: sem acentos, minúsculas, sem pontuação."""
    base = unicodedata.normalize("NFKD", str(texto or ""))
    base = "".join(c for c in base if not unicodedata.combining(c))
    base = base.lower().replace("'", " ").replace("-", " ")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", base)).strip()


def _normalizar_nome(texto: str) -> str:
    """Nome de município limpo de remates e de abreviaturas («S. Pedro» → «São Pedro»)."""
    limpo = _RUIDO_RE.sub("", str(texto or "")).strip()
    for padrao, troca in _ABREVIATURAS:
        limpo = padrao.sub(troca, limpo)
    return re.sub(r"\s+", " ", limpo).strip()


def municipio_do_adjudicante(nome: str) -> Optional[str]:
    """Extrai o nome do município de um adjudicante do Portal BASE.

    Devolve `None` quando o nome não identifica um município (ex.: empresas
    municipais com denominação própria).
    """
    texto = str(nome or "").strip()
    if not texto:
        return None
    m = _MUNICIPIO_RE.search(texto)
    if not m:
        return None
    candidato = _normalizar_nome(m.group("nome"))
    if not candidato or len(candidato) < 3:
        return None
    return candidato


# ----------------------------------------------------------------- providers
def recolher_ine(timeout: float = 90.0) -> Dict[str, Any]:
    """Descarrega o indicador do INE e devolve `{"despesas": {...}, "meta": {...}}`.

    `despesas` fica indexável por **nome de município**: para cada município,
    `{ano: {codigo_classificador: euros}}`.
    """
    headers = {"User-Agent": "IQOS/1.0 (analise de financas locais; contacto@icpm.tech)"}
    with httpx.Client(timeout=timeout, headers=headers, follow_redirects=True) as client:
        resp = client.get(INE_URL)
        resp.raise_for_status()
        payload = resp.json()

    bloco = (payload or [{}])[0]
    dados = bloco.get("Dados") or {}

    # Nome dos níveis NUTS (códigos curtos) para o campo `nuts_nome`.
    nuts_nomes: Dict[str, str] = {}
    for ano_linhas in dados.values():
        for linha in ano_linhas:
            codigo = str(linha.get("geocod") or "")
            if 0 < len(codigo) <= 3:
                nuts_nomes[codigo] = str(linha.get("geodsg") or "")

    despesas: Dict[str, Dict[str, Dict[str, float]]] = {}
    geocods: Dict[str, str] = {}
    anos: set = set()
    for ano, linhas in dados.items():
        anos.add(str(ano))
        for linha in linhas:
            codigo_geo = str(linha.get("geocod") or "")
            # 7 caracteres = município; os mais curtos são agregados NUTS.
            if len(codigo_geo) != 7:
                continue
            nome = str(linha.get("geodsg") or "").strip()
            if not nome:
                continue
            # O município entra na lista mesmo que este ano não tenha valor
            # publicado («//»): a ficha fica sem despesa, mas não desaparece.
            geocods[nome] = codigo_geo
            slot = despesas.setdefault(nome, {}).setdefault(str(ano), {})
            try:
                numero = float(linha["valor"]) * FATOR_EUROS
            except (KeyError, TypeError, ValueError):
                continue
            slot[str(linha.get("dim_3") or "")] = numero

    meta = {
        "indicador": bloco.get("IndicadorCod") or INE_INDICADOR,
        "designacao": bloco.get("IndicadorDsg"),
        "atualizado_em": bloco.get("DataUltimoAtualizacao"),
        "ultimo_periodo": bloco.get("UltimoPref"),
        "anos": sorted(anos),
        "municipios": len(despesas),
        "unidade_origem": f"milhares de euros (potência de 10 = {INE_POTENCIA_10})",
        "unidade_saida": "euros",
        "fator_euros": FATOR_EUROS,
        "fonte": INE_FONTE,
        "fonte_url": INE_URL_HUMANO,
        "dados_gov_url": DADOS_GOV_URL,
        "recolhido_em": _now_iso(),
        "nuts": sorted(nuts_nomes.items()),
    }
    return {"despesas": despesas, "geocods": geocods, "meta": meta}


def _padrao_adjudicantes_municipais() -> Dict[str, Any]:
    """Consulta os adjudicantes do Portal BASE que são câmaras/municípios."""
    should = []
    for termo in ("Município", "Câmara Municipal", "Camara Municipal", "Municipio"):
        should.append(
            {"wildcard": {"adjudicantes.parsed.nome": {"value": f"*{termo}*", "case_insensitive": True}}}
        )
    should.append(
        {"wildcard": {"adjudicantes.parsed.nome": {"value": "*mara Municipal*", "case_insensitive": True}}}
    )
    return {"bool": {"should": should, "minimum_should_match": 1}}


def agregar_contratos(es: Optional[Any] = None) -> Dict[str, Any]:
    """Agrega o índice `contratos` por adjudicante-município.

    Devolve, por **nome de adjudicante** (como está no BASE), o total de
    contratos, o valor e a série anual — mais o distrito de execução, que serve
    para preencher o distrito dos municípios que a ficha do INE não traz.
    """
    from api.elasticsearch_client import CONTRACTS_INDEX, get_es_client

    client = es or get_es_client()
    if not client:
        raise RuntimeError("Elasticsearch indisponível")

    body = {
        "size": 0,
        "query": {"nested": {"path": "adjudicantes.parsed", "query": _padrao_adjudicantes_municipais()}},
        "aggs": {
            "adjudicantes": {
                "nested": {"path": "adjudicantes.parsed"},
                "aggs": {
                    "nomes": {
                        "terms": {"field": "adjudicantes.parsed.nome", "size": 3000},
                        "aggs": {
                            "raiz": {
                                "reverse_nested": {},
                                "aggs": {
                                    "valor": {"sum": {"field": "precoContratual"}},
                                    "por_ano": {
                                        "date_histogram": {
                                            "field": "dataCelebracaoContrato",
                                            "calendar_interval": "year",
                                            "format": "yyyy",
                                            "min_doc_count": 1,
                                        },
                                        "aggs": {"valor": {"sum": {"field": "precoContratual"}}},
                                    },
                                    "execucao": {"terms": {"field": "localExecucao", "size": 10}},
                                },
                            }
                        },
                    }
                },
            }
        },
    }
    resp = client.search(index=CONTRACTS_INDEX, body=body)
    buckets = ((resp.get("aggregations", {}).get("adjudicantes", {}) or {}).get("nomes", {}) or {}).get("buckets", [])

    adjudicantes: Dict[str, Dict[str, Any]] = {}
    # Concelho → {distrito: contratos}, para se poder preencher o distrito de
    # cada município a partir do sítio onde os contratos são executados.
    execucao_por_concelho: Dict[str, Dict[str, int]] = {}
    for b in buckets:
        nome = b["key"]
        raiz = b.get("raiz", {}) or {}
        por_ano = {
            str(x.get("key_as_string") or x.get("key")): {
                "contratos": x["doc_count"],
                "valor": (x.get("valor", {}) or {}).get("value") or 0.0,
            }
            for x in (raiz.get("por_ano", {}) or {}).get("buckets", [])
        }
        adjudicantes[nome] = {
            "contratos": b["doc_count"],
            "valor": (raiz.get("valor", {}) or {}).get("value") or 0.0,
            "por_ano": por_ano,
        }
        # `localExecucao` é «Portugal, <Distrito>, <Concelho>».
        for execucao in (raiz.get("execucao", {}) or {}).get("buckets", []):
            partes = [p.strip() for p in str(execucao["key"]).split(",")]
            if len(partes) >= 3 and partes[2] and partes[1]:
                slot = execucao_por_concelho.setdefault(partes[2], {})
                slot[partes[1]] = slot.get(partes[1], 0) + execucao["doc_count"]

    distritos = {
        concelho: max(contagem.items(), key=lambda kv: kv[1])[0]
        for concelho, contagem in execucao_por_concelho.items()
    }
    return {
        "adjudicantes": adjudicantes,
        "distritos": distritos,
        "recolhido_em": _now_iso(),
    }


# ------------------------------------------------------------- construção
def _nuts_do_geocod(geocod: str) -> Tuple[Optional[str], Optional[str]]:
    """Devolve `(nuts_iii, nuts_ii)` a partir do código geográfico do INE."""
    codigo = str(geocod or "").strip()
    if len(codigo) != 7:
        return None, None
    return codigo[:3], codigo[:2]


def _distrito_do_municipio(nome: str, indice_distritos: Dict[str, str]) -> Optional[str]:
    """Distrito de um município, a partir dos concelhos vistos nos contratos.

    O indicador do INE não traz o distrito, mas `localExecucao` dos contratos
    traz («Portugal, Santarém, Abrantes»). Os municípios dos Açores e da Madeira
    aparecem no INE com a região entre parênteses («Calheta (R.A.M.)»), daí a
    desambiguação pelo sufixo antes de aceitar o distrito.
    """
    chave = _chave(nome)
    direto = indice_distritos.get(chave)
    if direto:
        return direto

    base = _chave(re.sub(r"\(.*?\)", " ", nome))
    distrito = indice_distritos.get(base)
    if not distrito:
        return None
    regiao = _chave(distrito)
    if "r a a" in chave and "acores" not in regiao:
        return None
    if "r a m" in chave and "madeira" not in regiao:
        return None
    return distrito


def construir_registos(
    ine: Dict[str, Any],
    contratos: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Junta a despesa do INE com a contratação pública, por município."""
    despesas: Dict[str, Dict[str, Dict[str, float]]] = ine.get("despesas") or {}
    geocods: Dict[str, str] = ine.get("geocods") or {}
    nuts_nomes = dict(ine.get("meta", {}).get("nuts") or [])
    adjudicantes: Dict[str, Dict[str, Any]] = (contratos or {}).get("adjudicantes") or {}

    # Índice dos nomes oficiais (a lista do INE é a espinha): chave normalizada
    # → nome oficial. Sem duplicados: os homónimos vêm desambiguados («Calheta
    # (R.A.A.)», «Calheta (R.A.M.)»).
    oficiais: Dict[str, List[str]] = {}
    for nome in despesas:
        oficiais.setdefault(_chave(nome), []).append(nome)

    # Adjudicante → município oficial, com os nomes usados por cada município.
    por_municipio: Dict[str, List[str]] = {}
    nao_atribuidos: List[str] = []
    ambiguos: List[str] = []
    for nome_adj in adjudicantes:
        candidato = municipio_do_adjudicante(nome_adj)
        if not candidato:
            nao_atribuidos.append(nome_adj)
            continue
        chave = _chave(candidato)
        alvo = None
        nomes_exatos = oficiais.get(chave) or []
        if len(nomes_exatos) == 1:
            alvo = nomes_exatos[0]
        else:
            # Tolerância, por ordem de confiança: o nome oficial começa pelo
            # candidato, o candidato começa pelo nome oficial, ou o candidato
            # está contido no nome oficial («Praia da Vitória» ⊂ «Vila da Praia
            # da Vitória»). Só se aceita quando o resultado é inequívoco.
            for filtro in (
                lambda k: k.startswith(chave),
                lambda k: chave.startswith(k),
                lambda k: chave in k,
            ):
                possiveis = [n for k, nomes in oficiais.items() if filtro(k) for n in nomes]
                if len(possiveis) == 1:
                    alvo = possiveis[0]
                    break
            if alvo is None and len(nomes_exatos) > 1:
                ambiguos.append(nome_adj)
                continue
        if not alvo:
            nao_atribuidos.append(nome_adj)
            continue
        por_municipio.setdefault(alvo, []).append(nome_adj)

    # Distrito por município: do concelho homónimo em `localExecucao` dos
    # contratos (o indicador do INE não traz o distrito). A comparação é feita
    # pela chave normalizada, para os acentos e a caixa não falharem o encontro.
    distritos: Dict[str, str] = (contratos or {}).get("distritos") or {}
    distrito_normalizado = {_chave(concelho): dist for concelho, dist in distritos.items()}

    registos: List[Dict[str, Any]] = []
    for nome, por_ano in despesas.items():
        geocod = geocods.get(nome, "")
        nuts_iii, nuts_ii = _nuts_do_geocod(geocod)
        anos = sorted(por_ano.keys())
        ano_atual = anos[-1] if anos else None
        atual = por_ano.get(ano_atual, {}) if ano_atual else {}

        doc: Dict[str, Any] = {
            "doc_id": geocod or _chave(nome).replace(" ", "-"),
            "nome": nome,
            "nome_keyword": _chave(nome),
            "geocod": geocod,
            "geocod_curto": geocod[-4:] if geocod else None,
            "ano_despesas": int(ano_atual) if ano_atual else None,
            "anos": anos,
            "despesas_total": atual.get("D"),
            "despesas_correntes": atual.get("D1"),
            "despesas_capital": atual.get("D2"),
            "despesas_pessoal": atual.get("D11"),
            "despesas_bens_servicos": atual.get("D12"),
            "despesas_juros": atual.get("D13"),
            "despesas_transferencias_freguesias": atual.get("D14"),
            "despesas_outras_correntes": atual.get("D15"),
            "despesas_bens_capital": atual.get("D21"),
            "despesas_transferencias_capital": atual.get("D22"),
            "despesas_transferencias_capital_freguesias": atual.get("D221"),
            "despesas_outras_transferencias_capital": atual.get("D222"),
            "despesas_outras_capital": atual.get("D23"),
            "despesas_ativos_financeiros": atual.get("D24"),
            "despesas_passivos_financeiros": atual.get("D25"),
            "despesas_por_ano": por_ano,
            "classificadores": {codigo: etiqueta for codigo, _, etiqueta in CLASSIFICADORES},
            "nuts": nuts_iii,
            "nuts_nome": nuts_nomes.get(nuts_iii or ""),
            "distrito": _distrito_do_municipio(nome, distrito_normalizado),
            "fonte_despesas": INE_FONTE,
            "recolhido_em": ine.get("meta", {}).get("recolhido_em"),
        }

        nomes_adj = por_municipio.get(nome) or []
        if nomes_adj:
            total = sum((adjudicantes.get(n) or {}).get("contratos", 0) for n in nomes_adj)
            valor = sum((adjudicantes.get(n) or {}).get("valor", 0.0) for n in nomes_adj)
            serie: Dict[str, Dict[str, float]] = {}
            for nome_adj in nomes_adj:
                for ano, dados in ((adjudicantes.get(nome_adj) or {}).get("por_ano") or {}).items():
                    slot = serie.setdefault(ano, {"contratos": 0, "valor": 0.0})
                    slot["contratos"] += dados.get("contratos", 0)
                    slot["valor"] += dados.get("valor", 0.0)
            doc.update({
                "contratos_total": total,
                "contratos_valor": valor,
                "contratos_por_ano": dict(sorted(serie.items())),
                "adjudicantes": nomes_adj,
                "fonte_contratos": CONTRATOS_FONTE,
            })
            anos_contrato = sorted(serie.keys())
            if anos_contrato:
                doc["contratos_primeiro_ano"] = int(anos_contrato[0])
                doc["contratos_ultimo_ano"] = int(anos_contrato[-1])

        registos.append(doc)

    # Diagnóstico ordenado por volume: mostra o que fica de fora **e** o que
    # isso representa, para não se julgar a qualidade do emparelhamento pela
    # contagem de nomes (as associações intermunicipais são muitas e pequenas).
    nao_atribuidos_ordenados = sorted(
        nao_atribuidos,
        key=lambda n: -((adjudicantes.get(n) or {}).get("valor") or 0.0),
    )
    diagnostico = {
        "municipios": len(registos),
        "com_despesas": sum(1 for r in registos if r.get("despesas_total") is not None),
        "com_contratos": sum(1 for r in registos if r.get("contratos_total")),
        "adjudicantes_reconhecidos": sum(len(v) for v in por_municipio.values()),
        "adjudicantes_nao_atribuidos": len(nao_atribuidos),
        "adjudicantes_ambiguos": len(ambiguos),
        "valor_nao_atribuido": sum((adjudicantes.get(n) or {}).get("valor") or 0.0 for n in nao_atribuidos),
        "exemplos_nao_atribuidos": nao_atribuidos_ordenados[:10],
        "exemplos_ambiguos": ambiguos[:10],
        "sem_distrito": sum(1 for r in registos if not r.get("distrito")),
    }
    return registos, diagnostico


def recolher(forcar: bool = False) -> Dict[str, Any]:
    """Recolhe as duas fontes, constrói as fichas e indexa-as."""
    from api.elasticsearch_client import index_municipios_despesas_bulk, get_es_client

    with _LOCK:
        ine = None if forcar else _read_json("despesas_ine.json")
        if not ine:
            ine = recolher_ine()
            _write_json("despesas_ine.json", ine)

        contratos = None if forcar else _read_json("contratos_municipios.json")
        if not contratos:
            contratos = agregar_contratos()
            _write_json("contratos_municipios.json", contratos)

    registos, diagnostico = construir_registos(ine, contratos)
    _write_json("municipios.json", {"gerado_em": _now_iso(), "fichas": registos, "diagnostico": diagnostico})

    indexacao = index_municipios_despesas_bulk(registos, es=get_es_client())
    return {
        "recolhido_em": _now_iso(),
        "indexacao": indexacao,
        "diagnostico": diagnostico,
        "meta": ine.get("meta"),
    }


# ------------------------------------------------------------------- leitura
def fichas_locais() -> List[Dict[str, Any]]:
    """Fichas guardadas em disco (fallback quando o Elasticsearch não responde)."""
    dados = _read_json("municipios.json") or {}
    return dados.get("fichas") or []


def anos_de_contratos(fichas: Optional[List[Dict[str, Any]]] = None) -> List[str]:
    """Anos com contratação registada no Portal BASE, do mais recente para o mais antigo.

    Sai das fichas locais (a série é a mesma que está no índice): é o que o
    seletor de ano da interface precisa para não oferecer anos vazios.
    """
    anos: set = set()
    for ficha in fichas if fichas is not None else fichas_locais():
        anos.update(str(ano) for ano in (ficha.get("contratos_por_ano") or {}))
    return sorted((ano for ano in anos if ano.isdigit()), reverse=True)


def contratos_do_ano(ficha: Dict[str, Any], ano: Any) -> Dict[str, float]:
    """Contratação de um município **num ano** (nº de contratos e valor)."""
    valores = (ficha.get("contratos_por_ano") or {}).get(str(ano)) or {}
    try:
        return {
            "contratos": int(valores.get("contratos") or 0),
            "valor": float(valores.get("valor") or 0.0),
        }
    except (TypeError, ValueError):
        return {"contratos": 0, "valor": 0.0}


#: Quantos anos recentes são calculados **por município** (o seletor de ano
#: continua a dar acesso a toda a série, 2012→2026).
ANOS_RECENTES = 5


def anos_recentes(fichas: Optional[List[Dict[str, Any]]] = None) -> List[str]:
    """Os `ANOS_RECENTES` anos mais recentes com contratação no Portal BASE."""
    return anos_de_contratos(fichas)[:ANOS_RECENTES]


def contratos_dos_anos_recentes(
    ficha: Dict[str, Any],
    limite: int = ANOS_RECENTES,
) -> List[Dict[str, Any]]:
    """Os anos mais recentes **de um município**, do mais recente para o mais antigo.

    Sai da série anual do Portal BASE (a mesma que está no índice): um município
    que só tenha contratado até 2019 mostra os anos dele, em vez de zeros nos
    anos em que não contratou.
    """
    serie = ficha.get("contratos_por_ano") or {}
    anos = sorted((str(ano) for ano in serie if str(ano).isdigit()), reverse=True)[:limite]
    return [
        {
            "ano": ano,
            "contratos": int((serie.get(ano) or {}).get("contratos") or 0),
            "valor": float((serie.get(ano) or {}).get("valor") or 0.0),
        }
        for ano in anos
    ]


def totais_dos_anos_recentes(fichas: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Contratação do Portal BASE nos anos recentes, somada por todos os municípios."""
    lista = fichas if fichas is not None else fichas_locais()
    anos = anos_recentes(lista)
    totais = {ano: {"ano": ano, "contratos": 0, "valor": 0.0} for ano in anos}
    for ficha in lista:
        serie = ficha.get("contratos_por_ano") or {}
        for ano in anos:
            dados = serie.get(ano) or {}
            totais[ano]["contratos"] += int(dados.get("contratos") or 0)
            totais[ano]["valor"] += float(dados.get("valor") or 0.0)
    return list(totais.values())


def _com_anos_recentes(itens: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Junta a cada linha os anos mais recentes de contratação do município."""
    for item in itens:
        item["contratos_recentes"] = contratos_dos_anos_recentes(item)
    return itens


#: Ordenações da lista quando se escolhe um ano de contratos: as de contratação
#: passam a ser **do ano escolhido** (é o valor que a coluna mostra).
ORDENACOES_ANO_CONTRATOS: Dict[str, str] = {
    "despesas": "despesas_total",
    "pessoal": "despesas_pessoal",
    "bens_servicos": "despesas_bens_servicos",
    "capital": "despesas_capital",
    "contratos": "contratos_ano_valor",
    "contratos_total": "contratos_ano_total",
    "nome": "nome",
}


def listar_por_ano_contratos(
    *,
    q: Optional[str] = None,
    distrito: Optional[str] = None,
    nuts: Optional[str] = None,
    ano: Optional[int] = None,
    ano_contratos: int,
    ordenar: str = "contratos",
    ordem: str = "desc",
    min_despesas: Optional[float] = None,
    size: int = 30,
    page: int = 1,
) -> Dict[str, Any]:
    """Lista os municípios pela contratação **de um ano** do Portal BASE.

    O `contratos_por_ano` é um objeto guardado mas **não indexado** (não se
    pesquisa nem se ordena por ele no Elasticsearch), pelo que a lista é montada
    sobre as 308 fichas locais: 308 linhas fazem-se em memória e poupam uma
    reindexação só para se poder ordenar por um ano.
    """
    alvo = _chave(q) if q else ""
    distrito_chave = _chave(distrito) if distrito else ""
    itens: List[Dict[str, Any]] = []
    for ficha in fichas_locais():
        if alvo and alvo not in _chave(str(ficha.get("nome") or "")):
            continue
        if distrito_chave and distrito_chave not in _chave(str(ficha.get("distrito") or "")):
            continue
        if nuts and str(ficha.get("nuts") or "") != str(nuts):
            continue
        if ano and str(ano) not in [str(valor) for valor in (ficha.get("anos") or [])]:
            continue
        if min_despesas is not None and float(ficha.get("despesas_total") or 0) < float(min_despesas):
            continue
        do_ano = contratos_do_ano(ficha, ano_contratos)
        itens.append({
            **ficha,
            "contratos_ano": int(ano_contratos),
            "contratos_ano_valor": do_ano["valor"],
            "contratos_ano_total": do_ano["contratos"],
        })

    campo = ORDENACOES_ANO_CONTRATOS.get(str(ordenar or ""), "contratos_ano_valor")
    reverso = str(ordem).lower() != "asc"
    itens.sort(
        key=lambda ficha: (
            str(ficha.get("nome") or "").lower() if campo == "nome" else float(ficha.get(campo) or 0)
        ),
        reverse=reverso,
    )

    distritos: Dict[str, int] = {}
    for ficha in itens:
        nome_distrito = str(ficha.get("distrito") or "—")
        distritos[nome_distrito] = distritos.get(nome_distrito, 0) + 1

    inicio = max(0, (max(1, page) - 1) * max(1, size))
    return {
        "total": len(itens),
        "items": _com_anos_recentes(itens[inicio : inicio + max(1, size)]),
        "page": page,
        "size": size,
        "origem": "json-local",
        "ano_contratos": int(ano_contratos),
        "contratos_ano_somados": sum(ficha["contratos_ano_valor"] for ficha in itens),
        "contratos_ano_total_somados": sum(ficha["contratos_ano_total"] for ficha in itens),
        "despesas_somadas": sum(float(ficha.get("despesas_total") or 0) for ficha in itens),
        "contratos_somados": sum(float(ficha.get("contratos_valor") or 0) for ficha in itens),
        "distritos": [
            {"key": chave, "count": count}
            for chave, count in sorted(distritos.items(), key=lambda par: -par[1])
        ],
    }


def listar(
    q: Optional[str] = None,
    distrito: Optional[str] = None,
    nuts: Optional[str] = None,
    ano: Optional[int] = None,
    ordenar: str = "despesas",
    ordem: str = "desc",
    min_despesas: Optional[float] = None,
    size: int = 30,
    page: int = 1,
    ano_contratos: Optional[int] = None,
) -> Dict[str, Any]:
    """Lista os municípios (Elasticsearch; recorre ao JSON local se falhar).

    Com `ano_contratos`, a lista é montada sobre as fichas locais para poder
    ordenar e somar a contratação **desse ano** do Portal BASE — a série anual
    não está indexada.
    """
    if ano_contratos:
        return listar_por_ano_contratos(
            q=q,
            distrito=distrito,
            nuts=nuts,
            ano=ano,
            ano_contratos=int(ano_contratos),
            ordenar=ordenar,
            ordem=ordem,
            min_despesas=min_despesas,
            size=size,
            page=page,
        )

    from api.elasticsearch_client import search_municipios_despesas

    resposta = search_municipios_despesas(
        q=q, distrito=distrito, nuts=nuts, ano=ano,
        ordenar=ordenar, ordem=ordem, min_despesas=min_despesas,
        size=size, page=page,
    )
    if resposta.get("items") or not resposta.get("error"):
        resposta["origem"] = "elasticsearch"
        resposta["items"] = _com_anos_recentes(resposta.get("items") or [])
        return resposta

    fichas = fichas_locais()
    alvo = _chave(q) if q else ""
    itens = [f for f in fichas if not alvo or alvo in _chave(f.get("nome", ""))]
    if distrito:
        d = _chave(distrito)
        itens = [f for f in itens if d in _chave(f.get("distrito", ""))]
    campo = "despesas_total" if ordenar == "despesas" else "contratos_valor"
    itens.sort(key=lambda f: f.get(campo) or 0, reverse=(ordem != "asc"))
    inicio = max(0, (max(1, page) - 1) * size)
    return {
        "total": len(itens),
        "items": _com_anos_recentes(itens[inicio:inicio + size]),
        "page": page,
        "size": size,
        "origem": "json-local",
        "error": resposta.get("error"),
    }


def ficha(nome_ou_codigo: str, detalhar_contratos: bool = True) -> Dict[str, Any]:
    """Ficha de um município, com a despesa detalhada e a contratação.

    Quando `detalhar_contratos` é verdadeiro (por omissão), junta a agregação a
    pedido — fornecedores e tipos de contrato —, que não é guardada no índice
    porque só interessa a quem abre a ficha.
    """
    from api.elasticsearch_client import contratos_do_municipio, get_municipio_despesas

    doc = get_municipio_despesas(nome_ou_codigo)
    if doc.get("error"):
        alvo = _chave(nome_ou_codigo)
        for f in fichas_locais():
            if _chave(f.get("nome", "")) == alvo or f.get("geocod") == nome_ou_codigo:
                doc = f
                break

    if detalhar_contratos and not doc.get("error") and doc.get("adjudicantes"):
        doc["contratos_detalhe"] = contratos_do_municipio(doc["adjudicantes"])
    return doc


def meta() -> Dict[str, Any]:
    """Proveniência dos dados e volumetria local."""
    from api.elasticsearch_client import municipios_despesas_status

    ine_meta = (_read_json("despesas_ine.json") or {}).get("meta") or {}
    dados = _read_json("municipios.json") or {}
    return {
        "fonte_despesas": INE_FONTE,
        "fonte_despesas_url": INE_URL_HUMANO,
        "fonte_dados_gov": DADOS_GOV_URL,
        "fonte_contratos": CONTRATOS_FONTE,
        "indicador": ine_meta.get("indicador") or INE_INDICADOR,
        "designacao": ine_meta.get("designacao"),
        "anos": ine_meta.get("anos") or [],
        "atualizado_no_ine": ine_meta.get("atualizado_em"),
        "ultimo_periodo": ine_meta.get("ultimo_periodo"),
        "recolhido_em": ine_meta.get("recolhido_em"),
        "gerado_em": dados.get("gerado_em"),
        "diagnostico": dados.get("diagnostico"),
        "classificadores": [{"codigo": c, "etiqueta": e} for c, _, e in CLASSIFICADORES],
        "anos_contratos": anos_de_contratos(),
        "anos_recentes": anos_recentes(),
        "totais_recentes": totais_dos_anos_recentes(),
        "indice": municipios_despesas_status(),
    }


def mapa() -> Dict[str, Any]:
    """Todos os municípios com os valores para a visualização."""
    from api.elasticsearch_client import municipios_despesas_mapa

    itens = municipios_despesas_mapa()
    if not itens:
        itens = fichas_locais()
    return {"total": len(itens), "items": itens}
