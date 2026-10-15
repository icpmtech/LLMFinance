"""Fotografia do **modelo de remunerações da Administração Pública** para o CMS.

A página pública do modelo não inventa números: mostra o que o quadro da DGAEP
do ano escolhido publica. Este módulo é a ponte entre o serviço (que lê os PDF)
e o documento do CMS — lê o modelo do ano, resume-o e devolve tudo o que a
página precisa de desenhar:

- `opcoes()` — anos recolhidos e o que a página pode mostrar;
- `dados_do_ano(ano)` — a fotografia: parâmetros (BRAP), Tabela Remuneratória
  Única, série entre anos, carreiras com posições, dirigentes, notas e base
  legal, mais as contagens;
- `descricao_dos_dados(dados)` / `resumo_dos_dados(dados)` — o que a página diz
  em texto, para o excerto, a `meta description` e o painel do CMS.

A leitura é **verificável**: cada linha diz de que secção do documento veio, e o
que o quadro não publica (suplementos, subsídio de refeição) é declarado como
fora do modelo em vez de ser estimado.

As **secções da página** (título, subtítulo, ordem e o que está ligado) vivem em
`cms_store` — este módulo só lhes dá os valores por omissão, para o editor e a
página pública dizerem o mesmo.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from api import cms_store as store
from api import remuneracoes_ap_service as ap

#: Quantas linhas de cada quadro a fotografia guarda (a página lista estas).
LIMITE_CARREIRAS = 60
LIMITE_POSICOES = 14
LIMITE_DIRIGENTES = 60


def opcoes() -> Dict[str, Any]:
    """Anos recolhidos e partes que a página pode mostrar."""
    return {
        "anos": ap.anos_disponiveis(),
        "ano": ap.ano_de_referencia(),
        "mostrar": _mostrar_opcoes(),
        "estilos": [{"id": chave, "label": rotulo} for chave, rotulo in store.ESTILOS_REMUNERACOES],
        "seccoes": ap.secao_carreiras() if ap.ano_de_referencia() else [],
        "parametros": ap.parametros_do_ano(),
        "fonte": ap.FONTE,
        "fonte_url": ap.FONTE_URL,
        "pagamentos_por_ano": ap.PAGAMENTOS_POR_ANO,
        "limites": {
            "carreiras": LIMITE_CARREIRAS,
            "posicoes": LIMITE_POSICOES,
            "dirigentes": LIMITE_DIRIGENTES,
        },
    }


def _mostrar_opcoes() -> List[Dict[str, Any]]:
    """As secções da página, iguais às do CMS (`cms_store`).

    Cada uma vem com o `id` (a chave guardada no documento), o `label` do
    interruptor e os **títulos por omissão** — o editor mostra-os como exemplo
    do que a página diz quando não reescreve nada.
    """
    return [
        {"id": chave, "label": titulo, "titulo": titulo, "sub": sub}
        for chave, titulo, sub in store.SECCOES_REMUNERACOES
    ]


def _serie_da_pagina() -> List[Dict[str, Any]]:
    """As linhas da série que a página compara: o nível 5 (BRAP) e o último nível.

    A página lê a evolução **ano a ano** de dois pontos da tabela. Guardar as
    últimas 60 linhas era guardar sessenta níveis que ninguém vê e deixar de
    fora, precisamente, o nível 5 — o gráfico saía a zeros.
    """
    linhas = ap.serie_dos_niveis()
    if not linhas:
        return []
    alvos = [5, max(int(linha.get("nivel") or 0) for linha in linhas)]
    return [
        linha
        for alvo in dict.fromkeys(alvos)
        for linha in linhas
        if int(linha.get("nivel") or 0) == alvo
    ]


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def dados_do_ano(ano: Optional[int] = None) -> Dict[str, Any]:
    """A fotografia do modelo de um ano, pronta a guardar no documento do CMS."""
    alvo = ap.ano_de_referencia(ano)
    if not alvo:
        return {"error": "Ainda não há nenhum ano recolhido da DGAEP.", "anos": ap.anos_disponiveis()}
    modelo = ap.ler_modelo(alvo)
    if not modelo:
        return {"error": f"Modelo de {alvo} ilegível.", "anos": ap.anos_disponiveis()}

    carreiras = modelo.get("carreiras") or []
    dirigentes = modelo.get("dirigentes") or []
    return {
        "ano": alvo,
        "versao": modelo.get("versao"),
        "contagens": modelo.get("contagens") or {},
        "parametros": ap.parametros_do_ano(alvo),
        "niveis": modelo.get("niveis") or [],
        "tru_notas": modelo.get("tru_notas") or [],
        "serie": _serie_da_pagina(),
        "seccoes": ap.secao_carreiras(alvo),
        "carreiras": [_carreira(item) for item in carreiras[:LIMITE_CARREIRAS]],
        "dirigentes": [_dirigente(item) for item in dirigentes[:LIMITE_DIRIGENTES]],
        "notas": [
            {"seccao": nota.get("seccao"), "texto": (nota.get("texto") or [])[:60]}
            for nota in (modelo.get("notas") or [])
        ],
        "base_legal": [
            {
                "seccao": tabela.get("seccao"),
                "linhas": [
                    {
                        "carreira": linha.get("Designação da carreira"),
                        "grau": linha.get("Grau"),
                        "estrutura_carreira": linha.get("Legislação - Estrutura da carreira"),
                        "estrutura_remuneratoria": linha.get("Legislação - Estrutura remuneratória"),
                        "outras_componentes": linha.get("Legislação - Outras componentes remuneratórias"),
                    }
                    for linha in (tabela.get("linhas") or [])
                    if linha.get("Designação da carreira")
                ][:40],
            }
            for tabela in (modelo.get("base_legal") or [])
        ],
        "fonte": {
            "documento": ap.FONTE,
            "url": (modelo.get("fonte") or {}).get("url"),
            "catalogo": ap.FONTE_URL,
            "ficheiro": (modelo.get("fonte") or {}).get("ficheiro"),
        },
        "gerado_em": _agora(),
    }


def _carreira(item: Dict[str, Any]) -> Dict[str, Any]:
    """Uma carreira com as suas posições (só o que a página mostra)."""
    return {
        "seccao": item.get("seccao"),
        "carreira": item.get("carreira"),
        "categoria": item.get("categoria"),
        "variante": item.get("variante"),
        "minimo": item.get("minimo"),
        "maximo": item.get("maximo"),
        "posicoes": [
            {
                "posicao": posicao.get("posicao"),
                "nivel": posicao.get("nivel"),
                "niveis_texto": posicao.get("niveis_texto"),
                "remuneracao": posicao.get("remuneracao"),
            }
            for posicao in (item.get("posicoes") or [])[:LIMITE_POSICOES]
        ],
    }


def _dirigente(item: Dict[str, Any]) -> Dict[str, Any]:
    """Um cargo dirigente (só o que a página mostra)."""
    return {
        "ambito": item.get("ambito"),
        "grupo": item.get("grupo"),
        "cargo": item.get("cargo"),
        "indice": item.get("indice"),
        "niveis_texto": item.get("niveis_texto"),
        "remuneracao": item.get("remuneracao"),
    }


def artigo_do_modelo(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Rascunho do artigo de blog que anuncia a página do modelo.

    O artigo não copia o quadro (é longo e muda quando a DGAEP publica outro):
    diz o que o ano traz, com os números que a página publica, e **liga para
    lá**. O título, o resumo e o corpo são editáveis no blog como em qualquer
    artigo — isto são só os valores de partida.
    """
    dados = doc.get("dados") if isinstance(doc.get("dados"), dict) else {}
    ano = dados.get("ano") or doc.get("ano")
    contagens = dados.get("contagens") or {}
    parametros = dados.get("parametros") or {}
    fonte = dados.get("fonte") or {}
    pagina = f"/site/remuneracoes/{doc.get('slug')}" if doc.get("slug") else "/site"
    destaques = [
        ("BRAP (nível 5 da TRU)", _euros(parametros.get("brap"))),
        ("Níveis da TRU", str(contagens.get("niveis") or "—")),
        ("Carreiras e categorias", str(contagens.get("carreiras") or "—")),
        ("Posições remuneratórias", str(contagens.get("posicoes") or "—")),
        ("Cargos dirigentes e equiparados", str(contagens.get("dirigentes") or "—")),
    ]
    corpo = [
        f"O quadro da DGAEP de {ano} está publicado: a Tabela Remuneratória Única, as carreiras com as "
        "suas posições remuneratórias e os cargos dirigentes da administração pública.",
        "",
        *[f"- **{rotulo}:** {valor}" for rotulo, valor in destaques],
        "",
        f"[Ver o quadro de {ano} completo]({pagina})",
        "",
    ]
    if fonte.get("documento"):
        corpo.append(f"Fonte: {fonte['documento']}" + (f" — {fonte['url']}" if fonte.get("url") else ""))
    return {
        "title": f"Remunerações da Administração Pública {ano}: o que o quadro da DGAEP mostra",
        "slug": f"remuneracoes-administracao-publica-{ano}",
        "excerpt": str(doc.get("excerpt") or resumo_dos_dados(dados)),
        "markdown": "\n".join(corpo),
        "tags": ["remunerações", "administração pública", "DGAEP"],
    }


def descricao_dos_dados(dados: Optional[Dict[str, Any]]) -> str:
    """Frase legível da fotografia («quadro de 2025 da DGAEP: …»)."""
    dados = dados if isinstance(dados, dict) else {}
    if not dados or dados.get("error"):
        return str((dados or {}).get("error") or "sem modelo lido")
    contagens = dados.get("contagens") or {}
    brap = (dados.get("parametros") or {}).get("brap")
    partes = [
        f"quadro da DGAEP de {dados.get('ano')}",
        f"{contagens.get('niveis', 0)} níveis na TRU",
    ]
    if brap:
        partes.append(f"BRAP de {_euros(brap)}")
    partes.append(f"{contagens.get('carreiras', 0)} carreiras/categorias")
    partes.append(f"{contagens.get('dirigentes', 0)} cargos dirigentes")
    return "; ".join(partes) + "."


def resumo_dos_dados(dados: Optional[Dict[str, Any]]) -> str:
    """Resumo factual para o painel do CMS e para a IA (uma linha)."""
    dados = dados if isinstance(dados, dict) else {}
    if not dados or dados.get("error"):
        return str((dados or {}).get("error") or "Sem modelo lido.")
    contagens = dados.get("contagens") or {}
    parametros = dados.get("parametros") or {}
    return (
        f"quadro de {dados.get('ano')} ({dados.get('versao') or 'sem data de atualização'}) · "
        f"{contagens.get('niveis', 0)} níveis · "
        f"{contagens.get('posicoes', 0)} posições remuneratórias · "
        f"{contagens.get('dirigentes', 0)} cargos dirigentes · "
        f"BRAP {_euros(parametros.get('brap'))}"
    )


def _euros(valor: Any) -> str:
    try:
        return f"{float(valor):,.2f}".replace(",", " ").replace(".", ",") + " €"
    except (TypeError, ValueError):
        return "—"
