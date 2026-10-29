"""Custo de vida por concelho e índice de custo de vida.

O site publica um mapa com a renda mediana (INE) e o gasóleo (DGEG). Este
serviço transforma esses valores num **orçamento mensal comparável** e num
**índice**, juntando os componentes que faltavam e que têm série oficial:

| Componente | Fonte | Varia por concelho? |
| --- | --- | --- |
| Renda (€/m²) | INE, novos contratos | sim |
| Gasóleo (€/l) | DGEG, postos do concelho | sim |
| IMI (taxa urbana) | AT (via `flatin.pt`, CC BY) | sim |
| Eletricidade | ERSE (tarifa transitória, BTN) | não — é nacional |
| Gás natural | ERSE (escalão 1) | não — é nacional |

**O índice de custo de vida** é 100 × (custo mensal do concelho ÷ mediana
nacional do custo mensal), na tipologia T2 (70 m²) e com 50 litros de gasóleo
por mês. Ou seja: 118 quer dizer «18 % acima da mediana do país», não «118
euros». É calculado só sobre os concelhos com renda publicada — o INE suprime
os concelhos com menos de 33 contratos novos — porque sem renda o custo não é
comparável e preencher o buraco com a mediana nacional falsearia o ranking.

Os componentes nacionais (eletricidade e gás) entram no **custo**, mas não
diferenciam territórios: somam o mesmo a todos os concelhos. É por isso que
`indice` e `custo` nunca são a mesma leitura — e a página diz isso.

Água, resíduos, transportes e alimentação ficam de fora, com o motivo escrito
em `collectors/custo_vida.LIMITES`: nesses casos o valor existe, mas não há
série aberta por concelho, e estimá-lo seria inventar um número.
"""
from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Dict, List, Optional

from collectors import custo_vida as recolha

ROOT = Path(__file__).resolve().parents[1]
BASE_PATH = ROOT / "data" / "custo-vida" / "base_concelhos.json"

#: Área bruta usada para converter €/m² em renda mensal, por tipologia.
TIPOLOGIAS: Dict[str, int] = {"T0": 35, "T1": 50, "T2": 70, "T3": 90}
#: Tipologia de referência do índice e do orçamento apresentado.
TIPOLOGIA_REFERENCIA = "T2"
#: Litros de gasóleo por mês no orçamento tipo.
LITROS_MES = 50
#: Consumo anual de eletricidade do exemplo da ERSE (1 900 kWh, 3,45 kVA).
KWH_ANO = 1900
#: Consumo anual de gás natural do exemplo da ERSE (138 m³, escalão 1).
GAS_M3_ANO = 138
#: Poder calorífico usado para converter m³ de gás natural em kWh (DGEG).
KWH_POR_M3_GAS = 11.0
#: Dias por mês (ano civil ÷ 12), para os termos fixos diários.
DIAS_MES = 365.25 / 12
#: Valor patrimonial tributário do imóvel de referência, para traduzir a taxa
#: de IMI num valor anual. É uma âncora explícita: a taxa varia, o VPT não.
VPT_REFERENCIA = 120_000.0


def _fold(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text).strip().lower()


def _slug(value: str) -> str:
    base = _fold(value).replace(" ", "-")
    return re.sub(r"[^a-z0-9\-]", "", base)


def _sem_parenteses(nome: str) -> str:
    """«Calheta (Açores)» → «Calheta»: o nome do concelho sem a desambiguação."""
    return re.sub(r"\s*\([^)]*\)\s*$", "", str(nome or "")).strip()


#: Nomes que a base e as fontes escrevem de forma diferente.
ALIASES = {
    "vila da praia da vitoria": "praia da vitoria",
}


def _chave_nome(nome: str) -> str:
    """Chave de comparação de um concelho, tolerante a parênteses e a grafias."""
    base = _fold(_sem_parenteses(nome))
    return ALIASES.get(base, base)


def carregar_base() -> Dict[str, Any]:
    """Os 308 concelhos com renda, gasóleo, população e despesa já publicados."""
    if not BASE_PATH.exists():
        return {"concelhos": []}
    return json.loads(BASE_PATH.read_text(encoding="utf-8"))


#: Concelhos cuja ficha do INE/base publicada não traz distrito. O valor é o
#: distrito oficial (CAOP): os dois Calheta e a Lagoa dos Açores têm homónimos
#: no continente e na Madeira, e é por isso que a tabela genérica falha.
DISTRITOS_EM_FALTA: Dict[str, str] = {
    "calheta (r.a.a.)": "Região Autónoma dos Açores",
    "calheta (r.a.m.)": "Região Autónoma da Madeira",
    "lagoa (r.a.a.)": "Região Autónoma dos Açores",
    "vila da praia da vitoria": "Região Autónoma dos Açores",
    "figueira de castelo rodrigo": "Guarda",
    "freixo de espada a cinta": "Bragança",
    "santa marta de penaguiao": "Vila Real",
    "vila real de santo antonio": "Faro",
}


def _distritos() -> Dict[str, str]:
    """Distrito por concelho, a partir das fichas do INE e da tabela de falhas.

    As fichas dos municípios (despesa municipal do INE) trazem o distrito em
    301 dos 308 concelhos. Os restantes ficam aqui, com o distrito oficial: são
    exactamente os casos em que o nome se repete entre regiões (Calheta, Lagoa)
    ou em que a fonte não publica o campo.
    """
    distritos: Dict[str, str] = {}
    caminho = ROOT / "data" / "municipios" / "municipios.json"
    if caminho.exists():
        try:
            fichas = json.loads(caminho.read_text(encoding="utf-8")).get("fichas") or []
        except (OSError, ValueError):
            fichas = []
        por_nome: Dict[str, List[str]] = {}
        for ficha in fichas:
            distrito = str(ficha.get("distrito") or "").strip()
            nome = str(ficha.get("nome") or "").strip()
            if distrito and nome:
                por_nome.setdefault(_chave_nome(nome), []).append(distrito)
        distritos.update(
            {chave: valores[0] for chave, valores in por_nome.items() if len(set(valores)) == 1}
        )
    for nome, distrito in DISTRITOS_EM_FALTA.items():
        distritos.setdefault(nome, distrito)
    return distritos


def _distrito_canonico(distrito: str) -> str:
    """Grafia oficial do distrito («Braganca» → «Bragança», «Acores» → região)."""
    from api.es.geo import PT_DISTRICTS

    chave = _fold(distrito)
    for nome in PT_DISTRICTS:
        if _fold(nome) == chave:
            return nome
    if chave in ("acores", "regiao autonoma dos acores"):
        return "Região Autónoma dos Açores"
    if chave in ("madeira", "regiao autonoma da madeira"):
        return "Região Autónoma da Madeira"
    return distrito


def _distrito_de(nome: str, distritos: Dict[str, str]) -> str:
    """Distrito de um concelho, com a desambiguação da região à frente da tabela."""
    marcador = _regiao(nome, "")
    if marcador == "acores":
        return "Região Autónoma dos Açores"
    if marcador == "madeira":
        return "Região Autónoma da Madeira"
    chave = _chave_nome(nome)
    if chave in DISTRITOS_EM_FALTA:
        return DISTRITOS_EM_FALTA[chave]
    cru = _fold(_sem_parenteses(nome))
    if cru in DISTRITOS_EM_FALTA:
        return DISTRITOS_EM_FALTA[cru]
    return distritos.get(chave, "")


def _indice_por_nome(bloco: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """Agrupa as entradas de um componente pelo nome do concelho, sem o parêntese.

    «Calheta (Açores)» e «Calheta (Madeira)» são concelhos diferentes; o nome
    sem parênteses é a chave, e a lista guarda os candidatos para se
    desambiguar depois pelo distrito ou pela região.
    """
    agrupado: Dict[str, List[Dict[str, Any]]] = {}
    for item in (bloco.get("por_concelho") or {}).values():
        nome = _sem_parenteses(item.get("concelho") or "")
        if nome:
            agrupado.setdefault(_chave_nome(nome), []).append(item)
    return agrupado


def _regiao(nome: str, distrito: str) -> str:
    """«acores»/«madeira»/"" a partir do distrito ou da marca no próprio nome."""
    alvo = _fold(f"{distrito or ''} {nome or ''}")
    if "acores" in alvo or "r.a.a" in alvo:
        return "acores"
    if "madeira" in alvo or "r.a.m" in alvo:
        return "madeira"
    return ""


def _distrito_do_continente(distrito: Any) -> bool:
    """Verdadeiro se o distrito for um dos 18 do continente (não Açores/Madeira)."""
    from api.es.geo import PT_DISTRICTS

    alvo = _fold(distrito)
    if not alvo:
        return False
    return any(_fold(nome) == alvo for nome in PT_DISTRICTS if not nome.startswith("Região"))


def _regiao_do_distrito(distrito: Any) -> str:
    """«acores»/«madeira»/«continente»/"" para um distrito publicado pela fonte."""
    from api.es.geo import PT_DISTRICTS

    alvo = _fold(distrito)
    if not alvo:
        return ""
    for nome in PT_DISTRICTS:
        if _fold(nome) == alvo:
            if nome.startswith("Região Autónoma dos Açores"):
                return "acores"
            if nome.startswith("Região Autónoma da Madeira"):
                return "madeira"
            return "continente"
    regiao = _regiao("", alvo)
    return regiao


def _escolher(
    candidatos: List[Dict[str, Any]], distrito: str, nome: str = ""
) -> Optional[Dict[str, Any]]:
    """Escolhe o candidato certo quando o nome do concelho se repete.

    Um candidato único não é automaticamente o certo: a DGEG escreve «Calheta» e
    «Lagoa» sem dizer de que região são. Quando o concelho da base traz a marca
    da região (R.A.A./R.A.M.) e o candidato traz um distrito que a contradiz, não
    se aproveita — vale mais ficar sem o dado do que dar o preço da Madeira a um
    concelho dos Açores.
    """
    if not candidatos:
        return None
    regiao = _regiao(nome, distrito)
    if len(candidatos) == 1:
        candidato = candidatos[0]
        regiao_candidato = _regiao_do_distrito(candidato.get("distrito"))
        if regiao and regiao_candidato and regiao_candidato != regiao:
            # «Lagoa» da DGEG é a do Algarve; não serve para Lagoa (R.A.A.) — e o
            # mesmo para a Calheta da Madeira contra a dos Açores.
            return None
        return candidato
    alvo = _fold(distrito)
    exatos = [c for c in candidatos if _fold(c.get("distrito")) == alvo]
    if len(exatos) == 1:
        return exatos[0]
    if regiao:
        por_regiao = [c for c in candidatos if regiao in _fold(c.get("concelho"))]
        if len(por_regiao) == 1:
            return por_regiao[0]
        # Sem parênteses na origem: fica o que não colide com a outra região.
        outra = "madeira" if regiao == "acores" else "acores"
        sem_outra = [c for c in candidatos if outra not in _fold(c.get("concelho"))]
        if len(sem_outra) == 1:
            return sem_outra[0]
    return None


def _eletricidade_mensal(erse: Dict[str, Any]) -> Optional[float]:
    dados = erse.get("eletricidade") or {}
    if not dados or "erro" in dados:
        return None
    energia = float(dados.get("energia_kwh") or 0)
    termo = float(dados.get("termo_fixo_dia") or 0)
    if not energia:
        return None
    return KWH_ANO / 12 * energia + termo * DIAS_MES


def _gas_mensal(erse: Dict[str, Any]) -> Optional[float]:
    dados = erse.get("gas") or {}
    if not dados or "erro" in dados:
        return None
    energia = float(dados.get("energia_kwh") or 0)
    termo = float(dados.get("termo_fixo_dia") or 0)
    if not energia:
        return None
    return GAS_M3_ANO * KWH_POR_M3_GAS / 12 * energia + termo * DIAS_MES


def construir(componentes: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Constrói um documento por concelho, com custo por tipologia e índice."""
    componentes = componentes or recolha.carregar_componentes()
    base = carregar_base()
    concelhos = base.get("concelhos") or []
    if not concelhos:
        return {"docs": [], "meta": {"erro": "sem dados base", "total": 0}}

    imi = componentes.get("imi") or {}
    gasoleo = componentes.get("gasoleo") or {}
    erse = componentes.get("erse") or {}
    imi_por_nome = _indice_por_nome(imi)
    gasoleo_por_nome = _indice_por_nome(gasoleo)
    distritos = _distritos()
    luz = _eletricidade_mensal(erse)
    gas = _gas_mensal(erse)

    docs: List[Dict[str, Any]] = []
    for linha in concelhos:
        nome = str(linha.get("n") or "").strip()
        if not nome:
            continue
        distrito = str(linha.get("d") or "").strip() or _distrito_de(nome, distritos)
        distrito = _distrito_canonico(distrito)

        taxa_item = _escolher(imi_por_nome.get(_chave_nome(nome), []), distrito, nome)
        taxa = None
        if taxa_item and taxa_item.get("urbana_pct") is not None:
            taxa = float(taxa_item["urbana_pct"])
        imi_anual = round(VPT_REFERENCIA * taxa / 100, 2) if taxa is not None else None
        imi_mensal = round(imi_anual / 12, 2) if imi_anual is not None else None

        combustivel = _escolher(gasoleo_por_nome.get(_chave_nome(nome), []), distrito, nome)
        # Com a recolha da DGEG feita, manda a recolha: um concelho que hoje não
        # tem posto com preço comunicado fica sem gasóleo, e não com o valor de
        # uma leitura antiga (a página publica a data da leitura ao lado).
        if gasoleo.get("fonte") and not gasoleo.get("erro"):
            gasoleo_l = combustivel.get("preco_l") if combustivel else None
        else:
            gasoleo_l = linha.get("g")
        gasoleo_postos = combustivel.get("postos") if combustivel else None

        renda_m2 = linha.get("r")
        renda_m2 = float(renda_m2) if renda_m2 is not None else None

        fixos = sum(valor for valor in (luz, gas, imi_mensal) if valor)
        custo: Dict[str, Optional[float]] = {}
        for tipologia, area in TIPOLOGIAS.items():
            if renda_m2 is None:
                custo[tipologia] = None
                continue
            renda = renda_m2 * area
            combustivel_mes = (float(gasoleo_l) * LITROS_MES) if gasoleo_l else 0.0
            custo[tipologia] = round(renda + combustivel_mes + fixos, 2)

        cobertura: List[str] = []
        if renda_m2 is not None:
            cobertura.append("renda")
        if gasoleo_l is not None:
            cobertura.append("gasoleo")
        if taxa is not None:
            cobertura.append("imi")
        if luz is not None:
            cobertura.append("eletricidade")
        if gas is not None:
            cobertura.append("gas")

        docs.append(
            {
                "doc_id": _slug(nome),
                "nome": nome,
                "nome_keyword": _fold(nome),
                "distrito": distrito,
                "nuts": str(linha.get("nu") or ""),
                "populacao": linha.get("p"),
                "despesa_hab": linha.get("dp"),
                "despesa_total": linha.get("desp"),
                "lat": linha.get("lat"),
                "lon": linha.get("lon"),
                "renda_m2": renda_m2,
                "gasoleo_l": round(float(gasoleo_l), 4) if gasoleo_l else None,
                "gasoleo_postos": gasoleo_postos,
                "imi_pct": taxa,
                "imi_anual": imi_anual,
                "imi_mensal": imi_mensal,
                "eletricidade_mensal": round(luz, 2) if luz is not None else None,
                "gas_mensal": round(gas, 2) if gas is not None else None,
                "custo": custo,
                "cobertura": cobertura,
                "completo": set(cobertura) >= {"renda", "gasoleo", "imi", "eletricidade", "gas"},
            }
        )

    referencia = [
        doc["custo"][TIPOLOGIA_REFERENCIA]
        for doc in docs
        if doc["custo"].get(TIPOLOGIA_REFERENCIA) is not None
    ]
    mediana = median(referencia) if referencia else None
    for doc in docs:
        valor = doc["custo"].get(TIPOLOGIA_REFERENCIA)
        doc["indice"] = round(100 * valor / mediana, 1) if (valor is not None and mediana) else None

    ordenados = sorted((d for d in docs if d["indice"] is not None), key=lambda d: d["indice"])
    for posicao, doc in enumerate(ordenados, 1):
        doc["indice_posicao"] = posicao
    for doc in docs:
        doc.setdefault("indice_posicao", None)

    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for doc in docs:
        doc["atualizado_em"] = agora

    meta = {
        "total": len(docs),
        "com_renda": sum(1 for d in docs if d["renda_m2"] is not None),
        "com_imi": sum(1 for d in docs if d["imi_pct"] is not None),
        "com_gasoleo": sum(1 for d in docs if d["gasoleo_l"] is not None),
        "completos": sum(1 for d in docs if d["completo"]),
        "tipologia_referencia": TIPOLOGIA_REFERENCIA,
        "litros_mes": LITROS_MES,
        "vpt_referencia": VPT_REFERENCIA,
        "custo_mediano": round(mediana, 2) if mediana else None,
        "concelho_mais_caro": ordenados[-1]["nome"] if ordenados else None,
        "concelho_mais_barato": ordenados[0]["nome"] if ordenados else None,
        "indice_max": ordenados[-1]["indice"] if ordenados else None,
        "indice_min": ordenados[0]["indice"] if ordenados else None,
        "recolha": {
            "imi_ano": imi.get("ano"),
            "gasoleo": gasoleo.get("leitura"),
            "recolhido_em": componentes.get("recolhido_em"),
        },
        "componentes": {
            "imi": {
                "fonte": imi.get("fonte"),
                "url": imi.get("url"),
                "licenca": imi.get("licenca"),
                "ano": imi.get("ano"),
                "sem_taxa_unica": imi.get("sem_taxa_unica"),
            },
            "gasoleo": {
                "fonte": gasoleo.get("fonte"),
                "url": gasoleo.get("url"),
                "leitura": gasoleo.get("leitura"),
            },
            "eletricidade": erse.get("eletricidade") or {},
            "gas": erse.get("gas") or {},
        },
        "referencias": {
            "kwh_ano": KWH_ANO,
            "gas_m3_ano": GAS_M3_ANO,
            "kwh_por_m3_gas": KWH_POR_M3_GAS,
            "tipologias": TIPOLOGIAS,
        },
        "limites": componentes.get("limites") or recolha.LIMITES,
    }
    return {"docs": docs, "meta": meta}
