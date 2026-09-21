"""Rotas das **skills** do IQ OS (`/skills/*`).

A biblioteca é partilhada pelo Hermes, pelo Chat IA e pelo RAG: antes de
responder, cada assistente escolhe (ou cria) a skill do pedido e segue o seu
método. Estas rotas servem o painel do Hermes (ver, editar, ativar/desativar,
apagar) e permitem pré-visualizar a skill que uma pergunta ia usar.

Leitura (aberta):

- `GET  /skills`              — biblioteca + estado (total, usos, por origem)
- `GET  /skills/{skill_id}`   — uma skill
- `POST /skills/match`        — que skill da biblioteca serviria esta pergunta
- `POST /skills/ensure`       — escolhe ou **cria** (sem responder) a skill do pedido

Escrita (requer sessão):

- `POST   /skills`            — criar/atualizar uma skill
- `PATCH  /skills/{skill_id}` — editar campos (nome, quando, passos, verificações, ativa)
- `DELETE /skills/{skill_id}` — apagar
- `DELETE /skills`            — limpar a biblioteca
"""
from __future__ import annotations

import logging
from typing import Annotated, Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException

from api import skills_service as skills
from api.auth_routes import CurrentSession, optional_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/skills", tags=["skills"])

Session = Annotated[Optional[CurrentSession], Depends(optional_session)]


def _writer(session: Optional[CurrentSession]) -> CurrentSession:
    if not session:
        raise HTTPException(status_code=401, detail="Entrar na plataforma para editar as skills.")
    return session


@router.get("")
def list_skills() -> Dict[str, Any]:
    """Biblioteca completa (mais usadas primeiro) e estado da coleção."""
    return {"skills": skills.list_skills(), "status": skills.status()}


@router.post("/match")
def match_skill(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """Skill da biblioteca que serviria esta pergunta (sem criar nada)."""
    question = str(payload.get("question") or "").strip()
    if not question:
        raise HTTPException(status_code=422, detail="Escreva a pergunta.")
    found = skills.match(question)
    return {
        "question": question,
        "skill": skills.public(found) if found else None,
        "score": skills.score(found, question) if found else 0.0,
    }


@router.post("/ensure")
async def ensure_skill(payload: Dict[str, Any] = Body(...), session: Session = None) -> Dict[str, Any]:
    """Escolhe a skill do pedido ou cria uma nova (sem a aplicar a nenhuma resposta)."""
    question = str(payload.get("question") or "").strip()
    if not question:
        raise HTTPException(status_code=422, detail="Escreva a pergunta.")
    result = await skills.ensure_skill(
        question,
        session=session,
        backend=str(payload["backend"]) if payload.get("backend") else None,
        model_draft=bool(payload.get("model_draft", True)),
    )
    return {
        "question": question,
        "created": result["created"],
        "merged": result["merged"],
        "mode": result["mode"],
        "score": result["score"],
        "skill": skills.public(result["skill"], created=result["created"], merged=result["merged"], skill_mode=result["mode"]),
    }


@router.get("/{skill_id}")
def get_skill(skill_id: str) -> Dict[str, Any]:
    skill = skills.get_skill(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill não encontrada.")
    return {"skill": skill}


@router.post("")
def save_skill(payload: Dict[str, Any] = Body(...), session: Session = None) -> Dict[str, Any]:
    _writer(session)
    if not (payload.get("name") or payload.get("question") or payload.get("id")):
        raise HTTPException(status_code=422, detail="Indique pelo menos o nome da skill.")
    return {"saved": True, "skill": skills.save_skill(payload), "status": skills.status()}


@router.patch("/{skill_id}")
def patch_skill(skill_id: str, payload: Dict[str, Any] = Body(...), session: Session = None) -> Dict[str, Any]:
    _writer(session)
    if not skills.get_skill(skill_id):
        raise HTTPException(status_code=404, detail="Skill não encontrada.")
    return {"saved": True, "skill": skills.save_skill({**payload, "id": skill_id})}


@router.delete("/{skill_id}")
def delete_skill(skill_id: str, session: Session = None) -> Dict[str, Any]:
    _writer(session)
    if not skills.delete_skill(skill_id):
        raise HTTPException(status_code=404, detail="Skill não encontrada.")
    return {"removed": True, "id": skill_id, "status": skills.status()}


@router.delete("")
def clear_skills(session: Session = None) -> Dict[str, Any]:
    _writer(session)
    return {"removed": skills.clear_skills(), "status": skills.status()}
