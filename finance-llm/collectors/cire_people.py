"""Extrai pessoas dos processos de insolvência do CIRE para o PessoasIQ.

Fonte: índice `finance_cire` (publicações de `consultascire.aspx`). Cada
publicação é um processo com uma lista de `intervenientes` (papel + nome + NIF);
cada interveniente passa a um **cargo** na ficha da pessoa em `finance_people`:

- `role`: papel no processo (`Credor`, `Insolvente`, `Administrador da
  insolvência`, `Requerente`, …);
- `role_org`: `CIRE` — identifica a origem, para as reingestões poderem
  substituir apenas os cargos do CIRE e preservar os do societário;
- `company_nif`/`company_name`: alvo do processo (insolvente/devedor) ou o
  próprio NIF, quando a pessoa **é** o insolvente;
- `acto`: espécie do processo (ex.: `Insolvência pessoa singular (Apresentação)`);
- `event`: número do processo;
- `tribunal`: comarca do tribunal;
- `publication_id`: `pub_id` da publicação;
- `date`/`publication_date`: data da publicação.

Por omissão entram apenas pessoas singulares (`is_company=False`): as pessoas
coletivas (credores institucionais, sociedades insolventes) são a maioria das
ocorrências no CIRE e iriam transformar o PessoasIQ num registo de empresas. Use
``include_companies=True`` para as incluir também.
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, Iterable, List, Optional

from collectors.people_extractor import _clean, _is_company_name, _normalize_name, aggregate_people

#: Etiqueta de origem dos cargos extraídos do CIRE (usada para os substituir em reingestões).
CIRE_ROLE_ORG = "CIRE"

#: Papéis do processo que identificam o alvo (insolvente/devedor).
_TARGET_PAPEIS = ("Insolvente", "Devedor", "Requerido", "Devedor/Insolvente")

#: Papel do CIRE -> rótulo apresentado no PessoasIQ.
PAPEL_LABELS = {
    "Administrador Insolvência": "Administrador da insolvência",
    "Administrador de Insolvência": "Administrador da insolvência",
    "Administrador da Insolvência": "Administrador da insolvência",
    "Insolvente": "Insolvente",
    "Devedor": "Devedor",
    "Requerido": "Requerido",
    "Requerente": "Requerente",
    "Credor": "Credor",
    "Gestor Judicial": "Gestor judicial",
    "Fiduciário": "Fiduciário",
    "Banco de Portugal": "Banco de Portugal",
    "Ministério Público": "Ministério Público",
    "Autoridade Tributária e Aduaneira": "Autoridade Tributária e Aduaneira",
}

#: Limites de segurança por ficha (um credor pessoa singular pode ter milhares de
#: processos; sem limite a ficha cresceria sem controlo).
MAX_ROLES = int(os.getenv("PEOPLE_CIRE_MAX_ROLES", "400"))
MAX_COMPANIES = int(os.getenv("PEOPLE_CIRE_MAX_COMPANIES", "400"))


def _normalize_nif(value: Any) -> Optional[str]:
    """NIF/NIPC com 9 dígitos, ou ``None`` (o CIRE tem intervenientes sem NIF)."""
    digits = re.sub(r"\D", "", str(value or ""))
    return digits if len(digits) == 9 else None


def role_label(papel: Any) -> str:
    """Rótulo normalizado do papel no processo (`Administrador Insolvência` -> ...)."""
    raw = _clean(str(papel or ""))
    if not raw:
        return "Interveniente"
    if raw in PAPEL_LABELS:
        return PAPEL_LABELS[raw]
    lowered = {key.lower(): value for key, value in PAPEL_LABELS.items()}
    return lowered.get(raw.lower(), raw if not raw.isupper() else raw.title())


def _processo(pub: Dict[str, Any]) -> str:
    return _clean(str(pub.get("processo_numero") or pub.get("processo") or ""))


def _target(intervenientes: List[Dict[str, Any]], insolvente: str) -> tuple:
    """Alvo do processo (insolvente/devedor): ``(nif, nome)``, com fallback no nome."""
    for item in intervenientes:
        papel = _clean(str(item.get("papel") or ""))
        if papel not in _TARGET_PAPEIS:
            continue
        nif = _normalize_nif(item.get("nif"))
        nome = _normalize_name(str(item.get("nome") or "")) or insolvente
        if nif:
            return nif, nome
    return None, insolvente


def extract_people_from_cire(
    pub: Dict[str, Any],
    *,
    papeis: Optional[Iterable[str]] = None,
    include_companies: bool = False,
) -> List[Dict[str, Any]]:
    """Converte uma publicação do CIRE nos registos de intervenientes (pessoas).

    Cada registo tem a mesma forma dos registos do societário
    (``collectors.people_extractor``), para poder ser agregado por
    :func:`aggregate_cire_people`.
    """
    intervenientes = [i for i in (pub.get("intervenientes") or []) if isinstance(i, dict)]
    if not intervenientes:
        return []

    pub_id = str(pub.get("pub_id") or "")
    data = pub.get("data_publicacao") or None
    processo = _processo(pub)
    especie = _clean(str(pub.get("especie") or pub.get("ato") or ""))
    tribunal = _clean(str(pub.get("tribunal_comarca") or pub.get("tribunal") or ""))
    insolvente = _normalize_name(str(pub.get("insolvente") or ""))
    target_nif, target_nome = _target(intervenientes, insolvente)

    wanted = None
    if papeis:
        wanted = {role_label(papel) for papel in papeis}

    records: List[Dict[str, Any]] = []
    seen: set = set()
    for item in intervenientes:
        cargo = role_label(item.get("papel"))
        if wanted is not None and cargo not in wanted:
            continue
        nif = _normalize_nif(item.get("nif"))
        nome = _normalize_name(str(item.get("nome") or ""))
        if not nif or not nome:
            continue
        is_company = _is_company_name(nome, nif)
        if is_company and not include_companies:
            continue
        key = (nif, cargo, pub_id)
        if key in seen:
            continue
        seen.add(key)

        is_target = bool(target_nif) and nif == target_nif
        records.append({
            "nif": nif,
            "name": nome,
            "is_company": is_company,
            "role_org": CIRE_ROLE_ORG,
            "cargo": cargo,
            "nacionalidade": None,
            "event": processo or None,
            "event_date": data,
            "publication_date": data,
            "acto": especie or None,
            "publication_id": pub_id or None,
            "company_nif": nif if is_target else target_nif,
            "company_name": (nome if is_target else target_nome) or None,
            "tribunal": tribunal or None,
            "quota": None,
            "causa": None,
            "residencia": None,
        })
    return records


def aggregate_cire_people(
    records: Iterable[Dict[str, Any]],
    *,
    max_roles: Optional[int] = None,
    max_companies: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Agrega registos do CIRE em documentos `finance_people` (um por NIF)."""
    return aggregate_people(
        records,
        source="cire",
        max_roles=MAX_ROLES if max_roles is None else max_roles,
        max_companies=MAX_COMPANIES if max_companies is None else max_companies,
    )


def extract_from_cire(
    publications: Iterable[Dict[str, Any]],
    *,
    papeis: Optional[Iterable[str]] = None,
    include_companies: bool = False,
    max_roles: Optional[int] = None,
    max_companies: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Pipeline completo: publicações do CIRE -> documentos `finance_people`."""
    records: List[Dict[str, Any]] = []
    for pub in publications:
        records.extend(extract_people_from_cire(pub, papeis=papeis, include_companies=include_companies))
    return aggregate_cire_people(records, max_roles=max_roles, max_companies=max_companies)


def preview(publications: Iterable[Dict[str, Any]], **kwargs: Any) -> tuple:
    """Devolve (publicações processadas, pessoas distintas) — útil em sondagens."""
    pubs = list(publications)
    people = extract_from_cire(pubs, **kwargs)
    return len(pubs), len(people)
