"""
Recolha incremental de políticos portugueses para o IQ OS Pessoas.
Fontes:
- Parlamento.pt (legislativas 2024/2025 quando estável)
- CNN Portugal 2025
- Público 2024/2025
- Wikipedia individual (páginas de políticos conhecidos / em falta)

Saídas:
- data/politicos_portugal.json
- index finance_people (PT-AR-DEPUTADO:<slug> e PT-WIKIPEDIA-<slug>)
"""
import json
import os
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
OUT_JSON = DATA_DIR / "politicos_portugal.json"

sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
from api.elasticsearch_client import get_es_client, index_people, search_people  # noqa: E402


# ---------------------------------------------------------------------------
# Utilitários
# ---------------------------------------------------------------------------
def slugify(name: str) -> str:
    s = name.lower()
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


def normalize_name(name: str) -> str:
    name = " ".join(name.split())
    return name.title()


def fetch_text(url: str, *, timeout: int = 30, headers: dict | None = None) -> str:
    default = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    if headers:
        default.update(headers)
    try:
        r = httpx.get(url, headers=default, timeout=timeout, follow_redirects=True)
        r.raise_for_status()
        return r.text
    except Exception as exc:
        print(f"[WARN] Falha ao obter {url}: {exc}")
        return ""


# ---------------------------------------------------------------------------
# Wikipedia
# ---------------------------------------------------------------------------
def scrape_wikipedia_politician(url_path: str, *, partido: str | None = None, circulo: str | None = None) -> dict[str, Any] | None:
    """Extrai infobox + primeiro parágrafo de uma página pt.wikipedia.org/wiki/<nome>."""
    if url_path.startswith("http"):
        url = url_path
    else:
        url = f"https://pt.wikipedia.org/wiki/{url_path}"
    html = fetch_text(url, timeout=45)
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")
    title = (soup.title.string if soup.title else "").replace(" – Wikipédia, a enciclopédia livre", "")

    info = soup.find("table", {"class": "infobox"})
    if not info:
        # Sem infobox: usar só primeiro parágrafo
        paras = [p.get_text(strip=True) for p in soup.find_all("p") if p.get_text(strip=True)]
        bio = " ".join(paras[:3])
        name = title.split("(")[0].strip() or url_path.replace("_", " ")
        return {
            "nif": f"PT-WIKIPEDIA-{slugify(name)}",
            "name": normalize_name(name),
            "nome": normalize_name(name),
            "source": url,
            "active": True,
            "tags": ["politica", "assembleia", "politicos-portugal"],
            "biography": bio[:1200],
            "photo_url": "",
            "metadata": {"fonte": "Wikipédia", "partido": partido or "", "circulo_eleitoral": circulo or ""},
        }

    # Imagem
    img = info.find("img")
    photo_url = ""
    if img:
        src = img.get("src", "")
        if src.startswith("//"):
            src = "https:" + src
        # normalizar para tamanho razoável
        photo_url = re.sub(r"/\d+px-", "/250px-", src) if "/thumb/" in src else src

    # Metadados do infobox
    rows = [tr.get_text(" ", strip=True) for tr in info.find_all("tr")]
    def get_field(rows, keys):
        for row in rows:
            for k in keys:
                if row.lower().startswith(k.lower()):
                    return row[len(k):].strip().strip(":").strip()
        return ""

    nome_info = get_field(rows, ["Nome completo", "Nome"])
    nascimento = get_field(rows, ["Nascimento"])
    profissao = get_field(rows, ["Profissão", "Ocupação", "Trabalho"])
    partido_info = get_field(rows, ["Partido"])
    mandatos = get_field(rows, ["Mandatos", "Deputad"])

    # Primeiros parágrafos como biografia
    paras = [p.get_text(strip=True) for p in soup.find_all("p") if p.get_text(strip=True)]
    bio = " ".join(paras[:4])

    name = normalize_name(nome_info or title.split("(")[0].strip() or url_path.replace("_", " "))
    return {
        "nif": f"PT-WIKIPEDIA-{slugify(name)}",
        "name": name,
        "nome": name,
        "source": url,
        "active": True,
        "tags": ["politica", "assembleia", "politicos-portugal"],
        "biography": bio[:2000],
        "photo_url": photo_url,
        "metadata": {
            "fonte": "Wikipédia",
            "data_nascimento": nascimento,
            "profissao": profissao,
            "partido": partido_info or partido or "",
            "mandatos": mandatos,
            "circulo_eleitoral": circulo or "",
        },
    }


# ---------------------------------------------------------------------------
# Consolidar fontes já existentes
# ---------------------------------------------------------------------------
def load_existing_source_json(path: Path, source_label: str) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def build_base_from_existing() -> dict[str, dict[str, Any]]:
    """Lê _deputados_consolidado.json ou recria a partir das fontes disponíveis."""
    consolidated_path = ROOT / "_deputados_consolidado.json"
    if consolidated_path.exists():
        raw = json.loads(consolidated_path.read_text(encoding="utf-8"))
        return {d["nif"]: d for d in raw}

    # fallback: recria a partir das listas CNN/Público se existirem
    by_key: dict[str, dict[str, Any]] = {}
    def merge(doc: dict[str, Any]):
        key = doc.get("nif") or slugify(doc.get("name", ""))
        if key in by_key:
            old = by_key[key]
            # guardar múltiplas fontes
            sources = set(old.get("sources", []) + [old.get("source", "")] + [doc.get("source", "")])
            old["sources"] = sorted(s for s in sources if s)
            # preferir nome mais longo (menos truncado)
            if len(doc.get("name", "")) > len(old.get("name", "")):
                old["name"] = doc["name"]
                old["nome"] = doc.get("nome", doc["name"])
            # fundir metadata
            for k, v in doc.get("metadata", {}).items():
                if v and not old.get("metadata", {}).get(k):
                    old.setdefault("metadata", {})[k] = v
        else:
            doc["sources"] = [doc.get("source", "")]
            by_key[key] = doc

    cnn = load_existing_source_json(ROOT / "_cnn_deputados.json", "cnnportugal")
    for d in cnn:
        nome = normalize_name(d.get("nome", ""))
        partido = d.get("partido", "")
        circulo = d.get("distrito", "")
        merge({
            "nif": f"PT-AR-DEPUTADO:{slugify(nome)}",
            "name": nome,
            "nome": nome,
            "source": "cnnportugal",
            "active": True,
            "tags": ["deputados", "politica", "assembleia", "politicos-portugal"],
            "metadata": {"partido": partido, "circulo_eleitoral": circulo, "fonte": "CNN Portugal 2025"},
        })

    publico = load_existing_source_json(ROOT / "_publico_deputados.json", "publico")
    for d in publico:
        meta = d.get("metadata", {})
        nome = normalize_name(meta.get("nome", d.get("name", "")))
        partido = meta.get("partido", "")
        circulo = meta.get("circulo", meta.get("circulo_eleitoral", ""))
        numero = meta.get("numero", "")
        nif = d.get("nif", f"PT-AR-DEPUTADO:{slugify(nome)}")
        merge({
            "nif": nif,
            "name": nome,
            "nome": nome,
            "source": "publico",
            "active": True,
            "tags": ["deputados", "politica", "assembleia", "politicos-portugal"],
            "metadata": {
                "partido": partido,
                "circulo_eleitoral": circulo,
                "numero": numero,
                "data_nascimento": meta.get("data_nascimento", ""),
                "idade": meta.get("idade", ""),
                "profissao": meta.get("profissao", ""),
                "fonte": meta.get("fonte", "Público"),
            },
        })
    return by_key


# ---------------------------------------------------------------------------
# Políticos em falta / destaque
# ---------------------------------------------------------------------------
MISSING_WIKI_PAGES = [
    # Nome da página, partido, circulo (quando conhecido)
    ("Catarina_Martins", "BE", "Lisboa"),
    ("Mariana_Mortágua", "BE", "Lisboa"),
    ("Marisa_Matias", "BE", "Porto"),
    ("Jerónimo_de_Sousa", "PCP", "Lisboa"),
    ("Paulo_Rangel", "PSD", "Lisboa"),
    ("Luís_Montenegro", "PSD", "Lisboa"),
    ("Pedro_Nuno_Santos", "PS", "Aveiro"),
    ("André_Ventura", "Chega", "Lisboa"),
    ("Rui_Rocha", "IL", "Lisboa"),
    ("Filipe_Semedo", "PAN", "Lisboa"),
    ("Inês_Sousa_Real", "PAN", "Lisboa"),
]


def enrich_missing(by_nif: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    for page, partido, circulo in MISSING_WIKI_PAGES:
        doc = scrape_wikipedia_politician(page, partido=partido, circulo=circulo)
        if not doc:
            continue
        key = doc["nif"]
        # Se já existe deputado com mesmo nome, fundir Wikipedia como fonte extra
        existing_key = None
        for k, v in by_nif.items():
            if slugify(v.get("nome", "")) == slugify(doc["nome"]):
                existing_key = k
                break
        if existing_key:
            v = by_nif[existing_key]
            v["sources"] = sorted(set(v.get("sources", []) + [doc["source"]]))
            if doc.get("photo_url") and not v.get("photo_url"):
                v["photo_url"] = doc["photo_url"]
            if doc.get("biography") and not v.get("biography"):
                v["biography"] = doc["biography"]
            for k2, val in doc.get("metadata", {}).items():
                if val and not v.get("metadata", {}).get(k2):
                    v.setdefault("metadata", {})[k2] = val
            print(f"[INFO] Wikipedia enriqueceu {existing_key}")
        else:
            by_nif[key] = doc
            print(f"[INFO] Wikipedia adicionou {key}")
    return by_nif


# ---------------------------------------------------------------------------
# Indexação
# ---------------------------------------------------------------------------
def save_json(docs: list[dict[str, Any]]):
    OUT_JSON.write_text(json.dumps(docs, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] {OUT_JSON}: {len(docs)} docs")


def normalize_tags(tags: list[str] | None) -> list[str]:
    base = list(tags or ["politica", "assembleia"])
    if "politicos-portugal" not in base:
        base.append("politicos-portugal")
    # garantir presença dos tags semânticos mínimos
    for t in ("politica", "assembleia"):
        if t not in base:
            base.append(t)
    return base


def index_docs(docs: list[dict[str, Any]]):
    # garante campo nome/name preenchido e aplica tag distintiva a todos
    for d in docs:
        d["name"] = d.get("name") or d.get("nome", "")
        d["nome"] = d.get("nome") or d["name"]
        d.setdefault("active", True)
        d["tags"] = normalize_tags(d.get("tags"))
    resp = index_people(docs)
    print(f"[ES] indexed={resp.get('indexed_count')} total={resp.get('total')} errors={resp.get('errors')}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("[START] Recolha políticos Portugal")
    base = build_base_from_existing()
    print(f"[BASE] {len(base)} docs das fontes existentes")
    base = enrich_missing(base)
    print(f"[AFTER WIKI] {len(base)} docs")
    docs = list(base.values())
    save_json(docs)
    index_docs(docs)
    print("[DONE]")


if __name__ == "__main__":
    main()
