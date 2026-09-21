"""Skills do IQ OS — o **método** que os assistentes seguem antes de responder.

Uma *skill* é um procedimento curto, reutilizável e verificável: quando usar,
que passos seguir, que ferramentas da plataforma tocar e que verificações fazer
antes de escrever a resposta. O Hermes, o Chat IA e o RAG partilham a mesma
biblioteca — todos passam por `ensure_skill()` **antes** de responder.

As skills são criadas **automaticamente a partir da pergunta**: se já existir uma
skill suficientemente parecida é essa que é usada (e ganha um uso); se não
existir, é criada uma nova — escrita pelo modelo de IA configurado e, sem modelo
(ou se a resposta do modelo não servir), montada de forma determinística a partir
das capacidades reais da plataforma. As quase-duplicadas são fundidas na
existente, para a biblioteca não crescer com sinónimos.

A biblioteca vive num ficheiro JSON (`data/skills/skills.json`) com escrita
atómica, tal como o Office: é a fonte de verdade e pode ser versionada.

Rotas em `api/skills_routes.py` (`/skills`).
"""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import re
import threading
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence
from uuid import uuid4

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
SKILLS_DIR = ROOT / "data" / "skills"
SKILLS_PATH = SKILLS_DIR / "skills.json"
SKILLS_VERSION = 1

MATCH_THRESHOLD = 0.5
MIN_MATCH_OVERLAP = 2
MERGE_THRESHOLD = 0.75
MIN_QUESTION_CHARS = 15
MIN_QUESTION_KEYWORDS = 2
MAX_SKILLS = 400
MAX_EXAMPLES = 5
MAX_STEPS = 8
MAX_CHECKS = 6
SKILL_TIMEOUT = 20.0
SKILL_MAX_TOKENS = 700

_lock = threading.Lock()
_cache: Optional[Dict[str, Any]] = None

# Palavras que não distinguem um procedimento de outro.
STOPWORDS = {
    "a", "o", "as", "os", "um", "uma", "uns", "umas", "de", "da", "do", "das", "dos", "em", "no", "na",
    "nos", "nas", "por", "para", "com", "sem", "sobre", "que", "quais", "qual", "quem", "como", "onde",
    "quando", "quanto", "quantos", "quantas", "e", "ou", "é", "sao", "são", "ser", "estar", "tem", "têm",
    "ha", "há", "mais", "menos", "se", "ao", "aos", "à", "às", "pelo", "pela", "the", "of", "and", "for",
    "with", "in", "about", "is", "are", "what", "which", "who", "how", "dados", "diz", "fala", "explica",
    "faz", "quero", "preciso", "podes", "pode", "lista", "mostra", "indica", "da-me", "dame",
}

TOOL_LABELS = {
    "contratos": "agregações do índice de contratos públicos",
    "empresas": "diretório de empresas (ranking por valor e por número de contratos)",
    "ontologia": "ontologia (objetos canónicos e ligações)",
    "documentos": "documentos indexados (RAG)",
    "pesquisa360": "recolha federada da Pesquisa 360",
    "mercados": "mercados (cotações, notícias, indicadores do ticker)",
}

CONTRACT_HINTS = ("contrat", "adjudic", "concurso", "licita", "fornecedor", "cpv", "empresa", "setor")
MARKET_HINTS = ("ticker", "acção", "acao", "ação", "cotação", "cotacao", "mercado", "preço", "preco", "bolsa")


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize(text: Any) -> str:
    value = unicodedata.normalize("NFD", str(text or ""))
    return "".join(char for char in value if unicodedata.category(char) != "Mn").lower()


def tokens(text: Any, *, minimum: int = 4) -> List[str]:
    """Palavras com significado (sem acentos, sem palavras vazias)."""
    out: List[str] = []
    for word in re.split(r"[^0-9a-zA-Z%]+", _normalize(text)):
        if len(word) < minimum or word in STOPWORDS or word.isdigit():
            continue
        if word not in out:
            out.append(word)
    return out


def _steps(value: Any) -> List[str]:
    if isinstance(value, str):
        rows = [line.strip(" -•\t") for line in value.splitlines() if line.strip()]
    elif isinstance(value, Sequence):
        rows = [str(item).strip() for item in value if str(item or "").strip()]
    else:
        rows = []
    return [row[:400] for row in rows if row][:MAX_STEPS]


def _keywords(value: Any, question: str = "") -> List[str]:
    if isinstance(value, str):
        rows = tokens(value)
    elif isinstance(value, Sequence):
        rows = [token for item in value for token in tokens(item)]
    else:
        rows = []
    if not rows:
        rows = tokens(question, minimum=3)
    return list(dict.fromkeys(rows))[:14]


def tools_for(question: str, keywords: Sequence[str] = ()) -> List[str]:
    """Ferramentas da plataforma que fazem sentido para este pedido."""
    blob = _normalize(" ".join([question, *[str(word) for word in keywords]]))
    tools: List[str] = []
    if any(hint in blob for hint in CONTRACT_HINTS):
        tools.extend(["contratos", "empresas"])
    if any(hint in blob for hint in MARKET_HINTS):
        tools.append("mercados")
    if any(word in blob for word in ("ontologia", "objeto", "ligacao", "ligacoes", "firma", "marca")):
        tools.append("ontologia")
    if any(word in blob for word in ("documento", "pdf", "relatorio", "dossier", "rag")):
        tools.append("documentos")
    tools.extend(["ontologia", "documentos", "pesquisa360"])
    return list(dict.fromkeys(tools))[:6]


def _heuristic_steps(question: str, tools: Sequence[str]) -> List[str]:
    steps = ["Identificar o tema, as entidades e as datas do pedido (NIF, ticker, empresa, período)."]
    if "contratos" in tools:
        steps.append("Contratos públicos: agregações (total, valor, média, máximo, por ano, CPV) e ranking de empresas por valor e por número de contratos.")
    if "empresas" in tools:
        steps.append("Empresas: usar o diretório de empresas e ligar cada entidade à ficha (NIF → /companies/<NIF>).")
    if "mercados" in tools:
        steps.append("Mercados: cotações, notícias e indicadores do ticker; comparar com o período pedido.")
    if "ontologia" in tools:
        steps.append("Ontologia: resolver os objetos canónicos do tema e ver as ligações relevantes.")
    if "documentos" in tools:
        steps.append("Documentos: procurar os trechos dos PDFs indexados (com título e página).")
    steps.append("Recolha federada na Pesquisa 360 nas fontes relevantes (plataforma, enciclopédia, dados abertos, investigação, web).")
    steps.append("Escrever a resposta citando as evidências [n] e separar factos da plataforma de fontes externas.")
    return steps[:MAX_STEPS]


def _heuristic_checks() -> List[str]:
    return [
        "Não inventar números, datas, nomes nem ligações.",
        "Citar sempre a evidência no formato [n].",
        "Se a evidência não responder à pergunta, dizê-lo explicitamente e sugerir o próximo passo.",
        "Distinguir factos calculados na plataforma de fontes externas.",
    ]


def _title(question: str, *, limit: int = 70) -> str:
    text = re.sub(r"\s+", " ", str(question or "")).strip(" ?.!")
    if len(text) <= limit:
        return text[:1].upper() + text[1:] if text else "Skill"
    return text[: limit - 1].rstrip() + "…"


# --------------------------------------------------------------------------
# Biblioteca
# --------------------------------------------------------------------------
def _empty_store() -> Dict[str, Any]:
    return {"version": SKILLS_VERSION, "updated_at": _now(), "skills": []}


def _read_store() -> Dict[str, Any]:
    if not SKILLS_PATH.exists():
        return _empty_store()
    try:
        raw = json.loads(SKILLS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Ficheiro de skills ilegível (%s); a recomeçar.", exc)
        return _empty_store()
    if not isinstance(raw, dict):
        return _empty_store()
    store = _empty_store()
    store["skills"] = [item for item in (raw.get("skills") or []) if isinstance(item, dict)]
    return store


def _write_store(store: Dict[str, Any]) -> None:
    global _cache
    store["version"] = SKILLS_VERSION
    store["updated_at"] = _now()
    store["skills"] = store["skills"][-MAX_SKILLS:]
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SKILLS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(store, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(SKILLS_PATH)
    _cache = store


def _store() -> Dict[str, Any]:
    global _cache
    with _lock:
        if _cache is None:
            _cache = _read_store()
        return copy.deepcopy(_cache)


def _persist(skills: List[Dict[str, Any]]) -> None:
    global _cache
    with _lock:
        store = _cache if _cache is not None else _read_store()
        store["skills"] = skills
        _write_store(store)


def list_skills(*, include_disabled: bool = True) -> List[Dict[str, Any]]:
    """Biblioteca, das mais usadas/recentes para as mais antigas."""
    skills = _store()["skills"]
    if not include_disabled:
        skills = [skill for skill in skills if skill.get("enabled", True)]
    return sorted(skills, key=lambda skill: (skill.get("uses") or 0, skill.get("last_used_at") or ""), reverse=True)


def get_skill(skill_id: str) -> Optional[Dict[str, Any]]:
    return next((skill for skill in _store()["skills"] if skill.get("id") == skill_id), None)


def save_skill(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Cria ou atualiza uma skill (usado pela API e pela criação automática)."""
    skills = _store()["skills"]
    skill_id = str(payload.get("id") or "").strip()
    existing = next((skill for skill in skills if skill.get("id") == skill_id), None) if skill_id else None
    if existing is None:
        skill = {
            "id": skill_id or f"skill-{uuid4().hex[:10]}",
            "name": _title(payload.get("name") or payload.get("question") or "Skill"),
            "when": str(payload.get("when") or "").strip()[:400],
            "question": str(payload.get("question") or "").strip()[:400],
            "steps": _steps(payload.get("steps")),
            "checks": _steps(payload.get("checks")) or [],
            "keywords": _keywords(payload.get("keywords"), str(payload.get("question") or payload.get("name") or "")),
            "tools": [str(item) for item in (payload.get("tools") or []) if str(item).strip()][:6]
            or tools_for(str(payload.get("question") or payload.get("name") or "")),
            "source": str(payload.get("source") or "auto"),
            "quality": str(payload.get("quality") or "heuristica"),
            "enabled": bool(payload.get("enabled", True)),
            "uses": int(payload.get("uses") or 0),
            "created_at": _now(),
            "updated_at": _now(),
            "last_used_at": None,
            "examples": [],
        }
        skills.append(skill)
    else:
        skill = existing
        for key in ("name", "when", "question", "source", "quality"):
            if payload.get(key):
                skill[key] = str(payload[key])[:400 if key != "name" else 120]
        if payload.get("steps") is not None:
            skill["steps"] = _steps(payload["steps"])
        if payload.get("checks") is not None:
            skill["checks"] = _steps(payload["checks"])
        if payload.get("keywords") is not None:
            skill["keywords"] = _keywords(payload["keywords"], skill.get("question") or "")
        if payload.get("tools") is not None:
            skill["tools"] = [str(item) for item in payload["tools"]][:6]
        if payload.get("enabled") is not None:
            skill["enabled"] = bool(payload["enabled"])
        skill["updated_at"] = _now()
    _persist(skills)
    return skill


def delete_skill(skill_id: str) -> bool:
    skills = _store()["skills"]
    remaining = [skill for skill in skills if skill.get("id") != skill_id]
    if len(remaining) == len(skills):
        return False
    _persist(remaining)
    return True


def set_enabled(skill_id: str, enabled: bool) -> Optional[Dict[str, Any]]:
    skill = save_skill({"id": skill_id, "enabled": enabled})
    return skill if skill.get("id") == skill_id else None


def clear_skills() -> int:
    removed = len(_store()["skills"])
    _persist([])
    return removed


# --------------------------------------------------------------------------
# Escolha e criação
# --------------------------------------------------------------------------
def score(skill: Dict[str, Any], question: str) -> float:
    """Semelhança entre a skill e a pergunta (0 a 1), sem modelo."""
    words = set(tokens(question, minimum=3))
    if not words:
        return 0.0
    keys = set(str(word) for word in (skill.get("keywords") or [])) | set(tokens(skill.get("name") or "", minimum=3))
    if not keys:
        return 0.0
    overlap = keys & words
    coverage = len(overlap) / max(1, len(keys))
    precision = len(overlap) / max(1, len(words) if len(words) < 12 else 12)
    return round(0.7 * coverage + 0.3 * precision, 4)


def match(question: str, *, minimum: float = MATCH_THRESHOLD) -> Optional[Dict[str, Any]]:
    """Melhor skill da biblioteca para a pergunta (ou `None`)."""
    words = set(tokens(question, minimum=3))
    best: Optional[Dict[str, Any]] = None
    best_score = 0.0
    for skill in list_skills(include_disabled=False):
        keys = set(str(word) for word in (skill.get("keywords") or [])) | set(tokens(skill.get("name") or "", minimum=3))
        if len(keys & words) < MIN_MATCH_OVERLAP:
            # Uma só palavra em comum é coincidência, não é o mesmo método.
            continue
        current = score(skill, question)
        if current > best_score:
            best, best_score = skill, current
    if best and best_score >= minimum:
        return {**best, "_score": best_score}
    return None


def _similar(skill: Dict[str, Any], keywords: Sequence[str]) -> Optional[Dict[str, Any]]:
    """Skill existente que representa o mesmo procedimento (para fundir)."""
    candidate = set(keywords)
    if not candidate:
        return None
    for existing in _store()["skills"]:
        keys = set(str(word) for word in (existing.get("keywords") or []))
        if not keys:
            continue
        overlap = len(keys & candidate) / max(1, min(len(keys), len(candidate)))
        if overlap >= MERGE_THRESHOLD:
            return existing
    return None


def record_use(skill_id: str, *, question: str = "", tools: Sequence[str] = (), mode: str = "") -> Optional[Dict[str, Any]]:
    """Marca a skill como usada e guarda a pergunta como exemplo."""
    skills = _store()["skills"]
    skill = next((item for item in skills if item.get("id") == skill_id), None)
    if skill is None:
        return None
    skill["uses"] = int(skill.get("uses") or 0) + 1
    skill["last_used_at"] = _now()
    skill["updated_at"] = _now()
    if tools:
        merged = list(dict.fromkeys([*(skill.get("tools") or []), *[str(item) for item in tools]]))[:6]
        skill["tools"] = merged
    if mode:
        skill["last_mode"] = mode
    if question:
        examples = [str(item) for item in (skill.get("examples") or []) if str(item) != question]
        skill["examples"] = [question[:240], *examples][:MAX_EXAMPLES]
    _persist(skills)
    return skill


SKILL_SYSTEM = (
    "És o arquiteto de skills do IQ OS. Escreves *skills* — procedimentos curtos, reutilizáveis e "
    "verificáveis que outro assistente aplica para responder a pedidos semelhantes. Escreves em "
    "português de Portugal e pensas nas capacidades reais da plataforma: agregações dos contratos "
    "públicos (total, valor, por ano, CPV, ranking de empresas por valor e por número de contratos), "
    "diretório de empresas (NIF → ficha), ontologia (objetos canónicos e ligações), documentos "
    "indexados (RAG, com título e página), mercados (cotações e notícias de um ticker) e a recolha "
    "federada da Pesquisa 360. Devolves **apenas** JSON válido."
)

SKILL_PROMPT = """\
Pedido do utilizador: {question}

Escreve a skill em JSON, com exatamente estes campos:
{{
  "name": "nome curto (até 70 caracteres), em português",
  "when": "quando aplicar esta skill (1 a 2 frases)",
  "steps": ["3 a 6 passos concretos, pela ordem da execução"],
  "checks": ["2 a 4 verificações antes de responder"],
  "keywords": ["5 a 12 palavras distintivas do pedido, sem acentos"],
  "tools": ["contratos", "empresas", "ontologia", "documentos", "mercados", "pesquisa360"]
}}

Os passos têm de ser executáveis com os dados da plataforma (números exatos, entidades por NIF,
trechos de documentos) e a resposta tem de citar as evidências. Não escrevas nada fora do JSON."""


async def _draft_with_model(
    question: str,
    *,
    session: Any = None,
    backend: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Pede ao modelo de IA a skill (ou `None` se não estiver disponível)."""
    from api import ontology_ai as ai  # noqa: PLC0415

    chosen = ai.available_backend(session, backend)
    if chosen.get("kind") != "cloud":
        return None
    from api.cloud_chat import complete_answer  # noqa: PLC0415

    try:
        text = await complete_answer(
            provider=chosen["provider"],
            spec=chosen.get("spec") or {},
            model=chosen.get("model") or "",
            messages=[
                {"role": "system", "content": SKILL_SYSTEM},
                {"role": "user", "content": SKILL_PROMPT.format(question=question)},
            ],
            api_key=chosen.get("api_key"),
            temperature=0.2,
            max_tokens=SKILL_MAX_TOKENS,
        )
    except Exception as exc:
        logger.info("Skills: o modelo não escreveu a skill (%s).", exc)
        return None
    proposal = ai.extract_json(text or "")
    if not isinstance(proposal, dict):
        return None
    steps = _steps(proposal.get("steps"))
    if not steps:
        return None
    return {
        "name": proposal.get("name") or _title(question),
        "when": proposal.get("when") or "",
        "steps": steps,
        "checks": _steps(proposal.get("checks")) or _heuristic_checks(),
        "keywords": _keywords(proposal.get("keywords"), question),
        "tools": [str(item) for item in (proposal.get("tools") or []) if str(item).strip()] or tools_for(question),
        "quality": "modelo",
    }


def _draft_heuristic(question: str) -> Dict[str, Any]:
    keywords = _keywords([], question)
    tools = tools_for(question, keywords)
    return {
        "name": _title(question),
        "when": f"Pedidos semelhantes a «{_title(question, limit=90)}».",
        "steps": _heuristic_steps(question, tools),
        "checks": _heuristic_checks(),
        "keywords": keywords,
        "tools": tools,
        "quality": "heuristica",
    }


async def ensure_skill(
    question: str,
    *,
    session: Any = None,
    backend: Optional[str] = None,
    model_draft: bool = True,
) -> Dict[str, Any]:
    """Devolve a skill a aplicar **antes** de responder (escolhe ou cria).

    Resultado: `{skill, created, merged, score}`. Nunca falha: se o modelo não
    estiver disponível, a skill é montada a partir das capacidades da plataforma.
    """
    clean = re.sub(r"\s+", " ", str(question or "")).strip()
    if not clean:
        raise ValueError("Escreva a pergunta para a qual quer uma skill.")

    found = match(clean)
    if found:
        found.pop("_score", None)
        return {"skill": found, "created": False, "merged": False, "score": score(found, clean), "mode": "biblioteca"}

    # Perguntas curtas ou sem palavras distintivas não dão um método reutilizável
    # (evita encher a biblioteca com pedidos de teste ou de uma só palavra).
    if len(clean) < MIN_QUESTION_CHARS or len(_keywords([], clean)) < MIN_QUESTION_KEYWORDS:
        return {"skill": None, "created": False, "merged": False, "score": 0.0, "mode": "ignorada"}

    proposal: Optional[Dict[str, Any]] = None
    if model_draft:
        try:
            proposal = await asyncio.wait_for(
                _draft_with_model(clean, session=session, backend=backend), timeout=SKILL_TIMEOUT
            )
        except Exception as exc:  # timeout/erro: segue a versão determinística
            logger.info("Skills: criação pelo modelo falhou (%s).", exc)
    if proposal is None:
        proposal = _draft_heuristic(clean)

    keywords = _keywords(proposal.get("keywords"), clean)
    twin = _similar(proposal, keywords)
    if twin is not None:
        merged = save_skill({"id": twin["id"], "keywords": keywords})
        logger.info("Skills: «%s» fundida em «%s».", proposal.get("name"), merged.get("name"))
        return {"skill": merged, "created": False, "merged": True, "score": score(merged, clean), "mode": "fundida"}

    skill = save_skill(
        {
            **proposal,
            "question": clean,
            "keywords": keywords,
            "source": "auto",
            "enabled": True,
        }
    )
    return {"skill": skill, "created": True, "merged": False, "score": 1.0, "mode": "criada"}


# --------------------------------------------------------------------------
# Aplicação
# --------------------------------------------------------------------------
def prompt_block(skill: Optional[Dict[str, Any]], *, label: str = "Skill aplicada") -> str:
    """Texto para injetar no prompt do assistente (método a seguir)."""
    if not skill:
        return ""
    lines = [f"{label}: {skill.get('name')}"]
    if skill.get("when"):
        lines.append(f"Quando usar: {skill['when']}")
    steps = skill.get("steps") or []
    if steps:
        lines.append("Método:")
        lines.extend(f"{index}. {step}" for index, step in enumerate(steps, start=1))
    checks = skill.get("checks") or []
    if checks:
        lines.append("Verificações obrigatórias:")
        lines.extend(f"- {check}" for check in checks)
    tools = [TOOL_LABELS.get(str(item), str(item)) for item in (skill.get("tools") or [])]
    if tools:
        lines.append("Ferramentas da plataforma: " + "; ".join(tools) + ".")
    lines.append("Segue este método e não o contradigas sem motivos das evidências.")
    return "\n".join(lines)


def public(skill: Optional[Dict[str, Any]], *, created: bool = False, merged: bool = False, skill_mode: str = "") -> Optional[Dict[str, Any]]:
    """Forma da skill devolvida ao cliente (nas respostas dos assistentes)."""
    if not skill:
        return None
    return {
        "id": skill.get("id"),
        "name": skill.get("name"),
        "when": skill.get("when"),
        "steps": skill.get("steps") or [],
        "checks": skill.get("checks") or [],
        "tools": skill.get("tools") or [],
        "uses": skill.get("uses") or 0,
        "quality": skill.get("quality"),
        "enabled": bool(skill.get("enabled", True)),
        "created": bool(created),
        "merged": bool(merged),
        "mode": skill_mode or None,
    }


async def for_request(
    question: str,
    *,
    session: Any = None,
    backend: Optional[str] = None,
    model_draft: bool = True,
    record: bool = False,
) -> Dict[str, Any]:
    """Skill a aplicar a um pedido: `{id, raw, public, block, mode}`.

    É o ponto de entrada dos assistentes (Hermes, Chat IA, RAG). Nunca falha:
    se a biblioteca ou o modelo não estiverem disponíveis, devolve vazio e o
    assistente responde como antes.
    """
    empty = {"id": None, "raw": None, "public": None, "block": "", "mode": None}
    if not str(question or "").strip():
        return empty
    try:
        result = await ensure_skill(question, session=session, backend=backend, model_draft=model_draft)
    except Exception as exc:
        logger.info("Skills: sem skill para este pedido (%s).", exc)
        return empty
    skill = result["skill"]
    if not skill:
        return {**empty, "mode": result.get("mode")}
    if record:
        record_use(skill["id"], question=str(question)[:240], mode="criada" if result["created"] else "biblioteca")
    return {
        "id": skill.get("id"),
        "raw": skill,
        "public": public(skill, created=result["created"], merged=result["merged"], skill_mode=result["mode"]),
        "block": prompt_block(skill),
        "mode": result["mode"],
        "created": result["created"],
        "merged": result["merged"],
    }


def finish(
    skill_id: Optional[str],
    *,
    question: str = "",
    tools: Sequence[str] = (),
    mode: str = "",
) -> None:
    """Regista o uso da skill depois da resposta (tolerante a falhas)."""
    if not skill_id:
        return
    try:
        record_use(skill_id, question=question[:240], tools=tools, mode=mode)
    except Exception as exc:  # pragma: no cover - nunca pode derrubar a resposta
        logger.info("Skills: não foi possível registar o uso (%s).", exc)


def status() -> Dict[str, Any]:
    skills = _store()["skills"]
    return {
        "total": len(skills),
        "enabled": len([skill for skill in skills if skill.get("enabled", True)]),
        "uses": sum(int(skill.get("uses") or 0) for skill in skills),
        "by_quality": {
            quality: len([skill for skill in skills if (skill.get("quality") or "heuristica") == quality])
            for quality in sorted({str(skill.get("quality") or "heuristica") for skill in skills})
        },
        "path": str(SKILLS_PATH),
        "updated_at": _store().get("updated_at"),
    }
