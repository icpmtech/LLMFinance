"""**Municípios de Portugal** — o brasão e a data de criação de cada concelho.

A lista da Wikipédia (`Lista de municípios de Portugal`) tem, para cada um dos 308
municípios, o **brasão**, a **data de criação do município** (com a origem, quando
é um foral: «1179 (foral de D. Afonso Henriques)»), o código de três letras e a
população do censo de 2021. É essa tabela que se lê aqui.

O brasão vem do Wikimedia Commons, pelo URL do ficheiro que a própria tabela
mostra; quando a linha não traz imagem (acontece com Almada), vai-se buscar a
`P94` do Wikidata e registra-se de onde veio — o brasão de um município não é
sítio para inventar. As imagens servem-se em miniatura, com autor e licença,
porque um brasão com procedência é um brasão que se pode mostrar.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import unquote

import httpx

logger = logging.getLogger(__name__)

PAGINA = "Lista de municípios de Portugal"
WIKI_API = "https://pt.wikipedia.org/w/api.php"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
CABECALHOS = {"User-Agent": "IQOS/1.0 (analise de financas publicas; contacto@icpm.tech)"}
FICHEIRO = "municipios_wikipedia.json"


class ErroLista(RuntimeError):
    """A Wikipédia não devolveu a lista, ou devolveu-a noutra forma."""


# ---------------------------------------------------------------------------
# Leitura do wikitext
# ---------------------------------------------------------------------------

def obter_wikitext(pagina: str = PAGINA) -> str:
    """O wikitext da página da lista, tal como está na Wikipédia."""
    resposta = httpx.get(
        WIKI_API,
        params={
            "action": "parse",
            "page": pagina,
            "prop": "wikitext",
            "format": "json",
            "formatversion": "2",
        },
        headers=CABECALHOS,
        timeout=120.0,
    )
    resposta.raise_for_status()
    dados = resposta.json()
    texto = ((dados.get("parse") or {}).get("wikitext")) or ""
    if "{|" not in texto:
        raise ErroLista("a página não trouxe a tabela dos municípios")
    return texto


def primeira_tabela(texto: str) -> str:
    """A primeira tabela do wikitext (as tabelas podem ter tabelas dentro)."""
    inicio = texto.find("{|")
    if inicio < 0:
        return ""
    profundidade = 0
    linhas: List[str] = []
    for linha in texto[inicio:].split("\n"):
        crua = linha.lstrip()
        if crua.startswith("{|"):
            profundidade += 1
        if crua.startswith("|}"):
            profundidade -= 1
            linhas.append(linha)
            if profundidade <= 0:
                break
            continue
        linhas.append(linha)
    return "\n".join(linhas)


def _celulas(tabela: str) -> List[List[str]]:
    """As linhas da tabela em células (`||` separa, `|-` abre linha)."""
    linhas: List[List[str]] = []
    for linha in tabela.split("\n"):
        crua = linha.strip()
        if crua.startswith("|-"):
            linhas.append([])
            continue
        if not linhas or crua.startswith("|}"):
            continue
        if crua.startswith("|"):
            linhas[-1].extend(crua[1:].split("||"))
    return [linha for linha in linhas if linha]


def limpar(valor: str) -> str:
    """Tira do wikitext o que não é conteúdo: referências, ligações, negrito."""
    valor = re.sub(r"<ref[^>]*>.*?</ref>", "", valor, flags=re.DOTALL)
    valor = re.sub(r"<ref[^>]*/>", "", valor)
    valor = re.sub(r"\{\{\s*fmtn\s*\|\s*([^}|]*)[^}]*\}\}", r"\1", valor)
    valor = re.sub(r"\[\[[^\]|]*\|([^\]]*)\]\]", r"\1", valor)
    valor = re.sub(r"\[\[([^\]]*)\]\]", r"\1", valor)
    valor = re.sub(r"'{2,}", "", valor)
    valor = re.sub(r"<[^>]+>", " ", valor)
    # As células alinhadas à direita trazem o atributo colado ao valor.
    valor = re.sub(r"align\s*=\s*\"?right\"?\s*\|", " ", valor)
    valor = valor.replace("|", " ")
    return re.sub(r"\s+", " ", valor).strip()


def _imagem(celula: str) -> Optional[str]:
    """O nome do ficheiro do brasão, como está no Commons.

    O nome vem por vezes percent-encoded (`Vila_Real_bras%C3%A3o.gif`) e com
    `_` no lugar dos espaços: sem o desfazer, o Commons não encontra nada.
    """
    achado = re.search(r"(?:Imagem|Ficheiro|File)\s*:\s*([^|\]]+)", celula or "")
    if not achado:
        return None
    nome = unquote(achado.group(1)).replace("_", " ").strip()
    return nome or None


def _titulo_artigo(celula: str) -> Optional[str]:
    """O artigo da Wikipédia do município (é por ele que se vai ao Wikidata)."""
    achado = re.search(r"\[\[([^\]|]+)", celula or "")
    return achado.group(1).strip() if achado else None


def _ano(descricao: str) -> Optional[int]:
    """O primeiro ano da descrição da criação («1179 (foral de …)» → 1179)."""
    achado = re.search(r"\b(\d{3,4})\b", descricao or "")
    if not achado:
        return None
    ano = int(achado.group(1))
    return ano if 1000 <= ano <= 2100 else None


def ler_tabela(texto: str) -> List[Dict[str, Any]]:
    """Lê a tabela dos municípios: brasão, data de criação, código e população.

    Cada registo é:

    ```python
    {"municipio": "Abrantes", "artigo": "Abrantes", "imagem": "PRT Abrantes CoA.svg",
     "criacao": "1179 (foral de D. Afonso Henriques)", "ano": 1179,
     "codigo": "ABT", "populacao_2021": 34351}
    ```
    """
    registos: List[Dict[str, Any]] = []
    for celulas in _celulas(primeira_tabela(texto)):
        if len(celulas) < 4:
            continue
        nome = limpar(celulas[1])
        if not nome:
            continue
        criacao = limpar(celulas[2])
        populacao = limpar(celulas[4]) if len(celulas) > 4 else ""
        registos.append({
            "municipio": nome,
            "artigo": _titulo_artigo(celulas[1]) or nome,
            "imagem": _imagem(celulas[0]),
            "criacao": criacao or None,
            "ano": _ano(criacao),
            "codigo": limpar(celulas[3]) or None,
            "populacao_2021": int(populacao.replace(" ", "")) if populacao.replace(" ", "").isdigit() else None,
        })
    return registos


# ---------------------------------------------------------------------------
# Brasões que a tabela não traz (Wikidata) e créditos (Commons)
# ---------------------------------------------------------------------------

def brasoes_do_wikidata(titulos: List[str]) -> Dict[str, str]:
    """O brasão (`P94`) dos municípios cujo artigo não o mostra na tabela.

    Vai-se pelo *sitelink* da Wikipédia portuguesa, para não depender de
    adivinhar o `Qid` pelo nome.
    """
    if not titulos:
        return {}
    resposta = httpx.get(
        WIKIDATA_API,
        params={
            "action": "wbgetentities",
            "sites": "ptwiki",
            "titles": "|".join(titulos),
            "props": "claims|sitelinks",
            "languages": "pt",
            "format": "json",
            "formatversion": "2",
        },
        headers=CABECALHOS,
        timeout=120.0,
    )
    resposta.raise_for_status()
    corpo = resposta.json()
    entidades = corpo.get("entities") or {}
    if isinstance(entidades, dict):
        entidades = list(entidades.values())
    brasoes: Dict[str, str] = {}
    for entidade in entidades:
        titulo = ((entidade.get("sitelinks") or {}).get("ptwiki") or {}).get("title")
        for declaracao in (entidade.get("claims") or {}).get("P94", []):
            ficheiro = ((declaracao.get("mainsnak") or {}).get("datavalue") or {}).get("value")
            if titulo and ficheiro:
                brasoes[titulo] = unquote(str(ficheiro)).replace("_", " ")
                break
    return brasoes


def coletar(forcar: bool = False, pasta: Optional[Path] = None) -> Dict[str, Any]:
    """Recolhe a lista (brasões, datas de criação) e guarda-a em disco."""
    destino = Path(pasta or ".") / FICHEIRO
    if destino.exists() and not forcar:
        try:
            return json.loads(destino.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Lista dos municípios ilegível (%s); a recolher de novo", exc)

    from api import camaras_wikidata

    texto = obter_wikitext()
    municipios = ler_tabela(texto)
    if len(municipios) < 300:
        raise ErroLista(f"a lista trouxe {len(municipios)} municípios (esperava 308)")

    sem_brasao = [m for m in municipios if not m.get("imagem")]
    if sem_brasao:
        try:
            do_wikidata = brasoes_do_wikidata([m["artigo"] for m in sem_brasao])
        except Exception as exc:  # noqa: BLE001
            logger.warning("Wikidata falhou a completar os brasões: %s", exc)
            do_wikidata = {}
        for municipio in sem_brasao:
            ficheiro = do_wikidata.get(municipio["artigo"])
            if ficheiro:
                municipio["imagem"] = ficheiro
                municipio["imagem_fonte"] = "Wikidata (P94)"

    nomes = sorted({m["imagem"] for m in municipios if m.get("imagem")})
    try:
        creditos = camaras_wikidata.creditos_imagens(nomes, largura=200)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Commons falhou nos créditos dos brasões: %s", exc)
        creditos = {}
    for municipio in municipios:
        municipio["credito"] = creditos.get(municipio.get("imagem") or "")

    payload = {
        "recolhido_em": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "fonte": "Wikipédia — Lista de municípios de Portugal",
        "fonte_url": f"https://pt.wikipedia.org/wiki/{PAGINA.replace(' ', '_')}",
        "fonte_imagens": "Wikimedia Commons (créditos por imagem; brasões em falta: Wikidata P94)",
        "pagina": PAGINA,
        "municipios": municipios,
        "total": len(municipios),
        "com_brasao": sum(1 for m in municipios if m.get("imagem")),
        "com_credito": sum(1 for m in municipios if m.get("credito")),
        "com_data_criacao": sum(1 for m in municipios if m.get("ano")),
    }
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return payload
