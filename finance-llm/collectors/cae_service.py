"""Serviço de recolha de CAE para entidades portuguesas.

Fontes:
- PNS/RNPC (gov.pt) — já implementado em ``collectors.pns_firmas``; devolve
  ``cae_principal`` e o nome/denominação oficial.
- SICAe (sicae.pt) — formulário WebForms com CAPTCHA; não é usado aqui para
  evitar dependência de resolução manual de imagem.

Estratégia:
1. Pesquisa por nome da empresa no PNS.
2. Se for fornecido NIF/NIPC, tenta cruzar com os resultados por NIF exato.
3. Se não houver cruzamento, tenta variantes de nome derivadas do nome original.
4. Guarda o resultado estruturado em ``data/cae/<nome-seguro>.json``.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from collectors.pns_firmas import PnsFirmasClient, fetch_firmas_for_company
from collectors.name_utils import name_search_candidates

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
CAE_DIR = ROOT / "data" / "cae"

NIF_RE = re.compile(r"^\d{9}$")


def _safe_filename(name: str) -> str:
    """Gera um nome de ficheiro seguro a partir do nome da empresa."""
    safe = re.sub(r"[^a-zA-Z0-9\-]", "_", name or "sem_nome")
    safe = re.sub(r"_+", "_", safe).strip("_")
    return safe[:120] or "entidade"


def _deduplicate_caes(caes: List[str]) -> List[str]:
    """Remove CAEs vazios e duplicados, preservando ordem."""
    seen = set()
    out: List[str] = []
    for c in (caes or []):
        code = (c or "").strip()
        if code and code not in seen:
            seen.add(code)
            out.append(code)
    return out


def _best_match(
    firmas: List[Dict[str, Any]],
    name: str,
    nif: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Escolhe o resultado mais provável.

    Prioridade:
    1. NIF exato (quando fornecido).
    2. Nome exato (case-insensitive, ignorando pontuação).
    3. Maior score devolvido pelo PNS.
    """
    norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())
    target_norm = norm(name)
    target_nif = (nif or "").strip()

    # 1. NIF
    if target_nif:
        for f in firmas:
            if f.get("nipc") and f["nipc"].strip() == target_nif:
                return f

    # 2. nome exato normalizado
    for f in firmas:
        if norm(f.get("nome")) == target_norm:
            return f

    # 3. maior score
    scored = [f for f in firmas if f.get("score") is not None]
    if scored:
        return max(scored, key=lambda f: f["score"])

    return firmas[0] if firmas else None


def collect_cae(
    name: str,
    nif: Optional[str] = None,
    include_detail: bool = True,
    save: bool = True,
    min_interval: float = 0.5,
) -> Dict[str, Any]:
    """Recolhe CAE para uma entidade portuguesa.

    Args:
        name: nome/denominação social da empresa.
        nif: NIF/NIPC opcional; usado como fallback quando a pesquisa por nome
            não devolve correspondência clara.
        include_detail: abre detalhe PNS para obter CAE principal.
        save: grava JSON em ``data/cae/<nome>.json``.
        min_interval: intervalo mínimo entre pedidos ao PNS.

    Returns:
        Dicionário com ``cae_principal``, ``caes_secundarios`` (lista), ``source``,
        ``match`` (melhor firma encontrada), ``tried`` (termos testados) e ``saved_to``.
    """
    if not name or not str(name).strip():
        return {
            "cae_principal": None,
            "caes_secundarios": [],
            "source": "pns_rnpc",
            "match": None,
            "tried": [],
            "error": "Nome em falta",
            "saved_to": None,
        }

    name = str(name).strip()
    CAE_DIR.mkdir(parents=True, exist_ok=True)

    client = PnsFirmasClient(min_interval=min_interval)
    candidates = name_search_candidates(name) or [name]
    tried: List[Dict[str, Any]] = []
    all_firmas: List[Dict[str, Any]] = []

    for term in candidates:
        try:
            if include_detail:
                result = fetch_firmas_for_company(
                    term,
                    include_detail=True,
                    max_results=20,
                    min_interval=min_interval,
                )
                firmas = result.get("firmas", [])
            else:
                firmas_raw = client.search(term)
                firmas = [f.to_dict() for f in firmas_raw]
            tried.append({"term": term, "found": len(firmas)})
            all_firmas.extend(firmas)
            # se já encontramos match pelo NIF, podemos parar cedo
            if nif and any(f.get("nipc") == nif.strip() for f in firmas):
                break
        except Exception as exc:
            logger.warning("Falha CAE ao pesquisar '%s': %s", term, exc)
            tried.append({"term": term, "found": 0, "error": str(exc)})

    match = _best_match(all_firmas, name, nif=nif)

    cae_principal = None
    caes_secundarios: List[str] = []
    if match:
        cae_principal = (match.get("cae_principal") or "").strip() or None
        # PNS não devolve secundários de momento; reservado para futuras fontes.
        caes_secundarios = _deduplicate_caes(match.get("caes_secundarios"))

    payload: Dict[str, Any] = {
        "name": name,
        "nif": (nif or "").strip() or None,
        "cae_principal": cae_principal,
        "caes_secundarios": caes_secundarios,
        "source": "pns_rnpc",
        "match": match,
        "tried": tried,
        "total_firmas_considered": len(all_firmas),
        "error": None if match else "Nenhuma firma encontrada",
    }

    if save:
        path = CAE_DIR / f"{_safe_filename(name)}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        payload["saved_to"] = str(path)
    else:
        payload["saved_to"] = None

    return payload


def load_cae(name: str) -> Optional[Dict[str, Any]]:
    """Lê um ficheiro CAE previamente guardado."""
    path = CAE_DIR / f"{_safe_filename(name)}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # exemplo: EDP Comercial
    print(json.dumps(collect_cae("EDP COMERCIAL", nif="503504564"), ensure_ascii=False, indent=2))
