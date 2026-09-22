"""Hermes — o assistente de investigação do IQ OS.

Recebe uma pergunta em linguagem natural, planeia-a (tema, entidades, tickers,
NIF) e recolhe evidências nas fontes da plataforma através do meta-modelo da
Pesquisa 360. Depois redige uma resposta **citada** com o modelo de IA
configurado (modelo predefinido da conta ou chave em variável de ambiente).

Sem modelo disponível, o Hermes responde na mesma em modo **factual**: só
contagens, títulos, ligações e indicadores, tal como devolvidos pelas fontes,
sem interpretação.

Modos de investigação:

- `rapida` — uma recolha nas fontes da plataforma e uma resposta curta;
- `profunda` — decompõe a pergunta em sub-perguntas, recolhe para cada uma
  (alargando as fontes a indicadores e investigação) e junta tudo na resposta.

Rotas em `api/hermes_routes.py` (`GET /hermes/meta`, `POST /hermes/ask`).
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
import unicodedata
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence
from uuid import uuid4

from api import search360_service as search360
from api import search360_sources as search_sources

logger = logging.getLogger(__name__)

MAX_QUESTION_CHARS = 2000
MAX_EVIDENCE = 18
MAX_SUBSTEPS = 4
MAX_HISTORY = 8
METRICS_TIMEOUT = 14.0
FACTS_TIMEOUT = 30.0
# As agregações dos contratos são pesadas a frio (primeira consulta depois de
# arrancar o Elasticsearch); não podem perder-se por 30 segundos.
FACTS_TIMEOUT_HEAVY = 50.0

# Itens de factos: pontuação alta para entrarem primeiro nas citações [n].
FACT_SOURCE = "Plataforma IQ OS · factos"
FACT_SCORE = 100.0
FACT_SCORE_DOCUMENT = 40.0
FACT_ENTITY_LIMIT = 6
FACT_OBJECT_LIMIT = 3
FACT_DOCUMENT_LIMIT = 4
FACT_DOCUMENT_CANDIDATES = 8
FACT_DOCUMENT_MIN_SCORE = 0.2

# Palavras que não distinguem o tema (aparecem em quase todas as perguntas).
FACT_NOISE_WORDS = (
    "portugal",
    "portugues",
    "portuguesa",
    "portuguesas",
    "portugueses",
    "iq",
    "os",
    "dados",
    "maior",
    "maiores",
    "menor",
    "menores",
    "principal",
    "principais",
    "total",
    "quais",
    "quanto",
    "quantos",
)

DEPTHS: List[Dict[str, Any]] = [
    {
        "id": "rapida",
        "label": "Resposta rápida",
        "description": "Uma recolha nas fontes da plataforma e uma resposta curta com citações.",
        "sources": ["internal", "documents", "wikipedia_pt", "wikidata"],
        "limit": 5,
        "subquestions": False,
        "max_tokens": 1200,
    },
    {
        "id": "profunda",
        "label": "Investigação profunda",
        "description": "Decompõe a pergunta em sub-perguntas, alarga as fontes e junta indicadores.",
        "sources": [
            "internal",
            "documents",
            "wikipedia_pt",
            "wikipedia_en",
            "wikidata",
            "worldbank",
            "dadosgov",
            "openalex",
        ],
        "limit": 6,
        "subquestions": True,
        "max_tokens": 2200,
    },
]
DEPTH_BY_ID = {item["id"]: item for item in DEPTHS}
DEFAULT_DEPTH = "rapida"

SYSTEM = (
    "És o Hermes, o assistente de investigação do IQ OS. Respondes em português de Portugal e usas "
    "**apenas** as evidências numeradas que te são dadas, citando sempre no formato [n]. "
    "Nunca inventas números, datas, nomes nem ligações: o que não estiver nas evidências é declarado "
    "explicitamente como não encontrado nas fontes consultadas.\n"
    "Estrutura a resposta assim:\n"
    "1) Resposta direta (2 a 4 frases).\n"
    "2) Dados da plataforma IQ OS (contratos, empresas, documentos, notícias), com números e citações.\n"
    "3) Evidência externa (enciclopédia, dados abertos, investigação), com citações.\n"
    "4) Indicadores quantitativos, se existirem.\n"
    "5) Lacunas e próximos passos sugeridos.\n"
    "Quando existirem «factos calculados da plataforma» (agregações exatas dos contratos públicos, objetos da "
    "ontologia do IQ OS ou trechos de documentos indexados), trata-os como os números oficiais da plataforma e "
    "dá-lhes prioridade sobre as fontes externas.\n"
    "Máximo 420 palavras, em texto simples: sem markdown, apenas listas com «-» quando for útil."
)


# --------------------------------------------------------------------------
# Preparação da pergunta
# --------------------------------------------------------------------------
def _text(value: Any, *, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _fold(value: Any) -> str:
    """Minúsculas sem acentos (para procurar palavras nos trechos dos documentos)."""
    text = unicodedata.normalize("NFD", str(value or ""))
    return "".join(char for char in text if unicodedata.category(char) != "Mn").lower()


def _plural(count: int, singular: str, plural: str) -> str:
    return singular if count == 1 else plural


def clean_question(value: Any) -> str:
    return _text(value, limit=MAX_QUESTION_CHARS)


# Palavras vazias em português (e inglês) para extrair o tema da pergunta.
TOPIC_STOPWORDS = {
    "o", "a", "os", "as", "um", "uma", "uns", "umas", "de", "da", "do", "das", "dos", "em", "no", "na", "nos",
    "nas", "por", "para", "com", "sem", "sobre", "que", "quais", "qual", "quem", "como", "onde", "quando",
    "quanto", "quantos", "quantas", "e", "ou", "é", "são", "ser", "estar", "tem", "têm", "há", "mais", "menos",
    "se", "ao", "aos", "à", "às", "pelo", "pela", "seus", "suas", "este", "esta", "esse", "essa", "diz",
    "the", "of", "and", "for", "with", "in", "about", "is", "are", "what", "which", "who", "how", "many", "much",
}


def _topic_of(question: str, keywords: Optional[Sequence[str]] = None) -> str:
    """Tema curto e em minúsculas (sem palavras vazias) para as sub-perguntas."""
    base = question.strip(" .?!:;")
    lowered = base.lower()
    for prefix in (
        "o que é que",
        "o que é",
        "quem é que",
        "quem é",
        "qual é",
        "quais são",
        "diz-me",
        "diz me",
        "explica-me",
        "explica me",
        "fala-me sobre",
        "fala me sobre",
        "resume",
        "resumo de",
        "investiga",
        "pesquisa",
        "analisa",
    ):
        if lowered.startswith(prefix):
            base = base[len(prefix) :].strip(" :,.?!")
            break
    tokens = [token for token in re.split(r"[^\w%.-]+", base) if token and token.lower() not in TOPIC_STOPWORDS]
    if not tokens and keywords:
        tokens = [str(word).strip("?.!") for word in keywords if str(word).strip("?.!").lower() not in TOPIC_STOPWORDS]
    topic = " ".join(tokens[:6])
    if not topic:
        topic = " ".join(base.split()[:6])
    if topic:
        topic = topic[0].lower() + topic[1:]
    return topic or question


def _subquestions(topic: str, *, limit: int = MAX_SUBSTEPS) -> List[Dict[str, str]]:
    """Decomposição determinística da pergunta (sem modelo, sempre disponível)."""
    def with_word(word: str) -> str:
        return topic if word in topic.lower() else f"{topic} {word}"

    return [
        {"id": "contexto", "question": topic, "focus": "Contexto e definição"},
        {"id": "plataforma", "question": with_word("contratos"), "focus": "Dados do IQ OS"},
        {"id": "numeros", "question": with_word("indicadores"), "focus": "Indicadores e números"},
        {"id": "evidencia", "question": with_word("estudo"), "focus": "Evidência externa"},
    ][:limit]


# Raízes que indicam perguntas sobre os dados estruturados de contratos públicos.
CONTRACT_TERMS = (
    "contrat",
    "adjudic",
    "concurso",
    "licita",
    "fornecedor",
    "cpv",
    "públic",
    "public",
    "empresa",
    "setor",
    "preç",
    "valor",
)


def _money(value: Any) -> str:
    """Formata euros de forma legível (milhares, M€, mM€)."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "n/d"
    if abs(number) >= 1e9:
        return f"{number / 1e9:.2f} mM€"
    if abs(number) >= 1e6:
        return f"{number / 1e6:.2f} M€"
    if abs(number) >= 1e3:
        return f"{number / 1e3:.1f} mil€"
    return f"{number:.0f} €"


def _count(value: Any) -> str:
    """Contagem com separador de milhares (espaço, como em português)."""
    try:
        return f"{int(value):,}".replace(",", " ")
    except (TypeError, ValueError):
        return str(value)


def _fact_item(
    *,
    title: str,
    kind: str,
    snippet: Optional[str] = None,
    url: Optional[str] = None,
    source: str = FACT_SOURCE,
    score: float = FACT_SCORE,
) -> Dict[str, Any]:
    """Item de evidência para um facto calculado na plataforma."""
    return {
        "id": "fact-" + re.sub(r"[^a-z0-9]+", "-", title.lower())[:60].strip("-"),
        "source_id": "platform_facts",
        "source_label": source,
        "source_family": "internal",
        "kind": kind,
        "title": title,
        "snippet": (snippet or "")[:400] or None,
        "url": url,
        "date": None,
        "score": score,
    }


def _fact_keywords(question: str, plan: Dict[str, Any], *, limit: int = 3) -> List[str]:
    """Palavras distintivas da pergunta (sem termos de contratos nem palavras vazias)."""
    words = [str(word) for word in (plan.get("keywords") or [])] or re.split(r"[^\w%.-]+", question)
    out: List[str] = []
    for word in words:
        token = word.strip("?.!,;:").lower()
        if len(token) < 4 or token in TOPIC_STOPWORDS:
            continue
        if any(token.startswith(term) for term in CONTRACT_TERMS):
            continue
        if any(token.startswith(noise) for noise in FACT_NOISE_WORDS):
            continue
        if token not in out:
            out.append(token)
        if len(out) >= limit:
            break
    return out


def _has_word(text: str, terms: Sequence[str]) -> bool:
    """Termo inteiro no texto (evita «documentação» casar com «ação»)."""
    if not terms:
        return False
    pattern = r"\b(" + "|".join(re.escape(term) for term in terms) + r")\b"
    return re.search(pattern, text.lower()) is not None


def _has_stem(text: str, terms: Sequence[str]) -> bool:
    """Raiz de palavra no início de uma palavra (contrat → contratos, contratual)."""
    if not terms:
        return False
    pattern = r"\b(" + "|".join(re.escape(term) for term in terms) + r")"
    return re.search(pattern, text.lower()) is not None


def _wants_contracts(question: str, plan: Dict[str, Any]) -> bool:
    # Total global: pergunta geral sobre a plataforma de contratos sem filtro concreto.
    if _wants_general_total(question, plan):
        return True
    return bool(plan.get("nifs")) or _has_stem(question, CONTRACT_TERMS)


# Termos que indicam perguntas sobre mercados (cotações, notícias de um ticker).
MARKET_TERMS = (
    "acao",
    "ação",
    "acoes",
    "ações",
    "cotacao",
    "cotação",
    "bolsa",
    "ticker",
    "preco",
    "preço",
    "subiu",
    "desceu",
    "valorizou",
    "desvalorizou",
    "performance",
    "mercado",
)

# Termos que indicam perguntas sobre a própria plataforma (metamodelo).
PLATFORM_TERMS = (
    "iq os",
    "plataforma",
    "ontologia",
    "modulo",
    "módulo",
    "aplicacao",
    "aplicação",
    "ferramenta",
    "funcionalidade",
    "que dados",
    "indice",
    "índice",
    "indices",
    "índices",
)

# Termos que pedem os contratos de maior valor (com nome e montante).
BIGGEST_TERMS = ("maior", "maiores", "mais caro", "mais caros", "mais elevado", "mais alto", "top")

EXTRA_KIND_LABELS = {"contract": "Contratos", "metric": "Métricas", "entity": "Entidades"}

# Módulos que o Hermes descreve quando lhe perguntam o que é o IQ OS.
PLATFORM_MODULES = (
    ("Chat IA", "conversar com os modelos, com ferramentas de mercado e de contratos"),
    ("EmpresasIQ", "inteligência contratual: empresas, relações, mapa e grafo"),
    ("Ontologia", "camada semântica: tipos de objeto, propriedades, ligações e ações"),
    ("Visualizador", "BI: métricas, gráficos e dashboards"),
    ("Sentimento", "análise de sentimento da recolha, notícias, dossiês e documentos"),
    ("Pesquisa 360", "pesquisa federada com dossiê, biblioteca e grafo"),
    ("Hermes", "assistente de investigação com resposta citada e skills"),
    ("Office", "documentos em Markdown: notas, relatórios e dossiês"),
    ("Email", "caixa de correio IMAP/SMTP"),
    ("CRM", "contas, contactos, agenda e oportunidades"),
    ("Recolha", "recolha de dados de sites, com execuções e agendamentos"),
    ("Contratos ES", "contratos públicos de Espanha"),
    ("Finder", "explorador dos dados da plataforma"),
    ("Mercados", "cotações, notícias e indicadores por ticker"),
    ("Browser", "navegador dentro da plataforma"),
)

_ticker_cache: Dict[str, Any] = {"at": 0.0, "tickers": []}


def _kind_label(kind: Any) -> str:
    key = str(kind or "document")
    if key in EXTRA_KIND_LABELS:
        return EXTRA_KIND_LABELS[key]
    try:
        return search360.kind_label(key)
    except Exception:
        return key


def _entity_name(value: Any) -> str:
    """Nome legível das partes de um contrato (`adjudicantes`/`adjudicatarios`).

    O campo pode vir como lista de strings, lista de dicionários com `parsed`
    (lista de `{nif, nome}`) e/ou `raw` — é o mesmo formato que o RAG usa.
    """
    parties = value if isinstance(value, list) else [value]
    names: List[str] = []
    for party in parties:
        if isinstance(party, str):
            names.append(party)
            continue
        if not isinstance(party, dict):
            continue
        parsed = party.get("parsed")
        parsed_rows = parsed if isinstance(parsed, list) else [parsed] if isinstance(parsed, dict) else []
        for row in parsed_rows:
            if isinstance(row, dict) and row.get("nome"):
                names.append(str(row["nome"]))
        if not parsed_rows:
            raw = party.get("raw")
            if isinstance(raw, str):
                names.append(raw)
            elif isinstance(raw, list):
                names.extend(str(item) for item in raw if isinstance(item, str))
    clean = [name.strip() for name in names if str(name).strip()]
    return "; ".join(dict.fromkeys(clean)) or "n/d"


def _search_term(question: str, topic: str, plan: Dict[str, Any]) -> str:
    """Termo para a recolha federada: NIF/ticker exatos, senão as palavras distintivas."""
    nifs = [nif for nif in (plan.get("nifs") or []) if nif]
    if nifs:
        return nifs[0]
    tickers = [str(ticker) for ticker in (plan.get("tickers") or []) if ticker]
    if tickers:
        return tickers[0]
    return topic or question


def _wants_market(question: str) -> bool:
    return _has_word(question, MARKET_TERMS)


def _wants_platform(question: str) -> bool:
    return _has_word(question, PLATFORM_TERMS)


def _wants_biggest(question: str) -> bool:
    return _has_word(question, BIGGEST_TERMS)


# Perguntas sobre totais globais da plataforma (ex.: "quantos contratos temos",
# "qual o valor total", "totais dos contratos"). Nestes casos a agregação deve
# cobrir **todos** os contratos indexados em vez de filtrar pelas keywords.
GENERAL_TOTAL_TERMS = (
    "total", "totais", "global", "geral", "quantos", "quanto", "qual o valor",
    "valor total", "valor agregado", "montante total", "número total",
    "numero total", "quantos contratos", "quantas empresas",
)


def _wants_general_total(question: str, plan: Dict[str, Any]) -> bool:
    """True quando a pergunta pede totais agregados sem filtro semântico/especifico."""
    low = question.lower()
    # Evitar falsos positivos em perguntas que já trazem um filtro concreto.
    for neg in (
        "edp",
        "ctt",
        "galp",
        "nos",
        "mota-engil",
        "infraestruturas",
        "saúde",
        "saude",
        "setor",
        "cpv",
        "ano",
        "202",
        "2023",
        "2024",
        "2025",
    ):
        if neg in low:
            return False
    # Se o plano tem tickers ou NIF, é uma pergunta entidade-especifica.
    if plan.get("tickers") or plan.get("nifs"):
        return False
    return _has_word(question, GENERAL_TOTAL_TERMS) or _has_stem(
        question, ("quantos contrato", "quanto contrato", "total contrato")
    )


def _indexed_tickers() -> List[str]:
    """Tickers com notícias indexadas na plataforma (cache de 10 minutos)."""
    now = time.time()
    if _ticker_cache["tickers"] and now - float(_ticker_cache["at"]) < 600:
        return list(_ticker_cache["tickers"])
    try:
        from api.elasticsearch_client import get_es_client  # noqa: PLC0415

        client = get_es_client()
        if client:
            resp = client.search(
                index="finance_news",
                body={"size": 0, "aggs": {"t": {"terms": {"field": "ticker", "size": 200}}}},
            )
            tickers = [str(bucket["key"]) for bucket in resp["aggregations"]["t"]["buckets"]]
            if tickers:
                _ticker_cache.update({"at": now, "tickers": tickers})
    except Exception as exc:
        logger.info("Hermes: tickers indexados indisponíveis: %s", exc)
    return list(_ticker_cache["tickers"])


def _resolve_ticker(value: str) -> str:
    """Ticker dos índices da plataforma para o símbolo mencionado (EDP → EDP.LS)."""
    clean = str(value or "").strip().upper()
    if not clean:
        return ""
    stored = _indexed_tickers()
    for ticker in stored:
        if ticker.upper() == clean:
            return ticker
    for ticker in stored:
        if ticker.upper().split(".")[0] == clean:
            return ticker
    return clean


def _market_candidates(question: str, plan: Dict[str, Any]) -> List[str]:
    """Tickers a que a pergunta se refere (só quando fala de mercados).

    Se a pergunta é claramente sobre contratos/empresas públicas, o ticker serve
    para filtrar contratos, não para ir buscar cotações de bolsa.
    """
    if not _wants_market(question):
        return []
    if _has_stem(question, CONTRACT_TERMS) and not _has_stem(question, MARKET_TERMS):
        return []
    from api.tools import extract_tickers  # noqa: PLC0415

    found = [*(plan.get("tickers") or []), *extract_tickers(question)]
    return [str(item) for item in dict.fromkeys(found) if str(item).strip()][:2]


def _history_prompt(history: Optional[Sequence[Dict[str, Any]]]) -> str:
    rows: List[str] = []
    for entry in list(history or [])[-MAX_HISTORY:]:
        role = str(entry.get("role") or "").lower()
        content = _text(entry.get("content"), limit=600)
        if not content:
            continue
        rows.append(f"{'Utilizador' if role == 'user' else 'Hermes'}: {content}")
    return "\n".join(rows)


# --------------------------------------------------------------------------
# Evidências
# --------------------------------------------------------------------------
def _evidence_of(payload: Dict[str, Any], *, start: int) -> List[Dict[str, Any]]:
    items = sorted(payload.get("items") or [], key=lambda entry: -float(entry.get("score") or 0))
    out: List[Dict[str, Any]] = []
    for item in items:
        out.append(
            {
                "n": start + len(out),
                "id": item.get("id"),
                "title": item.get("title") or "(sem título)",
                "subtitle": item.get("subtitle"),
                "source": item.get("source_label") or item.get("source_id"),
                "source_id": item.get("source_id"),
                "source_family": item.get("source_family"),
                "kind": item.get("kind"),
                "date": item.get("date"),
                "url": item.get("url"),
                "snippet": (item.get("snippet") or "")[:400] or None,
                "score": float(item.get("score") or 0),
                "also_in": item.get("also_in") or [],
            }
        )
    return out


def _dedupe_evidence(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Mantém a primeira ocorrência de cada título/ligação e renumera."""
    seen: set[str] = set()
    out: List[Dict[str, Any]] = []
    for row in rows:
        key = re.sub(r"[^a-z0-9]+", "", str(row.get("title") or "").lower())[:70]
        url = str(row.get("url") or "")
        if key in seen or (url and url in seen):
            continue
        if key:
            seen.add(key)
        if url:
            seen.add(url)
        out.append(row)
    for position, row in enumerate(out, start=1):
        row["n"] = position
    return out


def _evidence_prompt(evidence: Sequence[Dict[str, Any]]) -> List[str]:
    lines: List[str] = []
    for entry in evidence:
        parts = [f"({entry.get('source')} · {_kind_label(entry.get('kind'))}"]
        if entry.get("date"):
            parts.append(f" · {entry['date']}")
        parts.append(")")
        line = f"[{entry['n']}] {' '.join(parts)} {entry.get('title')}"
        if entry.get("snippet"):
            line += f" — {entry['snippet']}"
        if entry.get("url"):
            line += f" <{entry['url']}>"
        lines.append(line)
    return lines


def _metrics_prompt(metrics: Sequence[Dict[str, Any]]) -> List[str]:
    lines: List[str] = []
    for entry in metrics:
        lines.append(
            f"- {entry.get('label')} ({entry.get('country')}): "
            f"{entry['first']['value']:.2f} em {entry['first']['year']} → "
            f"{entry['last']['value']:.2f} em {entry['last']['year']}"
        )
    return lines


def _prompt(
    question: str,
    topic: str,
    evidence: Sequence[Dict[str, Any]],
    metrics: Sequence[Dict[str, Any]],
    history: Optional[Sequence[Dict[str, Any]]],
    steps: Sequence[Dict[str, Any]],
    facts: Sequence[str] = (),
    skill_block: str = "",
) -> str:
    lines = [f"Pergunta do utilizador: {question}"]
    if skill_block:
        lines += ["", skill_block]
    previous = _history_prompt(history)
    if previous:
        lines += ["", "Conversa anterior (contexto, não são evidências):", previous]
    if len(steps) > 1:
        lines += ["", "Sub-perguntas investigadas:"]
        lines += [f"- {row['focus']} («{row['question']}»): {row['items']} resultados" for row in steps]
    if facts:
        lines += ["", "Factos calculados da plataforma (dados exatos do IQ OS):", *facts]
    lines += ["", "Evidências:"]
    lines += _evidence_prompt(evidence) or ["(nenhuma evidência encontrada)"]
    numbers = _metrics_prompt(metrics)
    if numbers:
        lines += ["", "Indicadores:", *numbers]
    lines += [
        "",
        f"Responde à pergunta sobre «{topic}» seguindo a estrutura pedida e citando [n].",
    ]
    return "\n".join(lines)


def _factual_answer(
    question: str,
    evidence: Sequence[Dict[str, Any]],
    metrics: Sequence[Dict[str, Any]],
    per_source: Sequence[Dict[str, Any]],
    steps: Sequence[Dict[str, Any]],
    facts: Sequence[str] = (),
) -> str:
    """Resposta sem modelo: só o que as fontes devolveram, sem interpretação."""
    sources_with_items = [row for row in per_source if row.get("items")]
    blocks = [
        f"Resposta factual a «{question}»: {len(evidence)} "
        f"{_plural(len(evidence), 'evidência', 'evidências')} em "
        f"{len(sources_with_items)} de {len(per_source)} "
        f"{_plural(len(per_source), 'fonte', 'fontes')} com resultados."
    ]
    if facts:
        blocks.append("Factos calculados da plataforma:\n" + "\n".join(facts[:14]))
    if len(steps) > 1:
        blocks.append(
            "Sub-perguntas: "
            + "; ".join(f"{row['focus']} ({row['items']} resultados)" for row in steps)
            + "."
        )
    by_kind: Dict[str, List[Dict[str, Any]]] = {}
    for entry in evidence:
        by_kind.setdefault(str(entry.get("kind") or "document"), []).append(entry)
    for kind, rows in sorted(by_kind.items(), key=lambda pair: -len(pair[1])):
        label = _kind_label(kind)
        titles = "; ".join(f"[{row['n']}] {str(row.get('title'))[:70]}" for row in rows[:5])
        blocks.append(f"{label} ({len(rows)}): {titles}.")
    for entry in metrics:
        blocks.append(
            f"{entry.get('label')} ({entry.get('country')}): "
            f"{entry['first']['value']:.2f} em {entry['first']['year']} → "
            f"{entry['last']['value']:.2f} em {entry['last']['year']}."
        )
    empty = [str(row.get("label")) for row in per_source if not row.get("items")]
    if empty:
        blocks.append("Fontes sem resultados: " + ", ".join(empty) + ".")
    blocks.append(
        "Texto montado sem modelo de IA: apenas contagens, títulos e indicadores, tal como devolvidos pelas fontes."
    )
    return "\n\n".join(blocks)


def _followups(
    topic: str,
    plan: Dict[str, Any],
    per_source: Sequence[Dict[str, Any]],
) -> List[str]:
    out: List[str] = []
    for nif in (plan.get("nifs") or [])[:2]:
        out.append(f"Dossiê da empresa com NIF {nif}")
    for ticker in (plan.get("tickers") or [])[:2]:
        out.append(f"Resumo de mercado do ticker {ticker}")
    out.append(f"Contratos públicos — {topic}")
    out.append(f"Principais intervenientes — {topic}")
    out.append(f"Indicadores e números — {topic}")
    empty = [str(row.get("label")) for row in per_source if not row.get("items")]
    if empty:
        out.append("Sem resultados em: " + ", ".join(empty[:3]))
    return out[:5]


# --------------------------------------------------------------------------
# Recolha
# --------------------------------------------------------------------------
# Factos calculados na plataforma (contratos, ontologia e documentos)
#
# A recolha federada é pesquisa de texto; estes factos usam as capacidades
# **estruturadas** do IQ OS (agregações dos contratos, objetos canónicos da
# ontologia e trechos dos documentos indexados) para o Hermes poder responder
# com números exatos em vez de só com títulos.
# --------------------------------------------------------------------------
def _contract_role(question: str) -> str:
    """Papel pedido na pergunta (adjudicatário, adjudicante ou ambos).

    «contratos com o Estado» são contratos em que o Estado é o **adjudicante**:
    quem tem mais contratos é a empresa **adjudicatária** (o fornecedor).
    """
    if _has_stem(question, ("adjudicatári", "adjudicatario", "fornecedor", "concorrente")):
        return "adjudicatario"
    if _has_word(question, ("adjudicante", "adjudicantes")) or _has_stem(
        question, ("entidade publica", "entidade pública", "quem contrata")
    ):
        return "adjudicante"
    if _has_word(question, ("estado", "administracao publica", "administração pública")):
        return "adjudicatario"
    return "all"


def _nif_of(value: Any) -> Optional[str]:
    match = re.match(r"\s*(\d{9})", str(value or ""))
    return match.group(1) if match else None


def _company_name(nif: str) -> Optional[str]:
    """Nome da empresa a partir do NIF (diretório de empresas)."""
    from api.elasticsearch_client import search_companies  # noqa: PLC0415

    try:
        payload = search_companies(q=str(nif), size=3, min_contracts=1)
    except Exception as exc:
        logger.info("Hermes: nome da empresa %s indisponível: %s", nif, exc)
        return None
    rows = [row for row in (payload.get("items") or []) if str(row.get("nif")) == str(nif)]
    rows = rows or (payload.get("items") or [])
    name = str(rows[0].get("name") or "").strip() if rows else ""
    return name or None


def _biggest_contracts(keywords: Sequence[str], *, limit: int = 4) -> tuple:
    """Contratos de maior valor (objeto, montante, adjudicante e adjudicatário)."""
    from api.elasticsearch_client import search_contracts  # noqa: PLC0415

    payload = search_contracts(q=" ".join(keywords) or None, sort_by="precoContratual", sort_order="desc", size=limit)
    rows = payload.get("items") or []
    facts: List[str] = []
    items: List[Dict[str, Any]] = []
    for row in rows:
        value = row.get("precoContratual")
        try:
            if value is None or float(value) <= 0:
                continue
        except (TypeError, ValueError):
            continue
        objecto = _text(row.get("objectoContrato"), limit=120) or "(sem objeto)"
        adjudicante = _entity_name(row.get("adjudicantes"))
        adjudicatario = _entity_name(row.get("adjudicatarios"))
        ident = row.get("idcontrato")
        published = _text(row.get("dataPublicacao"), limit=10)
        facts.append(
            f"- «{objecto}» — {_money(value)}; adjudicante: {adjudicante}; adjudicatário: {adjudicatario}"
            + (f"; publicado em {published}" if published else "")
            + (f" (id {ident})." if ident else ".")
        )
        items.append(
            _fact_item(
                title=f"{objecto} — {_money(value)}",
                kind="contract",
                snippet=f"{adjudicante} → {adjudicatario}" + (f" · id {ident}" if ident else ""),
                url=f"/contracts-list/{ident}" if ident else "/contracts/dashboard",
                source="Contratos públicos · maiores valores",
            )
        )
    return facts, items


def _entity_facts(question: str, plan: Dict[str, Any], *, limit: int = FACT_ENTITY_LIMIT) -> Dict[str, Any]:
    """Ranking de empresas dos contratos públicos, com nomes (diretório de empresas)."""
    from api.elasticsearch_client import search_companies  # noqa: PLC0415

    nifs = [nif for nif in (plan.get("nifs") or []) if nif]
    if nifs:
        # NIF concreto: ficha da empresa, com o papel de cada lado.
        nif = nifs[0]
        payload = search_companies(q=nif, size=5, min_contracts=1)
        rows = [row for row in (payload.get("items") or []) if str(row.get("nif")) == str(nif)]
        if not rows:
            rows = (payload.get("items") or [])[:1]
        if not rows:
            return {"facts": [], "items": [], "warnings": [], "stats": {"nif": nif}}
        row = rows[0]
        name = str(row.get("name") or nif)
        facts = [f"Ficha da empresa (diretório de empresas do IQ OS):"]
        facts.append(
            f"- {name} (NIF {row.get('nif') or nif}): {_count(row.get('contracts_total'))} contratos públicos, "
            f"{_money(row.get('total_value'))} no total."
        )
        for role, label in (("adjudicante", "como adjudicante"), ("adjudicatario", "como adjudicatário")):
            summary = row.get(role)
            if isinstance(summary, dict) and summary.get("contracts_count"):
                years = ""
                if summary.get("first_year") and summary.get("last_year"):
                    years = f" ({summary['first_year']}–{summary['last_year']})"
                facts.append(
                    f"- {label}: {_count(summary.get('contracts_count'))} contratos, "
                    f"{_money(summary.get('total_value'))}{years}."
                )
        items = [
            _fact_item(
                title=f"{name} — {_count(row.get('contracts_total'))} contratos · {_money(row.get('total_value'))}",
                kind="entity",
                snippet=f"NIF {row.get('nif') or nif} · valores agregados dos contratos indexados.",
                url=f"/companies/{row.get('nif') or nif}",
                source="Plataforma IQ OS · empresas",
            )
        ]
        return {"facts": facts, "items": items, "warnings": [], "stats": {"nif": nif}}

    role = _contract_role(question)
    payload = search_companies(role=role, size=max(limit * 2, 12), min_contracts=1)
    if payload.get("error"):
        return {"facts": [], "items": [], "warnings": [f"Empresas: {payload['error']}"], "stats": {}}
    rows = [row for row in (payload.get("items") or []) if row.get("nif")]
    if not rows:
        return {"facts": [], "items": [], "warnings": [], "stats": {"empresas": 0}}

    role_label = {"adjudicatario": "adjudicatárias", "adjudicante": "adjudicantes (entidades públicas)"}.get(
        role, "adjudicantes e adjudicatárias"
    )
    by_value = sorted(rows, key=lambda row: (row.get("total_value") or 0, row.get("contracts_total") or 0), reverse=True)
    by_count = sorted(rows, key=lambda row: (row.get("contracts_total") or 0, row.get("total_value") or 0), reverse=True)

    facts: List[str] = [
        f"Empresas {role_label} com mais valor contratado (diretório de empresas do IQ OS, "
        f"{_count(payload.get('total') or len(rows))} no total):"
    ]
    items: List[Dict[str, Any]] = []
    for row in by_value[:limit]:
        nif = row.get("nif")
        name = str(row.get("name") or nif)
        facts.append(
            f"- {name} (NIF {nif}): {_count(row.get('contracts_total'))} contratos, {_money(row.get('total_value'))}."
        )
        items.append(
            _fact_item(
                title=f"{name} — {_count(row.get('contracts_total'))} contratos · {_money(row.get('total_value'))}",
                kind="entity",
                snippet=f"NIF {nif} · valores agregados dos contratos públicos indexados no IQ OS.",
                url=f"/companies/{nif}",
                source="Plataforma IQ OS · empresas",
            )
        )

    facts.append("Empresas com mais contratos (número):")
    for row in by_count[:limit]:
        facts.append(
            f"- {str(row.get('name') or row.get('nif'))}: {_count(row.get('contracts_total'))} contratos, "
            f"{_money(row.get('total_value'))}."
        )
    return {
        "facts": facts,
        "items": items,
        "warnings": [],
        "stats": {"empresas": int(payload.get("total") or len(rows)), "papel": role},
    }


def _entity_facts_for_ticker(question: str, plan: Dict[str, Any], *, limit: int = FACT_ENTITY_LIMIT) -> Dict[str, Any]:
    """Ficha de empresa para um ticker/entidade mencionada (ex.: 'contratos da EDP')."""
    from api.elasticsearch_client import search_companies, get_contract_analytics  # noqa: PLC0415

    tickers = [str(t).strip().upper() for t in (plan.get("tickers") or []) if t]
    if not tickers:
        # Sem ticker, fallback para entidades gerais.
        return _entity_facts(question, plan, limit=limit)

    symbol = tickers[0]
    # Tenta encontrar empresa interna pelo nome/ticker (EDP -> EDP, NOS, GALP, ...).
    payload = search_companies(q=symbol, size=10, min_contracts=1)
    rows = [row for row in (payload.get("items") or []) if row.get("nif")]
    # Preferir correspondencia exacta do nome/normalizado ao simbolo.
    exact_rows = [
        row for row in rows
        if str(row.get("name") or row.get("normalized_name") or "").upper() == symbol
        or str(row.get("normalized_name") or "").upper() == symbol
    ]
    if exact_rows:
        rows = exact_rows

    if not rows:
        return {
            "facts": [f"Nao encontrei uma entidade interna com o simbolo/nome «{symbol}» nos contratos indexados."],
            "items": [],
            "warnings": [],
            "stats": {"ticker": symbol, "empresas": 0},
        }

    row = rows[0]
    name = str(row.get("name") or row.get("normalized_name") or symbol)
    nif = str(row.get("nif"))
    facts: List[str] = [
        f"Entidade «{name}» (NIF {nif}, simbolo {symbol}): "
        f"{_count(row.get('contracts_total'))} contratos publicos indexados, "
        f"{_money(row.get('total_value'))} de valor total."
    ]
    for role, label in (("adjudicante", "como adjudicante"), ("adjudicatario", "como adjudicatario")):
        summary = row.get(role)
        if isinstance(summary, dict) and summary.get("contracts_count"):
            years = ""
            if summary.get("first_year") and summary.get("last_year"):
                years = f" ({summary['first_year']}-{summary['last_year']})"
            facts.append(
                f"- {label}: {_count(summary.get('contracts_count'))} contratos, "
                f"{_money(summary.get('total_value'))}{years}."
            )

    # Evita duplicar a ficha da entidade vinda da ontologia (que ja inclui nif).
    # Guardamos o NIF no stats para o orquestrador poder deduplicar.
    entity_hash = f"entity:{nif}"

    items: List[Dict[str, Any]] = [
        _fact_item(
            title=f"{name} - {_count(row.get('contracts_total'))} contratos - {_money(row.get('total_value'))}",
            kind="entity",
            snippet=f"NIF {nif} - valores agregados dos contratos indexados no IQ OS.",
            url=f"/companies/{nif}",
            source="Plataforma IQ OS - empresas",
        )
    ]

    # Agrega contratos desta entidade pelo NIF (mais fiel do que match por nome).
    try:
        analytics = get_contract_analytics(
            nif=nif,
            top_entities=3,
            top_cpv=5,
        )
        total = analytics.get("total_contracts")
        if total:
            facts.append(
                f"Agregacao por NIF {nif} («{name}»): {_count(total)} contratos, "
                f"{_money(analytics.get('total_value'))} de valor total."
            )
            cpv_rows = analytics.get("top_cpv") or []
            if cpv_rows:
                facts.append(
                    "CPV mais frequentes: "
                    + "; ".join(f"{_cpv_label(c)} ({_count(c.get('count'))})" for c in cpv_rows[:5])
                    + "."
                )
    except Exception as exc:
        facts.append(f"Nao foi possivel obter agregacoes detalhadas para {name}: {exc}")

    # Adiciona factos provenientes da ontologia (objetos, linkes, acoes) se a entidade existir.
    try:
        ctx = ontology.ai_context(name, limit=10)
        if ctx and ctx.get("objects"):
            objects = ctx.get("objects") or []
            links = ctx.get("links") or []
            actions = ctx.get("actions") or []
            facts.append(
                f"Objetos da ontologia do IQ OS identificados para «{name}»: "
                + "; ".join(
                    f"{obj.get('label')} ({obj.get('type')}, id {obj.get('id')})"
                    for obj in objects[:3]
                )
                + "."
            )
            for obj in objects[:3]:
                details = [f"{k}={v}" for k, v in obj.items() if k not in ("id", "label", "type") and v is not None][:6]
                if details:
                    facts.append(f"- {obj.get('label')} ({obj.get('type')}, id {obj.get('id')}): " + ", ".join(details) + ".")
            if links:
                facts.append(
                    "Ligacoes da ontologia: "
                    + "; ".join(f"{link.get('source')} --{link.get('type')}--> {link.get('target')}" for link in links[:3])
                    + "."
                )
            if actions:
                facts.append(
                    "Acoes/alertas da ontologia: "
                    + "; ".join(f"{action.get('type')} ({action.get('label')})" for action in actions[:3])
                    + "."
                )
            items.extend(
                _fact_item(
                    title=f"Ontologia: {obj.get('label')} ({obj.get('type')})",
                    kind="entity",
                    snippet=str(obj),
                    url="/ontology",
                    source="Ontologia IQ OS",
                )
                for obj in objects[:5]
            )
    except Exception as exc:
        logger.info("Hermes: factos de ontologia para «%s» indisponiveis: %s", name, exc)

    return {"facts": facts, "items": items, "warnings": [], "stats": {"ticker": symbol, "empresas": len(rows), "entity_hash": entity_hash}}


def _cpv_label(cpv: Dict[str, Any]) -> str:
    """Devolve 'codigo - descricao' ou so o codigo."""
    code = cpv.get("key") or cpv.get("code")
    desc = cpv.get("description")
    if code and desc:
        return f"{code} - {desc}"
    return str(code or "n/d")


def _contract_facts(question: str, plan: Dict[str, Any], *, limit: int = FACT_ENTITY_LIMIT) -> Dict[str, Any]:
    """Totais, tendência e CPV dos contratos indexados (agregações do índice)."""
    from api.elasticsearch_client import get_contract_analytics  # noqa: PLC0415

    keywords = _fact_keywords(question, plan)
    nifs = [nif for nif in (plan.get("nifs") or []) if nif]
    # Perguntas gerais de total («quantos contratos temos», «valor total») não
    # devem filtrar por keywords; cobrem todos os contratos indexados.
    wants_general_total = _wants_general_total(question, plan) and not nifs
    # Perguntas do tipo «empresas do setor X»: reter as entidades do filtro e dar-lhes
    # nome (as agregações devolvem só o NIF).
    wants_sector_entities = bool(keywords) and not wants_general_total and _has_stem(
        question, ("empresa", "adjudicat", "fornecedor", "concorrente")
    )
    analytics = get_contract_analytics(
        q=None if wants_general_total else (" ".join(keywords) or None),
        nif=nifs[0] if nifs else None,
        top_entities=6 if wants_sector_entities else 1,
        top_cpv=5,
    )
    if analytics.get("error"):
        return {"facts": [], "items": [], "warnings": [f"Contratos: {analytics['error']}"], "stats": {}}

    if wants_general_total:
        scope_label = " (total global da plataforma)"
    else:
        scope_label = f" (filtro «{' '.join(keywords)}»)" if keywords else ""
    nif_label = f" para o NIF {nifs[0]}" if nifs else ""
    total = analytics.get("total_contracts") or 0
    facts: List[str] = [
        f"Contratos públicos indexados{scope_label}{nif_label}: {_count(total)}; "
        f"valor total {_money(analytics.get('total_value'))}; média {_money(analytics.get('avg_value'))}; "
        f"maior contrato {_money(analytics.get('max_value'))}."
    ]
    items: List[Dict[str, Any]] = [
        _fact_item(
            title=f"Contratos públicos{scope_label}{nif_label}: {_count(total)} contratos · {_money(analytics.get('total_value'))}",
            kind="metric",
            snippet=(
                f"Média {_money(analytics.get('avg_value'))} · maior contrato {_money(analytics.get('max_value'))} · "
                "agregações do índice de contratos do IQ OS"
            ),
            url="/contracts/dashboard",
        )
    ]

    years = [row for row in (analytics.get("by_year") or []) if row.get("key")][-4:]
    if years:
        facts.append(
            "Por ano: "
            + "; ".join(f"{row['key']}: {_count(row.get('count'))} contratos ({_money(row.get('total_value'))})" for row in years)
            + "."
        )

    cpv = analytics.get("top_cpv") or []
    if cpv:
        facts.append(
            "CPV mais frequentes: "
            + "; ".join(f"{row.get('key')} ({_count(row.get('count'))})" for row in cpv[:5])
            + "."
        )
    procedures = analytics.get("procedure_types") or []
    if procedures:
        facts.append(
            "Tipos de procedimento: "
            + "; ".join(f"{row.get('key')}: {_count(row.get('count'))}" for row in procedures[:4])
            + "."
        )
    if wants_sector_entities:
        rows = analytics.get("top_entities") or []
        if rows:
            facts.append(f"Entidades com mais valor contratado no filtro «{' '.join(keywords)}»:")
            for row in rows[:5]:
                nif = _nif_of(row.get("key"))
                name = _company_name(nif) if nif else None
                label = f"{name} (NIF {nif})" if name and nif else str(row.get("key"))
                facts.append(f"- {label}: {_count(row.get('count'))} contratos, {_money(row.get('total_value'))}.")
                items.append(
                    _fact_item(
                        title=f"{label} — {_count(row.get('count'))} contratos · {_money(row.get('total_value'))}",
                        kind="entity",
                        snippet=f"Agregações do índice de contratos com o filtro «{' '.join(keywords)}».",
                        url=f"/companies/{nif}" if nif else "/contracts/dashboard",
                        source="Plataforma IQ OS · contratos",
                    )
                )
    if _wants_biggest(question):
        big_facts, big_items = _biggest_contracts(keywords, limit=4)
        if big_facts:
            facts.append("Contratos de maior valor" + (f" (filtro «{' '.join(keywords)}»)" if keywords else "") + ":")
            facts.extend(big_facts)
            items.extend(big_items)
    return {"facts": facts, "items": items, "warnings": [], "stats": {"contratos": total}}


def _ontology_facts(question: str, scope: Optional[Dict[str, Any]], *, limit: int = FACT_OBJECT_LIMIT) -> Dict[str, Any]:
    """Objetos canónicos da ontologia do IQ OS identificados na pergunta."""
    from api import ontology_service as ontology  # noqa: PLC0415

    context = ontology.ai_context(question, limit=limit, scope=scope)
    objects = context.get("objects") or []
    if not objects:
        return {"facts": [], "items": [], "warnings": [], "stats": {"objetos": 0}}
    lines: List[str] = []
    items: List[Dict[str, Any]] = []
    for obj in objects[:limit]:
        mention = str(obj.get("mention") or "").strip().lower()
        if mention and (
            any(mention.startswith(noise) for noise in FACT_NOISE_WORDS)
            or any(mention.startswith(term) for term in CONTRACT_TERMS)
        ):
            # «PORTUGAL» num nome de firma não é o objeto que o utilizador pediu.
            continue
        props = {key: value for key, value in (obj.get("properties") or {}).items() if value not in (None, "", [], {})}
        summary = ", ".join(f"{key}={_text(value, limit=60)}" for key, value in list(props.items())[:6])
        lines.append(
            f"- {obj.get('label')} ({obj.get('type_label')}, id {obj.get('id')})" + (f": {summary}" if summary else "")
        )
        items.append(
            _fact_item(
                title=f"{obj.get('label')} · {obj.get('type_label')}",
                kind="entity",
                snippet=summary or None,
                url="/ontology",
                source="Ontologia IQ OS",
            )
        )
    if not lines:
        return {"facts": [], "items": [], "warnings": [], "stats": {"objetos": 0}}
    facts = ["Objetos da ontologia do IQ OS identificados na pergunta:", *lines]
    return {"facts": facts, "items": items, "warnings": [], "stats": {"objetos": len(items)}}


def _lexical_chunks(store: Any, keywords: Sequence[str], *, limit: int = 2, minimum_hits: int = 2) -> List[Dict[str, Any]]:
    """Trechos que contêm as palavras distintivas (procura lexical, sem vetores).

    A pesquisa vetorial falha secções específicas de documentos grandes (ex.:
    «6.2 Sufixos por Entidade» num manual de 51 páginas); esta passagem usa o
    texto dos chunks já indexados para garantir que o conteúdo exato entra nas
    evidências.
    """
    words = [_fold(word) for word in keywords if str(word).strip()]
    if not words:
        return []
    chunks = getattr(store, "_chunks", None) or []
    needed = min(minimum_hits, len(words))
    scored: List[tuple] = []
    for position, chunk in enumerate(chunks):
        text = str(chunk.get("text") or "")
        if not text:
            continue
        lowered = _fold(text)
        hits = sum(1 for word in words if word and word in lowered)
        if hits >= needed:
            scored.append((hits, -position, chunk))
    scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return [chunk for _, _, chunk in scored[:limit]]


def _document_facts(
    question: str,
    keywords: Sequence[str] = (),
    *,
    top_k: int = FACT_DOCUMENT_LIMIT,
) -> Dict[str, Any]:
    """Trechos dos documentos indexados (RAG): pesquisa vetorial + palavras-chave."""
    from api.rag_service import get_vector_store  # noqa: PLC0415

    warnings: List[str] = []
    store = get_vector_store()
    candidates: List[tuple] = []
    # Os trechos encontrados por palavras-chave entram primeiro: exigem 2+ palavras
    # distintivas na mesma secção, pelo que são mais precisos do que os vizinhos
    # semânticos (que enchem o orçamento com partes irrelevantes do mesmo PDF).
    try:
        for chunk in _lexical_chunks(store, keywords, limit=top_k):
            candidates.append((chunk, "Documentos indexados (RAG) · palavras-chave"))
    except Exception as exc:
        warnings.append(f"Documentos (palavras-chave) indisponíveis: {exc}")
    try:
        for chunk in store.search(
            question, top_k=max(top_k, FACT_DOCUMENT_CANDIDATES), min_score=FACT_DOCUMENT_MIN_SCORE
        ) or []:
            candidates.append((chunk, "Documentos indexados (RAG)"))
    except Exception as exc:
        warnings.append(f"Documentos (pesquisa vetorial) indisponíveis: {exc}")

    items: List[Dict[str, Any]] = []
    facts: List[str] = []
    seen_chunks: set[str] = set()
    per_document: Dict[str, int] = {}
    for chunk, source in candidates:
        title = str(chunk.get("doc_title") or "Documento")
        page = chunk.get("page")
        label = f"{title} · página {page}" if page else title
        text = _text(chunk.get("text"), limit=800)
        if not text:
            continue
        # O chunk costuma começar pelo título do documento em Markdown: tira-se
        # para não repetir a mesma linha no título e no trecho.
        text = re.sub(r"^\s*#+\s*" + re.escape(title) + r"\s*", "", text).strip()
        if not text or text in seen_chunks or len(items) >= top_k:
            continue
        # Até 3 trechos por documento (o mesmo PDF tem secções diferentes).
        if per_document.get(title, 0) >= 3:
            continue
        per_document[title] = per_document.get(title, 0) + 1
        seen_chunks.add(text)
        facts.append(f"- {label}: {text[:340]}")
        items.append(
            _fact_item(
                title=label,
                kind="document",
                snippet=text,
                url="/rag",
                source=source,
                score=FACT_SCORE_DOCUMENT,
            )
        )
    if facts:
        facts.insert(0, "Trechos dos documentos indexados (RAG) mais relevantes:")
    return {"facts": facts, "items": items, "warnings": warnings, "stats": {"trechos": len(items)}}


async def _guarded(name: str, fn: Any, timeout: float, *args: Any, **kwargs: Any) -> Dict[str, Any]:
    """Corre um construtor de factos em thread, sem deixar cair a investigação."""
    try:
        return await asyncio.wait_for(asyncio.to_thread(fn, *args, **kwargs), timeout=timeout)
    except Exception as exc:
        logger.info("Hermes: factos «%s» indisponíveis: %s", name, exc)
        return {"facts": [], "items": [], "warnings": [f"Factos «{name}» indisponíveis: {exc}"], "stats": {}}


def _platform_self_facts(question: str) -> Dict[str, Any]:
    """O que é o IQ OS: módulos, índices internos, ontologia e documentos indexados."""
    from api import ontology_service as ontology  # noqa: PLC0415

    facts: List[str] = [
        "O IQ OS é a plataforma portuguesa de inteligência financeira e de contratos públicos. Módulos: "
        + "; ".join(f"{name} ({hint})" for name, hint in PLATFORM_MODULES)
        + "."
    ]
    items: List[Dict[str, Any]] = [
        _fact_item(
            title="IQ OS · módulos da plataforma",
            kind="document",
            snippet="; ".join(name for name, _ in PLATFORM_MODULES),
            url="/",
            source="Plataforma IQ OS · metamodelo",
        )
    ]
    warnings: List[str] = []

    try:
        indexes = search360.status().get("indexes") or []
        if indexes:
            rows = "; ".join(
                f"{row.get('label') or row.get('index')} ({_count(row.get('documents'))})" for row in indexes
            )
            facts.append(f"Índices internos (Elasticsearch): {rows}.")
            items.append(
                _fact_item(
                    title=f"Índices internos: {_count(sum(int(row.get('documents') or 0) for row in indexes))} documentos",
                    kind="metric",
                    snippet=rows,
                    url="/elastic",
                    source="Plataforma IQ OS · metamodelo",
                )
            )
    except Exception as exc:
        warnings.append(f"Índices internos indisponíveis: {exc}")

    try:
        types = ontology.object_types() or []
        links = ontology.link_types() or []
        actions = ontology.actions() or []
        if types:
            names = ", ".join(str(item.get("label") or item.get("id")) for item in types[:20])
            facts.append(
                f"A ontologia do IQ OS descreve {len(types)} tipos de objeto ({names}), "
                f"{len(links)} tipos de ligação e {len(actions)} ações."
            )
            items.append(
                _fact_item(
                    title=f"Ontologia: {len(types)} tipos de objeto",
                    kind="entity",
                    snippet=names,
                    url="/ontology",
                    source="Ontologia IQ OS",
                )
            )
    except Exception as exc:
        warnings.append(f"Ontologia indisponível: {exc}")

    try:
        from api.rag_service import get_document_store  # noqa: PLC0415

        documents = get_document_store().list()
        if documents:
            rows = "; ".join(f"{getattr(doc, 'title', doc)} ({getattr(doc, 'pages', 0)} páginas)" for doc in documents[:8])
            facts.append(f"Documentos indexados no RAG: {len(documents)} — {rows}.")
            items.append(
                _fact_item(
                    title=f"Documentos indexados (RAG): {len(documents)}",
                    kind="document",
                    snippet=rows,
                    url="/rag",
                    source="Documentos indexados (RAG)",
                )
            )
    except Exception as exc:
        warnings.append(f"Documentos indexados indisponíveis: {exc}")

    return {"facts": facts, "items": items, "warnings": warnings, "stats": {"modulos": len(PLATFORM_MODULES)}}


def _market_facts(question: str, plan: Dict[str, Any], *, limit: int = 2) -> Dict[str, Any]:
    """Cotações (histórico recente) e notícias indexadas dos tickers mencionados."""
    from api.elasticsearch_client import search_news  # noqa: PLC0415
    from api.tools import get_stock_history  # noqa: PLC0415

    candidates = _market_candidates(question, plan)
    if not candidates:
        return {"facts": [], "items": [], "warnings": [], "stats": {"mercados": 0}}

    facts: List[str] = []
    items: List[Dict[str, Any]] = []
    warnings: List[str] = []
    for raw in candidates[:limit]:
        ticker = _resolve_ticker(raw)
        history = None
        try:
            frame = get_stock_history(ticker, period="1y")
            if frame is not None and not frame.empty:
                history = frame
        except Exception as exc:
            warnings.append(f"Cotações de {ticker} indisponíveis: {exc}")

        closes: List[float] = []
        if history is not None and "Close" in getattr(history, "columns", []):
            try:
                closes = [float(value) for value in history["Close"].tolist() if value == value]
            except Exception as exc:
                warnings.append(f"Série de {ticker} ilegível: {exc}")
        if closes:
            dates: List[str] = []
            if "Date" in getattr(history, "columns", []):
                dates = [str(value)[:10] for value in history["Date"].tolist()]
            first, last = closes[0], closes[-1]
            change = ((last - first) / first * 100) if first else 0.0
            facts.append(
                f"{ticker}: último fecho {last:.2f} em {dates[-1] if dates else 'n/d'}; variação em 1 ano "
                f"{change:+.1f}%; mínimo {min(closes):.2f} / máximo {max(closes):.2f} ({len(closes)} sessões)."
            )
            items.append(
                _fact_item(
                    title=f"{ticker}: {last:.2f} ({change:+.1f}% em 1 ano)",
                    kind="metric",
                    snippet=(
                        f"Último fecho em {dates[-1] if dates else 'n/d'} · mínimo {min(closes):.2f} · "
                        f"máximo {max(closes):.2f} · {len(closes)} sessões"
                    ),
                    url=f"/tickers/{ticker}",
                    source="Mercados · cotações",
                )
            )
        else:
            facts.append(f"{ticker}: a plataforma não tem cotações recentes disponíveis para este ticker.")

        try:
            news = search_news(ticker, size=5)
        except Exception as exc:
            news = {"items": []}
            warnings.append(f"Notícias de {ticker} indisponíveis: {exc}")
        rows = news.get("items") or []
        if rows:
            facts.append(f"Notícias indexadas de {ticker} ({len(rows)} mais recentes):")
        for row in rows[:5]:
            title = _text(row.get("title") or row.get("headline"), limit=140)
            if not title:
                continue
            published = _text(row.get("date") or row.get("published") or row.get("pubDate"), limit=10)
            facts.append(f"- {title}" + (f" ({published})" if published else ""))
            items.append(
                _fact_item(
                    title=title,
                    kind="news",
                    snippet=_text(row.get("summary") or row.get("description"), limit=200) or None,
                    url=str(row.get("url") or row.get("link") or f"/tickers/{ticker}"),
                    source=f"Notícias de {ticker}",
                )
            )
    return {"facts": facts, "items": items, "warnings": warnings, "stats": {"mercados": len(candidates[:limit])}}


async def _platform_facts(question: str, plan: Dict[str, Any], scope: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Factos calculados na plataforma (em paralelo; uma falha não derruba as outras)."""
    tasks: List[Any] = []
    has_tickers = bool(plan.get("tickers")) and not _wants_general_total(question, plan)
    wants_contracts = _wants_contracts(question, plan)
    if wants_contracts:
        tasks.append(_guarded("contratos", _contract_facts, FACTS_TIMEOUT_HEAVY, question, plan))
        # Empresa específica quando a pergunta menciona um ticker (ex.: EDP),
        # mas mantém factos gerais para perguntas globais.
        if has_tickers:
            tasks.append(_guarded("empresas", _entity_facts_for_ticker, FACTS_TIMEOUT_HEAVY, question, plan))
        else:
            tasks.append(_guarded("empresas", _entity_facts, FACTS_TIMEOUT_HEAVY, question, plan))
    # Mercado só corre se a pergunta for realmente sobre cotações/notícias de ticker;
    # se o utilizador só perguntar "contratos da EDP", o ticker serve para filtrar
    # contratos/entidades, não para ir buscar cotações.
    if _market_candidates(question, plan) and not (wants_contracts and has_tickers):
        tasks.append(_guarded("mercado", _market_facts, FACTS_TIMEOUT, question, plan))
    if _wants_platform(question):
        tasks.append(_guarded("plataforma", _platform_self_facts, FACTS_TIMEOUT, question))
    tasks.append(_guarded("ontologia", _ontology_facts, FACTS_TIMEOUT, question, scope))
    tasks.append(_guarded("documentos", _document_facts, FACTS_TIMEOUT, question, _fact_keywords(question, plan)))
    results = await asyncio.gather(*tasks)
    facts: List[str] = []
    items: List[Dict[str, Any]] = []
    warnings: List[str] = []
    stats: Dict[str, Any] = {}
    for result in results:
        facts.extend(result.get("facts") or [])
        items.extend(result.get("items") or [])
        warnings.extend(result.get("warnings") or [])
        stats.update(result.get("stats") or {})
    return {"facts": facts, "items": items, "warnings": warnings, "stats": stats}


# --------------------------------------------------------------------------
# Recolha
# --------------------------------------------------------------------------
async def _search(term: str, *, sources_ids: Sequence[str], limit: int, scope: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    try:
        return await search360.search(term, sources_ids=list(sources_ids), limit=limit, scope=scope, skip_ai=True)
    except Exception as exc:  # uma recolha falhada não pode derrubar a resposta
        logger.info("Hermes: recolha de «%s» falhou: %s", term, exc)
        return {"term": term, "items": [], "per_source": [], "warnings": [f"{term}: {exc}"], "stats": {}}


def _per_source(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        current = merged.get(row["source_id"])
        if current is None:
            merged[row["source_id"]] = {
                "source_id": row["source_id"],
                "label": row.get("label") or row["source_id"],
                "family": row.get("family"),
                "items": row.get("items") or 0,
                "ms": row.get("ms") or 0,
                "ok": bool(row.get("ok")),
            }
            continue
        current["items"] += row.get("items") or 0
        current["ms"] += row.get("ms") or 0
        current["ok"] = current["ok"] and bool(row.get("ok"))
    return sorted(merged.values(), key=lambda entry: -entry["items"])


async def ask(
    question: str,
    *,
    depth: str = DEFAULT_DEPTH,
    sources_ids: Optional[Sequence[str]] = None,
    backend: Optional[str] = None,
    history: Optional[Sequence[Dict[str, Any]]] = None,
    scope: Optional[Dict[str, Any]] = None,
    session: Any = None,
    country: str = "PRT",
) -> Dict[str, Any]:
    """Investiga a pergunta e devolve a resposta citada com as evidências."""
    from api import ontology_ai as ai  # noqa: PLC0415

    clean = clean_question(question)
    if not clean:
        raise ValueError("Escreva a pergunta que quer investigar.")

    # Se existir um agente dinâmico chamado "Hermes", dá-lhe prioridade.
    user_id = getattr(getattr(session, "user", None), "id", None) if session else None
    try:
        from api import agent_integration as agenti

        agent_result = await agenti.ask_hermes_agent(clean, user_id=user_id)
        if agent_result:
            return {
                "answer": agenti.agent_result_to_rag_answer(agent_result),
                "sources": agenti.agent_result_to_sources(agent_result),
                "subquestions": [],
                "skill": agenti.format_agent_as_skill("Hermes", agent_result),
                "elapsed_seconds": agent_result.get("elapsed_seconds", 0),
                "agent_id": agent_result.get("agent_id"),
                "thread_id": agent_result.get("thread_id"),
            }
    except Exception as exc:
        logger.warning("Falha ao executar agente Hermes dinâmico: %s", exc)

    started = time.perf_counter()
    spec = DEPTH_BY_ID.get(str(depth or DEFAULT_DEPTH)) or DEPTH_BY_ID[DEFAULT_DEPTH]
    selected = [
        source_id
        for source_id in (sources_ids or spec["sources"])
        if source_id in search_sources.CATALOG_BY_ID
    ] or list(spec["sources"])

    research = search360.plan(clean, selected)
    topic = _topic_of(clean, research.get("keywords"))
    substeps = _subquestions(topic) if spec["subquestions"] else []

    # 0) Skill: escolher (ou criar) o método antes de investigar. É este método
    #    que o modelo recebe no prompt e que o painel do Hermes mostra.
    from api import skills_service as skills  # noqa: PLC0415

    skill_result = await skills.for_request(clean, session=session, backend=backend)
    skill_block = skill_result["block"]

    # 1) recolha federada (sub-perguntas em paralelo no modo profundo) + factos
    #    calculados na plataforma (contratos, empresas, mercado, ontologia, documentos)
    #    A recolha usa as palavras distintivas (ou o NIF/ticker exato) — as fontes
    #    externas respondem muito melhor a um termo curto do que à pergunta inteira.
    search_term = _search_term(clean, topic, research)
    searches = [
        _search(row.get("term") or row["question"], sources_ids=selected, limit=int(spec["limit"]), scope=scope)
        for row in (substeps or [{"question": clean, "term": search_term}])
    ]
    results = await asyncio.gather(*searches, _platform_facts(clean, research, scope))
    payloads = results[:-1]
    facts_result = results[-1] if isinstance(results[-1], dict) else {}

    facts: List[str] = list(facts_result.get("facts") or [])
    merged_items: List[Dict[str, Any]] = list(facts_result.get("items") or [])
    per_source_rows: List[Dict[str, Any]] = []
    warnings: List[str] = list(facts_result.get("warnings") or [])
    steps: List[Dict[str, Any]] = []
    for position, payload in enumerate(payloads):
        merged_items.extend(payload.get("items") or [])
        per_source_rows.extend(payload.get("per_source") or [])
        warnings.extend(payload.get("warnings") or [])
        row = substeps[position] if substeps else None
        steps.append(
            {
                "id": row["id"] if row else "pergunta",
                "focus": row["focus"] if row else "Pergunta",
                "question": row["question"] if row else clean,
                "items": int((payload.get("stats") or {}).get("items") or len(payload.get("items") or [])),
                "sources_with_results": int((payload.get("stats") or {}).get("sources_with_results") or 0),
                "ms": int((payload.get("stats") or {}).get("ms") or 0),
            }
        )
    grouped = _per_source(per_source_rows)

    # 2) indicadores (só no modo profundo, e só se o Banco Mundial tiver entrado)
    metrics: List[Dict[str, Any]] = []
    if spec["subquestions"] and "worldbank" in selected:
        try:
            metrics = await asyncio.wait_for(
                search360.metrics({"items": merged_items}, country=country), timeout=METRICS_TIMEOUT
            )
        except Exception as exc:
            logger.info("Hermes: indicadores indisponíveis: %s", exc)
            warnings.append(f"Indicadores indisponíveis: {exc}")
        metrics = list({str(entry.get("indicator")): entry for entry in metrics}.values())

    evidence = _dedupe_evidence(_evidence_of({"items": merged_items}, start=1))[:MAX_EVIDENCE]

    # 3) resposta (modelo de IA quando configurado; factual caso contrário)
    chosen = ai.available_backend(session, backend)
    result: Dict[str, Any] = {
        "id": f"hermes-{uuid4().hex[:12]}",
        "question": clean,
        "topic": topic,
        "depth": spec["id"],
        "depth_label": spec["label"],
        "sources": selected,
        "plan": research,
        "backend": {
            "kind": chosen.get("kind"),
            "provider": chosen.get("provider"),
            "model": chosen.get("model"),
            "label": chosen.get("provider") or chosen.get("backend") or None,
        },
        "evidence": evidence,
        "facts": facts,
        "skill": skill_result["public"],
        "metrics": metrics,
        "steps": steps,
        "per_source": grouped,
        "notes": [],
        "warnings": warnings,
        "followups": _followups(topic, research, grouped),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    if not evidence:
        result["mode"] = "empty"
        result["text"] = (
            f"Não foram encontradas evidências sobre «{clean}» nas fontes consultadas "
            f"({', '.join(str(row['label']) for row in grouped) or 'nenhuma'}). "
            "Experimente reformular a pergunta, alargar as fontes ou usar a investigação profunda."
        )
    elif chosen.get("kind") == "cloud":
        try:
            text = await ai.ask_model(
                chosen,
                system=SYSTEM,
                prompt=_prompt(clean, topic, evidence, metrics, history, steps, facts, skill_block),
                max_tokens=int(spec["max_tokens"]),
                temperature=0.2,
            )
        except Exception as exc:
            logger.info("Hermes: modelo indisponível (%s); resposta factual.", exc)
            result["warnings"].append(f"IA indisponível ({exc}); resposta factual.")
            text = ""
        if text and text.strip():
            result["mode"] = "ai"
            result["text"] = text.strip()
            result["notes"].append(
                f"Resposta redigida por {chosen.get('provider')}:{chosen.get('model')} sobre {len(evidence)} evidências."
            )
        else:
            result["mode"] = "factual"
            result["text"] = _factual_answer(clean, evidence, metrics, grouped, steps, facts)
            result["notes"].append("Sem texto do modelo: resposta factual a partir das fontes.")
    else:
        result["mode"] = "factual"
        result["text"] = _factual_answer(clean, evidence, metrics, grouped, steps, facts)
        if chosen.get("kind") == "unavailable":
            result["notes"].append(
                str(chosen.get("note") or "Sem chave de API: resposta factual.")
                + " Configure um fornecedor em Definições → Fornecedores de IA."
            )
        else:
            result["notes"].append(
                "Sem modelo de IA configurado: resposta factual a partir das fontes. "
                "Configure um fornecedor em Definições → Fornecedores de IA."
            )

    result["stats"] = {
        "ms": int((time.perf_counter() - started) * 1000),
        "items": len(merged_items),
        "evidence": len(evidence),
        "facts": len(facts),
        "sources_queried": len(grouped),
        "sources_with_results": len([row for row in grouped if row["items"]]),
        "subquestions": len(steps),
    }
    skills.finish(
        skill_result["id"],
        question=clean,
        tools=(skill_result["raw"] or {}).get("tools") or (),
        mode=result["mode"],
    )
    return result


# --------------------------------------------------------------------------
# Metamodelo
# --------------------------------------------------------------------------
def meta(session: Any = None) -> Dict[str, Any]:
    """Capacidades do Hermes: modos, fontes, índices e modelo disponível."""
    from api import ontology_ai as ai  # noqa: PLC0415

    chosen = ai.available_backend(session, None)
    status = search360.status()
    return {
        "about": {
            "name": "Hermes",
            "description": (
                "Assistente de investigação: transforma uma pergunta em evidências citadas da plataforma "
                "(contratos, empresas, documentos, notícias) e das fontes abertas, e responde com citações [n]. "
                "Antes de escrever, calcula factos exatos na plataforma: agregações dos contratos públicos, "
                "objetos da ontologia e trechos dos documentos indexados."
            ),
            "capabilities": [
                "responder com citações",
                "factos calculados (contratos, ontologia, documentos)",
                "sub-perguntas (investigação profunda)",
                "indicadores macroeconómicos",
                "guardar a resposta no Office",
            ],
        },
        "depths": DEPTHS,
        "default_depth": DEFAULT_DEPTH,
        "sources": status["sources"],
        "families": status["families"],
        "indexes": status["indexes"],
        "cache": status["cache"],
        "limits": {
            "max_question_chars": MAX_QUESTION_CHARS,
            "max_evidence": MAX_EVIDENCE,
            "max_substeps": MAX_SUBSTEPS,
            "max_history": MAX_HISTORY,
        },
        "backend": {
            "kind": chosen.get("kind"),
            "provider": chosen.get("provider"),
            "model": chosen.get("model"),
            "note": chosen.get("note"),
        },
    }
