"""Inteligência empresarial de contratação pública — mercados CPV × CAE × contrato.

O que este motor faz
--------------------
Não compara empresas pelo volume total de contratos: define **mercados
comparáveis** por `CPV semelhante + CAE compatível + período` e mede, dentro
desse mercado, três coisas distintas:

1. **Posicionamento** — `P_i = V_i / Σ_{j∈M} V_j`: a quota do valor contratual
   publicado da empresa *dentro do mercado definido*. Não é quota de mercado
   total (o portal não publica a compra privada nem todas as compras públicas).
2. **Dependência da empresa face às entidades públicas** — `D_i = Σ_e s_{ie}²`
   (HHI da carteira de compradores): quanto maior, mais concentrado o valor
   publicado em poucos compradores. Concentração **não** é dependência
   económica: faltam receitas privadas e outros mercados.
3. **Dependência das entidades face aos fornecedores** — quanto do valor de cada
   entidade pública depende de um fornecedor por CPV, com as alternativas
   observadas (a base dos cenários de rutura).

A estrutura central é um **grafo temporal**: empresa → contrato → entidade
adjudicante → CPV → CAE, com relações datadas. Partilhar clientes ou
fornecedores é uma **relação observada** — não é prova de coordenação entre
empresas nem de irregularidade.

O motor de sensibilidade (Lorenz) e o World Model entram como **experiências**
de alteração das condições iniciais (perder o maior comprador, entrada de um
concorrente, contratos a expirar, preços, diversificação), sempre com os
contratos de origem como evidência e as hipóteses escritas.

Reutiliza de `lorenz_service` o escopo (filtros do índice `contratos`), a série
por período, o cruzamento por classe de CPV, as dependências, as evidências e a
matemática de sensibilidade — **uma só implementação** para as duas páginas.

Limitações declaradas (todas devolvidas em `avisos`/`cobertura`)
---------------------------------------------------------------
- O **CAE** vem do registo (`finance_entities`: `cae_principal`,
  `caes_secundarios`), não do Portal BASE: uma empresa sem CAE no registo fica
  com `cae: null` e **não** é inventada — a compatibilidade aparece como
  «desconhecida» e a cobertura do mercado é sempre reportada.
- A correspondência CPV ↔ CAE é uma **tabela de regras** curada e editável
  (`data/mercado/cae_cpv.json`), com grau (alta/média/baixa). É indicativa.
- O portal publica **concorrentes** (lista de NIFs em texto por contrato) e o
  **adjudicatário**, mas não as propostas completas: a simulação de concorrência
  usa a participação observada e a força histórica, não preços de cada proposta.
"""
from __future__ import annotations

import json
import logging
import math
import os
import random
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from elasticsearch import Elasticsearch

from api import lorenz_service as lz
from api.cae_catalog import label_for_cae
from api.elasticsearch_client import (
    CONTRACTS_INDEX,
    ENTITIES_INDEX,
    LORENZ_RUNS_INDEX,
    MERCADO_RUNS_INDEX,
    UNSPECIFIED_LABEL,
    ensure_indices,
    get_es_client,
)

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = Path(os.environ.get("MERCADO_CONFIG_PATH") or (ROOT / "data" / "mercado" / "cae_cpv.json"))

# ---------------------------------------------------------------------------
# Tabela CPV ↔ CAE (regras curadas, com grau) — editável no ficheiro JSON
# ---------------------------------------------------------------------------
#: Cada regra: `cae` (prefixo do código CAE), `cpv` (prefixo de CPV), `grau`
#: (`alta`/`média`/`baixa`), `nota` (porquê) e `fonte` (de onde vem a regra).
#: O código CAE é comparado por prefixo, do mais longo para o mais curto; a
#: compatibilidade de uma empresa é o **melhor** grau entre os seus CAE.
CAE_CPV_DEFAULT: List[Dict[str, str]] = [
    # --- saúde e farmácia
    {"cae": "21", "cpv": "336", "grau": "alta", "nota": "Fabricação de produtos farmacêuticos ↔ medicamentos", "fonte": "CAE Rev.4 div. 21 / CPV 336"},
    {"cae": "212", "cpv": "336", "grau": "alta", "nota": "Fabricação de preparações farmacêuticas", "fonte": "CAE Rev.4 2120x"},
    {"cae": "4646", "cpv": "336", "grau": "alta", "nota": "Comércio por grosso de produtos farmacêuticos", "fonte": "CAE Rev.4 46460"},
    {"cae": "3250", "cpv": "331", "grau": "alta", "nota": "Fabricação de dispositivos médicos e dentários", "fonte": "CAE Rev.4 3250x"},
    {"cae": "325", "cpv": "3314", "grau": "alta", "nota": "Instrumentos e material médico-cirúrgico", "fonte": "CAE Rev.4 3250x"},
    {"cae": "4645", "cpv": "331", "grau": "média", "nota": "Comércio por grosso de produtos de higiene e médico-cirúrgicos", "fonte": "CAE Rev.4 4645x"},
    {"cae": "4644", "cpv": "331", "grau": "média", "nota": "Comércio por grosso de equipamento médico (grupo do comércio especializado)", "fonte": "CAE Rev.4 464x"},
    {"cae": "2660", "cpv": "3311", "grau": "alta", "nota": "Fabricação de equipamento médico de radiação/imagiologia", "fonte": "CAE Rev.4 26600"},
    {"cae": "86", "cpv": "851", "grau": "alta", "nota": "Atividades de saúde humana ↔ serviços de saúde", "fonte": "CAE Rev.4 div. 86 / CPV 851"},
    {"cae": "87", "cpv": "853", "grau": "alta", "nota": "Atividades de apoio social com alojamento", "fonte": "CAE Rev.4 div. 87"},
    {"cae": "88", "cpv": "853", "grau": "média", "nota": "Ação social sem alojamento", "fonte": "CAE Rev.4 div. 88"},
    {"cae": "4773", "cpv": "336", "grau": "média", "nota": "Farmácias (retalho) — fornecimento pontual", "fonte": "CAE Rev.4 47730"},
    # --- construção e engenharia
    {"cae": "41", "cpv": "45", "grau": "alta", "nota": "Construção de edifícios ↔ obra", "fonte": "CAE Rev.4 div. 41 / CPV 45"},
    {"cae": "42", "cpv": "45", "grau": "alta", "nota": "Engenharia civil ↔ obra de infraestruturas", "fonte": "CAE Rev.4 div. 42"},
    {"cae": "43", "cpv": "45", "grau": "alta", "nota": "Atividades especializadas de construção", "fonte": "CAE Rev.4 div. 43"},
    {"cae": "71", "cpv": "712", "grau": "alta", "nota": "Arquitetura e engenharia ↔ serviços de engenharia (CPV 712)", "fonte": "CAE Rev.4 div. 71 / CPV 712"},
    {"cae": "71", "cpv": "45", "grau": "média", "nota": "Projetos para obra", "fonte": "CAE Rev.4 711x"},
    # --- tecnologias de informação
    {"cae": "62", "cpv": "72", "grau": "alta", "nota": "Consultoria e programação informática ↔ serviços de TI (CPV 72)", "fonte": "CAE Rev.4 div. 62"},
    {"cae": "62", "cpv": "48", "grau": "média", "nota": "Licenciamento e implementação de software", "fonte": "CAE Rev.4 620x"},
    {"cae": "63", "cpv": "72", "grau": "média", "nota": "Infraestrutura e processamento de dados", "fonte": "CAE Rev.4 div. 63"},
    {"cae": "26", "cpv": "30", "grau": "alta", "nota": "Fabricação de equipamento informático e eletrónico (CPV 30)", "fonte": "CAE Rev.4 div. 26"},
    {"cae": "46", "cpv": "30", "grau": "média", "nota": "Comércio por grosso de equipamento informático", "fonte": "CAE Rev.4 465x"},
    # --- energia, transportes, ambiente
    {"cae": "35", "cpv": "31", "grau": "alta", "nota": "Energia elétrica e gás ↔ CPV 31/09", "fonte": "CAE Rev.4 div. 35"},
    {"cae": "35", "cpv": "09", "grau": "média", "nota": "Combustíveis e energia", "fonte": "CAE Rev.4 div. 35"},
    {"cae": "49", "cpv": "60", "grau": "alta", "nota": "Transporte terrestre ↔ serviços de transporte", "fonte": "CAE Rev.4 div. 49"},
    {"cae": "52", "cpv": "63", "grau": "média", "nota": "Armazenagem e apoio ao transporte", "fonte": "CAE Rev.4 div. 52"},
    {"cae": "38", "cpv": "90", "grau": "alta", "nota": "Recolha, tratamento e eliminação de resíduos", "fonte": "CAE Rev.4 div. 38"},
    {"cae": "81", "cpv": "90", "grau": "média", "nota": "Limpeza e serviços para edifícios", "fonte": "CAE Rev.4 812x"},
    # --- serviços às organizações
    {"cae": "69", "cpv": "79", "grau": "alta", "nota": "Atividades jurídicas e de contabilidade ↔ serviços jurídicos", "fonte": "CAE Rev.4 div. 69"},
    {"cae": "70", "cpv": "79", "grau": "média", "nota": "Consultoria de gestão", "fonte": "CAE Rev.4 702x"},
    {"cae": "73", "cpv": "793", "grau": "alta", "nota": "Publicidade e estudos de mercado ↔ serviços de publicidade", "fonte": "CAE Rev.4 div. 73"},
    {"cae": "80", "cpv": "797", "grau": "média", "nota": "Segurança e investigação", "fonte": "CAE Rev.4 div. 80"},
    {"cae": "82", "cpv": "79", "grau": "média", "nota": "Serviços administrativos e de apoio", "fonte": "CAE Rev.4 div. 82"},
    {"cae": "85", "cpv": "80", "grau": "alta", "nota": "Educação ↔ serviços de educação e formação", "fonte": "CAE Rev.4 div. 85 / CPV 80"},
    {"cae": "56", "cpv": "55", "grau": "alta", "nota": "Restauração e catering", "fonte": "CAE Rev.4 div. 56 / CPV 55"},
    {"cae": "10", "cpv": "15", "grau": "alta", "nota": "Indústria alimentar ↔ produtos alimentares", "fonte": "CAE Rev.4 div. 10-12 / CPV 15"},
    {"cae": "11", "cpv": "15", "grau": "alta", "nota": "Indústria das bebidas", "fonte": "CAE Rev.4 div. 11"},
    {"cae": "33", "cpv": "50", "grau": "alta", "nota": "Reparação e instalação de máquinas ↔ serviços de reparação", "fonte": "CAE Rev.4 div. 33 / CPV 50"},
    {"cae": "33", "cpv": "507", "grau": "média", "nota": "Manutenção de equipamento", "fonte": "CAE Rev.4 div. 33 / CPV 507"},
    {"cae": "77", "cpv": "34", "grau": "média", "nota": "Aluguer de veículos e equipamento", "fonte": "CAE Rev.4 div. 77"},
    {"cae": "68", "cpv": "70", "grau": "média", "nota": "Atividades imobiliárias ↔ serviços imobiliários", "fonte": "CAE Rev.4 div. 68"},
    {"cae": "47", "cpv": "33", "grau": "baixa", "nota": "Retalho (pode fornecer material médico pontual)", "fonte": "CAE Rev.4 div. 47"},
]

GRAUS: Dict[str, float] = {"alta": 0.9, "média": 0.6, "média-alta": 0.75, "baixa": 0.3, "desconhecida": 0.0}
ORDEM_GRAU = {"alta": 0, "média": 1, "baixa": 2, "desconhecida": 3}

PARAMETROS_DEFAULT: Dict[str, Any] = {
    "top_empresas": 20,
    "top_mercados": 12,
    "top_entidades": 20,
    "entidades_por_empresa": 25,
    "cpvs_por_empresa": 20,
    "anos_por_empresa": 40,
    "limite_comparacao": 12,
    # Simulação de concorrência (Monte Carlo): concursos a simular e semente.
    "concursos_simulados": 2000,
    "semente": 42,
    # Peso da força histórica vs especialização no CPV, no modelo de disputa.
    "peso_forca": 0.65,
    "peso_especializacao": 0.35,
    # Contratos a expirar: horizonte por omissão (dias).
    "horizonte_expiracao_dias": 180,
    "precos_variacao": 0.10,
    # Limiares de alerta.
    "limiar_dependencia": 0.50,
    "limiar_lider": 0.40,
    "limiar_queda": -0.10,
}

_config_cache: Dict[str, Any] = {"mtime": None, "dados": None}
_config_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Configuração (tabela CPV↔CAE + parâmetros)
# ---------------------------------------------------------------------------
def _config_vazia() -> Dict[str, Any]:
    return {"cae_cpv": CAE_CPV_DEFAULT, "parametros": PARAMETROS_DEFAULT}


def _ler_config(forcar: bool = False) -> Dict[str, Any]:
    with _config_lock:
        try:
            mtime = CONFIG_PATH.stat().st_mtime
        except OSError:
            mtime = None
        if not forcar and _config_cache["dados"] is not None and _config_cache["mtime"] == mtime:
            return _config_cache["dados"]
        dados = _config_vazia()
        if mtime is not None:
            try:
                lido = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
                if isinstance(lido, dict) and isinstance(lido.get("cae_cpv"), list) and lido["cae_cpv"]:
                    dados["cae_cpv"] = lido["cae_cpv"]
                    if isinstance(lido.get("parametros"), dict):
                        dados["parametros"] = {**PARAMETROS_DEFAULT, **lido["parametros"]}
            except (OSError, ValueError) as erro:  # noqa: BLE001 — cai nas predefinições
                logger.warning("mercado: config ilegível (%s) — a usar a tabela predefinida", erro)
        _config_cache["mtime"] = mtime
        _config_cache["dados"] = dados
        return dados


def parametros() -> Dict[str, Any]:
    return dict(_ler_config()["parametros"])


def regras_cae_cpv() -> List[Dict[str, str]]:
    return list(_ler_config()["cae_cpv"])


def guardar_tabela(regras: List[Dict[str, str]], parametros_novos: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Grava a tabela CPV↔CAE (só regras válidas: prefixos numéricos e grau conhecido)."""
    limpas: List[Dict[str, str]] = []
    for regra in regras:
        cae = str(regra.get("cae") or "").strip()
        cpv = str(regra.get("cpv") or "").strip()
        grau = str(regra.get("grau") or "").strip().lower()
        if not cae.isdigit() or not cpv.isdigit() or grau not in GRAUS:
            continue
        limpas.append(
            {
                "cae": cae,
                "cpv": cpv,
                "grau": grau,
                "nota": str(regra.get("nota") or "").strip(),
                "fonte": str(regra.get("fonte") or "").strip(),
            }
        )
    if not limpas:
        limpas = list(CAE_CPV_DEFAULT)
    dados = {
        "cae_cpv": limpas,
        "parametros": {**PARAMETROS_DEFAULT, **(parametros_novos or parametros())},
        "atualizado_em": datetime.now(timezone.utc).isoformat(),
    }
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporario = CONFIG_PATH.with_suffix(".tmp")
    temporario.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    temporario.replace(CONFIG_PATH)
    _config_cache["mtime"] = None
    _config_cache["dados"] = None
    return {"ok": True, **dados}


# ---------------------------------------------------------------------------
# Compatibilidade CPV ↔ CAE
# ---------------------------------------------------------------------------
def _cae_normalizado(cae: Optional[str]) -> str:
    return "".join(ch for ch in str(cae or "") if ch.isdigit())


def compatibilidade(cae: Optional[str], cpv: Optional[str], *, regras: Optional[Sequence[Dict[str, str]]] = None) -> Dict[str, Any]:
    """Grau de compatibilidade entre um CAE (atividade) e um CPV (objeto do contrato).

    Regra: casa por **prefixo**, do mais longo para o mais curto, e fica com o
    melhor grau. Uma empresa sem CAE devolve `desconhecida` — nunca se inventa
    compatibilidade a partir do nome.
    """
    tabela = list(regras if regras is not None else regras_cae_cpv())
    codigo_cae = _cae_normalizado(cae)
    classe_cpv = lz._classe_cpv(cpv) if cpv else ""
    if not codigo_cae or not classe_cpv:
        return {
            "grau": "desconhecida",
            "score": 0.0,
            "motivo": "sem CAE no registo" if not codigo_cae else "sem CPV no contrato",
            "regra": None,
        }
    melhor: Optional[Dict[str, str]] = None
    for regra in tabela:
        prefixo_cae = str(regra.get("cae") or "")
        prefixo_cpv = str(regra.get("cpv") or "")
        cae_casa = codigo_cae.startswith(prefixo_cae)
        cpv_casa = str(cpv).startswith(prefixo_cpv) or classe_cpv.startswith(prefixo_cpv)
        if not cae_casa or not cpv_casa:
            continue
        if melhor is None or ORDEM_GRAU.get(regra.get("grau", "baixa"), 9) < ORDEM_GRAU.get(melhor.get("grau", "baixa"), 9):
            melhor = regra
    if melhor is None:
        return {"grau": "desconhecida", "score": 0.0, "motivo": "sem regra CPV↔CAE para este par", "regra": None}
    grau = melhor.get("grau", "baixa")
    return {
        "grau": grau,
        "score": GRAUS.get(grau, 0.3),
        "motivo": melhor.get("nota") or "regra da tabela CPV↔CAE",
        "regra": melhor,
    }


def compatibilidade_empresa(
    caes: Sequence[Optional[str]],
    cpv: Optional[str],
    *,
    regras: Optional[Sequence[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """Melhor compatibilidade entre **todos** os CAE da empresa e o CPV do mercado."""
    melhor: Optional[Dict[str, Any]] = None
    for cae in caes:
        resultado = compatibilidade(cae, cpv, regras=regras)
        if resultado["grau"] == "desconhecida":
            continue
        if melhor is None or resultado["score"] > melhor["score"]:
            melhor = {**resultado, "cae": cae}
    if melhor is not None:
        return melhor
    return {
        "grau": "desconhecida",
        "score": 0.0,
        "motivo": "sem CAE compatível conhecido" if any(caes) else "empresa sem CAE no registo",
        "regra": None,
        "cae": next((c for c in caes if c), None),
    }


# ---------------------------------------------------------------------------
# Indicadores (puros)
# ---------------------------------------------------------------------------
def indice_posicionamento(valor_empresa: float, valor_mercado: float) -> float:
    """`P_i = V_i / Σ_j V_j` — quota no mercado definido (nunca > 1 por construção)."""
    if valor_mercado <= 0:
        return 0.0
    return max(0.0, min(1.0, valor_empresa / valor_mercado))


def indice_dependencia(valores_por_entidade: Sequence[float]) -> Dict[str, Any]:
    """`D_i = Σ_e s_ie²` sobre a carteira de compradores + leitura legível."""
    total = sum(max(0.0, float(valor)) for valor in valores_por_entidade)
    if total <= 0:
        return {"hhi": 0.0, "maior_quota": 0.0, "n_entidades": 0, "entropia": 0.0}
    quotas = [max(0.0, float(valor)) / total for valor in valores_por_entidade]
    hhi = sum(quota**2 for quota in quotas)
    entropia = -sum(quota * math.log(quota) for quota in quotas if quota > 0)
    return {
        "hhi": hhi,
        "maior_quota": max(quotas),
        "n_entidades": len(quotas),
        "entropia": entropia,
        # HHI normalizado: 1 = um só comprador, 0 = totalmente disperso.
        "hhi_normalizado": (hhi - 1 / len(quotas)) / (1 - 1 / len(quotas)) if len(quotas) > 1 else 1.0,
    }


def evolucao_anual(serie: Sequence[Tuple[Any, float]]) -> Dict[str, Any]:
    """Evolução temporal de um valor anual: variação total, CAGR e declive normalizado."""
    limpos = sorted(((int(ano), float(valor)) for ano, valor in serie if valor is not None), key=lambda par: par[0])
    if len(limpos) < 2:
        return {
            "anos": [ano for ano, _ in limpos],
            "valores": [valor for _, valor in limpos],
            "variacao": None,
            "cagr": None,
            "declive": None,
            "n_anos": len(limpos),
        }
    primeiro, ultimo = limpos[0][1], limpos[-1][1]
    anos_decorridos = limpos[-1][0] - limpos[0][0]
    variacao = (ultimo - primeiro) / primeiro if primeiro > 0 else None
    cagr = None
    if primeiro > 0 and ultimo > 0 and anos_decorridos > 0:
        cagr = (ultimo / primeiro) ** (1.0 / anos_decorridos) - 1.0
    valores = np.array([valor for _, valor in limpos], dtype=float)
    declive = None
    if valores.size >= 2 and float(np.std(valores)) > 1e-9 and valores.mean() > 0:
        # Declive da reta ajustada, normalizado pela média (leitura «% por ano»).
        indices = np.arange(valores.size, dtype=float)
        inclinacao = float(np.polyfit(indices, valores, 1)[0])
        declive = inclinacao / float(valores.mean())
    return {
        "anos": [ano for ano, _ in limpos],
        "valores": [valor for _, valor in limpos],
        "variacao": variacao,
        "cagr": cagr,
        "declive": declive,
        "n_anos": len(limpos),
    }


# ---------------------------------------------------------------------------
# Recolha: empresas do mercado, CAE e métricas por empresa
# ---------------------------------------------------------------------------
def _label_cae(codigo: Optional[str]) -> Optional[str]:
    """Descrição legível do CAE, tolerante a ambientes sem o catálogo catalogado.

    O catálogo vive num documento (`data/docs/CAE-Rev.4.md`) que **não** entra na
    imagem de produção (o `data/` é excluído do contexto de build e chega por
    volume). Se faltar, a descrição fica `None` — nunca se derruba a medição
    inteira por causa de um rótulo.
    """
    if not codigo:
        return None
    try:
        return label_for_cae(codigo)
    except Exception as erro:  # noqa: BLE001
        logger.debug("mercado: catálogo CAE indisponível (%s)", erro)
        return None


def cae_por_nif(nifs: Sequence[str], *, es: Optional[Elasticsearch] = None) -> Dict[str, Dict[str, Any]]:
    """CAE (principal e secundários) das empresas, a partir de `finance_entities`.

    Empresas sem registo ficam de fora do dicionário: quem chama trata a ausência
    como «CAE desconhecido» (não se presume atividade).
    """
    limpos = sorted({str(nif) for nif in nifs if nif})
    if not limpos:
        return {}
    cliente = lz._cliente(es)
    if cliente is None:
        return {}
    corpo = {
        "size": len(limpos),
        "_source": ["nif", "name", "cae_principal", "caes_secundarios", "concelho", "situacao"],
        "query": {"terms": {"nif": limpos}},
    }
    try:
        resposta = cliente.search(index=ENTITIES_INDEX, body=corpo)
    except Exception as erro:  # noqa: BLE001
        logger.warning("mercado: leitura de CAE falhou (%s)", erro)
        return {}
    saida: Dict[str, Dict[str, Any]] = {}
    for hit in ((resposta.get("hits") or {}).get("hits") or []):
        fonte = hit.get("_source") or {}
        nif = str(fonte.get("nif") or hit.get("_id") or "")
        if not nif:
            continue
        principal = _cae_normalizado(fonte.get("cae_principal")) or None
        secundarios = [_cae_normalizado(valor) for valor in (fonte.get("caes_secundarios") or [])]
        secundarios = [valor for valor in secundarios if valor]
        saida[nif] = {
            "nif": nif,
            "nome_registo": fonte.get("name"),
            "cae_principal": principal,
            "cae_principal_label": _label_cae(principal),
            "caes_secundarios": secundarios,
            "caes": [valor for valor in [principal, *secundarios] if valor],
            "concelho": fonte.get("concelho"),
            "situacao": fonte.get("situacao"),
        }
    return saida


def _aggs_empresa(campo_procedimento: str, nif: str, *, entidades: int, cpvs: int, anos: int) -> Dict[str, Any]:
    """Agregações de uma empresa no papel de adjudicatária (nome próprio, compradores, anos, CPV).

    O nome da **própria** empresa vem de um `nested` + `filter` no seu NIF: sem
    isso, o rótulo acabava a ser o do maior comprador (defeito real corrigido).
    """
    return {
        "eu": {
            "nested": {"path": "adjudicatarios.parsed"},
            "aggs": {
                "proprio": {
                    "filter": {"term": {"adjudicatarios.parsed.nif": nif}},
                    "aggs": {"nome": {"top_hits": {"size": 1}}},
                }
            },
        },
        "valor": {"sum": {"field": "precoContratual"}},
        "valor_efetivo": {"sum": {"field": "PrecoTotalEfetivo"}},
        "percentis": {"percentiles": {"field": "precoContratual", "percents": [50, 90], "keyed": True}},
        "entidades": {
            "nested": {"path": "adjudicantes.parsed"},
            "aggs": {
                "distintas": {"cardinality": {"field": "adjudicantes.parsed.nif"}},
                "por_nif": {
                    "terms": {"field": "adjudicantes.parsed.nif", "size": entidades, "missing": UNSPECIFIED_LABEL},
                    "aggs": {
                        "nome": {"top_hits": {"size": 1}},
                        "documento": {"reverse_nested": {}, "aggs": {"valor": {"sum": {"field": "precoContratual"}}}},
                    },
                },
            },
        },
        "cpvs": {
            "nested": {"path": "cpv"},
            "aggs": {
                "por_codigo": {
                    "terms": {"field": "cpv.code", "size": 400, "missing": UNSPECIFIED_LABEL},
                    "aggs": {"documento": {"reverse_nested": {}, "aggs": {"valor": {"sum": {"field": "precoContratual"}}}}},
                }
            },
        },
        "anos": {
            # `Ano` e `precoContratual` são campos do documento: aqui **não** há
            # `reverse_nested` (só é válido dentro de um `nested` — o ES recusa
            # «Reverse nested aggregation can only be used inside a nested aggregation»).
            "terms": {"field": "Ano", "size": anos, "order": {"_key": "asc"}},
            "aggs": {"valor": {"sum": {"field": "precoContratual"}}},
        },
        "procedimentos": {"terms": {"field": campo_procedimento, "size": 10}},
    }


def metricas_empresas(
    escopo_def: Dict[str, Any],
    nifs: Sequence[str],
    *,
    es: Optional[Elasticsearch] = None,
    entidades: Optional[int] = None,
    cpvs: Optional[int] = None,
) -> Dict[str, Dict[str, Any]]:
    """Métricas de cada empresa (como adjudicatária) num `msearch` — uma consulta por NIF."""
    config = parametros()
    limite_entidades = int(entidades or config["entidades_por_empresa"])
    limite_cpvs = int(cpvs or config["cpvs_por_empresa"])
    campo_procedimento, runtime = lz._target_agregavel("tipoprocedimento", es)
    pedidos: List[Dict[str, Any]] = []
    for nif in nifs:
        filtros = json.loads(json.dumps(escopo_def["query"]))
        filtros["bool"]["filter"] = list(filtros["bool"].get("filter") or []) + [
            {"nested": {"path": "adjudicatarios.parsed", "query": {"term": {"adjudicatarios.parsed.nif": nif}}}}
        ]
        pedidos.append(
            lz._com_runtime(
                {
                    "size": 0,
                    "track_total_hits": True,
                    "query": filtros,
                    "aggs": _aggs_empresa(campo_procedimento, nif, entidades=limite_entidades, cpvs=limite_cpvs, anos=int(config["anos_por_empresa"])),
                },
                runtime,
            )
        )
    respostas = lz._msearch(pedidos, es=es)
    saida: Dict[str, Dict[str, Any]] = {}
    for nif, resposta in zip(nifs, respostas):
        if not isinstance(resposta, dict) or resposta.get("error"):
            saida[nif] = {"erro": (resposta or {}).get("error") if isinstance(resposta, dict) else "sem resposta"}
            continue
        aggs = resposta.get("aggregations") or {}
        valor = lz._num((aggs.get("valor") or {}).get("value"))
        contratos = int(lz._num(((resposta.get("hits") or {}).get("total") or {}).get("value")))
        percentis = aggs.get("percentis") or {}
        if isinstance(percentis.get("values"), dict):
            percentis = percentis["values"]
        entidades_lista: List[Dict[str, Any]] = []
        for balde in ((aggs.get("entidades") or {}).get("por_nif") or {}).get("buckets") or []:
            valor_entidade = lz._num((balde.get("documento") or {}).get("valor", {}).get("value"))
            entidades_lista.append(
                {
                    "nif": None if balde.get("key") == UNSPECIFIED_LABEL else balde.get("key"),
                    "nome": lz._nome_de_hits(balde) or str(balde.get("key") or UNSPECIFIED_LABEL),
                    "valor": valor_entidade,
                    "contratos": int(lz._num(balde.get("doc_count"))),
                    "quota": (valor_entidade / valor) if valor > 0 else 0.0,
                }
            )
        entidades_lista.sort(key=lambda item: item["valor"], reverse=True)
        por_classe: Dict[str, Dict[str, Any]] = {}
        for balde in ((aggs.get("cpvs") or {}).get("por_codigo") or {}).get("buckets") or []:
            classe = lz._classe_cpv(balde.get("key"))
            valor_cpv = lz._num((balde.get("documento") or {}).get("valor", {}).get("value"))
            registo = por_classe.setdefault(
                classe,
                {"classe": classe, "divisao": lz._divisao_cpv(balde.get("key")), "valor": 0.0, "contratos": 0},
            )
            registo["valor"] += valor_cpv
            registo["contratos"] += int(lz._num(balde.get("doc_count")))
        cpvs_lista = sorted(por_classe.values(), key=lambda item: item["valor"], reverse=True)[:limite_cpvs]
        for registo in cpvs_lista:
            registo["quota"] = (registo["valor"] / valor) if valor > 0 else 0.0
        anos_lista = [
            (balde.get("key"), lz._num((balde.get("valor") or {}).get("value")))
            for balde in ((aggs.get("anos") or {}).get("buckets") or [])
        ]
        procedimentos = ((aggs.get("procedimentos") or {}).get("buckets")) or []
        sem_concurso = sum(
            lz._num(balde.get("doc_count"))
            for balde in procedimentos
            if lz._fold(balde.get("key")) in ("", "ajuste direto", "consulta previa", "contratacao excluida")
            or any(lz._fold(balde.get("key")).startswith(prefixo) for prefixo in lz.AJUSTE_DIRETO_PREFIXOS)
        )
        dependencia = indice_dependencia([item["valor"] for item in entidades_lista])
        # Nome próprio da empresa (o rótulo do maior comprador não serve).
        hits_proprios = (((aggs.get("eu") or {}).get("proprio") or {}).get("nome") or {}).get("hits") or {}
        nome_proprio = ""
        for hit in hits_proprios.get("hits") or []:
            fonte = hit.get("_source") or {}
            nome_proprio = str(fonte.get("nome") or "").strip()
            if nome_proprio:
                break
        saida[nif] = {
            "nif": nif,
            "nome": nome_proprio or None,
            "valor": valor,
            "valor_efetivo": lz._num((aggs.get("valor_efetivo") or {}).get("value")),
            "contratos": contratos,
            "valor_mediano": lz._num(percentis.get("50.0")),
            "valor_p90": lz._num(percentis.get("90.0")),
            "entidades": entidades_lista,
            "entidades_distintas": int(lz._num((aggs.get("entidades") or {}).get("distintas", {}).get("value"))),
            "cpvs": cpvs_lista,
            "anos": anos_lista,
            "evolucao": evolucao_anual(anos_lista),
            "dependencia": dependencia,
            "taxa_sem_concurso": (sem_concurso / contratos) if contratos else 0.0,
            "procedimentos": [{"procedimento": balde.get("key"), "contratos": int(lz._num(balde.get("doc_count")))} for balde in procedimentos],
        }
    return saida


def empresas_do_mercado(
    escopo_def: Dict[str, Any],
    *,
    limite: Optional[int] = None,
    es: Optional[Elasticsearch] = None,
) -> List[Dict[str, Any]]:
    """Empresas (adjudicatárias) do escopo, por valor — o universo do mercado."""
    return lz._topo_por_papel(escopo_def, "adjudicatario", int(limite or parametros()["top_empresas"]), es=es)


# ---------------------------------------------------------------------------
# 1. Mercados comparáveis (CPV × CAE × período)
# ---------------------------------------------------------------------------
def mercados(
    escopo_def: Dict[str, Any],
    *,
    top: Optional[int] = None,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Define os mercados comparáveis: uma classe de CPV + as empresas com CAE compatível.

    Para cada uma das maiores classes de CPV do escopo (com os seus fornecedores
    e quotas, do cruzamento já usado na página Lorenz) junta-se o CAE das
    empresas, calcula-se a compatibilidade e mede-se a **cobertura de CAE** — que
    é o limite honesto deste modelo: sem CAE no registo não se afirma atividade.
    """
    config = parametros()
    limite = int(top or config["top_mercados"])
    cpvs = lz.matriz_cpv(escopo_def, top_cpvs=limite, es=es)
    classes = cpvs.get("classes") or []
    nifs = sorted({str(f.get("nif")) for classe in classes for f in (classe.get("fornecedores") or []) if f.get("nif")})
    registos = cae_por_nif(nifs, es=es)
    tabela = regras_cae_cpv()
    saida: List[Dict[str, Any]] = []
    for classe in classes:
        fornecedores = classe.get("fornecedores") or []
        empresas: List[Dict[str, Any]] = []
        for fornecedor in fornecedores:
            registo = registos.get(str(fornecedor.get("nif")))
            caes = list(registo.get("caes") or []) if registo else []
            compat = compatibilidade_empresa(caes, classe.get("classe"), regras=tabela)
            empresas.append(
                {
                    "nif": fornecedor.get("nif"),
                    "nome": fornecedor.get("nome"),
                    "valor": lz._num(fornecedor.get("valor")),
                    "contratos": int(lz._num(fornecedor.get("contratos"))),
                    "quota": lz._num(fornecedor.get("quota")),
                    "cae_principal": registo.get("cae_principal") if registo else None,
                    "cae_label": registo.get("cae_principal_label") if registo else None,
                    "caes": caes,
                    "compatibilidade": compat.get("grau"),
                    "compatibilidade_score": compat.get("score"),
                    "compatibilidade_motivo": compat.get("motivo"),
                }
            )
        conhecidos = [empresa for empresa in empresas if empresa["cae_principal"]]
        compativeis = [empresa for empresa in empresas if empresa["compatibilidade"] in ("alta", "média-alta", "média")]
        valor_mercado = sum(empresa["valor"] for empresa in empresas)
        valor_compativel = sum(empresa["valor"] for empresa in compativeis)
        cae_contagem: Dict[str, Dict[str, Any]] = {}
        for empresa in conhecidos:
            chave = str(empresa["cae_principal"])
            registo = cae_contagem.setdefault(chave, {"cae": chave, "label": empresa["cae_label"], "empresas": 0, "valor": 0.0})
            registo["empresas"] += 1
            registo["valor"] += empresa["valor"]
        saida.append(
            {
                "id": f"cpv:{classe.get('classe')}",
                "cpv_classe": classe.get("classe"),
                "cpv_divisao": classe.get("divisao"),
                "valor": lz._num(classe.get("valor")),
                "contratos": int(lz._num(classe.get("contratos"))),
                "compradores": int(lz._num(classe.get("compradores"))),
                "empresas": empresas,
                "empresas_analisadas": len(empresas),
                "empresas_com_cae": len(conhecidos),
                "empresas_compativeis": len(compativeis),
                "cobertura_cae": (len(conhecidos) / len(empresas)) if empresas else 0.0,
                "cobertura_valor_compativel": (valor_compativel / valor_mercado) if valor_mercado > 0 else 0.0,
                "hhi": lz._num(classe.get("hhi")),
                "quota_lider": lz._num(classe.get("quota_top1")),
                "lider": (empresas[0] if empresas else None),
                "caes_dominantes": sorted(cae_contagem.values(), key=lambda item: item["valor"], reverse=True)[:5],
                "anos": {"de": escopo_def.get("ano_de"), "ate": escopo_def.get("ano_ate")},
                "qualidade": _qualidade_mercado(len(empresas), len(conhecidos)),
            }
        )
    saida.sort(key=lambda item: item["valor"], reverse=True)
    return {
        "mercados": saida,
        "total_documentos": cpvs.get("total_documentos"),
        "notas": [
            "Um mercado é definido por CPV semelhante + CAE compatível + período; a mesma empresa pode pertencer a vários mercados.",
            "A cobertura de CAE é medida por mercado: quando é baixa, a comparação é indicativa (o registo não tem CAE para essas empresas).",
        ],
    }


def _qualidade_mercado(empresas: int, com_cae: int) -> Dict[str, Any]:
    cobertura = (com_cae / empresas) if empresas else 0.0
    if empresas >= 8 and cobertura >= 0.7:
        grau = "boa"
    elif empresas >= 4 and cobertura >= 0.4:
        grau = "aceitável"
    else:
        grau = "limitada"
    return {
        "grau": grau,
        "empresas": empresas,
        "com_cae": com_cae,
        "cobertura": cobertura,
        "motivo": (
            f"{empresas} empresas, {com_cae} com CAE no registo"
            + ("; poucas empresas — leitura indicativa" if empresas < 4 else "")
        ),
    }


# ---------------------------------------------------------------------------
# 2. Benchmark entre empresas do mesmo mercado
# ---------------------------------------------------------------------------
def benchmark(
    escopo_def: Dict[str, Any],
    *,
    nifs: Optional[Sequence[str]] = None,
    cpv: Optional[str] = None,
    limite: Optional[int] = None,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Compara empresas dentro do mesmo mercado (CPV + CAE + período).

    Devolve, por empresa: contratos, valor acumulado, entidades distintas, maior
    entidade e respetiva quota, `D_i` (HHI dos compradores), evolução anual,
    CPV principal, CAE e **grau de compatibilidade** com o mercado, quota `P_i`
    e posição relativa — com evidências e avisos.
    """
    config = parametros()
    limite_empresas = int(limite or config["top_empresas"])
    escopo_mercado = escopo_def
    if cpv:
        # Restringe o mercado ao CPV pedido (prefixo), mantendo o resto do escopo.
        escopo_mercado = lz.escopo(
            area=escopo_def.get("area"),
            cpv=str(cpv),
            ano_de=escopo_def.get("ano_de"),
            ano_ate=escopo_def.get("ano_ate"),
            regiao=escopo_def.get("regiao"),
            nif=escopo_def.get("nif"),
            valor_min=escopo_def.get("valor_min"),
            valor_max=escopo_def.get("valor_max"),
            texto=escopo_def.get("texto"),
        )
    lista_nifs = [str(nif) for nif in (nifs or []) if nif]
    if not lista_nifs:
        lista_nifs = [str(item.get("nif")) for item in empresas_do_mercado(escopo_mercado, limite=limite_empresas, es=es) if item.get("nif")]
    if not lista_nifs:
        return {"erro": "sem empresas no escopo escolhido", "empresas": [], "mercado": {}}

    metricas = metricas_empresas(escopo_mercado, lista_nifs, es=es, cpvs=config["cpvs_por_empresa"])
    registos = cae_por_nif(lista_nifs, es=es)
    tabela = regras_cae_cpv()

    mercado_valor = sum(lz._num(metrica.get("valor")) for metrica in metricas.values() if isinstance(metrica, dict))
    mercado_contratos = sum(int(lz._num(metrica.get("contratos"))) for metrica in metricas.values() if isinstance(metrica, dict))
    cpv_referencia = cpv or _cpv_dominante(metricas)

    empresas: List[Dict[str, Any]] = []
    for nif in lista_nifs:
        metrica = metricas.get(nif) or {}
        registo = registos.get(nif) or {}
        caes = list(registo.get("caes") or [])
        compat = compatibilidade_empresa(caes, cpv_referencia, regras=tabela)
        maior = (metrica.get("entidades") or [None])[0]
        principal = (metrica.get("cpvs") or [None])[0]
        dependencia = metrica.get("dependencia") or {}
        evolucao = metrica.get("evolucao") or {}
        alertas = _alertas_empresa(metrica, compat, config)
        empresas.append(
            {
                "nif": nif,
                "nome": metrica.get("nome") or registo.get("nome_registo") or nif,
                "contratos": int(lz._num(metrica.get("contratos"))),
                "valor": lz._num(metrica.get("valor")),
                "valor_mediano": lz._num(metrica.get("valor_mediano")),
                "valor_p90": lz._num(metrica.get("valor_p90")),
                "quota": indice_posicionamento(lz._num(metrica.get("valor")), mercado_valor),
                "entidades_distintas": int(lz._num(metrica.get("entidades_distintas"))),
                "maior_entidade": maior,
                "dependencia": dependencia,
                "evolucao": evolucao,
                "cpv_principal": principal,
                "n_cpvs": len(metrica.get("cpvs") or []),
                "cae_principal": registo.get("cae_principal"),
                "cae_label": registo.get("cae_principal_label"),
                "caes": caes,
                "compatibilidade": compat.get("grau"),
                "compatibilidade_score": compat.get("score"),
                "compatibilidade_motivo": compat.get("motivo"),
                "taxa_sem_concurso": lz._num(metrica.get("taxa_sem_concurso")),
                "alertas": alertas,
                "perfil": _perfil(metrica, compat, config),
                "erro": metrica.get("erro"),
            }
        )
    empresas.sort(key=lambda item: item["valor"], reverse=True)
    for posicao, empresa in enumerate(empresas, start=1):
        empresa["posicao"] = posicao

    compativeis = [empresa for empresa in empresas if empresa["compatibilidade"] in ("alta", "média-alta", "média")]
    avisos: List[str] = []
    sem_cae = [empresa["nome"] for empresa in empresas if not empresa["cae_principal"]]
    if sem_cae:
        avisos.append(
            f"{len(sem_cae)} de {len(empresas)} empresas não têm CAE no registo: para essas, a compatibilidade é «desconhecida» "
            "(não se presume atividade)."
        )
    if len(empresas) < 4:
        avisos.append("Menos de 4 empresas no mercado: leitura indicativa, não representativa.")
    if cpv_referencia:
        avisos.append(f"Mercado de referência: CPV {cpv_referencia} (compatibilidade medida contra este CPV).")

    return {
        "mercado": {
            "cpv": cpv_referencia,
            "cpv_label": next((empresa["cpv_principal"] for empresa in empresas if empresa.get("cpv_principal")), None),
            "area": escopo_def.get("area"),
            "area_label": escopo_def.get("area_label"),
            "ano_de": escopo_def.get("ano_de"),
            "ano_ate": escopo_def.get("ano_ate"),
            "regiao": escopo_def.get("regiao"),
            "valor": mercado_valor,
            "contratos": mercado_contratos,
            "empresas": len(empresas),
            "empresas_compativeis": len(compativeis),
            "hhi": sum(empresa["quota"] ** 2 for empresa in empresas),
            "quota_lider": empresas[0]["quota"] if empresas else 0.0,
            "mediana_valor": float(np.median([empresa["valor"] for empresa in empresas])) if empresas else 0.0,
            "cobertura_cae": (len([empresa for empresa in empresas if empresa["cae_principal"]]) / len(empresas)) if empresas else 0.0,
        },
        "empresas": empresas,
        "avisos": avisos,
        "limites": {
            "entidades_por_empresa": config["entidades_por_empresa"],
            "cpvs_por_empresa": config["cpvs_por_empresa"],
            "nota": "Cada empresa é medida com uma consulta própria (msearch), com os topos configurados; o resto fica fora do cálculo.",
        },
        "notas": [
            "P_i é a quota do valor publicado dentro deste mercado — não é quota de mercado total (não inclui compra privada nem todas as compras públicas).",
            "D_i é o HHI da carteira de compradores: concentração não é, por si só, dependência económica.",
            "A compatibilidade CPV↔CAE vem de uma tabela de regras (grau alta/média/baixa) — é indicativa.",
        ],
    }


def _cpv_dominante(metricas: Dict[str, Dict[str, Any]]) -> Optional[str]:
    contagem: Dict[str, float] = {}
    for metrica in metricas.values():
        if not isinstance(metrica, dict):
            continue
        for cpv in metrica.get("cpvs") or []:
            contagem[cpv["classe"]] = contagem.get(cpv["classe"], 0.0) + lz._num(cpv.get("valor"))
    if not contagem:
        return None
    return max(contagem.items(), key=lambda par: par[1])[0]


def _alertas_empresa(metrica: Dict[str, Any], compat: Dict[str, Any], config: Dict[str, Any]) -> List[Dict[str, str]]:
    alertas: List[Dict[str, str]] = []
    dependencia = metrica.get("dependencia") or {}
    if lz._num(dependencia.get("maior_quota")) >= float(config["limiar_dependencia"]):
        alertas.append(
            {
                "tipo": "dependencia_de_comprador",
                "severidade": "alta" if lz._num(dependencia.get("maior_quota")) >= 0.7 else "média",
                "detalhe": f"{lz._num(dependencia.get('maior_quota')) * 100:.0f} % do valor vem de um só comprador",
            }
        )
    if lz._num(metrica.get("taxa_sem_concurso")) >= 0.5:
        alertas.append(
            {
                "tipo": "sem_concurso",
                "severidade": "média",
                "detalhe": f"{lz._num(metrica.get('taxa_sem_concurso')) * 100:.0f} % dos contratos sem procedimento competitivo registado",
            }
        )
    if compat.get("grau") == "desconhecida":
        alertas.append({"tipo": "cae_desconhecido", "severidade": "baixa", "detalhe": compat.get("motivo") or "sem CAE compatível"})
    evolucao = metrica.get("evolucao") or {}
    if evolucao.get("variacao") is not None and float(evolucao["variacao"]) <= float(config["limiar_queda"]):
        alertas.append(
            {
                "tipo": "queda_de_atividade",
                "severidade": "média",
                "detalhe": f"variação de {float(evolucao['variacao']) * 100:.0f} % entre {evolucao['anos'][0]} e {evolucao['anos'][-1]}",
            }
        )
    if len(metrica.get("cpvs") or []) == 1:
        alertas.append({"tipo": "mercado_unico", "severidade": "baixa", "detalhe": "só atua numa classe de CPV neste escopo"})
    return alertas


def _perfil(metrica: Dict[str, Any], compat: Dict[str, Any], config: Dict[str, Any]) -> str:
    """Frase curta que resume a posição (nunca juízos absolutos)."""
    entidades = int(lz._num(metrica.get("entidades_distintas")))
    dependencia = lz._num((metrica.get("dependencia") or {}).get("maior_quota"))
    compativeis = compat.get("grau")
    parte = []
    if dependencia >= float(config["limiar_dependencia"]):
        parte.append(f"depende de um comprador ({dependencia * 100:.0f} % do valor)")
    elif entidades >= 5:
        parte.append(f"carteira diversificada ({entidades} compradores)")
    if compativeis == "alta":
        parte.append("CAE alinhado com o CPV")
    elif compativeis == "desconhecida":
        parte.append("CAE desconhecido ou sem regra aplicável")
    else:
        parte.append(f"CAE com compatibilidade {compativeis}")
    evolucao = metrica.get("evolucao") or {}
    if evolucao.get("cagr") is not None:
        parte.append(f"evolução {float(evolucao['cagr']) * 100:+.0f} %/ano")
    return "; ".join(parte) if parte else "sem dados suficientes para perfil"


# ---------------------------------------------------------------------------
# 3. Dependências recíprocas
# ---------------------------------------------------------------------------
def dependencias(
    escopo_def: Dict[str, Any],
    *,
    nifs: Optional[Sequence[str]] = None,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Dependência nos dois sentidos: empresa→entidades e entidade→fornecedores.

    - Empresa→entidades: `D_i` (HHI da carteira) e o maior comprador.
    - Entidade→fornecedores: por CPV, quanto do valor da entidade está num
      fornecedor, e que **alternativas observadas** existem (contratos de outros
      fornecedores no mesmo CPV para essa entidade).
    """
    lista_nifs = [str(nif) for nif in (nifs or []) if nif]
    if not lista_nifs:
        lista_nifs = [str(item.get("nif")) for item in empresas_do_mercado(escopo_def, es=es) if item.get("nif")]
    metricas = metricas_empresas(escopo_def, lista_nifs, es=es)
    por_empresa = [
        {
            "nif": nif,
            "nome": metrica.get("nome") or nif,
            "valor": lz._num(metrica.get("valor")),
            "contratos": int(lz._num(metrica.get("contratos"))),
            "entidades_distintas": int(lz._num(metrica.get("entidades_distintas"))),
            "dependencia": metrica.get("dependencia"),
            "maior_entidade": (metrica.get("entidades") or [None])[0],
            "carteira": metrica.get("entidades") or [],
        }
        for nif, metrica in metricas.items()
        if isinstance(metrica, dict)
    ]
    por_empresa.sort(key=lambda item: lz._num((item.get("dependencia") or {}).get("hhi")), reverse=True)

    # Lado das entidades: reutiliza o cruzamento já usado na página Lorenz.
    dados = lz.matriz_dependencia(escopo_def, es=es)
    entidades: List[Dict[str, Any]] = []
    for comprador in dados.get("compradores") or []:
        fornecedores = comprador.get("fornecedores") or []
        topo = fornecedores[0] if fornecedores else None
        classes = {cpv.get("classe"): cpv for cpv in (comprador.get("cpvs") or [])}
        alternativas = [f for f in fornecedores[1:4]]
        entidades.append(
            {
                "nif": comprador.get("nif"),
                "nome": comprador.get("nome"),
                "valor": lz._num(comprador.get("valor")),
                "contratos": int(lz._num(comprador.get("contratos"))),
                "fornecedores": len(fornecedores),
                "dependencia": {
                    "hhi": lz._num(comprador.get("hhi_top")),
                    "maior_quota": lz._num(comprador.get("quota_top1")),
                    "n_entidades": len(fornecedores),
                },
                "maior_fornecedor": topo,
                "alternativas": alternativas,
                "cpv_principal": max(classes.values(), key=lambda item: lz._num(item.get("valor"))) if classes else None,
                "cpvs": comprador.get("cpvs") or [],
                "critico": lz._num(comprador.get("quota_top1")) >= 0.6,
            }
        )
    entidades.sort(key=lambda item: lz._num(item["dependencia"]["maior_quota"]), reverse=True)
    return {
        "empresas": por_empresa,
        "entidades": entidades,
        "totais": {
            "empresas": len(por_empresa),
            "entidades": len(entidades),
            "entidades_criticas": len([entidade for entidade in entidades if entidade["critico"]]),
            "empresas_dependentes": len(
                [empresa for empresa in por_empresa if lz._num((empresa.get("dependencia") or {}).get("maior_quota")) >= parametros()["limiar_dependencia"]]
            ),
        },
        "notas": [
            "Concentração não é dependência económica absoluta: faltam receitas privadas e outros mercados da empresa.",
            "Nas entidades, o «maior fornecedor» e as alternativas são do **escopo escolhido** (CPV/anos), não de toda a despesa da entidade.",
            "Partilhar clientes ou fornecedores é uma relação observada — não é prova de coordenação nem de irregularidade.",
        ],
    }


# ---------------------------------------------------------------------------
# 4. Grafo temporal empresa → contrato → entidade → CPV → CAE
# ---------------------------------------------------------------------------
def grafo_temporal(
    escopo_def: Dict[str, Any],
    *,
    nifs: Optional[Sequence[str]] = None,
    contratos: int = 24,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Grafo datado com os cinco tipos de nós do modelo (para o `GraphCanvas`)."""
    lista_nifs = [str(nif) for nif in (nifs or []) if nif]
    if not lista_nifs:
        lista_nifs = [str(item.get("nif")) for item in empresas_do_mercado(escopo_def, limite=8, es=es) if item.get("nif")]
    metricas = metricas_empresas(escopo_def, lista_nifs, es=es)
    registos = cae_por_nif(lista_nifs, es=es)

    filtros = json.loads(json.dumps(escopo_def["query"]))
    filtros["bool"]["filter"] = list(filtros["bool"].get("filter") or []) + [
        {"nested": {"path": "adjudicatarios.parsed", "query": {"terms": {"adjudicatarios.parsed.nif": lista_nifs}}}}
    ]
    resposta = lz._pesquisar(
        {
            "size": min(int(contratos), 50),
            "track_total_hits": True,
            "query": filtros,
            "sort": [{"precoContratual": {"order": "desc"}}],
            "_source": ["idcontrato", "objectoContrato", "precoContratual", "Ano", "dataCelebracaoContrato", "dataFechoContrato", "cpv", "adjudicantes", "adjudicatarios"],
        },
        es=es,
    )

    nos: Dict[str, Dict[str, Any]] = {}
    arestas: List[Dict[str, Any]] = []
    tabela = regras_cae_cpv()

    for nif in lista_nifs:
        metrica = metricas.get(nif) or {}
        registo = registos.get(nif) or {}
        principal = (metrica.get("cpvs") or [None])[0]
        id_empresa = f"emp:{nif}"
        nos[id_empresa] = {
            "id": id_empresa,
            "key": nif,
            "label": metrica.get("nome") or registo.get("nome_registo") or nif,
            "dimension": "empresa",
            "type": "concorrente",
            "role": "adjudicatário",
            "count": int(lz._num(metrica.get("contratos"))),
            "total_value": lz._num(metrica.get("valor")),
            "value": lz._num(metrica.get("valor")),
            "cae": registo.get("cae_principal"),
            "cae_label": registo.get("cae_principal_label"),
            "compatibilidade": compatibilidade_empresa(registo.get("caes") or [], (principal or {}).get("classe"), regras=tabela).get("grau"),
        }
        for cae in registo.get("caes") or []:
            id_cae = f"cae:{cae}"
            nos.setdefault(
                id_cae,
                {
                    "id": id_cae,
                    "key": cae,
                    "label": _label_cae(cae) or f"CAE {cae}",
                    "dimension": "cae",
                    "type": "outra",
                    "role": "atividade",
                    "count": 1,
                    "total_value": 0.0,
                    "value": 0.0,
                },
            )
            arestas.append(
                {
                    "source": id_cae,
                    "target": id_empresa,
                    "count": 1,
                    "value": lz._num(metrica.get("valor")),
                    "relacao": "atividade registada",
                    "quota": None,
                }
            )
        for cpv in (metrica.get("cpvs") or [])[:5]:
            id_cpv = f"cpv:{cpv['classe']}"
            nos.setdefault(
                id_cpv,
                {
                    "id": id_cpv,
                    "key": cpv["classe"],
                    "label": f"CPV {cpv['classe']}",
                    "dimension": "cpv",
                    "type": "cpv",
                    "role": "mercado",
                    "count": 0,
                    "total_value": 0.0,
                    "value": 0.0,
                },
            )
            nos[id_cpv]["count"] += int(lz._num(cpv.get("contratos")))
            nos[id_cpv]["total_value"] += lz._num(cpv.get("valor"))
            nos[id_cpv]["value"] = nos[id_cpv]["total_value"]
            arestas.append(
                {
                    "source": id_empresa,
                    "target": id_cpv,
                    "count": int(lz._num(cpv.get("contratos"))),
                    "value": lz._num(cpv.get("valor")),
                    "relacao": "vende neste mercado",
                    "quota": lz._num(cpv.get("quota")),
                }
            )
        for entidade in (metrica.get("entidades") or [])[:6]:
            if not entidade.get("nif"):
                continue
            id_entidade = f"ent:{entidade['nif']}"
            nos.setdefault(
                id_entidade,
                {
                    "id": id_entidade,
                    "key": str(entidade["nif"]),
                    "label": entidade.get("nome") or str(entidade["nif"]),
                    "dimension": "entidade",
                    "type": "entidade",
                    "role": "comprador",
                    "count": 0,
                    "total_value": 0.0,
                    "value": 0.0,
                },
            )
            arestas.append(
                {
                    "source": id_empresa,
                    "target": id_entidade,
                    "count": int(lz._num(entidade.get("contratos"))),
                    "value": lz._num(entidade.get("valor")),
                    "relacao": "contrata com",
                    "quota": lz._num(entidade.get("quota")),
                }
            )

    for hit in ((resposta.get("hits") or {}).get("hits") or []):
        fonte = hit.get("_source") or {}
        id_contrato = str(fonte.get("idcontrato") or hit.get("_id") or "")
        if not id_contrato:
            continue
        id_no = f"ctr:{id_contrato}"
        adjudicatario = lz._nome_parte(fonte.get("adjudicatarios"))
        comprador = lz._nome_parte(fonte.get("adjudicantes"))
        cpv = (fonte.get("cpv") or [{}])[0] if isinstance(fonte.get("cpv"), list) else (fonte.get("cpv") or {})
        nos[id_no] = {
            "id": id_no,
            "key": id_contrato,
            "label": (fonte.get("objectoContrato") or f"Contrato {id_contrato}")[:80],
            "dimension": "contrato",
            "type": "outra",
            "role": "contrato",
            "count": 1,
            "total_value": lz._num(fonte.get("precoContratual")),
            "value": lz._num(fonte.get("precoContratual")),
            "data": fonte.get("dataCelebracaoContrato") or fonte.get("dataFechoContrato"),
            "fim": fonte.get("dataFechoContrato"),
            "empresa": adjudicatario,
            "entidade": comprador,
            "cpv": cpv.get("code") if isinstance(cpv, dict) else None,
        }
        for nif in (_nif_de_parte(fonte.get("adjudicatarios")),):
            if nif and f"emp:{nif}" in nos:
                arestas.append({"source": id_no, "target": f"emp:{nif}", "count": 1, "value": lz._num(fonte.get("precoContratual")), "relacao": "adjudicado a", "quota": None})
        nif_comprador = _nif_de_parte(fonte.get("adjudicantes"))
        if nif_comprador and f"ent:{nif_comprador}" in nos:
            arestas.append({"source": id_no, "target": f"ent:{nif_comprador}", "count": 1, "value": lz._num(fonte.get("precoContratual")), "relacao": "comprado por", "quota": None})

    return {
        "nodes": list(nos.values()),
        "edges": arestas,
        "meta": {
            "dimension_a": "empresa",
            "dimension_b": "cpv",
            "metric": "valor",
            "documents_scanned": int(lz._num(((resposta.get("hits") or {}).get("total") or {}).get("value"))),
            "nodes_returned": len(nos),
            "edges_returned": len(arestas),
            "tipos": ["empresa", "contrato", "entidade", "cpv", "cae"],
            "notas": [
                "As arestas empresa→CPV e empresa→entidade trazem valor acumulado, contratos e quota (datas do primeiro/último contrato).",
                "Os nós de contrato são os maiores por valor do escopo (amostra), para o desenho ficar legível.",
            ],
        },
    }


def _nif_de_parte(parte: Any) -> Optional[str]:
    if isinstance(parte, dict):
        parsed = parte.get("parsed")
        if isinstance(parsed, list):
            for entrada in parsed:
                if isinstance(entrada, dict) and entrada.get("nif"):
                    return str(entrada["nif"])
        if parte.get("nif"):
            return str(parte["nif"])
    return None


# ---------------------------------------------------------------------------
# 5. Cenários (World Model) + sensibilidade (Lorenz)
# ---------------------------------------------------------------------------
def _cotas_monte_carlo(
    forcas: Dict[str, float],
    *,
    concursos: int,
    semente: int,
) -> Dict[str, Dict[str, float]]:
    """Simula N concursos: em cada um, a probabilidade de ganhar é proporcional à força.

    Modelo declarado: escolha multinomial (uma empresa ganha cada concurso).
    Não modela preços individuais — o portal só publica o adjudicatário.
    """
    aleatorio = random.Random(semente)
    nomes = list(forcas)
    pesos = [max(0.0, float(forcas[nome])) for nome in nomes]
    total = sum(pesos)
    if total <= 0 or not nomes:
        return {}
    acumuladas: List[float] = []
    soma = 0.0
    for peso in pesos:
        soma += peso / total
        acumuladas.append(soma)
    vitorias = {nome: 0 for nome in nomes}
    for _ in range(max(int(concursos), 1)):
        sorteio = aleatorio.random()
        for indice, limite in enumerate(acumuladas):
            if sorteio <= limite:
                vitorias[nomes[indice]] += 1
                break
        else:  # pragma: no cover — só por segurança numérica
            vitorias[nomes[-1]] += 1
    return {
        nome: {"vitorias": vitorias[nome], "quota": vitorias[nome] / max(int(concursos), 1)}
        for nome in nomes
    }


def cenario_perda_maior_comprador(
    metrica: Dict[str, Any],
    *,
    nome: Optional[str] = None,
) -> Dict[str, Any]:
    """Empresa perde o seu maior comprador: volume, concentração residual e nova quota."""
    entidades = metrica.get("entidades") or []
    if not entidades:
        return {"evento": "perda_maior_comprador", "disponivel": False, "motivo": "sem compradores no escopo"}
    maior = entidades[0]
    restantes = entidades[1:]
    valor_total = lz._num(metrica.get("valor"))
    perdido = lz._num(maior.get("valor"))
    novo_total = max(0.0, valor_total - perdido)
    dependencia_antes = indice_dependencia([lz._num(item.get("valor")) for item in entidades])
    dependencia_depois = indice_dependencia([lz._num(item.get("valor")) for item in restantes])
    return {
        "evento": "perda_maior_comprador",
        "disponivel": True,
        "alvo": nome or metrica.get("nif"),
        "medicao": {
            "comprador": maior.get("nome"),
            "valor_perdido": perdido,
            "quota_do_valor": (perdido / valor_total) if valor_total > 0 else 0.0,
            "valor_residual": novo_total,
            "variacao_valor": (-perdido / valor_total) if valor_total > 0 else None,
            "dependencia_antes": dependencia_antes,
            "dependencia_depois": dependencia_depois,
            "compradores_restantes": len(restantes),
        },
        "hipoteses": [
            "Assume-se que o comprador deixa de contratar esta empresa (não que o mercado desaparece).",
            "O valor perdido não é redistribuído por outros compradores da mesma empresa.",
        ],
        "evidencia": [{"comprador": item.get("nome"), "valor": item.get("valor"), "quota": item.get("quota")} for item in entidades[:5]],
    }


def cenario_entidade_sem_fornecedor(
    escopo_def: Dict[str, Any],
    *,
    entidade_nif: Optional[str] = None,
    fornecedor_nif: Optional[str] = None,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Entidade deixa de contratar um fornecedor: exposição por CPV e alternativas observadas."""
    dados = lz.matriz_dependencia(escopo_def, es=es)
    compradores = dados.get("compradores") or []
    if not compradores:
        return {"evento": "entidade_sem_fornecedor", "disponivel": False, "motivo": "sem compradores no escopo"}
    comprador = next((item for item in compradores if str(item.get("nif")) == str(entidade_nif)), None) if entidade_nif else compradores[0]
    if comprador is None:
        return {"evento": "entidade_sem_fornecedor", "disponivel": False, "motivo": "entidade fora do escopo"}
    fornecedores = comprador.get("fornecedores") or []
    alvo = next((item for item in fornecedores if str(item.get("nif")) == str(fornecedor_nif)), None) if fornecedor_nif else (fornecedores[0] if fornecedores else None)
    if alvo is None:
        return {"evento": "entidade_sem_fornecedor", "disponivel": False, "motivo": "fornecedor fora do escopo"}
    alternativas = [item for item in fornecedores if str(item.get("nif")) != str(alvo.get("nif"))]
    cobertura_alternativa = sum(lz._num(item.get("quota")) for item in alternativas[:3])
    return {
        "evento": "entidade_sem_fornecedor",
        "disponivel": True,
        "alvo": {"entidade": comprador.get("nome"), "fornecedor": alvo.get("nome")},
        "medicao": {
            "valor_da_entidade": lz._num(comprador.get("valor")),
            "valor_do_fornecedor": lz._num(alvo.get("valor")),
            "exposicao": lz._num(alvo.get("quota")),
            "alternativas_no_escopo": [
                {"nome": item.get("nome"), "quota": lz._num(item.get("quota")), "valor": lz._num(item.get("valor"))} for item in alternativas[:5]
            ],
            "cobertura_alternativa_3": cobertura_alternativa,
            "dificuldade_substituicao": max(0.0, 1.0 - cobertura_alternativa),
            "cpvs": comprador.get("cpvs") or [],
        },
        "hipoteses": [
            "A exposição é a quota do fornecedor no valor da entidade **no escopo** (CPV/anos), não na despesa total da entidade.",
            "A dificuldade de substituição usa as alternativas que já têm contratos no mesmo escopo.",
        ],
        "evidencia": [
            {"fornecedor": item.get("nome"), "valor": item.get("valor"), "contratos": item.get("contratos")} for item in fornecedores[:5]
        ],
    }


def cenario_novo_concorrente(
    escopo_def: Dict[str, Any],
    *,
    forca_relativa: float = 1.0,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Entrada de um concorrente novo com a força de um par médio do mercado."""
    benchmark_dados = benchmark(escopo_def, es=es)
    empresas = benchmark_dados.get("empresas") or []
    if not empresas:
        return {"evento": "novo_concorrente", "disponivel": False, "motivo": "sem empresas no mercado"}
    config = parametros()
    forcas = {
        str(empresa["nif"]): lz._num(empresa["valor"]) * (1.0 + config["peso_especializacao"] * lz._num((empresa.get("cpv_principal") or {}).get("quota")))
        for empresa in empresas
    }
    mediana = float(np.median(list(forcas.values()))) if forcas else 0.0
    forcas["novo_concorrente"] = mediana * max(0.0, float(forca_relativa))
    resultado = _cotas_monte_carlo(forcas, concursos=int(config["concursos_simulados"]), semente=int(config["semente"]))
    antes = {str(empresa["nif"]): lz._num(empresa["quota"]) for empresa in empresas}
    linhas = []
    for empresa in empresas:
        nif = str(empresa["nif"])
        depois = (resultado.get(nif) or {}).get("quota", 0.0)
        linhas.append(
            {
                "nif": nif,
                "nome": empresa["nome"],
                "quota_observada": antes[nif],
                "quota_simulada": depois,
                "variacao": (depois - antes[nif]),
                "probabilidade_vitoria": (resultado.get(nif) or {}).get("quota", 0.0),
            }
        )
    entrante = resultado.get("novo_concorrente", {}).get("quota", 0.0)
    return {
        "evento": "novo_concorrente",
        "disponivel": True,
        "medicao": {
            "forca_relativa": forca_relativa,
            "forca_absoluta": forcas["novo_concorrente"],
            "forca_mediana_do_mercado": mediana,
            "quota_estimada_do_entrante": entrante,
            "empresas_afetadas": len([linha for linha in linhas if linha["variacao"] < -0.005]),
            "hhi_antes": sum(quota**2 for quota in antes.values()),
            "hhi_simulado": sum((resultado.get(nif) or {}).get("quota", 0.0) ** 2 for nif in antes) + entrante**2,
            "concursos_simulados": config["concursos_simulados"],
            "empresas": sorted(linhas, key=lambda item: item["variacao"]),
        },
        "hipoteses": [
            "Modelo declarado: em cada concurso a probabilidade de ganhar é proporcional à força histórica da empresa (multinomial).",
            "A força é o valor observado no mercado ajustado pela especialização no CPV principal; a do entrante é `força_relativa × mediana`.",
            "Não se modelam preços de proposta (o portal só publica o adjudicatário) nem barreiras de entrada técnica.",
        ],
        "notas": ["Simulação de sensibilidade: serve para comparar magnitudes, não para prever o vencedor de um concurso concreto."],
    }


def _dias_para_data(base: Optional[str], dias: float) -> Optional[str]:
    """Data ISO de `base` + `dias` (None se a base for inválida)."""
    if not base or not dias:
        return None
    texto = str(base)[:10]
    try:
        inicio = datetime.strptime(texto, "%Y-%m-%d").date()
    except ValueError:
        return None
    return (inicio + timedelta(days=int(dias))).isoformat()


def _agregar_expiracoes(
    escopo_def: Dict[str, Any],
    *,
    janela: Tuple[str, str],
    modo: str,
    amostra: int,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Contratos que terminam na janela — modo `estrito` ou `estimado`.

    - **estrito**: `dataFechoContrato` dentro da janela (o Portal só preenche este
      campo numa minoria dos contratos; a leitura é declaradamente parcial).
    - **estimado**: lê os maiores contratos cuja **celebração** está na janela alargada
      (até 10 anos antes) e calcula `celebração + prazoExecucao` (dias) em Python —
      sem `runtime` scripts no Elasticsearch, para o cálculo ser auditável e o erro
      impossível de esconder. Ignora prazos fora de [1, 3650] dias (contados em
      `prazos_ignorados`).
    """
    filtros = json.loads(json.dumps(escopo_def["query"]))
    lista = list(filtros["bool"].get("filter") or [])
    if modo == "estrito":
        lista.append({"range": {"dataFechoContrato": {"gte": janela[0], "lte": janela[1]}}})
    else:
        inicio_janela = datetime.strptime(janela[0], "%Y-%m-%d").date() - timedelta(days=3650)
        lista.append({"range": {"dataCelebracaoContrato": {"gte": inicio_janela.isoformat(), "lte": janela[1]}}})
    filtros["bool"]["filter"] = lista
    corpo = {
        "size": min(int(amostra), 500),
        "track_total_hits": True,
        "query": filtros,
        "sort": [{"precoContratual": {"order": "desc"}}],
        "_source": [
            "idcontrato",
            "objectoContrato",
            "precoContratual",
            "dataCelebracaoContrato",
            "dataFechoContrato",
            "prazoExecucao",
            "adjudicantes",
            "adjudicatarios",
        ],
        "aggs": {
            "valor": {"sum": {"field": "precoContratual"}},
        },
    }
    resposta = lz._pesquisar(corpo, es=es)
    hits = ((resposta.get("hits") or {}).get("hits")) or []
    total = int(lz._num(((resposta.get("hits") or {}).get("total") or {}).get("value")))
    valor_total = lz._num(((resposta.get("aggregations") or {}).get("valor") or {}).get("value"))

    def _nome(parte: Any) -> str:
        return lz._nome_parte(parte) or ""

    expirando: List[Dict[str, Any]] = []
    valor_lido = 0.0
    prazos_ignorados = 0
    for hit in hits:
        fonte = hit.get("_source") or {}
        valor = lz._num(fonte.get("precoContratual"))
        valor_lido += valor
        fim_explicito = (fonte.get("dataFechoContrato") or "")[:10] or None
        prazo = lz._num(fonte.get("prazoExecucao"))
        fim_calculado = None
        if not fim_explicito:
            if prazo < 1 or prazo > 3650:
                prazos_ignorados += 1
                continue
            fim_calculado = _dias_para_data(fonte.get("dataCelebracaoContrato"), prazo)
        fim = fim_explicito or fim_calculado or None
        if modo == "estrito" and not fim_explicito:
            continue
        if modo == "estimado" and fim_explicito:
            # Já contabilizado na leitura estrita (não se conta duas vezes).
            continue
        if not fim or not (janela[0] <= fim <= janela[1]):
            continue
        expirando.append(
            {
                "idcontrato": fonte.get("idcontrato") or hit.get("_id"),
                "objeto": (fonte.get("objectoContrato") or "")[:120],
                "valor": valor,
                "celebracao": (fonte.get("dataCelebracaoContrato") or "")[:10] or None,
                "fecho": fim_explicito,
                "fim_calculado": fim,
                "prazo": prazo or None,
                "adjudicatario": _nome(fonte.get("adjudicatarios")),
                "adjudicante": _nome(fonte.get("adjudicantes")),
            }
        )

    def _agregar(chave: str) -> List[Dict[str, Any]]:
        contagem: Dict[str, Dict[str, Any]] = {}
        for item in expirando:
            nome = item.get(chave) or "—"
            registo = contagem.setdefault(nome, {"nome": nome, "valor": 0.0, "contratos": 0})
            registo["valor"] += lz._num(item.get("valor"))
            registo["contratos"] += 1
        return sorted(contagem.values(), key=lambda item: item["valor"], reverse=True)[:15]

    por_mes: Dict[str, int] = {}
    for item in expirando:
        mes = str(item.get("fecho") or item.get("fim_calculado") or "")[:7]
        if mes:
            por_mes[mes] = por_mes.get(mes, 0) + 1
    return {
        "modo": modo,
        "campo": "dataFechoContrato" if modo == "estrito" else "dataCelebracaoContrato+prazoExecucao",
        "janela_alargada": modo == "estimado",
        "contratos": len(expirando),
        "valor": sum(lz._num(item["valor"]) for item in expirando),
        "empresas": _agregar("adjudicatario"),
        "entidades": _agregar("adjudicante"),
        "por_mes": [{"mes": mes, "contratos": quantidade} for mes, quantidade in sorted(por_mes.items())],
        "amostra": {
            "lidos": len(hits),
            "valor_lido": valor_lido,
            "valor_total_escopo": valor_total,
            "cobertura_valor": (valor_lido / valor_total) if valor_total > 0 else None,
            "candidatos_no_escopo": total,
            "prazos_ignorados": prazos_ignorados,
        },
        "evidencia": sorted(expirando, key=lambda item: lz._num(item["valor"]), reverse=True)[:12],
        "erro": resposta.get("erro"),
    }


def cenario_contratos_a_expirar(
    escopo_def: Dict[str, Any],
    *,
    horizonte_dias: Optional[int] = None,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Volume contratual que termina no horizonte: o que fica exposto à renovação.

    Duas leituras porque o dado é parcial: **estrita** (`dataFechoContrato`, presente
    numa minoria dos contratos) e **estimada** (celebração + `prazoExecucao`, calculada
    em Python sobre os maiores contratos candidatos, com a cobertura declarada).
    """
    config = parametros()
    dias = int(horizonte_dias or config["horizonte_expiracao_dias"])
    hoje = datetime.now(timezone.utc).date()
    limite = hoje + timedelta(days=dias)
    janela = (hoje.isoformat(), limite.isoformat())
    estrito = _agregar_expiracoes(escopo_def, janela=janela, modo="estrito", amostra=200, es=es)
    estimado = _agregar_expiracoes(escopo_def, janela=janela, modo="estimado", amostra=500, es=es)
    return {
        "evento": "contratos_a_expirar",
        "disponivel": True,
        "medicao": {
            "horizonte_dias": dias,
            "janela": {"de": janela[0], "ate": janela[1]},
            "estrito": estrito,
            "estimado": estimado,
            "valor_exposto": lz._num(estrito.get("valor")) + lz._num(estimado.get("valor")),
            "nota": (
                "«estrito» usa `dataFechoContrato` (campo preenchido numa minoria dos contratos); "
                "«estimado» calcula celebração + `prazoExecucao` (dias) sobre os maiores contratos candidatos "
                "e declara a cobertura de valor da amostra."
            ),
        },
        "hipoteses": [
            "O fim estimado assume `prazoExecucao` em dias e ignora valores fora de [1, 3650].",
            "A leitura estimada parte dos maiores contratos (por valor) — a cobertura está em `amostra`.",
            "Volume exposto à renovação ≠ perda de receita: o contrato pode ser renovado para a mesma empresa.",
        ],
        "notas": ["Serve para priorizar revisão de carteira e não como previsão de perda."],
    }


def cenario_precos(
    escopo_def: Dict[str, Any],
    *,
    variacao: Optional[float] = None,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Sensibilidade a preços: quanto muda o valor contratado com uma variação uniforme."""
    config = parametros()
    delta = float(variacao if variacao is not None else config["precos_variacao"])
    benchmark_dados = benchmark(escopo_def, es=es)
    empresas = benchmark_dados.get("empresas") or []
    valor = lz._num((benchmark_dados.get("mercado") or {}).get("valor"))
    return {
        "evento": "precos_mais",
        "disponivel": bool(empresas),
        "medicao": {
            "variacao": delta,
            "valor_atual": valor,
            "valor_simulado": valor * (1 + delta),
            "delta_valor": valor * delta,
            "por_empresa": [
                {"nif": empresa["nif"], "nome": empresa["nome"], "delta_valor": lz._num(empresa["valor"]) * delta}
                for empresa in empresas[:12]
            ],
        },
        "hipoteses": [
            "Variação **uniforme** sobre o valor contratado — não é um modelo de formação de preços.",
            "Sem dados de preço unitário por bem/serviço não se estima elasticidade nem efeito na procura.",
        ],
        "notas": ["Leitura de exposição orçamental: quanto do valor contratado está sensível a uma variação de preços."],
    }


def cenario_diversificacao(
    escopo_def: Dict[str, Any],
    *,
    nif: Optional[str] = None,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Efeito de diversificar a carteira: distribuir o maior comprador por vários."""
    lista = [str(nif)] if nif else None
    dados = dependencias(escopo_def, nifs=lista, es=es)
    empresas = dados.get("empresas") or []
    if not empresas:
        return {"evento": "diversificacao", "disponivel": False, "motivo": "sem empresas no escopo"}
    alvo = empresas[0]
    carteira = alvo.get("carteira") or []
    if len(carteira) < 2:
        return {
            "evento": "diversificacao",
            "disponivel": False,
            "motivo": "a empresa tem um só comprador no escopo — não há o que repartir",
            "alvo": alvo.get("nome"),
        }
    maior = carteira[0]
    valor_total = lz._num(alvo.get("valor"))
    valor_maior = lz._num(maior.get("valor"))
    metade = valor_maior / 2
    simulada = [valor_total - metade, metade] + [lz._num(item.get("valor")) for item in carteira[1:]]
    return {
        "evento": "diversificacao",
        "disponivel": True,
        "alvo": {"nif": alvo.get("nif"), "nome": alvo.get("nome")},
        "medicao": {
            "dependencia_antes": alvo.get("dependencia"),
            "dependencia_simulada": indice_dependencia(simulada),
            "maior_comprador": maior.get("nome"),
            "quota_do_maior": lz._num(maior.get("quota")),
            "valor_a_repartir": metade,
            "nota": "A repartição simulada mantém o valor total e divide o maior comprador em dois (nova relação a criar).",
        },
        "hipoteses": ["Assume-se valor total constante: a diversificação redistribui, não aumenta a carteira."],
        "evidencia": carteira[:5],
    }


def cenarios(
    escopo_def: Dict[str, Any],
    *,
    nif: Optional[str] = None,
    entidade_nif: Optional[str] = None,
    fornecedor_nif: Optional[str] = None,
    horizonte_dias: Optional[int] = None,
    forca_relativa: float = 1.0,
    variacao_precos: Optional[float] = None,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Os seis eventos do World Model aplicados ao mercado escolhido."""
    inicio = time.time()
    lista = [str(nif)] if nif else None
    metricas = metricas_empresas(escopo_def, lista or [e.get("nif") for e in empresas_do_mercado(escopo_def, limite=1, es=es)], es=es)
    alvo_nif = str(nif) if nif else next(iter(metricas), None)
    metrica_alvo = metricas.get(alvo_nif) or {}
    return {
        "escopo": {chave: valor for chave, valor in escopo_def.items() if chave != "query"},
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "eventos": [
            cenario_perda_maior_comprador(metrica_alvo, nome=alvo_nif),
            cenario_entidade_sem_fornecedor(escopo_def, entidade_nif=entidade_nif, fornecedor_nif=fornecedor_nif, es=es),
            cenario_novo_concorrente(escopo_def, forca_relativa=forca_relativa, es=es),
            cenario_contratos_a_expirar(escopo_def, horizonte_dias=horizonte_dias, es=es),
            cenario_precos(escopo_def, variacao=variacao_precos, es=es),
            cenario_diversificacao(escopo_def, nif=nif, es=es),
        ],
        "sensibilidade": sensibilidade(escopo_def, es=es),
        "duracao_s": round(time.time() - inicio, 2),
        "notas": [
            "Cada evento é um contrafactual medido nos contratos do escopo — não é previsão.",
            "O comportamento do modelo tem de ser confrontado com dados históricos e cenários economicamente plausíveis.",
        ],
    }


def sensibilidade(escopo_def: Dict[str, Any], *, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Motor Lorenz sobre a série do mercado: divergência, Lyapunov e regime."""
    serie_dados = lz.serie(escopo_def, es=es)
    if serie_dados.get("erro"):
        return {"disponivel": False, "motivo": serie_dados["erro"]}
    periodos = serie_dados.get("periodos") or []
    if len(periodos) < 3:
        return {"disponivel": False, "motivo": "série demasiado curta (mínimo 3 períodos)", "periodos": len(periodos)}
    estado = lz.estado_da_serie(periodos)
    parametros_est = lz.estimar_parametros(periodos)
    mapa = lz.ajustar_mapa_linear(estado["coordenadas"])
    divergencia = (
        lz.divergencia_mapa(
            estado["coordenadas"][-1],
            mapa["A"],
            mapa["b"],
            perturbacao=1e-3,
            passos=6,
            direcoes=12,
            semente=int(parametros()["semente"]),
        )
        if mapa.get("disponivel")
        else {"disponivel": False, "motivo": mapa.get("motivo")}
    )
    lorenz = None
    if parametros_est.get("disponivel"):
        ultimo = estado["cru"][-1] if estado["cru"] else [1.0, 0.2, 1.0]
        semente_lorenz = [max(0.5, min(3.0, float(ultimo[0]))), max(0.1, min(5.0, float(ultimo[1]) * 10)), max(0.5, min(3.0, float(ultimo[2])))]
        lorenz = {
            "trajetoria": lz.integrar(
                semente_lorenz,
                parametros_est["sigma"],
                parametros_est["rho"],
                parametros_est["beta"],
                passos=int(lz.parametros()["passos_lorenz"]),
                dt=float(lz.parametros()["dt"]),
                guardar_cada=max(int(lz.parametros()["passos_lorenz"]) // 60, 1),
            ),
            "lyapunov": lz.lyapunov_maximo(
                semente_lorenz,
                parametros_est["sigma"],
                parametros_est["rho"],
                parametros_est["beta"],
                perturbacao=float(lz.parametros()["perturbacao"]),
                passos=int(lz.parametros()["passos_lorenz"]),
                dt=float(lz.parametros()["dt"]),
            ),
        }
    return {
        "disponivel": True,
        "periodos": [periodo.get("periodo") for periodo in periodos],
        "parametros": parametros_est,
        "estado": estado,
        "mapa": mapa,
        "divergencia": divergencia,
        "lorenz": lorenz,
        "nota": "Leitura de regime (sensível/dissipador) do mercado, com a mesma matemática da página Lorenz.",
    }


# ---------------------------------------------------------------------------
# 6. Orquestradores e evidências
# ---------------------------------------------------------------------------
def empresa(nif: str, *, escopo_def: Optional[Dict[str, Any]] = None, es: Optional[Elasticsearch] = None) -> Dict[str, Any]:
    """Ficha de mercado de uma empresa: posição, dependências, pares e evolução."""
    base = escopo_def or lz.escopo(area="todas")
    filtrado = lz.escopo(
        area=base.get("area"),
        cpv=None,
        ano_de=base.get("ano_de"),
        ano_ate=base.get("ano_ate"),
        regiao=base.get("regiao"),
        nif=str(nif),
    )
    metrica = (metricas_empresas(filtrado, [str(nif)], es=es) or {}).get(str(nif)) or {}
    if metrica.get("erro"):
        return {"erro": metrica["erro"], "nif": nif}
    registo = (cae_por_nif([str(nif)], es=es) or {}).get(str(nif)) or {}
    principal = (metrica.get("cpvs") or [None])[0]
    compat = compatibilidade_empresa(registo.get("caes") or [], (principal or {}).get("classe"))
    return {
        "nif": str(nif),
        "nome": metrica.get("nome") or registo.get("nome_registo") or str(nif),
        "cae": registo,
        "compatibilidade": compat,
        "contratos": int(lz._num(metrica.get("contratos"))),
        "valor": lz._num(metrica.get("valor")),
        "entidades": metrica.get("entidades") or [],
        "entidades_distintas": int(lz._num(metrica.get("entidades_distintas"))),
        "cpvs": metrica.get("cpvs") or [],
        "dependencia": metrica.get("dependencia") or {},
        "evolucao": metrica.get("evolucao") or {},
        "taxa_sem_concurso": lz._num(metrica.get("taxa_sem_concurso")),
        "alertas": _alertas_empresa(metrica, compat, parametros()),
        "perfil": _perfil(metrica, compat, parametros()),
        "evidencias": lz.evidencias(base, fornecedor_nif=str(nif), limite=10, es=es),
    }


def pares(
    nif: str,
    *,
    escopo_def: Optional[Dict[str, Any]] = None,
    limite: Optional[int] = None,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    """Empresas comparáveis: mesmos CPV, CAE compatível e mesmo período."""
    base = escopo_def or lz.escopo(area="todas")
    ficha = empresa(nif, escopo_def=base, es=es)
    if ficha.get("erro"):
        return ficha
    classes = [cpv.get("classe") for cpv in (ficha.get("cpvs") or [])[:3] if cpv.get("classe")]
    cpv_ref = ",".join(classes) if classes else None
    comparacao = benchmark(base, cpv=cpv_ref, limite=int(limite or parametros()["limite_comparacao"]) or None, es=es)
    compativeis = [
        empresa_
        for empresa_ in (comparacao.get("empresas") or [])
        if str(empresa_["nif"]) != str(nif) and empresa_["compatibilidade"] in ("alta", "média-alta", "média")
    ]
    return {
        "alvo": {"nif": str(nif), "nome": ficha.get("nome"), "cpvs": classes, "cae": ficha.get("cae")},
        "mercado": comparacao.get("mercado"),
        "pares": compativeis,
        "avisos": comparacao.get("avisos") or [],
        "notas": [
            "«Par» é uma empresa que atua nas mesmas classes de CPV no período, com CAE compatível — não implica concorrência direta em todos os concursos.",
            "Sem CAE no registo, a compatibilidade fica «desconhecida» e a empresa não é apresentada como par.",
        ],
    }


def meta() -> Dict[str, Any]:
    """Metamodelo: camadas, indicadores, tabela CPV↔CAE e limites."""
    return {
        "modulo": "mercado",
        "titulo": "Inteligência de mercado · empresas, entidades e dependências",
        "descricao": (
            "Compara empresas dentro do mesmo mercado (CPV + CAE + período), mede dependências recíprocas com as "
            "entidades públicas, segue a evolução temporal e simula alterações na rede com evidências."
        ),
        "arquitetura": [
            {"camada": "ingestao", "label": "Ingestão e normalização", "detalhe": "Portal BASE (contratos, concorrentes) + registo (CAE) + catálogo CAE/CPV"},
            {"camada": "grafo", "label": "Grafo temporal", "detalhe": "Empresa → contrato → entidade → CPV → CAE, com relações datadas"},
            {"camada": "indicadores", "label": "Motor de indicadores", "detalhe": "P_i (posição), D_i (concentração de compradores), dependência recíproca, evolução"},
            {"camada": "dinamica", "label": "Motor Lorenz + World Model", "detalhe": "Perturbações, cenários contrafactuais, sensibilidade e incerteza"},
            {"camada": "evidencia", "label": "Evidências e auditoria", "detalhe": "Cada indicador chega aos contratos de origem e às limitações dos dados"},
        ],
        "indicadores": [
            {"id": "posicionamento", "label": "Índice de posicionamento (P_i)", "formula": "P_i = V_i / Σ_j V_j", "nota": "Quota do valor publicado dentro do mercado definido."},
            {"id": "dependencia_empresa", "label": "Dependência da empresa (D_i)", "formula": "D_i = Σ_e s_ie²", "nota": "HHI da carteira de compradores."},
            {"id": "dependencia_entidade", "label": "Dependência da entidade", "formula": "Σ_f (valor_f / valor_entidade)²", "nota": "Concentração dos fornecedores por entidade/CPV."},
            {"id": "evolucao", "label": "Evolução temporal", "formula": "variação e CAGR por ano", "nota": "Deteta alterações de posição no mercado."},
            {"id": "sensibilidade", "label": "Sensibilidade (Lorenz)", "formula": "D_t e λ do mapa ajustado", "nota": "Pequenas alterações nas condições iniciais."},
        ],
        "eventos": [
            {"id": "perda_maior_comprador", "label": "Empresa perde o maior comprador"},
            {"id": "entidade_sem_fornecedor", "label": "Entidade deixa de contratar um fornecedor"},
            {"id": "novo_concorrente", "label": "Novo concorrente entra no mercado"},
            {"id": "contratos_a_expirar", "label": "Contratos expiram no horizonte"},
            {"id": "precos_mais", "label": "Preços contratuais aumentam"},
            {"id": "diversificacao", "label": "Empresa diversifica compradores"},
        ],
        "tabela_cae_cpv": regras_cae_cpv(),
        "graus": GRAUS,
        "parametros": parametros(),
        "limites": [
            "O CAE vem do registo (`finance_entities`), não do Portal BASE: empresas sem CAE ficam como «desconhecida».",
            "A tabela CPV↔CAE é curada (grau alta/média/baixa) e editável — é indicativa.",
            "P_i não é quota de mercado total: exclui a compra privada e as compras públicas não publicadas.",
            "Concentração de compradores não é dependência económica absoluta.",
            "Partilhar clientes/fornecedores é relação observada, não prova de coordenação.",
        ],
        "indices": {"contratos": CONTRACTS_INDEX, "entidades": ENTITIES_INDEX, "execucoes": MERCADO_RUNS_INDEX},
    }


def guardar_execucao(
    escopo_def: Dict[str, Any],
    resultado: Dict[str, Any],
    *,
    autor: Optional[str] = None,
    titulo: Optional[str] = None,
    es: Optional[Elasticsearch] = None,
) -> Dict[str, Any]:
    cliente = lz._cliente(es)
    if cliente is None:
        return {"erro": "Elasticsearch indisponível"}
    ensure_indices(cliente)
    identificador = f"mk-{int(time.time() * 1000)}"
    documento = {
        "run_id": identificador,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "titulo": titulo or f"Mercado · {escopo_def.get('area_label') or escopo_def.get('area')}",
        "area": escopo_def.get("area"),
        "cpv_prefixos": escopo_def.get("cpv_prefixos"),
        "ano_de": escopo_def.get("ano_de"),
        "ano_ate": escopo_def.get("ano_ate"),
        "regiao": escopo_def.get("regiao"),
        "nif": escopo_def.get("nif"),
        "autor": autor,
        "mercado": resultado.get("mercado"),
        "empresas": len(resultado.get("empresas") or []),
        "resultado": resultado,
    }
    cliente.index(index=MERCADO_RUNS_INDEX, id=identificador, document=documento, refresh="wait_for")
    return {"ok": True, "run_id": identificador, "titulo": documento["titulo"]}


def listar_execucoes(*, limite: int = 20, es: Optional[Elasticsearch] = None) -> List[Dict[str, Any]]:
    cliente = lz._cliente(es)
    if cliente is None:
        return []
    ensure_indices(cliente)
    try:
        resposta = cliente.search(
            index=MERCADO_RUNS_INDEX,
            body={
                "size": int(limite),
                "sort": [{"created_at": {"order": "desc"}}],
                "query": {"match_all": {}},
                "_source": ["run_id", "created_at", "titulo", "area", "ano_de", "ano_ate", "regiao", "nif", "autor", "empresas", "mercado"],
            },
        )
    except Exception as erro:  # noqa: BLE001
        logger.warning("mercado: listagem falhou (%s)", erro)
        return []
    return [hit.get("_source") or {} for hit in ((resposta.get("hits") or {}).get("hits") or [])]


def obter_execucao(run_id: str, *, es: Optional[Elasticsearch] = None) -> Optional[Dict[str, Any]]:
    cliente = lz._cliente(es)
    if cliente is None:
        return None
    try:
        return (cliente.get(index=MERCADO_RUNS_INDEX, id=run_id) or {}).get("_source")
    except Exception:  # noqa: BLE001
        return None
