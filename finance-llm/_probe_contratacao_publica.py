"""Sonda das fontes de **contratação pública** (Portugal, União Europeia, Reino Unido e Espanha).

Responde, fonte a fonte, à pergunta que se faz antes de criar uma recolha: *isto
dá para recolher, e por onde?* Para cada candidata, o relatório diz

* se responde a um cliente HTTP simples (e com que tipo de conteúdo);
* se o `robots.txt` do domínio permite a recolha (a recolha do módulo respeita-o);
* se a página anuncia um `feed` RSS/Atom (o caminho mais estável quando existe);
* quantos registos saíram e, quando a fonte já é um **template**, a cobertura de
  cada campo — a mesma medida que o `_test_scraper_templates.py` usa.

Fontes com template vivem em `api/scraper_templates.py`; as que ainda não têm
(por dependerem de browser, de `stealth` ou de autorização do site) ficam aqui
com a razão à vista, para não se prometer o que não se entrega.

Uso::

    python _probe_contratacao_publica.py               # todas
    python _probe_contratacao_publica.py ted-api base-portal
    python _probe_contratacao_publica.py --limit 3

O relatório sai em `_probe_contratacao_publica.txt` (UTF-8: o console do Windows
estraga os acentos) e o resumo aparece no ecrã.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.robotparser
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests

RAIZ = Path(__file__).resolve().parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from api import scraper_service as scraper  # noqa: E402
from api import scraper_templates as templates  # noqa: E402

RELATORIO = RAIZ / "_probe_contratacao_publica.txt"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
TIMEOUT = 60

#: As candidatas, agrupadas por país. `template` liga a sonda ao catálogo de
#: templates (é o que se cria com um clique); `pais` e `notas` são para o leitor.
FONTES: List[Dict[str, Any]] = [
    # ------------------------------------------------------------------ Portugal
    {
        "id": "base-portal",
        "nome": "Portal BASE · lista de contratos",
        "pais": "Portugal",
        "url": "https://www.base.gov.pt/Base4/pt/pesquisa/",
        "notas": (
            "A pesquisa vive de um AJAX (`POST /Base4/pt/resultados/`, "
            "`type=search_contratos`) que responde **200 com corpo vazio** a clientes que não sejam "
            "um browser (defesa anti-bot da F5). O CSV (`type=csv_contratos`) está atrás da mesma "
            "defesa. Alternativas: fetcher `stealth`, ou os ficheiros de dados abertos do portal."
        ),
    },
    {
        "id": "base-api",
        "nome": "Portal BASE · endpoint AJAX dos resultados",
        "pais": "Portugal",
        "url": "https://www.base.gov.pt/Base4/pt/resultados/",
        "metodo": "POST",
        "form": {
            "type": "search_contratos",
            "version": "0.0",
            "query": "tipo=0&pais=0&distrito=0&concelho=0",
            "sort": "1",
            "page": "1",
            "size": "3",
        },
        "notas": "Referer do site obrigatório. Espera-se corpo vazio (bloqueio), não um erro HTTP.",
    },
    {
        "id": "base-detalhe",
        "nome": "Portal BASE · ficha de contrato",
        "pais": "Portugal",
        "url": "https://www.base.gov.pt/Base4/pt/detalhe/?type=contratos&id=0",
        "notas": (
            "A página de detalhe é servida em HTML (ao contrário da lista): serviria para "
            "`detail` de uma recolha, se a lista fosse acessível."
        ),
    },
    {
        "id": "vortal-publico",
        "nome": "Vortal · área pública",
        "pais": "Portugal",
        "url": "https://community.vortal.biz/public/",
        "notas": (
            "Já integrado na plataforma pelo `api/vortal_service.py` (peças do procedimento a partir do "
            "token do anúncio) — não precisa de template de recolha, e o `robots.txt` do domínio recusa "
            "a área pública, pelo que a recolha genérica também não é caminho."
        ),
    },
    {
        "id": "dre-pesquisa",
        "nome": "Diário da República · pesquisa",
        "pais": "Portugal",
        "url": "https://dre.pt/dre/pesquisa",
        "notas": (
            "Publica anúncios de contratos de autarquias e de outras entidades. A resposta é uma página "
            "de aplicação (~2 kB de HTML), pelo que a lista vem de um pedido próprio do site — exigiria "
            "`dynamic`/API, não um seletor de lista."
        ),
    },
    # ------------------------------------------------------------------------ UE
    {
        "id": "ted-api",
        "nome": "TED · API de pesquisa (UE)",
        "pais": "União Europeia",
        "url": "https://api.ted.europa.eu/v3/notices/search",
        "metodo": "POST",
        "json": {
            "query": "publication-date = today(-7)",
            "fields": ["publication-number", "notice-title", "publication-date", "buyer-name", "notice-type"],
            "page": 1,
            "limit": 5,
        },
        "contagem": "notices",
        "notas": "JSON sem chave. É a via mais estável para os avisos europeus (HTML é aplicação JavaScript).",
    },
    {
        "id": "ted-site",
        "nome": "TED · pesquisa no site",
        "pais": "União Europeia",
        "url": "https://ted.europa.eu/en/search/result?FT=publication-date%3D%3Dtoday",
        "notas": "Aplicação (Liferay + JavaScript): os resultados não vêm no HTML — exigiria fetcher `dynamic`.",
    },
    # ------------------------------------------------------------------------ RU
    {
        "id": "find-a-tender",
        "nome": "Find a Tender (RU)",
        "pais": "Reino Unido",
        "url": "https://www.find-tender.service.gov.uk/Search/Results",
        "template": "find-a-tender",
        "notas": "Avisos acima dos limiares europeus, com paginação por `?page=N`.",
    },
    {
        "id": "find-a-tender-api",
        "nome": "Find a Tender · dados abertos OCDS (RU)",
        "pais": "Reino Unido",
        "url": "https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages",
        "contagem": "releases",
        "notas": "JSON no padrão OCDS: alternativa estruturada ao template, sem paginação de HTML.",
    },
    {
        "id": "contracts-finder",
        "nome": "Contracts Finder (RU)",
        "pais": "Reino Unido",
        "url": "https://www.contractsfinder.service.gov.uk/Search/Results",
        "template": "contracts-finder",
        "notas": "Avisos abaixo e acima dos limiares, com paginação por `?page=N`.",
    },
    # ------------------------------------------------------------------------ ES
    {
        "id": "placsp-atom",
        "nome": "Plataforma de Contratación (ES) · Atom",
        "pais": "Espanha",
        "url": "https://contrataciondelestado.es/sindicacion/sindicacion_643/licitacionesPerfilesContratanteCompleto3.atom",
        "notas": (
            "O `robots.txt` de `contrataciondelestado.es` é `Disallow: /`, pelo que a recolha do "
            "módulo recusa esta fonte (respeita o `robots.txt`). Sem acordo/autorização, não entra "
            "no catálogo — para Espanha vale o `api/contratos_es_*`, que já usa a sindicação oficial."
        ),
    },
]


def _robots_permite(url: str) -> Optional[bool]:
    """O `robots.txt` do domínio deixa recolher este caminho? (`None` se ilegível.)"""
    partes = urlparse(url)
    robots = f"{partes.scheme}://{partes.netloc}/robots.txt"
    parser = urllib.robotparser.RobotFileParser()
    parser.set_url(robots)
    try:
        parser.read()
    except Exception:
        return None
    try:
        return parser.can_fetch("*", url)
    except Exception:
        return None


def _pedido(fonte: Dict[str, Any]) -> Dict[str, Any]:
    """Faz o pedido da fonte e devolve o que se conseguiu ver."""
    resultado: Dict[str, Any] = {
        "id": fonte["id"],
        "nome": fonte["nome"],
        "pais": fonte.get("pais", ""),
        "url": fonte["url"],
        "metodo": fonte.get("metodo", "GET"),
        "notas": fonte.get("notas", ""),
        "robots": _robots_permite(fonte["url"]),
        "template": fonte.get("template", ""),
    }
    cabecalhos = {
        "User-Agent": UA,
        "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
        "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8,es;q=0.7",
        "Referer": fonte["url"],
    }
    iniciado = time.perf_counter()
    try:
        if resultado["metodo"] == "POST" and fonte.get("json"):
            resposta = requests.post(fonte["url"], json=fonte["json"], headers=cabecalhos, timeout=TIMEOUT)
        elif resultado["metodo"] == "POST":
            resposta = requests.post(fonte["url"], data=fonte.get("form") or {}, headers=cabecalhos, timeout=TIMEOUT)
        else:
            resposta = requests.get(fonte["url"], headers=cabecalhos, timeout=TIMEOUT)
    except Exception as exc:  # noqa: BLE001 - uma fonte em baixo não trava a sonda
        resultado["estado"] = None
        resultado["erro"] = f"{type(exc).__name__}: {exc}"
        resultado["duracao_ms"] = int((time.perf_counter() - iniciado) * 1000)
        return resultado
    resultado["duracao_ms"] = int((time.perf_counter() - iniciado) * 1000)
    resultado["estado"] = resposta.status_code
    resultado["bytes"] = len(resposta.content)
    resultado["tipo"] = str(resposta.headers.get("content-type") or "")

    registos = _contar_registos(resposta, fonte)
    if registos is not None:
        resultado["registos"] = registos
    return resultado


def _contar_registos(resposta: requests.Response, fonte: Dict[str, Any]) -> Optional[int]:
    """Quantos registos traz a resposta: JSON (pela chave da fonte) ou Atom por `entry`."""
    tipo = str(resposta.headers.get("content-type") or "")
    if "json" in tipo or fonte.get("contagem"):
        try:
            dados = resposta.json()
        except Exception:
            return None
        chave = fonte.get("contagem")
        if not chave:
            return None
        valor = dados.get(chave)
        if isinstance(valor, list):
            return len(valor)
        if isinstance(valor, dict):
            return len(valor)
        return None
    if "xml" in tipo or "atom" in tipo:
        return resposta.text.count("<entry")
    return None


def _sondar_template(template_id: str, limit: int) -> Dict[str, Any]:
    """Corre o template verdadeiro sobre a página real e mede a cobertura dos campos."""
    resultado: Dict[str, Any] = {"template": template_id}
    try:
        source = templates.build_source(template_id)
        fonte = {**source, "detail": {**(source.get("detail") or {}), "enabled": False}}
        previsao = scraper.preview_source(fonte, limit=limit, max_pages=1)
    except Exception as exc:  # noqa: BLE001
        resultado["erro"] = f"{type(exc).__name__}: {exc}"
        return resultado
    resultado["ok"] = bool(previsao.get("ok"))
    resultado["erro"] = previsao.get("error")
    resultado["itens"] = previsao.get("total", 0)
    itens = previsao.get("items") or []
    cobertura: Dict[str, int] = {}
    for item in itens:
        dados = item.get("data") or {}
        for campo in fonte.get("fields", []):
            if dados.get(campo["name"]) not in (None, "", []):
                cobertura[campo["name"]] = cobertura.get(campo["name"], 0) + 1
    resultado["cobertura"] = cobertura
    resultado["amostra"] = [
        {"titulo": str(item.get("title") or "")[:90], "url": str(item.get("url") or "")[:110]}
        for item in itens[:2]
    ]
    return resultado


def _texto(fonte: Dict[str, Any], sonda: Optional[Dict[str, Any]]) -> str:
    """Relatório de uma fonte, para o ficheiro UTF-8."""
    linhas = ["=" * 100, f"{fonte['nome']} [{fonte.get('pais', '')}] {fonte['metodo']} {fonte['url']}"]
    robots = fonte.get("robots")
    linhas.append(
        f"  robots.txt: {'permite' if robots else 'recusa' if robots is False else 'ilegível (a recolha prossegue)'}"
        + f" · estado: {fonte.get('estado')} · {fonte.get('bytes', 0)} bytes · {fonte.get('tipo', '')}"
        + f" · {fonte.get('duracao_ms', 0)} ms"
    )
    if fonte.get("erro"):
        linhas.append(f"  erro: {fonte['erro']}")
    if fonte.get("registos") is not None:
        linhas.append(f"  registos encontrados: {fonte['registos']}")
    if fonte.get("notas"):
        linhas.append(f"  nota: {fonte['notas']}")
    if sonda:
        linhas.append(
            f"  template «{sonda['template']}»: ok={sonda.get('ok')} itens={sonda.get('itens')} "
            f"cobertura={sonda.get('cobertura')} {('erro: ' + str(sonda['erro'])) if sonda.get('erro') else ''}"
        )
        for amostra in sonda.get("amostra") or []:
            linhas.append(f"      · {amostra['titulo']}")
            linhas.append(f"        {amostra['url']}")
    return "\n".join(linhas)


def main() -> int:
    argumentos = [a for a in sys.argv[1:]]
    limite = 3
    if "--limit" in argumentos:
        limite = int(argumentos[argumentos.index("--limit") + 1])
    pedidos = [a for a in argumentos if not a.startswith("--") and not a.isdigit()]
    alvos = [fonte for fonte in FONTES if not pedidos or fonte["id"] in pedidos]
    if not alvos:
        print(f"Fonte desconhecida. Disponíveis: {', '.join(f['id'] for f in FONTES)}")
        return 2

    relatorios: List[Dict[str, Any]] = []
    blocos: List[str] = []
    for fonte in alvos:
        sonda = _pedido(fonte)
        if fonte.get("template"):
            sonda["sondagem_do_template"] = _sondar_template(fonte["template"], limite)
        relatorios.append(sonda)
        blocos.append(_texto(sonda, sonda.get("sondagem_do_template")))
        registos = sonda.get("registos")
        print(
            f"{fonte['id']:22s} estado={str(sonda.get('estado')):4s} "
            f"{sonda.get('bytes', 0):9d} bytes"
            + (f" registos={registos}" if registos is not None else "")
            + (f" itens={sonda['sondagem_do_template'].get('itens')}" if fonte.get("template") else "")
            + (f" {sonda['erro']}" if sonda.get("erro") else "")
        )

    RELATORIO.write_text(
        "Sonda de contratação pública (PT, UE, RU, ES)\n" + "\n".join(blocos) + "\n",
        encoding="utf-8",
    )
    (RAIZ / "_probe_contratacao_publica.json").write_text(
        json.dumps(relatorios, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nRelatórios: {RELATORIO.name} e _probe_contratacao_publica.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
