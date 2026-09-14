"""Análise NLP de notícias financeiras.

Combina modelos locais (gpt2/mistral) com heurísticas determinísticas e um modelo
de tradução Helsinki-NLP/opus-mt-en-pt para produzir output estruturado útil:
sentimento, idioma, tradução/sumário em PT, entidades e tópicos.
"""
import json
import re
import threading
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Dict, List, Optional

# Import adiado para não carregar GPT-2/Mistral apenas para usar o tradutor.
_get_inference_model = None

def get_inference_model(backend: str = "gpt2"):
    global _get_inference_model
    if _get_inference_model is None:
        from api.agent import get_inference_model as _gim
        _get_inference_model = _gim
    return _get_inference_model(backend)

# -----------------------------------------------------------------------------
# Tradutor EN-PT baseado em Helsinki-NLP/opus-mt-tc-big-en-pt (mirror acessível
# do Helsinki-NLP/opus-mt-en-pt). Lazy load, thread-safe.
# -----------------------------------------------------------------------------
TRANSLATION_MODEL_NAME = "Helsinki-NLP/opus-mt-tc-big-en-pt"

class _TranslationModel:
    _instance: Optional[Any] = None
    _tokenizer: Optional[Any] = None
    _lock = threading.Lock()

    @classmethod
    def translate(cls, text: str) -> str:
        if not text or not text.strip():
            return ""
        try:
            with cls._lock:
                if cls._instance is None:
                    from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
                    cls._tokenizer = AutoTokenizer.from_pretrained(TRANSLATION_MODEL_NAME)
                    cls._instance = AutoModelForSeq2SeqLM.from_pretrained(TRANSLATION_MODEL_NAME)

            inputs = cls._tokenizer(text, return_tensors="pt", padding=True, truncation=True, max_length=512)
            translated = cls._instance.generate(**inputs, max_length=512, num_beams=4, early_stopping=True)
            return cls._tokenizer.batch_decode(translated, skip_special_tokens=True)[0].strip()
        except Exception:
            # Fallback silencioso para o texto original se o modelo falhar.
            return ""


def _translate_en_to_pt(text: Optional[str]) -> str:
    """Traduz texto em inglês para português usando Helsinki-NLP/opus-mt-en-pt."""
    if not text:
        return ""
    return _TranslationModel.translate(text)

# Tickers/nomes conhecidos para extração de entidades. Expansível dinamicamente.
KNOWN_TICKERS = {
    "AAPL", "TSLA", "GOOGL", "GOOG", "MSFT", "AMZN", "NVDA", "META", "NFLX",
    "AMD", "INTC", "IBM", "ORCL", "CRM", "SAP", "UBER", "ABNB", "PYPL",
    "BABA", "TCEHY", "JD", "TSM", "ASML", "SONY", "DIS", "WBD", "CMCSA",
    "VZ", "T", "TMUS", "NOK", "ERIC", "QCOM", "AVGO", "TXN", "ADI", "MU",
    "LRCX", "KLAC", "AMAT", "SNPS", "CDNS", "ANSS", "PTC", "PAYC", "ADSK",
    "HPQ", "DELL", "HPE", "CSCO", "JNJ", "PFE", "UNH", "ABBV", "LLY", "MRK",
    "AZN", "GILD", "AMGN", "CVS", "WMT", "TGT", "COST", "HD", "LOW", "NKE",
    "MCD", "SBUX", "KO", "PEP", "PG", "UL", "NESN.SW", "ROG.SW", "NOVN.SW",
    "SAP", "SIE.DE", "ALV.DE", "DBK.DE", "BMW.DE", "VOW.DE", "PAH3.DE",
    "AIR.PA", "OR.PA", "MC.PA", "LVMH.PA", "TTE.PA", "SAN.PA", "BNP.PA",
    "GLE.PA", "CS.PA", "UBSG.SW", "ABB.SW", "NESN.SW", "BP.L", "SHEL.L",
    "RDSA.AS", "TTE.PA", "ENEL.MI", "ENI.MI", "ISP.MI", "UCG.MI", "UNI.MI",
    "STLA.MI", " Ferrari ", "ALTR.LS", "GALP.LS", "EDP.LS", "JMT.LS", "NOS.LS",
    "SON.LS", "BCP.LS", "REN.LS", "ESON.ST", "ESSITY-B.ST", "EVO.ST", "ERIC-B.ST",
    "SEB-A.ST", "SCA-B.ST", "SAND.ST", "SKF-B.ST", "SWED-A.ST", "TEL2-B.ST",
    "TELIA.ST", "VOLV-B.ST", "ALFA.ST", "INDU-C.ST", "INDT.ST", "LATO-B.ST",
    "LIFCO-B.ST", "LOOMIS.ST", "NIBE-B.ST", "PEAB-B.ST", "RATO-B.ST", "SAAB-B.ST",
    "SAGA-D.ST", "SBB-B.ST", "SECU-B.ST", "SINCH.ST", "SKIS-B.ST", "SSAB-A.ST",
    "SVOL-B.ST", "TFBANK.ST", "THULE.ST", "TREL-B.ST", "WALL-B.ST",
}

# Empresas e palavras chave associadas a entidades.
COMPANY_NAMES = {
    "apple": "AAPL", "iphone": "AAPL", "ipad": "AAPL", "mac": "AAPL", "siri": "AAPL",
    "duolingo": "DUOL", "duo": "AAPL",
    "tesla": "TSLA", "cybertruck": "TSLA",
    "google": "GOOGL", "alphabet": "GOOGL", "youtube": "GOOGL", "android": "GOOGL",
    "microsoft": "MSFT", "windows": "MSFT", "xbox": "MSFT", "azure": "MSFT",
    "amazon": "AMZN", "aws": "AMZN", "prime": "AMZN",
    "nvidia": "NVDA", "geforce": "NVDA", "rtx": "NVDA", "gpu": "NVDA",
    "meta": "META", "facebook": "META", "instagram": "META", "whatsapp": "META",
    "netflix": "NFLX", "stream": "NFLX",
    "disney": "DIS", "pixar": "DIS", "marvel": "DIS",
    "intel": "INTC", "amd": "AMD", "qualcomm": "QCOM", "broadcom": "AVGO",
    "oracle": "ORCL", "salesforce": "CRM", "sap": "SAP", "airbnb": "ABNB",
    "uber": "UBER", "paypal": "PYPL", "alibaba": "BABA",
    "shell": "SHEL", "bp": "BP", "total": "TTE", "eni": "ENI",
    "nestlé": "NESN.SW", "nestle": "NESN.SW", "roche": "ROG.SW", "novartis": "NOVN.SW",
    "siemens": "SIE.DE", "bmw": "BMW.DE", "volkswagen": "VOW.DE", "porsche": "PAH3.DE",
    "lvmh": "MC.PA", "airbus": "AIR.PA", "orange": "OR.PA", "totalenergies": "TTE.PA",
    "bnp": "BNP.PA", "société générale": "GLE.PA", "societe generale": "GLE.PA",
    "ubs": "UBSG.SW", "abb": "ABB.SW", "credit suisse": "CS.PW",
    "galp": "GALP.LS", "edp": "EDP.LS", "jerónimo martins": "JMT.LS",
    "nos": "NOS.LS", "sonae": "SON.LS", "bcp": "BCP.LS", "ren": "REN.LS",
}

# Pessoas conhecidas no contexto tech/finance.
KNOWN_PEOPLE = {
    "tim cook", "steve jobs", "jeff bezos", "andy jassy", "satya nadella",
    "sundar pichai", "elon musk", "mark zuckerberg", "lisa su", "jensen huang",
    "john ternus", "craig federighi", "phil schiller", "dan ives",
    "keith lerner", "kevin mahn", "julie hyman", "jerome powell", "warren buffett",
}

# Padrões de produtos e eventos.
PRODUCT_PATTERNS = re.compile(
    r"\b(iPhone(?:\s+(?:\d+|SE)(?:\s+(?:Pro\s*Max|Pro\s*Plus|Pro|Plus|Ultra))?|"
    r"\s+(?:Pro\s*Max|Pro\s*Plus|Pro|Plus|Ultra|mini|Duo|Air|Fold|Flip))?|"
    r"iPad(?:\s+(?:Air|mini|Pro(?:\s+\d+)?))?|Apple\s+Watch(?:\s+(?:Series\s*\d+|Ultra))?|"
    r"AirPods(?:\s+Pro)?(?:\s+\d+)?|MacBook(?:\s+(?:Air|Pro))?|Vision\s+Pro|"
    r"Cybertruck|Model\s+[3YSX]|Windows\s+\d+|Xbox(?:\s+Series\s*[SX])?|PlayStation\s*\d+|"
    r"RTX\s+\d+|GeForce\s+RTX|Google\s+Pixel\s*\d+|Galaxy\s+S\d+|Galaxy\s+Fold|Foldable\s+iPhone|"
    r"iPhone\s+Duo)\b",
    re.IGNORECASE,
)

# Palavras que nunca devem fazer parte do nome de um produto (evita 'iPhone vendas', 'iPad sales').
PRODUCT_STOPWORDS = {
    "sales", "vendas", "revenue", "receita", "profit", "lucro", "earnings", "market", "mercado",
    "stock", "ação", "shares", "ações", "price", "preço", "users", "utilizadores", "carries",
    "models", "modelos", "line", "gama", "series", "could", "poder", "poderá", "might", "can",
    "will", "shall", "make", "fazer", "say", "diz", "says", "of", "de", "the", "a", "an",
}

# Lexicon de sentimento (PT/EN).
POSITIVE_WORDS = {
    "surge", "rises", "gains", "rally", "soar", "jump", "boost", "strong", "growth",
    "profit", "record", "beat", "outperform", "upgrade", "bullish", "opportunity",
    "optimistic", "impressive", "advance", "success", "win", "solid", "surges",
    "soars", "jumps", "rallies", "climbs", "rebound", "bull", "positive",
    "subir", "aumentar", "crescer", "crescimento", "lucro", "recorde", "superar",
    "valorização", "oportunidade", "otimista", "impressionante", "avanço", "sucesso",
    "ganhar", "ganhos", "forte", "positivo", "expansão", "dividendo",
}
NEGATIVE_WORDS = {
    "fall", "falls", "drop", "drops", "decline", "plunge", "crash", "sink", "slide",
    "slump", "tumble", "weak", "loss", "miss", "underperform", "downgrade", "bearish",
    "risk", "crisis", "recession", "inflation", "layoff", "fear", "worry", "concern",
    "threat", "threatens", "threatened", "obsolete", "distracts", "problems",
    "descer", "cair", "queda", "afundar", "desaceleração", "perda", "fraco", "ruim",
    "crise", "recessão", "inflação", "medo", "preocupação", "ameaça", "ameaçar",
    "obsoleto", "problema", "despedimento", "demissão", "risco", "negativo",
}


def _clean_model_output(raw: str) -> str:
    """Remove conteúdo extra que o modelo possa gerar para devolver só JSON."""
    if not raw:
        return ""
    raw = raw.strip()
    if "```" in raw:
        parts = raw.split("```")
        for p in parts:
            t = p.strip()
            if t.startswith("{") and t.endswith("}"):
                return t
            if t.startswith("[") and t.endswith("]"):
                return t
    match = re.search(r"\{.*?\}", raw, re.DOTALL)
    if match:
        return match.group(0)
    return raw


def _parse_json(raw: str, default: dict):
    """Tenta fazer parse de JSON; em caso de falha devolve default."""
    cleaned = _clean_model_output(raw)
    if not cleaned:
        return default
    try:
        return json.loads(cleaned)
    except Exception:
        cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)
        try:
            return json.loads(cleaned)
        except Exception:
            return default


@dataclass
class NewsAnalysisResult:
    sentiment: str
    language: str
    translated_title: Optional[str]
    translated_summary: Optional[str]
    summary_pt: Optional[str]
    entities: List[Dict[str, str]]
    topics: List[str]
    raw_output: Optional[str] = None
    elapsed_ms: int = 0


def _detect_language(text: str) -> str:
    """Deteta idioma por palavras/caracteres típicos (fallback rápido)."""
    if not text:
        return "desconhecido"
    text_lower = text.lower()
    pt_markers = {"ação", "ações", "mercado", "empresa", "lucro", "queda", "subida", "económica", "económico",
                  "portugal", "português", "bolsa", "investimento", "resultados", "financeiro", "dividendo",
                  "receitas", "vendas", "crescimento", "prejuízo", "balanço", "trimestre",
                  "lança", "apresenta", "anuncia", "revela", "diz", "poderá", "impulsionar", "dobrável",
                  "novo", "nova", "funcionalidades", "modelos", "preço", "supera", "analistas"}
    es_markers = {"acción", "acciones", "empresa", "mercado", "beneficio", "pérdida", "subida", "bajada",
                  "españa", "español", "dividendo", "inversión", "resultados", "financiero"}
    fr_markers = {"action", "marché", "entreprise", "bénéfice", "perte", "france", "français", "dividende",
                  "investissement", "résultats", "financier"}
    de_markers = {"aktie", "aktien", "unternehmen", "markt", "gewinn", "verlust", "deutschland", "deutsch",
                  "dividende", "investition", "ergebnisse", "finanziell"}
    scores = {
        "pt": sum(1 for m in pt_markers if m in text_lower),
        "es": sum(1 for m in es_markers if m in text_lower),
        "fr": sum(1 for m in fr_markers if m in text_lower),
        "de": sum(1 for m in de_markers if m in text_lower),
    }
    best = max(scores, key=scores.get)
    if scores[best] > 0:
        return best
    # heurística simples: inglês por omissão se houver palavras comuns financeiras em inglês
    en_markers = {"stock", "market", "shares", "earnings", "revenue", "profit", "loss", "company", "trading",
                  "investor", "quarter", "fiscal", "dividend", "growth", "price"}
    if any(m in text_lower for m in en_markers):
        return "en"
    return "desconhecido"


def _heuristic_sentiment(title: str, summary: Optional[str]) -> str:
    """Classifica sentimento por palavras-chave."""
    text = f"{title} {summary or ''}".lower()
    pos = sum(1 for w in POSITIVE_WORDS if w in text)
    neg = sum(1 for w in NEGATIVE_WORDS if w in text)
    if pos > neg:
        return "positivo"
    if neg > pos:
        return "negativo"
    return "neutro"


def _translate_simple(text: Optional[str]) -> str:
    """Tradução EN-PT real via Helsinki-NLP/opus-mt-tc-big-en-pt (cache LRU)."""
    if not text:
        return ""
    key = text.strip()[:200]
    return _cached_translate(key) or text.strip()


@lru_cache(maxsize=512)
def _cached_translate(text: str) -> str:
    return _translate_en_to_pt(text)


def _translate_batch(texts: List[str]) -> List[str]:
    """Traduz um lote de textos EN-PT numa única passagem do modelo (limitado)."""
    if not texts:
        return []
    non_empty = [(i, t) for i, t in enumerate(texts) if t and t.strip()]
    if not non_empty:
        return [""] * len(texts)

    try:
        with _TranslationModel._lock:
            if _TranslationModel._instance is None:
                from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
                _TranslationModel._tokenizer = AutoTokenizer.from_pretrained(TRANSLATION_MODEL_NAME)
                _TranslationModel._instance = AutoModelForSeq2SeqLM.from_pretrained(TRANSLATION_MODEL_NAME)

        # Limita o tamanho do lote e trunca textos para reduzir latência em CPU.
        MAX_BATCH = 16
        MAX_LEN = 128
        chunks = non_empty[:MAX_BATCH]
        inputs = _TranslationModel._tokenizer(
            [t[:MAX_LEN] for _, t in chunks],
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=MAX_LEN,
        )
        translated = _TranslationModel._instance.generate(
            **inputs, max_length=MAX_LEN, num_beams=1, do_sample=False
        )
        decoded = _TranslationModel._tokenizer.batch_decode(translated, skip_special_tokens=True)
    except Exception:
        chunks = non_empty
        decoded = [t for _, t in non_empty]

    out = [""] * len(texts)
    for (i, _), d in zip(chunks, decoded):
        out[i] = d.strip()
    return out


def _summarize_pt(title: str, summary: Optional[str], sentiment: str) -> str:
    """Gera um sumário curto e fluente em português a partir do título/resumo traduzido."""
    text_pt = _translate_simple(title)
    if summary:
        translated_summary = _translate_simple(summary)
        # Só junta se trouxer informação nova e não for apenas repetição do título.
        if translated_summary and translated_summary.lower() not in text_pt.lower():
            text_pt += ". " + translated_summary

    # Normaliza espaços e pontuação.
    text_pt = re.sub(r"\s+", " ", text_pt).strip()
    text_pt = re.sub(r"\s+([.,;:!?])", r"\1", text_pt)

    # Corta após ~24 palavras, preferencialmente num ponto final.
    words = text_pt.split()
    if len(words) > 24:
        cut = " ".join(words[:24])
        # tenta terminar a frase num ponto final
        last_period = cut.rfind(".")
        if last_period > 15:
            text_pt = cut[: last_period + 1]
        else:
            text_pt = cut + "..."

    # Adiciona nuance de sentimento de forma natural.
    sentiment_nuance = {
        "positivo": "O tom geral é positivo.",
        "negativo": "O tom geral é negativo.",
        "neutro": "O tom geral é neutro.",
    }.get(sentiment, "")
    if sentiment_nuance and sentiment_nuance.lower() not in text_pt.lower():
        text_pt = (text_pt + " " + sentiment_nuance).strip()

    # Capitaliza primeira letra e remove artefactos de pontuação duplicada.
    text_pt = re.sub(r"\.{2,}", "...", text_pt)
    return text_pt[:1].upper() + text_pt[1:] if text_pt else ""


def _extract_entities(title: str, summary: Optional[str], ticker: Optional[str] = None) -> List[Dict[str, str]]:
    """Extrai entidades por regras sobre tickers, empresas, pessoas, produtos e eventos."""
    text = f"{title} {summary or ''}"
    text_lower = text.lower()
    found: Dict[str, Dict[str, str]] = {}

    # Ticker principal
    if ticker:
        t = ticker.upper()
        found[t] = {"name": t, "type": "ticker"}

    # Tickers conhecidos
    for tk in KNOWN_TICKERS:
        pat = r"\b" + re.escape(tk) + r"\b"
        if re.search(pat, text):
            found[tk.upper()] = {"name": tk.upper(), "type": "ticker"}

    # Empresas por nome
    for name, tk in COMPANY_NAMES.items():
        if name in text_lower:
            key = tk if tk in KNOWN_TICKERS else name.title()
            found[key] = {"name": name.title(), "type": "empresa"}
            # Também adiciona o ticker correspondente se conhecido.
            if tk in KNOWN_TICKERS:
                found[tk] = {"name": tk, "type": "ticker"}

    # Pessoas conhecidas
    for person in KNOWN_PEOPLE:
        if person in text_lower:
            found[person.title()] = {"name": person.title(), "type": "pessoa"}

    # Produtos por regex
    seen: set = set()
    for match in PRODUCT_PATTERNS.finditer(text):
        name = match.group(0).strip()
        key = name.lower()
        tokens = set(re.findall(r"[a-zA-Záéíóúãõç]+", key, flags=re.IGNORECASE))
        if tokens & PRODUCT_STOPWORDS:
            continue
        # Ignorar matches puramente genéricos que são apenas o nome base sem qualificador,
        # se uma versão qualificada do mesmo produto já foi vista no texto.
        base = re.split(r"\s+", key)[0]
        if base.lower() in {name.lower(): True for name in ["iphone", "ipad", "macbook", "airpods", "apple watch"]}:
            if len(key.split()) == 1 and seen:
                # só mantém iPhone/iPad isolado se nenhum outro produto qualificado foi encontrado
                if any(base in s and s != base for s in seen):
                    continue
            seen.add(key)
        if key not in found:
            found[key] = {"name": name, "type": "produto"}

    # Eventos/setores por palavras-chave
    event_keywords = {
        "earnings": "resultados", "quarter": "resultados trimestrais", "fiscal": "ano fiscal",
        "ipo": "IPO", "merger": "fusão", "acquisition": "aquisição", "split": "split",
        "dividend": "dividendo", "buyback": "recompra de ações", "guidance": "projeção",
        "announces": "anúncio", "reported": "reporte", "warns": "alerta",
    }
    for en, pt in event_keywords.items():
        if re.search(rf"\b{en}\b", text, re.IGNORECASE):
            found[pt] = {"name": pt, "type": "evento"}

    # Setores
    sector_keywords = ["tecnologia", "technology", "semiconductor", "semicondutores", "hardware",
                       "software", "cloud", "banco", "banking", "energia", "energy", "saúde", "healthcare",
        "automóvel", "automotive", "retail", "retalho", "telecom", "telecommunications"]
    for sector in sector_keywords:
        if re.search(rf"\b{sector}\b", text, re.IGNORECASE):
            pt = {"technology": "tecnologia", "semiconductor": "semicondutores",
                  "hardware": "hardware", "software": "software", "cloud": "cloud", "banking": "bancos",
                  "energy": "energia", "healthcare": "saúde", "automotive": "automóvel",
                  "retail": "retalho", "telecommunications": "telecomunicações"}.get(sector, sector)
            found[pt] = {"name": pt.title(), "type": "setor"}

    return list(found.values())


def _extract_topics(title: str, summary: Optional[str]) -> List[str]:
    """Extrai 1-3 tópicos em português baseados em palavras-chave."""
    text_lower = f"{title} {summary or ''}".lower()
    topics = []
    topic_keywords = [
        ("inteligência artificial", ["ai", "artificial intelligence", "ia", "inteligência artificial", "machine learning"]),
        ("lançamento de produto", ["launch", "launches", "unveils", "lança", "apresenta", "lançamento", "novo produto"]),
        ("resultados financeiros", ["earnings", "quarter", "revenue", "profit", "resultados", "lucro", "receitas", "trimestre"]),
        ("mercado de ações", ["stock market", "nasdaq", "shares", "mercado de ações", "bolsa", "ações"]),
        ("preço e valorização", ["price", "surge", "rises", "gains", "preço", "subida", "valorização", "queda"]),
        ("hardware", ["iphone", "ipad", "mac", "hardware", "dispositivos", "foldable"]),
        ("wearables", ["wearable", "watch", "airpods", "wearables"]),
        ("análise de analistas", ["analyst", "analysts", "ives", "analista", "analistas"]),
        ("concorrência", ["threatens", "distracts", "competition", "concorrência", "ameaça"]),
        ("gestão e liderança", ["ceo", "cfo", "coo", "executive", "leadership", "gestão", "liderança"]),
        ("regulação", ["regulation", "regulamentação", "sec", "fed", "banco central"]),
    ]
    for topic_pt, markers in topic_keywords:
        if any(m in text_lower for m in markers):
            topics.append(topic_pt)
        if len(topics) >= 3:
            break
    if not topics:
        topics.append("notícia financeira")
    return topics


def _build_prompt(title: str, summary: Optional[str]) -> str:
    text = f"Título: {title}\nResumo: {summary or ''}"
    return (
        "Analisa a seguinte notícia financeira e devolve APENAS um objeto JSON com estas chaves:\n"
        "- sentiment: 'positivo', 'neutro' ou 'negativo'\n"
        "- language: código do idioma detectado (ex: 'en', 'pt', 'es')\n"
        "- translated_title: título traduzido para português de Portugal\n"
        "- translated_summary: resumo traduzido para português de Portugal (string vazia se não houver resumo original)\n"
        "- summary_pt: um resumo curto em português de 1 frase com o insight principal\n"
        "- entities: lista de objetos {name, type} onde type pode ser empresa, ticker, pessoa, produto, evento ou setor\n"
        "- topics: lista de 1 a 3 tópicos/temas em português\n\n"
        f"{text}\n\nJSON:"
    )


def _run_model(prompt: str, backend: str = "gpt2", max_new_tokens: int = 180) -> str:
    if backend == "heuristic":
        return ""
    model = get_inference_model(backend)
    return model.generate(prompt, max_new_tokens=max_new_tokens, temperature=0.3)


def analyze_news_item(
    title: str,
    summary: Optional[str] = None,
    backend: str = "gpt2",
    ticker: Optional[str] = None,
    translate_summary: bool = True,
) -> NewsAnalysisResult:
    """Analisa uma notícia individual combinando modelo local e heurísticas."""
    start = time.time()
    prompt = _build_prompt(title, summary)
    try:
        raw = _run_model(prompt, backend=backend, max_new_tokens=180)
    except Exception:
        raw = ""
    elapsed = int((time.time() - start) * 1000)

    detected_language = _detect_language(f"{title} {summary or ''}")
    if detected_language == "pt":
        translated_title_default = title
        translated_summary_default = summary or ""
    else:
        translated_title_default = _translate_simple(title)
        translated_summary_default = _translate_simple(summary) if translate_summary else (summary or "")

    default = {
        "sentiment": _heuristic_sentiment(title, summary),
        "language": detected_language,
        "translated_title": translated_title_default,
        "translated_summary": translated_summary_default,
        "summary_pt": _summarize_pt(title, summary if translate_summary else None, _heuristic_sentiment(title, summary)),
        "entities": _extract_entities(title, summary, ticker),
        "topics": _extract_topics(title, summary),
    }

    data = _parse_json(raw, default)

    # Se o JSON parseado for igualzinho ao default (modelo falhou), mantemos defaults.
    # Senão, preenchemos campos em falta com heurísticas.
    sentiment = (data.get("sentiment") or default["sentiment"]).lower()
    if sentiment not in ("positivo", "neutro", "negativo"):
        sentiment = default["sentiment"]

    language = str(data.get("language") or default["language"]).lower()
    if not language or language == "desconhecido":
        language = default["language"]

    translated_title = str(data.get("translated_title") or "").strip() or default["translated_title"]
    translated_summary = str(data.get("translated_summary") or "").strip()
    if not translated_summary and summary:
        translated_summary = default["translated_summary"]

    summary_pt = str(data.get("summary_pt") or "").strip() or default["summary_pt"]

    entities = []
    for e in data.get("entities") or []:
        if isinstance(e, dict) and e.get("name"):
            entities.append({
                "name": str(e["name"]).strip(),
                "type": str(e.get("type", "entidade")).strip(),
            })
    if not entities:
        entities = default["entities"]

    topics = [str(t).strip() for t in (data.get("topics") or []) if str(t).strip()]
    if not topics:
        topics = default["topics"]

    return NewsAnalysisResult(
        sentiment=sentiment,
        language=language,
        translated_title=translated_title or title,
        translated_summary=translated_summary,
        summary_pt=summary_pt,
        entities=entities,
        topics=topics,
        raw_output=raw,
        elapsed_ms=elapsed,
    )


def analyze_news_batch(
    items: List[Dict[str, str]],
    backend: str = "gpt2",
    ticker: Optional[str] = None,
) -> List[NewsAnalysisResult]:
    """Analisa um lote de notícias, traduzindo apenas os títulos em batch.

    O resumo original em inglês é mantido (não traduzido) para evitar alta
    latência de CPU. O sumário PT é gerado a partir do título traduzido.
    """
    titles = [item.get("title") or "" for item in items]
    translated_titles = _translate_batch(titles)

    results = []
    for item, tt in zip(items, translated_titles):
        title = item.get("title") or ""
        summary = item.get("summary") or item.get("text") or ""
        result = analyze_news_item(
            title=title,
            summary=summary,
            backend=backend,
            ticker=ticker or item.get("ticker"),
            translate_summary=False,
        )
        # Sobrepõe a tradução batch do título para garantir PT fluente.
        if tt and result.language != "pt":
            result.translated_title = tt
            result.translated_summary = summary or ""
            result.summary_pt = _summarize_pt(tt, None, result.sentiment)
        results.append(result)
    return results


def build_news_entity_graph(
    ticker: str,
    news_items: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Constrói grafo notícias-entidades a partir de notícias já analisadas."""
    nodes: Dict[str, Dict[str, Any]] = {}
    edges: List[Dict[str, Any]] = []

    for i, item in enumerate(news_items):
        news_id = f"n{i}"
        title = item.get("translated_title") or item.get("title") or "Notícia"
        nodes[news_id] = {
            "id": news_id,
            "type": "noticia",
            "label": title[:80],
            "ticker": item.get("ticker", ticker),
            "sentiment": item.get("sentiment", "neutro"),
            "published": item.get("published"),
            "url": item.get("url"),
        }
        for entity in item.get("entities") or []:
            name = entity.get("name")
            etype = entity.get("type", "entidade")
            if not name:
                continue
            eid = f"e:{etype}:{name.lower().replace(' ', '_')}"
            if eid not in nodes:
                nodes[eid] = {"id": eid, "type": "entidade", "label": name, "entity_type": etype}
            edges.append({"source": news_id, "target": eid, "weight": 1.0})

    # ligar notícias entre si quando partilham entidades
    news_nodes = [nid for nid, n in nodes.items() if n["type"] == "noticia"]
    entity_news: Dict[str, List[str]] = {}
    for e in edges:
        entity_news.setdefault(e["target"], []).append(e["source"])
    for eid, nids in entity_news.items():
        for i in range(len(nids)):
            for j in range(i + 1, len(nids)):
                edges.append({"source": nids[i], "target": nids[j], "weight": 0.5})

    return {
        "ticker": ticker.upper(),
        "nodes": list(nodes.values()),
        "edges": edges,
    }
