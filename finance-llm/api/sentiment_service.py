"""Análise de sentimento do IQ OS — para texto, para a recolha e para as notícias.

Três camadas, todas offline e determinísticas por omissão:

1. **Léxico PT** (financeiro/noticioso) com **negação** e **intensificadores** —
   dá polaridade por frase e por documento sem depender da rede.
2. **Estatística com pandas** — tabela por item, distribuição por etiqueta,
   média/desvio, intervalo de confiança a 95 % e agregados por fonte e por dia.
3. **Palavras-chave com scikit-learn** (TF-IDF, 1–2 gramas) sobre o corpus.

Opcionalmente, um **modelo neuronal** (`transformers`) pode substituir o léxico —
se não estiver instalado ou não houver rede, cai-se no léxico e o relatório diz
qual o motor usado (nunca falha por causa disso).

Os resultados podem ser guardados no **dossiê de análise** (Pesquisa 360) e
levados para o **editor Office** como documento Markdown — a partir do dossiê o
Office já sabe montar o texto, por isso o caminho é sempre o mesmo: analisar →
guardar no dossiê → abrir/atualizar no Office.
"""
from __future__ import annotations

import io
import logging
import math
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------- léxico
# Peso de -2 (muito negativo) a +2 (muito positivo). Português de Portugal, com
# vocabulário de notícias, mercados e contratação pública.
LEXICON: Dict[str, float] = {
    # positivo
    "acordo": 1.0, "alto": 0.6, "avanco": 1.0, "avanço": 1.0, "beneficio": 1.2, "benefício": 1.2,
    "beneficios": 1.2, "benefícios": 1.2, "bom": 1.2, "boa": 1.2, "bons": 1.1, "boas": 1.1,
    "crescimento": 1.2, "cresce": 1.1, "crescer": 1.1, "cresceu": 1.1, "confianca": 1.0, "confiança": 1.0,
    "contratacao": 0.3, "contratação": 0.3, "estavel": 0.6, "estável": 0.6, "estabilidade": 0.8,
    "excelente": 2.0, "expansao": 1.1, "expansão": 1.1, "forte": 1.0, "fortalecimento": 1.2,
    "ganho": 1.1, "ganhos": 1.1, "ganha": 1.0, "ganhar": 0.9, "ganhou": 1.0, "garantia": 0.8,
    "impulso": 0.9, "inovacao": 1.0, "inovação": 1.0, "lucro": 1.4, "lucros": 1.4, "lucrativo": 1.3,
    "melhoria": 1.3, "melhora": 1.1, "melhoram": 1.1, "melhor": 1.2, "melhores": 1.2, "melhorou": 1.2,
    "notavel": 1.1, "notável": 1.1, "otimista": 1.2, "positivo": 1.4, "positiva": 1.4, "positivos": 1.4,
    "progresso": 1.1, "promissor": 1.2, "recorde": 1.1, "recuperacao": 1.2, "recuperação": 1.2,
    "recupera": 1.1, "recuperou": 1.2, "reduzir": 0.5, "reforco": 0.9, "reforço": 0.9, "reforca": 0.9,
    "rentavel": 1.3, "rentável": 1.3, "resiliente": 1.1, "solido": 1.0, "sólido": 1.0, "sucesso": 1.5,
    "subida": 0.9, "sobe": 0.9, "subiu": 0.9, "supera": 1.1, "superou": 1.2, "valorizacao": 1.3,
    "valorização": 1.3, "valoriza": 1.2, "vitoria": 1.4, "vitória": 1.4, "aprova": 1.1, "aprovado": 1.1,
    "aprovação": 1.1, "aprovacao": 1.1, "apoio": 0.9, "beneficia": 1.0, "beneficiado": 1.0,
    "eficaz": 1.0, "eficiencia": 0.9, "eficiência": 0.9, "suficiente": 0.5, "adequado": 0.7,
    # negativo
    "abrandamento": -1.1, "acusacao": -1.4, "acusação": -1.4, "acusa": -1.2, "acordo-ruim": -1.0,
    "ameaca": -1.4, "ameaça": -1.4, "atraso": -1.1, "atrasos": -1.1, "atrasado": -1.0, "baixa": -0.9,
    "cai": -1.1, "caiu": -1.1, "cair": -0.9, "queda": -1.2, "quebra": -1.2, "colapso": -2.0,
    "corrupcao": -2.0, "corrupção": -2.0, "crise": -1.7, "critica": -1.1, "crítica": -1.1, "critico": -1.0,
    "crítico": -1.0, "danos": -1.3, "deficit": -1.3, "défice": -1.3, "deficiente": -1.2, "desaceleracao": -1.2,
    "desaceleração": -1.2, "desastre": -1.9, "desemprego": -1.3, "desigualdade": -1.1, "deterioracao": -1.4,
    "deterioração": -1.4, "divida": -1.0, "dívida": -1.0, "erro": -1.2, "erros": -1.2, "falha": -1.4,
    "falencia": -2.0, "falência": -2.0, "falhou": -1.4, "falta": -1.0, "fraco": -1.1, "fraca": -1.1,
    "fraude": -1.9, "greve": -1.2, "guerra": -1.8, "impedimento": -1.1, "incerto": -0.9,
    "incerteza": -1.1, "inflacao": -1.2, "inflação": -1.2, "insuficiente": -1.1, "irregularidade": -1.3,
    "mau": -1.3, "má": -1.3, "maus": -1.2, "más": -1.2, "negativo": -1.4, "negativa": -1.4, "negativos": -1.4,
    "perda": -1.4, "perdas": -1.4, "perde": -1.2, "perdeu": -1.2, "perder": -1.1, "pessimo": -2.0,
    "péssimo": -2.0, "pior": -1.4, "piores": -1.4, "piorou": -1.4, "prejuizo": -1.5, "prejuízo": -1.5,
    "preocupacao": -1.0, "preocupação": -1.0, "preocupa": -1.0, "problema": -1.3, "problemas": -1.3,
    "protesto": -1.2, "recessao": -1.7, "recessão": -1.7, "recusa": -1.0, "reduz": -0.6,
    "reducao": -0.7, "redução": -0.7, "risco": -0.9, "riscos": -0.9, "sanção": -1.4, "sancao": -1.4,
    "suspensao": -1.2, "suspensão": -1.2, "suspende": -1.1, "tensao": -1.1, "tensão": -1.1,
    "turbulencia": -1.4, "turbulência": -1.4, "violacao": -1.5, "violação": -1.5, "volatilidade": -0.9,
    "aumento": -0.3, "aumenta": -0.3, "disputa": -0.8, "indignacao": -1.4, "indignação": -1.4,
}

NEGATIONS = {"nao", "não", "nunca", "jamais", "sem", "nenhum", "nenhuma", "nem", "tampouco", "nem-sequer"}
INTENSIFIERS = {
    "muito": 1.6, "muita": 1.6, "muitos": 1.6, "muitas": 1.6, "bastante": 1.5, "bastantes": 1.5,
    "extremamente": 1.9, "totalmente": 1.7, "completamente": 1.7, "demasiado": 1.5, "demasiada": 1.5,
    "fortemente": 1.5, "profundamente": 1.5, "grave": 1.4, "graves": 1.4, "significativo": 1.3,
    "significativa": 1.3, "acima": 1.2, "abaixo": 1.2,
}
DIMINISHERS = {"pouco": 0.6, "pouca": 0.6, "poucos": 0.6, "poucas": 0.6, "ligeiramente": 0.5,
               "levemente": 0.5, "quase": 0.7, "algo": 0.7, "relativamente": 0.8, "ligeiro": 0.6}

STOPWORDS = {
    "a", "ao", "aos", "as", "com", "como", "da", "das", "de", "do", "dos", "e", "em", "entre", "era", "essa",
    "esse", "esta", "este", "eu", "foi", "for", "ha", "há", "isso", "isto", "ja", "já", "lhe", "mais", "mas",
    "me", "mesmo", "meu", "na", "nas", "no", "nos", "o", "os", "ou", "para", "pela", "pelo", "por", "que",
    "se", "sem", "ser", "seu", "sua", "suas", "seus", "so", "só", "são", "sao", "tem", "ter", "tu", "um",
    "uma", "vai", "vão", "vao", "à", "às", "é", "e", "the", "of", "and", "to",
    # inglês (as notícias indexadas misturam originais em inglês)
    "that", "said", "with", "from", "for", "this", "have", "will", "were", "been", "they", "their",
    "which", "after", "over", "more", "than", "into", "about", "also", "when", "what", "your", "its",
}

_TOKEN_RE = re.compile(r"[A-Za-zÀ-ÿ]{3,}")
_SENTENCE_RE = re.compile(r"[^.!?…\n]+[.!?…]?")
# URL e «lixo» de parâmetros (miniaturas, trackers) que não é conteúdo.
_URL_RE = re.compile(r"https?://\S+", re.I)
_QUERY_NOISE_RE = re.compile(r"\b\w+\s*=\s*\S+|\b(?:delay_optim|webp|crop|epic|srcset|amp)\b", re.I)
_NEGATION_WINDOW = 3
_POSITIVE_THRESHOLD = 0.15
_NEGATIVE_THRESHOLD = -0.15

# Modelo neuronal opcional (usado só se pedido e se estiver disponível).
DEFAULT_TRANSFORMER_MODEL = os.getenv("SENTIMENT_MODEL", "nlptown/bert-base-multilingual-uncased-sentiment")
_transformer_cache: Dict[str, Any] = {}


# ------------------------------------------------------------------ utilidades
def _fold(value: str) -> str:
    return (
        (value or "")
        .lower()
        .replace("á", "a").replace("à", "a").replace("â", "a").replace("ã", "a")
        .replace("é", "e").replace("ê", "e").replace("í", "i")
        .replace("ó", "o").replace("ô", "o").replace("õ", "o")
        .replace("ú", "u").replace("ç", "c")
    )


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def clean_text(value: Any) -> str:
    """Remove ligações e parâmetros de imagem/rastreio do texto a analisar.

    Os itens recolhidos podem trazer miniaturas e trackers no meio do conteúdo;
    sem isto, as palavras-chave ficariam cheias de `delay_optim` e afins.
    """
    text = _URL_RE.sub(" ", str(value or ""))
    text = _QUERY_NOISE_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def label_for(polarity: float) -> str:
    if polarity >= _POSITIVE_THRESHOLD:
        return "positivo"
    if polarity <= _NEGATIVE_THRESHOLD:
        return "negativo"
    return "neutro"


def _lexicon_lookup(token: str) -> Optional[float]:
    """Peso de um token (aceita a forma exata e a forma sem acentos)."""
    if token in LEXICON:
        return LEXICON[token]
    folded = _fold(token)
    return LEXICON.get(folded) or LEXICON.get(token.replace("ç", "c"))


# --------------------------------------------------------------- análise base
def analyze_text(text: str, *, max_length: int = 200_000) -> Dict[str, Any]:
    """Analisa um texto: polaridade, frases, termos encontrados e contagens."""
    raw = clean_text(text)[:max_length]
    sentences = [match.group(0).strip() for match in _SENTENCE_RE.finditer(raw)]
    sentences = [sentence for sentence in sentences if len(sentence) > 3] or ([raw.strip()] if raw.strip() else [])

    tokens: List[str] = []
    matched: List[Dict[str, Any]] = []
    sentence_rows: List[Dict[str, Any]] = []
    positive_terms = negative_terms = 0
    total_weight = 0.0

    for sentence in sentences:
        sentence_tokens = [match.group(0).lower() for match in _TOKEN_RE.finditer(sentence)]
        tokens.extend(sentence_tokens)
        score = 0.0
        hits = 0
        for index, token in enumerate(sentence_tokens):
            weight = _lexicon_lookup(token)
            if weight is None:
                continue
            multiplier = 1.0
            # Intensificador imediatamente antes («muito bom»).
            if index:
                previous = sentence_tokens[index - 1]
                multiplier *= INTENSIFIERS.get(previous, DIMINISHERS.get(previous, 1.0))
            # Negação na janela anterior («não é bom»).
            window = sentence_tokens[max(0, index - _NEGATION_WINDOW) : index]
            if any(word in NEGATIONS for word in window):
                multiplier *= -1.0
            value = weight * multiplier
            score += value
            hits += 1
            matched.append({"term": token, "weight": round(weight, 2), "value": round(value, 2)})
            if value > 0:
                positive_terms += 1
            elif value < 0:
                negative_terms += 1
        total_weight += score
        # Polaridade da frase normalizada pelo número de termos encontrados.
        sentence_polarity = max(-1.0, min(1.0, score / max(1.0, hits * 2))) if hits else 0.0
        sentence_rows.append({"text": sentence[:240], "polarity": round(sentence_polarity, 3), "hits": hits})

    # Polaridade do documento: soma normalizada pela raiz dos termos (evita que
    # textos longos fiquem «extremos» só por serem longos).
    hits_total = len(matched)
    polarity = max(-1.0, min(1.0, total_weight / math.sqrt(max(1.0, hits_total)) / 2.0)) if hits_total else 0.0

    return {
        "polarity": round(polarity, 3),
        "label": label_for(polarity),
        "score": round(total_weight, 2),
        "tokens": len(tokens),
        "hits": hits_total,
        "positive_terms": positive_terms,
        "negative_terms": negative_terms,
        "sentences": sentence_rows[:200],
        "matched": matched[:400],
        "words": len(tokens),
    }


def _transformer_pipeline(model: str) -> Optional[Any]:
    """Carrega (uma vez) o pipeline de sentimento do `transformers`, se possível."""
    if model in _transformer_cache:
        return _transformer_cache[model]
    pipeline = None
    try:
        from transformers import pipeline as hf_pipeline  # type: ignore

        pipeline = hf_pipeline("sentiment-analysis", model=model, truncation=True, max_length=512)
    except Exception as exc:
        logger.warning("Modelo de sentimento indisponível (%s): %s", model, exc)
        pipeline = None
    _transformer_cache[model] = pipeline
    return pipeline


def _transformer_scores(texts: Sequence[str], model: str) -> Optional[List[Dict[str, Any]]]:
    """Polaridade por texto com um modelo neuronal (ou `None` se indisponível)."""
    pipeline = _transformer_pipeline(model)
    if pipeline is None:
        return None
    try:
        outputs = pipeline(list(texts))
    except Exception as exc:
        logger.warning("Falha ao aplicar o modelo de sentimento: %s", exc)
        return None
    rows: List[Dict[str, Any]] = []
    for output in outputs:
        label = str(output.get("label") or "").lower()
        score = float(output.get("score") or 0.0)
        # Modelos com estrelas (1-5) → polaridade; modelos pos/neg → direto.
        stars = re.search(r"(\d)\s*star", label)
        if stars:
            polarity = (int(stars.group(1)) - 3) / 2.0
        elif "neg" in label:
            polarity = -score
        elif "pos" in label:
            polarity = score
        else:
            polarity = 0.0
        rows.append({"polarity": round(max(-1.0, min(1.0, polarity)), 3), "label": label_for(polarity), "confidence": round(score, 3)})
    return rows


# ----------------------------------------------------------------- corpus/pandas
def analyze_documents(
    documents: Sequence[Dict[str, Any]],
    *,
    engine: str = "lexicon",
    text_field: str = "text",
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """Analisa uma lista de documentos e agrega tudo com pandas."""
    rows: List[Dict[str, Any]] = []
    model_id = model or DEFAULT_TRANSFORMER_MODEL
    neural: Optional[List[Dict[str, Any]]] = None
    if engine in ("neural", "auto") and documents:
        neural = _transformer_scores([str(doc.get(text_field) or "")[:4000] for doc in documents], model_id)
        if neural is None and engine == "neural":
            engine = "lexicon"

    for index, doc in enumerate(documents):
        text = str(doc.get(text_field) or "")
        base = analyze_text(text)
        if neural and index < len(neural):
            base["polarity"] = neural[index]["polarity"]
            base["label"] = neural[index]["label"]
            base["confidence"] = neural[index]["confidence"]
        rows.append(
            {
                "id": str(doc.get("id") or f"doc-{index + 1}"),
                "title": str(doc.get("title") or "")[:200],
                "source": str(doc.get("source") or doc.get("source_label") or "—"),
                "date": doc.get("date"),
                "url": doc.get("url") or "",
                "polarity": base["polarity"],
                "label": base["label"],
                "score": base["score"],
                "hits": base["hits"],
                "words": base["words"],
                "engine": "neural" if neural and index < len(neural) else "lexicon",
                "matched": base["matched"][:40],
                "sentences": base["sentences"][:20],
                "excerpt": re.sub(r"\s+", " ", text)[:300],
            }
        )

    frame = pd.DataFrame(rows)
    summary: Dict[str, Any] = {
        "documents": int(len(frame)),
        "engine": "neural" if (neural is not None) else "lexicon",
        "model": model_id if (neural is not None) else None,
        "generated_at": _now(),
    }
    if frame.empty:
        summary.update({"mean_polarity": 0.0, "label": "neutro", "positive": 0, "negative": 0, "neutral": 0})
        return {"summary": summary, "rows": [], "by_source": [], "by_day": [], "terms": [], "distribution": [], "keywords": []}

    polarity = frame["polarity"].astype(float)
    mean = float(polarity.mean())
    std = float(polarity.std(ddof=0) or 0.0)
    count = int(len(frame))
    # Intervalo de confiança a 95 % da média (aproximação normal).
    margin = 1.96 * std / math.sqrt(count) if count > 1 else 0.0
    labels = frame["label"].value_counts().to_dict()

    summary.update(
        {
            "mean_polarity": round(mean, 3),
            "median_polarity": round(float(polarity.median()), 3),
            "std_polarity": round(std, 3),
            "ci95": [round(mean - margin, 3), round(mean + margin, 3)],
            "label": label_for(mean),
            "positive": int(labels.get("positivo", 0)),
            "negative": int(labels.get("negativo", 0)),
            "neutral": int(labels.get("neutro", 0)),
            "positive_share": round(labels.get("positivo", 0) / count, 3),
            "negative_share": round(labels.get("negativo", 0) / count, 3),
            "extreme_positive": frame.loc[polarity.idxmax()].to_dict() if count else None,
            "extreme_negative": frame.loc[polarity.idxmin()].to_dict() if count else None,
        }
    )

    # Agregados (pandas): por fonte e por dia.
    by_source = (
        frame.groupby("source")
        .agg(documents=("polarity", "size"), polarity=("polarity", "mean"), desvio=("polarity", "std"))
        .reset_index()
        .sort_values("polarity", ascending=False)
    )
    by_source = [
        {
            "source": str(row["source"]),
            "documents": int(row["documents"]),
            "polarity": round(float(row["polarity"]), 3),
            "label": label_for(float(row["polarity"])),
            "std": round(float(row["desvio"] or 0.0), 3),
        }
        for _, row in by_source.iterrows()
    ]

    by_day: List[Dict[str, Any]] = []
    dated = frame[frame["date"].notna()].copy()
    if not dated.empty:
        dated["day"] = pd.to_datetime(dated["date"], errors="coerce").dt.strftime("%Y-%m-%d")
        dated = dated[dated["day"].notna()]
        if not dated.empty:
            grouped = (
                dated.groupby("day")
                .agg(documents=("polarity", "size"), polarity=("polarity", "mean"))
                .reset_index()
                .sort_values("day")
            )
            by_day = [
                {"day": str(row["day"]), "documents": int(row["documents"]), "polarity": round(float(row["polarity"]), 3)}
                for _, row in grouped.iterrows()
            ]

    # Termos com peso (positivos e negativos) e palavras-chave TF-IDF.
    term_counts: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        for hit in row.get("matched") or []:
            entry = term_counts.setdefault(hit["term"], {"term": hit["term"], "count": 0, "weight": 0.0})
            entry["count"] += 1
            entry["weight"] += hit["value"]
    terms = sorted(term_counts.values(), key=lambda item: abs(item["weight"]), reverse=True)
    for entry in terms:
        entry["weight"] = round(entry["weight"], 2)
        entry["polarity"] = "positivo" if entry["weight"] > 0 else "negativo"

        texts = [clean_text(doc.get(text_field)) for doc in documents if clean_text(doc.get(text_field)).strip()]
    keywords = _keywords(texts, top=20)

    return {
        "summary": summary,
        "rows": rows,
        "by_source": by_source,
        "by_day": by_day,
        "terms": terms[:40],
        "keywords": keywords,
        "distribution": [
            {"label": "positivo", "count": int(labels.get("positivo", 0))},
            {"label": "neutro", "count": int(labels.get("neutro", 0))},
            {"label": "negativo", "count": int(labels.get("negativo", 0))},
        ],
    }


def _keywords(texts: Sequence[str], top: int = 20) -> List[Dict[str, Any]]:
    """Palavras-chave do corpus com TF-IDF (scikit-learn), 1–2 gramas."""
    if not texts:
        return []
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer  # type: ignore

        vectorizer = TfidfVectorizer(
            lowercase=True,
            ngram_range=(1, 2),
            stop_words=sorted(STOPWORDS),
            max_features=400,
            # Só palavras (4+ letras): exclui números e «delay_optim»-like.
            token_pattern=r"(?u)\b[^\W\d_]{4,}\b",
            min_df=2 if len(texts) > 4 else 1,
        )
        matrix = vectorizer.fit_transform([_fold(text) for text in texts])
    except Exception as exc:
        logger.debug("TF-IDF indisponível: %s", exc)
        return []
    scores = matrix.mean(axis=0).A1
    names = vectorizer.get_feature_names_out()
    ordered = sorted(zip(names, scores), key=lambda pair: -pair[1])[: max(1, top)]
    return [{"term": str(term), "score": round(float(score), 4)} for term, score in ordered]


# -------------------------------------------------------------------- recursos
def corpus_from_scraped(q: Optional[str] = None, source_id: Optional[str] = None, limit: int = 60) -> List[Dict[str, Any]]:
    """Constrói um corpus a partir dos dados recolhidos (scraping)."""
    from api.elasticsearch_client import search_scraped

    result = search_scraped(q=q, source_id=source_id, size=max(1, min(limit, 200)), sort="relevance" if q else "recent")
    documents = []
    for hit in result.get("items") or []:
        documents.append(
            {
                "id": hit.get("item_id") or "",
                "title": hit.get("title") or "",
                "source": hit.get("source_name") or hit.get("source_id") or "Recolha",
                "date": hit.get("scraped_at"),
                "url": hit.get("url") or "",
                "text": clean_text(" ".join([str(hit.get("title") or ""), str(hit.get("summary") or ""), str(hit.get("text") or "")])),
            }
        )
    return documents


def corpus_from_news(q: Optional[str] = None, limit: int = 60) -> List[Dict[str, Any]]:
    """Constrói um corpus a partir das notícias indexadas (`finance_news`)."""
    from api.elasticsearch_client import get_es_client, ensure_indices

    client = get_es_client()
    if not client:
        return []
    ensure_indices(client)
    query: Dict[str, Any] = (
        {
            "bool": {
                "should": [
                    {"multi_match": {"query": q, "fields": ["title^3", "summary^2", "summary_pt^2", "translated_title", "topics"], "lenient": True}},
                    {"term": {"ticker": (q or "").upper()}},
                ],
                "minimum_should_match": 1,
            }
        }
        if q
        else {"match_all": {}}
    )
    try:
        resp = client.search(
            index="finance_news",
            body={"size": max(1, min(limit, 200)), "query": query, "sort": ["_score", {"published": "desc"}]},
        )
    except Exception as exc:
        logger.warning("Corpus de notícias falhou: %s", exc)
        return []
    documents: List[Dict[str, Any]] = []
    for hit in resp.get("hits", {}).get("hits", []):
        row = hit.get("_source") or {}
        documents.append(
            {
                "id": hit.get("_id") or "",
                "title": row.get("translated_title") or row.get("title") or "",
                "source": " · ".join(filter(None, [row.get("publisher"), row.get("ticker")])) or "Notícias",
                "date": row.get("published"),
                "url": row.get("url") or "",
                "text": " ".join(
                    str(part)
                    for part in (
                        row.get("title"),
                        row.get("translated_title"),
                        row.get("summary_pt"),
                        row.get("translated_summary"),
                        row.get("summary"),
                    )
                    if part
                ),
            }
        )
    return documents


def corpus_from_dossier(dossier_id: str, ontology_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Corpus a partir de um dossiê de análise guardado (itens + síntese)."""
    from api import search360_store

    dossier = search360_store.get_dossier(dossier_id, ontology_id)
    snapshot = dossier.get("snapshot") or {}
    documents: List[Dict[str, Any]] = []
    for entry in snapshot.get("items") or []:
        documents.append(
            {
                "id": str(entry.get("id") or entry.get("url") or ""),
                "title": entry.get("title") or "",
                "source": entry.get("source_label") or entry.get("source") or dossier.get("term") or "Dossiê",
                "date": entry.get("date"),
                "url": entry.get("url") or "",
                "text": " ".join(str(part) for part in (entry.get("title"), entry.get("snippet")) if part),
            }
        )
    synthesis = snapshot.get("synthesis") or {}
    text = synthesis.get("text") or synthesis.get("answer") or ""
    if text:
        documents.append(
            {
                "id": f"{dossier_id}:sintese",
                "title": f"Síntese — {dossier.get('title') or dossier_id}",
                "source": "Síntese do dossiê",
                "date": snapshot.get("generated_at"),
                "url": "",
                "text": str(text),
            }
        )
    return documents


def corpus_from_office(document_id: str) -> List[Dict[str, Any]]:
    """Corpus a partir de um documento do Office (o Markdown é o texto)."""
    from api import office_store

    document = office_store.get_document(document_id)
    markdown = str(document.get("markdown") or "")
    if not markdown.strip():
        return []
    return [
        {
            "id": document_id,
            "title": document.get("title") or document_id,
            "source": "Office",
            "date": document.get("updated_at"),
            "url": "",
            "text": markdown,
        }
    ]


# ------------------------------------------------------------------- relatórios
def build_markdown(analysis: Dict[str, Any], *, title: str = "Análise de sentimento", term: str = "") -> str:
    """Relatório em Markdown, pronto para o dossiê e para o editor Office."""
    summary = analysis.get("summary") or {}
    lines: List[str] = [f"# {title}", ""]
    if term:
        lines += [f"**Tema:** {term}", ""]
    lines += [
        f"**Gerado em:** {summary.get('generated_at') or _now()}",
        f"**Motor:** {'modelo neuronal ' + str(summary.get('model')) if summary.get('engine') == 'neural' else 'léxico PT + estatística (scikit-learn/pandas)'}",
        f"**Documentos analisados:** {summary.get('documents', 0)}",
        f"**Sentimento médio:** {summary.get('mean_polarity', 0):+.3f} ({summary.get('label', 'neutro')})",
        f"**Intervalo de confiança (95 %):** [{summary.get('ci95', [0, 0])[0]:+.3f}, {summary.get('ci95', [0, 0])[1]:+.3f}]",
        f"**Distribuição:** {summary.get('positive', 0)} positivos · {summary.get('neutral', 0)} neutros · {summary.get('negative', 0)} negativos",
        "",
        "## Indicadores",
        "",
        "| Indicador | Valor |",
        "| --- | --- |",
        f"| Polaridade média | {summary.get('mean_polarity', 0):+.3f} |",
        f"| Mediana | {summary.get('median_polarity', 0):+.3f} |",
        f"| Desvio-padrão | {summary.get('std_polarity', 0):.3f} |",
        f"| Positivos | {summary.get('positive', 0)} ({summary.get('positive_share', 0):.0%}) |",
        f"| Negativos | {summary.get('negative', 0)} ({summary.get('negative_share', 0):.0%}) |",
        "",
    ]

    by_source = analysis.get("by_source") or []
    if by_source:
        lines += ["## Sentimento por fonte", "", "| Fonte | Documentos | Polaridade | Leitura |", "| --- | --- | --- | --- |"]
        for row in by_source:
            lines.append(f"| {row['source']} | {row['documents']} | {row['polarity']:+.3f} | {row['label']} |")
        lines.append("")

    by_day = analysis.get("by_day") or []
    if by_day:
        lines += ["## Evolução diária", "", "| Dia | Documentos | Polaridade |", "| --- | --- | --- |"]
        for row in by_day:
            lines.append(f"| {row['day']} | {row['documents']} | {row['polarity']:+.3f} |")
        lines.append("")

    terms = analysis.get("terms") or []
    if terms:
        positives = [t for t in terms if t["weight"] > 0][:10]
        negatives = [t for t in terms if t["weight"] < 0][:10]
        lines += ["## Termos que mais pesaram", ""]
        if positives:
            lines.append("**Positivos:** " + ", ".join(f"{t['term']} ({t['weight']:+.1f}×{t['count']})" for t in positives))
            lines.append("")
        if negatives:
            lines.append("**Negativos:** " + ", ".join(f"{t['term']} ({t['weight']:+.1f}×{t['count']})" for t in negatives))
            lines.append("")

    keywords = analysis.get("keywords") or []
    if keywords:
        lines += ["## Palavras-chave (TF-IDF)", "", ", ".join(f"`{item['term']}`" for item in keywords[:20]), ""]

    rows = analysis.get("rows") or []
    if rows:
        lines += ["## Documentos", "", "| Documento | Fonte | Data | Polaridade | Leitura |", "| --- | --- | --- | --- | --- |"]
        for row in rows[:40]:
            title_cell = str(row.get("title") or row.get("id") or "")[:80].replace("|", "/")
            lines.append(
                f"| {title_cell} | {row.get('source')} | {str(row.get('date') or '')[:10]} | {row['polarity']:+.3f} | {row['label']} |"
            )
        lines.append("")

    lines += ["---", "", "Gerado pelo IQ OS · Análise de sentimento (léxico PT + estatística com pandas/scikit-learn)."]
    return "\n".join(lines)


def to_csv(analysis: Dict[str, Any]) -> str:
    """Exporta a tabela por documento em CSV (via pandas)."""
    rows = analysis.get("rows") or []
    frame = pd.DataFrame(rows)
    if frame.empty:
        return "id,title,source,date,polarity,label\n"
    columns = ["id", "title", "source", "date", "polarity", "label", "hits", "words"]
    for column in columns:
        if column not in frame.columns:
            frame[column] = None
    buffer = io.StringIO()
    frame[columns].to_csv(buffer, index=False)
    return buffer.getvalue()


def meta() -> Dict[str, Any]:
    """Estado do módulo (motores, léxico e integrações disponíveis)."""
    neural_available = False
    try:
        import transformers  # type: ignore

        neural_available = True
    except Exception:
        neural_available = False
    return {
        "engines": [
            {"id": "lexicon", "label": "Léxico PT + estatística", "detail": f"{len(LEXICON)} termos, negação e intensificadores, pandas + scikit-learn", "offline": True},
            {"id": "neural", "label": "Modelo neuronal (transformers)", "detail": DEFAULT_TRANSFORMER_MODEL, "offline": False, "available": neural_available},
        ],
        "lexicon_size": len(LEXICON),
        "thresholds": {"positive": _POSITIVE_THRESHOLD, "negative": _NEGATIVE_THRESHOLD},
        "keywords": "TF-IDF (scikit-learn, 1–2 gramas)",
        "aggregation": "pandas (média, mediana, desvio, IC 95 %, por fonte e por dia)",
        "dossiers": True,
        "office": True,
    }


# ------------------------------------------------------------------ integrações
def save_to_dossier(dossier_id: str, analysis: Dict[str, Any], *, title: Optional[str] = None, ontology_id: Optional[str] = None) -> Dict[str, Any]:
    """Guarda a análise no dossiê de análise (Pesquisa 360)."""
    from api import search360_store

    dossier = search360_store.get_dossier(dossier_id, ontology_id)
    report_title = title or f"Análise de sentimento — {dossier.get('term') or dossier.get('title') or dossier_id}"
    markdown = build_markdown(analysis, title=report_title, term=str(dossier.get("term") or ""))
    return search360_store.save_sentiment(dossier_id, analysis, markdown=markdown, ontology_id=ontology_id)


def save_to_office(
    analysis: Dict[str, Any],
    *,
    title: str,
    tags: Optional[Iterable[str]] = None,
    folder_id: Optional[str] = None,
    author: Optional[str] = None,
    dossier_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Cria (ou atualiza) um documento no Office com o relatório em Markdown."""
    from api import office_store

    markdown = build_markdown(analysis, title=title)
    payload: Dict[str, Any] = {
        "title": title,
        "kind": "relatorio",
        "markdown": markdown,
        "tags": [str(tag) for tag in (tags or []) if str(tag).strip()] or ["sentimento"],
        "source": {"type": "sentiment", "dossier_id": dossier_id} if dossier_id else {"type": "sentiment"},
        "folder_id": folder_id,
    }
    document = office_store.save_document(payload, author=author)
    return {"saved": True, "document": document}
