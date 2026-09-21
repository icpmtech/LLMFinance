"""Pipeline de contratos públicos de Espanha (PLACSP) — ZIP/ATOM -> JSONL -> Elasticsearch.

Fontes (em `data/contratos-espanha`):
- `licitacionesPerfilesContratanteCompleto3_<ano>.zip` — licitações e adjudicações.
- `contratosMenoresPerfilesContratantes_<ano>.zip` — contratos menores.

Cada ZIP contém vários ficheiros `.atom` (feed Atom 1.0 com entradas CODICE/UBL
`cac-place-ext:ContractFolderStatus`). O pipeline lê **em streaming** de dentro do
ZIP (não extrai para disco) e produz:
- `data/processed/contratos-es/<fonte>_<ano>.jsonl` — documentos normalizados;
- `data/processed/contratos-es/<fonte>_<ano>.meta.json` — estado/contagens (permite retomar);
- índice Elasticsearch `contratos_es` (`--index`).

Decisões de normalização:
- `_id` do documento ES = sha1 de `<fonte>|<DIR3 do órgão>|<id_expediente>`: o mesmo
  expediente é republicado a cada mudança de estado, por isso a última publicação
  processada vence (anos ascendentes, e dentro do ano ficheiros por ordem de nome).
  Isto também elimina os ZIPs duplicados (`...(1).zip`).
- Os códigos CODICE são guardados em bruto **e** com o rótulo oficial, lido das listas
  de códigos em `data/contratos-espanha/codigos/*.gc` (ver `LABELS`).
- Os feeds são UTF-8 (apesar de aparecerem «Espa±a» em consolas cp1252).

Uso:
    python -m collectors.contratos_es --list
    python -m collectors.contratos_es --datasets licitaciones menores --years 2023
    python -m collectors.contratos_es --datasets licitaciones --years 2023 --index
    python -m collectors.contratos_es --index-only --jsonl <ficheiro.jsonl>
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Tuple
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "data" / "contratos-espanha"
PROCESSED_DIR = ROOT / "data" / "processed" / "contratos-es"
CODIGOS_DIR = SOURCE_DIR / "codigos"

DATASETS: Dict[str, str] = {
    "licitaciones": "licitacionesPerfilesContratanteCompleto3",
    "menores": "contratosMenoresPerfilesContratantes",
}

NS_CODICE = "urn:dgpe:names:draft:codice"
ESTADO_LABELS = {
    "PRE": "Anuncio previo",
    "PUB": "En plazo",
    "EV": "Pendiente de adjudicación",
    "ADJ": "Adjudicada",
    "RES": "Resuelta",
    "ANUL": "Anulada",
}


# ------------------------------------------------------------------ listas de códigos
def _local(tag: str) -> str:
    return tag.split("}")[-1]


def _load_gc(path: Path) -> Dict[str, str]:
    """Lê uma lista de códigos genericode (`code` -> rótulo).

    As listas CODICE trazem a coluna `nombre` (espanhol) e `name` (inglês); a
    espanhola é preferida por ser a língua da fonte.
    """
    if not path.exists():
        return {}
    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    if "encoding=\"ISO-8859-1\"" in text[:200] or "encoding='ISO-8859-1'" in text[:200]:
        text = raw.decode("iso-8859-1", errors="replace")
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return {}
    out: Dict[str, str] = {}
    for row in root.iter():
        if _local(row.tag) != "Row":
            continue
        code: Optional[str] = None
        es: Optional[str] = None
        en: Optional[str] = None
        for value in row:
            ref = value.attrib.get("ColumnRef", "")
            simple = next((g.text.strip() for g in value.iter() if _local(g.tag) == "SimpleValue" and g.text), None)
            if ref == "code":
                code = simple
            elif ref == "nombre" and simple:
                es = simple
            elif ref == "name" and simple:
                en = simple
        if code:
            out[code] = es or en or ""
    return out


_lab_cache: Dict[str, Dict[str, str]] = {}


def label_map(name: str) -> Dict[str, str]:
    """Códigos oficiais de uma lista CODICE (com cache)."""
    if name not in _lab_cache:
        _lab_cache[name] = _load_gc(CODIGOS_DIR / f"{name}.gc")
    return _lab_cache[name]


def _cpv_map() -> Dict[str, str]:
    return label_map("CPV2008-2.04")


# ------------------------------------------------------------------ helpers
def _t(el: Optional[ET.Element]) -> Optional[str]:
    if el is None:
        return None
    txt = (el.text or "").strip()
    return txt or None


def _child(node: Optional[ET.Element], *names: str) -> Optional[ET.Element]:
    """Primeiro descendente direto por nome local, seguindo a cadeia indicada."""
    cur = node
    for name in names:
        if cur is None:
            return None
        cur = next((c for c in cur if _local(c.tag) == name), None)
    return cur


def _find_all(node: Optional[ET.Element], *names: str) -> List[ET.Element]:
    """Todos os elementos que correspondem à cadeia de nomes locais (podem repetir-se)."""
    cur = [node] if node is not None else []
    for name in names:
        nxt: List[ET.Element] = []
        for c in cur:
            if c is not None:
                nxt.extend([ch for ch in c if _local(ch.tag) == name])
        cur = nxt
    return cur


def _txt(node: Optional[ET.Element], *names: str) -> Optional[str]:
    return _t(_child(node, *names))


def _num(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        return float(str(value).replace(",", ".").strip())
    except ValueError:
        return None


def _int(value: Optional[str]) -> Optional[int]:
    n = _num(value)
    return int(n) if n is not None else None


def _date(value: Optional[str]) -> Optional[str]:
    """Normaliza datas do feed (`YYYY-MM-DD`, ISO com fuso, `YYYY/MM/DD HH:MM:SS`)."""
    if not value:
        return None
    txt = value.strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(txt, fmt).isoformat()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(txt.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return None


def _year_of(*dates: Optional[str], fallback: Optional[int] = None) -> Optional[int]:
    """Ano de faceta a partir da primeira data plausível (senão o ano do ZIP).

    A fonte tem gralhas de digitação (ex.: um `IssueDate` = `0018-03-02` em vez de
    2018), por isso um ano fora de [1900, ano corrente + 1] é ignorado em vez de
    poluir a faceta `ano`. A data crua mantém-se no documento (`fecha_publicacion`).
    """
    limite = datetime.now(timezone.utc).year + 1
    for d in dates:
        iso = _date(d)
        if iso and len(iso) >= 4 and iso[:4].isdigit():
            year = int(iso[:4])
            if 1900 <= year <= limite:
                return year
    return fallback


def _doc_id(fonte: str, organo_id: Optional[str], expediente: str) -> str:
    key = f"{fonte}|{organo_id or ''}|{expediente}".encode("utf-8")
    return hashlib.sha1(key).hexdigest()


# ------------------------------------------------------------------ ZIPs
def available_zips(dataset: Optional[str] = None, years: Optional[Iterable[int]] = None) -> List[Tuple[str, int, Path]]:
    """ZIPs disponíveis como (fonte, ano, caminho), sem duplicados `(1)`."""
    wanted = set(years) if years else None
    found: Dict[Tuple[str, int], Path] = {}
    for dataset_key, stem_prefix in DATASETS.items():
        if dataset and dataset_key != dataset:
            continue
        for path in SOURCE_DIR.glob("*.zip"):
            if not path.name.startswith(stem_prefix):
                continue
            match = re.search(r"(\d{4})", path.stem)
            if not match:
                continue
            year = int(match.group(1))
            if wanted and year not in wanted:
                continue
            key = (dataset_key, year)
            # Preferir sempre o ficheiro sem sufixo de cópia ("(1)").
            current = found.get(key)
            if current is None or ("(1)" in current.name and "(1)" not in path.name):
                found[key] = path
    return [(fonte, year, path) for (fonte, year), path in sorted(found.items())]


def iter_entries(zip_path: Path) -> Iterator[ET.Element]:
    """Itera as entradas `<entry>` dos ficheiros `.atom` de um ZIP, por ordem de nome."""
    with zipfile.ZipFile(zip_path) as zf:
        names = sorted(n for n in zf.namelist() if n.lower().endswith(".atom"))
        for name in names:
            with zf.open(name) as fh:
                try:
                    root = ET.parse(fh).getroot()
                except ET.ParseError:
                    continue
                for child in list(root):
                    if _local(child.tag) == "entry":
                        yield child
                root.clear()


def atom_names(zip_path: Path) -> List[str]:
    with zipfile.ZipFile(zip_path) as zf:
        return sorted(n for n in zf.namelist() if n.lower().endswith(".atom"))


# ------------------------------------------------------------------ normalização
def normalize_entry(entry: ET.Element, fonte: str, ano_fonte: int) -> Optional[Dict[str, Any]]:
    """Converte uma entrada Atom do PLACSP num documento normalizado."""
    status_el = next((c for c in entry if _local(c.tag) == "ContractFolderStatus"), None)
    if status_el is None:
        return None

    expediente = _txt(status_el, "ContractFolderID")
    if not expediente:
        return None

    organo_el = _child(status_el, "LocatedContractingParty")
    organo_nome = _txt(organo_el, "Party", "PartyName", "Name") or _txt(organo_el, "Party", "Contact", "Name")
    organo_id = _txt(organo_el, "Party", "PartyIdentification", "ID")
    if not organo_nome:
        return None

    tipo_raw = _txt(status_el, "ProcurementProject", "TypeCode")
    tipo_label = label_map("ContractCode-2.08").get(tipo_raw or "", "")
    estado_raw = _txt(status_el, "ContractFolderStatusCode")
    resultado_raw = _txt(status_el, "TenderResult", "ResultCode")
    proced_raw = _txt(status_el, "TenderingProcess", "ProcedureCode")

    cpv_codes = [
        code
        for el in _find_all(status_el, "ProcurementProject", "RequiredCommodityClassification", "ItemClassificationCode")
        if (code := _t(el))
    ]
    cpv_labels = _cpv_map()
    cpv = [{"code": code, "nombre": cpv_labels.get(code, "")} for code in dict.fromkeys(cpv_codes)]

    localidad = _txt(status_el, "ProcurementProject", "RealizedLocation", "CountrySubentity")
    nuts = _txt(status_el, "ProcurementProject", "RealizedLocation", "CountrySubentityCode")
    duracion = _child(status_el, "ProcurementProject", "PlannedPeriod", "DurationMeasure")

    award_date = _txt(status_el, "TenderResult", "AwardDate")
    contract_issue = _txt(status_el, "TenderResult", "Contract", "IssueDate")
    publication = _txt(
        status_el,
        "ValidNoticeInfo",
        "AdditionalPublicationStatus",
        "AdditionalPublicationDocumentReference",
        "IssueDate",
    )
    updated = _t(next((c for c in entry if _local(c.tag) == "updated"), None))
    deadline = _child(status_el, "TenderingProcess", "TenderSubmissionDeadlinePeriod")

    adjudicatario_nome = _txt(status_el, "TenderResult", "WinningParty", "PartyName", "Name")
    adjudicatario_nif = _txt(status_el, "TenderResult", "WinningParty", "PartyIdentification", "ID")

    linaje = _child(status_el, "TenderingTerms", "Language", "ID")
    ano = _year_of(publication, award_date, contract_issue, updated, fallback=ano_fonte)

    doc: Dict[str, Any] = {
        "fonte": fonte,
        "pais": "ES",
        "ano": ano,
        "ano_fonte": ano_fonte,
        "id_expediente": expediente,
        "estado": estado_raw,
        "estado_label": ESTADO_LABELS.get(estado_raw or "", ""),
        "enlace": next((c.attrib.get("href") for c in entry if _local(c.tag) == "link"), None),
        "organo_id": organo_id,
        "organo_nombre": organo_nome,
        "organo_ciudad": _txt(organo_el, "Party", "PostalAddress", "CityName"),
        "organo_cp": _txt(organo_el, "Party", "PostalAddress", "PostalZone"),
        "organo_web": _txt(organo_el, "Party", "WebsiteURI"),
        "organo_email": _txt(organo_el, "Party", "Contact", "ElectronicMail"),
        "organo_tipo": _txt(organo_el, "ContractingPartyTypeCode"),
        "tipo_contrato": tipo_raw,
        "tipo_contrato_label": tipo_label or "",
        "subtipo_contrato": _txt(status_el, "ProcurementProject", "SubTypeCode"),
        "objeto": _txt(status_el, "ProcurementProject", "Name") or _t(next((c for c in entry if _local(c.tag) == "title"), None)),
        "descripcion": _txt(status_el, "TenderResult", "Description"),
        "cpv": cpv,
        "valor_estimado": _num(_txt(status_el, "ProcurementProject", "BudgetAmount", "EstimatedOverallContractAmount")),
        "valor_presupuesto": _num(_txt(status_el, "ProcurementProject", "BudgetAmount", "TotalAmount")),
        "valor_base": _num(_txt(status_el, "ProcurementProject", "BudgetAmount", "TaxExclusiveAmount")),
        "valor_adjudicado": _num(
            _txt(status_el, "TenderResult", "AwardedTenderedProject", "LegalMonetaryTotal", "TaxExclusiveAmount")
        ),
        "valor_adjudicado_con_iva": _num(
            _txt(status_el, "TenderResult", "AwardedTenderedProject", "LegalMonetaryTotal", "PayableAmount")
        ),
        "moneda": (
            _child(status_el, "ProcurementProject", "BudgetAmount", "EstimatedOverallContractAmount").attrib.get("currencyID")
            if _child(status_el, "ProcurementProject", "BudgetAmount", "EstimatedOverallContractAmount") is not None
            else None
        ),
        "fecha_adjudicacion": _date(award_date or contract_issue),
        "fecha_publicacion": _date(publication),
        "fecha_actualizacion": _date(updated),
        "fecha_limite": _date(_txt(deadline, "EndDate")),
        "hora_limite": _txt(deadline, "EndTime"),
        "resultado": resultado_raw,
        "resultado_label": label_map("TenderResultCode-2.09").get(resultado_raw or "", ""),
        "num_ofertas": _int(_txt(status_el, "TenderResult", "ReceivedTenderQuantity")),
        "adjudicatario_nombre": adjudicatario_nome,
        "adjudicatario_nif": adjudicatario_nif,
        "adjudicatario_nuts": _txt(status_el, "TenderResult", "WinningParty", "PhysicalLocation", "CountrySubentityCode"),
        "adjudicatario_nacionalidad": _txt(status_el, "TenderResult", "AwardedOwnerNationalityCode"),
        "procedimiento": proced_raw,
        "procedimiento_label": label_map("SyndicationTenderingProcessCode-2.07").get(proced_raw or "", ""),
        "urgencia": _txt(status_el, "TenderingProcess", "UrgencyCode"),
        "sistema_contratacion": _txt(status_el, "TenderingProcess", "ContractingSystemCode"),
        "idioma": _t(linaje),
        "localidad": localidad if localidad and localidad.upper() not in {"ESPAÑA", "ESPANA", "ES"} else None,
        "nuts": nuts,
        "duracion_valor": _num(_t(duracion)),
        "duracion_unidad": duracion.attrib.get("unitCode") if duracion is not None else None,
        "num_lotes": len(_find_all(status_el, "ProcurementProjectLot")),
        "documentos": [
            doc_id
            for el in _find_all(status_el, "LegalDocumentReference", "ID") + _find_all(status_el, "TechnicalDocumentReference", "ID")
            if (doc_id := _t(el))
        ],
        "es_menor": fonte == "menores" or proced_raw == "6",
        "ingested_at": datetime.now(timezone.utc).isoformat(),
    }
    doc["doc_id"] = _doc_id(fonte, organo_id, expediente)
    doc["search_text"] = "\n".join(
        filter(
            None,
            [
                doc["objeto"],
                doc["descripcion"],
                doc["organo_nombre"],
                doc["adjudicatario_nombre"],
                expediente,
                ", ".join(f"{c['code']} {c['nombre']}".strip() for c in cpv),
                doc["procedimiento_label"],
                doc["tipo_contrato_label"],
            ],
        )
    )
    return doc


# ------------------------------------------------------------------ JSONL
def meta_path(fonte: str, ano: int) -> Path:
    return PROCESSED_DIR / f"{fonte}_{ano}.meta.json"


def jsonl_path(fonte: str, ano: int) -> Path:
    return PROCESSED_DIR / f"{fonte}_{ano}.jsonl"


def build_jsonl(
    fonte: str,
    ano: int,
    zip_path: Path,
    limit: Optional[int] = None,
    force: bool = False,
    resume: bool = False,
    log_every: int = 25000,
    on_progress: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """Normaliza um ano de uma fonte para JSONL (com retoma por ficheiro .atom).

    `on_progress` é chamado no fim de cada ficheiro `.atom` com as contagens
    correntes (usado pela importação em segundo plano exposta na API/UI).
    """
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out_path = jsonl_path(fonte, ano)
    meta_file = meta_path(fonte, ano)

    meta: Dict[str, Any] = {}
    if resume and meta_file.exists() and out_path.exists() and not force:
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            meta = {}
    done_atoms = set(meta.get("atoms_done", []))
    written = int(meta.get("count", 0)) if done_atoms else 0
    skipped = int(meta.get("skipped", 0)) if done_atoms else 0
    started = time.time()

    names = atom_names(zip_path)
    mode = "a" if done_atoms else "w"
    with open(out_path, mode, encoding="utf-8") as out:
        for name in names:
            if name in done_atoms:
                continue
            if limit and written >= limit:
                break
            for entry in _iter_atom(zip_path, name):
                try:
                    doc = normalize_entry(entry, fonte, ano)
                except Exception:  # noqa: BLE001 — uma entrada má não deve parar o ano
                    skipped += 1
                    continue
                if not doc:
                    skipped += 1
                    continue
                out.write(json.dumps(doc, ensure_ascii=False) + "\n")
                written += 1
                if limit and written >= limit:
                    break
            done_atoms.add(name)
            out.flush()
            progress = {
                "fonte": fonte,
                "ano": ano,
                "zip": str(zip_path),
                "atoms_total": len(names),
                "atoms_done": sorted(done_atoms),
                "count": written,
                "skipped": skipped,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            meta_file.write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8")
            if on_progress:
                on_progress(progress)
            if log_every and written and written % log_every < 500:
                rate = written / max(time.time() - started, 1e-6)
                print(f"  [{fonte} {ano}] {written:,} docs · {rate:,.0f} docs/s", flush=True)

    return {
        "fonte": fonte,
        "ano": ano,
        "jsonl": str(out_path),
        "count": written,
        "skipped": skipped,
        "atoms_done": len(done_atoms),
        "seconds": round(time.time() - started, 1),
    }


def _iter_atom(zip_path: Path, name: str) -> Iterator[ET.Element]:
    with zipfile.ZipFile(zip_path) as zf, zf.open(name) as fh:
        try:
            root = ET.parse(fh).getroot()
        except ET.ParseError:
            return
        for child in list(root):
            if _local(child.tag) == "entry":
                yield child
        root.clear()


def index_jsonl(path: Path, chunk_size: int = 2000, max_records: Optional[int] = None) -> Dict[str, Any]:
    """Indexa um JSONL no índice `contratos_es`."""
    from api.elasticsearch_client import bulk_index_contratos_es_from_jsonl

    return bulk_index_contratos_es_from_jsonl(path, chunk_size=chunk_size, max_records=max_records)


def run(
    datasets: Optional[List[str]] = None,
    years: Optional[List[int]] = None,
    limit: Optional[int] = None,
    force: bool = False,
    resume: bool = False,
    index: bool = False,
    chunk_size: int = 2000,
) -> List[Dict[str, Any]]:
    """Normaliza (e opcionalmente indexa) os ZIPs indicados."""
    results = []
    for fonte, ano, zip_path in available_zips(datasets[0] if datasets and len(datasets) == 1 else None, years):
        if datasets and fonte not in datasets:
            continue
        print(f"[{fonte} {ano}] {zip_path.name}", flush=True)
        info = build_jsonl(fonte, ano, zip_path, limit=limit, force=force, resume=resume)
        print(f"[{fonte} {ano}] jsonl={info['count']:,} docs · {info['seconds']}s", flush=True)
        if index and info["count"]:
            res = index_jsonl(Path(info["jsonl"]), chunk_size=chunk_size)
            info["index"] = res
            print(f"[{fonte} {ano}] ES indexed={res.get('indexed_count')} errors={res.get('errors')}", flush=True)
        results.append(info)
    return results


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Pipeline de contratos públicos de Espanha (PLACSP)")
    parser.add_argument("--datasets", nargs="*", choices=sorted(DATASETS), help="Fontes a processar (omissão: todas)")
    parser.add_argument("--years", nargs="*", type=int, help="Anos a processar")
    parser.add_argument("--limit", type=int, default=None, help="Limite de documentos por ano (amostra)")
    parser.add_argument("--force", action="store_true", help="Reprocessar do zero")
    parser.add_argument("--resume", action="store_true", help="Retomar um JSONL interrompido")
    parser.add_argument("--index", action="store_true", help="Indexar no Elasticsearch após normalizar")
    parser.add_argument("--index-only", action="store_true", help="Indexar JSONLs já existentes (sem renormalizar)")
    parser.add_argument("--jsonl", nargs="*", help="Ficheiros JSONL para --index-only")
    parser.add_argument("--chunk-size", type=int, default=2000, help="Documentos por bulk no Elasticsearch")
    parser.add_argument("--list", action="store_true", help="Listar ZIPs disponíveis")
    args = parser.parse_args(argv)

    if args.list:
        for fonte, ano, path in available_zips(args.datasets[0] if args.datasets and len(args.datasets) == 1 else None, args.years):
            if args.datasets and fonte not in args.datasets:
                continue
            size_mb = path.stat().st_size / 1e6
            print(f"{fonte:<14} {ano}  {size_mb:8.1f} MB  {path.name}")
        return 0

    if args.index_only:
        paths = [Path(p) for p in (args.jsonl or [])] or sorted(PROCESSED_DIR.glob("*.jsonl"))
        for path in paths:
            if not path.exists():
                print(f"ignorado (não existe): {path}")
                continue
            res = index_jsonl(path, chunk_size=args.chunk_size)
            print(f"{path.name}: indexed={res.get('indexed_count')} errors={res.get('errors')} error={res.get('error')}")
        return 0

    run(
        datasets=args.datasets,
        years=args.years,
        limit=args.limit,
        force=args.force,
        resume=args.resume,
        index=args.index,
        chunk_size=args.chunk_size,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
