"""Rotas do cabeçalho e rodapé das páginas públicas da plataforma.

- `GET /app-shell` — o que as páginas de entrada (`/`, `/login`, `/register`)
  desenham: marca, navegação, botões e rodapé, já resolvidos. É público: quem
  chega sem sessão tem de o poder ler.
- `GET /admin/app-shell` — a configuração em vigor + as predefinições, para o
  painel **Administração → Plataforma** editar.
- `PUT /admin/app-shell` — grava a configuração (só administradores).

A configuração vive no `api.app_shell` (`data/app/shell.json`). Este módulo
serve as duas pontas de propósito: a leitura pública e a escrita no backoffice
são a mesma definição, e tê-las juntas evita que uma mude sem a outra.
"""
from __future__ import annotations

from typing import Annotated, Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, Response

from api import app_shell
from api.admin_routes import require_admin
from api.auth_routes import CurrentSession

router = APIRouter(tags=["plataforma"])

AdminSession = Annotated[CurrentSession, Depends(require_admin)]

#: O cabeçalho muda raramente e é pedido em cada entrada: uns segundos de cache
#: chegam para poupar o ficheiro sem atrasar uma alteração feita no backoffice
#: (o mesmo valor das páginas públicas do CMS).
_PUBLIC_HEADERS = {"Cache-Control": "public, max-age=15, must-revalidate"}


def _estado_do_painel() -> Dict[str, Any]:
    """O que o painel precisa para editar: configuração, predefinições e limites."""
    return {
        "shell": app_shell.document(),
        "defaults": app_shell.defaults(),
        "limits": {
            "links": app_shell.MAX_LINKS,
            "label": app_shell.MAX_LABEL,
            "href": app_shell.MAX_HREF,
            "text": app_shell.MAX_TEXT,
        },
        "social": [{"key": chave, "label": etiqueta} for chave, etiqueta in app_shell.SOCIAL],
    }


@router.get("/app-shell")
def app_shell_publico(response: Response) -> Dict[str, Any]:
    """Cabeçalho e rodapé das páginas públicas da plataforma."""
    response.headers.update(_PUBLIC_HEADERS)
    return app_shell.public_payload()


@router.get("/admin/app-shell")
def admin_app_shell(session: AdminSession) -> Dict[str, Any]:
    """Configuração em vigor do cabeçalho e rodapé das páginas públicas."""
    return _estado_do_painel()


@router.put("/admin/app-shell")
def admin_gravar_app_shell(session: AdminSession, payload: Optional[Dict[str, Any]] = Body(None)) -> Dict[str, Any]:
    """Grava a configuração e devolve o estado do painel já atualizado."""
    guardado = app_shell.save(payload, author=session.user.email)
    estado = _estado_do_painel()
    estado["shell"] = guardado
    estado["saved"] = True
    return estado
