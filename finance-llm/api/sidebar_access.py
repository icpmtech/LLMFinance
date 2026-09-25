"""Acesso aos módulos da solução na barra lateral, por perfil de acesso.

A barra lateral da plataforma mostra as aplicações e as secções do CRM. Nem todos
os perfis precisam de as ver todas: esta definição, gerida na **página de
administração**, permite esconder módulos por perfil.

Perfis considerados (aditivos):

* os papéis da plataforma (`admin`, `member`) — o campo `role` da conta;
* os perfis de CRM (`comercial`, `marketing`, `convidado`…), que são atribuídos a
  cada utilizador no módulo «Utilizadores» do CRM (`finance_crm_rbac`).

Um módulo desaparece da barra lateral quando está escondido **no papel da
plataforma ou no perfil de CRM** do utilizador (união das duas regras). Alguns
módulos são intocáveis (`PROTECTED`): o chat, o Finder, as definições e a própria
administração — escondê-los trancaria o utilizador fora da plataforma.

A definição vive num documento único do índice `finance_settings`
(`id = sidebar_access`), pelo que sobrevive a reinícios e é auditada.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from api import crm_registry as registry
from api.elasticsearch_client import SETTINGS_INDEX, ensure_indices, get_es_client

logger = logging.getLogger(__name__)

DOC_ID = "sidebar_access"
DOC_KIND = "sidebar_access"

# Papéis da plataforma (campo `role` da conta de autenticação).
PLATFORM_ROLES: Tuple[Tuple[str, str], ...] = (
    ("admin", "Administrador (plataforma)"),
    ("member", "Utilizador (plataforma)"),
)

# Módulos que nunca podem ser escondidos (trancariam o acesso à plataforma).
PROTECTED: Tuple[str, ...] = ("chat", "finder", "settings", "admin")

PROFILE_KINDS: Tuple[Tuple[str, str], ...] = (("plataforma", "Papel da plataforma"), ("crm", "Perfil de CRM"))

_INDICES_READY: Dict[str, Any] = {"at": None}
INDICES_TTL = 300


# ------------------------------------------------------------------ infraestrutura
def _client() -> Optional[Any]:
    """Cliente do Elasticsearch, garantindo o índice de definições (1×/5 min)."""
    client = get_es_client()
    if not client:
        return None
    stamp = _INDICES_READY.get("at")
    if stamp is None or (datetime.now(timezone.utc) - stamp).total_seconds() > INDICES_TTL:
        try:
            ensure_indices(client)
            _INDICES_READY["at"] = datetime.now(timezone.utc)
        except Exception as exc:  # pragma: no cover - depende do Elasticsearch
            logger.warning("Sidebar access: não foi possível garantir os índices: %s", exc)
    return client


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


# --------------------------------------------------------------------- perfis
def profiles() -> List[Dict[str, Any]]:
    """Perfis que podem ter regras: papéis da plataforma + perfis de CRM."""
    items: List[Dict[str, Any]] = [
        {"key": key, "label": label, "kind": "plataforma", "area": "", "department": "", "scope": ""}
        for key, label in PLATFORM_ROLES
    ]
    items.extend(
        {
            "key": role.key,
            "label": role.label,
            "kind": "crm",
            "area": role.area,
            "department": role.department,
            "scope": role.scope,
        }
        for role in registry.ROLES
    )
    return items


def known_profiles() -> Tuple[str, ...]:
    return tuple(item["key"] for item in profiles())


# ------------------------------------------------------------------ ler/gravar
def _clean(rules: Dict[str, Any]) -> Dict[str, List[str]]:
    """Normaliza as regras: perfis conhecidos, módulos intocáveis fora, listas limpas."""
    allowed = set(known_profiles())
    clean: Dict[str, List[str]] = {}
    for profile, modules in (rules or {}).items():
        key = str(profile or "").strip()
        if not key or key not in allowed:
            continue
        values: Iterable[Any] = modules if isinstance(modules, (list, tuple, set)) else []
        seen: List[str] = []
        for value in values:
            module = str(value or "").strip()
            if not module or module in PROTECTED or module in seen:
                continue
            seen.append(module)
        seen.sort()
        if seen:
            clean[key] = seen
    return dict(sorted(clean.items()))


def load() -> Dict[str, Any]:
    """Regras gravadas (vazio quando nunca foram definidas)."""
    empty: Dict[str, Any] = {"rules": {}, "updated_at": None, "updated_by": "", "backend": "memória"}
    client = _client()
    if not client:
        return empty
    try:
        if not client.exists(index=SETTINGS_INDEX, id=DOC_ID):
            return {**empty, "backend": "elasticsearch"}
        source = client.get(index=SETTINGS_INDEX, id=DOC_ID)["_source"]
    except Exception as exc:  # pragma: no cover - depende do Elasticsearch
        logger.warning("Sidebar access: falha a ler as regras: %s", exc)
        return empty
    return {
        "rules": _clean(source.get("rules") or {}),
        "updated_at": source.get("updated_at"),
        "updated_by": source.get("updated_by") or "",
        "backend": "elasticsearch",
    }


def save(rules: Dict[str, Any], *, actor_email: str = "") -> Dict[str, Any]:
    """Grava as regras (substitui as anteriores) e devolve o estado resultante."""
    clean = _clean(rules)
    client = _client()
    if not client:
        return {"error": "Elasticsearch indisponível", "rules": clean, "updated_at": None, "updated_by": ""}
    document = {
        "id": DOC_ID,
        "kind": DOC_KIND,
        "rules": clean,
        "updated_at": _now(),
        "updated_by": actor_email,
    }
    try:
        client.index(index=SETTINGS_INDEX, id=DOC_ID, document=document, refresh=True)
    except Exception as exc:  # pragma: no cover - depende do Elasticsearch
        logger.warning("Sidebar access: falha a gravar as regras: %s", exc)
        return {"error": str(exc), "rules": clean, "updated_at": None, "updated_by": actor_email}
    return {
        "rules": clean,
        "updated_at": document["updated_at"],
        "updated_by": actor_email,
        "backend": "elasticsearch",
    }


def reset(*, actor_email: str = "") -> Dict[str, Any]:
    """Volta a mostrar todos os módulos a todos os perfis."""
    return save({}, actor_email=actor_email)


# ------------------------------------------------------------------- efetivo
def _crm_profile(user: Any) -> Tuple[str, str]:
    """Chave e etiqueta do perfil de CRM do utilizador (por omissão, o predefinido)."""
    try:  # importação tardia para evitar ciclos (crm_suite importa registry)
        from api import crm_suite as suite

        assignment = suite.get_assignment(user)
    except Exception as exc:  # pragma: no cover - depende do Elasticsearch
        logger.debug("Sidebar access: perfil de CRM indisponível: %s", exc)
        assignment = {}
    key = str(assignment.get("role") or registry.DEFAULT_ROLE_KEY)
    role = registry.ROLE_BY_KEY.get(key)
    return key, (role.label if role else key)


def effective(
    user: Any,
    *,
    rules: Optional[Dict[str, List[str]]] = None,
    assignment_label: Optional[str] = None,
) -> Dict[str, Any]:
    """Módulos escondidos para um utilizador (união do papel e do perfil de CRM)."""
    stored = rules if rules is not None else load()["rules"]
    platform_role = str(getattr(user, "role", "") or "member")
    profile, profile_label = _crm_profile(user)
    if assignment_label:
        profile_label = assignment_label

    hidden: List[str] = []
    for key in (platform_role, profile):
        for module in stored.get(key) or []:
            if module not in hidden:
                hidden.append(module)
    hidden = [module for module in hidden if module not in PROTECTED]
    hidden.sort()

    return {
        "hidden": hidden,
        "platform_role": platform_role,
        "profile": profile,
        "profile_label": profile_label,
        "rules_aplicadas": sorted({key for key in (platform_role, profile) if stored.get(key)}),
        "protected": list(PROTECTED),
    }


def overview() -> Dict[str, Any]:
    """Estado completo para a página de administração."""
    stored = load()
    return {
        "profiles": profiles(),
        "profile_kinds": [{"id": key, "label": label} for key, label in PROFILE_KINDS],
        "protected": list(PROTECTED),
        "rules": stored["rules"],
        "updated_at": stored.get("updated_at"),
        "updated_by": stored.get("updated_by") or "",
        "escondidos": {key: len(value) for key, value in stored["rules"].items()},
        "backend": stored.get("backend"),
    }


def apply_hidden(modules: Sequence[str], hidden: Iterable[str]) -> List[str]:
    """Utilitário de teste: filtra ids de módulos pelos escondidos."""
    blocked = set(hidden)
    return [module for module in modules if module not in blocked]
