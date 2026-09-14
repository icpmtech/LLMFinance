"""Pipeline de ingestão de contratos públicos do portal base (ZIP -> JSONL -> ES)."""
import json
import os
import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_DIR = ROOT / "data" / "contratos-gov-portal-base"
PROCESSED_DIR = ROOT / "data" / "processed" / "contratos"
FINAL_DIR = ROOT / "data" / "final"


def _parse_date(value: Any) -> Optional[str]:
    if not value or not isinstance(value, str):
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(value.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v).strip() for v in value if v is not None)
    return str(value).strip()


def _extract_nif_entity(text: str) -> List[Dict[str, str]]:
    out = []
    if not text:
        return out
    for m in re.finditer(r"(\d{9})\s*-\s*([^,]+)", text):
        out.append({"nif": m.group(1), "nome": m.group(2).strip()})
    return out


def _clean_cpv(value: Any) -> List[Dict[str, str]]:
    out = []
    for entry in _to_list(value):
        entry = entry.strip()
        if not entry:
            continue
        m = re.match(r"(\d{8}-\d)\s*-\s*(.+)", entry)
        if m:
            out.append({"code": m.group(1), "description": m.group(2).strip()})
        else:
            out.append({"code": "", "description": entry})
    return out


def _to_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)]


def _safe_id(value: Any) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", str(value))[:80]


def normalize_contract(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Converte um registo bruto do portal base num documento normalizado."""
    adjudicantes = _to_list(raw.get("adjudicante"))
    adjudicatarios = _to_list(raw.get("adjudicatarios"))

    doc: Dict[str, Any] = {
        "idcontrato": str(raw.get("idcontrato", "")).strip(),
        "nAnuncio": _normalize_text(raw.get("nAnuncio")),
        "TipoAnuncio": _normalize_text(raw.get("TipoAnuncio")),
        "idINCM": _normalize_text(raw.get("idINCM")),
        "tipoContrato": _to_list(raw.get("tipoContrato")),
        "idprocedimento": _normalize_text(raw.get("idprocedimento")),
        "tipoprocedimento": _normalize_text(raw.get("tipoprocedimento")),
        "objectoContrato": _normalize_text(raw.get("objectoContrato")),
        "descContrato": _normalize_text(raw.get("descContrato")),
        "adjudicantes": {
            "raw": adjudicantes,
            "parsed": [e for t in adjudicantes for e in _extract_nif_entity(t)],
        },
        "adjudicatarios": {
            "raw": adjudicatarios,
            "parsed": [e for t in adjudicatarios for e in _extract_nif_entity(t)],
        },
        "dataPublicacao": _parse_date(raw.get("dataPublicacao")),
        "dataCelebracaoContrato": _parse_date(raw.get("dataCelebracaoContrato")),
        "precoContratual": _as_float(raw.get("precoContratual")),
        "cpv": _clean_cpv(raw.get("cpv")),
        "prazoExecucao": _as_float(raw.get("prazoExecucao")),
        "localExecucao": _to_list(raw.get("localExecucao")),
        "fundamentacao": _normalize_text(raw.get("fundamentacao")),
        "ProcedimentoCentralizado": _normalize_text(raw.get("ProcedimentoCentralizado")),
        "numAcordoQuadro": _normalize_text(raw.get("numAcordoQuadro")),
        "DescrAcordoQuadro": _normalize_text(raw.get("DescrAcordoQuadro")),
        "precoBaseProcedimento": _as_float(raw.get("precoBaseProcedimento")),
        "dataDecisaoAdjudicacao": _parse_date(raw.get("dataDecisaoAdjudicacao")),
        "dataFechoContrato": _parse_date(raw.get("dataFechoContrato")),
        "PrecoTotalEfetivo": _as_float(raw.get("PrecoTotalEfetivo")),
        "regime": _normalize_text(raw.get("regime")),
        "justifNReducEscrContrato": _normalize_text(raw.get("justifNReducEscrContrato")),
        "tipoFimContrato": _normalize_text(raw.get("tipoFimContrato")),
        "CritMateriais": _normalize_text(raw.get("CritMateriais")),
        "concorrentes": _normalize_text(raw.get("concorrentes")),
        "linkPecasProc": _normalize_text(raw.get("linkPecasProc")),
        "Observacoes": _normalize_text(raw.get("Observacoes")),
        "ContratEcologico": _normalize_text(raw.get("ContratEcologico")),
        "Ano": int(raw.get("Ano", 0)) if raw.get("Ano") else None,
        "fundamentAjusteDireto": _normalize_text(raw.get("fundamentAjusteDireto")),
        "adjudicatarioPMEs": _normalize_text(raw.get("adjudicatarioPMEs")),
        "NUTs": _to_list(raw.get("NUTs")),
        "Lotes": _normalize_text(raw.get("Lotes")),
        "TipoCriterioAdjudicacao": _normalize_text(raw.get("TipoCriterioAdjudicacao")),
        "ingested_at": datetime.utcnow().isoformat(),
    }

    # Campos de texto completo para search
    doc["search_text"] = "\n".join(
        [
            doc["objectoContrato"],
            doc["descContrato"],
            doc["tipoprocedimento"],
            doc["regime"],
            ", ".join(doc["tipoContrato"]),
            ", ".join(adjudicantes),
            ", ".join(adjudicatarios),
            " ".join(c["description"] for c in doc["cpv"]),
            " ".join(doc["localExecucao"]),
            doc["Observacoes"],
        ]
    )

    # Entidades extraídas para nested queries
    entities: List[Dict[str, str]] = []
    for a in doc["adjudicantes"]["parsed"]:
        entities.append({"name": a["nome"], "type": "adjudicante", "nif": a["nif"]})
    for a in doc["adjudicatarios"]["parsed"]:
        entities.append({"name": a["nome"], "type": "adjudicatario", "nif": a["nif"]})
    for c in doc["cpv"]:
        if c["description"]:
            entities.append({"name": c["description"], "type": "cpv", "code": c["code"]})
    doc["entities"] = entities

    return doc


def extract_zip_jsonl(zip_path: Path, dest_dir: Path, force: bool = False) -> Optional[Path]:
    """Extrai o JSON do ZIP para um ficheiro .json no disco."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    year_match = re.search(r"(\d{4})", zip_path.stem)
    year = year_match.group(1) if year_match else zip_path.stem
    json_path = dest_dir / f"Contratos{year}.json"
    if json_path.exists() and not force:
        return json_path

    with zipfile.ZipFile(zip_path, "r") as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(".json")]
        if not names:
            raise ValueError(f"Nenhum ficheiro JSON encontrado em {zip_path}")
        with zf.open(names[0]) as src, open(json_path, "wb") as dst:
            dst.write(src.read())
    return json_path


def iter_contracts(json_path: Path) -> Iterable[Dict[str, Any]]:
    """Itera contratos de um ficheiro JSON (lista ou objecto com 'contratos')."""
    with open(json_path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, list):
        yield from data
    elif isinstance(data, dict):
        yield from data.get("contratos", []) or data.get("data", []) or []
    else:
        raise ValueError(f"Formato inesperado em {json_path}: {type(data)}")


def normalize_year_to_jsonl(year: int, force: bool = False, limit: Optional[int] = None) -> Dict[str, Any]:
    """Processa um ano de contratos: extrai, normaliza e guarda JSONL."""
    zip_path = CONTRACTS_DIR / f"contratos{year}.zip"
    if not zip_path.exists():
        return {"year": year, "error": f"ZIP não encontrado: {zip_path}"}

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    json_path = extract_zip_jsonl(zip_path, PROCESSED_DIR / "raw", force=force)
    jsonl_path = PROCESSED_DIR / f"contratos_{year}.jsonl"

    if jsonl_path.exists() and not force:
        count = sum(1 for _ in open(jsonl_path, "r", encoding="utf-8"))
        return {"year": year, "jsonl": str(jsonl_path), "count": count, "message": "JSONL já existia"}

    written = 0
    errors = 0
    with open(jsonl_path, "w", encoding="utf-8") as out:
        for raw in iter_contracts(json_path):
            try:
                doc = normalize_contract(raw)
                out.write(json.dumps(doc, ensure_ascii=False) + "\n")
                written += 1
                if limit and written >= limit:
                    break
            except Exception:
                errors += 1
    return {"year": year, "jsonl": str(jsonl_path), "count": written, "errors": errors}


def normalize_all_years(years: Optional[List[int]] = None, force: bool = False, limit_per_year: Optional[int] = None) -> List[Dict[str, Any]]:
    """Processa todos os anos disponíveis (ou os especificados)."""
    if years is None:
        years = sorted(
            int(m.group(1))
            for p in CONTRACTS_DIR.glob("contratos*.zip")
            if (m := re.search(r"(\d{4})", p.stem))
        )
    return [normalize_year_to_jsonl(y, force=force, limit=limit_per_year) for y in years]


def build_training_corpus(years: Optional[List[int]] = None, output: Optional[Path] = None, max_records: Optional[int] = None) -> Path:
    """Gera ficheiro de treino a partir dos contratos normalizados."""
    output = output or FINAL_DIR / "contratos_train.jsonl"
    output.parent.mkdir(parents=True, exist_ok=True)

    if years is None:
        files = sorted(PROCESSED_DIR.glob("contratos_*.jsonl"))
    else:
        files = [PROCESSED_DIR / f"contratos_{y}.jsonl" for y in years]

    count = 0
    with open(output, "w", encoding="utf-8") as out:
        for path in files:
            if not path.exists():
                continue
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    doc = json.loads(line)
                    # Formato instrução simples para fine-tuning
                    prompt = (
                        f"Contrato {doc.get('idcontrato')} - {doc.get('objectoContrato')}\n"
                        f"Adjudicante: {', '.join(doc.get('adjudicantes', {}).get('raw', []))}\n"
                        f"Adjudicatário: {', '.join(doc.get('adjudicatarios', {}).get('raw', []))}\n"
                        f"Tipo: {', '.join(doc.get('tipoContrato', []))}\n"
                        f"Procedimento: {doc.get('tipoprocedimento')}\n"
                        f"Preço contratual: {doc.get('precoContratual')}\n"
                        f"Descrição: {doc.get('descContrato')}"
                    )
                    completion = (
                        f"Este contrato, publicado a {doc.get('dataPublicacao')} e com regime "
                        f"{doc.get('regime')}, envolve {doc.get('objectoContrato')} entre "
                        f"{', '.join(doc.get('adjudicantes', {}).get('raw', []))} e "
                        f"{', '.join(doc.get('adjudicatarios', {}).get('raw', []))}. "
                        f"O valor contratual foi {doc.get('precoContratual')}€ e o CPV principal é "
                        f"{doc.get('cpv')[0]['description'] if doc.get('cpv') else 'não especificado'}."
                    )
                    out.write(
                        json.dumps(
                            {
                                "instruction": "Descreve este contrato público português.",
                                "input": prompt,
                                "output": completion,
                                "metadata": {
                                    "idcontrato": doc.get("idcontrato"),
                                    "ano": doc.get("Ano"),
                                    "tipoContrato": doc.get("tipoContrato"),
                                },
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                    count += 1
                    if max_records and count >= max_records:
                        break
            if max_records and count >= max_records:
                break
    return output


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Pipeline de contratos públicos")
    parser.add_argument("--years", nargs="*", type=int, help="Anos a processar")
    parser.add_argument("--force", action="store_true", help="Reprocessar mesmo que exista")
    parser.add_argument("--limit", type=int, default=None, help="Limite de registos por ano")
    parser.add_argument("--train-corpus", action="store_true", help="Gerar corpus de treino")
    args = parser.parse_args()

    results = normalize_all_years(years=args.years, force=args.force, limit_per_year=args.limit)
    for r in results:
        print(r)

    if args.train_corpus:
        out = build_training_corpus()
        print("Corpus de treino:", out)
