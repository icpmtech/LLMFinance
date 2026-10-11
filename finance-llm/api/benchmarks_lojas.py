"""Catálogo de lojas conhecidas para a sonda de produtos.

Endereços de **categoria** (não da página inicial) e o fetcher que cada site
exige. Cada entrada traz o que se aprendeu a medir, para não se repetir o erro de
apontar a sonda para um caminho que já não existe — foi assim que a PCDiga e a
Radio Popular pareceram «sem preços» quando o endereço estava errado (404):

- `fetcher`: `http` chega a catálogos simples; `dynamic` quando o preço só
  aparece depois do JavaScript; `stealth` para sites com proteção agressiva.
- `estado`: `ok` já validado, `bloqueado` quando o site recusa (403/captcha),
  `sem_preco` quando a listagem não traz o preço ao fetcher.
- `nota`: o que se verificou, com data, para quem vier depois.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

#: Categorias de demonstração (a lista é usada pela UI para sondar num clique).
CATALOGO: List[Dict[str, Any]] = [
    {
        "id": "worten",
        "nome": "Worten",
        "url": "https://www.worten.pt/informatica-e-acessorios/computadores",
        "fetcher": "dynamic",
        "estado": "ok",
        "nota": "Cartão `article.product-card`; preço, preço antes, imagem e descrição (validado 2026-10-11).",
    },
    {
        "id": "amazon-es",
        "nome": "Amazon Espanha",
        "url": "https://www.amazon.es/s?k=portatil",
        "fetcher": "dynamic",
        "estado": "ok",
        "nota": "Página de pesquisa; ~60 cartões. A «descrição» da listagem é o aviso de patrocínio, não a ficha do produto (validado 2026-10-11).",
    },
    {
        "id": "mediamarkt-pt",
        "nome": "MediaMarkt (Darty PT)",
        "url": "https://www.mediamarkt.pt/collections/portateis",
        "fetcher": "dynamic",
        "estado": "ok",
        "nota": "Loja Shopify: preço, preço antes e disponibilidade (validado 2026-10-11).",
    },
    {
        "id": "pcdiga",
        "nome": "PCDiga",
        "url": "https://www.pcdiga.com/computadores-e-software/computadores-laptop",
        "fetcher": "dynamic",
        "estado": "ok",
        "nota": "Caminho `/portateis` dava 404; o correto é este. Confirmar os preços da listagem (algumas promoções trazem etiquetas com valores à parte).",
    },
    {
        "id": "fnac",
        "nome": "Fnac",
        "url": "https://www.fnac.pt/informatica/h10",
        "fetcher": "stealth",
        "estado": "bloqueado",
        "nota": "HTTP 403 mesmo com Chromium: página «FNAC DARTY - Maintenance» e `x-datadome: protected`. Não é problema de seletores.",
    },
    {
        "id": "fnac-es",
        "nome": "Fnac Espanha",
        "url": "https://www.fnac.es/Ordenadores-portatiles/Ordenadores-portatiles/na48",
        "fetcher": "stealth",
        "estado": "bloqueado",
        "nota": "HTTP 403 (mesma proteção da Fnac.pt).",
    },
    {
        "id": "darty",
        "nome": "Darty (França)",
        "url": "https://www.darty.com/nav/achat/informatique/ordinateur_portable-portable/index.html",
        "fetcher": "stealth",
        "estado": "bloqueado",
        "nota": "HTTP 403.",
    },
    {
        "id": "radiopopular",
        "nome": "Radio Popular",
        "url": "https://www.radiopopular.pt/categoria/computadores-portateis",
        "fetcher": "dynamic",
        "estado": "sem_preco",
        "nota": "A listagem traz título, imagem e descrição, mas o preço não aparece no HTML entregue ao browser.",
    },
    {
        "id": "auchan",
        "nome": "Auchan",
        "url": "https://www.auchan.pt/pt/tecnologia/informatica/",
        "fetcher": "dynamic",
        "estado": "sem_preco",
        "nota": "Sem preço na listagem (categoria de informática, não só portáteis).",
    },
]

CATALOGO_POR_ID = {loja["id"]: loja for loja in CATALOGO}


def lojas(estado: Optional[str] = None) -> List[Dict[str, Any]]:
    """Catálogo de lojas conhecidas (opcionalmente só as de um estado)."""
    if not estado:
        return [dict(loja) for loja in CATALOGO]
    return [dict(loja) for loja in CATALOGO if loja.get("estado") == estado]


def obter(loja_id: str) -> Optional[Dict[str, Any]]:
    loja = CATALOGO_POR_ID.get(str(loja_id or "").strip())
    return dict(loja) if loja else None


def resumo() -> Dict[str, Any]:
    """Contagem por estado, para a página de configuração mostrar o panorama."""
    contagem: Dict[str, int] = {}
    for loja in CATALOGO:
        contagem[loja["estado"]] = contagem.get(loja["estado"], 0) + 1
    return {
        "total": len(CATALOGO),
        "por_estado": contagem,
        "atualizado_em": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
