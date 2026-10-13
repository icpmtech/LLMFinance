"""Páginas públicas de **pesquisa** sobre as despesas municipais.

Uma pesquisa publicada é uma **consulta congelada**: os filtros (texto, distrito,
ano da contratação, ordenação, limite) ficam guardados no documento do CMS e os
números são a fotografia lida quando o editor os mandou ler. O Portal BASE e o
INE mudam todos os dias; a página publicada só muda quando alguém a volta a ler
(`POST /cms/pesquisas/{id}/dados`) — como nas fichas de município.

- `opcoes()` — filtros disponíveis (distritos, anos de contratação, ordenações);
- `dados_da_pesquisa(filtros)` — corre a pesquisa no módulo dos municípios e
  devolve o que a página mostra: totais, linhas, **gráficos** (municípios do
  topo, contratado e despesa por ano), **principais adjudicatários** e
  proveniência;
- `descricao_dos_filtros(filtros)` — frase legível («distrito do Porto,
  contratação de 2024, ordenado por valor contratado (decrescente)»), que serve
  de resumo e de base à `meta description`.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from api import cms_store as store
from api import municipios_service as municipios

#: Quantas linhas a página lista (o resto continua no `total`).
LIMITE_MAXIMO = 200

#: Ordenações possíveis (as mesmas da lista das despesas municipais).
ORDENACOES: List[Dict[str, str]] = [
    {"id": "despesas", "label": "Despesa total"},
    {"id": "pessoal", "label": "Despesas com pessoal"},
    {"id": "bens_servicos", "label": "Bens e serviços"},
    {"id": "capital", "label": "Despesas de capital"},
    {"id": "contratos", "label": "Valor contratado"},
    {"id": "contratos_total", "label": "N.º de contratos"},
    {"id": "nome", "label": "Nome"},
]

FONTE_DESPESAS_URL = "https://www.ine.pt/xurl/indx/0013909/PT"


def opcoes() -> Dict[str, Any]:
    """Filtros disponíveis para montar uma pesquisa (e os rótulos das fontes)."""
    meta = municipios.meta()
    distritos = sorted(
        {
            str(ficha.get("distrito")).strip()
            for ficha in municipios.fichas_locais()
            if str(ficha.get("distrito") or "").strip()
        }
    )
    return {
        "distritos": distritos,
        "anos_contratos": meta.get("anos_contratos") or [],
        "ordenacoes": ORDENACOES,
        "limite_maximo": LIMITE_MAXIMO,
        "ultimo_periodo": meta.get("ultimo_periodo"),
        "ano_despesas": meta.get("ultimo_periodo"),
        "fonte_despesas": meta.get("fonte_despesas"),
        "fonte_contratos": meta.get("fonte_contratos"),
    }


def descricao_dos_filtros(filtros: Optional[Dict[str, Any]] = None) -> str:
    """Os filtros em português («distrito do Porto, contratação de 2024, …»).

    É o que se mostra por cima da tabela e o que dá a `meta description` por
    omissão — a página explica-se sem depender do texto editorial.
    """
    limpos = store.normalizar_filtros(filtros)
    partes: List[str] = []
    if limpos["q"]:
        partes.append(f"«{limpos['q']}»")
    if limpos["distrito"]:
        partes.append(f"distrito de {limpos['distrito']}")
    if limpos["ano_contratos"]:
        partes.append(f"contratação de {limpos['ano_contratos']}")
    if limpos["min_despesas"]:
        partes.append(f"despesa a partir de {int(limpos['min_despesas']):,} €".replace(",", " "))
    rotulo = next(
        (item["label"].lower() for item in ORDENACOES if item["id"] == limpos["ordenar"]),
        "despesa total",
    )
    partes.append(f"ordenado por {rotulo} ({'crescente' if limpos['ordem'] == 'asc' else 'decrescente'})")
    return ", ".join(partes)


def dados_da_pesquisa(filtros: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Corre a pesquisa nos municípios e devolve a fotografia que a página usa."""
    limpos = store.normalizar_filtros(filtros)
    limite = max(1, min(LIMITE_MAXIMO, int(limpos["limite"] or 25)))
    # O universo é o filtro inteiro (até ao limite da página): a tabela mostra as
    # primeiras `limite` linhas, mas os gráficos e os fornecedores precisam de
    # todos os municípios que o filtro apanha.
    resposta = municipios.listar(
        q=limpos["q"] or None,
        distrito=limpos["distrito"] or None,
        nuts=limpos["nuts"] or None,
        ano_contratos=limpos["ano_contratos"],
        ordenar=limpos["ordenar"] or "despesas",
        ordem=limpos["ordem"] or "desc",
        min_despesas=limpos["min_despesas"],
        size=LIMITE_MAXIMO,
        page=1,
    )
    if resposta.get("error") and not resposta.get("items"):
        return {
            "error": str(resposta["error"]),
            "filtros": limpos,
            "itens": [],
            "total": 0,
            "gerado_em": _agora(),
        }

    ano_contratos = resposta.get("ano_contratos") or limpos["ano_contratos"]
    universo: List[Dict[str, Any]] = list(resposta.get("items") or [])
    itens: List[Dict[str, Any]] = []
    for item in universo[:limite]:
        itens.append(
            {
                "nome": item.get("nome"),
                "geocod": item.get("geocod"),
                "distrito": item.get("distrito"),
                "ano_despesas": item.get("ano_despesas"),
                "despesas_total": item.get("despesas_total"),
                "despesas_pessoal": item.get("despesas_pessoal"),
                "contratos_total": item.get("contratos_total"),
                "contratos_valor": item.get("contratos_valor"),
                "contratos_ano_total": item.get("contratos_ano_total"),
                "contratos_ano_valor": item.get("contratos_ano_valor"),
                # Os anos mais recentes de cada município (Portal BASE): é o que
                # evita ler a tabela como se só existisse o ano escolhido.
                "anos_recentes": item.get("contratos_recentes") or [],
            }
        )

    ano_despesas = _ano_das_despesas(itens)
    adjudicatarios = _adjudicatarios(
        universo,
        ano_contratos,
        total_municipios=int(resposta.get("total") or 0),
    )

    return {
        "filtros": limpos,
        "descricao": descricao_dos_filtros(limpos),
        "total": int(resposta.get("total") or 0),
        "linhas": len(itens),
        "itens": itens,
        "ano_contratos": ano_contratos,
        "ano_despesas": ano_despesas,
        "despesas_somadas": resposta.get("despesas_somadas") or 0.0,
        "contratos_somados": resposta.get("contratos_somados") or 0.0,
        "contratos_ano_somados": resposta.get("contratos_ano_somados") or 0.0,
        "contratos_ano_total_somados": resposta.get("contratos_ano_total_somados") or 0,
        "distritos": resposta.get("distritos") or [],
        "adjudicatarios": adjudicatarios,
        "graficos": _graficos(universo, limpos, ano_contratos=ano_contratos, ano_despesas=ano_despesas),
        "origem": resposta.get("origem"),
        "gerado_em": _agora(),
        "fontes": [
            {
                "documento": municipios.INE_FONTE,
                "url": FONTE_DESPESAS_URL,
            },
            {
                "documento": municipios.CONTRATOS_FONTE,
                "url": "https://www.base.gov.pt/Base4/pt/resultados/",
            },
        ],
    }


def _adjudicatarios(
    universo: List[Dict[str, Any]],
    ano_contratos: Optional[int],
    *,
    total_municipios: int = 0,
) -> Dict[str, Any]:
    """Os maiores adjudicatários dos contratos dos municípios do filtro.

    A lista é lida do índice dos contratos (não do INE) e fica **guardada** com a
    página: é a fotografia do dia em que o editor a mandou ler, para a página
    publicada não mudar sozinha.
    """
    nomes: List[str] = []
    for item in universo:
        nomes += [str(nome) for nome in (item.get("adjudicantes") or []) if nome]
    dados = municipios.fornecedores_de_varios(nomes, ano=ano_contratos)
    if dados.get("error"):
        return {"ano": ano_contratos, "total": 0, "valor": 0.0, "itens": [], "error": dados["error"]}
    return {
        "ano": ano_contratos,
        "total": int(dados.get("total") or 0),
        "valor": float(dados.get("valor") or 0.0),
        "municipios": len(universo),
        "total_municipios": total_municipios or len(universo),
        "itens": (dados.get("itens") or [])[:ADJUDICATARIOS_MAXIMO],
    }


#: Quantos adjudicatários a página mostra (o resto continua no `total`).
ADJUDICATARIOS_MAXIMO = 20

#: Métricas dos gráficos por município, pela ordenação escolhida: a barra mostra
#: sempre o número que a tabela ordenou, para não haver duas leituras do mesmo.
_METRICAS_MUNICIPIO: Dict[str, Dict[str, str]] = {
    "pessoal": {"campo": "despesas_pessoal", "rotulo": "Despesa com pessoal"},
    "bens_servicos": {"campo": "despesas_bens_servicos", "rotulo": "Bens e serviços"},
    "capital": {"campo": "despesas_capital", "rotulo": "Despesa de capital"},
    "contratos": {"campo": "contratos_valor", "rotulo": "Valor contratado"},
    "contratos_total": {"campo": "contratos_total", "rotulo": "N.º de contratos"},
    "despesas": {"campo": "despesas_total", "rotulo": "Despesa total"},
}


def _graficos(
    universo: List[Dict[str, Any]],
    limpos: Dict[str, Any],
    *,
    ano_contratos: Optional[int],
    ano_despesas: Optional[int],
) -> List[Dict[str, Any]]:
    """As séries que a página desenha: municípios do topo, contratado e despesa por ano."""
    graficos: List[Dict[str, Any]] = []

    metrica = dict(_METRICAS_MUNICIPIO.get(str(limpos.get("ordenar") or "despesas")) or _METRICAS_MUNICIPIO["despesas"])
    do_ano = ano_contratos if metrica["campo"].startswith("contratos_") else None
    if do_ano:
        metrica["campo"] = metrica["campo"].replace("contratos_valor", "contratos_ano_valor").replace(
            "contratos_total", "contratos_ano_total"
        )
        metrica["rotulo"] += f" em {do_ano}"
    elif metrica["campo"] == "despesas_total" and ano_despesas:
        metrica["rotulo"] += f" {ano_despesas}"
    elif metrica["campo"].startswith("despesas_") and ano_despesas:
        metrica["rotulo"] += f" {ano_despesas}"

    barras = []
    for item in universo[:BARRAS_MAXIMO]:
        valor = _float(item.get(metrica["campo"]))
        if valor <= 0:
            continue
        barras.append(
            {
                "rotulo": str(item.get("nome") or ""),
                "valor": valor,
                "nota": _nota_da_barra(item, metrica["campo"], ano_contratos),
            }
        )
    if barras:
        graficos.append(
            {
                "id": "municipios",
                "titulo": "Municípios do filtro",
                "subtitulo": metrica["rotulo"],
                "unidade": "euros" if metrica["campo"] != "contratos_ano_total" and metrica["campo"] != "contratos_total" else "contratos",
                "itens": barras,
            }
        )

    anos_contratos = _por_ano(universo, "contratos_recentes")
    if len(anos_contratos) > 1:
        graficos.append(
            {
                "id": "anos_contratos",
                "titulo": "Contratado por ano",
                "subtitulo": f"{municipios.CONTRATOS_FONTE} · soma dos municípios do filtro",
                "unidade": "euros",
                "itens": anos_contratos,
            }
        )

    anos_despesas = _por_ano(universo, "despesas_por_ano")
    if len(anos_despesas) > 1:
        graficos.append(
            {
                "id": "anos_despesas",
                "titulo": "Despesa por ano",
                "subtitulo": f"{municipios.INE_FONTE} · soma dos municípios do filtro",
                "unidade": "euros",
                "itens": anos_despesas,
            }
        )
    return graficos


#: Quantas barras cada gráfico mostra.
BARRAS_MAXIMO = 12


def _por_ano(universo: List[Dict[str, Any]], campo: str) -> List[Dict[str, Any]]:
    """Soma uma série anual de todas as linhas (contratação ou despesa)."""
    totais: Dict[str, Dict[str, Any]] = {}
    for item in universo:
        if campo == "despesas_por_ano":
            for ano, valores in (item.get("despesas_por_ano") or {}).items():
                total = _float((valores or {}).get("D"))
                if total:
                    totais.setdefault(str(ano), {"rotulo": str(ano), "valor": 0.0})["valor"] += total
            continue
        for linha in item.get(campo) or []:
            ano = str(linha.get("ano") or "")
            if not ano:
                continue
            slot = totais.setdefault(ano, {"rotulo": ano, "valor": 0.0, "contratos": 0})
            slot["valor"] += _float(linha.get("valor"))
            slot["contratos"] = int(slot.get("contratos") or 0) + int(linha.get("contratos") or 0)
    return sorted(totais.values(), key=lambda item: str(item["rotulo"]))


def _nota_da_barra(item: Dict[str, Any], campo: str, ano_contratos: Optional[int]) -> Optional[str]:
    """O número que acompanha a barra (os contratos, quando a barra é um valor)."""
    if campo == "contratos_ano_total":
        return _euros_curto(item.get("contratos_ano_valor"))
    if campo == "contratos_total":
        return _euros_curto(item.get("contratos_valor"))
    if campo == "contratos_ano_valor":
        return f"{_numero(item.get('contratos_ano_total'))} contratos"
    if campo == "contratos_valor":
        return f"{_numero(item.get('contratos_total'))} contratos"
    if item.get("contratos_ano_valor") and ano_contratos:
        return f"{_euros_curto(item['contratos_ano_valor'])} contratado em {ano_contratos}"
    if item.get("contratos_valor"):
        return f"{_euros_curto(item['contratos_valor'])} contratado"
    return None


def _float(valor: Any) -> float:
    try:
        return float(valor or 0.0)
    except (TypeError, ValueError):
        return 0.0


def resumo_dos_dados(dados: Optional[Dict[str, Any]]) -> str:
    """Resumo factual da fotografia, para o painel do CMS e para a IA."""
    dados = dados if isinstance(dados, dict) else {}
    if not dados or dados.get("error"):
        return dados.get("error") or "Sem dados lidos."
    maior = (dados.get("adjudicatarios") or {}).get("itens") or []
    return (
        f"{int(dados.get('total') or 0)} municípios no filtro · "
        f"despesa {_euros_curto(dados.get('despesas_somadas'))} · "
        f"contratado {_euros_curto(dados.get('contratos_somados'))}"
        + (
            f" · em {dados.get('ano_contratos')}: "
            f"{_numero(dados.get('contratos_ano_total_somados'))} contratos, "
            f"{_euros_curto(dados.get('contratos_ano_somados'))}"
            if dados.get("ano_contratos")
            else ""
        )
        + (
            f" · {_numero((dados.get('adjudicatarios') or {}).get('total'))} adjudicatários, "
            f"o maior {maior[0].get('nome')} ({_euros_curto(maior[0].get('valor'))})"
            if maior
            else ""
        )
        + f" · {dados.get('descricao') or ''}"
    ).strip()


def _ano_das_despesas(itens: List[Dict[str, Any]]) -> Optional[int]:
    """Ano da despesa do INE, comum às linhas (é o que a tabela diz)."""
    anos = {str(item.get("ano_despesas")) for item in itens if item.get("ano_despesas")}
    if len(anos) == 1:
        try:
            return int(next(iter(anos)))
        except ValueError:
            return None
    return None


def _numero(valor: Any) -> str:
    try:
        return f"{int(valor or 0):,}".replace(",", " ")
    except (TypeError, ValueError):
        return "0"


def _euros_curto(valor: Any) -> str:
    try:
        numero = float(valor or 0)
    except (TypeError, ValueError):
        numero = 0.0
    if abs(numero) >= 1_000_000:
        return f"{numero / 1_000_000:.1f}".replace(".", ",") + " M€"
    if abs(numero) >= 1_000:
        return f"{numero / 1_000:.0f} mil €"
    return f"{numero:,.0f}".replace(",", " ") + " €"


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()
