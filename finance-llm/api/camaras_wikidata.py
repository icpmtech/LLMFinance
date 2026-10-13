"""**Câmaras municipais** — o edifício (foto, coordenadas e classificação).

A lista da Wikipédia das câmaras municipais em Portugal é gerada a partir do
Wikidata (classe `Q25550691`, «câmara municipal», com país Portugal), e é daí que
vêm a **fotografia** (`P18`), as **coordenadas** (`P625`), a classificação
patrimonial (`P1435`) e a referência SIPA (`P1700`). Este módulo vai à mesma
fonte — o Wikidata — em vez de raspar o HTML da Wikipédia, pelo que os dados
ficam estruturados e com licença clara.

As imagens são do **Wikimedia Commons**: além do URL, recolhe-se o autor e a
licença (e o URL da licença), porque uma foto com procedência é uma foto que se
pode mostrar. Servem-se em miniatura (`thumburl`), não no original — são fotos de
edifícios, o original pode ter dezenas de megabytes.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List
from urllib.parse import unquote

import httpx

logger = logging.getLogger(__name__)

WIKIDATA_ENDPOINT = "https://query.wikidata.org/sparql"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
CABECALHOS = {"User-Agent": "IQOS/1.0 (analise de financas publicas; contacto@icpm.tech)"}

CLASSE_CAMARA_MUNICIPAL = "Q25550691"
PAIS_PORTUGAL = "Q45"

CONSULTA = f"""
SELECT DISTINCT ?item ?itemLabel ?imagem ?localizacaoLabel ?coord ?patrimonioLabel ?sipa ?artigo WHERE {{
  ?item wdt:P31 wd:{CLASSE_CAMARA_MUNICIPAL} ; wdt:P17 wd:{PAIS_PORTUGAL} .
  OPTIONAL {{ ?item wdt:P18 ?imagem . }}
  OPTIONAL {{ ?item wdt:P131 ?localizacao . }}
  OPTIONAL {{ ?item wdt:P625 ?coord . }}
  OPTIONAL {{ ?item wdt:P1435 ?patrimonio . }}
  OPTIONAL {{ ?item wdt:P1700 ?sipa . }}
  OPTIONAL {{ ?artigo schema:about ?item ; schema:isPartOf <https://pt.wikipedia.org/> . }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "pt,en". }}
}}
"""


def _coordenadas(valor: str) -> tuple:
    """`Point(-8.19 39.46)` → `(39.46, -8.19)` (lat, lon)."""
    dentro = valor[valor.find("(") + 1 : valor.rfind(")")].split()
    if len(dentro) < 2:
        return None, None
    return float(dentro[1]), float(dentro[0])


def _nome_ficheiro(url: str) -> str:
    return unquote(url.rsplit("/", 1)[-1]).replace("_", " ")


def consultar_wikidata(tentativas: int = 3) -> List[Dict[str, Any]]:
    """Os edifícios das câmaras municipais (um registo por edifício)."""
    ultimo_erro: Exception | None = None
    for tentativa in range(1, tentativas + 1):
        try:
            resposta = httpx.get(
                WIKIDATA_ENDPOINT,
                params={"query": CONSULTA, "format": "json"},
                headers={**CABECALHOS, "Accept": "application/sparql-results+json"},
                timeout=180.0,
            )
            resposta.raise_for_status()
            linhas = resposta.json()["results"]["bindings"]
            return _agregar(linhas)
        except Exception as exc:  # noqa: BLE001
            ultimo_erro = exc
            logger.warning("Wikidata falhou na tentativa %d: %s", tentativa, exc)
    raise RuntimeError(f"Não foi possível ler as câmaras do Wikidata: {ultimo_erro}")


def _agregar(linhas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    itens: Dict[str, Dict[str, Any]] = {}
    for linha in linhas:
        qid = linha["item"]["value"].rsplit("/", 1)[-1]
        registo = itens.setdefault(
            qid,
            {
                "wikidata": qid,
                "designacao": linha.get("itemLabel", {}).get("value"),
                "imagem": None,
                "localizacao": None,
                "lat": None,
                "lon": None,
                "patrimonio": None,
                "sipa": None,
                "artigo": None,
            },
        )
        if linha.get("imagem"):
            registo["imagem"] = _nome_ficheiro(linha["imagem"]["value"])
        if linha.get("localizacaoLabel"):
            registo["localizacao"] = linha["localizacaoLabel"]["value"]
        if linha.get("coord"):
            registo["lat"], registo["lon"] = _coordenadas(linha["coord"]["value"])
        if linha.get("patrimonioLabel"):
            registo["patrimonio"] = linha["patrimonioLabel"]["value"]
        if linha.get("sipa"):
            registo["sipa"] = linha["sipa"]["value"]
        if linha.get("artigo"):
            registo["artigo"] = linha["artigo"]["value"]
    return sorted(itens.values(), key=lambda registo: registo.get("designacao") or "")


def creditos_imagens(nomes: List[str], largura: int = 480, lote: int = 50) -> Dict[str, Any]:
    """Autor, licença e URL de miniatura de cada imagem, pelo Commons."""
    creditos: Dict[str, Any] = {}
    for inicio in range(0, len(nomes), lote):
        pedaco = [nome for nome in nomes[inicio : inicio + lote] if nome]
        if not pedaco:
            continue
        try:
            dados = httpx.get(
                COMMONS_API,
                params={
                    "action": "query",
                    "format": "json",
                    "formatversion": "2",
                    "prop": "imageinfo",
                    "iiprop": "url|extmetadata",
                    "iiurlwidth": str(largura),
                    "titles": "|".join(f"File:{nome}" for nome in pedaco),
                },
                headers=CABECALHOS,
                timeout=120.0,
            ).json()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Commons falhou para um lote de %d imagens: %s", len(pedaco), exc)
            continue
        for pagina in dados.get("query", {}).get("pages", []):
            info = (pagina.get("imageinfo") or [None])[0]
            if not info:
                continue
            meta = info.get("extmetadata", {})
            creditos[pagina["title"][len("File:") :].replace("_", " ")] = {
                "url": info.get("thumburl") or info.get("url"),
                "autor": _autor(meta.get("Artist")),
                "licenca": _texto(meta.get("LicenseShortName")),
                "licenca_url": _texto(meta.get("LicenseUrl")),
                "pagina": info.get("descriptionurl"),
                "largura": largura,
            }
    return creditos


def _texto(campo: Any) -> str | None:
    """O Commons devolve etiquetas HTML no autor; fica só o texto."""
    if not campo:
        return None
    valor = campo.get("value") if isinstance(campo, dict) else campo
    if not valor:
        return None
    sem_tags = re.sub(r"<[^>]+>", " ", str(valor))
    return re.sub(r"\s+", " ", sem_tags).strip() or None


# Onde começa o texto da licença quando ele vem colado ao nome do autor.
_INICIO_LICENCA = re.compile(
    r"(licensed under|this file is|creative ?commons|you are free|share ?alike"
    r"|public domain|attribution|cc[ -]?by)",
    re.IGNORECASE,
)


def _autor(campo: Any) -> str | None:
    """O autor da imagem, sem o texto da licença nem etiquetas HTML.

    Alguns carregadores deixam o **template inteiro da licença** no campo do
    autor (é o caso do utilizador «Kolforn»), o que dava créditos de centenas de
    caracteres. Acima de 100 caracteres corta-se no início da licença e, se ainda
    sobrar frase a mais, fica só o nome antes do parêntese. A licença em si vem
    no campo próprio (`LicenseShortName`), pelo que nada se perde.
    """
    texto = _texto(campo)
    if not texto or len(texto) <= 100:
        return texto
    inicio = _INICIO_LICENCA.search(texto)
    if inicio:
        texto = texto[: inicio.start()].strip(" .,;:—-") or texto
    if len(texto) > 100:
        parentese = texto.find("(")
        texto = texto[:parentese].strip() if parentese >= 3 else texto[:97].rstrip() + "…"
    return texto or None


def coletar(forcar: bool = False, pasta=None) -> Dict[str, Any]:
    """Edifícios das câmaras + créditos das fotos, com cache em disco.

    A cache existe porque a Wikidata é lenta e as fotos quase nunca mudam: uma
    passagem completa (consulta + 6 lotes ao Commons) demora perto de um minuto, e
    não vale a pena repeti-la a cada reindexação.
    """
    import json
    from datetime import datetime, timezone
    from pathlib import Path

    destino = (Path(pasta) if pasta else Path(__file__).resolve().parents[1] / "data" / "remuneracoes") / "camaras_wikidata.json"
    if destino.exists() and not forcar:
        try:
            guardado = json.loads(destino.read_text(encoding="utf-8"))
            if guardado.get("camaras"):
                return guardado
        except Exception as exc:  # noqa: BLE001
            logger.warning("Cache das câmaras ilegível (%s); a recolher de novo.", exc)

    camaras = consultar_wikidata()
    nomes = sorted({c["imagem"] for c in camaras if c.get("imagem")})
    creditos = creditos_imagens(nomes)
    payload = {
        "recolhido_em": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "fonte": "Wikidata (classe «câmara municipal», Q25550691) — imagens do Wikimedia Commons",
        "fonte_url": WIKIDATA_ENDPOINT,
        "pagina_wikipedia": "https://pt.wikipedia.org/wiki/Lista_das_câmaras_municipais_em_Portugal",
        "total": len(camaras),
        "total_com_imagem": sum(1 for c in camaras if c.get("imagem")),
        "total_com_coordenadas": sum(1 for c in camaras if c.get("lat") is not None),
        "camaras": camaras,
        "creditos": creditos,
    }
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload
