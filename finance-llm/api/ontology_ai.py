"""IA ao serviço da ontologia: desenhar tipos, sugerir relações e redigir fichas.

Três utilizações, todas com **alternativa determinística** — a ontologia nunca
depende de um modelo para funcionar:

- `design_ontology` — a partir de uma descrição em português e/ou de fontes de
  dados já ligadas, propõe **tipos de objeto, propriedades e ligações**. Com um
  fornecedor de IA configurado (Definições → Fornecedores de IA) o modelo lê o
  diagnóstico real das fontes (campos, tipos, exemplos) e devolve a proposta em
  JSON; sem modelo, a proposta é inferida dos campos reais (`ontology_sources`).
- `suggest_links` — propõe ligações que faltam entre tipos existentes (campos
  partilhados como `nif`/`ticker`, referências `values_from`, fontes comuns).
- `draft_dossier` — redige uma ficha de análise a partir de **factos reais**
  (objeto + relações + indicadores), com ou sem modelo.

Regra de ouro: o modelo propõe, o registo valida. Tudo o que sai daqui é
verificado campo a campo antes de ser aceite (ids em `slug`, tipos permitidos,
`binding` coerente com as fontes registadas) e nada é gravado sem `apply`.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from api import ontology_registry as registry
from api import ontology_sources as sources_service

logger = logging.getLogger(__name__)

ALLOWED_PROPERTY_TYPES = {"string", "text", "keyword", "number", "date", "boolean", "enum", "reference"}
ALLOWED_BINDING_KINDS = {"es", "aggregation", "derived"}
DESIGN_MAX_TOKENS = 4000
LINKS_MAX_TOKENS = 1500
DOSSIER_MAX_TOKENS = 2200

SYSTEM_DESIGN = (
    "És um engenheiro de ontologias (camada semântica ao estilo Palantir Foundry) na plataforma "
    "financeira IQ OS. Desenhas tipos de objeto, propriedades e ligações a partir de dados reais. "
    "Escreves sempre em português de Portugal e respondes APENAS com JSON válido, sem comentários "
    "nem texto fora do JSON."
)

SYSTEM_LINKS = (
    "És um engenheiro de ontologias na plataforma IQ OS. Propões ligações (relações) entre tipos de "
    "objeto já existentes, com base em chaves partilhadas e no significado dos dados. Escreves em "
    "português de Portugal e respondes APENAS com JSON válido."
)

SYSTEM_DOSSIER = (
    "És um analista da plataforma IQ OS. Rediges fichas de análise em português de Portugal, apenas "
    "com os factos fornecidos. Não inventas números, nomes nem datas: se um dado não estiver nos "
    "factos, escreves que não está disponível."
)


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------
def _slug(value: Any, fallback: str = "item") -> str:
    return registry.slugify(str(value or ""), fallback=fallback)


def extract_json(text: str) -> Optional[Dict[str, Any]]:
    """Extrai o primeiro objeto JSON de uma resposta de modelo (tolera cercas ```)."""
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
        cleaned = re.sub(r"```\s*$", "", cleaned).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        return None
    candidate = cleaned[start : end + 1]
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        # Última tentativa: remover vírgulas finais antes de fechar.
        candidate = re.sub(r",\s*([}\]])", r"\1", candidate)
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


def available_backend(session: Any, backend: Optional[str] = None) -> Dict[str, Any]:
    """Resolve o modelo a usar: `{kind, provider, model, api_key, label}`."""
    from api import providers_service

    user_id = getattr(getattr(session, "user", None), "id", None)
    chosen = (backend or "").strip()
    if not chosen:
        config = providers_service.load_user_config(user_id) if user_id else {"defaults": {}}
        defaults = config.get("defaults") or {}
        provider = defaults.get("provider")
        if provider:
            model = defaults.get("model") or ""
            chosen = f"{provider}:{model}" if model else provider
    parsed = providers_service.parse_backend(chosen or "gpt2")
    if parsed.get("kind") != "cloud":
        return {"kind": "local", "provider": None, "model": None, "api_key": None, "backend": parsed.get("backend") or "gpt2"}
    api_key, origin = providers_service.resolve_key(user_id, parsed["provider"])
    if not api_key:
        return {
            "kind": "unavailable",
            "provider": parsed["provider"],
            "model": parsed.get("model"),
            "api_key": None,
            "backend": parsed.get("backend"),
            "note": f"Sem chave de API para {parsed['provider']} (origem: {origin}).",
        }
    spec = dict(parsed.get("spec") or {})
    if parsed["provider"] == "ollama-cloud":
        custom_url = providers_service.resolve_provider_url(user_id, parsed["provider"])
        custom_model = providers_service.resolve_provider_model(user_id, parsed["provider"])
        if custom_url:
            spec["base_url"] = custom_url
        if parsed.get("model"):
            spec = {**spec, "models": list(dict.fromkeys([parsed["model"], *(spec.get("models") or [])]))}
        if custom_model and not parsed.get("model"):
            parsed["model"] = custom_model
    return {
        "kind": "cloud",
        "provider": parsed["provider"],
        "model": parsed.get("model") or providers_service.resolve_provider_model(user_id, parsed["provider"]),
        "spec": spec,
        "api_key": api_key,
        "backend": parsed.get("backend"),
    }


async def ask_model(backend: Dict[str, Any], *, system: str, prompt: str, max_tokens: int, temperature: float = 0.1) -> str:
    """Pergunta de uma só vez ao modelo (só para fornecedores cloud)."""
    from api.cloud_chat import complete_answer

    return await complete_answer(
        provider=backend["provider"],
        spec=backend.get("spec") or {},
        model=backend.get("model") or "",
        messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        api_key=backend.get("api_key"),
        temperature=temperature,
        max_tokens=max_tokens,
    )


# --------------------------------------------------------------------------
# Contexto
# --------------------------------------------------------------------------
def _existing_types(ontology_id: Optional[str]) -> List[Dict[str, Any]]:
    doc = registry.load_ontology(ontology_id=ontology_id)
    return [
        {
            "id": item["id"],
            "label": item["label"],
            "domain": item.get("domain"),
            "properties": [
                {
                    "id": prop.get("id"),
                    "field": prop.get("field"),
                    "type": prop.get("type"),
                    "values_from": prop.get("values_from"),
                }
                for prop in (item.get("properties") or [])
            ][:16],
        }
        for item in doc["object_types"]
    ]


def _domain_ids(ontology_id: Optional[str]) -> List[str]:
    doc = registry.load_ontology(ontology_id=ontology_id)
    return [domain["id"] for domain in doc["domains"]]


def _source_bundle(source_ids: Optional[List[str]], ontology_id: Optional[str]) -> List[Dict[str, Any]]:
    """Fontes escolhidas (ou todas) com o respetivo diagnóstico."""
    known = {source["id"]: source for source in registry.list_sources(ontology_id)}
    selected = [known[source_id] for source_id in (source_ids or []) if source_id in known] or list(known.values())
    bundle: List[Dict[str, Any]] = []
    for source in selected[:6]:
        diagnostic = sources_service.probe(source)
        bundle.append({"source": source, "diagnostic": diagnostic})
    return bundle


def _auto_proposal(bundle: List[Dict[str, Any]], *, domain: Optional[str], ontology_id: Optional[str]) -> Dict[str, Any]:
    """Proposta inferida dos campos reais das fontes (sem modelo)."""
    object_types: List[Dict[str, Any]] = []
    for entry in bundle:
        source = entry["source"]
        diagnostic = entry["diagnostic"]
        fields = diagnostic.get("fields") or []
        if not fields:
            continue
        object_types.append(
            sources_service.infer_object_type(
                source,
                fields=fields,
                domain=domain,
                samples=diagnostic.get("samples") or {},
            )
        )
    link_types = _heuristic_links(object_types, _existing_types(ontology_id))
    return {
        "object_types": object_types,
        "link_types": link_types,
        "domains": [{"id": _slug(domain, "dados"), "label": str(domain).title()}] if domain else [],
        "notes": ["Proposta inferida dos campos reais das fontes (sem modelo de IA)."],
    }


# --------------------------------------------------------------------------
# Relações
# --------------------------------------------------------------------------
KEY_FIELDS = ("nif", "nipc", "ticker", "symbol", "isin", "id", "codigo", "code", "email", "slug")


def _leaf(name: Optional[str]) -> str:
    """Último segmento de um caminho (`adjudicatarios.parsed.nif` → `nif`), normalizado."""
    return str(name or "").split(".")[-1].strip().lower()


def _property_keys(obj_type: Dict[str, Any]) -> Dict[str, str]:
    """Mapa `nome de campo curto → id da propriedade` de um tipo."""
    keys: Dict[str, str] = {}
    for prop in obj_type.get("properties") or []:
        if not isinstance(prop, dict):
            continue
        for candidate in (prop.get("field"), prop.get("id")):
            leaf = _leaf(candidate)
            if leaf:
                keys.setdefault(leaf, prop.get("id"))
    return keys


def _shared_key(left: Dict[str, Any], right: Dict[str, Any]) -> Optional[str]:
    """Campo-chave comum a dois tipos (nif, ticker, …) que justifica uma ligação."""
    left_keys = _property_keys(left)
    right_keys = _property_keys(right)
    for field in KEY_FIELDS:
        if field in left_keys and field in right_keys:
            return field
    left_props = {prop.get("id"): prop for prop in left.get("properties") or [] if isinstance(prop, dict)}
    for prop_id, prop in left_props.items():
        reference = prop.get("values_from")
        if reference and reference == right.get("id"):
            return prop_id
        if prop.get("type") == "reference" and prefix_of(prop.get("field"), right.get("id")):
            return prop_id
    return None


def prefix_of(field: Optional[str], type_id: Optional[str]) -> bool:
    if not field or not type_id:
        return False
    return str(field).split(".")[0].lower() in {str(type_id).lower(), str(type_id).lower() + "_id"}


def _heuristic_links(
    proposed: List[Dict[str, Any]],
    existing: List[Dict[str, Any]],
    extra_types: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Ligações por chave partilhada entre os tipos propostos e os já existentes."""
    universe = [*proposed, *(extra_types or []), *existing]
    links: List[Dict[str, Any]] = []
    seen: set = set()
    for index, left in enumerate(proposed):
        for right in universe:
            if right is left or right.get("id") == left.get("id"):
                continue
            field = _shared_key(left, right)
            if not field:
                continue
            link_id = f"{left['id']}_{right['id']}_{field}"
            if link_id in seen:
                continue
            seen.add(link_id)
            links.append(
                {
                    "id": _slug(link_id, "ligacao"),
                    "label": f"{left.get('label')} — {right.get('label')} (por {field})",
                    "description": f"Ligação proposta automaticamente pelo campo partilhado `{field}`.",
                    "from": left["id"],
                    "to": right["id"],
                    "cardinality": "many-to-one",
                    "binding": {"kind": "term", "from_field": field, "to_field": field},
                }
            )
            if len(links) >= 24:
                return links
        if index > 12:
            break
    return links


# --------------------------------------------------------------------------
# Validação da proposta
# --------------------------------------------------------------------------
def _clean_properties(raw: Any, *, field_lookup: Dict[str, Dict[str, Any]], warnings: List[str]) -> List[Dict[str, Any]]:
    properties: List[Dict[str, Any]] = []
    seen: set = set()
    for entry in raw or []:
        if not isinstance(entry, dict):
            continue
        prop_id = _slug(entry.get("id") or entry.get("field") or entry.get("label"), "campo")
        if not prop_id or prop_id in seen:
            continue
        seen.add(prop_id)
        prop_type = str(entry.get("type") or "keyword").lower()
        if prop_type not in ALLOWED_PROPERTY_TYPES:
            warnings.append(f"Propriedade `{prop_id}`: tipo «{prop_type}» não suportado (assumido keyword).")
            prop_type = "keyword"
        prop: Dict[str, Any] = {"id": prop_id, "label": str(entry.get("label") or prop_id.replace("_", " ").capitalize()), "type": prop_type}
        field = entry.get("field")
        if field:
            field = str(field)
            if field_lookup and field not in field_lookup and _leaf(field) not in {_leaf(name) for name in field_lookup}:
                warnings.append(f"Propriedade `{prop_id}`: o campo `{field}` não existe na fonte; campo removido.")
            else:
                prop["field"] = field
        if field_lookup:
            # O diagnóstico da fonte manda: corrige tipo e capacidades com os dados reais.
            real = field_lookup.get(prop.get("field") or "")
            if real is None and prop.get("field"):
                real = next((value for name, value in field_lookup.items() if _leaf(name) == _leaf(prop["field"])), None)
            if real:
                prop["type"] = real.get("type") or prop["type"]
                if real.get("field") and prop["type"] == "keyword":
                    prop["field"] = real.get("exact_field") or prop.get("field")
                if real.get("nested"):
                    prop["nested"] = real["nested"]
                for flag in ("searchable", "filterable", "sortable"):
                    if real.get(flag):
                        prop[flag] = True
            else:
                prop.pop("field", None)
        if entry.get("nested"):
            prop["nested"] = str(entry["nested"])
        for flag in ("pk", "searchable", "filterable", "sortable"):
            if entry.get(flag):
                prop[flag] = True
        if entry.get("enum"):
            prop["enum"] = [str(value) for value in entry["enum"]][:24]
        if entry.get("values_from"):
            prop["values_from"] = _slug(entry["values_from"], "tipo")
        if prop["type"] == "number":
            prop["sortable"] = True
        if field_lookup:
            real = field_lookup.get(prop.get("field") or "", {})
            if not real and prop.get("field"):
                real = next((value for name, value in field_lookup.items() if _leaf(name) == _leaf(prop["field"])), {})
            if real.get("sample") is not None:
                prop["sample_values"] = [str(real["sample"])]
        properties.append(prop)
    return properties


def clean_proposal(
    proposal: Dict[str, Any],
    *,
    bundle: List[Dict[str, Any]],
    domain: Optional[str],
    ontology_id: Optional[str],
) -> Dict[str, Any]:
    """Verifica e normaliza a proposta do modelo antes de a mostrar ou gravar."""
    warnings: List[str] = list(proposal.get("warnings") or [])
    known_types = {item["id"] for item in _existing_types(ontology_id)}
    objects: List[Dict[str, Any]] = []
    for entry in proposal.get("object_types") or []:
        if not isinstance(entry, dict):
            continue
        type_id = _slug(entry.get("id") or entry.get("label"), "objeto")
        if not type_id or type_id in known_types:
            if type_id in known_types:
                warnings.append(f"O tipo `{type_id}` já existe nesta ontologia; ignorado.")
            continue
        binding = entry.get("binding") if isinstance(entry.get("binding"), dict) else {}
        kind = str(binding.get("kind") or "es").lower()
        if kind not in ALLOWED_BINDING_KINDS:
            warnings.append(f"Tipo `{type_id}`: ligação «{kind}» desconhecida (assumido es).")
            kind = "es"
        source_id = binding.get("source")
        source_ids = {entry["source"]["id"] for entry in bundle}
        if source_id and source_id not in source_ids:
            warnings.append(f"Tipo `{type_id}`: fonte `{source_id}` desconhecida; ligação sem fonte.")
            binding = {key: value for key, value in binding.items() if key != "source"}
        field_lookup: Dict[str, Dict[str, Any]] = {}
        for entry_source in bundle:
            if entry_source["source"]["id"] == (source_id or (bundle[0]["source"]["id"] if bundle else None)):
                field_lookup = {field["name"]: field for field in entry_source["diagnostic"].get("fields") or []}
        properties = _clean_properties(entry.get("properties"), field_lookup=field_lookup, warnings=warnings)
        if not properties:
            warnings.append(f"Tipo `{type_id}` sem propriedades utilizáveis; ignorado.")
            continue
        if not any(prop.get("pk") for prop in properties):
            properties[0]["pk"] = True
        binding["kind"] = kind
        objects.append(
            {
                "id": type_id,
                "label": str(entry.get("label") or type_id.replace("_", " ").title()),
                "plural": str(entry.get("plural") or f"{entry.get('label') or type_id}s"),
                "description": str(entry.get("description") or ""),
                "domain": _slug(entry.get("domain") or domain or "dados", "dados"),
                "icon": str(entry.get("icon") or "database"),
                "primary_key": next((prop["id"] for prop in properties if prop.get("pk")), properties[0]["id"]),
                "title_field": _title_of(entry, properties),
                "subtitle_fields": [prop["id"] for prop in properties if prop.get("filterable")][:3],
                "resolvable": bool(entry.get("resolvable", True)),
                "binding": binding,
                "query_hint": str(entry.get("query_hint") or ""),
                "properties": properties,
            }
        )
        known_types.add(type_id)
    object_ids = {item["id"] for item in objects} | known_types
    links: List[Dict[str, Any]] = []
    for entry in proposal.get("link_types") or []:
        if not isinstance(entry, dict):
            continue
        link_id = _slug(entry.get("id") or f"{entry.get('from')}_{entry.get('to')}", "ligacao")
        source_type = _slug(entry.get("from") or entry.get("source_type"), "origem")
        target_type = _slug(entry.get("to") or entry.get("target_type"), "destino")
        if source_type not in object_ids or target_type not in object_ids:
            warnings.append(f"Ligação `{link_id}`: tipos `{source_type}`→`{target_type}` não existem; ignorada.")
            continue
        links.append(
            {
                "id": link_id,
                "label": str(entry.get("label") or f"{source_type} → {target_type}"),
                "description": str(entry.get("description") or ""),
                "from": source_type,
                "to": target_type,
                "cardinality": str(entry.get("cardinality") or "many-to-one"),
                "binding": entry.get("binding") if isinstance(entry.get("binding"), dict) else {},
                "reverse": entry.get("reverse") if isinstance(entry.get("reverse"), dict) else None,
            }
        )
    domains: List[Dict[str, Any]] = []
    known_domains = set(_domain_ids(ontology_id))
    for entry in [*(proposal.get("domains") or [])]:
        if not isinstance(entry, dict):
            continue
        domain_id = _slug(entry.get("id") or entry.get("label"), "dominio")
        if not domain_id or domain_id in known_domains:
            continue
        domains.append({"id": domain_id, "label": str(entry.get("label") or domain_id.title()), "description": str(entry.get("description") or "")})
        known_domains.add(domain_id)
    notes = [str(note) for note in (proposal.get("notes") or [])]
    return {"object_types": objects, "link_types": links, "domains": domains, "warnings": warnings, "notes": notes}


def _title_of(entry: Dict[str, Any], properties: List[Dict[str, Any]]) -> str:
    for candidate in ("title_field", "title"):
        value = entry.get(candidate)
        if value and any(prop["id"] == _slug(value, "campo") for prop in properties):
            return _slug(value, "campo")
    for field in sources_service.TITLE_CANDIDATES:
        for prop in properties:
            if prop["id"] == field.replace("ç", "c"):
                return prop["id"]
    for prop in properties:
        if prop.get("searchable"):
            return prop["id"]
    return properties[0]["id"]


# --------------------------------------------------------------------------
# Desenho da ontologia
# --------------------------------------------------------------------------
DESIGN_PROMPT = """\
Desenha (ou amplia) a ontologia «{ontology}» da plataforma IQ OS.

Pedido do utilizador:
{description}
{instructions}
Tipos de objeto que já existem (não repetir estes ids): {existing}
Domínios existentes: {domains}

Fontes de dados reais disponíveis (usa os nomes de campo exatamente como aparecem):
{sources}

Responde APENAS com JSON válido com esta forma:
{{
  "object_types": [
    {{
      "id": "snake_case_curto",
      "label": "Nome singular em português",
      "plural": "Nome plural",
      "description": "Uma frase",
      "domain": "dominio_existente_ou_novo",
      "primary_key": "id_da_propriedade",
      "title_field": "id_da_propriedade",
      "binding": {{"kind": "es", "index": "indice_da_fonte", "source": "id_da_fonte", "id_field": "campo", "search_fields": ["campo"]}},
      "properties": [
        {{"id": "campo", "label": "Rótulo", "type": "text|keyword|number|date|boolean|enum|reference",
          "field": "campo_real_do_indice", "pk": false, "searchable": false, "filterable": false, "sortable": false,
          "nested": "caminho_aninhado_se_existir", "values_from": "id_de_tipo_para_enum"}}
      ]
    }}
  ],
  "link_types": [
    {{"id": "origem_destino", "label": "Rótulo da relação", "from": "id_tipo_origem", "to": "id_tipo_destino",
      "cardinality": "many-to-one", "binding": {{"kind": "term", "from_field": "campo_origem", "to_field": "campo_destino"}},
      "reverse": {{"id": "destino_origem", "label": "Rótulo inverso"}}}}
  ],
  "domains": [{{"id": "dominio", "label": "Nome", "description": "Uma frase"}}],
  "notes": ["nota curta sobre decisões ou limitações"]
}}

Regras: usa apenas campos que existam nas fontes (copia os nomes tal como aparecem); cada tipo precisa de
propriedades; liga os tipos novos aos já existentes quando partilharem chaves (nif, ticker, id, código) e indica
`field`/`to_field` reais; não repitas ids existentes; escreve em português de Portugal.\
"""


async def design_ontology(
    *,
    description: str,
    source_ids: Optional[List[str]] = None,
    domain: Optional[str] = None,
    backend: Optional[str] = None,
    session: Any = None,
    ontology_id: Optional[str] = None,
    sample_text: Optional[str] = None,
    instructions: Optional[str] = None,
) -> Dict[str, Any]:
    """Propõe tipos/ligações para a ontologia a partir de uma descrição e/ou fontes."""
    target = registry.normalize_ontology_id(ontology_id) or registry.active_ontology_id()
    entry = registry.get_ontology_entry(target)
    bundle = _source_bundle(source_ids, target)
    chosen = available_backend(session, backend)
    result: Dict[str, Any] = {
        "ontology": {"id": target, "name": entry.get("name")},
        "backend": {"kind": chosen["kind"], "provider": chosen.get("provider"), "model": chosen.get("model"), "backend": chosen.get("backend")},
        "sources": [
            {
                "id": item["source"]["id"],
                "label": item["source"].get("label"),
                "kind": item["source"].get("kind"),
                "ok": bool(item["diagnostic"].get("ok")),
                "fields": len(item["diagnostic"].get("fields") or []),
                "documents": item["diagnostic"].get("documents"),
                "note": item["diagnostic"].get("note"),
            }
            for item in bundle
        ],
        "warnings": [],
        "notes": [],
    }
    if not bundle and not (description or "").strip():
        result["warnings"].append("Descreva o que quer modelar ou ligue pelo menos uma fonte de dados.")
        result["proposal"] = {"object_types": [], "link_types": [], "domains": []}
        return result

    proposal: Optional[Dict[str, Any]] = None
    if chosen["kind"] == "cloud":
        prompt = DESIGN_PROMPT.format(
            ontology=entry.get("name") or target,
            description=(description or "(sem descrição)").strip(),
            instructions=f"\nInstruções adicionais: {instructions.strip()}\n" if (instructions or "").strip() else "",
            existing=", ".join(item["id"] for item in _existing_types(target)) or "(nenhum)",
            domains=", ".join(_domain_ids(target)) or "(nenhum)",
            sources="\n\n".join(sources_service.describe_source(item["source"], item["diagnostic"]) for item in bundle) or "(sem fontes ligadas)",
        )
        if (sample_text or "").strip():
            prompt += f"\n\nAmostra de dados/notas fornecida pelo utilizador:\n{(sample_text or '').strip()[:4000]}"
        try:
            raw = await ask_model(chosen, system=SYSTEM_DESIGN, prompt=prompt, max_tokens=DESIGN_MAX_TOKENS)
            parsed = extract_json(raw)
            if parsed:
                proposal = parsed
                result["notes"].append(f"Proposta gerada por {chosen.get('provider')}:{chosen.get('model')}.")
            else:
                result["warnings"].append("O modelo não devolveu JSON válido; usada a inferência dos campos reais.")
        except Exception as exc:  # erro do fornecedor → segue com a via determinística
            logger.warning("Desenho de ontologia por IA falhou: %s", exc)
            result["warnings"].append(f"IA indisponível ({exc}); usada a inferência dos campos reais.")
    elif chosen["kind"] == "unavailable":
        result["notes"].append(chosen.get("note") or "Sem chave de API: proposta inferida dos dados.")
    else:
        result["notes"].append("Sem modelo configurado: proposta inferida dos campos reais das fontes.")

    cleaned = clean_proposal(proposal, bundle=bundle, domain=domain, ontology_id=target) if proposal else None
    if not cleaned or not cleaned["object_types"]:
        cleaned = clean_proposal(_auto_proposal(bundle, domain=domain, ontology_id=target), bundle=bundle, domain=domain, ontology_id=target)
        result["mode"] = "auto"
    else:
        result["mode"] = "ai"
    result["proposal"] = cleaned
    result["warnings"].extend(cleaned["warnings"])
    result["notes"].extend(cleaned["notes"])
    # Pré-visualização do que os tipos novos vão mostrar.
    result["preview"] = [
        {
            "id": item["id"],
            "label": item["label"],
            "properties": len(item["properties"]),
            "source": (item.get("binding") or {}).get("source"),
            "index": (item.get("binding") or {}).get("index"),
        }
        for item in cleaned["object_types"]
    ]
    result["totals"] = {
        "object_types": len(cleaned["object_types"]),
        "link_types": len(cleaned["link_types"]),
        "domains": len(cleaned["domains"]),
        "properties": sum(len(item["properties"]) for item in cleaned["object_types"]),
    }
    if not result["totals"]["object_types"]:
        result["warnings"].append("Nenhum tipo foi proposto: confirme a descrição ou o diagnóstico das fontes.")
    return result


def apply_proposal(proposal: Dict[str, Any], *, ontology_id: Optional[str] = None) -> Dict[str, Any]:
    """Grava uma proposta (tipos, ligações e domínios) na ontologia."""
    from api import ontology_service as ontology

    target = registry.normalize_ontology_id(ontology_id) or registry.active_ontology_id()
    created: Dict[str, List[str]] = {"object_types": [], "link_types": [], "domains": []}
    errors: List[str] = []
    for domain in proposal.get("domains") or []:
        if not isinstance(domain, dict) or not domain.get("id"):
            continue
        try:
            store = registry._read_store(target)
            domains = store.get("domains") or []
            if not any(item.get("id") == domain["id"] for item in domains):
                domains.append(
                    {"id": domain["id"], "label": domain.get("label") or domain["id"], "description": domain.get("description") or ""}
                )
                store["domains"] = domains
                registry._write_store(store, target)
                created["domains"].append(domain["id"])
        except Exception as exc:
            errors.append(f"Domínio {domain.get('id')}: {exc}")
    for item in proposal.get("object_types") or []:
        try:
            registry.upsert_object_type(item, target)
            created["object_types"].append(item["id"])
        except Exception as exc:
            errors.append(f"Tipo {item.get('id')}: {exc}")
    # As ligações só entram depois de os tipos existirem (e só se os dois existirem).
    known = {item["id"] for item in registry.load_ontology(ontology_id=target)["object_types"]}
    for link in proposal.get("link_types") or []:
        if link.get("from") not in known or link.get("to") not in known:
            errors.append(f"Ligação {link.get('id')}: tipos em falta.")
            continue
        try:
            body = dict(link)
            if not body.get("binding"):
                body["binding"] = {"kind": "term", "from_field": body["from"], "to_field": body["to"]}
            registry.upsert_link_type(body, target)
            created["link_types"].append(link["id"])
        except Exception as exc:
            errors.append(f"Ligação {link.get('id')}: {exc}")
    ontology.clear_cache()
    return {"applied": True, "ontology": target, "created": created, "errors": errors}


# --------------------------------------------------------------------------
# Ligações sugeridas
# --------------------------------------------------------------------------
LINKS_PROMPT = """\
Tipos de objeto da ontologia «{ontology}» (com propriedades e fontes):
{types}

Ligações que já existem (não repetir):
{links}

Propõe as ligações que faltam entre estes tipos — relações úteis para análise (por chave partilhada
como nif/ticker/id/código, por referência, ou por significado). Máximo 12.

Responde APENAS com JSON:
{{"link_types": [{{"id": "origem_destino", "label": "Rótulo", "description": "Uma frase",
  "from": "id_tipo", "to": "id_tipo", "cardinality": "many-to-one",
  "binding": {{"kind": "term", "from_field": "campo", "to_field": "campo"}},
  "reverse": {{"id": "destino_origem", "label": "Rótulo inverso"}}}}], "notes": []}}\
"""


async def suggest_links(
    *,
    backend: Optional[str] = None,
    session: Any = None,
    ontology_id: Optional[str] = None,
    type_ids: Optional[List[str]] = None,
    apply: bool = False,
) -> Dict[str, Any]:
    """Propõe ligações em falta entre os tipos existentes."""
    target = registry.normalize_ontology_id(ontology_id) or registry.active_ontology_id()
    doc = registry.load_ontology(ontology_id=target)
    chosen = available_backend(session, backend)
    types = [item for item in doc["object_types"] if not type_ids or item["id"] in set(type_ids)]
    existing = [
        {"id": link["id"], "from": link["from"], "to": link["to"], "label": link.get("label")}
        for link in doc["link_types"]
    ]
    existing_keys = {(link["from"], link["to"]) for link in doc["link_types"]}
    result: Dict[str, Any] = {
        "ontology": {"id": target, "name": doc["ontology"]["name"]},
        "backend": {"kind": chosen["kind"], "provider": chosen.get("provider"), "model": chosen.get("model")},
        "warnings": [],
        "notes": [],
    }
    proposal: Optional[Dict[str, Any]] = None
    if chosen["kind"] == "cloud":
        prompt = LINKS_PROMPT.format(
            ontology=doc["ontology"]["name"],
            types="\n".join(
                f"- {item['id']} ({item['label']}, domínio {item.get('domain')}): "
                f"{', '.join(prop['id'] for prop in (item.get('properties') or [])[:12])} | fonte: "
                f"{(item.get('binding') or {}).get('source') or (item.get('binding') or {}).get('index') or '- '}"
                for item in types
            ),
            links="\n".join(f"- {link['id']}: {link['from']} → {link['to']}" for link in existing) or "(nenhuma)",
        )
        try:
            raw = await ask_model(chosen, system=SYSTEM_LINKS, prompt=prompt, max_tokens=LINKS_MAX_TOKENS)
            parsed = extract_json(raw)
            if parsed:
                proposal = parsed
                result["notes"].append(f"Sugestões de {chosen.get('provider')}:{chosen.get('model')}.")
            else:
                result["warnings"].append("O modelo não devolveu JSON válido; usadas as chaves partilhadas.")
        except Exception as exc:
            logger.warning("Sugestão de ligações falhou: %s", exc)
            result["warnings"].append(f"IA indisponível ({exc}); usadas as chaves partilhadas.")
    else:
        result["notes"].append("Sem modelo configurado: sugestões por chaves partilhadas (nif, ticker, id, código).")

    links: List[Dict[str, Any]] = []
    if proposal:
        cleaned = clean_proposal({"link_types": proposal.get("link_types")}, bundle=[], domain=None, ontology_id=target)
        links = cleaned["link_types"]
        result["warnings"].extend(cleaned["warnings"])
    if not links:
        links = _heuristic_links(types, [])
    filtered: List[Dict[str, Any]] = []
    for link in links:
        if (link["from"], link["to"]) in existing_keys:
            continue
        if any(item["id"] == link["id"] for item in doc["link_types"]):
            link["id"] = _slug(f"{link['id']}_2", "ligacao_2")
        filtered.append(link)
    result["link_types"] = filtered[:12]
    result["totals"] = {"suggestions": len(result["link_types"]), "existing": len(existing)}
    if apply and filtered:
        result["applied"] = apply_proposal({"link_types": filtered}, ontology_id=target)
    return result


# --------------------------------------------------------------------------
# Fichas de análise
# --------------------------------------------------------------------------
DOSSIER_PROMPT = """\
Redige a secção «{section}» de uma ficha de análise da plataforma IQ OS.

Assunto: {subject}
Secções já escritas: {existing}

Factos verificados na plataforma (usa apenas estes):
{facts}

Escreve 2 a 5 parágrafos corridos em português de Portugal, sem listas nem markdown, sem inventar
números. Se faltar informação, di-lo de forma explícita. Devolve apenas o texto.\
"""


def _facts_for(subject: Dict[str, Any], links: Dict[str, Any], object_data: Optional[Dict[str, Any]]) -> List[str]:
    """Lista de factos verificados sobre o assunto da ficha."""
    facts: List[str] = []
    item = (object_data or {}).get("object") or {}
    if item:
        title = item.get("_title") or item.get("_label") or item.get("_id")
        facts.append(f"Objeto: {title} (tipo {subject.get('type_id')}, id {subject.get('object_id')}).")
        for key, value in list(item.items())[:24]:
            if key.startswith("_"):
                continue
            if value in (None, "", [], {}):
                continue
            facts.append(f"{key} = {str(value)[:160]}")
    for group in (links or {}).get("links") or []:
        label = group.get("label") or group.get("id")
        items = group.get("items") or []
        facts.append(f"Relação «{label}»: {group.get('total', len(items))} objetos.")
        for entry in items[:5]:
            name = entry.get("_title") or entry.get("_label") or entry.get("_id")
            facts.append(f"- {name}")
    return facts


async def draft_dossier(
    *,
    dossier: Dict[str, Any],
    payload: Optional[Dict[str, Any]] = None,
    session: Any = None,
    backend: Optional[str] = None,
    ontology_id: Optional[str] = None,
    apply: bool = False,
) -> Dict[str, Any]:
    """Redige uma secção/estrutura de ficha a partir dos dados reais do assunto."""
    from api import ontology_service as ontology

    target = registry.normalize_ontology_id(ontology_id) or registry.active_ontology_id()
    payload = payload or {}
    subject = payload.get("subject") if isinstance(payload.get("subject"), dict) else (dossier.get("subject") or {})
    scope = payload.get("scope")
    object_data: Optional[Dict[str, Any]] = None
    links: Dict[str, Any] = {}
    warnings: List[str] = []
    if subject.get("type_id") and subject.get("object_id"):
        try:
            object_data = ontology.get_object(
                subject["type_id"], str(subject["object_id"]), scope=scope, include_source=False, with_links=True
            )
        except Exception as exc:
            warnings.append(f"Não foi possível ler o objeto: {exc}")
        try:
            links = ontology.object_links(subject["type_id"], str(subject["object_id"]), size=8, scope=scope)
        except Exception as exc:
            warnings.append(f"Não foi possível ler as relações: {exc}")
    facts = _facts_for(subject, links, object_data)
    chosen = available_backend(session, backend)
    sections = [section for section in (dossier.get("sections") or []) if isinstance(section, dict)]
    section_title = str(payload.get("section") or (sections[0].get("title") if sections else "Sumário executivo"))
    result: Dict[str, Any] = {
        "ontology": {"id": target},
        "backend": {"kind": chosen["kind"], "provider": chosen.get("provider"), "model": chosen.get("model")},
        "subject": subject,
        "facts": facts,
        "section": section_title,
        "warnings": warnings,
        "notes": [],
    }
    if not facts:
        result["warnings"].append("Sem factos: escolha um objeto da ontologia como assunto da ficha.")
        result["text"] = ""
        result["mode"] = "empty"
        return result
    text = ""
    if chosen["kind"] == "cloud":
        prompt = DOSSIER_PROMPT.format(
            section=section_title,
            subject=f"{subject.get('type_id')}/{subject.get('object_id')}",
            existing=", ".join(str(section.get("title")) for section in sections if section.get("title")) or "(nenhuma)",
            facts="\n".join(facts[:60]),
        )
        try:
            text = (await ask_model(chosen, system=SYSTEM_DOSSIER, prompt=prompt, max_tokens=DOSSIER_MAX_TOKENS, temperature=0.2)).strip()
            result["mode"] = "ai"
            result["notes"].append(f"Texto redigido por {chosen.get('provider')}:{chosen.get('model')}.")
        except Exception as exc:
            logger.warning("Redação de ficha falhou: %s", exc)
            result["warnings"].append(f"IA indisponível ({exc}); gerado resumo factual.")
    else:
        result["notes"].append("Sem modelo configurado: gerado resumo factual a partir dos dados.")
    if not text:
        text = _factual_summary(subject, object_data, links, facts)
        result["mode"] = "factual"
    result["text"] = text
    if apply:
        sections = list(sections)
        sections.append(
            {
                "id": _slug(f"{section_title}-{len(sections) + 1}", "seccao"),
                "title": section_title,
                "kind": "ai" if result["mode"] == "ai" else "text",
                "content": text,
                "created_at": registry._now(),
                "source": f"{chosen.get('provider') or 'factos'}:{chosen.get('model') or 'ontologia'}",
            }
        )
        updated = registry.upsert_dossier({**dossier, "sections": sections}, target)
        result["dossier"] = updated
    return result


def _factual_summary(subject: Dict[str, Any], object_data: Optional[Dict[str, Any]], links: Dict[str, Any], facts: List[str]) -> str:
    item = (object_data or {}).get("object") or {}
    title = item.get("_title") or item.get("_label") or subject.get("object_id")
    lines = [f"Resumo factual de {title} ({subject.get('type_id')}/{subject.get('object_id')})."]
    metrics = [fact for fact in facts[1:13] if " = " in fact]
    if metrics:
        lines.append("Dados registados: " + "; ".join(metrics) + ".")
    for group in (links or {}).get("links") or []:
        total = group.get("total") or len(group.get("items") or [])
        lines.append(f"Relação «{group.get('label') or group.get('id')}»: {total} objetos ligados.")
    lines.append("Texto redigido sem modelo de IA; apenas os factos acima, tal como registados na plataforma.")
    return "\n\n".join(lines)
