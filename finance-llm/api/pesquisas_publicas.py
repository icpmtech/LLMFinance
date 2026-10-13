"""Páginas públicas de **pesquisa** sobre as despesas municipais.

Uma pesquisa publicada é uma **consulta congelada**: os filtros (texto, distrito,
ano da contratação, ordenação, limite) ficam guardados no documento do CMS e os
números são a fotografia lida quando o editor os mandou ler. O Portal BASE e o
INE mudam todos os dias; a página publicada só muda quando alguém a volta a ler
(`POST /cms/pesquisas/{id}/dados`) — como nas fichas de município.

- `opcoes()` — filtros disponíveis (distritos, anos de contratação, ordenações);
- `dados_da_pesquisa(filtros)` — corre a pesquisa no módulo dos municípios e
  devolve o que a página mostra: totais, linhas e proveniência;
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
    resposta = municipios.listar(
        q=limpos["q"] or None,
        distrito=limpos["distrito"] or None,
        nuts=limpos["nuts"] or None,
        ano_contratos=limpos["ano_contratos"],
        ordenar=limpos["ordenar"] or "despesas",
        ordem=limpos["ordem"] or "desc",
        min_despesas=limpos["min_despesas"],
        size=limite,
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
    itens: List[Dict[str, Any]] = []
    for item in resposta.get("items") or []:
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

    return {
        "filtros": limpos,
        "descricao": descricao_dos_filtros(limpos),
        "total": int(resposta.get("total") or 0),
        "linhas": len(itens),
        "itens": itens,
        "ano_contratos": ano_contratos,
        "ano_despesas": _ano_das_despesas(itens),
        "despesas_somadas": resposta.get("despesas_somadas") or 0.0,
        "contratos_somados": resposta.get("contratos_somados") or 0.0,
        "contratos_ano_somados": resposta.get("contratos_ano_somados") or 0.0,
        "contratos_ano_total_somados": resposta.get("contratos_ano_total_somados") or 0,
        "distritos": resposta.get("distritos") or [],
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


def resumo_dos_dados(dados: Optional[Dict[str, Any]]) -> str:
    """Resumo factual da fotografia, para o painel do CMS e para a IA."""
    dados = dados if isinstance(dados, dict) else {}
    if not dados or dados.get("error"):
        return dados.get("error") or "Sem dados lidos."
    return (
        f"{int(dados.get('total') or 0)} municípios no filtro · "
        f"despesa {_euros_curto(dados.get('despesas_somadas'))} · "
        f"contratado {_euros_curto(dados.get('contratos_somados'))}"
        + (
            f" · em {dados.get('ano_contratos')}: "
            f"{int(dados.get('contratos_ano_total_somados') or 0)} contratos, "
            f"{_euros_curto(dados.get('contratos_ano_somados'))}"
            if dados.get("ano_contratos")
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
