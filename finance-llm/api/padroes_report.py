"""Relatório da análise de uma empresa — **PDF, Excel e CSV**.

O conteúdo vem de `padroes_service.analise_empresa` (contratos, CPV, sinais,
relações) e, quando existe, da ficha redigida por IA e das páginas lidas no
browser. Os três formatos partilham a **mesma estrutura de secções**, pelo que
dizem exatamente o mesmo — a diferença é só o suporte:

- **PDF** — ReportLab, com a marca do IQ OS e tabelas que mudam de largura
  conforme os dados (retrato para fichas, paisagem quando há tabelas largas);
- **Excel** — openpyxl, com uma folha por bloco e o logótipo embutido;
- **CSV** — separador `;` com BOM UTF-8 (abre corretamente no Excel português).

O relatório é **auditável**: cada secção diz de que fonte vem e o que a amostra
não cobre. Nada é recalculado aqui — se a análise foi guardada no Elasticsearch,
o relatório pode ser emitido mais tarde com os mesmos números.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Sequence

from api import contribuintes_report as base
from api.elasticsearch_client import ROOT  # noqa: F401  (mantém a raiz do projeto coerente)

logger = logging.getLogger(__name__)

#: Formatos suportados (id → etiqueta, tipo MIME e extensão).
FORMATS: Dict[str, Dict[str, str]] = dict(base.FORMATS)

#: Contratos listados no relatório (o PDF não precisa de 1500 linhas para provar nada).
MAX_CONTRATOS_RELATORIO = 200


def _moeda(valor: Any) -> str:
    if not isinstance(valor, (int, float)):
        return "—"
    return f"{valor:,.2f} €".replace(",", " ").replace(".", ",")


def _numero(valor: Any) -> str:
    if not isinstance(valor, (int, float)):
        return "—"
    return f"{valor:,.0f}".replace(",", " ")


def _pct(valor: Any) -> str:
    if not isinstance(valor, (int, float)):
        return "—"
    return f"{valor * 100:.1f}%"


def _ratio(valor: Any) -> str:
    if not isinstance(valor, (int, float)):
        return "—"
    return f"{valor:.2f}×"


def _sigma(valor: Any) -> str:
    if not isinstance(valor, (int, float)):
        return "—"
    return f"σ {valor:.1f}"


def _nome_entidade(entidades: Dict[str, Dict[str, Any]], nif: Any, fallback: Any) -> str:
    """Nome do adjudicante pelo cadastro, com o que vem nos contratos como recuo."""
    ficha = entidades.get(str(nif)) or {}
    return str(ficha.get("nome") or fallback or "—")[:160]


def _seccoes_markdown(texto: str, *, prefixo: str = "") -> List[List[str]]:
    """Markdown da IA → pares (secção, corpo), para caber em tabela nos 3 formatos.

    O texto do modelo é longo: numa só célula estouraria a página do PDF. Aqui
    cada título vira uma linha, com o corpo correspondente ao lado.
    """
    linhas = str(texto or "").strip().splitlines()
    if not linhas:
        return []
    blocos: List[List[str]] = []
    titulo_atual: Optional[str] = None
    corpo: List[str] = []

    def fechar() -> None:
        if titulo_atual is None and not corpo:
            return
        bloco = "\n".join(corpo).strip()
        if titulo_atual or bloco:
            blocos.append([f"{prefixo}{titulo_atual or 'Notas'}", bloco or "—"])

    for linha in linhas:
        achado = re.match(r"^\s{0,3}#{1,4}\s+(.*)$", linha)
        if achado:
            fechar()
            titulo_atual = achado.group(1).strip()
            corpo = []
            continue
        corpo.append(linha)
    fechar()
    return blocos


def analise_sections(
    analise: Dict[str, Any],
    *,
    ficha_ia: Optional[str] = None,
    paginas: Optional[Sequence[Dict[str, Any]]] = None,
    notas: Optional[Sequence[str]] = None,
    entidades: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Secções do relatório de **uma empresa** (a matéria-prima dos três formatos)."""
    analise = analise or {}
    entidades = entidades or {}
    resumo = analise.get("resumo") or {}
    relacoes = analise.get("relacoes") or {}
    anos = analise.get("anos") or []
    titulo = analise.get("nome") or analise.get("nif") or "empresa"

    secoes: List[Dict[str, Any]] = []

    secoes.append(
        {
            "title": "Identificação",
            "rows": [
                ["Empresa", str(titulo)],
                ["NIF", str(analise.get("nif") or "—")],
                ["Portal", str(analise.get("pais_label") or analise.get("pais") or "—")],
                ["Período", f"{anos[0]}–{anos[1]}" if len(anos) >= 2 else "todos os anos"],
                [
                    "Filtros",
                    " / ".join(
                        item
                        for item in (
                            f"ano ≥ {analise.get('filtros', {}).get('ano_from')}" if analise.get("filtros", {}).get("ano_from") else None,
                            f"ano ≤ {analise.get('filtros', {}).get('ano_to')}" if analise.get("filtros", {}).get("ano_to") else None,
                        )
                        if item
                    )
                    or "sem filtros de ano",
                ],
                ["Contratos analisados", f"{_numero(analise.get('contratos_analisados'))} de {_numero(analise.get('contratos_total'))} registados"],
                ["CPV distintos", _numero(resumo.get("cpvs"))],
                ["Insolvência (CIRE)", "sim" if resumo.get("insolvente") else "sem registo"],
            ],
        }
    )

    ficha = analise.get("ficha") or {}
    if ficha:
        secoes.append(
            {
                "title": "Ficha de cadastro",
                "rows": [
                    ["Nome de cadastro", str(ficha.get("nome") or "—")],
                    ["Papéis", ", ".join(ficha.get("papeis") or []) or "—"],
                    ["Concelho", str(ficha.get("concelho") or "—")],
                    ["Contratos no cadastro", _numero(ficha.get("contratos"))],
                    ["Valor no cadastro", _moeda(ficha.get("valor"))],
                    ["Designações alternativas", " | ".join(ficha.get("alias") or []) or "—"],
                ],
            }
        )

    secoes.append(
        {
            "title": "Resumo do portefólio",
            "rows": [
                ["Valor adjudicado (amostra)", _moeda(resumo.get("valor_total"))],
                ["Valor mediano", _moeda(resumo.get("valor_mediano"))],
                ["Desvio mediano do preço base", _ratio(resumo.get("desvio_mediano"))],
                ["Taxa de ajuste direto", _pct(resumo.get("taxa_ajuste_direto"))],
                ["Taxa de aditivos (efetivo > 1,15×)", _pct(resumo.get("taxa_aditivo"))],
                ["Adjudicantes distintos", _numero(resumo.get("adjudicantes_distintos"))],
                ["Concentração no maior adjudicante", _pct(resumo.get("concentracao_adjudicante"))],
                ["Contratos com sinais de regra", _numero(resumo.get("contratos_com_sinais"))],
                ["Contratos atípicos no CPV (σ > 3,5)", _numero(resumo.get("contratos_atipicos_cpv"))],
                [
                    "Escalões de valor",
                    " · ".join(f"{faixa}: {_numero(quantidade)}" for faixa, quantidade in (resumo.get("escaloes") or {}).items()) or "—",
                ],
            ],
        }
    )

    if ficha_ia:
        secoes.append(
            {
                "title": "Ficha analítica (IA)",
                "columns": ["Secção", "Texto"],
                "rows": _seccoes_markdown(ficha_ia) or [["Ficha", ficha_ia[:4000]]],
            }
        )

    sinais = analise.get("sinais") or []
    if sinais:
        secoes.append(
            {
                "title": "Sinais de regra",
                "columns": ["Regra", "Severidade", "Contratos", "Taxa", "Exemplo", "Detalhe"],
                "rows": [
                    [
                        str(sinal.get("label") or sinal.get("padrao")),
                        str(sinal.get("severidade") or "—"),
                        _numero(sinal.get("contratos")),
                        _pct(sinal.get("taxa")),
                        str(((sinal.get("exemplos") or [{}])[0]).get("objeto") or "—")[:300],
                        str(((sinal.get("exemplos") or [{}])[0]).get("detalhe") or "—")[:200],
                    ]
                    for sinal in sinais
                ],
            }
        )

    reguas = {item.get("cpv"): item for item in (analise.get("reguas_cpv") or [])}
    if analise.get("por_cpv"):
        secoes.append(
            {
                "title": "Onde atua (CPV)",
                "columns": ["CPV", "Descrição", "Contratos", "Valor", "Ajuste direto", "Aditivos", "Ajuste direto no setor", "Pares (n)"],
                "rows": [
                    [
                        str(item.get("cpv") or "—"),
                        str(item.get("descricao") or "—")[:160],
                        _numero(item.get("contratos")),
                        _moeda(item.get("valor")),
                        _pct(item.get("taxa_ajuste_direto")),
                        _numero(item.get("aditivos")),
                        _pct((reguas.get(item.get("cpv")) or {}).get("taxa_ajuste_direto")),
                        _numero((reguas.get(item.get("cpv")) or {}).get("contratos")),
                    ]
                    for item in analise.get("por_cpv") or []
                ],
            }
        )

    if analise.get("adjudicantes"):
        secoes.append(
            {
                "title": "Entidades contratantes",
                "columns": ["Adjudicante", "NIF", "Tipo (cadastro)", "Concelho", "Contratos", "Valor", "Parte do valor"],
                "rows": [
                    [
                        str(item.get("nome") or "—")[:160],
                        str(item.get("nif") or "—"),
                        str((entidades.get(str(item.get("nif"))) or {}).get("tipo") or "—"),
                        str((entidades.get(str(item.get("nif"))) or {}).get("concelho") or "—"),
                        _numero(item.get("contratos")),
                        _moeda(item.get("valor")),
                        _pct((item.get("valor") or 0) / resumo["valor_total"]) if resumo.get("valor_total") else "—",
                    ]
                    for item in analise.get("adjudicantes") or []
                ],
            }
        )

    if analise.get("por_procedimento"):
        secoes.append(
            {
                "title": "Procedimentos",
                "columns": ["Procedimento", "Contratos", "Valor"],
                "rows": [
                    [str(item.get("procedimento") or "—")[:200], _numero(item.get("contratos")), _moeda(item.get("valor"))]
                    for item in analise.get("por_procedimento") or []
                ],
            }
        )

    if analise.get("por_ano"):
        secoes.append(
            {
                "title": "Evolução por ano",
                "columns": ["Ano", "Contratos", "Valor"],
                "rows": [[str(item.get("ano")), _numero(item.get("contratos")), _moeda(item.get("valor"))] for item in analise.get("por_ano") or []],
            }
        )

    pares = relacoes.get("empresas") or []
    if pares:
        secoes.append(
            {
                "title": "Outras empresas nos mesmos adjudicantes",
                "columns": ["Empresa", "NIF", "Adjudicante", "Contratos", "Valor"],
                "rows": [
                    [
                        str(item.get("nome") or "—")[:160],
                        str(item.get("nif") or "—"),
                        _nome_entidade(entidades, item.get("adjudicante"), item.get("adjudicante")),
                        _numero(item.get("contratos")),
                        _moeda(item.get("valor")),
                    ]
                    for item in pares[:30]
                ],
            }
        )

    cargos = relacoes.get("cargos_sociais") or []
    if cargos:
        secoes.append(
            {
                "title": "Órgãos sociais",
                "columns": ["Pessoa", "NIF", "Cargos"],
                "rows": [
                    [
                        str(pessoa.get("nome") or "—"),
                        str(pessoa.get("nif") or "—"),
                        ", ".join(
                            filter(
                                None,
                                {
                                    str(cargo.get("role_org") or cargo.get("role") or "")
                                    for cargo in (pessoa.get("cargos") or [])
                                },
                            )
                        )
                        or "—",
                    ]
                    for pessoa in cargos[:30]
                ],
            }
        )

    insolvencias = relacoes.get("insolvencias") or []
    if insolvencias:
        secoes.append(
            {
                "title": "Insolvências (CIRE)",
                "columns": ["Espécie", "Ato", "Data", "Tribunal", "Processo"],
                "rows": [
                    [
                        str(item.get("especie") or "—"),
                        str(item.get("ato") or "—"),
                        str(item.get("data") or "—")[:10],
                        str(item.get("tribunal") or "—"),
                        str(item.get("processo") or "—"),
                    ]
                    for item in insolvencias[:20]
                ],
            }
        )

    noticias = relacoes.get("noticias") or []
    if noticias:
        secoes.append(
            {
                "title": "Menções em notícias",
                "columns": ["Data", "Fonte", "Título", "Ligação"],
                "rows": [
                    [
                        str(noticia.get("data") or "—")[:10],
                        str(noticia.get("fonte") or noticia.get("canal") or "—"),
                        str(noticia.get("titulo") or "—")[:200],
                        str(noticia.get("url") or "—")[:200],
                    ]
                    for noticia in noticias[:30]
                ],
            }
        )

    contratos = analise.get("contratos") or []
    if contratos:
        secoes.append(
            {
                "title": f"Contratos analisados (até {MAX_CONTRATOS_RELATORIO})",
                "columns": [
                    "Id",
                    "Ano",
                    "Publicação",
                    "Objeto",
                    "CPV",
                    "Valor",
                    "Base",
                    "Efetivo",
                    "σ CPV",
                    "Concorrentes",
                    "Procedimento",
                    "Adjudicante",
                    "Sinais",
                ],
                "rows": [
                    [
                        str(item.get("id") or "—"),
                        str(item.get("ano") or "—"),
                        str(item.get("data_publicacao") or "—"),
                        str(item.get("objeto") or "—")[:300],
                        str(item.get("cpv") or "—"),
                        _moeda(item.get("valor")),
                        _ratio(item.get("ratio_base")),
                        _ratio(item.get("ratio_efetivo")),
                        _sigma(item.get("z_cpv")),
                        _numero(item.get("n_concorrentes")),
                        str(item.get("procedimento") or "—")[:120],
                        str(item.get("adjudicante") or "—")[:120],
                        ", ".join(str(razao.get("padrao") or "") for razao in (item.get("razoes") or [])),
                    ]
                    for item in contratos[:MAX_CONTRATOS_RELATORIO]
                ],
            }
        )

    if paginas:
        lidas = [pagina for pagina in paginas if pagina.get("ok")]
        if lidas:
            secoes.append(
                {
                    "title": "Páginas lidas no browser",
                    "columns": ["URL", "Título", "Caracteres", "Índice"],
                    "rows": [
                        [str(pagina.get("url"))[:300], str(pagina.get("titulo") or "—")[:200], _numero(pagina.get("chars")), "finance_scraped"]
                        for pagina in lidas[:MAX_CONTRATOS_RELATORIO]
                    ],
                }
            )

    fontes = [
        "Contratos públicos do portal (amostra analisada, não a totalidade).",
        "Cadastro de contribuintes (identificação e localização).",
        "PessoasIQ (órgãos sociais) e CIRE (insolvências), quando existirem.",
        "Notícias: leitor RSS, recolha por scraping e redes sociais.",
    ]
    if paginas:
        fontes.append("Páginas externas lidas no browser e indexadas em `finance_scraped`.")
    if ficha_ia:
        fontes.append("Ficha analítica redigida por modelo de linguagem a partir dos dados acima (só os factos fornecidos).")
    secoes.append(
        {
            "title": "Fontes e limitações",
            "rows": [["Fonte", texto] for texto in fontes]
            + [["Aviso", str(analise.get("aviso") or "—")]]
            + [["Nota", str(nota)] for nota in (notas or [])],
        }
    )
    return secoes


def empresa_report(
    analise: Dict[str, Any],
    *,
    format: str = "pdf",
    ficha_ia: Optional[str] = None,
    paginas: Optional[Sequence[Dict[str, Any]]] = None,
    notas: Optional[Sequence[str]] = None,
    entidades: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Relatório de uma empresa. Devolve `{filename, content, media_type, format}`."""
    if analise.get("error"):
        return {"error": f"A análise não está disponível: {analise['error']}"}
    nome = str(analise.get("nome") or analise.get("nif") or "empresa")
    titulo = f"Análise de padrões · {nome}"
    subtitulo = f"NIF {analise.get('nif') or '—'} · {analise.get('pais_label') or analise.get('pais') or 'PT'}"
    secoes = analise_sections(
        analise,
        ficha_ia=ficha_ia,
        paginas=paginas,
        notas=notas,
        entidades=entidades,
    )
    try:
        fmt, conteudo, media = base._render(format, title=titulo, subtitle=subtitulo, sections=secoes)  # noqa: SLF001
    except ValueError as exc:
        return {"error": str(exc)}
    except RuntimeError as exc:
        return {"error": f"Falta a dependência para gerar {format}: {exc}"}
    nome_ficheiro = f"iq-os-padroes-{base.slugify(nome, fallback='empresa')}_{base._stamp()}.{FORMATS[fmt]['extension']}"  # noqa: SLF001
    return {
        "filename": nome_ficheiro,
        "content": conteudo,
        "media_type": media,
        "format": fmt,
        "secoes": [secao["title"] for secao in secoes],
    }


def empresas_sections(conjunto: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Secções do relatório de **comparação** entre várias empresas."""
    conjunto = conjunto or {}
    empresas = conjunto.get("empresas") or []
    totais = conjunto.get("totais") or {}
    cruz = conjunto.get("cruzamentos") or {}
    filtros = conjunto.get("filtros") or {}
    anos = conjunto.get("anos")
    secoes: List[Dict[str, Any]] = []

    secoes.append(
        {
            "title": "Identificação do conjunto",
            "rows": [
                ["Empresas comparadas", str(totais.get("empresas") or len(empresas))],
                ["Empresas pedidas", str(totais.get("empresas_pedidas") or len(empresas))],
                ["Portal", str(conjunto.get("pais_label") or conjunto.get("pais") or "—")],
                [
                    "Filtros",
                    " · ".join(
                        item
                        for item in (
                            f"ano ≥ {filtros.get('ano_from')}" if filtros.get("ano_from") else None,
                            f"ano ≤ {filtros.get('ano_to')}" if filtros.get("ano_to") else None,
                            f"até {filtros.get('max_contratos')} contratos por empresa" if filtros.get("max_contratos") else None,
                        )
                        if item
                    )
                    or "sem filtros",
                ],
                ["Contratos analisados", f"{_numero(totais.get('contratos'))} (de {_numero(totais.get('contratos_total_portal'))} registados)"],
                ["Valor adjudicado (soma)", _moeda(totais.get("valor_total"))],
                ["Insolventes no conjunto", _numero(totais.get("insolventes"))],
                ["Empresas com sinais", _numero(totais.get("com_sinais"))],
                [
                    "Cruzamentos",
                    f"adjudicantes {_numero(totais.get('adjudicantes_comuns'))} · pessoas {_numero(totais.get('pessoas_comuns'))} · "
                    f"processos {_numero(totais.get('processos_comuns'))} · CPV {_numero(totais.get('cpvs_comuns'))}",
                ],
                ["Período", f"{anos[0]}–{anos[1]}" if isinstance(anos, list) and len(anos) >= 2 else "—"],
            ],
        }
    )

    secoes.append(
        {
            "title": "Comparação das empresas",
            "columns": [
                "Empresa",
                "NIF",
                "Contratos",
                "Valor",
                "Valor mediano",
                "Desvio",
                "Ajuste direto",
                "Aditivos",
                "Adjudicantes",
                "Concentração",
                "Atípicos CPV",
                "Sinais",
                "Severidade",
                "Insolvente",
            ],
            "rows": [
                [
                    str(linha.get("nome") or linha.get("nif"))[:120],
                    str(linha.get("nif") or "—"),
                    _numero((linha.get("resumo") or {}).get("contratos")),
                    _moeda((linha.get("resumo") or {}).get("valor_total")),
                    _moeda((linha.get("resumo") or {}).get("valor_mediano")),
                    _ratio((linha.get("resumo") or {}).get("desvio_mediano")),
                    _pct((linha.get("resumo") or {}).get("taxa_ajuste_direto")),
                    _pct((linha.get("resumo") or {}).get("taxa_aditivo")),
                    _numero((linha.get("resumo") or {}).get("adjudicantes_distintos")),
                    _pct((linha.get("resumo") or {}).get("concentracao_adjudicante")),
                    _numero((linha.get("resumo") or {}).get("contratos_atipicos_cpv")),
                    _numero((linha.get("resumo") or {}).get("contratos_com_sinais")),
                    str(linha.get("severidade") or "—"),
                    "sim" if (linha.get("resumo") or {}).get("insolvente") else "não",
                ]
                for linha in empresas
            ],
        }
    )

    sinais = [(linha, sinal) for linha in empresas for sinal in linha.get("sinais") or []]
    if sinais:
        secoes.append(
            {
                "title": "Sinais por empresa",
                "columns": ["Empresa", "Regra", "Severidade", "Contratos", "Taxa", "Exemplo"],
                "rows": [
                    [
                        str(linha.get("nome") or linha.get("nif"))[:100],
                        str(sinal.get("label") or sinal.get("padrao")),
                        str(sinal.get("severidade") or "—"),
                        _numero(sinal.get("contratos")),
                        _pct(sinal.get("taxa")),
                        str(sinal.get("exemplo") or sinal.get("detalhe") or "—")[:220],
                    ]
                    for linha, sinal in sinais
                ],
            }
        )

    if cruz.get("adjudicantes"):
        secoes.append(
            {
                "title": "Adjudicantes comuns (concorrência no mesmo cliente)",
                "columns": ["Adjudicante", "NIF", "Empresas do conjunto", "Contratos", "Valor"],
                "rows": [
                    [
                        str(item.get("nome") or "—")[:140],
                        str(item.get("nif") or "—"),
                        " | ".join(item.get("empresas_nome") or [])[:300],
                        _numero(item.get("contratos")),
                        _moeda(item.get("valor")),
                    ]
                    for item in cruz["adjudicantes"][:60]
                ],
            }
        )

    if cruz.get("pessoas"):
        secoes.append(
            {
                "title": "Pessoas comuns (órgãos sociais partilhados)",
                "columns": ["Pessoa", "NIF", "Cargos", "Empresas do conjunto"],
                "rows": [
                    [
                        str(item.get("nome") or "—"),
                        str(item.get("nif") or "—"),
                        ", ".join(item.get("cargos") or [])[:160] or "—",
                        " | ".join(item.get("empresas_nome") or [])[:300],
                    ]
                    for item in cruz["pessoas"][:60]
                ],
            }
        )

    if cruz.get("processos"):
        secoes.append(
            {
                "title": "Processos do CIRE partilhados",
                "columns": ["Processo", "Espécie", "Tribunal", "Data", "Empresas do conjunto"],
                "rows": [
                    [
                        str(item.get("processo") or "—"),
                        str(item.get("especie") or "—"),
                        str(item.get("tribunal") or "—"),
                        str(item.get("data") or "—")[:10],
                        " | ".join(item.get("empresas_nome") or [])[:300],
                    ]
                    for item in cruz["processos"][:60]
                ],
            }
        )

    if cruz.get("cpvs"):
        secoes.append(
            {
                "title": "CPV comuns (mesmo mercado)",
                "columns": ["CPV", "Descrição", "Empresas", "Contratos", "Valor"],
                "rows": [
                    [
                        str(item.get("cpv") or "—"),
                        str(item.get("descricao") or "—")[:160],
                        _numero(item.get("n_empresas")),
                        _numero(item.get("contratos")),
                        _moeda(item.get("valor")),
                    ]
                    for item in cruz["cpvs"][:60]
                ],
            }
        )

    if conjunto.get("por_cpv"):
        secoes.append(
            {
                "title": "Distribuição por CPV (conjunto)",
                "columns": ["CPV", "Descrição", "Empresas", "Contratos", "Valor"],
                "rows": [
                    [
                        str(item.get("cpv") or "—"),
                        str(item.get("descricao") or "—")[:160],
                        _numero(item.get("empresas")),
                        _numero(item.get("contratos")),
                        _moeda(item.get("valor")),
                    ]
                    for item in conjunto["por_cpv"]
                ],
            }
        )

    secoes.append(
        {
            "title": "Fontes e limitações",
            "rows": [
                ["Fonte", "Contratos públicos do portal — amostra por empresa, não a totalidade."],
                ["Fonte", "PessoasIQ (órgãos sociais) e CIRE (insolvências), quando existirem na amostra."],
                [
                    "Como ler os cruzamentos",
                    "Um adjudicante comum significa que as empresas concorrem no mesmo cliente; não significa, por si, "
                    "nenhum ilícito. Uma pessoa comum significa cargos de órgãos sociais registados em duas empresas.",
                ],
                ["Aviso", str(conjunto.get("aviso") or "—")],
            ]
            + [["Empresa ignorada", str(aviso)] for aviso in conjunto.get("avisos") or []],
        }
    )
    return secoes


def empresas_report(conjunto: Dict[str, Any], *, format: str = "pdf") -> Dict[str, Any]:
    """Relatório de comparação de várias empresas (`{filename, content, media_type}`)."""
    if conjunto.get("error"):
        return {"error": f"A comparação não está disponível: {conjunto['error']}"}
    empresas = conjunto.get("empresas") or []
    if not empresas:
        return {"error": "Sem empresas para relatar."}
    nomes = ", ".join(str(empresa.get("nome") or empresa.get("nif")) for empresa in empresas[:4])
    titulo = f"Comparação de empresas · {len(empresas)} empresas"
    subtitulo = f"{nomes}{' …' if len(empresas) > 4 else ''} · {conjunto.get('pais_label') or conjunto.get('pais') or 'PT'}"
    secoes = empresas_sections(conjunto)
    try:
        fmt, conteudo, media = base._render(format, title=titulo, subtitle=subtitulo, sections=secoes)  # noqa: SLF001
    except ValueError as exc:
        return {"error": str(exc)}
    except RuntimeError as exc:
        return {"error": f"Falta a dependência para gerar {format}: {exc}"}
    return {
        "filename": f"iq-os-padroes-comparacao_{len(empresas)}-empresas_{base._stamp()}.{FORMATS[fmt]['extension']}",  # noqa: SLF001
        "content": conteudo,
        "media_type": media,
        "format": fmt,
        "secoes": [secao["title"] for secao in secoes],
    }


def available() -> Dict[str, Any]:
    """Formatos e dependências disponíveis (diagnóstico)."""
    estado = base.available()
    return {
        **estado,
        "max_contratos": MAX_CONTRATOS_RELATORIO,
        "seccoes": [
            "Identificação",
            "Ficha de cadastro",
            "Resumo do portefólio",
            "Ficha analítica (IA)",
            "Sinais de regra",
            "Onde atua (CPV)",
            "Entidades contratantes",
            "Procedimentos",
            "Evolução por ano",
            "Outras empresas nos mesmos adjudicantes",
            "Órgãos sociais",
            "Insolvências (CIRE)",
            "Menções em notícias",
            "Contratos analisados",
            "Páginas lidas no browser",
            "Fontes e limitações",
        ],
    }
