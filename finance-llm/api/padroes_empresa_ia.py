"""Dados por **IA** e por **browser** para a análise de uma empresa.

O motor de padrões diz o que os dados mostram; este módulo acrescenta o que
**não está indexado** e escreve a ficha analítica:

1. **browser** — lê páginas públicas (site da empresa, portal de contratação,
   imprensa) com um agente HTTP próprio, extrai o texto útil e **indexa-o em
   `finance_scraped`**, para que a leitura fique pesquisável no IQ OS como
   qualquer outra recolha (mesma deduplicação por URL);
2. **factos** — reúne a análise da empresa (portefólio, CPV, sinais, relações) e
   o **enriquecimento das entidades** adjudicantes (tipo, localização, papéis no
   cadastro) num JSON compacto;
3. **ficha** — pede ao modelo configurado uma ficha em Markdown, com a regra de
   ferro: só usar o que foi fornecido e dizer o que não foi encontrado. Sem
   modelo disponível devolve-se a ficha **factual** (sem IA), construída com os
   mesmos números.

Nada aqui inventa dados: o texto lido é guardado com o URL de origem e a ficha
lista as fontes usadas, para poder ser auditada.
"""
from __future__ import annotations

import hashlib
import html as html_lib
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import httpx

from api.elasticsearch_client import (
    CONTRIBUINTES_INDEX,
    SCRAPED_INDEX,
    get_es_client,
    index_scraped_items,
)

logger = logging.getLogger(__name__)

#: Agente identificado (o mesmo critério das recolhas do módulo social).
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36 (compatible; IQOS-Padroes/1.0; +https://iqos.local)"
)

#: Limites do browser (evitam que uma página enorme domine o prompt do modelo).
MAX_PAGINAS = 8
MAX_CHARS_PAGINA = 6000
TIMEOUT = httpx.Timeout(20.0, connect=8.0)

#: Identidade da recolha nos índices (aparece em `finance_scraped.source_id`).
FONTE_ID = "padroes-empresa"
FONTE_NOME = "Padrões · pesquisa de empresa"

_SISTEMA = (
    "És analista de contratação pública e risco do IQ OS. Escreves em português de Portugal, "
    "com linguagem sóbria e verificável. Usa **apenas** os dados fornecidos (análise, factos das "
    "entidades e texto de páginas lidas no browser): não inventes contratos, valores, processos, "
    "nomes nem datas. Quando um dado não existir, escreve que não foi encontrado. Cada afirmação de "
    "risco tem de indicar a evidência que a sustenta (regra cumprida, contrato, par, menção) e a "
    "limitação da análise. Não dês aconselhamento jurídico nem juízos sobre pessoas."
)


# ---------------------------------------------------------------------------
# Browser
# ---------------------------------------------------------------------------
def _texto_limpo(html: str) -> Tuple[Optional[str], str]:
    """Título e texto legível de uma página HTML (sem scripts, estilos e menu)."""
    bruto = re.sub(r"<!--.*?-->", " ", html or "", flags=re.S)
    bruto = re.sub(r"<(script|style|noscript|svg|template)[^>]*>.*?</\1>", " ", bruto, flags=re.S | re.I)
    titulo = None
    achado = re.search(r"<title[^>]*>(.*?)</title>", bruto, flags=re.S | re.I)
    if achado:
        titulo = html_lib.unescape(re.sub(r"\s+", " ", achado.group(1))).strip()[:300] or None
    for candidato in (r"<main[^>]*>(.*?)</main>", r"<article[^>]*>(.*?)</article>", r"<body[^>]*>(.*?)</body>"):
        bloco = re.search(candidato, bruto, flags=re.S | re.I)
        if bloco:
            bruto = bloco.group(1)
            break
    bruto = re.sub(r"<(h[1-6])[^>]*>", r"\n\n## ", bruto, flags=re.I)
    bruto = re.sub(r"<li[^>]*>", "\n- ", bruto, flags=re.I)
    bruto = re.sub(r"</(p|div|tr|h[1-6]|li|section)>", "\n", bruto, flags=re.I)
    bruto = re.sub(r"<br\s*/?>", "\n", bruto, flags=re.I)
    texto = re.sub(r"<[^>]+>", " ", bruto)
    texto = html_lib.unescape(texto)
    texto = re.sub(r"[ \t\r\f\v]+", " ", texto)
    texto = re.sub(r"\n\s*\n\s*\n+", "\n\n", texto)
    linhas = [linha.strip() for linha in texto.split("\n")]
    # Uma página de menu dá muitas linhas de 1–2 palavras: só ficam as com conteúdo.
    linhas = [linha for linha in linhas if len(linha) > 40 or linha.startswith("##")]
    return titulo, "\n".join(linhas).strip()


def ler_url(url: str) -> Dict[str, Any]:
    """Lê uma página e devolve `{url, titulo, texto, chars, ok}` (nunca levanta)."""
    alvo = str(url or "").strip()
    if not alvo:
        return {"url": url, "ok": False, "erro": "URL vazio"}
    if not alvo.startswith(("http://", "https://")):
        alvo = f"https://{alvo}"
    try:
        with httpx.Client(follow_redirects=True, timeout=TIMEOUT, headers={"User-Agent": BROWSER_UA}) as client:
            resposta = client.get(alvo)
        tipo = resposta.headers.get("content-type") or ""
        if "html" not in tipo.lower() and "text" not in tipo.lower():
            return {"url": str(resposta.url), "ok": False, "erro": f"conteúdo não textual ({tipo or 'desconhecido'})"}
        titulo, texto = _texto_limpo(resposta.text)
        return {
            "url": str(resposta.url),
            "titulo": titulo,
            "texto": texto[:MAX_CHARS_PAGINA],
            "chars": len(texto),
            "status": resposta.status_code,
            "ok": bool(texto),
            "erro": None if texto else "sem texto legível",
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("Leitura de %s falhou: %s", alvo, exc)
        return {"url": alvo, "ok": False, "erro": str(exc)[:200]}


def browser_ler(
    urls: Sequence[str],
    *,
    limite: int = MAX_PAGINAS,
    indexar: bool = True,
    es: Any = None,
) -> Dict[str, Any]:
    """Lê uma lista de páginas em paralelo e (por omissão) indexa-as.

    A indexação usa `finance_scraped` com `item_id` derivado do URL, pelo que
    reler a mesma página **substitui** o documento em vez de o duplicar.
    """
    alvos: List[str] = []
    for url in urls or []:
        limpo = str(url or "").strip()
        if limpo and limpo not in alvos:
            alvos.append(limpo)
    alvos = alvos[: max(1, int(limite or MAX_PAGINAS))]
    if not alvos:
        return {"paginas": [], "lidas": 0, "indexadas": 0, "erro": "sem URLs"}

    with ThreadPoolExecutor(max_workers=min(4, len(alvos))) as pool:
        paginas = list(pool.map(ler_url, alvos))

    lidas = [pagina for pagina in paginas if pagina.get("ok")]
    indexadas = 0
    if indexar and lidas:
        run_id = f"padroes-empresa-{hashlib.sha1('|'.join(alvos).encode('utf-8')).hexdigest()[:10]}"
        itens = [
            {
                "item_id": f"padroes-empresa:{hashlib.sha1(str(pagina['url']).encode('utf-8')).hexdigest()[:16]}",
                "url": pagina["url"],
                "title": pagina.get("titulo") or pagina["url"],
                "summary": (pagina.get("texto") or "")[:500],
                "text": pagina.get("texto") or "",
                "tags": ["padroes", "empresa", "browser"],
                "data": {"origem": FONTE_ID},
            }
            for pagina in lidas
        ]
        resultado = index_scraped_items(FONTE_ID, FONTE_NOME, run_id, itens, trigger="padroes", es=es)
        indexadas = int(resultado.get("indexed_count") or 0)

    return {
        "paginas": paginas,
        "lidas": len(lidas),
        "indexadas": indexadas,
        "indice": SCRAPED_INDEX,
        "pareadas": [pagina["url"] for pagina in paginas if not pagina.get("ok")],
    }


# ---------------------------------------------------------------------------
# Factos das entidades adjudicantes
# ---------------------------------------------------------------------------
def dados_entidades(nifs: Iterable[str], *, es: Any = None, size: int = 40) -> Dict[str, Dict[str, Any]]:
    """Ficha de cadastro (tipo, localização, papéis) das entidades adjudicantes.

    Uma só consulta por `terms` — nunca uma por NIF — para o painel poder
    enriquecer até 40 adjudicantes sem multiplicar pedidos ao Elasticsearch.
    """
    chaves = [str(nif).strip() for nif in nifs or [] if str(nif or "").strip()]
    chaves = list(dict.fromkeys(chaves))[: max(1, int(size))]
    if not chaves:
        return {}
    client = es or get_es_client()
    if client is None:
        return {}
    body = {
        "size": len(chaves),
        "_source": ["nif", "name", "names", "type", "country", "location", "roles", "contracts_count", "contracts_value"],
        "query": {"terms": {"nif": chaves}},
    }
    try:
        resp = client.search(index=CONTRIBUINTES_INDEX, body=body)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Ficha de contribuintes indisponível: %s", exc)
        return {}
    saida: Dict[str, Dict[str, Any]] = {}
    for hit in ((resp.get("hits") or {}).get("hits")) or []:
        src = hit.get("_source") or {}
        nif = str(src.get("nif") or "").strip()
        if not nif:
            continue
        local = src.get("location") if isinstance(src.get("location"), dict) else {}
        saida[nif] = {
            "nif": nif,
            "nome": src.get("name"),
            "tipo": src.get("type"),
            "pais": src.get("country"),
            "concelho": local.get("concelho"),
            "distrito": local.get("distrito"),
            "papeis": list(src.get("roles") or [])[:8],
            "contratos": src.get("contracts_count"),
            "valor": src.get("contracts_value"),
        }
    return saida


# ---------------------------------------------------------------------------
# Factos para o modelo
# ---------------------------------------------------------------------------
def factos(analise: Dict[str, Any], *, entidades: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Resumo compacto da análise (o que o modelo pode afirmar sem inventar)."""
    entidades = entidades or {}
    resumo = analise.get("resumo") or {}
    adjudicantes = []
    for item in (analise.get("adjudicantes") or [])[:12]:
        nif = str(item.get("nif") or "")
        extra = entidades.get(nif) or {}
        adjudicantes.append(
            {
                "nif": nif or None,
                "nome": item.get("nome"),
                "contratos": item.get("contratos"),
                "valor": item.get("valor"),
                "tipo": extra.get("tipo"),
                "concelho": extra.get("concelho"),
            }
        )
    return {
        "empresa": {
            "nif": analise.get("nif"),
            "nome": analise.get("nome"),
            "pais": analise.get("pais_label") or analise.get("pais"),
            "anos": analise.get("anos"),
            "ficha_cadastro": analise.get("ficha"),
        },
        "portfolio": {
            "contratos_analisados": analise.get("contratos_analisados"),
            "contratos_registados": analise.get("contratos_total"),
            "valor_total": resumo.get("valor_total"),
            "valor_mediano": resumo.get("valor_mediano"),
            "escaloes": resumo.get("escaloes"),
            "desvio_mediano_preco_base": resumo.get("desvio_mediano"),
            "taxa_ajuste_direto": resumo.get("taxa_ajuste_direto"),
            "taxa_aditivo": resumo.get("taxa_aditivo"),
            "adjudicantes_distintos": resumo.get("adjudicantes_distintos"),
            "concentracao_no_maior_adjudicante": resumo.get("concentracao_adjudicante"),
            "contratos_com_sinais": resumo.get("contratos_com_sinais"),
            "contratos_atipicos_no_cpv": resumo.get("contratos_atipicos_cpv"),
            "insolvente_cire": resumo.get("insolvente"),
        },
        "por_ano": (analise.get("por_ano") or [])[:12],
        "por_cpv": (analise.get("por_cpv") or [])[:8],
        "reguas_cpv": (analise.get("reguas_cpv") or [])[:8],
        "procedimentos": (analise.get("por_procedimento") or [])[:8],
        "adjudicantes": adjudicantes,
        "sinais": [
            {
                "regra": sinal.get("padrao"),
                "etiqueta": sinal.get("label"),
                "severidade": sinal.get("severidade"),
                "contratos": sinal.get("contratos"),
                "exemplo": (sinal.get("exemplos") or [{}])[0].get("objeto"),
                "detalhe": (sinal.get("exemplos") or [{}])[0].get("detalhe"),
            }
            for sinal in (analise.get("sinais") or [])[:14]
        ],
        "contratos_de_maior_risco": [
            {
                "id": item.get("id"),
                "ano": item.get("ano"),
                "valor": item.get("valor"),
                "ratio_efetivo": item.get("ratio_efetivo"),
                "z_cpv": item.get("z_cpv"),
                "cpv": item.get("cpv"),
                "adjudicante": item.get("adjudicante"),
                "procedimento": item.get("procedimento"),
                "objeto": (item.get("objeto") or "")[:200],
                "sinais": [razao.get("padrao") for razao in (item.get("razoes") or [])],
            }
            for item in (analise.get("contratos") or [])[:15]
        ],
        "relacoes": {
            "mesmos_adjudicantes": (analise.get("relacoes") or {}).get("empresas", [])[:15],
            "cargos_sociais": (analise.get("relacoes") or {}).get("cargos_sociais", [])[:15],
            "insolvencias": (analise.get("relacoes") or {}).get("insolvencias", [])[:10],
            "noticias": [
                {"titulo": noticia.get("titulo"), "fonte": noticia.get("fonte"), "data": noticia.get("data")}
                for noticia in ((analise.get("relacoes") or {}).get("noticias") or [])[:12]
            ],
        },
        "regras_ativas": [regra.get("label") or regra.get("id") for regra in (analise.get("regras_ativas") or [])],
    }


def _prompt(factos_json: Dict[str, Any], paginas: Sequence[Dict[str, Any]]) -> str:
    import json  # noqa: PLC0415

    partes = [
        "Escreve a **ficha de análise de risco** desta empresa adjudicatária, em Markdown, com as secções:\n"
        "1. **Síntese** (4–6 linhas: o que a empresa é, dimensão do portefólio e nível de risco);\n"
        "2. **Portefólio e concorrência** (valores, ajuste direto, aditivos, número de adjudicantes, concentração);\n"
        "3. **Onde atua (CPV)** — o que é normal no setor e onde esta empresa se afasta;\n"
        "4. **Sinais de regra** — cada um com o número de contratos e um exemplo concreto;\n"
        "5. **Entidades contratantes** — quem compra e o que isso sugere;\n"
        "6. **Relações** (pares nos mesmos adjudicantes, gerentes, insolvências, menções públicas);\n"
        "7. **O que verificar a seguir** (perguntas concretas, com o dado que as fecha);\n"
        "8. **Limitações desta análise** (amostra, o que não está registado).\n\n"
        "Regras: não inventes nada; usa os números exatos; se um ponto não tiver dados, escreve «não foi "
        "encontrado»; distingue sempre o que é **facto indexado** do que é **leitura da página web** "
        "(indica o URL).\n\n"
        "DADOS (JSON):\n" + json.dumps(factos_json, ensure_ascii=False, default=str)[:16000]
    ]
    if paginas:
        blocos = []
        for pagina in paginas[:6]:
            blocos.append(
                f"— URL: {pagina.get('url')}\n"
                f"  título: {pagina.get('titulo') or '(sem título)'}\n"
                f"  texto: {(pagina.get('texto') or '')[:3500]}"
            )
        partes.append("\n\nPÁGINAS LIDAS NO BROWSER (fontes externas, citar o URL):\n" + "\n\n".join(blocos))
    return "\n".join(partes)


def factual_markdown(analise: Dict[str, Any]) -> str:
    """Ficha **sem IA** (o recuo quando não há modelo configurado)."""
    resumo = analise.get("resumo") or {}
    linhas = [
        f"# Análise de padrões · {analise.get('nome') or analise.get('nif')}",
        "",
        f"- **NIF:** {analise.get('nif')}",
        f"- **Portal:** {analise.get('pais_label') or analise.get('pais')}",
        f"- **Contratos analisados:** {analise.get('contratos_analisados')} de {analise.get('contratos_total')} registados",
        f"- **Valor adjudicado (amostra):** {resumo.get('valor_total'):,.2f} €".replace(",", " ")
        if isinstance(resumo.get("valor_total"), (int, float))
        else "- **Valor adjudicado (amostra):** não disponível",
        f"- **Ajuste direto:** {(resumo.get('taxa_ajuste_direto') or 0) * 100:.1f}% · "
        f"**aditivos:** {(resumo.get('taxa_aditivo') or 0) * 100:.1f}%",
        f"- **Adjudicantes distintos:** {resumo.get('adjudicantes_distintos')} · "
        f"**concentração no maior:** {(resumo.get('concentracao_adjudicante') or 0) * 100:.1f}%",
        f"- **Contratos com sinais de regra:** {resumo.get('contratos_com_sinais')} · "
        f"**atípicos no CPV:** {resumo.get('contratos_atipicos_cpv')}",
        f"- **Insolvência (CIRE):** {'sim' if resumo.get('insolvente') else 'sem registo'}",
        "",
        "## Sinais de regra",
        "",
    ]
    for sinal in analise.get("sinais") or []:
        exemplo = (sinal.get("exemplos") or [{}])[0]
        linhas.append(
            f"- **{sinal.get('label') or sinal.get('padrao')}** ({sinal.get('severidade')}): "
            f"{sinal.get('contratos')} contratos. Exemplo: {exemplo.get('objeto') or '—'}"
        )
    if not (analise.get("sinais") or []):
        linhas.append("- Nenhuma regra ativa se aplica aos contratos analisados.")
    linhas += ["", "## Entidades contratantes", ""]
    for item in (analise.get("adjudicantes") or [])[:10]:
        linhas.append(f"- {item.get('nome') or item.get('nif')} — {item.get('contratos')} contratos")
    linhas += ["", "## Onde atua (CPV)", ""]
    for item in (analise.get("por_cpv") or [])[:8]:
        linhas.append(f"- CPV {item.get('cpv')} ({item.get('descricao') or '—'}) — {item.get('contratos')} contratos")
    linhas += [
        "",
        "*Ficha montada apenas com factos do IQ OS (sem modelo de IA). Inclui a amostra analisada, "
        "não a totalidade dos contratos da empresa.*",
    ]
    return "\n".join(linhas)


async def ficha_ia(
    analise: Dict[str, Any],
    *,
    paginas: Sequence[Dict[str, Any]] = (),
    entidades: Optional[Dict[str, Dict[str, Any]]] = None,
    session: Any = None,
    backend: Optional[str] = None,
    max_tokens: int = 2200,
) -> Dict[str, Any]:
    """Ficha analítica da empresa (IA quando há modelo; senão, factual)."""
    factos_json = factos(analise, entidades=entidades)
    saida: Dict[str, Any] = {
        "mode": "factual",
        "text": factual_markdown(analise),
        "backend": None,
        "notes": [],
        "warnings": [],
        "factos": factos_json,
        "paginas": [
            {"url": pagina.get("url"), "titulo": pagina.get("titulo"), "chars": pagina.get("chars")}
            for pagina in paginas
            if pagina.get("ok")
        ],
    }
    if not analise or analise.get("error"):
        saida["warnings"].append("Sem análise válida: ficha factual vazia.")
        return saida
    try:
        from api import ontology_ai as ai  # noqa: PLC0415
        from api import people_360  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        saida["warnings"].append(f"IA indisponível ({exc}).")
        return saida
    try:
        escolhido, nota = people_360.resolve_backend(session, backend)
    except Exception as exc:  # noqa: BLE001
        saida["warnings"].append(f"IA indisponível ({exc}).")
        return saida
    if nota:
        saida["notes"].append(nota)
    saida["backend"] = {
        "kind": escolhido.get("kind"),
        "provider": escolhido.get("provider"),
        "model": escolhido.get("model"),
    }
    if escolhido.get("kind") != "cloud":
        saida["notes"].append(escolhido.get("note") or "Sem modelo configurado: ficha montada só com factos.")
        return saida
    try:
        texto = await ai.ask_model(
            escolhido,
            system=_SISTEMA,
            prompt=_prompt(factos_json, paginas),
            max_tokens=max_tokens,
            temperature=0.2,
        )
    except Exception as exc:  # noqa: BLE001
        saida["warnings"].append(f"A IA falhou ({exc}); ficha factual.")
        return saida
    if not texto:
        saida["warnings"].append("A IA devolveu texto vazio; ficha factual.")
        return saida
    saida["mode"] = "ai"
    saida["text"] = texto
    saida["notes"].append(
        f"Ficha redigida por {escolhido.get('provider')}:{escolhido.get('model')} a partir da análise e de "
        f"{len(saida['paginas'])} página(s) lidas no browser."
    )
    return saida


def disponivel() -> Dict[str, Any]:
    """Estado do módulo (browser e dependências) para o `/meta` e diagnóstico."""
    import httpx as _httpx  # noqa: PLC0415

    return {
        "browser": {"cliente": f"httpx {_httpx.__version__}", "max_paginas": MAX_PAGINAS, "max_chars": MAX_CHARS_PAGINA},
        "indice_recolha": SCRAPED_INDEX,
        "fonte": FONTE_ID,
    }
