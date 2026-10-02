"""Pipeline de contratos públicos de França (DECP / data.gouv.fr).

Fonte: `data/contratos-franca/decp-*.json` (JSON publicado pelo profil d'acheteur,
formato DECP). O pipeline normaliza cada registo para um documento plano,
produz `data/processed/contratos-franca/decp_<ano>_<mes>.jsonl` e pode indexar
em Elasticsearch (`contratos_fr`).

Decisões de normalização:
- `doc_id` = sha1 de `fr|<acheteur.id>|<id>|<nature>`: idempotente entre
  reprocessamentos.
- Datas inválidas/ambíguas do DECP são corrigidas quando possível (ano com 2
  dígitos, ano "00" resolvido via data de publicação); mantém-se a data bruta
  em `date_notification_raw` / `date_publication_raw`.
- Titulaires são desdobrados: o documento principal leva o primeiro titulaire
  nos campos planos (`adjudicatario_id`/`adjudicatario_nom`); todos ficam em
  `titulaires` para facetas/entidades.
- CPV: guarda o código bruto e a descrição em francês (quando disponível no
  prefixo do CPV; para descrições completas usar futuro mapeamento CPV2008).
- Local de execução: `lieuExecution.code` e `lieuExecution.typeCode`.

Uso:
    python -m collectors.contratos_fr --list
    python -m collectors.contratos_fr --process decp-2026-09.json --index
    python -m collectors.contratos_fr --index-only --jsonl data/processed/contratos-franca/decp_2026_09.jsonl
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "data" / "contratos-franca"
PROCESSED_DIR = ROOT / "data" / "processed" / "contratos-franca"

# Tipos de contrato DECP que conhecemos; a nature pode vir como "Marché",
# "Contrat de concession", etc.
NATURE_MARCHE = "Marché"
NATURE_CONCESSION = "Contrat de concession"


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v).strip() for v in value if v is not None)
    return str(value).strip()


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _as_int(value: Any) -> Optional[int]:
    f = _as_float(value)
    if f is None:
        return None
    return int(f)


def _parse_date(value: Optional[str], fallback: Optional[str] = None) -> Optional[str]:
    """Normaliza data ISO; corrige anos com 2 dígitos se houver fallback."""
    if not value:
        return None
    txt = value.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(txt, fmt).date().isoformat()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(txt.replace("Z", "+00:00")).isoformat()
    except ValueError:
        pass
    return None


def _fix_two_digit_year(
    iso_date: Optional[str],
    fallback_year: Optional[int],
) -> Optional[str]:
    """O DECP publica por vezes datas com ano de 2 dígitos (ex.: 0023-03-03).

    Se o ano parecer inválido (< 1900) e existir um fallback (data de
    publicação), adivinha o século comparando as duas últimas cifras.
    """
    if not iso_date or len(iso_date) < 4:
        return iso_date
    try:
        year = int(iso_date[:4])
    except ValueError:
        return iso_date
    if year >= 1900:
        return iso_date
    if not fallback_year:
        return iso_date
    suffix = year % 100
    base = (fallback_year // 100) * 100
    candidates = [base + suffix, base + suffix - 100, base + suffix + 100]
    # Escolhe o candidato mais próximo do ano de publicação (diferença absoluta).
    best = min(candidates, key=lambda y: abs(y - fallback_year))
    if 1900 <= best <= datetime.now(timezone.utc).year + 1:
        return f"{best}{iso_date[4:]}"
    return iso_date


def _extract_year(date_iso: Optional[str]) -> Optional[int]:
    if not date_iso or len(date_iso) < 4:
        return None
    try:
        year = int(date_iso[:4])
        if 1900 <= year <= datetime.now(timezone.utc).year + 1:
            return year
    except ValueError:
        pass
    return None


def _safe_id(value: Any) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", str(value))[:120]


def _doc_id(acheteur_id: Optional[str], record_id: Optional[str], nature: Optional[str]) -> str:
    key = f"fr|{acheteur_id or ''}|{record_id or ''}|{nature or ''}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


def _cpv_label(code: str) -> str:
    """Descrição básica do CPV a partir do prefixo (família).

    O DECP traz apenas o código; para descrições completas seria necessário um
    mapeamento CPV2008. Aqui devolvemos uma categoria grossa para facilitar
    facetas até esse mapeamento existir.
    """
    if not code:
        return ""
    family = code[:2]
    labels = {
        "03": "Produits agricoles",
        "09": "Produits pétroliers",
        "14": "Travaux de construction",
        "15": "Produits alimentaires",
        "16": "Agriculture",
        "18": "Textiles",
        "19": "Cuir et textiles",
        "20": "Produits chimiques",
        "22": "Imprimés",
        "24": "Matériaux de construction",
        "30": "Matériel informatique",
        "31": "Matériel électrique",
        "32": "Matériel de radio/télécommunication",
        "33": "Matériel médical",
        "34": "Matériel de transport",
        "35": "Matériel de sécurité",
        "36": "Instruments de musique",
        "37": "Sports",
        "38": "Matériel de laboratoire",
        "39": "Meubles",
        "41": "Eau collectée et traitée",
        "42": "Machines industrielles",
        "43": "Machines pour l'industrie",
        "44": "Matériel d'installation",
        "45": "Travaux de construction",
        "48": "Logiciels",
        "50": "Services de réparation",
        "51": "Services d'installation",
        "55": "Services hôteliers",
        "60": "Services de transport",
        "61": "Services de télécommunications",
        "62": "Services informatiques",
        "63": "Services d'information",
        "64": "Services financiers",
        "65": "Services d'assurance",
        "66": "Services financiers et d'assurance",
        "67": "Services immobiliers",
        "70": "Services immobiliers",
        "71": "Services d'architecture",
        "72": "Services de recherche",
        "73": "Services publicitaires",
        "75": "Services administratifs",
        "76": "Services d'ingénierie",
        "77": "Services d'assurance",
        "79": "Services d'affaires",
        "80": "Services d'éducation",
        "85": "Services de santé",
        "90": "Services d'assainissement",
        "92": "Services de loisirs",
        "98": "Services divers",
    }
    return labels.get(family, "")


def _normalize_titulaires(titulaires: Any) -> List[Dict[str, Any]]:
    """Extrai lista de titulaires do formato DECP aninhado."""
    out: List[Dict[str, Any]] = []
    if not titulaires:
        return out
    if isinstance(titulaires, dict):
        titulaires = [titulaires]
    for entry in titulaires:
        if not isinstance(entry, dict):
            continue
        t = entry.get("titulaire") or entry
        if not isinstance(t, dict):
            continue
        out.append({
            "type_identifiant": _normalize_text(t.get("typeIdentifiant")),
            "id": _normalize_text(t.get("id")),
            "nom": _normalize_text(t.get("nom")),
        })
    return out


def _first_titulaire(titulaires: List[Dict[str, Any]]) -> Dict[str, Any]:
    return titulaires[0] if titulaires else {}


def normalize_record(raw: Dict[str, Any], filename: str) -> Optional[Dict[str, Any]]:
    """Converte um registo DECP num documento ES normalizado (plano)."""
    if not isinstance(raw, dict):
        return None

    record_id = _normalize_text(raw.get("id"))
    if not record_id:
        return None

    acheteur = raw.get("acheteur") or {}
    if isinstance(acheteur, str):
        acheteur = {"id": acheteur}
    acheteur_id = _normalize_text(acheteur.get("id"))
    acheteur_nom = _normalize_text(acheteur.get("nom"))

    nature = _normalize_text(raw.get("nature")) or NATURE_MARCHE
    doc_id = _doc_id(acheteur_id, record_id, nature)

    date_pub_raw = _normalize_text(raw.get("datePublicationDonnees"))
    date_pub = _parse_date(date_pub_raw)
    pub_year = _extract_year(date_pub)

    date_notif_raw = _normalize_text(raw.get("dateNotification"))
    date_notif = _fix_two_digit_year(_parse_date(date_notif_raw), pub_year)

    # Ano: preferência pela data de notificação corrigida, depois publicação,
    # depois ano/mês do nome do ficheiro.
    ano = _extract_year(date_notif) or _extract_year(date_pub)
    if ano is None:
        m = re.search(r"(\d{4})", filename)
        if m:
            ano = int(m.group(1))

    montant = _as_float(raw.get("montant"))
    montant_estime = _as_float(raw.get("montantEstime"))
    valor = montant if montant is not None else montant_estime

    cpv_code = _normalize_text(raw.get("codeCPV"))
    cpv: List[Dict[str, str]] = []
    if cpv_code:
        cpv.append({"code": cpv_code, "nom": _cpv_label(cpv_code)})

    lieu = raw.get("lieuExecution") or {}
    if isinstance(lieu, str):
        lieu = {"code": lieu}
    lieu_code = _normalize_text(lieu.get("code"))
    lieu_type = _normalize_text(lieu.get("typeCode"))
    lieu_nom = _normalize_text(lieu.get("nom"))

    titulaires = _normalize_titulaires(raw.get("titulaires"))
    first = _first_titulaire(titulaires)

    doc: Dict[str, Any] = {
        "doc_id": doc_id,
        "pais": "FR",
        "fonte": "decp",
        "filename": filename,
        "id": record_id,
        "nature": nature,
        "objet": _normalize_text(raw.get("objet")),
        "code_cpv": cpv_code,
        "cpv": cpv,
        "procedure": _normalize_text(raw.get("procedure")),
        "ccag": _normalize_text(raw.get("ccag")),
        "offres_recues": _as_int(raw.get("offresRecues")),
        "type_groupement": _normalize_text(raw.get("typeGroupementOperateurs")),
        "lieu_execution_code": lieu_code,
        "lieu_execution_type": lieu_type,
        "lieu_execution_nom": lieu_nom,
        "duree_mois": _as_int(raw.get("dureeMois")),
        "date_notification": date_notif,
        "date_notification_raw": date_notif_raw,
        "date_publication": date_pub,
        "date_publication_raw": date_pub_raw,
        "montant": montant,
        "montant_estime": montant_estime,
        "valor": valor,
        "forme_prix": _normalize_text(raw.get("formePrix")),
        "acheteur_id": acheteur_id,
        "acheteur_nom": acheteur_nom,
        "adjudicatario_id": first.get("id"),
        "adjudicatario_type_identifiant": first.get("type_identifiant"),
        "adjudicatario_nom": first.get("nom"),
        "titulaires": titulaires,
        "considerations_sociales": _to_strings(raw.get("considerationsSociales")),
        "considerations_environnementales": _to_strings(raw.get("considerationsEnvironnementales")),
        "modalites_execution": _to_strings(raw.get("modalitesExecution")),
        "techniques": _to_strings(raw.get("techniques")),
        "types_prix": _to_strings(raw.get("typesPrix")),
        "source": _normalize_text(raw.get("source")) or "data.gouv.fr_pes",
        "taux_avance": _as_float(raw.get("tauxAvance")),
        "origine_ue": _as_float(raw.get("origineUE")),
        "origine_france": _as_float(raw.get("origineFrance")),
        "marche_innovant": bool(raw.get("marcheInnovant")) if raw.get("marcheInnovant") is not None else None,
        "attribution_avance": bool(raw.get("attributionAvance")) if raw.get("attributionAvance") is not None else None,
        "sous_traitance_declaree": bool(raw.get("sousTraitanceDeclaree")) if raw.get("sousTraitanceDeclaree") is not None else None,
        "ano": ano,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
    }

    doc["search_text"] = "\n".join(
        [
            doc["objet"],
            doc["acheteur_nom"],
            doc["adjudicatario_nom"],
            " ".join(t.get("nom", "") for t in titulaires),
            doc["procedure"],
            doc["forme_prix"],
            doc["code_cpv"],
            doc["lieu_execution_nom"],
        ]
    )
    return doc


def _to_strings(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, dict):
        # Estrutura com chave plural + lista, ex.: {"considerationSociale": [...]}
        out: List[str] = []
        for v in value.values():
            out.extend(_to_strings(v))
        return out
    if isinstance(value, list):
        return [_normalize_text(v) for v in value]
    return [_normalize_text(value)]


def iter_records(json_path: Path) -> Iterator[Tuple[str, Dict[str, Any]]]:
    """Itera secções DECP (marche, contrat-concession) e devolve (nature, raw)."""
    with open(json_path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    marches = data.get("marches") if isinstance(data, dict) else None
    if not marches:
        return
    for section, records in marches.items():
        if not isinstance(records, list):
            continue
        for raw in records:
            if not isinstance(raw, dict):
                continue
            # Garante que a nature está preenchida quando a secção é concession.
            if section == "contrat-concession" and not raw.get("nature"):
                raw = dict(raw)
                raw["nature"] = NATURE_CONCESSION
            yield section, raw


def build_jsonl(
    json_path: Path,
    force: bool = False,
    limit: Optional[int] = None,
    on_progress: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """Normaliza um ficheiro DECP e escreve JSONL.

    O nome do ficheiro de saída é `decp_<ano>_<mes>.jsonl`, extraído do nome do
    ficheiro de entrada.
    """
    json_path = Path(json_path)
    filename = json_path.name
    m = re.search(r"decp-(\d{4})-(\d{2})", filename)
    out_name = f"decp_{m.group(1)}_{m.group(2)}.jsonl" if m else f"{json_path.stem}.jsonl"
    out_path = PROCESSED_DIR / out_name
    meta_path = PROCESSED_DIR / f"{out_path.stem}.meta.json"

    if out_path.exists() and meta_path.exists() and not force:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        return {"path": str(out_path), "count": meta.get("count", 0), "errors": meta.get("errors", 0), "meta": meta}

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    count = 0
    errors = 0
    sections: Dict[str, int] = {}
    earliest: Optional[str] = None
    latest: Optional[str] = None
    started = time.time()

    with open(out_path, "w", encoding="utf-8") as out:
        for section, raw in iter_records(json_path):
            if limit is not None and count >= limit:
                break
            try:
                doc = normalize_record(raw, filename)
                if not doc:
                    continue
                out.write(json.dumps(doc, ensure_ascii=False) + "\n")
                count += 1
                sections[section] = sections.get(section, 0) + 1
                d = doc.get("date_notification") or doc.get("date_publication")
                if d:
                    if earliest is None or d < earliest:
                        earliest = d
                    if latest is None or d > latest:
                        latest = d
                if on_progress and count % 1000 == 0:
                    on_progress({"count": count, "section": section})
            except Exception:
                errors += 1

    meta = {
        "source": str(json_path),
        "filename": filename,
        "out": str(out_path),
        "count": count,
        "errors": errors,
        "sections": sections,
        "date_min": earliest,
        "date_max": latest,
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "path": str(out_path),
        "count": count,
        "errors": errors,
        "meta": meta,
        "seconds": round(time.time() - started, 1),
    }


def available_jsonl() -> List[Path]:
    """Lista JSONLs normalizados de França."""
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    return sorted(PROCESSED_DIR.glob("decp_*.jsonl"))


def index_jsonl(jsonl_path: Path, chunk_size: int = 2000, max_records: Optional[int] = None) -> Dict[str, Any]:
    """Indexa um JSONL de contratos franceses no Elasticsearch."""
    from api.elasticsearch_client import index_contratos_fr, get_es_client, ensure_indices

    client = get_es_client()
    if not client:
        return {"error": "Elasticsearch indisponível", "indexed_count": 0}
    ensure_indices(client)

    total = success_total = error_total = 0
    chunk: List[Dict[str, Any]] = []
    started = time.time()

    with open(jsonl_path, "r", encoding="utf-8") as fh:
        for line in fh:
            if max_records and total >= max_records:
                break
            line = line.strip()
            if not line:
                continue
            try:
                chunk.append(json.loads(line))
            except json.JSONDecodeError:
                continue
            total += 1
            if len(chunk) >= chunk_size:
                res = index_contratos_fr(chunk, client)
                success_total += res.get("indexed_count", 0)
                error_total += res.get("errors", 0) or (len(chunk) if res.get("error") else 0)
                chunk = []
                if total % (chunk_size * 10) == 0:
                    rate = total / max(time.time() - started, 1e-6)
                    print(f"[contratos_fr] {total:,} docs · {rate:,.0f} docs/s", flush=True)
    if chunk:
        res = index_contratos_fr(chunk, client)
        success_total += res.get("indexed_count", 0)
        error_total += res.get("errors", 0) or (len(chunk) if res.get("error") else 0)

    return {
        "indexed_count": success_total,
        "total": total,
        "errors": error_total,
        "seconds": round(time.time() - started, 1),
    }


def _list_sources() -> List[Dict[str, Any]]:
    sources: List[Dict[str, Any]] = []
    for path in sorted(SOURCE_DIR.glob("decp-*.json")):
        m = re.search(r"decp-(\d{4})-(\d{2})", path.name)
        sources.append({
            "filename": path.name,
            "ano": int(m.group(1)) if m else None,
            "mes": int(m.group(2)) if m else None,
            "size_mb": round(path.stat().st_size / (1024 * 1024), 2),
            "processed": (PROCESSED_DIR / f"decp_{m.group(1)}_{m.group(2)}.jsonl").exists() if m else False,
        })
    return sources


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Pipeline DECP França")
    parser.add_argument("--list", action="store_true", help="Listar ficheiros DECP disponíveis")
    parser.add_argument("--process", metavar="FILE", help="Normalizar um ficheiro DECP para JSONL")
    parser.add_argument("--index", action="store_true", help="Indexar o JSONL gerado")
    parser.add_argument("--index-only", metavar="JSONL", help="Indexar um JSONL existente")
    parser.add_argument("--force", action="store_true", help="Reprocessar mesmo que o JSONL exista")
    parser.add_argument("--limit", type=int, help="Limite de registos (amostra)")
    args = parser.parse_args()

    if args.list:
        for s in _list_sources():
            print(s)
        return 0

    if args.process:
        path = SOURCE_DIR / args.process if not Path(args.process).is_absolute() else Path(args.process)
        info = build_jsonl(path, force=args.force, limit=args.limit, on_progress=lambda p: print(p, flush=True))
        print(json.dumps({"path": info["path"], "count": info["count"], "errors": info["errors"]}, indent=2))
        if args.index:
            idx = index_jsonl(Path(info["path"]), max_records=args.limit)
            print(json.dumps(idx, indent=2))
        return 0

    if args.index_only:
        idx = index_jsonl(Path(args.index_only), max_records=args.limit)
        print(json.dumps(idx, indent=2))
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
