"""Temas da plataforma para a pesquisa de notícias (`/news/themes`).

O índice `finance_news` junta notícias de duas origens: por **ticker** (o que o
mercado diz de um ativo) e por **tema** (o que o Yahoo devolve para uma
expressão). As duas alimentam o sentimento, a Pesquisa total e o RAG — mas quem
trabalha na plataforma quer outra pergunta: *o que saiu sobre contratos
públicos, fundos europeus ou insolvências?*

É isso que este catálogo responde. Cada tema é um conjunto **curado** de
expressões que se procuram no título, no resumo, na fonte, nos tópicos e nas
entidades das notícias (`multi_match` com `operator: and`), mais o **tema exato**
com que a notícia foi recolhida. Não há configuração a manter na base de dados:
o vocabulário vive aqui, com a revisão do código.

Porquê curado e não aprendido
-----------------------------
Um tema com palavras a mais enche a lista de ruído («concurso» traz concursos
de televisão); com palavras a menos, esconde metade do que interessa. As
expressões abaixo foram escolhidas por serem **específicas do que a plataforma
cobre** — contratação pública, contratos, fundos, subvenções, insolvências,
Administração Pública, empresas e fiscalidade — e são a única coisa a mexer
quando um tema trouxer resultados estranhos.

Acentos
-------
O `standard analyzer` do Elasticsearch não remove acentos: «contratação» e
«contratacao» são termos diferentes. Para uma notícia escrita sem acentos não
desaparecer, cada expressão é procurada nas duas formas (com e sem acentos) —
ver `match_terms`.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Optional

#: Os temas da plataforma, pela ordem em que a interface os mostra.
THEMES: List[Dict[str, Any]] = [
    {
        "id": "contratacao-publica",
        "label": "Contratação pública",
        "description": "Concursos, ajustes diretos, anúncios de procedimento e compras públicas (BASE, Vortal, TED).",
        "terms": [
            "contratação pública",
            "compras públicas",
            "ajuste direto",
            "concurso público",
            "anúncio de procedimento",
            "procedimento concursal",
            "public procurement",
        ],
        "tags": ["contratação pública", "compras públicas"],
        "category": "analises",
    },
    {
        "id": "contratos",
        "label": "Contratos e adjudicações",
        "description": "Adjudicações, contratos assinados, preços e alterações contratuais.",
        "terms": [
            "contrato público",
            "contratos públicos",
            "adjudicação",
            "adjudicatário",
            "preço base",
            "alteração contratual",
            "public contract",
        ],
        "tags": ["contratos", "adjudicações"],
        "category": "analises",
    },
    {
        "id": "fundos-europeus",
        "label": "Fundos europeus e PRR",
        "description": "Portugal 2030, PRR, fundos de coesão e dinheiro de Bruxelas.",
        "terms": [
            "fundos europeus",
            "plano de recuperação e resiliência",
            "quadro financeiro plurianual",
            "fundo de coesão",
            "next generation",
            "fundo europeu",
            "european funds",
        ],
        "tags": ["fundos europeus", "PRR"],
        "category": "analises",
    },
    {
        "id": "subvencoes",
        "label": "Subvenções e incentivos",
        "description": "Apoios, avisos de abertura, incentivos fiscais e financiamento público.",
        "terms": [
            "subvenção",
            "aviso de abertura",
            "incentivo financeiro",
            "apoio financeiro",
            "fundo de investimento",
            "financiamento público",
        ],
        "tags": ["subvenções", "incentivos"],
        "category": "analises",
    },
    {
        "id": "insolvencias",
        "label": "Insolvências e reestruturações",
        "description": "Insolvências, PER, recuperação de empresas e cessação de atividade.",
        "terms": [
            "insolvência",
            "processo de insolvência",
            "recuperação de empresas",
            "reestruturação de dívida",
            "liquidação da empresa",
            "cessação de atividade",
            "bankruptcy",
        ],
        "tags": ["insolvências", "risco"],
        "category": "mercado",
    },
    {
        "id": "administracao-publica",
        "label": "Administração Pública",
        "description": "Estado, autarquias, carreiras, remunerações e emprego público.",
        "terms": [
            "administração pública",
            "carreira geral",
            "tabela remuneratória",
            "remuneração base",
            "cargos dirigentes",
            "função pública",
            "setor público",
        ],
        "tags": ["administração pública", "remunerações"],
        "category": "analises",
    },
    {
        "id": "empresas",
        "label": "Empresas e grupos",
        "description": "Atos societários, contas, fusões, aquisições e participações.",
        "terms": [
            "atos societários",
            "registo comercial",
            "capital social",
            "fusão de empresas",
            "aquisição de participação",
            "grupo empresarial",
            "holding",
        ],
        "tags": ["empresas", "societário"],
        "category": "mercado",
    },
    {
        "id": "fiscalidade",
        "label": "Fiscalidade e orçamento",
        "description": "Orçamento do Estado, dívida pública, impostos e execução orçamental.",
        "terms": [
            "orçamento do estado",
            "dívida pública",
            "execução orçamental",
            "receita fiscal",
            "política fiscal",
            "receitas fiscais",
        ],
        "tags": ["fiscalidade", "orçamento"],
        "category": "analises",
    },
]

_BY_ID: Dict[str, Dict[str, Any]] = {theme["id"]: theme for theme in THEMES}


def _sem_acentos(text: str) -> str:
    """A mesma expressão escrita sem acentos (`contratação` → `contratacao`)."""
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def term_variants(term: str) -> List[str]:
    """Uma expressão e as suas formas equivalentes (sem acentos)."""
    variants = [term]
    plain = _sem_acentos(term)
    if plain != term:
        variants.append(plain)
    return variants


def list_themes() -> List[Dict[str, Any]]:
    """Catálogo completo (para a interface e para a documentação)."""
    return [
        {
            "id": theme["id"],
            "label": theme["label"],
            "description": theme["description"],
            "terms": list(theme["terms"]),
            "tags": list(theme["tags"]),
            "category": theme.get("category") or "",
        }
        for theme in THEMES
    ]


def theme_ids() -> List[str]:
    return [theme["id"] for theme in THEMES]


def get_theme(theme_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """Tema pelo identificador (aceita também o rótulo, com ou sem acentos)."""
    wanted = str(theme_id or "").strip().lower()
    if not wanted:
        return None
    chosen = _BY_ID.get(wanted)
    if chosen is None:
        plain = _sem_acentos(wanted)
        for theme in THEMES:
            if plain in {_sem_acentos(theme["id"]), _sem_acentos(theme["label"]).lower()}:
                chosen = theme
                break
    if chosen is None:
        return None
    return {
        "id": chosen["id"],
        "label": chosen["label"],
        "description": chosen["description"],
        "terms": list(chosen["terms"]),
        "tags": list(chosen["tags"]),
        "category": chosen.get("category") or "",
    }


def match_terms(theme_id: Optional[str]) -> List[str]:
    """Expressões a procurar no Elasticsearch, com as variantes sem acentos."""
    theme = _BY_ID.get(str(theme_id or "").strip().lower())
    if not theme:
        return []
    terms: List[str] = []
    for term in theme["terms"]:
        for variant in term_variants(term):
            if variant not in terms:
                terms.append(variant)
    return terms


def theme_buckets() -> List[Dict[str, Any]]:
    """Todos os temas com as suas expressões — para contar notícias por tema."""
    return [
        {"id": theme["id"], "label": theme["label"], "terms": match_terms(theme["id"])}
        for theme in THEMES
    ]


def suggested_tags(theme_id: Optional[str]) -> List[str]:
    """Etiquetas de blog sugeridas para um artigo criado a partir de um tema."""
    theme = _BY_ID.get(str(theme_id or "").strip().lower())
    return list(theme["tags"]) if theme else []


def suggested_category(theme_id: Optional[str]) -> str:
    """Slug da categoria de blog sugerida (`""` quando o tema não sugere nenhuma)."""
    theme = _BY_ID.get(str(theme_id or "").strip().lower())
    return str(theme.get("category") or "") if theme else ""


def slugify(value: str, limit: int = 60) -> str:
    """Endereço do artigo a partir do título da notícia (sem acentos)."""
    text = re.sub(r"[^a-z0-9]+", "-", _sem_acentos(str(value or "")).lower()).strip("-")
    return text[:limit].strip("-")
