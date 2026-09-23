"""Extrai pessoas e cargos das publicações societárias indexadas.

Fonte: texto integral (`texto`) das publicações de `publicacoes.mj.pt` guardadas
em `finance_publicacoes_mj`. Devolve registos normalizados prontos a indexar no
índice `finance_people`.

Cada registo de pessoa contém:
- `nif`: NIF/NIPC da pessoa (ou entidade sócia);
- `name`: nome/firma tal como aparece na publicação;
- `is_company`: indicação se o NIF é de pessoa coletiva (heurística de 9 dígitos
  e nome com LDA/S.A./UNIPESSOAL/etc.).
- `roles`: lista de eventos com cargo/orgão, empresa, data da publicação, acto,
  evento (designação/cessação/sócio), quota, causa e residência.

A extração é regex sobre o texto achatado (sem quebras de linha). Cobre os
padrões observados nas publicações do MJ:

1. Membros de órgãos sociais designados (orgão + nome/firma + cargo).
2. Cessação de funções (orgão + nome/firma + cargo + causa + data de efeito).
3. Sócios e quotas (TITULAR + quota + NIF/NIPC).
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any, Dict, Iterable, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Constantes de parsing
# ---------------------------------------------------------------------------

# Marcadores típicos de entidade coletiva que aparecem como TOKEN no fim do
# nome («... LDA», «... S.A.»). Comparados como tokens isolados para evitar
# falsos positivos com apelidos (ex.: «VIEIRA DE SA»).
_COMPANY_SUFFIX_TOKENS = {
    "LDA", "LDA.", "SA", "S.A", "S.A.", "SGPS", "UNIPESSOAL", "E.I.R.L",
    "SOCIEDADE", "SUCURSAL", "HOLDING", "FUNDO", "FUNDOS", "CRL", "ACE",
    "EPE", "EIM", "ESTABELECIMENTO", "BANCO", "SEGUROS", "COOPERATIVA",
}

# Frases multi-palavra que só aparecem em nomes de entidades.
_COMPANY_PHRASE_MARKERS = (
    "SOCIEDADE POR QUOTAS", "SOCIEDADE ANONIMA", "SOCIEDADE ANÓNIMA",
    "SOCIEDADE UNIPESSOAL", "- SUCURSAL", "EM NOME INDIVIDUAL",
    "AGRUPAMENTO COMPLEMENTAR",
)

# Heurística: nomes próprios de pessoas individuais geralmente têm até 5 tokens,
# raramente contêm hífen no início e têm NIF que começa por 1/2/3.
_MAX_INDIVIDUAL_NAME_TOKENS = 8


# ---------------------------------------------------------------------------
# Normalização
# ---------------------------------------------------------------------------

def _clean(value: str) -> str:
    """Limpa espaços e entidades HTML de um valor extraído."""
    value = value.replace("&nbsp;", " ").replace("\xa0", " ")
    value = re.sub(r"\s+", " ", value)
    return value.strip(" :;,.-")


def _as_iso(value: Optional[str]) -> Optional[str]:
    """Converte uma data portuguesa (`6 de maio de 2025`) ou `AAAA-MM-DD`."""
    value = (value or "").strip()
    if not value:
        return None
    # Já ISO?
    if re.match(r"^\d{4}-\d{2}-\d{2}$", value):
        return value
    # 6 de maio de 2025
    meses = {
        "janeiro": 1, "fevereiro": 2, "março": 3, "abril": 4,
        "maio": 5, "junho": 6, "julho": 7, "agosto": 8,
        "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
    }
    m = re.search(r"(\d{1,2})\s+de\s+([a-zç]+)\s+de\s+(\d{4})", value, re.I)
    if m:
        mes = meses.get(m.group(2).lower())
        if mes:
            return f"{int(m.group(3)):04d}-{mes:02d}-{int(m.group(1)):02d}"
    return None


def _normalize_quota(value: str) -> Optional[str]:
    """Extrai valor numérico de uma quota (ex.: `66.666,67 Euros`)."""
    value = _clean(value)
    m = re.search(r"(\d{1,3}(?:[.\s]?\d{3})*,\d{2})", value)
    if m:
        raw = m.group(1).replace(" ", "").replace(".", "").replace(",", ".")
        return raw
    return None


def _is_company_name(name: str, nif: str) -> bool:
    """Heurística para distinguir pessoa individual de pessoa coletiva.

    O **NIF é o critério principal** em Portugal: pessoas singulares residentes
    têm NIF começado por 1/2/3 e pessoas coletivas por 5/6/7/9. O nome só decide
    quando o NIF é desconhecido ou atípico (ex.: 45/70 = não residentes).
    """
    nif = (nif or "").strip()
    if re.fullmatch(r"[123]\d{8}", nif):
        return False
    if re.fullmatch(r"[5679]\d{8}", nif):
        return True

    name_upper = (name or "").upper()
    if any(marker in name_upper for marker in _COMPANY_PHRASE_MARKERS):
        return True
    tokens = [t.strip(".,;:()") for t in re.split(r"[\s/]+", name_upper) if t.strip(".,;:()")]
    if tokens and tokens[-1] in _COMPANY_SUFFIX_TOKENS:
        return True

    # NIF fora dos intervalos habituais (45/70 = não residentes): decidir pelo
    # tamanho do nome — nomes de pessoas são curtos.
    if re.fullmatch(r"[48]\d{8}", nif):
        return len(tokens) > _MAX_INDIVIDUAL_NAME_TOKENS
    return False


def _normalize_name(name: str) -> str:
    """Nome canónico: título em maiúsculas, mas mantém acentos."""
    name = _clean(name)
    # Casos especiais como "CARLOS GOMES COMO BEM PRÓPRIO".
    name = re.sub(r"\s+COMO\s+BEM\s+PRÓPRIO\s*$", "", name, flags=re.I)
    return name


# ---------------------------------------------------------------------------
# Regexes
# ---------------------------------------------------------------------------

# Cabeçalho de um bloco de órgão designado: "ORGÃO(S) DESIGNADO(S): GERÊNCIA:" ou "GERÊNCIA:".
_ORG_HEADER_RE = re.compile(
    r"(?:ORGÃO\(S\)\s*DESIGNADO\(S\)\s*:\s*)?(GERÊNCIA|GERENCIA|DIRECÇÃO|DIRECAO|ADMINISTRAÇÃO|ADMINISTRACAO|FISCALIZAÇÃO|FISCALIZACAO|CONSELHO\s*DE\s*ADMINISTRAÇÃO|ASSEMBLEIA\s*GERAL)\s*:",
    re.I,
)

# Nome/Firma ... NIF/NIPC ... Cargo (designação).
_DESIGNADO_RE = re.compile(
    r"Nome/Firma:\s*(?P<name>[^\n]+?)\s*"
    r"NIF/NIPC:\s*(?P<nif>\d+)\s*"
    r"(?:Nacionalidade:\s*(?P<nacionalidade>[^\n]+?)\s*)?"
    r"Cargo:\s*(?P<cargo>[^\n]+?)(?=\s*Nome/Firma:|\s*Residência/Sede:|\s*Data da deliberação:|\s*Os documentos|\s*$)",
    re.I,
)

# Cessação: Nome/Firma ... NIF/NIPC ... (Cargo) ... (Residência) ... Causa ... Data.
# O portal omite frequentemente «Cargo:» e «Residência/Sede:» nas cessações.
_CESSACAO_RE = re.compile(
    r"Nome/Firma:\s*(?P<name>[^\n]+?)\s*"
    r"NIF/NIPC:\s*(?P<nif>\d+)\s*"
    r"(?:Cargo:\s*(?P<cargo>[^\n]+?)\s*)?"
    r"(?:Nacionalidade:\s*(?P<nacionalidade>[^\n]+?)\s*)?"
    r"(?:Resid[êe]ncia/Sede:\s*(?P<residencia>[^\n]+?)\s*)?"
    r"Causa:\s*(?P<causa>[^\n]+?)\s*"
    r"Data:\s*(?P<data_evento>[^\n]+?)(?=\s*Nome/Firma:|\s*Os documentos|\s*$)",
    re.I,
)

# Sócios e quotas.
_SOCIO_RE = re.compile(
    r"QUOTA\s*:\s*(?P<quota>[^\n]+?)\s*"
    r"TITULAR:\s*(?P<name>[^\n]+?)\s*"
    r"NIF/NIPC:\s*(?P<nif>\d+)",
    re.I,
)


def _flatten(text: str) -> str:
    """Achatamento tolerante para regex: preserva labels mas remove quebras."""
    text = text.replace("&nbsp;", " ").replace("\xa0", " ")
    text = text.replace("\r", " ").replace("\n", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# ---------------------------------------------------------------------------
# Extração por publicação
# ---------------------------------------------------------------------------

def extract_people_from_publicacao(pub: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extrai todos os registos de pessoas de uma publicação MJ normalizada.

    O input deve ter pelo menos `nif`, `entidade`/`firma`, `data_publicacao`,
    `acto`, `pub_id` e `texto`.
    """
    texto = _flatten(pub.get("texto") or "")
    if not texto:
        return []

    company_nif = str(pub.get("nif") or "").strip()
    company_name = _clean(pub.get("firma") or pub.get("entidade") or "")
    pub_date = pub.get("data_publicacao") or _as_iso(pub.get("data_publicacao_detalhe"))
    pub_id = pub.get("pub_id") or ""
    acto = pub.get("acto") or pub.get("acto_detalhe") or ""

    records: List[Dict[str, Any]] = []
    seen: set = set()

    # 1. Designações de órgãos sociais.
    for org_match in _ORG_HEADER_RE.finditer(texto):
        org_name = org_match.group(1).strip().title()
        start = org_match.end()
        # Fim do bloco: próximo marcador de interesse.
        end = len(texto)
        for m in (
            re.search(r"\s*(?:SÓCIOS E QUOTAS|SOCIOS E QUOTAS|FORMA DE OBRIGAR|ÓRGÃOS SOCIAIS|ORGÃOS SOCIAIS|Data da deliberação|Os documentos)", texto[start:], re.I),
            re.search(r"\s*(?=(?:ORGÃO\(S\)\s*DESIGNADO\(S\)\s*:\s*)?(?:GERÊNCIA|GERENCIA|DIRECÇÃO|ADMINISTRAÇÃO|FISCALIZAÇÃO|CONSELHO|ASSEMBLEIA)\s*:)", texto[start:], re.I),
        ):
            if m and m.start() < end:
                end = start + m.start()
        block = texto[start:start + end]

        for m in _DESIGNADO_RE.finditer(block):
            name = _normalize_name(m.group("name"))
            nif = m.group("nif").strip()
            if not name or not nif:
                continue
            is_company = _is_company_name(name, nif)
            key = (nif, "designacao", pub_id, org_name, m.group("cargo").strip())
            if key in seen:
                continue
            seen.add(key)
            records.append({
                "nif": nif,
                "name": name,
                "is_company": is_company,
                "role_org": org_name,
                "cargo": _clean(m.group("cargo")),
                "nacionalidade": _clean(m.group("nacionalidade") or ""),
                "event": "designacao",
                "event_date": pub_date,
                "publication_date": pub_date,
                "acto": acto,
                "publication_id": pub_id,
                "company_nif": company_nif,
                "company_name": company_name,
                "quota": None,
                "causa": None,
                "residencia": None,
            })

    # 2. Cessações (a publicação toda, pois o cabeçalho é "GERÊNCIA:" sem Cargo no bloco).
    for m in _CESSACAO_RE.finditer(texto):
        name = _normalize_name(m.group("name"))
        nif = m.group("nif").strip()
        if not name or not nif:
            continue
        is_company = _is_company_name(name, nif)
        key = (nif, "cessacao", pub_id)
        if key in seen:
            continue
        seen.add(key)
        cargo = _clean(m.group("cargo") or "") or "Membro de órgão social"
        records.append({
            "nif": nif,
            "name": name,
            "is_company": is_company,
            "role_org": "Gerência",
            "cargo": cargo,
            "nacionalidade": _clean(m.group("nacionalidade") or "") or None,
            "event": "cessacao",
            "event_date": _as_iso(m.group("data_evento")) or pub_date,
            "publication_date": pub_date,
            "acto": acto,
            "publication_id": pub_id,
            "company_nif": company_nif,
            "company_name": company_name,
            "quota": None,
            "causa": _clean(m.group("causa")),
            "residencia": _clean(m.group("residencia") or "") or None,
        })

    # 3. Sócios e quotas.
    for m in _SOCIO_RE.finditer(texto):
        name = _normalize_name(m.group("name"))
        nif = m.group("nif").strip()
        if not name or not nif:
            continue
        is_company = _is_company_name(name, nif)
        # Evitar duplicar como designação caso o titular seja também gerente na
        # mesma publicação — mantemos ambos os eventos porque são contextos
        # distintos, mas garantimos chave única.
        key = (nif, "socio", pub_id, m.group("quota"))
        if key in seen:
            continue
        seen.add(key)
        records.append({
            "nif": nif,
            "name": name,
            "is_company": is_company,
            "role_org": "Sócios e Quotas",
            "cargo": "Sócio",
            "nacionalidade": None,
            "event": "socio",
            "event_date": pub_date,
            "publication_date": pub_date,
            "acto": acto,
            "publication_id": pub_id,
            "company_nif": company_nif,
            "company_name": company_name,
            "quota": _normalize_quota(m.group("quota")),
            "causa": None,
            "residencia": None,
        })

    return records


# ---------------------------------------------------------------------------
# Agregação por pessoa
# ---------------------------------------------------------------------------

def aggregate_people(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Agrava registos de eventos em documentos por NIF pessoa.

    Cada documento tem uma lista `roles` com todos os eventos observados,
    campos resumo (`first_seen`, `last_seen`, `companies`, `roles_summary`) e
    metadados de origem. O `_id` final em ES será `finance_people:{nif}`.
    """
    by_nif: Dict[str, Dict[str, Any]] = {}
    today = date.today().isoformat()

    for r in records:
        nif = r["nif"]
        entry = by_nif.setdefault(nif, {
            "nif": nif,
            "name": r["name"],
            "name_keyword": r["name"],
            "is_company": r["is_company"],
            "roles": [],
            "companies": [],
            "sources": set(),
            "first_seen": None,
            "last_seen": None,
        })
        # Preferir nome mais longo se houver variantes (ex.: com/sem apelidos).
        if len(r["name"]) > len(entry["name"]):
            entry["name"] = r["name"]
            entry["name_keyword"] = r["name"]
        role = {
            "role": r["cargo"],
            "role_org": r["role_org"],
            "company_nif": r["company_nif"],
            "company_name": r["company_name"],
            "date": r["event_date"],
            "publication_date": r["publication_date"],
            "acto": r["acto"],
            "event": r["event"],
            "quota": r["quota"],
            "causa": r["causa"],
            "residencia": r["residencia"],
            "publication_id": r["publication_id"],
            "nacionalidade": r["nacionalidade"],
        }
        entry["roles"].append(role)
        entry["sources"].add("publicacoes_mj")
        if r["company_nif"]:
            entry["companies"].append({"nif": r["company_nif"], "name": r["company_name"]})

    people: List[Dict[str, Any]] = []
    for entry in by_nif.values():
        dates = [r["date"] for r in entry["roles"] if r["date"]]
        entry["first_seen"] = min(dates) if dates else None
        entry["last_seen"] = max(dates) if dates else None
        # Deduplicar empresas mantendo ordem de primeira ocorrência.
        seen_companies: List[Dict[str, str]] = []
        seen_nifs: set = set()
        for c in entry["companies"]:
            if c["nif"] and c["nif"] not in seen_nifs:
                seen_nifs.add(c["nif"])
                seen_companies.append(c)
        entry["companies"] = seen_companies
        entry["companies_count"] = len(seen_companies)
        entry["roles_count"] = len(entry["roles"])
        # Resumo dos cargos mais recentes (último evento por empresa).
        latest_by_company: Dict[str, Dict[str, Any]] = {}
        for role in sorted(entry["roles"], key=lambda x: x["date"] or "", reverse=True):
            cnif = role["company_nif"] or ""
            if cnif not in latest_by_company:
                latest_by_company[cnif] = role
        entry["latest_roles"] = list(latest_by_company.values())
        entry["source"] = "publicacoes_mj"
        entry["ingested_at"] = today
        entry.pop("sources")
        people.append(entry)

    return people


def extract_from_publicacoes(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Pipeline completo: lista de publicações -> documentos `finance_people`."""
    raw: List[Dict[str, Any]] = []
    for pub in items:
        raw.extend(extract_people_from_publicacao(pub))
    return aggregate_people(raw)


# ---------------------------------------------------------------------------
# Helpers de debugging
# ---------------------------------------------------------------------------

def preview(items: List[Dict[str, Any]]) -> Tuple[int, int]:
    """Devolve (publicações processadas, pessoas distintas encontradas)."""
    people = extract_from_publicacoes(items)
    return len(items), len(people)
