"""Scraper e normalizador do **EU Taxonomy Navigator**.

Recolhe os dados oficiais da Comissão Europeia (DG FISMA) a partir das APIs
públicas do *EU Taxonomy Navigator*:

- https://webgate.ec.europa.eu/sft/api/v1/en/activities/matches
- https://webgate.ec.europa.eu/sft/api/v1/en/objectives
- https://webgate.ec.europa.eu/sft/api/v1/en/sectors

Os dados são normalizados em documentos prontos a indexar no Elasticsearch,
com texto original (EN) e tradução para português (quando disponível). A
cache local em `data/eu_taxonomy_raw/` evita downloads repetidos.

Última sincronização: 2026-10-21.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "eu_taxonomy_raw"
CACHE_DIR = ROOT / "data" / "eu_taxonomy_cache"
SNAPSHOT_PATH = ROOT / "data" / "eu_taxonomy.json"

URL_ACTIVITIES = "https://webgate.ec.europa.eu/sft/api/v1/en/activities/matches"
URL_OBJECTIVES = "https://webgate.ec.europa.eu/sft/api/v1/en/objectives"
URL_SECTORS = "https://webgate.ec.europa.eu/sft/api/v1/en/sectors"
ACTIVITY_VIEW_URL = "https://ec.europa.eu/sustainable-finance-taxonomy/activities/activity/{id}/view"

_translate_cache: Optional[Dict[str, str]] = None
_translate_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _http_get_json(url: str) -> Any:
    import urllib.request

    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _ensure_dirs() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def fetch_raw(force: bool = False) -> Dict[str, Any]:
    """Faz download dos ficheiros raw da API oficial (com cache local)."""
    _ensure_dirs()
    paths = {
        "activities": RAW_DIR / "activities.json",
        "objectives": RAW_DIR / "objectives.json",
        "sectors": RAW_DIR / "sectors.json",
    }
    urls = {
        "activities": URL_ACTIVITIES,
        "objectives": URL_OBJECTIVES,
        "sectors": URL_SECTORS,
    }
    result: Dict[str, Any] = {}
    for key, path in paths.items():
        if not force and path.exists():
            logger.info("EU Taxonomy: a usar cache local de %s", path.name)
            result[key] = json.loads(path.read_text(encoding="utf-8"))
            continue
        try:
            data = _http_get_json(urls[key])
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            result[key] = data
            logger.info("EU Taxonomy: descarregado %s (%d itens)", key, len(data))
        except Exception as exc:
            logger.warning("EU Taxonomy: falha a descarregar %s: %s", key, exc)
            if path.exists():
                result[key] = json.loads(path.read_text(encoding="utf-8"))
            else:
                result[key] = []
    result["synced_at"] = _now()
    return result


def _html_to_text(html: Optional[str]) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all("sup"):
        tag.decompose()
    text = soup.get_text(separator=" ")
    text = re.sub(r"\s+", " ", text).strip()
    # Normaliza as aspas curvas que o BeautifulSoup pode deixar mal
    text = text.replace("\u2018", "'").replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"')
    return text


def _nace_codes(nace_codes: List[str]) -> List[str]:
    return [str(c).strip().upper() for c in (nace_codes or []) if str(c).strip()]


def _contribuicao_pt(tipo: Optional[str]) -> str:
    mapping = {
        "Enabling": "Atividade facilitadora",
        "Transitional": "Atividade transicional",
        "Contribui significativamente": "Contribui significativamente",
    }
    return mapping.get(str(tipo or ""), str(tipo or ""))


def _objective_label_pt(name: Optional[str], short: Optional[str]) -> Tuple[str, str]:
    mapping: Dict[str, Tuple[str, str]] = {
        "Climate change mitigation": ("Mitigação das alterações climáticas", "Clima (mitigação)"),
        "Climate change adaptation": ("Adaptação às alterações climáticas", "Clima (adaptação)"),
        "Sustainable use and protection of water and marine resources": (
            "Utilização sustentável e proteção dos recursos hídricos e marinhos",
            "Água e mares",
        ),
        "Transition to a circular economy": ("Transição para uma economia circular", "Economia circular"),
        "Pollution prevention and control": ("Prevenção e controlo da poluição", "Poluição"),
        "Protection and restoration of biodiversity and ecosystems": (
            "Proteção e restauro da biodiversidade e dos ecossistemas",
            "Biodiversidade",
        ),
    }
    return mapping.get(str(name or ""), (str(name or ""), str(short or "")))


def _sector_pt(name: str) -> str:
    mapping = {
        "Accommodation activities": "Alojamento",
        "Arts, entertainment and recreation": "Artes, entretenimento e recreação",
        "Construction and real estate activities": "Construção e atividades imobiliárias",
        "Disaster risk management": "Gestão do risco de catástrofes",
        "Education": "Educação",
        "Energy": "Energia",
        "Environmental protection and restoration activities": "Proteção e restauro ambiental",
        "Financial and insurance activities": "Atividades financeiras e de seguros",
        "Forestry": "Silvicultura",
        "Human health and social work activities": "Saúde humana e atividades de apoio social",
        "Information and communication": "Informação e comunicação",
        "Manufacturing": "Indústria transformadora",
        "Professional, scientific and technical activities": "Atividades profissionais, científicas e técnicas",
        "Services": "Serviços",
        "Transport": "Transportes",
        "Water supply, sewerage, waste management and remediation": (
            "Abastecimento de água, saneamento, gestão de resíduos e reabilitação"
        ),
    }
    return mapping.get(name, name)


def build_activities(raw: Dict[str, Any], translate: bool = True) -> List[Dict[str, Any]]:
    """Normaliza a lista de atividades do Compass com campos EN e PT."""
    activities = raw.get("activities") or []
    objectives = raw.get("objectives") or []
    obj_by_id = {int(o["id"]): o for o in objectives}

    docs: List[Dict[str, Any]] = []
    for activity in activities:
        act_id = int(activity.get("id") or 0)
        name_en = str(activity.get("name") or "").strip()
        sector_en = activity.get("sector", {}).get("name") or ""
        sector_id = activity.get("sector", {}).get("id")
        description_en = _html_to_text(activity.get("description"))
        nace = _nace_codes(activity.get("naceCodes") or [])

        matches: List[Dict[str, Any]] = []
        for m in activity.get("matches") or []:
            obj = m.get("objective") or {}
            obj_id = int(obj.get("id") or 0)
            name_obj_en = obj.get("name") or ""
            short_obj_en = obj.get("shortName") or ""
            label_pt, curto_pt = _objective_label_pt(name_obj_en, short_obj_en)
            matches.append(
                {
                    "objective_id": obj_id,
                    "objective_name_en": name_obj_en,
                    "objective_short_en": short_obj_en,
                    "objective_name_pt": label_pt,
                    "objective_short_pt": curto_pt,
                    "contribution_type_en": m.get("activityContributionType") or "Substantial contribution",
                    "contribution_type_pt": _contribuicao_pt(m.get("activityContributionType")),
                }
            )

        doc: Dict[str, Any] = {
            "kind": "activity",
            "activity_id": act_id,
            "name_en": name_en,
            "name_pt": None,
            "sector_id": sector_id,
            "sector_en": sector_en,
            "sector_pt": _sector_pt(sector_en),
            "description_en": description_en,
            "description_pt": None,
            "nace_codes": nace,
            "objectives": matches,
            "url": ACTIVITY_VIEW_URL.format(id=act_id),
            "synced_at": raw.get("synced_at") or _now(),
        }
        docs.append(doc)

    if translate:
        docs = translate_docs(docs)
    return docs


def build_objectives(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Normaliza os objetivos ambientais com campos EN e PT."""
    objectives = raw.get("objectives") or []
    cores = {
        41: "#34d399",
        42: "#38bdf8",
        43: "#22d3ee",
        44: "#a78bfa",
        45: "#fbbf24",
        46: "#fb7185",
    }
    docs: List[Dict[str, Any]] = []
    for obj in objectives:
        obj_id = int(obj.get("id") or 0)
        name_en = str(obj.get("name") or "").strip()
        short_en = str(obj.get("shortName") or "").strip()
        label_pt, curto_pt = _objective_label_pt(name_en, short_en)
        docs.append(
            {
                "kind": "objective",
                "objective_id": obj_id,
                "name_en": name_en,
                "name_pt": label_pt,
                "short_en": short_en,
                "short_pt": curto_pt,
                "color": cores.get(obj_id, "#94a3b8"),
                "synced_at": raw.get("synced_at") or _now(),
            }
        )
    return docs


def build_sectors(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Normaliza os setores do Compass com campos EN e PT."""
    sectors = raw.get("sectors") or []
    docs: List[Dict[str, Any]] = []
    for sector in sectors:
        name_en = str(sector.get("name") or "").strip()
        docs.append(
            {
                "kind": "sector",
                "sector_id": sector.get("id"),
                "name_en": name_en,
                "name_pt": _sector_pt(name_en),
                "synced_at": raw.get("synced_at") or _now(),
            }
        )
    return docs


def build_snapshot(raw: Dict[str, Any], translate: bool = True) -> Dict[str, Any]:
    """Cria o snapshot normalizado (atividades + objetivos + setores)."""
    activities = build_activities(raw, translate=translate)
    objectives = build_objectives(raw)
    sectors = build_sectors(raw)
    return {
        "source": {
            "id": "eu_taxonomy_navigator",
            "label": "EU Taxonomy Navigator — Comissão Europeia",
            "url": "https://ec.europa.eu/sustainable-finance-taxonomy/home",
            "api": "https://webgate.ec.europa.eu/sft/api/v1/en",
            "synced_at": raw.get("synced_at") or _now(),
            "aviso": (
                "A lista serve para elegibilidade indicativa. O alinhamento exige critérios técnicos, "
                "DNSH e salvaguardas mínimas documentados."
            ),
        },
        "total_activities": len(activities),
        "total_objectives": len(objectives),
        "total_sectors": len(sectors),
        "activities": activities,
        "objectives": objectives,
        "sectors": sectors,
    }


# ---------------------------------------------------------------------------
# Tradução PT via IA (mesmo padrão de contratos_fr_translate.py)
# ---------------------------------------------------------------------------

def _load_translate_cache() -> Dict[str, str]:
    global _translate_cache
    if _translate_cache is not None:
        return _translate_cache
    cache_path = CACHE_DIR / "traducao-pt.json"
    try:
        if cache_path.is_file():
            dados = json.loads(cache_path.read_text(encoding="utf-8"))
            _translate_cache = {str(k): str(v) for k, v in dados.items()} if isinstance(dados, dict) else {}
        else:
            _translate_cache = {}
    except Exception as exc:
        logger.warning("Cache de tradução da taxonomia ilegível (%s); a recomeçar.", exc)
        _translate_cache = {}
    return _translate_cache


def _save_translate_cache() -> None:
    if _translate_cache is None:
        return
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_path = CACHE_DIR / "traducao-pt.json"
        temporario = cache_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
        temporario.write_text(json.dumps(_translate_cache, ensure_ascii=False, indent=0), encoding="utf-8")
        temporario.replace(cache_path)
    except Exception as exc:
        logger.warning("Não foi possível gravar a cache de tradução da taxonomia: %s", exc)


def _normalizar(texto: str) -> str:
    return re.sub(r"\s+", " ", (texto or "")).strip()


#: O modelo EN→PT mistura grafias do Brasil e de Portugal. Estas substituições
#: deixam o texto na norma portuguesa sem lhe mexer no sentido.
_PT_PT: Tuple[Tuple[str, str], ...] = (
    (r"\beconômic", "económic"),
    (r"\bEconômic", "Económic"),
    (r"\bcoleta\b", "recolha"),
    (r"\bcoletar\b", "recolher"),
    (r"\bcoletas\b", "recolhas"),
    (r"\bplantio\b", "plantação"),
    (r"\bsemeadura\b", "sementeira"),
    (r"\bgerenciamento\b", "gestão"),
    (r"\bcaminhão\b", "camião"),
    (r"\bcaminhões\b", "camiões"),
    (r"\bônibus\b", "autocarros"),
    (r"\bestoque\b", "inventário"),
    (r"\bregistro\b", "registo"),
    (r"\bregistros\b", "registos"),
    (r"\bcontrole\b", "controlo"),
    (r"\bcontroles\b", "controlos"),
    (r"\bfrota\b", "frota"),
    (r"\bumidade\b", "humidade"),
    (r"\businas\b", "centrais"),
    (r"\busina\b", "central"),
)

#: Números «isolados» (não a parte numérica de códigos como `A2` ou `C25.99`,
#: que são códigos NACE e não referências a confirmar).
_NUMERO = re.compile(r"(?<![A-Za-z0-9])(\d+(?:[.,]\d+)*)(?![A-Za-z0-9])")


def _normalizar_pt(texto: str) -> str:
    """Aproxima a tradução da norma portuguesa (evita grafias do Brasil)."""
    resultado = texto or ""
    for padrao, substituto in _PT_PT:
        resultado = re.sub(padrao, substituto, resultado)
    return _normalizar(resultado)


def _numeros_em_falta(origem: str, traducao: str) -> List[str]:
    """Números do original que desapareceram da tradução (fidelidade legal).

    O modelo pode trocar algarismos em referências («Regulamento (CE) n.º
    1893/2006»); não se corrige o texto à força, mas o desvio fica registado
    e é visível no aviso do módulo.
    """
    origem_nums = [n.strip(".,") for n in _NUMERO.findall(origem or "")]
    traducao_nums = {n.strip(".,") for n in _NUMERO.findall(traducao or "")}
    return [n for n in origem_nums if n and n not in traducao_nums]


#: Modelo local de tradução EN→PT (o mesmo usado pelo módulo de notícias).
#: Não depende de chaves nem de créditos: traduz na própria máquina.
TRADUCAO_MODELO = "Helsinki-NLP/opus-mt-tc-big-en-pt"

#: Quantos textos vão em cada passagem pelo modelo (o lote amortiza o custo: um
#: lote de 16 textos do mesmo tamanho gera em paralelo, sem somar passagens).
BATCH_SIZE = 16

#: Limite de caracteres por pedaço de descrição. O modelo trunca a 512 tokens
#: (~1 500–2 000 caracteres); dividir em pedaços garante que nada se perde.
CHUNK_CHARS = 1500


def _chunk_text(texto: str, limite: int = CHUNK_CHARS) -> List[str]:
    """Divide um texto em pedaços por frase, sem cortar palavras."""
    texto = _normalizar(texto)
    if not texto:
        return []
    if len(texto) <= limite:
        return [texto]
    frases = re.split(r"(?<=[.!?;:])\s+", texto)
    pedacos: List[str] = []
    atual = ""
    for frase in frases:
        if not frase:
            continue
        if atual and len(atual) + 1 + len(frase) > limite:
            pedacos.append(atual)
            atual = frase
        else:
            atual = f"{atual} {frase}".strip() if atual else frase
        # Uma «frase» maior do que o limite é cortada em blocos de palavras.
        while len(atual) > limite:
            corte = atual.rfind(" ", 0, limite)
            if corte <= 0:
                corte = limite
            pedacos.append(atual[:corte].strip())
            atual = atual[corte:].strip()
    if atual:
        pedacos.append(atual)
    return [p for p in pedacos if p]


def _modelo_pronto() -> Any:
    """Garante o modelo carregado (a primeira chamada descarrega os pesos)."""
    from api.news_nlp import _TranslationModel as modelo

    if modelo._instance is None or modelo._tokenizer is None:
        modelo.translate("inicialização")
    return modelo


def _traduzir_lote(textos: List[str]) -> List[str]:
    """Traduz um lote de textos numa só passagem pelo modelo local.

    O `max_new_tokens` acompanha o tamanho do lote: gerar até 512 tokens quando
    a entrada tem 60 desperdiça tempo (a geração é autoregressiva e só termina
    quando todas as sequências do lote chegam ao fim).
    """
    if not textos:
        return []
    modelo = _modelo_pronto()
    with modelo._lock:
        tokens = modelo._tokenizer(
            textos, return_tensors="pt", padding=True, truncation=True, max_length=512
        )
        entrada = int(tokens["input_ids"].shape[1])
        maximo = min(512, max(64, int(entrada * 2.2) + 24))
        saida = modelo._instance.generate(
            **tokens,
            max_length=maximo,
            num_beams=1,
            no_repeat_ngram_size=0,
        )
        return modelo._tokenizer.batch_decode(saida, skip_special_tokens=True)


#: Abaixo desta razão entre o texto traduzido e o original considera-se que a
#: tradução ficou cortada (o modelo tem um teto de tokens por pedaço).
LIMIAR_TRUNCADO = 0.55

#: Pedaços mais pequenos usados na segunda passagem, para o texto completo caber
#: dentro do teto do modelo sem cortes.
CHUNK_CHARS_FINO = 900


def _completar_truncados(
    docs: List[Dict[str, Any]],
    cache: Dict[str, str],
    *,
    progress: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    """Traduz de novo, em pedaços mais pequenos, as descrições que ficaram cortadas."""
    alvo = [
        (indice, doc)
        for indice, doc in enumerate(docs)
        if doc.get("description_en")
        and doc.get("description_pt")
        and len(doc["description_pt"]) < LIMIAR_TRUNCADO * len(doc["description_en"])
    ]
    if not alvo:
        return docs

    pendentes: List[str] = []
    vistos = set()
    for _, doc in alvo:
        for pedaco in _chunk_text(doc["description_en"], CHUNK_CHARS_FINO):
            if pedaco not in cache and pedaco not in vistos:
                vistos.add(pedaco)
                pendentes.append(pedaco)

    if pendentes:
        try:
            _modelo_pronto()
        except Exception as exc:
            logger.warning("EU Taxonomy: tradutor local indisponível: %s", exc)
            return docs

    pendentes.sort(key=len)
    total = len(pendentes)
    for inicio in range(0, total, BATCH_SIZE):
        lote = pendentes[inicio : inicio + BATCH_SIZE]
        try:
            traduzidos = _traduzir_lote(lote)
        except Exception as exc:
            logger.warning("EU Taxonomy: lote de recuperação falhou: %s", exc)
            traduzidos = []
        with _translate_lock:
            for original, traduzido in zip(lote, traduzidos):
                limpo = _normalizar(traduzido)
                if limpo:
                    cache[original] = limpo
            _save_translate_cache()
        if progress:
            try:
                progress(min(total, inicio + len(lote)), total)
            except Exception:
                pass

    for indice, doc in alvo:
        partes = [
            cache.get(pedaco) for pedaco in _chunk_text(doc["description_en"], CHUNK_CHARS_FINO)
        ]
        if all(partes):
            doc["description_pt"] = _normalizar_pt(" ".join(partes))
    logger.info("EU Taxonomy: %d descrições cortadas foram traduzidas de novo.", len(alvo))
    return docs


def translate_docs(
    docs: List[Dict[str, Any]],
    *,
    progress: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    """Traduz nome e descrição das atividades para PT, mantendo os originais.

    As descrições longas são divididas em pedaços (`_chunk_text`) e traduzidas
    em lote; os pedaços já traduzidos ficam em cache, pelo que repetir a
    operação só processa o que falta. `progress(done, total)` é chamado após
    cada lote para a interface poder mostrar o andamento.
    """
    with _translate_lock:
        cache = _load_translate_cache()

    # Cada documento tem: um nome e N pedaços de descrição.
    nomes: List[Tuple[int, str]] = []
    descricoes: List[Tuple[int, int, int, str]] = []  # (doc, pedaço, total, texto)
    for idx, doc in enumerate(docs):
        nome = _normalizar(doc.get("name_en") or "")
        if nome:
            nomes.append((idx, nome))
        pedacos = _chunk_text(doc.get("description_en") or "")
        for posicao, pedaco in enumerate(pedacos):
            descricoes.append((idx, posicao, len(pedacos), pedaco))

    # Textos únicos que ainda não estão em cache.
    pendentes: List[str] = []
    vistos = set()
    for _, texto in nomes:
        if texto not in cache and texto not in vistos:
            vistos.add(texto)
            pendentes.append(texto)
    for _, _, _, texto in descricoes:
        if texto not in cache and texto not in vistos:
            vistos.add(texto)
            pendentes.append(texto)

    total = len(pendentes)
    feitos = 0
    numeros_falhados: List[str] = []
    if pendentes:
        try:
            _modelo_pronto()
        except Exception as exc:  # modelo indisponível (sem rede/disco)
            logger.warning("EU Taxonomy: tradutor local indisponível: %s", exc)
            return docs

        # Agrupar por comprimento antes de lotear: um texto curto num lote de
        # textos longos fica à espera do mais longo (o lote só termina quando
        # todas as sequências acabam) e o trabalho cresce sem necessidade.
        pendentes.sort(key=len)

        for inicio in range(0, total, BATCH_SIZE):
            lote = pendentes[inicio : inicio + BATCH_SIZE]
            try:
                traduzidos = _traduzir_lote(lote)
            except Exception as exc:
                logger.warning("EU Taxonomy: lote de tradução falhou: %s", exc)
                traduzidos = []
            for original, traduzido in zip(lote, traduzidos):
                limpo = _normalizar(traduzido)
                if limpo:
                    with _translate_lock:
                        cache[original] = limpo
                em_falta = _numeros_em_falta(original, limpo)
                if em_falta:
                    with _translate_lock:
                        numeros_falhados.extend(em_falta)
            feitos = min(total, inicio + len(lote))
            with _translate_lock:
                _save_translate_cache()
            if progress:
                try:
                    progress(feitos, total)
                except Exception:  # o progresso nunca deve quebrar a tradução
                    pass

    for idx, nome in nomes:
        traduzido = cache.get(nome)
        if traduzido:
            docs[idx]["name_pt"] = _normalizar_pt(traduzido)

    for idx, posicao, total_pedacos, texto in descricoes:
        traduzido = cache.get(texto)
        if not traduzido:
            continue
        atual = docs[idx].get("description_pt")
        if posicao == 0 or not atual:
            docs[idx]["description_pt"] = _normalizar_pt(traduzido)
        else:
            docs[idx]["description_pt"] = _normalizar_pt(f"{atual} {traduzido}")

    docs = _completar_truncados(docs, cache, progress=progress)

    # Referências legais com algarismos que a tradução não preservou: ficam
    # assinaladas (o original inglês é sempre apresentado ao lado).
    for doc in docs:
        em_falta = _numeros_em_falta(doc.get("description_en") or "", doc.get("description_pt") or "")
        if em_falta:
            doc["revisto"] = False
            doc["numeros_a_confirmar"] = em_falta[:10]
        else:
            doc["revisto"] = True

    if numeros_falhados:
        logger.info(
            "EU Taxonomy: %d referências numéricas não preservadas na tradução (o original fica sempre visível).",
            len(set(numeros_falhados)),
        )

    return docs


def traduzir_snapshot(*, progress: Optional[Any] = None) -> Dict[str, Any]:
    """Traduz (incrementalmente) o snapshot existente e regrava-o em disco."""
    if not SNAPSHOT_PATH.exists():
        return {"error": "Snapshot ainda não existe. Execute a recolha primeiro."}
    snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    atividades = translate_docs(snapshot.get("activities", []), progress=progress)
    snapshot["activities"] = atividades
    snapshot["traduzido_em"] = _now()
    save_snapshot(snapshot)
    return {
        "activities": atividades,
        "objectives": snapshot.get("objectives", []),
        "sectors": snapshot.get("sectors", []),
        "translated_names": sum(1 for item in atividades if item.get("name_pt")),
        "translated_descriptions": sum(1 for item in atividades if item.get("description_pt")),
    }


def save_snapshot(snapshot: Dict[str, Any]) -> Path:
    """Grava o snapshot normalizado em `data/eu_taxonomy.json`."""
    _ensure_dirs()
    temporario = SNAPSHOT_PATH.with_suffix(f".{uuid.uuid4().hex}.tmp")
    temporario.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    temporario.replace(SNAPSHOT_PATH)
    logger.info("EU Taxonomy: snapshot gravado em %s", SNAPSHOT_PATH)
    return SNAPSHOT_PATH


def run(force: bool = False, translate: bool = False) -> Dict[str, Any]:
    """Executa a recolha completa: download, normalização e snapshot.

    `translate=True` traduz tudo de imediato (demora vários minutos no modelo
    local); o normal é recolher primeiro e traduzir depois, em segundo plano.
    """
    raw = fetch_raw(force=force)
    snapshot = build_snapshot(raw, translate=translate)
    save_snapshot(snapshot)
    return snapshot
