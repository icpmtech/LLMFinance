"""Relatório **PDF do benchmark** (empresa, mercado ou entre países).

Este módulo é o que transforma um pedido pago na área «Relatórios» num PDF: o
cliente escolhe o que quer ver (uma empresa num CPV, o quadro por CPV dos três
países, ou o cruzamento de empresas de países diferentes) e o documento é
**calculado a partir das mesmas agregações das páginas** — não há uma segunda
implementação dos números.

Estrutura:

- `normalise(params)` — valida e arruma o pedido (é o que fica guardado no
  pedido de relatório, para o PDF poder ser reemitido mais tarde com os mesmos
  parâmetros);
- `build(params)` — corre o serviço do benchmark e devolve os dados;
- `sections(params, dados, …)` — a matéria-prima dos três formatos (o PDF usa o
  mesmo renderizador da casa, com o logótipo e o rodapé do IQ OS);
- `render(params, …)` — devolve `(nome do ficheiro, bytes, mime)`.

Os valores são sempre em euros e as datas em ISO 8601, como no resto do módulo.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Sequence

from api import benchmark_countries as bc
from api import benchmark_service as bench
from api import contribuintes_report as base

logger = logging.getLogger(__name__)

#: Modos de relatório: uma empresa, o quadro por CPV dos três países, ou o
#: cruzamento de empresas de países diferentes.
MODES: Dict[str, str] = {
    "empresa": "Benchmark de uma empresa",
    "mercado": "Benchmark por CPV (três países)",
    "cruzar": "Benchmark entre países (empresas cruzadas)",
}

#: Máximo de empresas cruzadas num relatório (igual ao limite da página).
MAX_ENTITIES = bench.MAX_CROSS
#: Máximo de CPV listados por secção.
MAX_CPV = 40
#: Máximo de linhas por secção (o PDF não precisa de milhares de linhas).
MAX_ROWS = 40

CPV_RE = re.compile(r"^[0-9]{2,10}(-[0-9])?$")


def _texto(value: Any, limit: int = 200) -> str:
    return " ".join(str(value or "").split())[:limit]


def _ano(value: Any) -> Optional[int]:
    try:
        numero = int(value)
    except (TypeError, ValueError):
        return None
    return numero if 1990 <= numero <= 2100 else None


def normalise(params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Valida os parâmetros do relatório e devolve-os limpos.

    É chamado **antes** de o pedido ser criado (para o erro aparecer ao cliente,
    com uma mensagem clara) e outra vez quando o PDF é produzido.
    """
    dados = dict(params or {})
    modo = _texto(dados.get("mode") or "empresa", 20).lower()
    if modo not in MODES:
        raise ValueError("Modo de relatório inválido (use empresa, mercado ou cruzar).")
    role = _texto(dados.get("role") or bc.SUPPLIER, 20).lower()
    if role not in bench.ROLES:
        role = bc.SUPPLIER
    country = bc.country_key(dados.get("country") or "pt")
    cpv = _texto(dados.get("cpv_code"), 20)
    if cpv and not CPV_RE.match(cpv):
        raise ValueError("CPV inválido: use um prefixo numérico (ex.: 33600000 ou 33600).")
    ano_de = _ano(dados.get("year_from"))
    ano_ate = _ano(dados.get("year_to"))
    if ano_de and ano_ate and ano_de > ano_ate:
        ano_de, ano_ate = ano_ate, ano_de

    limpos: Dict[str, Any] = {
        "mode": modo,
        "role": role,
        "cpv_code": cpv,
        "year_from": ano_de,
        "year_to": ano_ate,
    }

    if modo in {"empresa", "cruzar"}:
        nif = _texto(dados.get("nif"), 40)
        nome = _texto(dados.get("name"), 200)
        if modo == "empresa" and not (nif or nome):
            raise ValueError("Indique a empresa (NIF ou nome) do relatório.")
        if modo == "empresa":
            limpos["country"] = country
            limpos["nif"] = nif
            limpos["name"] = nome
            limpos["region"] = _texto(dados.get("region"), 80)
        else:
            entidades: List[Dict[str, Any]] = []
            for alvo in dados.get("entities") or []:
                if not isinstance(alvo, dict):
                    continue
                nif_alvo = _texto(alvo.get("nif"), 40)
                nome_alvo = _texto(alvo.get("name"), 200)
                if not (nif_alvo or nome_alvo):
                    continue
                entidades.append(
                    {
                        "country": bc.country_key(alvo.get("country") or "pt"),
                        "nif": nif_alvo,
                        "name": nome_alvo,
                    }
                )
                if len(entidades) >= MAX_ENTITIES:
                    break
            if len(entidades) < 2:
                raise ValueError("Indique pelo menos duas empresas para cruzar.")
            limpos["entities"] = entidades
    else:  # mercado
        pedidos = dados.get("countries") or []
        escolhidos = [bc.country_key(item) for item in pedidos if str(item or "").strip()]
        escolhidos = [item for item in bc.COUNTRIES if item in escolhidos] or list(bc.COUNTRIES)
        limpos["countries"] = escolhidos
        try:
            limpos["top"] = max(5, min(int(dados.get("top") or 40), 200))
        except (TypeError, ValueError):
            limpos["top"] = 40

    return limpos


def titulo(params: Dict[str, Any]) -> str:
    """Título legível do relatório («Benchmark Portugal · CPV 33600000»)."""
    partes = ["Benchmark"]
    if params["mode"] == "empresa":
        partes.append(bc.dialect(params.get("country"))["label"])
        alvo = params.get("name") or params.get("nif") or ""
        if alvo:
            partes.append(_texto(alvo, 80))
    elif params["mode"] == "cruzar":
        nomes = [alvo.get("name") or alvo.get("nif") or "" for alvo in params.get("entities") or []]
        partes.append(" · ".join(_texto(nome, 28) for nome in nomes[:3]))
        if len(nomes) > 3:
            partes.append(f"+{len(nomes) - 3}")
    else:
        partes.append("Portugal, Espanha e França")
    if params.get("cpv_code"):
        partes.append(f"CPV {params['cpv_code']}")
    if params.get("year_from") or params.get("year_to"):
        partes.append(f"{params.get('year_from') or '…'}–{params.get('year_to') or '…'}")
    return " · ".join(item for item in partes if item)


def subtitulo(params: Dict[str, Any], *, reference: str = "", requester: str = "") -> str:
    """Linha de contexto do cabeçalho (papel, janela de anos, pedido)."""
    papel = "quem vende" if params.get("role") == bc.SUPPLIER else "quem compra"
    partes = [MODES.get(params["mode"], "Benchmark"), f"{papel} ao Estado"]
    if params.get("year_from") or params.get("year_to"):
        partes.append(f"anos {params.get('year_from') or '…'}–{params.get('year_to') or '…'}")
    if params["mode"] == "empresa" and params.get("region"):
        partes.append(f"região {params['region']}")
    if reference:
        partes.append(f"pedido {reference}")
    if requester:
        partes.append(requester)
    return " · ".join(partes)


def build(params: Dict[str, Any], *, es: Any = None) -> Dict[str, Any]:
    """Corre a análise do benchmark e devolve os dados do relatório."""
    modo = params["mode"]
    if modo == "empresa":
        resultado = bench.benchmark_entity(
            nif=params.get("nif") or None,
            name=params.get("name") or None,
            role=params["role"],
            country=params.get("country") or "pt",
            cpv_code=params.get("cpv_code") or None,
            year_from=params.get("year_from"),
            year_to=params.get("year_to"),
            region=params.get("region") or None,
            top=MAX_ROWS,
            es=es,
        )
        if not (isinstance(resultado, dict) and resultado.get("error")):
            # As duas leituras de valor acrescentado (anomalias e o que os
            # compradores compram sem esta empresa) entram no PDF; se falharem,
            # o relatório sai sem elas em vez de não sair.
            try:
                resultado["anomalies"] = bench.benchmark_anomalies(
                    nif=params.get("nif") or None,
                    name=params.get("name") or None,
                    role=params["role"],
                    country=params.get("country") or "pt",
                    cpv_code=params.get("cpv_code") or None,
                    year_from=params.get("year_from"),
                    year_to=params.get("year_to"),
                    region=params.get("region") or None,
                    es=es,
                )
            except Exception as exc:  # noqa: BLE001 - o relatório não pode falhar por isto
                logger.warning("Sem anomalias no relatório: %s", exc)
            try:
                resultado["gaps"] = bench.benchmark_gaps(
                    nif=params.get("nif") or None,
                    name=params.get("name") or None,
                    role=params["role"],
                    country=params.get("country") or "pt",
                    year_from=params.get("year_from"),
                    year_to=params.get("year_to"),
                    region=params.get("region") or None,
                    es=es,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Sem oportunidades no relatório: %s", exc)
            try:
                resultado["price_risk"] = bench.benchmark_price_risk(
                    nif=params.get("nif") or None,
                    name=params.get("name") or None,
                    role=params["role"],
                    country=params.get("country") or "pt",
                    cpv_code=params.get("cpv_code") or None,
                    year_from=params.get("year_from"),
                    year_to=params.get("year_to"),
                    region=params.get("region") or None,
                    es=es,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Sem risco de preço no relatório: %s", exc)
    elif modo == "cruzar":
        resultado = bench.benchmark_cross(
            entities=params.get("entities") or [],
            role=params["role"],
            cpv_code=params.get("cpv_code") or None,
            year_from=params.get("year_from"),
            year_to=params.get("year_to"),
            top=20,
            es=es,
        )
    else:
        resultado = bench.benchmark_by_cpv(
            countries=params.get("countries"),
            cpv_code=params.get("cpv_code") or None,
            year_from=params.get("year_from"),
            year_to=params.get("year_to"),
            top=params.get("top") or 40,
            es=es,
        )
    if isinstance(resultado, dict) and resultado.get("error"):
        raise RuntimeError(str(resultado["error"]))
    return resultado


# ------------------------------------------------------------------ formatação
def _moeda(valor: Any) -> str:
    if not isinstance(valor, (int, float)):
        return "—"
    return f"{valor:,.2f} €".replace(",", " ").replace(".", ",")


def _contratos(valor: Any) -> str:
    if not isinstance(valor, (int, float)):
        return "—"
    return f"{valor:,.0f}".replace(",", " ")


def _indice(valor: Any) -> str:
    if not isinstance(valor, (int, float)):
        return "—"
    return f"{valor:.2f}× mediana do mercado"


def _data(valor: Any) -> str:
    texto = str(valor or "")
    return texto[:10] if len(texto) >= 10 else (texto or "—")


def _pct(valor: Any) -> str:
    if not isinstance(valor, (int, float)):
        return "—"
    return f"{valor:.2f} %"


def _papeis(params: Dict[str, Any]) -> tuple[str, str]:
    """(papel da entidade, papel da contraparte) em português."""
    if params.get("role") == bc.SUPPLIER:
        return "vende ao Estado (adjudicatário)", "Quem compra"
    return "compra ao mercado (adjudicante)", "Quem vende"


def _linha_empresa(empresa: Dict[str, Any]) -> List[str]:
    return [
        empresa.get("name") or empresa.get("nif") or "—",
        empresa.get("nif") or "—",
        _contratos(empresa.get("count")),
        _moeda(empresa.get("value")),
        _contratos(empresa.get("rank")),
        _pct(empresa.get("share_pct")),
        _data(empresa.get("last_date")),
    ]


# --------------------------------------------------------------------- secções
def sections(
    params: Dict[str, Any],
    dados: Dict[str, Any],
    *,
    reference: str = "",
    requester: str = "",
) -> List[Dict[str, Any]]:
    """Secções do relatório (matéria-prima do PDF)."""
    modo = params["mode"]
    papel, contraparte = _papeis(params)
    secoes: List[Dict[str, Any]] = []

    # ---------------------------------------------------------- identificação
    if modo == "empresa":
        entidade = dados.get("entity") or {}
        referencia = dados.get("reference") or {}
        identificacao = [
            ["Empresa", entidade.get("name") or params.get("name") or "—"],
            ["NIF / identificador", entidade.get("nif") or params.get("nif") or "—"],
            ["País dos dados", f"{dados.get('country_label') or bc.dialect(params.get('country'))['label']} ({dados.get('country')})"],
            ["Papel analisado", papel],
            ["Segmento", f"CPV {params['cpv_code']}" if params.get("cpv_code") else "todo o mercado filtrado"],
            ["Janela de anos", _janela(params)],
            ["Pedido", reference or "—"],
            ["Requerente", requester or "—"],
        ]
        secoes.append({"title": "Identificação", "rows": identificacao})
        secoes.append(
            {
                "title": "A empresa no mercado",
                "rows": [
                    ["Contratos", _contratos(entidade.get("contracts"))],
                    ["Valor contratado", _moeda(entidade.get("total_value"))],
                    ["Valor médio", _moeda(entidade.get("avg_value"))],
                    ["Mediana da empresa", _moeda(entidade.get("median_value"))],
                    ["Mediana do mercado", _moeda(referencia.get("median"))],
                    ["Índice de preço", _indice(entidade.get("price_index"))],
                    ["Posição no mercado", f"#{entidade.get('rank')}" if entidade.get("rank") else "fora do topo do mercado"],
                    ["Quota de valor", _pct(entidade.get("share_pct"))],
                    ["Quota de contratos", _pct(entidade.get("count_share_pct"))],
                    ["Último contrato", _data(entidade.get("last_date"))],
                ],
            }
        )
        secoes.append(
            {
                "title": "Preço de referência do mercado",
                "rows": [
                    ["Contratos com valor", _contratos(referencia.get("contracts"))],
                    ["Valor total", _moeda(referencia.get("total_value"))],
                    ["Valor médio", _moeda(referencia.get("avg"))],
                    ["Mediana", _moeda(referencia.get("median"))],
                    ["P10", _moeda(referencia.get("p10"))],
                    ["P25", _moeda(referencia.get("p25"))],
                    ["P75", _moeda(referencia.get("p75"))],
                    ["P90", _moeda(referencia.get("p90"))],
                    ["Mínimo", _moeda(referencia.get("min"))],
                    ["Máximo", _moeda(referencia.get("max"))],
                ],
            }
        )
        secoes.append(_seccao_cpvs("Perfil de CPV da empresa", entidade.get("top_cpv") or []))
        secoes.append(
            {
                "title": "Concorrentes no segmento",
                "columns": ["#", "Entidade", "Contratos", "Valor", "Posição", "Quota", "Último contrato"],
                "rows": [
                    [
                        str(linha.get("rank") or indice + 1),
                        linha.get("name") or linha.get("nif") or "—",
                        _contratos(linha.get("count")),
                        _moeda(linha.get("value")),
                        linha.get("rank") or "—",
                        _pct(linha.get("share_pct")),
                        _data(linha.get("last_date")),
                    ]
                    for indice, linha in enumerate((dados.get("competitors") or [])[:MAX_ROWS])
                ],
            }
        )
        secoes.append(
            {
                "title": f"{contraparte} — maiores contrapartes do segmento",
                "columns": ["#", "Entidade", "Contratos", "Valor", "Posição", "Quota", "Último contrato"],
                "rows": [
                    [
                        str(linha.get("rank") or indice + 1),
                        linha.get("name") or linha.get("nif") or "—",
                        _contratos(linha.get("count")),
                        _moeda(linha.get("value")),
                        linha.get("rank") or "—",
                        _pct(linha.get("share_pct")),
                        _data(linha.get("last_date")),
                    ]
                    for indice, linha in enumerate((dados.get("counterparties") or [])[:MAX_ROWS])
                ],
            }
        )
        secoes.append(
            {
                "title": "Historial da empresa (contrapartes já conhecidas)",
                "columns": ["#", "Entidade", "Contratos", "Valor", "Posição", "Quota", "Último contrato"],
                "rows": [
                    [
                        str(linha.get("rank") or indice + 1),
                        linha.get("name") or linha.get("nif") or "—",
                        _contratos(linha.get("count")),
                        _moeda(linha.get("value")),
                        linha.get("rank") or "—",
                        _pct(linha.get("share_pct")),
                        _data(linha.get("last_date")),
                    ]
                    for indice, linha in enumerate((dados.get("history") or [])[:MAX_ROWS])
                ],
            }
        )
        secoes.append(
            {
                "title": f"Oportunidades ({contraparte.lower()} sem contratos com a empresa)",
                "columns": ["Entidade", "Contratos no segmento", "Valor", "Posição", "Último contrato"],
                "rows": [
                    [
                        linha.get("name") or linha.get("nif") or "—",
                        _contratos(linha.get("count")),
                        _moeda(linha.get("value")),
                        linha.get("rank") or "—",
                        _data(linha.get("last_date")),
                    ]
                    for linha in (dados.get("opportunities") or [])[:MAX_ROWS]
                ],
            }
        )
        secoes.append(
            {
                "title": "Contratos recentes",
                "columns": ["Data", "Objeto", "Valor", "Contraparte", "Procedimento"],
                "rows": [
                    [
                        _data(contrato.get("date")),
                        _texto(contrato.get("objecto"), 160) or "—",
                        _moeda(contrato.get("value")),
                        _texto(contrato.get("counterpart"), 80) or "—",
                        contrato.get("procedure") or "—",
                    ]
                    for contrato in (dados.get("recent") or [])[:MAX_ROWS]
                ],
            }
        )
        secoes.extend(_seccoes_preco_por_cpv(dados.get("price_risk")))
        secoes.extend(_seccoes_anomalias(dados.get("anomalies")))
        secoes.extend(_seccoes_oportunidades(dados.get("gaps")))
    elif modo == "mercado":
        secoes.append(
            {
                "title": "Identificação",
                "rows": [
                    ["Âmbito", "Portugal, Espanha e França (por CPV)"],
                    ["Papel analisado", papel],
                    ["Segmento", f"CPV {params['cpv_code']}" if params.get("cpv_code") else "todos os CPV"],
                    ["Janela de anos", _janela(params)],
                    ["Pedido", reference or "—"],
                    ["Requerente", requester or "—"],
                ],
            }
        )
        secoes.append(
            {
                "title": "Totais por país",
                "columns": ["País", "Índice", "Contratos", "Contratos com valor", "Valor", "Mediana do contrato"],
                "rows": [
                    [
                        info.get("label") or info.get("country"),
                        info.get("index") or "—",
                        _contratos(info.get("contracts")),
                        _contratos(info.get("priced_contracts")),
                        _moeda(info.get("total_value")),
                        _moeda(info.get("median")),
                    ]
                    for info in dados.get("countries") or []
                ],
            }
        )
        paises = [info.get("country") for info in dados.get("countries") or []]
        colunas = ["#", "CPV", "Descrição"] + [f"{str(pais).upper()}" for pais in paises] + ["Total"]
        linhas: List[List[str]] = []
        for indice, linha in enumerate((dados.get("items") or [])[:MAX_ROWS]):
            celulas: List[str] = [str(linha.get("rank") or indice + 1), str(linha.get("code") or "—"), _texto(linha.get("description"), 70) or "—"]
            for pais in paises:
                celula = (linha.get("by_country") or {}).get(pais) or {}
                if celula:
                    celulas.append(
                        f"{_contratos(celula.get('contracts'))} · {_moeda(celula.get('value'))} · mediana {_moeda(celula.get('median'))}"
                    )
                else:
                    celulas.append("—")
            celulas.append(f"{_moeda(linha.get('value'))} · {_contratos(linha.get('contracts'))} contratos")
            linhas.append(celulas)
        secoes.append({"title": "CPV por valor contratado", "columns": colunas, "rows": linhas})
    else:  # cruzar
        empresas = dados.get("companies") or []
        secoes.append(
            {
                "title": "Identificação",
                "rows": [
                    ["Âmbito", "empresas de países diferentes, cruzadas por CPV"],
                    ["Papel comum", papel],
                    ["Segmento", f"CPV {params['cpv_code']}" if params.get("cpv_code") else "todo o mercado de cada empresa"],
                    ["Janela de anos", _janela(params)],
                    ["Empresas", "; ".join(f"{e.get('name')} ({str(e.get('country')).upper()})" for e in empresas)],
                    ["Pedido", reference or "—"],
                    ["Requerente", requester or "—"],
                ],
            }
        )
        secoes.append(
            {
                "title": "As empresas no seu próprio mercado",
                "columns": ["País", "Empresa", "NIF/SIRET", "Contratos", "Valor", "Mediana", "Índice de preço", "Posição", "Quota", "Mediana do mercado"],
                "rows": [
                    [
                        str(empresa.get("country") or "").upper(),
                        empresa.get("name") or "—",
                        empresa.get("nif") or "—",
                        _contratos(empresa.get("contracts")),
                        _moeda(empresa.get("total_value")),
                        _moeda(empresa.get("median")),
                        _indice(empresa.get("price_index")),
                        f"#{empresa.get('rank')}" if empresa.get("rank") else "—",
                        _pct(empresa.get("share_pct")),
                        _moeda((empresa.get("market") or {}).get("median")),
                    ]
                    for empresa in empresas
                ],
            }
        )
        comuns = dados.get("shared_cpvs") or []
        if comuns:
            cabecalho = ["CPV", "Descrição"] + [f"{str(empresa.get('country')).upper()} {_texto(empresa.get('name'), 18)}" for empresa in empresas] + ["Total"]
            secoes.append(
                {
                    "title": "CPV em comum",
                    "columns": cabecalho,
                    "rows": [
                        [
                            item.get("code") or "—",
                            _texto(item.get("description"), 60) or "—",
                            *[
                                next(
                                    (
                                        f"{_contratos(parte.get('count'))} · {_moeda(parte.get('value'))}"
                                        for parte in item.get("companies") or []
                                        if parte.get("name") == empresa.get("name") and parte.get("short") == empresa.get("short")
                                    ),
                                    "—",
                                )
                                for empresa in empresas
                            ],
                            f"{_contratos(item.get('contracts'))} · {_moeda(item.get('value'))}",
                        ]
                        for item in comuns[:MAX_ROWS]
                    ],
                }
            )
        contrapartes = dados.get("shared_counterparties") or []
        if contrapartes:
            cabecalho = ["Contraparte"] + [f"{str(empresa.get('country')).upper()} {_texto(empresa.get('name'), 18)}" for empresa in empresas] + ["Total"]
            secoes.append(
                {
                    "title": f"{dados.get('counterparty_label') or 'Contrapartes'} em comum",
                    "columns": cabecalho,
                    "rows": [
                        [
                            item.get("name") or item.get("nif") or "—",
                            *[
                                next(
                                    (
                                        _contratos(parte.get("count"))
                                        for parte in item.get("companies") or []
                                        if parte.get("name") == empresa.get("name") and parte.get("short") == empresa.get("short")
                                    ),
                                    "—",
                                )
                                for empresa in empresas
                            ],
                            f"{_contratos(item.get('contracts'))} · {_moeda(item.get('value'))}",
                        ]
                        for item in contrapartes[:MAX_ROWS]
                    ],
                }
            )
        recentes: List[List[str]] = []
        for empresa in empresas:
            for contrato in (empresa.get("recent") or [])[:6]:
                recentes.append(
                    [
                        str(empresa.get("country") or "").upper(),
                        _texto(empresa.get("name"), 24),
                        _data(contrato.get("date")),
                        _texto(contrato.get("objecto"), 120) or "—",
                        _moeda(contrato.get("value")),
                        _texto(contrato.get("counterpart"), 60) or "—",
                    ]
                )
        if recentes:
            secoes.append(
                {
                    "title": "Contratos recentes das empresas",
                    "columns": ["País", "Empresa", "Data", "Objeto", "Valor", "Contraparte"],
                    "rows": recentes,
                }
            )

    notas = [str(nota) for nota in (dados.get("notes") or []) if str(nota).strip()]
    notas.append(
        "Os preços absolutos não se comparam entre países: compare-se o índice de preço "
        "(mediana da entidade ÷ mediana do mercado dela) e a quota de valor."
    )
    secoes.append({"title": "Como ler este relatório", "rows": [[f"Nota {indice + 1}", nota] for indice, nota in enumerate(notas)]})
    return [seccao for seccao in secoes if seccao.get("rows")]


def _seccao_cpvs(titulo_seccao: str, cpvs: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "title": titulo_seccao,
        "columns": ["CPV", "Descrição", "Contratos", "Valor", "Mediana"],
        "rows": [
            [
                item.get("code") or "—",
                _texto(item.get("description"), 80) or "—",
                _contratos(item.get("count")),
                _moeda(item.get("value")),
                _moeda(item.get("median")),
            ]
            for item in list(cpvs)[:MAX_CPV]
        ],
    }


def _seccoes_preco_por_cpv(risco: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Preço por CPV e ano (eu vs média do mercado) com o risco de cada CPV."""
    if not risco or risco.get("error") or not risco.get("items"):
        return []
    secoes: List[Dict[str, Any]] = []
    achados = (risco.get("summary") or {}).get("items") or []
    if achados:
        secoes.append(
            {
                "title": "Risco de preço (resumo)",
                "columns": ["Severidade", "Leitura", "Detalhe"],
                "rows": [
                    [str(item.get("severity") or "info"), str(item.get("title") or ""), str(item.get("detail") or "")]
                    for item in achados
                ],
            }
        )
    linhas: List[List[str]] = []
    for item in risco["items"]:
        serie = " / ".join(
            f"{ano['year']}:{ano['ratio']:.2f}×" if ano.get("ratio") else f"{ano['year']}:—"
            for ano in (item.get("years") or [])[:6]
        )
        linhas.append(
            [
                item.get("code") or "—",
                _texto(item.get("description"), 56) or "—",
                f"{_contratos(item.get('contracts'))} de {_contratos(item.get('market_contracts'))}",
                _moeda(item.get("avg")),
                _moeda(item.get("market_avg")),
                f"{item['ratio']:.2f}×" if item.get("ratio") else "—",
                _pct(item.get("share_pct")),
                _contratos(item.get("suppliers")),
                serie,
                f"{item.get('risk')} — {_texto(item.get('risk_reason'), 90)}",
            ]
        )
    secoes.append(
        {
            "title": "Preço por CPV e ano (empresa vs mercado)",
            "columns": [
                "CPV",
                "Descrição",
                "Contratos",
                "Média empresa",
                "Média mercado",
                "Rácio",
                "Quota",
                "Concorrentes",
                "Série por ano",
                "Risco",
            ],
            "rows": linhas,
        }
    )
    concorrentes: List[List[str]] = []
    for item in risco["items"]:
        for posicao, linha in enumerate(item.get("competitors") or []):
            concorrentes.append(
                [
                    item.get("code") or "—",
                    str(posicao + 1),
                    _texto(linha.get("name") or linha.get("nif"), 50) or "—",
                    _contratos(linha.get("count")),
                    _moeda(linha.get("value")),
                ]
            )
    if concorrentes:
        secoes.append(
            {
                "title": "Maiores concorrentes por CPV",
                "columns": ["CPV", "#", "Entidade", "Contratos", "Valor"],
                "rows": concorrentes,
            }
        )
    return secoes


def _seccoes_anomalias(anomalias: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Secções das anomalias de preço/concentração (vazio se não houver dados)."""
    if not anomalias or anomalias.get("error"):
        return []
    secoes: List[Dict[str, Any]] = []
    itens = anomalias.get("items") or []
    if itens:
        secoes.append(
            {
                "title": "Sinais de alerta (preço, concentração e qualidade do dado)",
                "columns": ["Severidade", "Sinal", "Explicação"],
                "rows": [
                    [str(item.get("severity") or "info"), str(item.get("title") or ""), str(item.get("detail") or "")]
                    for item in itens
                ],
            }
        )
    if anomalias.get("by_cpv"):
        secoes.append(
            {
                "title": "Preço e concorrência por CPV (empresa vs mercado)",
                "columns": [
                    "CPV",
                    "Descrição",
                    "Contratos",
                    "Quota",
                    "Mediana empresa",
                    "Mediana mercado",
                    "Fornecedores",
                    "Leitura",
                ],
                "rows": [
                    [
                        linha.get("code") or "—",
                        _texto(linha.get("description"), 60) or "—",
                        f"{_contratos(linha.get('contracts'))} de {_contratos(linha.get('market_contracts'))}",
                        _pct(linha.get("share_pct")),
                        _moeda(linha.get("entity_median")),
                        _moeda(linha.get("market_median")),
                        _contratos(linha.get("suppliers")),
                        f"{linha.get('competition_verdict')} / {linha.get('price_verdict')}",
                    ]
                    for linha in anomalias["by_cpv"]
                ],
            }
        )
    if anomalias.get("outliers"):
        secoes.append(
            {
                "title": "Contratos acima do p90 do segmento",
                "columns": ["Data", "Objeto", "Contraparte", "Valor", "×p90"],
                "rows": [
                    [
                        _data(contrato.get("date")),
                        _texto(contrato.get("object"), 120) or "—",
                        _texto(contrato.get("counterpart"), 60) or "—",
                        _moeda(contrato.get("value")),
                        f"{contrato['times_p90']:.1f}×" if contrato.get("times_p90") else "—",
                    ]
                    for contrato in anomalias["outliers"]
                ],
            }
        )
    return secoes


def _seccoes_oportunidades(lacunas: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Secção das oportunidades (CPV dos compradores que a empresa não serve)."""
    if not lacunas or lacunas.get("error") or not lacunas.get("gaps"):
        return []
    papel = "Onde pode vender mais" if lacunas.get("role") == bc.SUPPLIER else "O que pode comprar e ainda não compra"
    return [
        {
            "title": papel,
            "columns": ["CPV", "Descrição", "Valor contratado", "Contratos", "Mediana", "Compradores", "Quem vende ali"],
            "rows": [
                [
                    linha.get("code") or "—",
                    _texto(linha.get("description"), 60) or "—",
                    _moeda(linha.get("value")),
                    _contratos(linha.get("contracts")),
                    _moeda(linha.get("median")),
                    _contratos(linha.get("buyers_total")),
                    ", ".join(_texto(item.get("name") or item.get("nif"), 28) for item in (linha.get("competition") or [])[:2])
                    or "—",
                ]
                for linha in lacunas["gaps"]
            ],
        }
    ]


def _janela(params: Dict[str, Any]) -> str:
    de = params.get("year_from")
    ate = params.get("year_to")
    if de and ate:
        return f"{de}–{ate}" if de != ate else str(de)
    if de:
        return f"desde {de}"
    if ate:
        return f"até {ate}"
    return "todos os anos"


def nome_ficheiro(params: Dict[str, Any], *, reference: str = "") -> str:
    """Nome do PDF (sem acentos, com a referência do pedido)."""
    partes = ["benchmark", str(params.get("mode") or "empresa")]
    if params["mode"] == "empresa":
        partes.append(str(params.get("nif") or params.get("name") or ""))
    elif params["mode"] == "mercado":
        partes.append("pt-es-fr")
    else:
        partes.append(f"{len(params.get('entities') or [])}empresas")
    if params.get("cpv_code"):
        partes.append(f"cpv-{params['cpv_code']}")
    if reference:
        partes.append(str(reference))
    return base.slugify("-".join(partes), fallback="benchmark") + ".pdf"


def render(
    params: Dict[str, Any],
    *,
    reference: str = "",
    requester: str = "",
    es: Any = None,
) -> tuple[str, bytes, str]:
    """Gera o PDF do benchmark: `(nome do ficheiro, bytes, mime)`."""
    limpos = normalise(params)
    dados = build(limpos, es=es)
    secoes = sections(limpos, dados, reference=reference, requester=requester)
    pdf = base.render_pdf(title=titulo(limpos), subtitle=subtitulo(limpos, reference=reference, requester=requester), sections=secoes)
    return nome_ficheiro(limpos, reference=reference), pdf, "application/pdf"


def preview(params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Valida um pedido e descreve o relatório (para a interface mostrar o que vai gerar)."""
    limpos = normalise(params)
    return {
        "mode": limpos["mode"],
        "mode_label": MODES.get(limpos["mode"], "Benchmark"),
        "title": titulo(limpos),
        "subtitle": subtitulo(limpos),
        "params": limpos,
    }
